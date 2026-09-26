"""设置存储单测：能力默认值、文件覆盖、点分 key 校验、落盘权限、密钥脱敏、旧结构迁移。"""

import json
import stat

import pytest

from videodoc import settings as st
from videodoc.capabilities import registry

CAPABILITY = "image_vision"


def _section(settings):
    return st.capability_settings(settings, CAPABILITY)


def test_default_settings_are_grouped_by_capability():
    defaults = st.default_settings()

    assert list(defaults["capabilities"]) == [CAPABILITY]
    vision = defaults["capabilities"][CAPABILITY]
    assert vision["engine"] == "auto"
    assert vision["local"]["enabled"] is True
    assert vision["external"]["protocol"] == "openai-chat"
    assert vision["external"]["prompt"]


def test_defaults_read_environment(monkeypatch):
    monkeypatch.setenv("VIDEODOC_VISION_ENGINE", "external")
    monkeypatch.setenv("VIDEODOC_VISION_BASE_URL", "http://192.168.8.211:3006/v1")
    monkeypatch.setenv("VIDEODOC_VISION_MODEL", "vision-model")
    monkeypatch.setenv("VIDEODOC_VISION_MAX_FRAMES", "4")
    monkeypatch.setenv("VIDEODOC_VISION_DAILY_BUDGET", "9")

    external = _section(st.default_settings())["external"]

    assert external["base_url"] == "http://192.168.8.211:3006/v1"
    assert external["model"] == "vision-model"
    assert external["max_frames"] == 4
    assert external["daily_budget"] == 9


def test_effective_settings_file_overrides_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODOC_VISION_ENGINE", "local")
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"capabilities": {CAPABILITY: {"engine": "both"}}}), encoding="utf-8"
    )

    assert _section(st.effective_settings(path))["engine"] == "both"


def test_effective_settings_tolerates_broken_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")

    assert _section(st.effective_settings(path))["engine"] == "auto"


def test_effective_settings_migrates_legacy_vision_section(tmp_path):
    """历史文件里的顶层 vision 段要能自动迁移，不让升级后配置丢失。"""
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "vision": {
                    "engine": "external",
                    "external": {
                        "protocol": "openai-responses",
                        "base_url": "http://legacy/v1",
                        "model": "m",
                        "api_key": "legacy-key-1234",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    section = _section(st.effective_settings(path))

    assert section["engine"] == "external"
    assert section["external"]["base_url"] == "http://legacy/v1"
    assert section["external"]["api_key"] == "legacy-key-1234"


def test_effective_settings_expand_dotted_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"capabilities": {CAPABILITY: {"external.base_url": "http://h/v1"}}}),
        encoding="utf-8",
    )

    section = _section(st.effective_settings(path))

    assert section["external"]["base_url"] == "http://h/v1"
    assert section["external"]["protocol"] == "openai-chat"


def test_deep_merge_and_expand_helpers():
    assert st.deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 9}}) == {"a": {"b": 9, "c": 2}}
    assert st.expand_settings({"capabilities": {CAPABILITY: {"a.b": 1}}}) == {
        "capabilities": {CAPABILITY: {"a": {"b": 1}}}
    }


def test_capability_settings_returns_empty_for_unknown():
    assert st.capability_settings(st.default_settings(), "nope") == {}


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"capabilities": {CAPABILITY: {"engine": "cloud"}}}, "通道 只能是"),
        ({"capabilities": {CAPABILITY: {"external.protocol": "soap"}}}, "协议 只能是"),
        ({"capabilities": {CAPABILITY: {"external.max_frames": 99}}}, "每任务云端上限"),
        ({"capabilities": {CAPABILITY: {"external.daily_budget": -1}}}, "每日预算"),
        ({"capabilities": {CAPABILITY: {"local.level": "ultra"}}}, "精度 只能是"),
        ({"capabilities": {"nope": {"engine": "auto"}}}, "未知能力"),
        ({"capabilities": {CAPABILITY: {"nope": 1}}}, "未知设置项"),
        ({"weather": {}}, "未知字段"),
    ],
)
def test_validate_settings_rejects_bad_input(payload, message):
    with pytest.raises(st.SettingsError) as error:
        st.validate_settings(payload)

    assert message in str(error.value)


def test_validate_settings_accepts_legacy_vision_shape():
    validated = st.validate_settings({"vision": {"engine": "external"}})

    assert validated == {"capabilities": {CAPABILITY: {"engine": "external"}}}


def test_validate_settings_rejects_header_injection():
    with pytest.raises(st.SettingsError):
        st.validate_settings({"capabilities": {CAPABILITY: {"external.extra_headers": {"X-Bad": "a\nb"}}}})


def test_validate_settings_parses_header_text_and_keeps_base_url_raw():
    validated = st.validate_settings(
        {
            "capabilities": {
                CAPABILITY: {
                    "external.base_url": "http://192.168.8.211:3006/v1/",
                    "external.extra_headers": "x-opencode-session: abc; X-Trace=1",
                }
            }
        }
    )

    section = validated["capabilities"][CAPABILITY]
    assert section["external.extra_headers"] == {"x-opencode-session": "abc", "X-Trace": "1"}
    # base_url 的 http(s) 校验在保存时做（见 test_save_settings_rejects_non_http_base_url）
    assert section["external.base_url"] == "http://192.168.8.211:3006/v1/"


