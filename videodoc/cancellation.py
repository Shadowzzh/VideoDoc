"""任务取消：把「终止正在运行的流水线」变成可重入、可观测的操作。

三条设计约束（2026-10-15，来自实测）：

1. **子进程必须自成一个进程组。** 流水线原先直接 ``subprocess.Popen(...)``，子进程
   继承服务的进程组；实测 ``pgid`` 等于服务 PID，此时 ``killpg`` 会把服务自己一起
   杀掉。所有外部命令改由 ``pipeline._run_command`` 以 ``start_new_session=True``
   启动，取消时只对那个新会话开枪。
2. **取消是协作式的。** HTTP 线程负责置信号并杀进程，流水线线程在自己的检查点、
   或子进程退出之后自行停下 —— Python 没有安全的手段强杀线程。因此「取消后不再写
   完成状态」由流水线自己在检查点保证，而不是靠外部打断。
3. **已生成的产物一律保留。** 取消只改状态，不删文件；上游阶段产物因此可以直接复用。

已知边界：Whisper 走 pywhispercpp 时是**同进程内的 C 调用**，没有可中断接口，
取消要等该阶段结束才生效（抽帧、下载、音频提取都是子进程，可立即终止）。
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from typing import Any, Callable


class TaskCancelled(RuntimeError):
    """任务被用户取消。

    与 ``PipelineError``（失败）刻意区分：取消不是错误，不该把任务标成 ``failed``，
    也不该把「用户终止」写进 ``error`` 让页面弹失败横幅。
    """

    def __init__(self, message: str = "任务已被用户取消。"):
        super().__init__(message)


class TaskCancellation:
    """单个任务的取消信号，以及它当前启动的子进程。

    一个任务一个实例，由 ``CancellationRegistry`` 持有；HTTP 层和流水线线程拿到的是
    同一个对象，所以「谁在跑」和「谁要停」不需要额外的跨线程通道。
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self._event = threading.Event()
        self._processes: dict[int, subprocess.Popen] = {}
        self._lock = threading.Lock()

    # ---- 取消信号 ----

    def requested(self) -> bool:
        return self._event.is_set()

    def request(self) -> bool:
        """置位取消信号；返回是否是本次调用首次置位。"""
        if self._event.is_set():
            return False
        self._event.set()
        return True

    def clear(self) -> None:
        """清掉取消信号（任务被重新排队继续时用）。"""
        self._event.clear()

    def raise_if_requested(self) -> None:
        if self._event.is_set():
            raise TaskCancelled()

    def sleep(self, seconds: float) -> None:
        """可被取消打断的 sleep；取消时立刻抛 ``TaskCancelled``。"""
        if self._event.wait(timeout=seconds):
            raise TaskCancelled()

    # ---- 子进程登记 ----

    def register(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._processes[process.pid] = process

    def unregister(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._processes.pop(process.pid, None)

    def live_processes(self) -> list[int]:
        """仍在运行的子进程 PID。"""
        with self._lock:
            items = list(self._processes.items())
        return [pid for pid, process in items if process.poll() is None]

    def terminate(self, grace_seconds: float = 3.0) -> list[int]:
        """先 SIGTERM、宽限期后 SIGKILL，终止所有已登记子进程所在的进程组。

        返回被发过信号的 PID（用于日志和测试断言）。宽限期是必要的：ffmpeg 收到
        SIGTERM 会做收尾，直接 SIGKILL 会留下写了一半的文件。
        """
        targets = self.live_processes()
        if not targets:
            return []
        signalled: list[int] = []
        for pid in targets:
            if self._signal_group(pid, signal.SIGTERM):
                signalled.append(pid)
        deadline = time.monotonic() + max(0.0, grace_seconds)
        pending = targets
        while pending and time.monotonic() < deadline:
            time.sleep(0.1)
            with self._lock:
                pending = [
                    pid for pid, process in self._processes.items() if process.poll() is None
                ]
        for pid in pending:
            self._signal_group(pid, signal.SIGKILL)
        return signalled

    @staticmethod
    def _signal_group(pid: int, sig: int) -> bool:
        """向子进程所在的进程组发信号，但绝不对服务自己的进程组开枪。

        第二道防线：即使将来有调用方忘了 ``start_new_session=True``，这里也只会杀掉
        那个子进程本身，而不会把整个服务带走。
        """
        try:
            group = os.getpgid(pid)
        except (ProcessLookupError, PermissionError):
            return False
        if group == os.getpgid(0):
            try:
                os.kill(pid, sig)
                return True
            except (ProcessLookupError, PermissionError):
                return False
        try:
            os.killpg(group, sig)
            return True
        except (ProcessLookupError, PermissionError):
            return False


class CancellationRegistry:
    """按任务保存取消信号；服务层与流水线通过它共享同一个对象。"""

    def __init__(self) -> None:
        self._items: dict[str, TaskCancellation] = {}
        self._lock = threading.Lock()

    def for_task(self, task_id: str) -> TaskCancellation:
        with self._lock:
            return self._items.setdefault(task_id, TaskCancellation(task_id))

    def get(self, task_id: str) -> TaskCancellation | None:
        with self._lock:
            return self._items.get(task_id)

    def reset(self, task_id: str) -> TaskCancellation:
        """换一个新的取消信号（任务被重新排队继续时用）。

        必须换新实例而不是 ``clear()``：上一次取消可能留下还没结束的 daemon 调用线程，
        它仍然持有旧对象；沿用旧对象会让新的一次执行刚起步就再次判定为「已取消」。
        """
        with self._lock:
            fresh = TaskCancellation(task_id)
            self._items[task_id] = fresh
            return fresh

    def discard(self, task_id: str) -> None:
        with self._lock:
            self._items.pop(task_id, None)


def run_interruptible(
    cancel: TaskCancellation | None,
    call: Callable[[], Any],
    poll_interval: float = 0.2,
) -> Any:
    """在后台线程里执行 ``call()``，期间可被取消打断。

    为什么需要：``urllib`` 的阻塞读（模型等待最长 600 秒）没有可中断接口，直接调用
    时取消要等它自己超时才生效 —— 用户体验上等于「点了没反应」。这里把阻塞调用放到
    daemon 线程里，调用方每 ``poll_interval`` 秒检查一次取消信号，取消时立刻抛
    ``TaskCancelled`` 返回。

    代价：被放弃的线程会继续跑到它自己的超时为止（上限就是调用方设置的 timeout）。
    它只写自己的局部结果，不碰任务状态文件，因此不会出现「取消后又被写回完成状态」。
    """
    if cancel is None:
        return call()
    outcome: dict[str, Any] = {}

    def worker() -> None:
        try:
            outcome["value"] = call()
        except BaseException as error:  # 原样带回调用线程重新抛出，保留异常类型
            outcome["error"] = error

    thread = threading.Thread(
        target=worker,
        name=f"videodoc-call-{cancel.task_id}",
        daemon=True,
    )
    thread.start()
    while thread.is_alive():
        if cancel.requested():
            raise TaskCancelled()
        thread.join(poll_interval)
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")
