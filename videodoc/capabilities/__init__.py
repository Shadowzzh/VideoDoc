"""可插拔能力注册表。

内置能力在此显式注册。**删掉一行 import 就等于整体移除该能力**：主流程不 import
任何具体能力，设置页左侧分类列表也随之少一项。
"""

from __future__ import annotations

from .base import (
    Availability,
    Capability,
    Evidence,
    Field,
    FieldGroup,
    Registry,
    StepSpec,
    registry,
)
from . import image_vision  # noqa: F401  内置能力：图像识别（本地 Vision + 云端视觉）

__all__ = [
    "Availability",
    "Capability",
    "Evidence",
    "Field",
    "FieldGroup",
    "Registry",
    "StepSpec",
    "registry",
]
