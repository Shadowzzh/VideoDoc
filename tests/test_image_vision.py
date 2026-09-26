"""图像识别能力单测：通道解析、两条通道并行、每日预算、失败降级、证据文本。"""

import json

import pytest

from videodoc import settings as st
from videodoc.capabilities import image_vision, registry
from videodoc.integrations import vision_local, vision_remote


@pytest.fixture()
def local_ready(tmp_path, monkeypatch):
    """让本地通道“可用”：假装有 swift，并给一个存在的脚本路径。"""
    script = tmp_path / "vision_ocr.swift"
    script.write_text("// stub", encoding="utf-8")
    monkeypatch.setattr(vision_local.shutil, "which", lambda name: "/usr/bin/swift")
    return {"local": {"enabled": True, "script": str(script)}}


@pytest.fixture()
def remote_ready():
    return {
        "external": {
            "protocol": "openai-chat",
            "base_url": "http://127.0.0.1:3006/v1",
            "model": "gemini-3.5-flash-lite",
            "api_key": "k-abcd1234",
            "max_frames": 4,
            "daily_budget": 10,
        }
    }


def _settings(*overrides):
    merged = image_vision.defaults()
    for item in overrides:
        merged = st.deep_merge(merged, item)
    return merged


def _task_dir(tmp_path):
    target = tmp_path / "tasks" / "t1"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _run(settings, images, tmp_path, logs=None):
    logs = logs if logs is not None else []
    return image_vision.image_vision.run(
        settings,
        images,
        frame_dir=tmp_path,
        log=logs.append,
        task_dir=_task_dir(tmp_path),
    )


# ---------------------------------------------------------------- 注册表


def test_capability_is_registered_with_its_step_and_artifact():
    capability = registry.by_step("ocr")

    assert capability is not None
    assert capability.key == "image_vision"
    assert capability.artifact() == ("ocr", "ocr.json")
    spec = capability.step()
    assert spec.key == "ocr"
    assert spec.after == "select_images"


def test_schema_declares_settings_page_fields():
    groups = image_vision.image_vision.groups()
    titles = [group.title for group in groups]
    keys = [item.key for group in groups for item in group.fields]

    assert titles == ["识别通道", "本地（macOS Vision）", "云端（视觉模型理解）", "预算与重试"]
    assert "engine" in keys
    assert "external.base_url" in keys
    assert "external.api_key" in keys
    assert "external.max_frames" in keys
    secret = [item for group in groups for item in group.fields if item.key == "external.api_key"]
    assert secret and secret[0].secret is True


# ---------------------------------------------------------------- 通道解析


def test_resolve_engine_auto_without_any_channel(monkeypatch):
    monkeypatch.setattr(vision_local.shutil, "which", lambda name: None)

    resolved = image_vision.resolve_engine(_settings())

    assert resolved.engine is None
    assert "swift" in resolved.local_reason
    assert "BaseURL" in resolved.external_reason


def test_resolve_engine_auto_prefers_both(local_ready, remote_ready, monkeypatch):
    monkeypatch.setattr(vision_local.shutil, "which", lambda name: "/usr/bin/swift")

    assert image_vision.resolve_engine(_settings(local_ready, remote_ready)).engine == "both"


def test_resolve_engine_auto_falls_back_to_local(local_ready, monkeypatch):
    monkeypatch.setattr(vision_local.shutil, "which", lambda name: "/usr/bin/swift")

    assert image_vision.resolve_engine(_settings(local_ready)).engine == "local"


def test_resolve_engine_auto_falls_back_to_external(remote_ready):
    settings = _settings(remote_ready, {"local": {"enabled": False}})

    assert image_vision.resolve_engine(settings).engine == "external"


def test_resolve_engine_explicit_local_requires_swift(monkeypatch):
    monkeypatch.setattr(vision_local.shutil, "which", lambda name: None)

    assert image_vision.resolve_engine(_settings({"engine": "local"})).engine is None


def test_resolve_engine_explicit_external_requires_configuration():
    resolved = image_vision.resolve_engine(_settings({"engine": "external"}))

    assert resolved.engine is None
    assert "BaseURL" in resolved.external_reason


def test_resolve_engine_both_with_only_external_configured(remote_ready):
    settings = _settings(remote_ready, {"engine": "both", "local": {"enabled": False}})

    assert image_vision.resolve_engine(settings).engine == "external"


def test_resolve_engine_reports_missing_key(monkeypatch):
    monkeypatch.delenv("VIDEODOC_VISION_API_KEY", raising=False)
    settings = _settings({"external": {"base_url": "http://h/v1", "model": "m", "api_key": ""}})

    assert "Key" in image_vision.resolve_engine(settings).external_reason


def test_describe_mentions_both_channels(local_ready, remote_ready, monkeypatch):
    monkeypatch.setattr(vision_local.shutil, "which", lambda name: "/usr/bin/swift")

    described = image_vision.image_vision.describe(_settings(local_ready, remote_ready))

    assert "swift" in described
    assert "/responses" in described or "/chat/completions" in described


# ---------------------------------------------------------------- 执行


