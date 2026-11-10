"""配音设置：TTS 服务、声音、语气强度、字幕样式。

和 ``text_model`` 一样只实现 ``Section`` 协议——它不占流水线步骤位，而是
``dub`` 这一步怎么跑的参数。优先级仍是：**页面保存值 > 环境变量 > 内置默认**。

语气强度 ``tone`` 是 0–10 的整数，越大越口语化：

* 0–1 严格忠实，只做必要口语化
* 2–3 通顺，去掉书面语冗余
* 4–5 有趣（默认），感叹句和连接句允许轻吐槽
* 6–7 活泼，可以用流行梗
* 8–9 放飞，优先好玩
* 10 极端，以好玩为第一目标

它只影响**配音稿**，不影响字幕——字幕始终是忠实译文。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .base import Availability, Field, FieldGroup, registry

SECTION_KEY = "dub"
# 默认指向 workhorse 上的 ming-tts-web；换机器只改这一项。
DEFAULT_BASE_URL = "http://192.168.8.194:17863"
# 张子恒的克隆声音（clone / BASIC / 慢速）。
DEFAULT_VOICE_ID = "f3392eb2103749f78d57b70cfb399e24"
DEFAULT_TONE = 5
DEFAULT_MAX_TEMPO = 1.15
DEFAULT_DEMUCS = "demucs"
# 分离器：auto = 能连 Ray 就用 Ray，否则本地 demucs；local / ray 强制指定。
DEFAULT_SEPARATOR = "auto"
DEFAULT_RAY_SPOOL = "/data/demucs-dispatch"
DEFAULT_RAY_API = "http://host.docker.internal:8265"
# 背景音乐相对原音量的倍数：1.0 会盖住配音，0.4 保留氛围又不抢人声。
DEFAULT_BACKGROUND_GAIN = 0.4
USER_AGENT = "videodoc/0.1"


def _env_text(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class DubConfig:
    base_url: str
    voice_id: str
    tone: int
    max_tempo: float
    subtitle_bar: bool
    separate: bool
    demucs_command: str
    separator: str
    ray_spool: str
    ray_api: str
    background_gain: float

    def describe(self) -> str:
        return (f"{self.voice_id[:8]}… @ {self.base_url}，"
                f"语气 {self.tone}/10，变速上限 {self.max_tempo:.2f}x")


def _groups() -> tuple[FieldGroup, ...]:
    return (
        FieldGroup(
            title="配音服务",
            description=(
                "指向一个 ming-tts-web 实例。留空时用环境变量 "
                "VIDEODOC_DUB_BASE_URL / VIDEODOC_DUB_VOICE_ID，再退回内置默认。"
            ),
            fields=(
                Field(
                    key="base_url",
                    label="服务地址",
                    type="text",
                    placeholder=DEFAULT_BASE_URL,
                    help="含端口，例如 http://192.168.8.194:17863；不要带 /api 路径。",
                ),
                Field(
                    key="voice_id",
                    label="声音 ID",
                    type="text",
                    placeholder=DEFAULT_VOICE_ID,
                    help="在声音工作室里复制声音的 ID；不同声音对应不同音色和语速。",
                ),
            ),
        ),
        FieldGroup(
            title="生成参数",
            description="影响配音稿的写法和最终成片；改动后重新生成才会生效。",
            fields=(
                Field(
                    key="tone",
                    label="语气强度",
                    type="number",
                    default=DEFAULT_TONE,
                    minimum=0,
                    maximum=10,
                    help="0 最严肃，10 最放飞。只影响配音稿，字幕始终忠实翻译。",
                ),
                Field(
                    key="max_tempo",
                    label="变速上限",
                    type="number",
                    default=DEFAULT_MAX_TEMPO,
                    minimum=1.0,
                    maximum=1.3,
                    help="句子超时时最多压缩多少倍。超过 1.2 会有明显拉伸感。",
                ),
                Field(
                    key="subtitle_bar",
                    label="字幕黑条",
                    type="boolean",
                    default=True,
                    help="在画面底部铺一条半透明黑带。原片自带硬字幕时建议开启。",
                ),
                Field(
                    key="separate",
                    label="分离背景音乐",
                    type="boolean",
                    default=True,
                    help="用 demucs 把原人声剥掉、保留 BGM。关闭时直接替换整条音轨。",
                ),
                Field(
                    key="demucs_command",
                    label="demucs 命令",
                    type="text",
                    placeholder=DEFAULT_DEMUCS,
                    help="容器内可能叫 demucs 或绝对路径；留空时用环境变量。",
                ),
                Field(
                    key="separator",
                    label="分离方式",
                    type="select",
                    options=(
                        ("auto", "自动（优先 Ray）"),
                        ("local", "本地 CPU"),
                        ("ray", "强制 Ray GPU"),
                    ),
                    default=DEFAULT_SEPARATOR,
                    help="Ray 走 GPU，106 秒音频约 4 秒；本地 CPU 约 2 分钟。",
                ),
                Field(
                    key="background_gain",
                    label="背景音乐音量",
                    type="number",
                    default=DEFAULT_BACKGROUND_GAIN,
                    minimum=0,
                    maximum=1.5,
                    help="相对原音量的倍数：1.0 会盖住配音，0.4 保留氛围，0 等于静音。",
                ),
            ),
        ),
    )


def defaults() -> dict[str, Any]:
    return {
        "base_url": _env_text("VIDEODOC_DUB_BASE_URL", DEFAULT_BASE_URL),
        "voice_id": _env_text("VIDEODOC_DUB_VOICE_ID", DEFAULT_VOICE_ID),
        "tone": int(_env_float("VIDEODOC_DUB_TONE", DEFAULT_TONE)),
        "max_tempo": _env_float("VIDEODOC_DUB_MAX_TEMPO", DEFAULT_MAX_TEMPO),
        "subtitle_bar": _env_bool("VIDEODOC_DUB_SUBTITLE_BAR", True),
        "separate": _env_bool("VIDEODOC_DUB_SEPARATE", True),
        "demucs_command": _env_text("VIDEODOC_DEMUCS_COMMAND", DEFAULT_DEMUCS),
        "separator": _env_text("VIDEODOC_DUB_SEPARATOR", DEFAULT_SEPARATOR),
        "ray_spool": _env_text("VIDEODOC_DUB_RAY_SPOOL", DEFAULT_RAY_SPOOL),
        "ray_api": _env_text("VIDEODOC_DUB_RAY_API", DEFAULT_RAY_API),
        "background_gain": _env_float(
            "VIDEODOC_DUB_BACKGROUND_GAIN", DEFAULT_BACKGROUND_GAIN),
    }


def _section_of(settings: dict[str, Any]) -> dict[str, Any]:
    """兼容两种入参：完整设置（含 ``capabilities``）或单个设置段。"""
    if isinstance(settings, dict) and "capabilities" in settings:
        return settings.get("capabilities", {}).get(SECTION_KEY, {}) or {}
    return settings or {}


def config_from(settings: dict[str, Any]) -> DubConfig:
    """把设置面板的值和默认值合并成一个不可变配置。"""
    section = _section_of(settings)
    base = defaults()

    def pick(key: str) -> Any:
        value = section.get(key)
        return base[key] if value in (None, "") else value

    tone = int(pick("tone"))
    return DubConfig(
        base_url=str(pick("base_url")).rstrip("/"),
        voice_id=str(pick("voice_id")),
        tone=max(0, min(10, tone)),
        max_tempo=min(1.3, max(1.0, float(pick("max_tempo")))),
        subtitle_bar=bool(pick("subtitle_bar")),
        separate=bool(pick("separate")),
        demucs_command=str(pick("demucs_command")),
        separator=str(pick("separator")),
        ray_spool=str(pick("ray_spool")),
        ray_api=str(pick("ray_api")).rstrip("/"),
        background_gain=max(0.0, min(2.0, float(pick("background_gain")))),
    )


def availability(settings: dict[str, Any]) -> Availability:
    config = config_from(settings)
    if not config.base_url:
        return Availability(available=False, reason="未配置配音服务地址")
    if not config.voice_id:
        return Availability(available=False, reason="未选择声音")
    return Availability(available=True)


def probe(settings: dict[str, Any]) -> dict[str, Any]:
    """检查服务是否可达，顺带列出可用的声音数量。"""
    config = config_from(settings)
    result: dict[str, Any] = {"ok": False, "detail": ""}
    try:
        req = urllib.request.Request(
            f"{config.base_url}/api/status",
            headers={"User-Agent": USER_AGENT}, method="GET",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as error:
        return {**result, "detail": f"HTTP {error.code}"}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        return {**result, "detail": str(error)}

    voices = body.get("storage", {}).get("voices") if isinstance(body, dict) else None
    version = body.get("version") if isinstance(body, dict) else None
    detail = f"服务可用（v{version}，{voices} 个声音）" if version else "服务可用"
    return {**result, "ok": True, "detail": detail}


class DubSection:
    key = SECTION_KEY
    label = "配音"
    description = "把视频配上中文配音，保留背景音乐。"

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


dub = registry.register_section(DubSection())
