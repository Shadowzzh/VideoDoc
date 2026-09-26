"""设置存储（与能力解耦）。

分工：

* ``.env`` / 环境变量：提供**默认值**（由各能力自带，见 ``capabilities/*.defaults()``）；
* ``settings.json``：页面里保存的值，**优先于**环境变量；
* 每个任务开始时重新读取 —— 页面改完即时生效，无需重启服务。

文件结构（点分 key 由设置页直接驱动）：

.. code-block:: json

    {
      "capabilities": {
        "image_vision": {"engine": "auto", "external.base_url": "…", "external.api_key": "…"}
      }
    }

历史文件里的顶层 ``vision`` 段会被自动迁移成 ``capabilities.image_vision``。

密钥策略：明文落盘（用户明确选择），文件权限 0600；接口永不回显完整值。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .capabilities import Field, registry
from .capabilities.base import _deep_merge

# 对外暴露（server.py 合并草稿设置时用）
deep_merge = _deep_merge

SETTINGS_FILE_VARIABLE = "VIDEODOC_SETTINGS_FILE"
DEFAULT_SETTINGS_PATH = Path.home() / ".config" / "videodoc" / "settings.json"
LEGACY_CAPABILITY_MAP = {"vision": "image_vision"}


class SettingsError(ValueError):
    """设置非法（会转成 HTTP 400，并直接展示给用户）。"""


# ---------------------------------------------------------------- 路径与读写


def settings_path(project_root: Path | None = None) -> Path:
    override = os.environ.get(SETTINGS_FILE_VARIABLE)
    if override:
        return Path(override).expanduser()
    if project_root is not None and (project_root / ".videodoc-settings.json").is_file():
        return project_root / ".videodoc-settings.json"
    return DEFAULT_SETTINGS_PATH


def default_settings() -> dict[str, Any]:
    return {"capabilities": registry.defaults()}


def load_file_settings(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        return {}, ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {}, f"设置文件无法读取，已忽略: {error}"
    if not isinstance(raw, dict):
        return {}, "设置文件内容不是 JSON 对象，已忽略。"
    return _migrate(raw), ""


def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """把历史结构（顶层 vision 段 / 嵌套值）迁移成点分 key 结构。"""
    payload: dict[str, Any] = {}
    capabilities = raw.get("capabilities")
    if isinstance(capabilities, dict):
        payload["capabilities"] = {
            str(key): _flatten(value if isinstance(value, dict) else {})
            for key, value in capabilities.items()
        }
    for old_key, new_key in LEGACY_CAPABILITY_MAP.items():
        section = raw.get(old_key)
        if not isinstance(section, dict):
            continue
        payload.setdefault("capabilities", {})[new_key] = _flatten(section)
    return payload


def _flatten(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """嵌套结构 → 点分 key（已是点分 key / 标量的原样保留）。"""
    flat: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}{key}"
        if isinstance(item, dict):
            flat.update(_flatten(item, prefix=f"{path}."))
        else:
            flat[path] = item
    return flat


def effective_settings(path: Path | None = None) -> dict[str, Any]:
    """默认值 + 文件覆盖（点分 key 在读取时展开回嵌套，便于能力直接取用）。"""
    target = path or settings_path()
    file_settings, _ = load_file_settings(target)
    merged = _deep_merge(default_settings(), file_settings)
    return _expand(merged)


def capability_settings(settings: dict[str, Any], key: str) -> dict[str, Any]:
    section = (settings.get("capabilities") or {}).get(key)
    return section if isinstance(section, dict) else {}


def _expand(payload: dict[str, Any]) -> dict[str, Any]:
    """点分 key → 嵌套结构。"""
    expanded: dict[str, Any] = {}
    for cap_key, section in (payload.get("capabilities") or {}).items():
        target: dict[str, Any] = {}
        for field_key, value in (section or {}).items():
            if "." not in field_key:
                target[field_key] = value
                continue
            head, _, tail = field_key.partition(".")
            branch = target.setdefault(head, {})
            if isinstance(branch, dict):
                branch[tail] = value
        expanded[cap_key] = target
    return {"capabilities": expanded}


def _flatten_for_save(section: dict[str, Any]) -> dict[str, Any]:
    """写入前统一成点分 key，避免嵌套与点分两种写法混存。"""
    return _flatten(section)


# ---------------------------------------------------------------- 校验


def _field_index() -> dict[str, dict[str, Field]]:
    index: dict[str, dict[str, Field]] = {}
    for category in registry.schema(default_settings()):
        fields: dict[str, Field] = {}
        for group in category["groups"]:
            for item in group["fields"]:
                fields[item["key"]] = Field(
                    key=item["key"],
                    label=item["label"],
                    type=item["type"],
                    help=item["help"],
                    placeholder=item["placeholder"],
                    options=tuple((option["value"], option["label"]) for option in item["options"]),
                    minimum=item["minimum"],
                    maximum=item["maximum"],
                    secret=item["secret"],
                )
        index[category["key"]] = fields
    return index


def _coerce(field: Field, value: Any) -> Any:
    if field.type == "boolean":
        if isinstance(value, bool):
            return value
        raise SettingsError(f"{field.label} 需要是 true/false。")
    if field.type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise SettingsError(f"{field.label} 需要是数字。")
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise SettingsError(f"{field.label} 需要是整数。") from None
        low = field.minimum if field.minimum is not None else 0
        high = field.maximum if field.maximum is not None else 10**9
        if number < low or number > high:
            raise SettingsError(f"{field.label} 需要在 {low}-{high} 之间（当前 {number}）。")
        return number
    if field.type == "select":
        text = "" if value is None else str(value).strip()
        allowed = [option[0] for option in field.options]
        if allowed and text not in allowed:
            raise SettingsError(f"{field.label} 只能是 {'/'.join(allowed)}。")
        return text
    if field.type == "textarea" and field.key.endswith("extra_headers"):
        return _as_headers(value)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SettingsError(f"{field.label} 需要是字符串。")
    return value.strip()


def _as_headers(value: Any) -> dict[str, str]:
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        parsed: dict[str, str] = {}
        for chunk in value.replace(";", "\n").splitlines():
            line = chunk.strip()
            if not line:
                continue
            key, _, val = line.partition(":") if ":" in line else line.partition("=")
            key, val = key.strip(), val.strip()
            if key:
                parsed[key] = val
        return _as_headers(parsed)
    if not isinstance(value, dict):
        raise SettingsError("自定义 header 需要是对象或 K: V 文本。")
    headers: dict[str, str] = {}
    for key, item in value.items():
        name = str(key).strip()
        if not name:
            continue
        text = "" if item is None else str(item).strip()
        if any(ch in name for ch in "\r\n:") or any(ch in text for ch in "\r\n"):
            raise SettingsError(f"自定义 header {name!r} 含有非法字符（换行或冒号）。")
        headers[name] = text
    return headers


def validate_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """校验页面提交的设置，返回可落盘的点分 key 结构（只处理出现的字段）。"""
    if not isinstance(payload, dict):
        raise SettingsError("设置需要是 JSON 对象。")
    unknown_top = set(payload) - {"capabilities", *LEGACY_CAPABILITY_MAP}
    if unknown_top:
        raise SettingsError(f"未知字段: {', '.join(sorted(unknown_top))}")
    incoming = _migrate(payload)

    index = _field_index()
    result: dict[str, Any] = {}
    for cap_key, section in (incoming.get("capabilities") or {}).items():
        if cap_key not in index:
            raise SettingsError(f"未知能力: {cap_key}")
        if not isinstance(section, dict):
            raise SettingsError(f"{cap_key} 的设置需要是对象。")
        clean: dict[str, Any] = {}
        for field_key, value in section.items():
            field = index[cap_key].get(field_key)
            if field is None:
                raise SettingsError(f"{cap_key} 下未知设置项: {field_key}")
            if field.secret and (value is None or str(value).strip() == ""):
                # 密钥留空 = 保持已保存的值不变（页面不回显密钥，无法回填）。
                continue
            clean[field_key] = _coerce(field, value)
        if clean:
            result.setdefault("capabilities", {})[cap_key] = clean
    return result


def _base_url_guard(clean: dict[str, Any]) -> None:
    """base_url 必须是 http(s)（防止 file:// 之类被页面写进来）。"""
    for field_key, value in clean.items():
        if field_key.endswith("base_url") and isinstance(value, str) and value:
            if not value.startswith(("http://", "https://")):
                raise SettingsError("BaseURL 必须以 http:// 或 https:// 开头。")


