"""文本模型设置分类单测：端点拼接、可用性、/models 探测、密钥文件、流水线取值。

文本模型与图像识别最大的不同：**它不占流水线步骤位**，但必须能盖住环境变量
（页面保存的值优先），否则「改成网关里的 DeepSeek 4.1」这类需求只能靠改 .env。
"""

import json
import urllib.error

import pytest

from videodoc import pipeline
from videodoc import settings as st
from videodoc.capabilities import registry, text_model
from videodoc.integrations.api_key import extract_key_value
from videodoc.task_store import TaskStore


def _section(*overrides):
    merged = text_model.defaults()
    for item in overrides:
        merged = st.deep_merge(merged, item)
    return merged


# ---------------------------------------------------------------- 注册方式


def test_section_registers_without_taking_a_pipeline_step():
    assert registry.get("text_model") is text_model.text_model
    assert "text_model" not in {spec.key for spec in registry.step_specs()}
    assert registry.by_step("text_model") is None
    # 设置页要能看到它
    assert [item.key for item in registry.sections()] == ["image_vision", "text_model"]


def test_defaults_follow_deepseek_official():
    section = _section()

    assert section["base_url"] == text_model.DEFAULT_BASE_URL
    assert section["model"] == text_model.DEFAULT_MODEL
    assert section["retries"] == 3


# ---------------------------------------------------------------- 端点拼接


def test_endpoint_appends_chat_completions_once():
    config = text_model.TextModelConfig(base_url="http://127.0.0.1:3006/v1", model="m")

    assert config.endpoint() == "http://127.0.0.1:3006/v1/chat/completions"
    assert config.describe() == "POST http://127.0.0.1:3006/v1/chat/completions model=m"

    full = text_model.TextModelConfig(base_url="http://h/v1/chat/completions/", model="m")
    assert full.endpoint() == "http://h/v1/chat/completions"


def test_probe_url_drops_generation_path():
    base = text_model.TextModelConfig(base_url="http://h:3006/v1", model="m")
    full = text_model.TextModelConfig(base_url="http://h/v1/chat/completions", model="m")

    assert base.probe_url() == "http://h:3006/v1/models"
    assert full.probe_url() == "http://h/v1/models"


# ---------------------------------------------------------------- 可用性


def test_availability_lists_missing_pieces():
    assert (
        text_model.availability({"base_url": "", "model": "m", "api_key": "k"}).reason
        == "未配置文本模型 BaseURL"
    )
    assert (
        text_model.availability({"base_url": "http://h", "model": "", "api_key": "k"}).reason
        == "未配置文本模型"
    )
    assert (
        text_model.availability({"base_url": "http://h", "model": "m", "api_key": ""}).reason
        == "未配置文本模型 Key"
    )
    assert text_model.availability(
        {"base_url": "http://h", "model": "m", "api_key": "k"}
    ).available


# ---------------------------------------------------------------- 密钥来源


def test_api_key_can_come_from_file(tmp_path):
    key_file = tmp_path / "ai.env"
    key_file.write_text("OPENCODE_GO_API_KEY=sk-from-file\n", encoding="utf-8")
    settings = {"base_url": "http://h", "model": "m", "api_key_file": str(key_file)}

    assert text_model.config_from(settings).resolved_api_key() == "sk-from-file"
    assert text_model.availability(settings).available


def test_inline_key_wins_over_file(tmp_path):
    key_file = tmp_path / "ai.env"
    key_file.write_text("sk-from-file\n", encoding="utf-8")
    settings = {"api_key": "sk-inline", "api_key_file": str(key_file)}

    assert text_model.config_from(settings).resolved_api_key() == "sk-inline"


def test_key_file_beats_environment_key(tmp_path, monkeypatch):
    """配了 Key 文件就不该被环境变量里的旧 Key 压住（本次踩到的坑）。"""
    key_file = tmp_path / "gateway-key"
    key_file.write_text("sk-from-file\n", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "sk-from-env")

    settings = _section({"api_key_file": str(key_file)})

    assert text_model.config_from(settings).resolved_api_key() == "sk-from-file"


