"""文本模型接入点：大纲和正文用的 LLM 配置。

**它不是流水线的一步**，而是核心步骤（outline / article）怎么发请求的设置，
所以只实现 ``Section`` 协议（设置页分类），不占步骤位。

优先级由 settings 层统一合并：**页面保存的值 > 环境变量 > 内置默认**。
内置默认指向 DeepSeek 官方端点；任何 OpenAI 兼容端点都能改 BaseURL 直接接
（本机 gpt-load、opencode zen、火山、OpenRouter、Ollama……）。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..integrations.api_key import resolve_api_key
from .base import Availability, Field, FieldGroup, registry

SECTION_KEY = "text_model"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_RETRIES = 3
USER_AGENT = "videodoc/0.1"


def _env_text(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def llm_api_key() -> str | None:
    """环境变量里的 LLM API Key；兼容旧的 ``OPENCODE_GO_API_KEY`` 变量名。"""
    return _env_text("VIDEODOC_LLM_API_KEY") or _env_text("OPENCODE_GO_API_KEY") or None


# ---------------------------------------------------------------- 设置声明


def _groups() -> tuple[FieldGroup, ...]:
    return (
        FieldGroup(
            title="接入点",
            description=(
                "大纲和正文都发到这里。留空时用环境变量 VIDEODOC_LLM_BASE_URL / "
                "VIDEODOC_LLM_MODEL，再退回内置默认值。"
            ),
            fields=(
                Field(
                    key="base_url",
                    label="BaseURL",
                    type="text",
                    placeholder=DEFAULT_BASE_URL,
                    help="含版本路径，例如 …/v1；协议路径（/chat/completions）会自动拼接。",
                ),
                Field(
                    key="model",
                    label="模型",
                    type="text",
                    placeholder=DEFAULT_MODEL,
                    help="如 deepseek-v4.1-flash / deepseek-v4-flash。",
                ),
            ),
        ),
        FieldGroup(
            title="凭据",
            description="页面里的明文 Key 优先；也可以指向一个密钥文件（不进 Git）。",
            fields=(
                Field(
                    key="api_key",
                    label="API Key",
                    type="password",
                    secret=True,
                    placeholder="粘贴明文 Key（留空表示保持不变）",
                    help=(
                        "明文保存在设置文件里（权限 600），接口永不回显完整值。"
                        "两者都留空时用环境变量 VIDEODOC_LLM_API_KEY / OPENCODE_GO_API_KEY。"
                    ),
                ),
                Field(
                    key="api_key_file",
                    label="或 Key 文件路径",
                    type="text",
                    placeholder="~/.secrets/ai.env",
                    help="文件里放纯文本 Key 或 KEY=VALUE 均可。",
                ),
            ),
        ),
        FieldGroup(
            title="请求",
            description="长文章会逐章调用模型，超时和重试按最慢的一章设。",
            fields=(
                Field(
                    key="timeout_seconds",
                    label="单次超时（秒）",
                    type="number",
                    default=DEFAULT_TIMEOUT_SECONDS,
                    minimum=10,
                    maximum=3600,
                ),
                Field(
                    key="retries",
                    label="失败重试次数",
                    type="number",
                    default=DEFAULT_RETRIES,
                    minimum=0,
                    maximum=10,
                    help="只对网络类错误重试；HTTP 4xx 直接失败。",
                ),
            ),
        ),
    )


def defaults() -> dict[str, Any]:
    """默认设置：环境变量提供兜底，页面保存的值优先（由 settings 层合并）。

    ★ Key 不放进默认值。若把环境变量里的 Key 当成 ``api_key`` 的默认值，它会盖过
    页面里显式配的 ``api_key_file``（明文优先于文件），用户就会看到「配了文件却不
    生效」。所以环境变量只在 ``resolved_api_key()`` 里作为最后兜底。
    """
    return {
        "base_url": _env_text("VIDEODOC_LLM_BASE_URL", DEFAULT_BASE_URL),
        "model": _env_text("VIDEODOC_LLM_MODEL", DEFAULT_MODEL),
        "api_key": "",
        "api_key_file": _env_text("VIDEODOC_LLM_API_KEY_FILE"),
        "timeout_seconds": _env_int("VIDEODOC_LLM_TIMEOUT", DEFAULT_TIMEOUT_SECONDS),
        "retries": _env_int("VIDEODOC_LLM_RETRIES", DEFAULT_RETRIES),
    }


# ---------------------------------------------------------------- 装配


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class TextModelConfig:
    base_url: str
    model: str
    api_key: str = ""
    api_key_file: Path | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    retries: int = DEFAULT_RETRIES

    def resolved_api_key(self) -> str:
        """页面里填的（明文 > Key 文件）优先，都没有才回落到环境变量。"""
        return resolve_api_key(self.api_key, self.api_key_file) or (llm_api_key() or "")

    def endpoint(self) -> str:
        base = self.base_url.strip().rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def probe_url(self) -> str:
        """探测端点：始终打 ``/models``，不产生生成计费。"""
        base = self.base_url.strip().rstrip("/")
        for suffix in ("/chat/completions", "/completions"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        return f"{base}/models"

    def describe(self) -> str:
        return f"POST {self.endpoint()} model={self.model}"


def config_from(settings: dict[str, Any]) -> TextModelConfig:
    """从设置段（``capabilities.text_model``）装配出一次调用要用的配置。"""
    key_file = str(settings.get("api_key_file") or "").strip()
    return TextModelConfig(
        base_url=str(settings.get("base_url") or "").strip(),
        model=str(settings.get("model") or "").strip(),
        api_key=str(settings.get("api_key") or "").strip(),
        api_key_file=Path(key_file).expanduser() if key_file else None,
        timeout_seconds=_as_int(settings.get("timeout_seconds"), DEFAULT_TIMEOUT_SECONDS),
        retries=_as_int(settings.get("retries"), DEFAULT_RETRIES),
    )


def availability(settings: dict[str, Any]) -> Availability:
    config = config_from(settings)
    if not config.base_url:
        return Availability(False, "未配置文本模型 BaseURL")
    if not config.model:
        return Availability(False, "未配置文本模型")
    if not config.resolved_api_key():
        return Availability(False, "未配置文本模型 Key")
    return Availability(True)


def probe(settings: dict[str, Any]) -> dict[str, Any]:
    """廉价连通性探测：只打 ``/models``，不消耗生成额度。"""
    config = config_from(settings)
    result: dict[str, Any] = {
        "capability": SECTION_KEY,
        "endpoint": config.probe_url(),
        "model": config.model,
    }
    state = availability(settings)
    if not state.available:
        return {**result, "ok": False, "detail": state.reason}
    request = urllib.request.Request(
        config.probe_url(),
        headers={
            "Authorization": f"Bearer {config.resolved_api_key()}",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=max(5, min(config.timeout_seconds, 20))
        ) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:300]
        return {**result, "ok": False, "detail": f"HTTP {error.code}: {detail}"}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {**result, "ok": False, "detail": str(error)}

    models: list[str] = []
    try:
        parsed = json.loads(body)
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if isinstance(data, list):
            models = [str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")]
    except json.JSONDecodeError:
        models = []
    listed = f"（列出 {len(models)} 个模型）" if models else ""
    miss = f"；未列出 {config.model}" if models and config.model not in models else ""
    return {**result, "ok": True, "detail": f"可用{listed}{miss}", "models": models[:50]}


# ---------------------------------------------------------------- 注册


class TextModelSection:
    key = SECTION_KEY
    label = "文本模型"
    description = "生成大纲和正文的 LLM 接入点；任何 OpenAI 兼容端点都行。"

    def defaults(self) -> dict[str, Any]:
        return defaults()

    def groups(self) -> tuple[FieldGroup, ...]:
        return _groups()

    def availability(self, settings: dict[str, Any]) -> Availability:
        return availability(settings)

    def describe(self, settings: dict[str, Any]) -> str:
        return config_from(settings).describe()

    def probe(self, settings: dict[str, Any]) -> dict[str, Any]:
        return probe(settings)


text_model = registry.register_section(TextModelSection())
