"""配音对齐的纯逻辑测试：短段合并、吃间隙、变速上限。"""

from __future__ import annotations

from videodoc.dub.align import merge_short, plan, summarize


def _row(key: str, start: float, end: float, text: str = "") -> dict:
    return {"id": key, "start": start, "end": end, "target": text or f"{key}。"}


def test_merge_keeps_normal_segments():
    rows = [
        _row("a", 0.0, 2.0, "第一句。"),
        _row("b", 2.0, 5.0, "第二句。"),
    ]
    merged = merge_short(rows)
    assert [m["id"] for m in merged] == ["a", "b"]
    assert merged[0]["duration"] == 2.0
    assert merged[1]["duration"] == 3.0


def test_merge_absorbs_short_segment_forward():
    rows = [
        _row("a", 0.0, 2.0, "第一句。"),
        _row("b", 2.0, 2.3, "嗯。"),
        _row("c", 2.3, 5.0, "第三句。"),
    ]
    merged = merge_short(rows)
    assert [m["id"] for m in merged] == ["a", "b"]
    assert merged[1]["merged_ids"] == ["b", "c"]
    assert merged[1]["duration"] == 3.0


def test_merge_absorbs_tail_into_previous():
    rows = [
        _row("a", 0.0, 2.0, "第一句。"),
        _row("b", 2.0, 2.4, "抱歉。"),
    ]
    merged = merge_short(rows)
    assert len(merged) == 1
    assert merged[0]["merged_ids"] == ["a", "b"]
    assert merged[0]["duration"] == 2.4


def test_merge_strips_trailing_punctuation():
    rows = [
        _row("a", 0.0, 0.4, "对不起。"),
        _row("b", 0.4, 0.7, "实在忍不住。"),
        _row("c", 0.7, 3.0, "下一句。"),
    ]
    merged = merge_short(rows)
    assert merged[0]["target"] == "对不起，实在忍不住，下一句。"
    assert "。。" not in merged[0]["target"]


def test_merge_empty_input():
    assert merge_short([]) == []


def test_plan_leaves_short_take_untouched():
    rows = [{"id": "a", "start": 0.0, "end": 2.0, "duration": 2.0}]
    plans = plan(rows, {"a": 1.8})
    assert plans[0]["tempo"] == 1.0
    assert plans[0]["overflow"] is False
    assert plans[0]["end_shift"] == 0.0


def test_plan_compresses_within_limit():
    rows = [{"id": "a", "start": 0.0, "end": 2.0, "duration": 2.0}]
    plans = plan(rows, {"a": 2.2})
    assert plans[0]["tempo"] == 1.1
    assert plans[0]["overflow"] is False


def test_plan_uses_gap_when_overflowing():
    rows = [
        {"id": "a", "start": 0.0, "end": 2.0, "duration": 2.0},
        {"id": "b", "start": 2.5, "end": 4.5, "duration": 2.0},
    ]
    # 2.6 / 1.15 = 2.26，需要多 0.26 秒；下一段前有 0.5 秒间隙
    plans = plan(rows, {"a": 2.6, "b": 2.0})
    assert plans[0]["overflow"] is False
    assert abs(plans[0]["end_shift"] - 0.261) < 0.001
    assert plans[0]["gap"] == 0.5


def test_plan_flags_overflow_without_gap():
    rows = [
        {"id": "a", "start": 0.0, "end": 2.0, "duration": 2.0},
        {"id": "b", "start": 2.1, "end": 4.1, "duration": 2.0},
    ]
    # 3.0 / 1.15 = 2.61，需要多 0.61 秒；间隙只有 0.1 秒
    plans = plan(rows, {"a": 3.0, "b": 2.0})
    assert plans[0]["overflow"] is True
    assert plans[0]["tempo"] == 1.15


def test_plan_marks_missing_audio_as_overflow():
    rows = [{"id": "a", "start": 0.0, "end": 2.0, "duration": 2.0}]
    plans = plan(rows, {})
    assert plans[0]["overflow"] is True


def test_summarize_counts_modes():
    rows = [
        {"id": "a", "start": 0.0, "end": 2.0, "duration": 2.0},
        {"id": "b", "start": 2.5, "end": 4.5, "duration": 2.0},
        {"id": "c", "start": 4.7, "end": 6.7, "duration": 2.0},
    ]
    plans = plan(rows, {"a": 1.8, "b": 2.4, "c": 3.0})
    stats = summarize(plans)
    assert stats["total"] == 3
    assert stats["exact"] == 1
    assert stats["shifted"] == 1
    assert stats["overflow"] == 1
