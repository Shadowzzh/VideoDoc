"""可插拔能力的公共协议。

设计目标（2026-09-25 澄清）：**任何人 clone 这个仓库，只配一个 BaseURL + Key 就能用，
不必依赖 macOS、也不必依赖某台机器的既有资产。** 因此：

* 主流程只认注册表，不 import 任何具体能力；能力缺失/关闭时流水线照常跑完；
* 能力的**设置项自己声明**（字段类型、标签、帮助、选项），设置页据此通用渲染，
  左侧分类列表随注册的能力自动增减；
* 能力自己决定产物字段名与提示词片段，主流程不做字段级假设。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

# 字段类型：前端通用渲染用，校验在后端按同一类型做。
FIELD_TYPES = ("text", "password", "number", "select", "boolean", "textarea")


@dataclass(frozen=True)
class Field:
    """一个设置项。``key`` 是点分路径（如 ``external.base_url``），落盘时展开成嵌套结构。"""

    key: str
    label: str
    type: str = "text"
    help: str = ""
    placeholder: str = ""
    options: tuple[tuple[str, str], ...] = ()
    default: Any = None
    minimum: int | None = None
    maximum: int | None = None
    # 密钥字段：落盘保存，但接口永不回显，只回「已配置 + 末 4 位」。
    secret: bool = False
    # 只在同一分组内的某个字段取值匹配时展示（前端用；后端不强制）。
    show_when: tuple[str, str] | None = None


@dataclass(frozen=True)
class FieldGroup:
    """设置面板里的一组卡片。"""

    title: str
    fields: tuple[Field, ...]
    description: str = ""


@dataclass(frozen=True)
class StepSpec:
    """能力在流水线里占的步骤位。``after`` 是插入锚点（核心步骤 key）。"""

    key: str
    label: str
    after: str = "select_images"


@dataclass
class Evidence:
    """能力一次执行的产物。

    * ``images``：能力自己补好字段的图片列表（字段名由能力决定，主流程不解释）；
    * ``texts``：``{图片文件名: 证据文本}``，主流程按章节取用写进提示词；
    * ``artifacts``：要登记到任务产物的文件（``{名称: 相对路径}``）。
    """

    images: list[dict[str, Any]]
    texts: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Availability:
    """能力当前是否可用 + 不可用原因（原因会写进任务日志和设置页）。"""

    available: bool
    reason: str = ""


class Capability(Protocol):
    """能力协议。实现只要满足这些属性/方法即可被注册表与页面使用。"""

    key: str
    label: str
    description: str

    def defaults(self) -> dict[str, Any]:
        """该能力的默认设置（会被环境变量/设置文件覆盖）。"""

    def groups(self) -> tuple[FieldGroup, ...]:
        """设置页右侧的字段分组声明。"""

    def step(self) -> StepSpec:
        """占用的流水线步骤位。"""

    def artifact(self) -> tuple[str, str]:
        """产物登记名：(artifact_key, 文件名)。"""

    def availability(self, settings: dict[str, Any]) -> Availability:
        """在给定设置下是否可用。"""

    def describe(self, settings: dict[str, Any]) -> str:
        """步骤卡片上显示的「命令/端点」摘要。"""

    def probe(self, settings: dict[str, Any]) -> dict[str, Any]:
        """连通性探测：不允许消耗业务额度。"""

    def run(
        self,
        settings: dict[str, Any],
        images: list[dict[str, Any]],
        *,
        frame_dir,
        log: Callable[[str], None],
        task_dir,
    ) -> Evidence:
        """执行一次，返回产物。任何失败都要非阻塞降级，不得抛出让任务失败。"""


class Registry:
    """能力注册表：主流程、设置页、任务状态页都只通过它取能力。"""

    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}

    def register(self, capability: Capability) -> Capability:
        if capability.key in self._items:
            raise ValueError(f"能力 key 重复注册: {capability.key}")
        self._items[capability.key] = capability
        return capability

    def all(self) -> tuple[Capability, ...]:
        return tuple(self._items.values())

    def get(self, key: str) -> Capability | None:
        return self._items.get(key)

    def by_step(self, step_key: str) -> Capability | None:
        for capability in self._items.values():
            if capability.step().key == step_key:
                return capability
        return None

    def step_specs(self) -> tuple[StepSpec, ...]:
        return tuple(capability.step() for capability in self._items.values())

    def defaults(self) -> dict[str, Any]:
        """按能力 key 分组的默认设置（对应设置文件里的 capabilities.<key> 段）。"""
        return {capability.key: capability.defaults() for capability in self._items.values()}

    def schema(self, settings: dict[str, Any]) -> list[dict[str, Any]]:
        """设置页左侧分类列表 + 右侧字段声明（不含密钥值）。

        ``settings`` 是完整设置树；能力只拿到自己的那一段（``capabilities.<key>``）。
        """
        sections = settings.get("capabilities") or {}
        categories: list[dict[str, Any]] = []
        for capability in self._items.values():
            section = sections.get(capability.key) or {}
            availability = capability.availability(section)
            categories.append(
                {
                    "key": capability.key,
                    "label": capability.label,
                    "description": capability.description,
                    "available": availability.available,
                    "unavailable_reason": availability.reason,
                    "groups": [
                        {
                            "title": group.title,
                            "description": group.description,
                            "fields": [
                                {
                                    "key": item.key,
                                    "label": item.label,
                                    "type": item.type,
                                    "help": item.help,
                                    "placeholder": item.placeholder,
                                    "options": [{"value": v, "label": l} for v, l in item.options],
                                    "minimum": item.minimum,
                                    "maximum": item.maximum,
                                    "secret": item.secret,
                                    "show_when": (
                                        {"key": item.show_when[0], "value": item.show_when[1]}
                                        if item.show_when
                                        else None
                                    ),
                                }
                                for item in group.fields
                            ],
                        }
                        for group in capability.groups()
                    ],
                }
            )
        return categories


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# 全局注册表：主流程、设置页、任务状态页都只通过它取能力。
registry = Registry()
