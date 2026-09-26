"""全局测试隔离。

**为什么要这个**：设置层默认读 ``~/.config/videodoc/settings.json``。开发机上这份文件是
真实配置（含云端图像识别的 BaseURL / Key），如果不隔离：

1. 测试会读到我本机的私有配置，结果依赖机器状态；
2. 更糟的是流水线测试会据此真的向网关发图像识别请求（测试不联网的前提被破坏）。

因此所有测试默认把设置文件指向临时目录；需要特定设置文件的测试在自己体内再
``monkeypatch.setenv`` 覆盖即可（fixture 先执行，测试体的设置优先生效）。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_settings_file(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODOC_SETTINGS_FILE", str(tmp_path / "videodoc-settings.json"))
