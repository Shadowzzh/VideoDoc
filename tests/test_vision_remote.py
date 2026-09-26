"""多协议适配层单测：请求体形状、响应文本抽取、端点拼接、Key 解析、重试。"""

import base64
import io
import json
import urllib.error
from dataclasses import replace

import pytest

from videodoc.integrations import vision_remote as vr


BASE = vr.RemoteVisionConfig(
    protocol="openai-chat",
    base_url="http://127.0.0.1:3006/v1",
    model="gemini-3.5-flash-lite",
    api_key="secret-key-abcd",
)
IMAGE = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "http://127.0.0.1:3006/v1/chat/completions",
        code,
        "boom",
        {},
        io.BytesIO(json.dumps({"error": "boom"}).encode()),
    )


# ---------------------------------------------------------------- 基础工具


def test_sniff_media_type_prefers_magic_bytes():
    assert vr.sniff_media_type(b"\xff\xd8\xff\xe0....") == "image/jpeg"
    assert vr.sniff_media_type(b"\x89PNG\r\n\x1a\n....") == "image/png"
    assert vr.sniff_media_type(b"GIF89a....") == "image/gif"
    assert vr.sniff_media_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"


def test_sniff_media_type_falls_back_to_suffix_then_jpeg():
    assert vr.sniff_media_type(b"unknown", ".png") == "image/png"
    assert vr.sniff_media_type(b"unknown", ".jpeg") == "image/jpeg"
    assert vr.sniff_media_type(b"unknown") == "image/jpeg"


@pytest.mark.parametrize(
    "protocol, base_url, expected",
    [
        ("openai-chat", "http://h:3006/v1", "http://h:3006/v1/chat/completions"),
        ("openai-responses", "http://h:3006/v1", "http://h:3006/v1/responses"),
        ("anthropic-messages", "https://api.anthropic.com/v1", "https://api.anthropic.com/v1/messages"),
        (
            "gemini-generateContent",
            "https://generativelanguage.googleapis.com/v1beta",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent",
        ),
    ],
)
def test_endpoint_joins_protocol_path(protocol, base_url, expected):
    config = replace(BASE, protocol=protocol, base_url=base_url)

    assert config.endpoint() == expected


def test_endpoint_does_not_duplicate_existing_path():
    config = replace(BASE, base_url="http://h:3006/v1/chat/completions")

    assert config.endpoint() == "http://h:3006/v1/chat/completions"


def test_endpoint_respects_api_path_override():
    config = replace(BASE, api_path="/custom/vision")

    assert config.endpoint() == "http://127.0.0.1:3006/v1/custom/vision"


def test_probe_endpoint_always_uses_models():
    config = replace(BASE, api_path="/custom/vision")

    assert config.endpoint(probe=True) == "http://127.0.0.1:3006/v1/models"


