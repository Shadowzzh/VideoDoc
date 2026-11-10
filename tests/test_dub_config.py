"""配音配置的合并与夹紧。"""

from __future__ import annotations

from videodoc.capabilities.dub import (
    DEFAULT_TONE,
    DEFAULT_VOICE_ID,
    availability,
    config_from,
    defaults,
)


def test_defaults_have_service_and_voice():
    base = defaults()
    assert base["base_url"].startswith("http")
    assert base["voice_id"] == DEFAULT_VOICE_ID
    assert base["tone"] == DEFAULT_TONE
    assert base["subtitle_bar"] is True
    assert base["separate"] is True


def test_settings_override_defaults():
    config = config_from({"capabilities": {"dub": {
        "base_url": "http://example:9000/",
        "voice_id": "abc",
        "tone": 8,
        "max_tempo": 1.2,
    }}})
    assert config.base_url == "http://example:9000"  # 去掉尾部斜杠
    assert config.voice_id == "abc"
    assert config.tone == 8
    assert config.max_tempo == 1.2


def test_tone_is_clamped():
    assert config_from({"capabilities": {"dub": {"tone": 99}}}).tone == 10
    assert config_from({"capabilities": {"dub": {"tone": -5}}}).tone == 0


def test_max_tempo_is_clamped():
    assert config_from({"capabilities": {"dub": {"max_tempo": 9}}}).max_tempo == 1.3
    assert config_from({"capabilities": {"dub": {"max_tempo": 0.1}}}).max_tempo == 1.0


def test_blank_values_fall_back_to_defaults():
    config = config_from({"capabilities": {"dub": {"base_url": "", "voice_id": ""}}})
    assert config.base_url.startswith("http")
    assert config.voice_id == DEFAULT_VOICE_ID


def test_availability_requires_voice():
    state = availability({"capabilities": {"dub": {"voice_id": ""}}})
    assert state.available is True  # 空值会回落到默认声音

    config = config_from({"capabilities": {"dub": {"voice_id": ""}}})
    assert config.voice_id == DEFAULT_VOICE_ID