def test_environment_key_still_fills_in_when_page_is_empty(monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "sk-from-env")

    assert text_model.config_from(_section()).resolved_api_key() == "sk-from-env"


def test_missing_key_file_is_not_an_error():
    settings = {"base_url": "http://h", "model": "m", "api_key_file": "/nope/missing.env"}

    assert text_model.config_from(settings).resolved_api_key() == ""
    assert text_model.availability(settings).available is False


def test_extract_key_value_accepts_plain_and_assignment_forms():
    assert extract_key_value("  sk-abc  ") == "sk-abc"
    assert extract_key_value('OPENCODE_GO_API_KEY="sk-abc"') == "sk-abc"
    assert extract_key_value("") == ""


# ---------------------------------------------------------------- 探测


def test_probe_hits_models_endpoint(monkeypatch):
    seen = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"data": [{"id": "deepseek-v4.1-flash"}]}).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["auth"] = request.headers.get("Authorization")
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = text_model.probe(
        _section(
            {
                "base_url": "http://127.0.0.1:3006/v1",
                "model": "deepseek-v4.1-flash",
                "api_key": "k",
            }
        )
    )

    assert result["ok"] is True
    assert seen["url"] == "http://127.0.0.1:3006/v1/models"
    assert seen["auth"] == "Bearer k"
    assert result["models"] == ["deepseek-v4.1-flash"]


