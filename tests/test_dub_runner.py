"""断点续跑和 TTS 编排的测试，用假后端避免真的调服务。"""

from __future__ import annotations

from pathlib import Path

import pytest

from videodoc.dub.runner import (
    DubManifest,
    synthesize_all,
    text_hash,
)
from videodoc.dub.tts import TTSError


class FakeTTS:
    """按文本长度造一个假时长，可选地让指定文本失败。"""

    name = "fake"

    def __init__(self, fail_texts: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.fail_texts = fail_texts or set()
        self._jobs: dict[str, str] = {}
        self._counter = 0

    def submit(self, text: str) -> str:
        self.calls.append(text)
        self._counter += 1
        job = f"job-{self._counter}"
        self._jobs[job] = text
        return job

    def fetch(self, job_id: str, out: Path) -> float:
        text = self._jobs[job_id]
        if text in self.fail_texts:
            raise TTSError("boom", retryable=False)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake")
        return round(len(text) * 0.1, 3)


def _units(*texts: str) -> list[dict]:
    return [{"id": f"seg-{i:05d}", "script": t} for i, t in enumerate(texts, 1)]


def test_text_hash_changes_with_text_and_voice():
    a = text_hash("你好", "voice-1")
    assert a == text_hash("你好", "voice-1")
    assert a != text_hash("你好啊", "voice-1")
    assert a != text_hash("你好", "voice-2")
    assert a != text_hash("你好", "voice-1", extra="慢速")


def test_manifest_roundtrip(tmp_path: Path):
    path = tmp_path / "manifest.json"
    m = DubManifest(path, voice="v1")
    wav = tmp_path / "seg-00001.wav"
    wav.write_bytes(b"x")
    m.set_done("seg-00001", "你好", 1.5, wav)

    reloaded = DubManifest(path, voice="v1")
    assert reloaded.cached("seg-00001", "你好") == 1.5
    assert reloaded.summary()["done"] == 1


def test_manifest_invalidates_on_text_change(tmp_path: Path):
    path = tmp_path / "manifest.json"
    m = DubManifest(path, voice="v1")
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    m.set_done("seg-00001", "旧文本", 1.0, wav)

    assert m.cached("seg-00001", "旧文本") == 1.0
    assert m.cached("seg-00001", "新文本") is None


def test_manifest_invalidates_when_file_missing(tmp_path: Path):
    path = tmp_path / "manifest.json"
    m = DubManifest(path, voice="v1")
    wav = tmp_path / "gone.wav"
    wav.write_bytes(b"x")
    m.set_done("seg-00001", "你好", 1.0, wav)
    wav.unlink()

    assert m.cached("seg-00001", "你好") is None


def test_synthesize_all_skips_cached(tmp_path: Path):
    tts = FakeTTS()
    manifest = DubManifest(tmp_path / "m.json", voice="v1")
    units = _units("第一句", "第二句")

    first = synthesize_all(units, tts, manifest, tmp_path / "wav")
    assert len(first) == 2
    assert len(tts.calls) == 2

    second = synthesize_all(units, tts, manifest, tmp_path / "wav")
    assert second == first
    assert len(tts.calls) == 2  # 没有新增调用


def test_synthesize_all_only_reruns_changed(tmp_path: Path):
    tts = FakeTTS()
    manifest = DubManifest(tmp_path / "m.json", voice="v1")
    units = _units("第一句", "第二句")
    synthesize_all(units, tts, manifest, tmp_path / "wav")

    units[1]["script"] = "第二句改过了"
    synthesize_all(units, tts, manifest, tmp_path / "wav")
    assert tts.calls[-1] == "第二句改过了"
    assert len(tts.calls) == 3  # 两次初始 + 一次改动


def test_synthesize_all_records_failure(tmp_path: Path):
    tts = FakeTTS(fail_texts={"坏句子"})
    manifest = DubManifest(tmp_path / "m.json", voice="v1")
    units = _units("好句子", "坏句子")

    durations = synthesize_all(units, tts, manifest, tmp_path / "wav")
    assert "seg-00001" in durations
    assert "seg-00002" not in durations
    summary = manifest.summary()
    assert summary["done"] == 1
    assert summary["failed"] == 1


def test_synthesize_all_resumes_after_failure(tmp_path: Path):
    manifest_path = tmp_path / "m.json"
    units = _units("好句子", "坏句子")

    tts1 = FakeTTS(fail_texts={"坏句子"})
    synthesize_all(units, tts1, DubManifest(manifest_path, voice="v1"), tmp_path / "wav")

    # 第二次：服务恢复，只应该重跑失败的那句
    tts2 = FakeTTS()
    durations = synthesize_all(units, tts2, DubManifest(manifest_path, voice="v1"), tmp_path / "wav")
    assert set(durations) == {"seg-00001", "seg-00002"}
    assert tts2.calls == ["坏句子"]


def test_progress_callback_reports_counts(tmp_path: Path):
    seen: list[tuple[int, int]] = []
    tts = FakeTTS()
    manifest = DubManifest(tmp_path / "m.json", voice="v1")
    synthesize_all(
        _units("一", "二", "三"), tts, manifest, tmp_path / "wav",
        on_progress=lambda done, total, _msg: seen.append((done, total)),
    )
    assert seen[0] == (0, 3)
    assert seen[-1][0] == 3
