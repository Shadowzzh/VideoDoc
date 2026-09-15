"""配置加载单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from videodoc.config import (
    default_env_file,
    load_env_file,
    parse_env_text,
)


def test_parse_env_text_supports_comments_quotes_and_export() -> None:
    text = "\n".join(
        [
            "# 注释行",
            "",
            "VIDEODOC_LLM_BASE_URL=https://api.deepseek.com",
            "export VIDEODOC_LLM_MODEL=deepseek-v4-flash",
            'VIDEODOC_RUNTIME_DIR="/tmp/with space"',
            "VIDEODOC_WHISPER_MODEL='/models/ggml.bin'",
            "   ",
            "没有等号的行",
            "=空键",
            "VIDEODOC_EMPTY=",
        ]
    )
    values = parse_env_text(text)
    assert values["VIDEODOC_LLM_BASE_URL"] == "https://api.deepseek.com"
    assert values["VIDEODOC_LLM_MODEL"] == "deepseek-v4-flash"
    assert values["VIDEODOC_RUNTIME_DIR"] == "/tmp/with space"
    assert values["VIDEODOC_WHISPER_MODEL"] == "/models/ggml.bin"
    assert values["VIDEODOC_EMPTY"] == ""
    assert "没有等号的行" not in values
    assert "" not in values


def test_load_env_file_does_not_override_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIDEODOC_LLM_MODEL", "from-shell")
    monkeypatch.delenv("VIDEODOC_LLM_BASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "VIDEODOC_LLM_MODEL=from-file\nVIDEODOC_LLM_BASE_URL=from-file\n",
        encoding="utf-8",
    )

    applied = load_env_file(env_file)

    import os

    # 已存在的 shell 变量优先，.env 只补空缺
    assert os.environ["VIDEODOC_LLM_MODEL"] == "from-shell"
    assert os.environ["VIDEODOC_LLM_BASE_URL"] == "from-file"
    assert applied == ["VIDEODOC_LLM_BASE_URL"]


def test_load_env_file_can_override_explicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    monkeypatch.setenv("VIDEODOC_LLM_MODEL", "from-shell")
    env_file = tmp_path / ".env"
    env_file.write_text("VIDEODOC_LLM_MODEL=from-file\n", encoding="utf-8")

    load_env_file(env_file, override=True)

    assert os.environ["VIDEODOC_LLM_MODEL"] == "from-file"


def test_load_env_file_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "does-not-exist") == []


def test_default_env_file_uses_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VIDEODOC_ENV_FILE", raising=False)
    assert default_env_file(tmp_path) == tmp_path / ".env"

    monkeypatch.setenv("VIDEODOC_ENV_FILE", str(tmp_path / "local.env"))
    assert default_env_file(tmp_path) == tmp_path / "local.env"


def test_default_env_file_expands_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIDEODOC_ENV_FILE", "~/videodoc.env")
    assert default_env_file(tmp_path) == Path.home() / "videodoc.env"