def test_run_fills_both_channels_and_consumes_quota(local_ready, remote_ready, tmp_path, monkeypatch):
    monkeypatch.setattr(vision_local.shutil, "which", lambda name: "/usr/bin/swift")
    monkeypatch.setattr(vision_local, "recognize", lambda config, path: "画面文字\t0.10\t0.20")
    monkeypatch.setattr(
        vision_remote,
        "analyze",
        lambda config, prompt, path: {"text": "画面是 K 线图", "model": "m1", "usage": {}, "elapsed_ms": 12},
    )
    images = [{"file": "a.jpg", "timestamp": "00:01"}, {"file": "b.jpg", "timestamp": "00:02"}]
    logs: list[str] = []

    evidence = _run(_settings(local_ready, remote_ready), images, tmp_path, logs)

    assert [image["ocr_text"] for image in evidence.images] == ["画面文字\t0.10\t0.20"] * 2
    assert [image["vision_text"] for image in evidence.images] == ["画面是 K 线图"] * 2
    assert evidence.images[0]["ocr_provider"] == "macos-vision"
    assert evidence.images[0]["vision_provider"] == "openai-chat:m1"
    assert set(evidence.texts) == {"a.jpg", "b.jpg"}
    quota = json.loads((tmp_path / "vision-quota.json").read_text(encoding="utf-8"))
    assert quota["used"] == 2
    assert any("云端视觉完成 2 张" in line for line in logs)


def test_run_local_only_leaves_cloud_fields_absent(local_ready, tmp_path, monkeypatch):
    monkeypatch.setattr(vision_local.shutil, "which", lambda name: "/usr/bin/swift")
    monkeypatch.setattr(vision_local, "recognize", lambda config, path: "只有本地文字")

    evidence = _run(_settings(local_ready), [{"file": "a.jpg"}], tmp_path)

    assert evidence.images[0]["ocr_text"] == "只有本地文字"
    assert "vision_text" not in evidence.images[0]


def test_run_marks_local_failure_without_stopping(remote_ready, tmp_path, monkeypatch):
    def boom(config, path):
        raise vision_local.LocalVisionError("OCR 超过 120 秒。")

    monkeypatch.setattr(vision_local.shutil, "which", lambda name: "/usr/bin/swift")
    monkeypatch.setattr(vision_local, "recognize", boom)
    monkeypatch.setattr(
        vision_remote,
        "analyze",
        lambda config, prompt, path: {"text": "云端仍然成功", "model": "m", "usage": {}, "elapsed_ms": 1},
    )
    script = tmp_path / "vision_ocr.swift"
    script.write_text("// stub", encoding="utf-8")
    settings = _settings(remote_ready, {"local": {"script": str(script)}})

    evidence = _run(settings, [{"file": "a.jpg"}], tmp_path)

    assert "超过 120 秒" in evidence.images[0]["ocr_error"]
    assert evidence.images[0]["vision_text"] == "云端仍然成功"


def test_run_marks_cloud_failure_without_stopping(remote_ready, tmp_path, monkeypatch):
    def boom(config, prompt, path):
        raise vision_remote.RemoteVisionError("HTTP 500: 上游挂了")

    monkeypatch.setattr(vision_remote, "analyze", boom)

    evidence = _run(_settings(remote_ready), [{"file": "a.jpg"}], tmp_path)

    assert "HTTP 500" in evidence.images[0]["vision_error"]
    assert "ocr_text" not in evidence.images[0]


def test_run_respects_daily_budget(remote_ready, tmp_path, monkeypatch):
    monkeypatch.setattr(
        vision_remote,
        "analyze",
        lambda config, prompt, path: {"text": "x", "model": "m", "usage": {}, "elapsed_ms": 1},
    )
    settings = _settings(remote_ready, {"external": {"daily_budget": 0}})
    logs: list[str] = []

    evidence = _run(settings, [{"file": "a.jpg"}], tmp_path, logs)

    assert evidence.images[0]["vision_error"] == "今日云端图像识别预算已用完。"
    assert any("预算" in line for line in logs)


def test_run_respects_max_frames(remote_ready, tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_analyze(config, prompt, path):
        calls["n"] += 1
        return {"text": "x", "model": "m", "usage": {}, "elapsed_ms": 1}

    monkeypatch.setattr(vision_remote, "analyze", fake_analyze)
    settings = _settings(remote_ready, {"external": {"max_frames": 1}})

    evidence = _run(settings, [{"file": "a.jpg"}, {"file": "b.jpg"}], tmp_path)

    assert calls["n"] == 1
    assert "vision_text" in evidence.images[0]
    assert "超出本任务云端上限" in evidence.images[1]["vision_error"]


def test_run_without_channel_keeps_images(monkeypatch, tmp_path):
    monkeypatch.setattr(vision_local.shutil, "which", lambda name: None)
    logs: list[str] = []

    images = [{"file": "a.jpg"}]
    evidence = _run(_settings(), images, tmp_path, logs)

    assert evidence.images == images
    assert any("跳过图像取证" in line for line in logs)


def test_run_without_images_logs_and_returns(tmp_path):
    logs: list[str] = []

    evidence = _run(_settings(), [], tmp_path, logs)

    assert evidence.images == []
    assert logs and logs[0].startswith("图像证据通道：")


def test_availability_reflects_engine(monkeypatch, remote_ready):
    monkeypatch.setattr(vision_local.shutil, "which", lambda name: None)

    assert image_vision.image_vision.availability(_settings()) .available is False
    assert image_vision.image_vision.availability(_settings(remote_ready)).available is True


# ---------------------------------------------------------------- 证据文本


def test_evidence_text_labels_both_sources():
    text = image_vision.image_vision.evidence_text(
        {"ocr_text": "数字 42", "vision_text": "画面是仪表盘", "vision_provider": "openai-chat:m"}
    )

    assert "[本地 OCR 逐行文字]" in text
    assert "数字 42" in text
    assert "[视觉模型理解（openai-chat:m）]" in text
    assert "画面是仪表盘" in text


def test_evidence_text_empty_for_image_without_evidence():
    assert image_vision.image_vision.evidence_text({"file": "a.jpg"}) == ""