def test_resolved_api_key_inline_wins_then_file(tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("file-key-1234\n", encoding="utf-8")
    config = replace(BASE, api_key_file=key_file)

    assert config.resolved_api_key() == "secret-key-abcd"
    assert replace(config, api_key="").resolved_api_key() == "file-key-1234"


def test_resolved_api_key_accepts_env_style_file(tmp_path):
    key_file = tmp_path / "key.env"
    key_file.write_text("VIDEODOC_VISION_API_KEY=env-style-key\n", encoding="utf-8")

    assert replace(BASE, api_key="", api_key_file=key_file).resolved_api_key() == "env-style-key"


def test_resolved_api_key_missing_file_is_empty(tmp_path):
    assert replace(BASE, api_key="", api_key_file=tmp_path / "nope").resolved_api_key() == ""


# ---------------------------------------------------------------- 请求体


@pytest.mark.parametrize("protocol", vr.PROTOCOLS)
def test_build_payload_carries_prompt_and_base64_image(protocol):
    config = replace(BASE, protocol=protocol)

    body = vr.build_payload(config, "这是提示词", IMAGE, "image/jpeg")
    serialized = json.dumps(body, ensure_ascii=False)

    assert "这是提示词" in serialized
    assert base64.b64encode(IMAGE).decode() in serialized


def test_build_payload_openai_chat_shape():
    body = vr.build_payload(BASE, "p", IMAGE, "image/jpeg")

    content = body["messages"][0]["content"]
    assert body["model"] == "gemini-3.5-flash-lite"
    assert content[0] == {"type": "text", "text": "p"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_build_payload_openai_responses_shape():
    body = vr.build_payload(replace(BASE, protocol="openai-responses"), "p", IMAGE, "image/jpeg")

    content = body["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/jpeg;base64,")


def test_build_payload_anthropic_shape():
    body = vr.build_payload(replace(BASE, protocol="anthropic-messages"), "p", IMAGE, "image/png")

    content = body["messages"][0]["content"]
    assert body["max_tokens"] == 1024
    assert content[0]["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": base64.b64encode(IMAGE).decode(),
    }
    assert content[1] == {"type": "text", "text": "p"}


def test_build_payload_gemini_shape():
    body = vr.build_payload(replace(BASE, protocol="gemini-generateContent"), "p", IMAGE, "image/jpeg")

    parts = body["contents"][0]["parts"]
    assert parts[0] == {"text": "p"}
    assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"
    assert parts[1]["inline_data"]["data"] == base64.b64encode(IMAGE).decode()


def test_build_payload_rejects_unknown_protocol():
    with pytest.raises(vr.RemoteVisionError):
        vr.build_payload(replace(BASE, protocol="mystery"), "p", IMAGE, "image/jpeg")


# ---------------------------------------------------------------- 响应抽取


def test_extract_text_openai_chat_string_and_parts():
    assert vr.extract_text("openai-chat", {"choices": [{"message": {"content": " 你好 "}}]}) == "你好"
    parts = {"choices": [{"message": {"content": [{"type": "text", "text": "甲"}, {"type": "text", "text": "乙"}]}}]}
    assert vr.extract_text("openai-chat", parts) == "甲\n乙"


def test_extract_text_openai_responses():
    body = {
        "output": [
            {"type": "reasoning", "content": []},
            {"type": "message", "content": [{"type": "output_text", "text": "画面里是 K 线图"}]},
        ]
    }

    assert vr.extract_text("openai-responses", body) == "画面里是 K 线图"


def test_extract_text_anthropic_skips_non_text_parts():
    body = {"content": [{"type": "thinking", "text": "忽略"}, {"type": "text", "text": "结论"}]}

    assert vr.extract_text("anthropic-messages", body) == "结论"


def test_extract_text_gemini_and_empty_cases():
    body = {"candidates": [{"content": {"parts": [{"text": "数值 42"}, {"text": ""}]}}]}

    assert vr.extract_text("gemini-generateContent", body) == "数值 42"
    assert vr.extract_text("gemini-generateContent", {}) == ""
    assert vr.extract_text("openai-chat", {}) == ""


# ---------------------------------------------------------------- analyze / probe


def test_analyze_returns_text_model_usage_and_redacts(tmp_path, monkeypatch):
    image = tmp_path / "frame.jpg"
    image.write_bytes(IMAGE)
    monkeypatch.setattr(
        vr,
        "_http_json",
        lambda *args, **kwargs: {
            "choices": [{"message": {"content": "理解结果"}}],
            "model": "gemini-3.5-flash-lite",
            "usage": {"total_tokens": 7},
        },
    )

    result = vr.analyze(BASE, "提示", image)

    assert result["text"] == "理解结果"
    assert result["model"] == "gemini-3.5-flash-lite"
    assert result["usage"] == {"total_tokens": 7}
    assert result["endpoint"].endswith("/chat/completions")


def test_analyze_retries_on_429_then_succeeds(tmp_path, monkeypatch):
    image = tmp_path / "frame.jpg"
    image.write_bytes(IMAGE)
    calls = {"n": 0}

    def fake_http(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429)
        return {"choices": [{"message": {"content": "第二次成功"}}]}

    monkeypatch.setattr(vr, "_http_json", fake_http)
    monkeypatch.setattr(vr.time, "sleep", lambda _seconds: None)

    result = vr.analyze(replace(BASE, retries=1), "提示", image)

    assert result["text"] == "第二次成功"
    assert calls["n"] == 2


def test_analyze_does_not_retry_on_400(tmp_path, monkeypatch):
    image = tmp_path / "frame.jpg"
    image.write_bytes(IMAGE)
    calls = {"n": 0}

    def fake_http(*args, **kwargs):
        calls["n"] += 1
        raise _http_error(400)

    monkeypatch.setattr(vr, "_http_json", fake_http)

    with pytest.raises(vr.RemoteVisionError):
        vr.analyze(replace(BASE, retries=3), "提示", image)
    assert calls["n"] == 1


def test_analyze_raises_on_empty_text(tmp_path, monkeypatch):
    image = tmp_path / "frame.jpg"
    image.write_bytes(IMAGE)
    monkeypatch.setattr(vr, "_http_json", lambda *a, **k: {"choices": [{"message": {"content": "  "}}]})

    with pytest.raises(vr.RemoteVisionError):
        vr.analyze(BASE, "提示", image)


def test_analyze_requires_existing_image(tmp_path):
    with pytest.raises(vr.RemoteVisionError):
        vr.analyze(BASE, "提示", tmp_path / "missing.jpg")


def test_probe_reports_ok_and_model_presence(monkeypatch):
    monkeypatch.setattr(
        vr,
        "_http_json",
        lambda *a, **k: {"data": [{"id": "gemini-3.5-flash-lite"}, {"id": "other"}]},
    )

    result = vr.probe(BASE)

    assert result["ok"] is True
    assert result["model_present"] is True
    assert result["endpoint"].endswith("/models")


def test_probe_reports_http_failure_without_raising(monkeypatch):
    def fake_http(*args, **kwargs):
        raise _http_error(401)

    monkeypatch.setattr(vr, "_http_json", fake_http)

    result = vr.probe(BASE)

    assert result["ok"] is False
    assert "401" in result["detail"]


def test_probe_redacts_api_key_from_error_body(monkeypatch):
    def fake_http(*args, **kwargs):
        raise urllib.error.HTTPError(
            "http://h",
            500,
            "boom",
            {},
            io.BytesIO(b'{"error":"bad key secret-key-abcd"}'),
        )

    monkeypatch.setattr(vr, "_http_json", fake_http)

    result = vr.probe(BASE)

    assert "secret-key-abcd" not in result["detail"]
    assert "***" in result["detail"]