def test_probe_reports_http_error(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = text_model.probe(
        _section({"base_url": "http://h/v1", "model": "m", "api_key": "bad"})
    )

    assert result["ok"] is False
    assert "401" in result["detail"]


def test_probe_without_key_is_not_available():
    result = text_model.probe({"base_url": "http://h", "model": "m", "api_key": ""})

    assert result["ok"] is False
    assert "Key" in result["detail"]


# ---------------------------------------------------------------- 流水线取值


def _text_model_settings_file(tmp_path, section: dict) -> str:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"capabilities": {"text_model": section}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(path)


def test_pipeline_prefers_page_settings_over_environment(tmp_path, monkeypatch):
    """本次改动的核心行为：页面保存的接入点盖住环境变量。"""
    monkeypatch.setenv(
        "VIDEODOC_SETTINGS_FILE",
        _text_model_settings_file(
            tmp_path,
            {
                "base_url": "http://127.0.0.1:3006/v1",
                "model": "deepseek-v4.1-flash",
                "api_key": "sk-page-key",
            },
        ),
    )
    monkeypatch.setenv("VIDEODOC_LLM_BASE_URL", "https://opencode.ai/zen/go/v1")
    monkeypatch.setenv("VIDEODOC_LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "sk-env-key")

    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    instance = pipeline.VideoArticlePipeline(store, task["id"], pipeline.PipelineConfig())

    assert instance.text_model.base_url == "http://127.0.0.1:3006/v1"
    assert instance.text_model.model == "deepseek-v4.1-flash"
    assert instance.text_model.resolved_api_key() == "sk-page-key"
    assert instance._llm_endpoint() == "http://127.0.0.1:3006/v1/chat/completions"


def test_pipeline_falls_back_to_environment_when_page_is_empty(tmp_path, monkeypatch):
    # conftest 已把设置文件指到空文件；这里只提供环境变量。
    monkeypatch.setenv("VIDEODOC_LLM_BASE_URL", "https://opencode.ai/zen/go/v1")
    monkeypatch.setenv("VIDEODOC_LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "sk-env-key")

    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    instance = pipeline.VideoArticlePipeline(store, task["id"], pipeline.PipelineConfig())

    assert instance.text_model.base_url == "https://opencode.ai/zen/go/v1"
    assert instance.text_model.model == "deepseek-v4-flash"
    assert instance.text_model.resolved_api_key() == "sk-env-key"


def test_pipeline_uses_key_file_and_ignores_environment_key(tmp_path, monkeypatch):
    """本机场景：页面里靠 api_key_file 指向网关 Key，环境变量里还留着旧的 zen Key。"""
    key_file = tmp_path / "gateway-key"
    key_file.write_text("sk-gateway\n", encoding="utf-8")
    monkeypatch.setenv(
        "VIDEODOC_SETTINGS_FILE",
        _text_model_settings_file(
            tmp_path,
            {
                "base_url": "http://192.168.8.211:3006/v1",
                "model": "deepseek-v4.1-flash",
                "api_key_file": str(key_file),
            },
        ),
    )
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "sk-env-key")

    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    instance = pipeline.VideoArticlePipeline(store, task["id"], pipeline.PipelineConfig())

    assert instance.text_model.resolved_api_key() == "sk-gateway"
    assert instance._llm_endpoint() == "http://192.168.8.211:3006/v1/chat/completions"


def test_call_llm_uses_configured_timeout_and_retries(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODOC_FAKE_LLM", raising=False)
    monkeypatch.setenv(
        "VIDEODOC_SETTINGS_FILE",
        _text_model_settings_file(
            tmp_path,
            {
                "base_url": "http://127.0.0.1:3006/v1",
                "model": "deepseek-v4.1-flash",
                "api_key": "sk-page-key",
                "timeout_seconds": 7,
                "retries": 0,
            },
        ),
    )
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    instance = pipeline.VideoArticlePipeline(store, task["id"], pipeline.PipelineConfig())

    calls = {"n": 0}
    timeouts: list[int] = []

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        timeouts.append(timeout)
        raise urllib.error.URLError("boom")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(pipeline.PipelineError) as error:
        instance._call_llm("outline", [{"role": "user", "content": "hi"}])

    assert calls["n"] == 1  # retries=0 → 不重试
    assert timeouts == [7]
    assert "LLM API 请求失败" in str(error.value)


def test_call_llm_reports_missing_key_with_setting_page_hint(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODOC_FAKE_LLM", raising=False)
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    instance = pipeline.VideoArticlePipeline(store, task["id"], pipeline.PipelineConfig())

    with pytest.raises(pipeline.PipelineError) as error:
        instance._call_llm("outline", [{"role": "user", "content": "hi"}])

    assert "设置页" in str(error.value)


# ---------------------------------------------------------------- 设置层校验


def test_save_settings_accepts_text_model_section(tmp_path):
    path = tmp_path / "settings.json"

    st.save_settings(
        {
            "capabilities": {
                "text_model": {
                    "base_url": "http://192.168.8.211:3006/v1",
                    "model": "deepseek-v4.1-flash",
                    "api_key": "sk-abcdefgh",
                }
            }
        },
        path,
    )
    saved = json.loads(path.read_text(encoding="utf-8"))["capabilities"]["text_model"]

    assert saved["model"] == "deepseek-v4.1-flash"
    assert saved["api_key"] == "sk-abcdefgh"


def test_save_settings_rejects_non_http_text_model_base_url(tmp_path):
    path = tmp_path / "settings.json"

    with pytest.raises(st.SettingsError):
        st.save_settings(
            {"capabilities": {"text_model": {"base_url": "ftp://h/v1"}}}, path
        )

    assert not path.exists()


def test_text_model_secret_is_never_echoed(tmp_path):
    path = tmp_path / "settings.json"
    st.save_settings(
        {"capabilities": {"text_model": {"api_key": "sk-plain-abcd"}}}, path
    )

    view = st.redact_settings(st.effective_settings(path))["capabilities"]["text_model"]

    assert view["api_key_configured"] is True
    assert view["api_key_hint"] == "****abcd"
    assert "api_key" not in view
