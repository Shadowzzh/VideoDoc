"""API Key 解析：页面里填的明文优先，其次读 Key 文件。

为什么单独一个模块：文本模型和图像识别是两套互不相干的接入点，但「从哪拿 Key」
的规则必须一致 —— 否则同一个密钥文件在一边能读、另一边读不出来，用户很难自己查。

密钥文件的两种写法都认（很多 ``.env`` 风格的密钥文件是前者）：

* 纯值：``sk-xxxx``
* 带变量名：``VIDEODOC_LLM_API_KEY=sk-xxxx``
"""

from __future__ import annotations

from pathlib import Path


def extract_key_value(text: str) -> str:
    """从密钥文件内容里取出 Key；纯值原样返回。"""
    value = text.strip()
    if not value:
        return ""
    # ``=`` 说明这是 ``KEY=VALUE`` 形态；Key 本身以 ``sk-`` 开头时不误判。
    if "=" in value and not value.startswith("sk-"):
        return value.partition("=")[2].strip().strip("'\"")
    return value


def read_key_file(path: Path | str | None) -> str:
    """读密钥文件里的 Key；文件没配 / 不存在 / 读不了都返回空串（不抛错）。"""
    if path is None or str(path).strip() == "":
        return ""
    target = Path(path).expanduser()
    if not target.is_file():
        return ""
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return ""
    return extract_key_value(text)


def resolve_api_key(inline: str = "", key_file: Path | str | None = None) -> str:
    """优先用页面里填的明文 Key；没有再读 Key 文件。"""
    if inline and inline.strip():
        return inline.strip()
    return read_key_file(key_file)
