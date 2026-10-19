"""全局测试隔离。

**为什么要这个**：设置层默认读 ``~/.config/videodoc/settings.json``。开发机上这份文件是
真实配置（含云端图像识别的 BaseURL / Key），如果不隔离：

1. 测试会读到我本机的私有配置，结果依赖机器状态；
2. 更糟的是流水线测试会据此真的向网关发图像识别请求（测试不联网的前提被破坏）。

因此所有测试默认把设置文件指向临时目录；需要特定设置文件的测试在自己体内再
``monkeypatch.setenv`` 覆盖即可（fixture 先执行，测试体的设置优先生效）。

另外 LLM 相关的环境变量也要清空：文本模型设置以环境变量作默认值，开发机 shell 里的
值与 ``.env`` 会直接改变断言结果（旧 ``.env`` 加载测试曾把 ``VIDEODOC_LLM_BASE_URL``
留在 ``os.environ`` 里，污染后续用例）。
"""

from __future__ import annotations

import pytest


# LLM 接入点的环境变量：清理后由各测试自己 setenv。
LLM_ENVIRONMENT_KEYS = (
    "VIDEODOC_LLM_BASE_URL",
    "VIDEODOC_LLM_MODEL",
    "VIDEODOC_LLM_API_KEY",
    "VIDEODOC_LLM_API_KEY_FILE",
    "VIDEODOC_LLM_TIMEOUT",
    "VIDEODOC_LLM_RETRIES",
    "OPENCODE_GO_API_KEY",
)


@pytest.fixture(autouse=True)
def isolated_settings_file(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODOC_SETTINGS_FILE", str(tmp_path / "videodoc-settings.json"))


@pytest.fixture(autouse=True)
def isolated_llm_environment(monkeypatch):
    for key in LLM_ENVIRONMENT_KEYS:
        monkeypatch.delenv(key, raising=False)
