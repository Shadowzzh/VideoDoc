"""取消机制的单测：进程组终止、安全兜底、可中断调用。

这里用真实的子进程（``sys.executable -c 'time.sleep(...)'``）而不是打桩：取消要解决的
正是「信号能不能真的送到子进程」这件事，打桩之后就没有被测对象了。
"""

import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from videodoc.cancellation import (
    CancellationRegistry,
    TaskCancellation,
    TaskCancelled,
    run_interruptible,
)


def spawn_sleeper(*, new_session: bool) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=new_session,
    )


def reap(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def test_terminate_kills_registered_process_group():
    cancel = TaskCancellation("task-1")
    process = spawn_sleeper(new_session=True)
    cancel.register(process)
    try:
        cancel.request()

        terminated = cancel.terminate(grace_seconds=1.0)

        assert terminated == [process.pid]
        process.wait(timeout=5)
        assert process.returncode is not None
    finally:
        reap(process)


def test_signal_group_never_targets_the_service_process_group():
    """兜底防线：子进程没有独立会话时，只杀它自己，不碰服务所在的进程组。

    历史实现里子进程与服务同组，``killpg`` 会把服务一起带走。这个用例如果在未来的
    重构里退化，测试进程本身就会被打死 —— 所以它同时也是一条回归防线。
    """
    process = spawn_sleeper(new_session=False)
    try:
        assert os.getpgid(process.pid) == os.getpgid(0)

        assert TaskCancellation._signal_group(process.pid, signal.SIGTERM) is True

        process.wait(timeout=5)
        assert process.returncode is not None
    finally:
        reap(process)


def test_terminate_is_a_noop_without_processes():
    cancel = TaskCancellation("task-1")
    assert cancel.terminate() == []


def test_sleep_is_interruptible():
    cancel = TaskCancellation("task-1")
    threading.Timer(0.1, cancel.request).start()
    started = time.monotonic()

    with pytest.raises(TaskCancelled):
        cancel.sleep(10)

    assert time.monotonic() - started < 5


def test_request_reports_only_the_first_call():
    cancel = TaskCancellation("task-1")

    assert cancel.request() is True
    assert cancel.request() is False
    assert cancel.requested() is True
    cancel.clear()
    assert cancel.requested() is False


def test_run_interruptible_passes_through_value_without_cancel():
    assert run_interruptible(None, lambda: "ok") == "ok"


def test_run_interruptible_reraises_original_error():
    def boom():
        raise ValueError("bad payload")

    with pytest.raises(ValueError, match="bad payload"):
        run_interruptible(TaskCancellation("task-1"), boom)


def test_run_interruptible_stops_waiting_when_cancelled():
    cancel = TaskCancellation("task-1")
    threading.Timer(0.2, cancel.request).start()
    started = time.monotonic()

    # 被放弃的调用线程是 daemon，会自己跑到超时为止；调用方必须立刻拿到取消信号。
    with pytest.raises(TaskCancelled):
        run_interruptible(cancel, lambda: time.sleep(30))

    assert time.monotonic() - started < 5


def test_registry_reset_replaces_signal_so_resume_is_not_instantly_cancelled():
    registry = CancellationRegistry()
    first = registry.for_task("task-1")
    first.request()

    assert registry.for_task("task-1") is first

    fresh = registry.reset("task-1")

    assert fresh is not first
    assert fresh.requested() is False
    assert registry.get("task-1") is fresh

    registry.discard("task-1")
    assert registry.get("task-1") is None
