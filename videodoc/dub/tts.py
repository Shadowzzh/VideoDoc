"""TTS 后端：协议 + Ming 实现。

只有两个方法要满足：``submit`` 提交一条文本、``fetch`` 等它完成并落盘。
批量调度和重试策略在 ``runner`` 里，这里只管单条的生命周期。

Ming 的接口是异步的（202 + 轮询），所以 ``submit`` 返回 job id，``fetch``
负责轮询到终态、下载 wav、用 ffprobe 量出真实时长。
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol

DEFAULT_TIMEOUT = 90
DEFAULT_POLL = 1.0
# 服务端队列满了会返回 429；退避后重试，仍失败才让上层记 failed。
RETRY_STATUSES = {429, 503}
BACKOFF_SECONDS = (2, 4, 8)


class TTSError(RuntimeError):
    """合成失败，``retryable`` 表示值不值得再试一次。"""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class TTSBackend(Protocol):
    """任何 TTS 后端只要实现这两个方法就能接进来。"""

    name: str

    def submit(self, text: str) -> str: ...

    def fetch(self, job_id: str, out: Path) -> float:
        """等任务完成，把音频写到 ``out``，返回秒数。"""
        ...


def probe_duration(path: Path) -> float:
    """用 ffprobe 量音频时长；失败返回 0，让上层按 overflow 处理。"""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return round(float(result.stdout.strip()), 3)
    except ValueError:
        return 0.0


class MingTTS:
    """ming-tts-web 的 HTTP 客户端（zero-shot / clone 都走同一个 /api/jobs）。"""

    name = "ming"

    def __init__(
        self,
        base_url: str,
        voice_id: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        poll: float = DEFAULT_POLL,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.voice_id = voice_id
        self.timeout = timeout
        self.poll = poll

    # -- HTTP -----------------------------------------------------------

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        req = urllib.request.Request(
            self.base_url + path, data=data, headers=headers,
            method="POST" if data else "GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            retryable = exc.code in RETRY_STATUSES
            raise TTSError(f"HTTP {exc.code} {path}", retryable=retryable) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TTSError(f"连接失败 {path}: {exc}", retryable=True) from exc

    def submit(self, text: str) -> str:
        """提交一条合成任务，返回 job id。429 时按退避重试。"""
        payload = {"voice_id": self.voice_id, "text": text}
        last: TTSError | None = None
        for delay in (0,) + BACKOFF_SECONDS:
            if delay:
                time.sleep(delay)
            try:
                job = self._request("/api/jobs", payload)
                return str(job["id"])
            except TTSError as exc:
                last = exc
                if not exc.retryable:
                    raise
        raise last or TTSError("提交失败")

    def fetch(self, job_id: str, out: Path) -> float:
        """轮询到终态并下载音频。"""
        deadline = time.monotonic() + self.timeout
        while True:
            job = self._request(f"/api/jobs/{job_id}")
            status = str(job.get("status") or "")
            if status not in ("queued", "running", "preparing", "synthesizing"):
                break
            if time.monotonic() > deadline:
                raise TTSError(f"合成超时 {job_id}", retryable=True)
            time.sleep(self.poll)

        filename = job.get("filename")
        if not filename:
            raise TTSError(f"合成失败 {job_id}: {job.get('error') or status}",
                           retryable=status != "failed")

        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".part")
        try:
            with urllib.request.urlopen(
                f"{self.base_url}/api/audio/{filename}", timeout=self.timeout
            ) as resp, open(tmp, "wb") as fh:
                fh.write(resp.read())
        except (urllib.error.URLError, TimeoutError) as exc:
            tmp.unlink(missing_ok=True)
            raise TTSError(f"下载音频失败: {exc}", retryable=True) from exc
        tmp.replace(out)

        duration = probe_duration(out)
        if duration <= 0:
            out.unlink(missing_ok=True)
            raise TTSError("音频时长无效", retryable=True)
        return duration

    def synthesize(self, text: str, out: Path) -> float:
        """提交 + 等待 + 落盘，一步到位。"""
        return self.fetch(self.submit(text), out)
