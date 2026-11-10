"""对齐计划：短段合并、吃间隙、变速上限。

三条规则（来自 2026-11-09 的实测）：

1. **短段先合并，再合成。** 0.3 秒的段物理上只能念 2 个字，硬配出来是
   「抱歉」「对不起」这种丢意思的残句。合并发生在 TTS 之前，所以合并后
   要重新按合并时长算音节预算。
2. **偏短不加速。** 念短了就留白——停顿自然，加速刺耳。
3. **超时先吃间隙，再考虑重写。** 压到 ``max_tempo`` 仍放不下时，如果下一段
   前面有足够静音，就让它延后结束；实在没有才标记 ``overflow`` 交给调用方重写。
"""

from __future__ import annotations

from typing import Any

# 小于这个时长无法独立配音，需要和相邻段合并。
MIN_DURATION = 1.0
# 合并后的上限：再长就不像一句口播了，拆开更自然。
MAX_MERGE = 6.0
# 间隙判定容差，避免把 0.02 秒的抖动当成可用空间。
GAP_EPSILON = 0.05


def _combine(items: list[dict[str, Any]]) -> dict[str, Any]:
    """把若干相邻行合并成一个配音单元。"""
    first, last = items[0], items[-1]
    parts = []
    for item in items:
        text = str(item.get("target") or "").strip()
        # 去掉句末标点再拼接，避免出现「，。」这种叠标点
        parts.append(text.rstrip("。，,.!?！？"))
    return {
        "id": first["id"],
        "merged_ids": [str(item["id"]) for item in items],
        "start": float(first["start"]),
        "end": float(last["end"]),
        "duration": round(float(last["end"]) - float(first["start"]), 3),
        "target": "，".join(part for part in parts if part) + "。",
    }


def merge_short(
    rows: list[dict[str, Any]],
    min_duration: float = MIN_DURATION,
    max_merge: float = MAX_MERGE,
) -> list[dict[str, Any]]:
    """把过短的段合并成可配音的单元。

    输入行需要 ``id`` / ``start`` / ``end`` / ``target``（译文）。输出每项多出
    ``merged_ids`` 和 ``duration``，``target`` 是合并后的文本。
    """
    if not rows:
        return []

    groups: list[list[dict[str, Any]]] = []
    buf: list[dict[str, Any]] = []
    for row in rows:
        buf.append(row)
        span = float(buf[-1]["end"]) - float(buf[0]["start"])
        if span >= min_duration or span > max_merge:
            groups.append(buf)
            buf = []

    if buf:
        # 末尾剩余：优先并入最后一组，避免单独留下一个极短段
        if groups:
            groups[-1].extend(buf)
        else:
            groups.append(buf)

    return [_combine(group) for group in groups]


def plan(
    rows: list[dict[str, Any]],
    measured: dict[str, float],
    max_tempo: float = 1.15,
) -> list[dict[str, Any]]:
    """根据实测合成时长，给每个单元算 atempo 和是否溢出。

    ``measured`` 是 ``{id: 实际合成秒数}``。``overflow`` 为真表示压到上限仍放不下，
    调用方应重写这句而不是用更大的倍率硬凑。
    """
    plans: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        key = str(row.get("id") or "")
        duration = float(row.get("duration") or 0)
        actual = float(measured.get(key) or 0)

        next_start = None
        if index + 1 < len(rows):
            next_start = float(rows[index + 1].get("start") or 0)
        gap = max(0.0, (next_start - float(row.get("end") or 0))) if next_start is not None else 0.0

        if duration <= 0 or actual <= 0:
            plans.append({
                **row,
                "actual": actual,
                "needed": 0.0,
                "tempo": 1.0,
                "gap": round(gap, 3),
                "end_shift": 0.0,
                "overflow": True,
            })
            continue

        needed = actual / duration
        if needed <= 1.0:
            tempo, overflow, end_shift = 1.0, False, 0.0
        elif needed <= max_tempo:
            tempo, overflow, end_shift = needed, False, 0.0
        else:
            compressed = actual / max_tempo
            extra = compressed - duration
            if extra <= gap + GAP_EPSILON:
                tempo, overflow, end_shift = max_tempo, False, max(0.0, extra)
            else:
                tempo, overflow, end_shift = max_tempo, True, gap

        plans.append({
            **row,
            "actual": round(actual, 3),
            "needed": round(needed, 3),
            "tempo": round(tempo, 3),
            "gap": round(gap, 3),
            "end_shift": round(end_shift, 3),
            "overflow": overflow,
        })
    return plans


def summarize(plans: list[dict[str, Any]]) -> dict[str, int]:
    """统计处理分布，用于日志和测试断言。"""
    total = len(plans)
    return {
        "total": total,
        "exact": sum(1 for p in plans if p["tempo"] == 1.0 and not p["overflow"]),
        "compressed": sum(1 for p in plans if p["tempo"] > 1.0 and not p["overflow"]),
        "shifted": sum(1 for p in plans if p.get("end_shift", 0) > 0),
        "overflow": sum(1 for p in plans if p["overflow"]),
    }
