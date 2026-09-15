"""配置加载：把 .env 文件读进环境变量。

设计约定：

* 默认读取项目根目录的 ``.env``，可用 ``VIDEODOC_ENV_FILE`` 指向别处；
* **已存在的真实环境变量优先**，``.env`` 只做兜底，不覆盖外部注入的值；
* 只实现最小的 ``KEY=VALUE`` 语法（支持注释、可选引号、``export`` 前缀），
  不引入额外依赖。

这样本项目可以自带一套「开箱可用」的默认值，而本地部署用一份独立的环境
文件覆盖成自己的路径、端点与密钥来源。
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILE_VARIABLE = "VIDEODOC_ENV_FILE"


def parse_env_text(text: str) -> dict[str, str]:
    """解析 .env 文本，返回键值对。"""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def default_env_file(project_root: Path) -> Path:
    override = os.environ.get(ENV_FILE_VARIABLE)
    if override:
        return Path(override).expanduser()
    return project_root / ".env"


def load_env_file(path: Path, *, override: bool = False) -> list[str]:
    """把 .env 注入 ``os.environ``，返回实际设置的变量名。

    默认不覆盖已存在的环境变量，保证命令行/shell 注入的值优先。
    """
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    applied: list[str] = []
    for key, value in parse_env_text(text).items():
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        applied.append(key)
    return applied
