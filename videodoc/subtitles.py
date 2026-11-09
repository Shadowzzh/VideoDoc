"""字幕生成：把转写分段翻译成中文，输出 SRT / VTT。

设计约束（来自 `apps/video-localization` 调研踩过的坑）：

* **译文按 ``segment_id`` 回填，模型不接触时间码。** 时间轴只来自转写结果，
  翻译只能改文本，不能合并、拆分或改起止时间。
* **按块翻译但带上文**：一次塞太多段会超输出预算，切成小块又会丢术语一致性，
  所以每块把上一块的末几段译文当上下文传进去。
* **缺译不丢段**：某段没有译文时保留原文并交给调用方记日志，整条字幕照常产出。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

MODES = ("none", "zh", "bilingual")
DEFAULT_MODE = "none"

# 每块的段数。240 段约 2500 token 输入；1155 段的长视频会被切成 10 块。
CHUNK_SEGMENTS = 120
# 传给下一块的上下文段数。
CONTEXT_SEGMENTS = 3

SYSTEM_PROMPT = (
    "你是专业字幕译者。把给定的口播逐条译成简体中文；原文已是简体中文时原样返回，不要改写。\n"
    "硬性要求：\n"
    "1. 只能返回 JSON：{\"translations\": [{\"id\": \"seg-00001\", \"text\": \"译文\"}]}\n"
    "2. id 必须与输入一一对应，不许新增、删除、合并或拆分条目。\n"
    "3. 不许输出时间码或任何额外字段。\n"
    "4. 译文要口语化、简洁，适合一行字幕阅读；不要加解释、不要音译人名之外的内容。\n"
    "5. 专有名词（型号、品牌、接口）保留原文。"
)


def normalize_mode(value: Any) -> str:
    """把外部输入收敛到合法模式；未知值按 ``none`` 处理。"""
    text = str(value or "").strip().lower()
    return text if text in MODES else DEFAULT_MODE


def srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def vtt_timestamp(seconds: float) -> str:
    return srt_timestamp(seconds).replace(",", ".")


def _chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def build_messages(
    segments: list[dict[str, Any]],
    context: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """构造一次翻译请求；``context`` 是上一块末尾的译文，用来保持术语一致。"""
    payload: dict[str, Any] = {
        "segments": [
            {"id": segment["id"], "text": str(segment.get("text") or "").strip()}
            for segment in segments
        ]
    }
    if context:
        payload["previous_context"] = [
            {"source": str(row.get("source") or ""), "target": str(row.get("target") or "")}
            for row in context
        ]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def merge_translations(
    segments: list[dict[str, Any]],
    payload: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """把模型返回的译文按 id 合并回原分段。

    返回 ``(rows, missing_ids)``。``rows`` 一定与输入分段等长、顺序一致；
    缺译的段落 ``target`` 为空串，由调用方决定回退策略。
    """
    translations: dict[str, str] = {}
    if isinstance(payload, dict):
        raw = payload.get("translations")
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                identifier = str(item.get("id") or "").strip()
                text = str(item.get("text") or "").strip()
                if identifier and text:
                    translations[identifier] = text

    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for segment in segments:
        identifier = str(segment.get("id") or "").strip()
        target = translations.get(identifier, "")
        if not target:
            missing.append(identifier)
        rows.append(
            {
                "id": identifier,
                # 时间码只从转写结果拷贝，不接受模型给的值。
                "start_sec": float(segment.get("start_sec") or 0.0),
                "end_sec": float(segment.get("end_sec") or 0.0),
                "source": str(segment.get("text") or "").strip(),
                "target": target,
            }
        )
    return rows, missing


def is_chinese(segments: list[dict[str, Any]], threshold: float = 0.2) -> bool:
    """判断转写内容是否已是中文。

    中文素材再走一遍「翻译成中文」纯属浪费，而且模型会顺手改写标点和措辞。

    用 CJK 占「CJK + 拉丁字母」的比例判断，而不是占全部字符：中文技术口播里
    型号和品牌（RTX 4060、DLSS）会拉低朴素占比，按全部字符算会把它们误判成英文。
    """
    text = "".join(str(segment.get("text") or "") for segment in segments)
    if not text:
        return False
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    latin = sum(1 for char in text if char.isascii() and char.isalpha())
    return cjk / max(1, cjk + latin) >= threshold


def passthrough_rows(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """不翻译，直接把原文当译文（时间码照抄）。"""
    return [
        {
            "id": str(segment.get("id") or ""),
            "start_sec": float(segment.get("start_sec") or 0.0),
            "end_sec": float(segment.get("end_sec") or 0.0),
            "source": str(segment.get("text") or "").strip(),
            "target": str(segment.get("text") or "").strip(),
        }
        for segment in segments
    ]


def translate(
    segments: list[dict[str, Any]],
    call: Callable[[list[dict[str, str]]], dict[str, Any]],
    *,
    log: Callable[[str], None] | None = None,
    chunk_size: int = CHUNK_SEGMENTS,
) -> list[dict[str, Any]]:
    """逐块翻译，返回与 ``segments`` 等长的行列表。

    ``call`` 接一组 messages 并返回解析后的 JSON 对象（流水线里就是 ``_call_llm``）。
    """
    rows: list[dict[str, Any]] = []
    total = len(segments)
    for index, chunk in enumerate(_chunks(segments, max(1, chunk_size)), start=1):
        if log:
            log(f"翻译字幕第 {index} 块（{len(chunk)} 段，累计 {len(rows)}/{total}）")
        context = rows[-CONTEXT_SEGMENTS:] if rows else []
        payload = call(build_messages(chunk, context))
        merged, missing = merge_translations(chunk, payload)
        if missing and log:
            log(f"第 {index} 块有 {len(missing)} 段没有译文，保留原文：{', '.join(missing[:5])}")
        rows.extend(merged)
    return rows


def _render(row: dict[str, Any], bilingual: bool) -> str:
    target = row.get("target") or row.get("source") or ""
    if not bilingual:
        return str(target)
    source = row.get("source") or ""
    return f"{target}\n{source}" if target and source else str(target or source)


def write_srt(rows: list[dict[str, Any]], path, *, bilingual: bool = False) -> None:
    blocks: list[str] = []
    for index, row in enumerate(rows, start=1):
        text = _render(row, bilingual)
        if not text.strip():
            continue
        blocks.append(
            f"{index}\n"
            f"{srt_timestamp(row['start_sec'])} --> {srt_timestamp(row['end_sec'])}\n"
            f"{text}"
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def write_vtt(rows: list[dict[str, Any]], path, *, bilingual: bool = False) -> None:
    blocks: list[str] = ["WEBVTT"]
    for row in rows:
        text = _render(row, bilingual)
        if not text.strip():
            continue
        blocks.append(
            f"{vtt_timestamp(row['start_sec'])} --> {vtt_timestamp(row['end_sec'])}\n{text}"
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "subtitle"
