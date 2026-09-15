"""转写适配层单元测试：不加载真实模型。"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from videodoc.integrations import transcribe as transcribe_module
from videodoc.integrations.transcribe import (
    TranscribeError,
    format_srt_timestamp,
    language,
    model_reference,
    thread_count,
    to_pipeline_segments,
    transcribe,
    write_srt,
    write_text,
)


@pytest.fixture()
def audio(tmp_path: Path) -> Path:
    path = tmp_path / "audio" / "transcript.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"wav")
    return path


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "VIDEODOC_WHISPER_BIN",
        "VIDEODOC_WHISPER_MODEL",
        "VIDEODOC_WHISPER_MODEL_DIR",
        "VIDEODOC_WHISPER_LANGUAGE",
        "VIDEODOC_WHISPER_THREADS",
    ):
        monkeypatch.delenv(name, raising=False)


def fake_pywhispercpp(monkeypatch: pytest.MonkeyPatch, raw_segments: list) -> dict:
    """把 pywhispercpp 的 Model 换成假实现，记录调用参数。"""
    recorded: dict = {}

    class FakeModel:
        def __init__(self, **kwargs) -> None:
            recorded["init"] = kwargs

        def transcribe(self, media: str, **kwargs):
            recorded["transcribe"] = {"media": media, **kwargs}
            return raw_segments

    module = types.ModuleType("pywhispercpp.model")
    module.Model = FakeModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pywhispercpp.model", module)
    return recorded


def test_format_srt_timestamp() -> None:
    assert format_srt_timestamp(0) == "00:00:00,000"
    assert format_srt_timestamp(4.16) == "00:00:04,160"
    assert format_srt_timestamp(3661.5) == "01:01:01,500"


def test_to_pipeline_segments_converts_centiseconds_to_seconds() -> None:
    raw = [
        SimpleNamespace(t0=16, t1=416, text=" Hello "),
        SimpleNamespace(t0=472, t1=824, text="World"),
    ]
    segments = to_pipeline_segments(raw)
    assert [s["id"] for s in segments] == ["seg-00001", "seg-00002"]
    assert segments[0]["start_sec"] == pytest.approx(0.16)
    assert segments[0]["end_sec"] == pytest.approx(4.16)
    assert segments[0]["text"] == "Hello"


def test_to_pipeline_segments_skips_empty_text() -> None:
    raw = [
        SimpleNamespace(t0=0, t1=100, text="   "),
        SimpleNamespace(t0=100, t1=200, text="kept"),
    ]
    segments = to_pipeline_segments(raw)
    assert len(segments) == 1
    # id 必须按保留后的顺序连续编号
    assert segments[0]["id"] == "seg-00001"
    assert segments[0]["text"] == "kept"


def test_write_srt_round_trips_through_parser(tmp_path: Path) -> None:
    segments = [
        {"id": "seg-00001", "start_sec": 0.16, "end_sec": 4.16, "text": "第一句"},
        {"id": "seg-00002", "start_sec": 4.72, "end_sec": 8.24, "text": "second line"},
    ]
    path = tmp_path / "transcript.srt"
    write_srt(segments, path)
    text = path.read_text(encoding="utf-8")
    assert "00:00:00,160 --> 00:00:04,160" in text
    assert "00:00:04,720 --> 00:00:08,240" in text
    assert transcribe_module.parse_srt(text) == segments


def test_write_text_joins_lines(tmp_path: Path) -> None:
    segments = [
        {"id": "seg-00001", "start_sec": 0, "end_sec": 1, "text": "a"},
        {"id": "seg-00002", "start_sec": 1, "end_sec": 2, "text": "b"},
    ]
    path = tmp_path / "transcript.txt"
    write_text(segments, path)
    assert path.read_text(encoding="utf-8") == "a\nb\n"


def test_environment_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    assert model_reference() == "large-v3-turbo"
    # "auto" 要映射成「不传参」，否则 whisper.cpp 会打一条无用的告警
    assert language() is None
    monkeypatch.setenv("VIDEODOC_WHISPER_LANGUAGE", "zh")
    assert language() == "zh"
    monkeypatch.setenv("VIDEODOC_WHISPER_MODEL", "/models/ggml-custom.bin")
    assert model_reference() == "/models/ggml-custom.bin"


def test_thread_count_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEODOC_WHISPER_THREADS", "3")
    assert thread_count() == 3
    monkeypatch.setenv("VIDEODOC_WHISPER_THREADS", "0")
    assert thread_count() >= 1
    monkeypatch.setenv("VIDEODOC_WHISPER_THREADS", "abc")
    assert thread_count() >= 1


def test_transcribe_uses_pywhispercpp_and_writes_artifacts(
    tmp_path: Path, audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = fake_pywhispercpp(
        monkeypatch,
        [SimpleNamespace(t0=16, t1=416, text=" Hello world ")],
    )
    monkeypatch.setenv("VIDEODOC_WHISPER_MODEL", "/models/local.bin")
    monkeypatch.setenv("VIDEODOC_WHISPER_LANGUAGE", "zh")

    transcript_dir = tmp_path / "transcript"
    segments = transcribe(audio, transcript_dir)

    assert segments == [
        {
            "id": "seg-00001",
            "start_sec": pytest.approx(0.16),
            "end_sec": pytest.approx(4.16),
            "text": "Hello world",
        }
    ]
    assert (transcript_dir / "transcript.srt").is_file()
    assert (transcript_dir / "transcript.txt").read_text(encoding="utf-8") == "Hello world\n"
    assert recorded["init"]["model"] == "/models/local.bin"
    assert recorded["transcribe"]["language"] == "zh"


def test_transcribe_omits_language_when_auto(
    tmp_path: Path, audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = fake_pywhispercpp(
        monkeypatch, [SimpleNamespace(t0=0, t1=100, text="x")]
    )
    transcribe(audio, tmp_path / "transcript")
    assert recorded["transcribe"]["language"] is None


def test_transcribe_uses_cli_when_binary_override_set(
    tmp_path: Path, audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "fake-whisper"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("VIDEODOC_WHISPER_BIN", str(binary))

    seen: dict = {}

    def runner(command: list[str], env: dict[str, str]) -> None:
        seen["command"] = command
        prefix = Path(command[command.index("-of") + 1])
        prefix.with_suffix(".srt").write_text(
            "1\n00:00:00,000 --> 00:00:02,000\n来自 CLI\n", encoding="utf-8"
        )
        prefix.with_suffix(".txt").write_text("来自 CLI\n", encoding="utf-8")

    segments = transcribe(audio, tmp_path / "transcript", runner=runner)

    assert seen["command"][0] == str(binary)
    assert seen["command"][2:4] == ["-of", str(tmp_path / "transcript" / "transcript")]
    assert segments[0]["text"] == "来自 CLI"
    assert segments[0]["end_sec"] == pytest.approx(2.0)
    assert (tmp_path / "transcript" / "transcript.srt").is_file()


def test_transcribe_reports_missing_cli_binary(
    tmp_path: Path, audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIDEODOC_WHISPER_BIN", "/nonexistent/whisper")
    with pytest.raises(TranscribeError, match="找不到 whisper 可执行文件"):
        transcribe(audio, tmp_path / "transcript")


def test_transcribe_rejects_missing_audio(tmp_path: Path) -> None:
    with pytest.raises(TranscribeError, match="找不到待转写的音频"):
        transcribe(tmp_path / "missing.wav", tmp_path / "transcript")


def test_transcribe_rejects_empty_result(
    tmp_path: Path, audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pywhispercpp(monkeypatch, [SimpleNamespace(t0=0, t1=100, text="   ")])
    with pytest.raises(TranscribeError, match="没有识别出任何语音片段"):
        transcribe(audio, tmp_path / "transcript")


def test_transcribe_reports_missing_dependency(
    tmp_path: Path, audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pywhispercpp 缺失时要给出可操作的提示，而不是裸 ImportError。"""
    monkeypatch.setitem(sys.modules, "pywhispercpp.model", None)
    with pytest.raises(TranscribeError):
        transcribe(audio, tmp_path / "transcript")


def test_json_segments_are_serializable(
    tmp_path: Path, audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pywhispercpp(monkeypatch, [SimpleNamespace(t0=16, t1=416, text="hi")])
    segments = transcribe(audio, tmp_path / "transcript")
    # 流水线会把 segments 原子写成 segments.json，必须是纯 JSON 类型
    assert json.loads(json.dumps(segments)) == segments