def test_validate_settings_skips_empty_secret_to_keep_saved_value():
    validated = st.validate_settings({"capabilities": {CAPABILITY: {"external.api_key": ""}}})

    assert validated == {}


def test_validate_settings_ignores_empty_section():
    assert st.validate_settings({"capabilities": {CAPABILITY: {}}}) == {}


def test_save_settings_merges_partial_updates_and_sets_permissions(tmp_path):
    path = tmp_path / "nested" / "settings.json"

    st.save_settings(
        {"capabilities": {CAPABILITY: {"external.base_url": "http://h/v1", "external.model": "m"}}},
        path,
    )
    st.save_settings({"capabilities": {CAPABILITY: {"engine": "external"}}}, path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    section = raw["capabilities"][CAPABILITY]
    assert section["engine"] == "external"
    assert section["external.base_url"] == "http://h/v1"
    assert section["external.model"] == "m"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert [item.name for item in path.parent.iterdir()] == ["settings.json"]


def test_save_settings_rejects_non_http_base_url(tmp_path):
    path = tmp_path / "settings.json"

    with pytest.raises(st.SettingsError) as error:
        st.save_settings({"capabilities": {CAPABILITY: {"external.base_url": "ftp://h/v1"}}}, path)

    assert "http://" in str(error.value)
    assert not path.exists()


def test_save_settings_rejects_bad_input_without_writing(tmp_path):
    path = tmp_path / "settings.json"

    with pytest.raises(st.SettingsError):
        st.save_settings({"capabilities": {CAPABILITY: {"engine": "nope"}}}, path)

    assert not path.exists()


def test_save_settings_keeps_previously_saved_secret(tmp_path):
    path = tmp_path / "settings.json"
    st.save_settings({"capabilities": {CAPABILITY: {"external.api_key": "first-secret-abcd"}}}, path)

    st.save_settings({"capabilities": {CAPABILITY: {"engine": "external", "external.api_key": ""}}}, path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert raw["capabilities"][CAPABILITY]["external.api_key"] == "first-secret-abcd"


def test_redact_settings_never_returns_full_key(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODOC_VISION_API_KEY", raising=False)
    path = tmp_path / "settings.json"
    st.save_settings(
        {
            "capabilities": {
                CAPABILITY: {
                    "engine": "external",
                    "external.base_url": "http://h/v1",
                    "external.model": "m",
                    "external.api_key": "plain-secret-abcd",
                }
            }
        },
        path,
    )

    view = st.redact_settings(st.effective_settings(path))
    section = view["capabilities"][CAPABILITY]

    assert '"external.api_key":' not in json.dumps(view, ensure_ascii=False)
    assert section["external.api_key_configured"] is True
    assert section["external.api_key_hint"] == "****abcd"
    assert "plain-secret-abcd" not in json.dumps(view)


def test_redact_settings_detects_key_file(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODOC_VISION_API_KEY", raising=False)
    key_file = tmp_path / "key"
    key_file.write_text("file-secret-9876\n", encoding="utf-8")
    path = tmp_path / "settings.json"
    st.save_settings(
        {
            "capabilities": {
                CAPABILITY: {
                    "external.base_url": "http://h/v1",
                    "external.model": "m",
                    "external.api_key_file": str(key_file),
                }
            }
        },
        path,
    )

    section = st.redact_settings(st.effective_settings(path))["capabilities"][CAPABILITY]

    assert section["external.api_key_configured"] is True
    assert section["external.api_key_hint"] == "****9876"
    assert section["external.api_key_file"] == str(key_file)


def test_redact_settings_exposes_schema_for_settings_page(tmp_path):
    view = st.redact_settings(st.effective_settings(tmp_path / "missing.json"))

    categories = view["categories"]
    assert [category["key"] for category in categories] == [CAPABILITY]
    assert categories[0]["label"] == "图像识别"
    assert [group["title"] for group in categories[0]["groups"]] == [
        "识别通道",
        "本地（macOS Vision）",
        "云端（视觉模型理解）",
        "预算与重试",
    ]
    fields = {
        item["key"]: item for group in categories[0]["groups"] for item in group["fields"]
    }
    assert fields["external.api_key"]["secret"] is True
    assert fields["external.protocol"]["type"] == "select"
    assert {option["value"] for option in fields["external.protocol"]["options"]} == {
        "openai-chat",
        "openai-responses",
        "anthropic-messages",
        "gemini-generateContent",
    }
    assert fields["external.max_frames"]["maximum"] == 24
    assert view["settings_path"].endswith("settings.json")


def test_settings_path_prefers_environment(tmp_path, monkeypatch):
    target = tmp_path / "custom.json"
    monkeypatch.setenv("VIDEODOC_SETTINGS_FILE", str(target))

    assert st.settings_path() == target


def test_settings_path_uses_project_file_when_present(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODOC_SETTINGS_FILE", raising=False)
    (tmp_path / ".videodoc-settings.json").write_text("{}", encoding="utf-8")

    assert st.settings_path(tmp_path) == tmp_path / ".videodoc-settings.json"


def test_settings_path_defaults_to_home(monkeypatch):
    monkeypatch.delenv("VIDEODOC_SETTINGS_FILE", raising=False)

    assert st.settings_path() == st.DEFAULT_SETTINGS_PATH
