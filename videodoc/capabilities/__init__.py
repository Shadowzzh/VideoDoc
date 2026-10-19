"""可插拔能力注册表。

内置模块在此显式注册。**删掉一行 import 就等于整体移除该模块**：主流程不 import
任何具体实现，设置页左侧分类列表也随之少一项。

两类模块：

* ``register``：占流水线步骤位的能力（如图像识别）；
* ``register_section``：只提供设置、不占步骤位的分类（如文本模型）。
"""

from __future__ import annotations

from .base import (
    Availability,
    Capability,
    Evidence,
    Field,
    FieldGroup,
    Registry,
    Section,
    StepSpec,
    registry,
)
from . import image_vision  # noqa: F401  内置能力：图像识别（本地 Vision + 云端视觉）
from . import text_model  # noqa: F401  内置分类：文本模型接入点（大纲 / 正文）

__all__ = [
    "Availability",
    "Capability",
    "Evidence",
    "Field",
    "FieldGroup",
    "Registry",
    "Section",
    "StepSpec",
    "registry",
]
