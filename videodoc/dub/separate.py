"""人声分离：协议 + demucs 实现。

配音要保留背景音乐，就得先把原片的人声剥掉。demucs 的 ``--two-stems=vocals``
正好给两条：``vocals``（原人声，丢掉）和 ``no_vocals``（BGM + 环境声，保留）。

部署注意：demucs 目前装在 workhorse 宿主的独立 venv 里（含 CUDA torch，约 5.4 GB），
没有打进 videodoc 镜像。所以命令路径是可配置的，容器里部署时改成容器内路径即可。
"""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

DEFAULT_MODEL = "htdemucs"
DEFAULT_DEVICE = "cuda"
DEFAULT_TIMEOUT = 900


class SeparationError(RuntimeError):
    """分离失败。调用方可以退回到「不分离」继续跑。"""


class Separator(Protocol):
    name: str

    def split(self, audio: Path, work_dir: Path) -> tuple[Path, Path]:
        """返回 ``(vocals, background)`` 两个 wav 路径。"""
        ...


class DemucsSeparator:
    """调用 demucs 命令行做两轨分离。"""

    name = "demucs"

    def __init__(
        self,
        command: str = "demucs",
        *,
        model: str = DEFAULT_MODEL,
        device: str = DEFAULT_DEVICE,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.command = command
        self.model = model
        self.device = device
        self.timeout = timeout

    def available(self) -> bool:
        return shutil.which(self.command) is not None

    def split(self, audio: Path, work_dir: Path) -> tuple[Path, Path]:
        """先按配置的设备跑；CPU 版 torch 不支持 CUDA 时自动退回 cpu。"""
        if not self.available():
            raise SeparationError(f"找不到 demucs 命令: {self.command}")

        devices = [self.device]
        if self.device != "cpu":
            devices.append("cpu")
        last: SeparationError | None = None
        for device in devices:
            try:
                return self._split_with(audio, work_dir, device)
            except SeparationError as exc:
                last = exc
                # 只有「设备不可用」才换 cpu；其它错误（文件损坏等）直接抛。
                if device == "cpu" or "CUDA" not in str(exc):
                    raise
        raise last or SeparationError("demucs 失败")

    def _split_with(self, audio: Path, work_dir: Path, device: str) -> tuple[Path, Path]:
        out_dir = work_dir / "demucs"
        out_dir.mkdir(parents=True, exist_ok=True)
        args = [
            self.command,
            "--two-stems=vocals",
            "-n", self.model,
            "-d", device,
            "-o", str(out_dir),
            str(audio),
        ]
        try:
            result = subprocess.run(args, capture_output=True, text=True,
                                    timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise SeparationError("demucs 超时") from exc
        if result.returncode != 0:
            tail = (result.stderr or "").strip().splitlines()[-3:]
            raise SeparationError("demucs 失败: " + " / ".join(tail))

        stem = out_dir / self.model / audio.stem
        vocals = stem / "vocals.wav"
        background = stem / "no_vocals.wav"
        if not vocals.is_file() or not background.is_file():
            raise SeparationError(f"demucs 没有产出预期文件: {stem}")
        return vocals, background


class NoSeparator:
    """不分离：原音频整条当背景，用来跑通链路或处理纯音乐视频。"""

    name = "none"

    def split(self, audio: Path, work_dir: Path) -> tuple[Path, Path]:
        empty = work_dir / "silence.wav"
        if not empty.is_file():
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i",
                 "anullsrc=r=44100:cl=stereo", "-t", "1", str(empty)],
                capture_output=True, check=False,
            )
        return empty, audio


class RaySeparator:
    """通过 ray-gpu-control 的 ``demucs`` profile 做分离。

    VideoDoc 容器不装 CUDA torch：把任务写进共享 spool，由 Ray 起 GPU 容器执行，
    再读回结果。协议和 ``ming-tts-web`` 的 ``gpu_dispatch`` 一致：

    * 写 ``<spool>/<job_id>/request.json``
    * ``POST /api/jobs/`` 提交 ``python -m gpu_runner --profile demucs --job-id <id>``
    * 轮询 Ray job 状态，完成后读 ``<spool>/<job_id>/result.json``

    路径映射：VideoDoc 容器的 ``/data`` 与 Ray worker 的 ``/videodoc`` 指向同一个
    宿主目录，所以提交前要把前缀换掉。
    """

    name = "ray"

    def __init__(
        self,
        spool_dir: Path,
        api_url: str,
        *,
        data_prefix: str = "/data",
        remote_prefix: str = "/videodoc",
        timeout: float = DEFAULT_TIMEOUT,
        poll: float = 1.0,
    ) -> None:
        self.spool_dir = Path(spool_dir)
        self.api_url = api_url.rstrip("/")
        self.data_prefix = data_prefix
        self.remote_prefix = remote_prefix
        self.timeout = timeout
        self.poll = poll

    def available(self) -> bool:
        if not self.spool_dir.is_dir():
            return False
        try:
            with urllib.request.urlopen(f"{self.api_url}/api/version", timeout=3) as resp:
                return resp.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def _remote_path(self, path: Path) -> str:
        text = path.as_posix()
        if text.startswith(self.data_prefix + "/"):
            return self.remote_prefix + text[len(self.data_prefix):]
        return text

    def split(self, audio: Path, work_dir: Path) -> tuple[Path, Path]:
        job_id = secrets.token_hex(16)
        job_dir = self.spool_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "request.json").write_text(
            json.dumps({"audio": self._remote_path(audio)}), encoding="utf-8")

        payload = {
            "entrypoint": f"python -m gpu_runner --profile demucs --job-id {job_id}",
            "submission_id": f"demucs-{job_id}",
            "entrypoint_num_gpus": 1,
            "entrypoint_num_cpus": 0.1,
            "metadata": {"profile": "demucs", "job_id": job_id},
        }
        request = urllib.request.Request(
            f"{self.api_url}/api/jobs/",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                body = json.load(resp)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise SeparationError(f"提交 Ray 任务失败: {exc}") from exc

        ray_job = str(body.get("job_id") or f"demucs-{job_id}")
        deadline = time.monotonic() + self.timeout
        while True:
            status = self._status(ray_job)
            if status in ("SUCCEEDED", "FAILED", "STOPPED"):
                break
            if time.monotonic() > deadline:
                raise SeparationError("Ray 分离超时")
            time.sleep(self.poll)

        result_path = job_dir / "result.json"
        if not result_path.is_file():
            raise SeparationError(f"Ray 任务没有产出 result.json（{status}）")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("ok"):
            tail = str(result.get("log") or result.get("error") or "")[-500:]
            raise SeparationError(f"Ray 分离失败: {tail}")
        # worker 返回的是容器内路径（/job/out/...），换回本机的 job 目录
        def local(value: str) -> Path:
            path = Path(value)
            if path.as_posix().startswith("/job/"):
                return job_dir / path.as_posix()[len("/job/"):]
            return path

        vocals = local(str(result["vocals"]))
        background = local(str(result["background"]))
        if not vocals.is_file() or not background.is_file():
            raise SeparationError("Ray 产出的文件不存在")
        return vocals, background

    def _status(self, ray_job: str) -> str:
        try:
            with urllib.request.urlopen(
                f"{self.api_url}/api/jobs/{ray_job}", timeout=10
            ) as resp:
                data = json.load(resp)
            return str(data.get("status") or "UNKNOWN").upper()
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return "UNKNOWN"
