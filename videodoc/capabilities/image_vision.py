"""图像识别能力：本地 macOS Vision OCR + 云端视觉模型理解。

这是本仓库目前唯一的可插拔能力，用来验证「clone 就能用」的目标：
不装 macOS 也能用（只配 BaseURL + Key 走云端），关掉它也完全不影响流水线。

两条通道各写各的字段，互不替代，任何一路失败都非阻塞：

* 本地（``ocr_text``）：逐行精确文字，离线免费无配额；仅 macOS（需要 ``swift``）。
* 云端（``vision_text``）：AI 理解（画面/图表/界面），任何 OpenAI 兼容端点或原生协议。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

from ..integrations import vision_local, vision_remote
from ..integrations.vision_remote import PROTOCOLS, RemoteVisionConfig
from .base import Availability, Evidence, Field, FieldGroup, StepSpec, registry

CAPABILITY_KEY = "image_vision"
STEP_KEY = "ocr"
ENGINE_LOCAL = "local"
ENGINE_EXTERNAL = "external"
ENGINE_BOTH = "both"
ENGINE_AUTO = "auto"

DEFAULT_PROMPT = (
    "这是技术视频里的一帧画面。请用中文描述画面内容（图表、界面、走势、物体），"
    "并提取其中的文字、数值和标签。只依据图中可见内容，不要推测。"
)
DEFAULT_SCRIPT = Path(__file__).resolve().parent.parent / "integrations" / "vision_ocr.swift"
MAX_FRAMES_HARD_LIMIT = 24


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_text(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


# ---------------------------------------------------------------- 设置声明


def _groups() -> tuple[FieldGroup, ...]:
    return (
        FieldGroup(
            title="识别通道",
            description="决定任务里的图像证据从哪来；两条通道可以同时开。",
            fields=(
                Field(
                    key="engine",
                    label="通道",
                    type="select",
                    default=ENGINE_AUTO,
                    options=(
                        (ENGINE_AUTO, "自动（有本地用本地，配了云端就同时用）"),
                        (ENGINE_LOCAL, "仅本地（macOS Vision）"),
                        (ENGINE_EXTERNAL, "仅云端（外部视觉模型）"),
                        (ENGINE_BOTH, "本地文字 + 云端理解"),
                    ),
                    help="auto 在非 macOS 上会自动只用云端。",
                ),
            ),
        ),
        FieldGroup(
            title="本地（macOS Vision）",
            description="离线、免费、逐行精确；仅 macOS 可用（需要 swift）。其他平台会自动跳过这一路。",
            fields=(
                Field(key="local.enabled", label="启用本地 OCR", type="boolean", default=True),
                Field(
                    key="local.script",
                    label="OCR 脚本路径",
                    type="text",
                    placeholder="留空使用随包内置的 macOS Vision 脚本",
                    help="默认使用仓库内置脚本，一般不需要改。",
                ),
                Field(key="local.language", label="识别语言", type="text", default="zh-Hans,en-US"),
                Field(
                    key="local.level",
                    label="精度",
                    type="select",
                    default="accurate",
                    options=(("accurate", "accurate（默认）"), ("fast", "fast")),
                ),
            ),
        ),
        FieldGroup(
            title="云端（视觉模型理解）",
            description=(
                "任何 OpenAI 兼容端点都能填 BaseURL + Key 直接接；也可切原生协议。"
                "这一路是「clone 就能用」的关键：配好它，本服务不再依赖 macOS。"
            ),
            fields=(
                Field(
                    key="external.protocol",
                    label="协议",
                    type="select",
                    default="openai-chat",
                    options=tuple((item, item) for item in PROTOCOLS),
                    help="openai-chat 覆盖绝大多数兼容端点；openai-responses 对应 gpt-load 的 Responses 形态。",
                ),
                Field(
                    key="external.base_url",
                    label="BaseURL",
                    type="text",
                    placeholder="https://api.openai.com/v1",
                    help="含版本路径，例如 …/v1；协议路径（/chat/completions 等）会自动拼接。",
                ),
                Field(key="external.model", label="模型", type="text", placeholder="如 gpt-4o-mini / gemini-3.5-flash-lite"),
                Field(
                    key="external.api_key",
                    label="API Key",
                    type="password",
                    secret=True,
                    placeholder="粘贴明文 Key（留空表示保持不变）",
                    help="明文保存在设置文件里（权限 600），接口永不回显完整值。",
                ),
                Field(
                    key="external.api_key_file",
                    label="或 Key 文件路径",
                    type="text",
                    placeholder="~/.secrets/vision-key",
                    help="文件里放纯文本 Key 或 KEY=VALUE 均可。",
                ),
                Field(
                    key="external.extra_headers",
                    label="自定义 Header（一行一个，K: V）",
                    type="textarea",
                    help="部分网关需要额外头（如会话亲和头）。",
                ),
                Field(
                    key="external.prompt",
                    label="提示词",
                    type="textarea",
                    default=DEFAULT_PROMPT,
                    help="默认要求「只描述画面并提取文字，不得推测」。",
                ),
            ),
        ),
        FieldGroup(
            title="预算与重试",
            description="云端调用是有额度成本的，这里设的硬闸只影响本服务。",
            fields=(
                Field(
                    key="external.max_frames",
                    label="每任务云端上限（张）",
                    type="number",
                    default=12,
                    minimum=0,
                    maximum=MAX_FRAMES_HARD_LIMIT,
                ),
                Field(key="external.daily_budget", label="每日预算（次）", type="number", default=200, minimum=0, maximum=10000),
                Field(key="external.timeout_seconds", label="单张超时（秒）", type="number", default=90, minimum=5, maximum=900),
                Field(key="external.retries", label="重试次数", type="number", default=2, minimum=0, maximum=5),
                Field(key="external.max_tokens", label="输出 token 上限", type="number", default=1024, minimum=16, maximum=8192),
            ),
        ),
    )


def defaults() -> dict[str, Any]:
    """默认设置：环境变量提供兜底，页面保存的值优先（由 settings 层合并）。"""
    script = _env_text("VIDEODOC_OCR_SCRIPT")
    return {
        "engine": _env_text("VIDEODOC_VISION_ENGINE", ENGINE_AUTO),
        "local": {
            "enabled": True,
            "script": script or str(DEFAULT_SCRIPT),
            "language": _env_text("VIDEODOC_OCR_LANG", vision_local.DEFAULT_LANGUAGE),
            "level": _env_text("VIDEODOC_OCR_LEVEL", vision_local.DEFAULT_LEVEL),
            "timeout_seconds": _env_int("VIDEODOC_OCR_TIMEOUT", vision_local.DEFAULT_TIMEOUT_SECONDS),
        },
        "external": {
            "protocol": _env_text("VIDEODOC_VISION_PROTOCOL", "openai-chat"),
            "base_url": _env_text("VIDEODOC_VISION_BASE_URL"),
            "model": _env_text("VIDEODOC_VISION_MODEL"),
            "api_key": _env_text("VIDEODOC_VISION_API_KEY"),
            "api_key_file": _env_text("VIDEODOC_VISION_API_KEY_FILE"),
            "api_path": "",
            "extra_headers": {},
            "prompt": _env_text("VIDEODOC_VISION_PROMPT", DEFAULT_PROMPT),
            "timeout_seconds": _env_int("VIDEODOC_VISION_TIMEOUT", 90),
            "max_tokens": _env_int("VIDEODOC_VISION_MAX_TOKENS", 1024),
            "retries": _env_int("VIDEODOC_VISION_RETRIES", 2),
            "max_frames": _env_int("VIDEODOC_VISION_MAX_FRAMES", 12),
            "daily_budget": _env_int("VIDEODOC_VISION_DAILY_BUDGET", 200),
            "min_interval_seconds": 0,
        },
    }


# ---------------------------------------------------------------- 引擎装配


def local_config_from(settings: dict[str, Any]) -> vision_local.LocalVisionConfig:
    local = settings["local"]
    script = str(local.get("script") or "").strip()
    return vision_local.LocalVisionConfig(
        script=Path(script).expanduser() if script else DEFAULT_SCRIPT,
        language=str(local.get("language") or vision_local.DEFAULT_LANGUAGE),
        level=str(local.get("level") or vision_local.DEFAULT_LEVEL),
        timeout_seconds=int(local.get("timeout_seconds") or vision_local.DEFAULT_TIMEOUT_SECONDS),
    )


def remote_config_from(settings: dict[str, Any]) -> RemoteVisionConfig:
    external = settings["external"]
    key_file = str(external.get("api_key_file") or "").strip()
    return RemoteVisionConfig(
        protocol=str(external.get("protocol") or "openai-chat"),
        base_url=str(external.get("base_url") or "").strip(),
        model=str(external.get("model") or "").strip(),
        api_key=str(external.get("api_key") or "").strip()
        or _env_text("VIDEODOC_VISION_API_KEY"),
        api_key_file=Path(key_file).expanduser() if key_file else None,
        extra_headers=dict(external.get("extra_headers") or {}),
        timeout_seconds=int(external.get("timeout_seconds") or 90),
        max_tokens=int(external.get("max_tokens") or 1024),
        retries=int(external.get("retries") or 0),
        api_path=str(external.get("api_path") or "").strip(),
    )


def _external_configured(settings: dict[str, Any]) -> Availability:
    external = settings["external"]
    if not str(external.get("base_url") or "").strip():
        return Availability(False, "未配置图像识别 BaseURL")
    if not str(external.get("model") or "").strip():
        return Availability(False, "未配置图像识别模型")
    protocol = str(external.get("protocol") or "").strip()
    if protocol not in PROTOCOLS:
        return Availability(False, f"协议非法: {protocol or '（空）'}")
    if not remote_config_from(settings).resolved_api_key():
        return Availability(False, "未配置图像识别 Key")
    return Availability(True)


@dataclass(frozen=True)
class ResolvedEngine:
    engine: str | None
    local_reason: str
    external_reason: str

    def __str__(self) -> str:
        if self.engine is None:
            return f"无可用通道（本地：{self.local_reason}；云端：{self.external_reason}）"
        return self.engine


def resolve_engine(settings: dict[str, Any]) -> ResolvedEngine:
    requested = str(settings.get("engine") or ENGINE_AUTO)
    if settings["local"].get("enabled", True):
        local_ok, local_reason = local_config_from(settings).available()
    else:
        local_ok, local_reason = False, "设置里已关闭本地 OCR"
    external = _external_configured(settings)
    if requested == ENGINE_AUTO:
        if local_ok and external.available:
            return ResolvedEngine(ENGINE_BOTH, local_reason, external.reason)
        if local_ok:
            return ResolvedEngine(ENGINE_LOCAL, local_reason, external.reason)
        if external.available:
            return ResolvedEngine(ENGINE_EXTERNAL, local_reason, external.reason)
        return ResolvedEngine(None, local_reason, external.reason)
    if requested == ENGINE_LOCAL:
        return ResolvedEngine(ENGINE_LOCAL if local_ok else None, local_reason, external.reason)
    if requested == ENGINE_EXTERNAL:
        return ResolvedEngine(ENGINE_EXTERNAL if external.available else None, local_reason, external.reason)
    if requested == ENGINE_BOTH:
        if local_ok and external.available:
            return ResolvedEngine(ENGINE_BOTH, local_reason, external.reason)
        if local_ok:
            return ResolvedEngine(ENGINE_LOCAL, local_reason, external.reason)
        if external.available:
            return ResolvedEngine(ENGINE_EXTERNAL, local_reason, external.reason)
        return ResolvedEngine(None, local_reason, external.reason)
    return ResolvedEngine(None, f"未知通道: {requested}", external.reason)


# ---------------------------------------------------------------- 配额


class DailyQuota:
    """云端调用的每日硬预算（本地计数；与上游共享额度是两回事）。"""

    def __init__(self, path: Path, limit: int) -> None:
        self.path = path
        self.limit = max(int(limit), 0)
        self.used = 0
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict) or raw.get("date") != date.today().isoformat():
            return
        try:
            self.used = int(raw.get("used") or 0)
        except (TypeError, ValueError):
            self.used = 0

    def remaining(self) -> int:
        return 0 if self.limit <= 0 else max(self.limit - self.used, 0)

    def consume(self) -> None:
        self.used += 1
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"date": date.today().isoformat(), "used": self.used}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass


# ---------------------------------------------------------------- 能力实现


class ImageVisionCapability:
    key = CAPABILITY_KEY
    label = "图像识别"
    description = "把配图变成任务可用的图像证据：本地 macOS Vision 出精确文字，云端视觉模型出画面理解。"

    def defaults(self) -> dict[str, Any]:
        return defaults()

    def groups(self) -> tuple[FieldGroup, ...]:
        return _groups()

    def step(self) -> StepSpec:
        return StepSpec(key=STEP_KEY, label="图像证据（本地 OCR / 云端理解）", after="select_images")

    def artifact(self) -> tuple[str, str]:
        return (STEP_KEY, "ocr.json")

    def availability(self, settings: dict[str, Any]) -> Availability:
        resolved = resolve_engine(settings)
        if resolved.engine is None:
            return Availability(False, str(resolved))
        return Availability(True)

    def describe(self, settings: dict[str, Any]) -> str:
        resolved = resolve_engine(settings)
        parts: list[str] = []
        if resolved.engine in {ENGINE_LOCAL, ENGINE_BOTH}:
            local = local_config_from(settings)
            parts.append(
                f"swift {local.script} <frame> --lang {local.language} --level {local.level} --positions"
            )
        if resolved.engine in {ENGINE_EXTERNAL, ENGINE_BOTH}:
            parts.append(remote_config_from(settings).describe())
        return " ; ".join(parts) or "跳过（无可用图像识别通道）"

    def probe(self, settings: dict[str, Any]) -> dict[str, Any]:
        resolved = resolve_engine(settings)
        result: dict[str, Any] = {"capability": self.key, "engine": str(resolved)}
        if resolved.engine in {ENGINE_LOCAL, ENGINE_BOTH}:
            ok, reason = local_config_from(settings).available()
            result["local"] = {"ok": ok, "detail": reason or "可用"}
        if resolved.engine in {ENGINE_EXTERNAL, ENGINE_BOTH}:
            result["external"] = vision_remote.probe(remote_config_from(settings))
        if resolved.engine is None:
            return {**result, "ok": False, "detail": str(resolved)}
        ok = all(
            part.get("ok", True) for name, part in result.items() if name in {"local", "external"}
        )
        return {**result, "ok": ok}

    def evidence_text(self, image: dict[str, Any]) -> str:
        """把该图的证据拼成给文章提示词的文本块（字段名由本能力解释）。"""
        blocks: list[str] = []
        ocr_text = str(image.get("ocr_text") or "").strip()
        vision_text = str(image.get("vision_text") or "").strip()
        if ocr_text:
            blocks.append(f"[本地 OCR 逐行文字]\n{ocr_text}")
        if vision_text:
            provider = str(image.get("vision_provider") or "").strip()
            suffix = f"（{provider}）" if provider else ""
            blocks.append(f"[视觉模型理解{suffix}]\n{vision_text}")
        return "\n".join(blocks)

    def run(
        self,
        settings: dict[str, Any],
        images: list[dict[str, Any]],
        *,
        frame_dir: Path,
        log: Callable[[str], None],
        task_dir: Path,
    ) -> Evidence:
        resolved = resolve_engine(settings)
        log(f"图像证据通道：{resolved}")
        if not images:
            log("没有待处理的章节配图。")
            return Evidence(images=list(images))
        if resolved.engine is None:
            log("保留图片并跳过图像取证（可在设置页配置云端图像识别，或安装本地环境）。")
            return Evidence(images=[dict(image) for image in images])

        external = settings["external"]
        max_external_frames = int(external.get("max_frames") or 0)
        min_interval = float(external.get("min_interval_seconds") or 0)
        quota = DailyQuota(task_dir.parent.parent / "vision-quota.json", int(external.get("daily_budget") or 0))
        remote_config = (
            remote_config_from(settings) if resolved.engine in {ENGINE_EXTERNAL, ENGINE_BOTH} else None
        )
        local_config = local_config_from(settings) if resolved.engine in {ENGINE_LOCAL, ENGINE_BOTH} else None
        prompt = str(external.get("prompt") or "").strip()

        if remote_config is not None:
            log(
                f"云端视觉：{remote_config.describe()}；本任务上限 {max_external_frames} 张，"
                f"今日剩余预算 {quota.remaining()} 次"
            )
        if local_config is not None:
            log(f"本地视觉：{local_config.script}（lang={local_config.language}, level={local_config.level}）")

        completed: list[dict[str, Any]] = []
        external_done = 0
        last_external_at = 0.0
        for image in images:
            current = dict(image)
            frame_path = frame_dir / str(current.get("file", ""))
            if local_config is not None:
                started = time.monotonic()
                try:
                    current["ocr_text"] = vision_local.recognize(local_config, frame_path)
                    current["ocr_provider"] = "macos-vision"
                    current["ocr_elapsed_ms"] = int((time.monotonic() - started) * 1000)
                    current.pop("ocr_error", None)
                except (vision_local.LocalVisionError, OSError) as error:
                    current["ocr_error"] = str(error)
                    log(f"[本地] {current.get('file')} 失败（非阻塞）: {error}")

            if remote_config is not None:
                if external_done >= max_external_frames:
                    current.setdefault("vision_error", f"超出本任务云端上限（{max_external_frames} 张）。")
                elif quota.remaining() <= 0:
                    current.setdefault("vision_error", "今日云端图像识别预算已用完。")
                else:
                    if min_interval and last_external_at:
                        wait = min_interval - (time.monotonic() - last_external_at)
                        if wait > 0:
                            time.sleep(wait)
                    started = time.monotonic()
                    try:
                        result = vision_remote.analyze(remote_config, prompt, frame_path)
                    except (vision_remote.RemoteVisionError, OSError) as error:
                        current["vision_error"] = str(error)
                        log(f"[云端] {current.get('file')} 失败（非阻塞）: {error}")
                    else:
                        current["vision_text"] = result["text"]
                        current["vision_model"] = result["model"]
                        current["vision_provider"] = f"{remote_config.protocol}:{result['model']}"
                        current["vision_elapsed_ms"] = result["elapsed_ms"]
                        current.pop("vision_error", None)
                        external_done += 1
                        quota.consume()
                        last_external_at = time.monotonic()
                        log(f"[云端] {current.get('file')}: {result['text']}")
            completed.append(current)

        if remote_config is not None:
            log(f"云端视觉完成 {external_done} 张，今日已用 {quota.used}/{quota.limit}。")
        texts = {
            str(item.get("file")): self.evidence_text(item)
            for item in completed
            if str(item.get("file"))
        }
        return Evidence(images=completed, texts=texts)


image_vision = registry.register(ImageVisionCapability())
