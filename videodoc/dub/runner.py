"""配音编排：批量合成、断点续跑、缓存清单。

长视频要跑几十分钟，中途挂掉不能从头再来。所以每合成一句就落盘一份
``manifest.json``，用「文本哈希」判断要不要重跑：

* 文本没变 → 直接复用 wav，0 秒
* 改了 tone / 重写了某句 → 只有那几句 hash 变，其余复用
* 上次失败的 → 重跑失败的，跳过已完成的
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from .tts import TTSError, TTSBackend

MANIFEST_VERSION = 1
# 每批提交多少条。Ming 的队列上限实测约 13，留余量避免 429。
BATCH_SIZE = 8
# 单句最多尝试次数（一次失败可能重新提交）。
MAX_ATTEMPTS = 3


def text_hash(text: str, voice: str, extra: str = "") -> str:
    """缓存键：文本 + 声音 + 额外参数（语速等）。"""
    raw = f"{voice}|{extra}|{text}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


class DubManifest:
    """配音缓存清单。所有写操作立即落盘，保证崩溃后能续跑。"""

    def __init__(self, path: Path, voice: str = "", extra: str = "") -> None:
        self.path = path
        self.voice = voice
        self.extra = extra
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("version") == MANIFEST_VERSION:
                    data.setdefault("segments", {})
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return {"version": MANIFEST_VERSION, "voice": self.voice,
                "extra": self.extra, "segments": {}}

    def save(self) -> None:
        """原子写：先写临时文件再替换，避免半个 JSON。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self.path)

    # -- 查询与更新 ------------------------------------------------------

    def segments(self) -> dict[str, dict[str, Any]]:
        return self.data["segments"]

    def cached(self, key: str, text: str) -> float | None:
        """命中缓存时返回时长，否则 None。"""
        entry = self.segments().get(key)
        if not entry or entry.get("status") != "done":
            return None
        if entry.get("hash") != text_hash(text, self.voice, self.extra):
            return None
        if not Path(entry.get("file") or "").is_file():
            return None
        return float(entry.get("duration") or 0)

    def set_done(self, key: str, text: str, duration: float, file: Path) -> None:
        self.segments()[key] = {
            "status": "done",
            "hash": text_hash(text, self.voice, self.extra),
            "duration": round(duration, 3),
            "file": str(file),
            "updated_at": int(time.time()),
        }
        self.save()

    def set_failed(self, key: str, error: str, attempts: int) -> None:
        self.segments()[key] = {
            "status": "failed",
            "error": str(error)[:300],
            "attempts": attempts,
            "updated_at": int(time.time()),
        }
        self.save()

    def summary(self) -> dict[str, int]:
        segs = self.segments()
        return {
            "total": len(segs),
            "done": sum(1 for s in segs.values() if s.get("status") == "done"),
            "failed": sum(1 for s in segs.values() if s.get("status") == "failed"),
        }


def _batches(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def synthesize_all(
    units: list[dict[str, Any]],
    tts: TTSBackend,
    manifest: DubManifest,
    wav_dir: Path,
    *,
    batch_size: int = BATCH_SIZE,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, float]:
    """把所有单元合成一遍，跳过缓存命中的。

    ``units`` 每项需要 ``id`` 和 ``script``。返回 ``{id: 实际时长}``；失败的单元
    不出现在结果里，由调用方按 overflow 处理。
    """
    wav_dir.mkdir(parents=True, exist_ok=True)
    durations: dict[str, float] = {}
    todo: list[dict[str, Any]] = []

    for unit in units:
        key = str(unit["id"])
        text = str(unit.get("script") or "")
        hit = manifest.cached(key, text)
        if hit is not None:
            durations[key] = hit
        else:
            todo.append(unit)

    total = len(units)
    if on_progress:
        on_progress(len(durations), total, f"缓存命中 {len(durations)} 段")

    for chunk in _batches(todo, batch_size):
        jobs: list[tuple[dict[str, Any], str]] = []
        for unit in chunk:
            key = str(unit["id"])
            text = str(unit.get("script") or "")
            try:
                jobs.append((unit, tts.submit(text)))
            except TTSError as exc:
                manifest.set_failed(key, str(exc), 1)
                if on_progress:
                    on_progress(len(durations), total, f"{key} 提交失败")

        for unit, job_id in jobs:
            key = str(unit["id"])
            text = str(unit.get("script") or "")
            out = wav_dir / f"{key}.wav"
            last_error = ""
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    duration = tts.fetch(job_id, out)
                    manifest.set_done(key, text, duration, out)
                    durations[key] = duration
                    break
                except TTSError as exc:
                    last_error = str(exc)
                    if not exc.retryable or attempt == MAX_ATTEMPTS:
                        manifest.set_failed(key, last_error, attempt)
                        break
                    # 重新提交一次再等（原 job 可能已失效）
                    try:
                        job_id = tts.submit(text)
                    except TTSError as submit_exc:
                        last_error = str(submit_exc)
            if on_progress:
                done = len(durations)
                on_progress(done, total, f"已合成 {done}/{total}")

    return durations
