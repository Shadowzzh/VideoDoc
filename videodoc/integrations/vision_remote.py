"""远端视觉引擎：把「一张图片 + 一段提示词」翻译成各家协议的原生请求。

为什么自己写这层：需要支持的协议只有四种，而内部形态只有
``{prompt, image_bytes, media_type}`` → ``{text, model, usage}``。
与其引入一个多协议 SDK（Node 的 Vercel AI SDK 或 Python 的 litellm），
不如按项目一贯的「零额外依赖」做法，用标准库 ``urllib`` 写一个薄适配层：
请求体构造、响应文本抽取各一段，全部可单测。

支持协议：

======================  ==============================  ==========================================
协议                    图片字段                        文本抽取位置
======================  ==============================  ==========================================
``openai-chat``         ``content[].image_url.url``     ``choices[0].message.content``
``openai-responses``    ``content[].input_image``        ``output[].content[].text``
``anthropic-messages``  ``content[].source(base64)``     ``content[].text``
``gemini-generateContent``  ``parts[].inline_data``      ``candidates[0].content.parts[].text``
======================  ==============================  ==========================================

``openai-chat`` 覆盖绝大多数「OpenAI 兼容」端点（本机 gpt-load、zen、火山、OpenRouter、
Ollama、vLLM……）；另三种用于原生协议。
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROTOCOLS: tuple[str, ...] = (
    "openai-chat",
    "openai-responses",
    "anthropic-messages",
    "gemini-generateContent",
)

PROTOCOL_LABELS: dict[str, str] = {
    "openai-chat": "OpenAI 兼容（chat/completions，最通用）",
    "openai-responses": "OpenAI Responses API（gpt-load 图像识别组用这个）",
    "anthropic-messages": "Anthropic Messages API",
    "gemini-generateContent": "Google Gemini generateContent",
}

DEFAULT_PATHS: dict[str, str] = {
    "openai-chat": "/chat/completions",
    "openai-responses": "/responses",
    "anthropic-messages": "/messages",
    "gemini-generateContent": "/models/{model}:generateContent",
}

# 探测端点：只列模型，不产生生成计费（尤其不消耗视觉额度）。
DEFAULT_PROBE_PATHS: dict[str, str] = {
    "openai-chat": "/models",
    "openai-responses": "/models",
    "anthropic-messages": "/models",
    "gemini-generateContent": "/models",
}

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT_SECONDS = 90
DEFAULT_MAX_TOKENS = 1024
DEFAULT_RETRIES = 2
USER_AGENT = "videodoc/0.1"


class RemoteVisionError(RuntimeError):
    """远端视觉调用失败（非阻塞：调用方记录成该图的 vision_error 后继续）。"""


@dataclass(frozen=True)
class RemoteVisionConfig:
    protocol: str
    base_url: str
    model: str
    api_key: str = ""
    api_key_file: Path | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_tokens: int = DEFAULT_MAX_TOKENS
    retries: int = DEFAULT_RETRIES
    api_path: str = ""

    def resolved_api_key(self) -> str:
        """优先用页面里填的明文 Key；没有再读 Key 文件。"""
        if self.api_key.strip():
            return self.api_key.strip()
        if self.api_key_file is not None:
            path = Path(self.api_key_file).expanduser()
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8").strip()
                except OSError:
                    return ""
                # 密钥文件可能写成 KEY=VALUE 或纯值，两种都认。
                if "=" in text and not text.startswith("sk-"):
                    return text.partition("=")[2].strip().strip("'\"")
                return text
        return ""

    def endpoint(self, *, probe: bool = False) -> str:
        table = DEFAULT_PROBE_PATHS if probe else DEFAULT_PATHS
        path = self.api_path.strip() if (self.api_path.strip() and not probe) else table[self.protocol]
        path = path.format(model=self.model)
        base = self.base_url.strip().rstrip("/")
        if base.endswith(path):
            return base
        if probe and self.api_path.strip() and not base.endswith("/models"):
            # 探测始终打 /models，避免用户自定义生成路径时误打生成端点。
            path = "/models"
        return f"{base}{path}"

    def describe(self) -> str:
        return f"{self.protocol} {self.endpoint()} model={self.model}"


def sniff_media_type(data: bytes, suffix: str = "") -> str:
    """按魔术字节判断图片类型，认不出时退回后缀/JPEG。"""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    lowered = suffix.lower().lstrip(".")
    if lowered in {"jpg", "jpeg"}:
        return "image/jpeg"
    if lowered in {"png", "gif", "webp"}:
        return f"image/{lowered}"
    return "image/jpeg"


def _auth_headers(config: RemoteVisionConfig, api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if config.protocol in {"openai-chat", "openai-responses"}:
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    elif config.protocol == "anthropic-messages":
        if api_key:
            headers["x-api-key"] = api_key
        headers["anthropic-version"] = ANTHROPIC_VERSION
    elif config.protocol == "gemini-generateContent":
        if api_key:
            headers["x-goog-api-key"] = api_key
    headers.update({str(k): str(v) for k, v in (config.extra_headers or {}).items()})
    return headers


def build_payload(
    config: RemoteVisionConfig,
    prompt: str,
    image_bytes: bytes,
    media_type: str,
) -> dict[str, Any]:
    """按协议构造请求体（纯函数，便于单测）。"""
    encoded = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{media_type};base64,{encoded}"
    if config.protocol == "openai-chat":
        return {
            "model": config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        }
    if config.protocol == "openai-responses":
        return {
            "model": config.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        }
    if config.protocol == "anthropic-messages":
        return {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
    if config.protocol == "gemini-generateContent":
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": media_type, "data": encoded}},
                    ],
                }
            ]
        }
    raise RemoteVisionError(f"不支持的协议: {config.protocol}")


def _join_text_parts(parts: Any) -> str:
    """把 [{type:'text',text:'…'}, …] 之类的结构拼成一段文字。"""
    if not isinstance(parts, list):
        return ""
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            text = part.get("text")
        else:
            text = getattr(part, "text", None)
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    return "\n".join(chunks)


def extract_text(protocol: str, body: dict[str, Any]) -> str:
    """从各家响应里抽正文（纯函数，便于单测）。"""
    if protocol == "openai-chat":
        choices = body.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        return _join_text_parts(content).strip()
    if protocol == "openai-responses":
        chunks: list[str] = []
        for item in body.get("output") or []:
            if not isinstance(item, dict):
                continue
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        chunks.append(text.strip())
        if chunks:
            return "\n".join(chunks).strip()
        fallback = body.get("output_text")
        return fallback.strip() if isinstance(fallback, str) else ""
    if protocol == "anthropic-messages":
        parts = [part for part in (body.get("content") or []) if isinstance(part, dict)]
        return _join_text_parts([part for part in parts if part.get("type") == "text"]).strip()
    if protocol == "gemini-generateContent":
        candidates = body.get("candidates") or []
        if not candidates:
            return ""
        content = candidates[0].get("content") or {}
        return _join_text_parts(content.get("parts")).strip()
    raise RemoteVisionError(f"不支持的协议: {protocol}")


def _is_image_path(path: Path) -> bool:
    return path.is_file()


def read_image(path: Path) -> tuple[bytes, str]:
    if not _is_image_path(path):
        raise RemoteVisionError(f"找不到图片: {path}")
    data = path.read_bytes()
    if not data:
        raise RemoteVisionError(f"图片为空: {path}")
    return data, sniff_media_type(data, path.suffix)


def _http_json(
    url: str,
    *,
    headers: dict[str, str],
    method: str = "POST",
    body: bytes | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RemoteVisionError(f"响应不是合法 JSON: {raw[:300]}") from error
    if not isinstance(parsed, dict):
        raise RemoteVisionError("响应 JSON 不是对象。")
    return parsed


def _redact(text: str, secret: str) -> str:
    if secret and len(secret) >= 8 and secret in text:
        return text.replace(secret, "***")
    return text


def analyze(
    config: RemoteVisionConfig,
    prompt: str,
    image_path: Path,
) -> dict[str, Any]:
    """调用一次远端视觉：返回 ``{text, model, usage, elapsed_ms, endpoint}``。"""
    image_bytes, media_type = read_image(Path(image_path))
    payload = build_payload(config, prompt, image_bytes, media_type)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    api_key = config.resolved_api_key()
    headers = _auth_headers(config, api_key)
    url = config.endpoint()

    last_error: Exception | None = None
    started = time.monotonic()
    for attempt in range(max(config.retries, 0) + 1):
        if attempt:
            time.sleep(min(2 ** attempt, 5))
        try:
            parsed = _http_json(url, headers=headers, body=body, timeout=config.timeout_seconds)
        except urllib.error.HTTPError as error:
            detail = _redact(error.read().decode("utf-8", errors="replace")[:600], api_key)
            message = f"HTTP {error.code}: {detail}"
            last_error = RemoteVisionError(message)
            if error.code in {408, 429, 500, 502, 503, 504}:
                continue
            raise last_error from error
        except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError, OSError) as error:
            last_error = RemoteVisionError(f"网络错误: {_redact(str(error), api_key)}")
            continue
        text = extract_text(config.protocol, parsed)
        if not text:
            raise RemoteVisionError("模型返回了空文本。")
        return {
            "text": text,
            "model": str(parsed.get("model") or config.model),
            "usage": parsed.get("usage") or {},
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "endpoint": url,
        }
    raise last_error or RemoteVisionError("远端视觉调用失败。")


def probe(config: RemoteVisionConfig) -> dict[str, Any]:
    """廉价连通性探测：只打 ``/models``，不消耗视觉额度。"""
    api_key = config.resolved_api_key()
    headers = _auth_headers(config, api_key)
    headers.pop("Content-Type", None)
    url = config.endpoint(probe=True)
    try:
        parsed = _http_json(url, headers=headers, method="GET", timeout=min(config.timeout_seconds, 20))
    except urllib.error.HTTPError as error:
        detail = _redact(error.read().decode("utf-8", errors="replace")[:300], api_key)
        return {"ok": False, "endpoint": url, "detail": f"HTTP {error.code}: {detail}"}
    except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError, OSError) as error:
        return {"ok": False, "endpoint": url, "detail": f"网络错误: {_redact(str(error), api_key)}"}
    except RemoteVisionError as error:
        return {"ok": False, "endpoint": url, "detail": str(error)}
    models = parsed.get("data") or parsed.get("models") or []
    count = len(models) if isinstance(models, list) else None
    return {
        "ok": True,
        "endpoint": url,
        "detail": f"可达（模型数 {count}）" if count is not None else "可达",
        "model_present": _model_present(parsed, config.model),
    }


def _model_present(body: dict[str, Any], model: str) -> bool | None:
    """探测结果里是否看得到配置的模型（看得到不代表权限一定有）。"""
    items = body.get("data") or body.get("models")
    if not isinstance(items, list) or not model:
        return None
    names: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            name = item.get("id") or item.get("name")
            if isinstance(name, str):
                names.add(name)
                names.add(name.rsplit("/", 1)[-1])
    return model in names


def api_key_from_environment() -> str:
    """远端视觉 Key 的兜底来源（页面没填时）。"""
    for name in ("VIDEODOC_VISION_API_KEY", "OPENCODE_GO_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""