def save_settings(payload: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """校验后合并写入，返回写盘后的完整设置。"""
    target = path or settings_path()
    incoming = validate_settings(payload)
    for section in (incoming.get("capabilities") or {}).values():
        _base_url_guard(section)
    try:
        current_text = target.read_text(encoding="utf-8")
        current = _migrate(json.loads(current_text)) if current_text.strip() else {}
    except (OSError, json.JSONDecodeError):
        current = {}
    merged = _deep_merge(current, incoming)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, prefix=".settings-", delete=False
    )
    try:
        with handle:
            json.dump(merged, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(handle.name, 0o600)
        os.replace(handle.name, target)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
    return effective_settings(target)


# ---------------------------------------------------------------- 对外视图


def _secret_view(field_key: str, value: str) -> dict[str, Any]:
    return {
        f"{field_key}_configured": bool(value),
        f"{field_key}_hint": f"****{value[-4:]}" if len(value) >= 4 else "",
    }


def expand_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """把校验后的点分结构展开成嵌套结构（便于与 ``effective_settings()`` 合并）。"""
    return _expand(payload)


def redact_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """给浏览器看的设置：密钥只回「是否配置 + 末 4 位」；同时给出左侧分类声明。"""
    index = _field_index()
    view: dict[str, Any] = {}
    for cap_key, fields in index.items():
        section = capability_settings(settings, cap_key)
        flat = _flatten_for_save(section)
        public: dict[str, Any] = {}
        for field_key, field in fields.items():
            value = flat.get(field_key, "" if field.default is None else field.default)
            if field.secret:
                resolved = str(flat.get(field_key) or "")
                if not resolved:
                    # 允许能力用 Key 文件/环境变量兜底：这里只看文件是否配置了。
                    key_file = str(flat.get(field_key.replace("api_key", "api_key_file")) or "").strip()
                    if key_file:
                        path = Path(key_file).expanduser()
                        if path.is_file():
                            try:
                                resolved = path.read_text(encoding="utf-8").strip()
                            except OSError:
                                resolved = ""
                public.update(_secret_view(field_key, resolved))
                continue
            public[field_key] = value
        view[cap_key] = public
    return {
        "capabilities": view,
        "categories": registry.schema(settings),
        "settings_path": str(settings_path()),
    }
