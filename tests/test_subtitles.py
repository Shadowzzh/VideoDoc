"""字幕模块的纯逻辑测试：不联网、不碰 LLM。"""

from __future__ import annotations

import json

from videodoc import subtitles


def _segments(count: int) -> list[dict]:
    return [
        {
            "id": f"seg-{index:05d}",
            "start_sec": float(index),
            "end_sec": float(index) + 0.9,
            "text": f"line {index}",
        }
        for index in range(1, count + 1)
    ]


def test_normalize_mode():
    assert subtitles.normalize_mode("zh") == "zh"
    assert subtitles.normalize_mode("Bilingual") == "bilingual"
    assert subtitles.normalize_mode(None) == "none"
    assert subtitles.normalize_mode("bogus") == "none"
    assert subtitles.normalize_mode("") == "none"


def test_timestamps():
    assert subtitles.srt_timestamp(0) == "00:00:00,000"
    assert subtitles.srt_timestamp(3661.234) == "01:01:01,234"
    assert subtitles.vtt_timestamp(3661.234) == "01:01:01.234"
    # 负值不应产生非法时间码
    assert subtitles.srt_timestamp(-1) == "00:00:00,000"


def test_merge_keeps_source_timecodes():
    segments = _segments(2)
    # 模型给了错误的时间码字段，必须被忽略
    payload = {
        "translations": [
            {"id": "seg-00001", "text": "第一行", "start": 999, "end": 1000},
            {"id": "seg-00002", "text": "第二行"},
        ]
    }
    rows, missing = subtitles.merge_translations(segments, payload)
    assert missing == []
    assert rows[0]["start_sec"] == 1.0 and rows[0]["end_sec"] == 1.9
    assert rows[0]["target"] == "第一行"
    assert rows[1]["target"] == "第二行"


def test_merge_reports_missing_without_dropping_rows():
    segments = _segments(3)
    payload = {"translations": [{"id": "seg-00001", "text": "只有第一条"}]}
    rows, missing = subtitles.merge_translations(segments, payload)
    assert len(rows) == 3
    assert missing == ["seg-00002", "seg-00003"]
    assert rows[1]["target"] == ""


def test_merge_ignores_unknown_ids_and_bad_payload():
    segments = _segments(1)
    payload = {"translations": [{"id": "seg-99999", "text": "无关"}, {"id": "", "text": "空 id"}]}
    rows, missing = subtitles.merge_translations(segments, payload)
    assert missing == ["seg-00001"]
    assert rows[0]["target"] == ""

    rows, missing = subtitles.merge_translations(segments, None)
    assert missing == ["seg-00001"]


def test_translate_chunks_and_passes_context():
    segments = _segments(5)
    calls: list[list[dict]] = []

    def fake_call(messages):
        payload = json.loads(messages[1]["content"])
        calls.append(payload["segments"])
        return {
            "translations": [
                {"id": item["id"], "text": f"译 {item['text']}"} for item in payload["segments"]
            ]
        }

    logs: list[str] = []
    rows = subtitles.translate(segments, fake_call, log=logs.append, chunk_size=2)

    assert len(rows) == 5
    assert [len(chunk) for chunk in calls] == [2, 2, 1]
    # 第二块应带上第一块末尾的上下文
    second = json.loads(
        subtitles.build_messages(segments[2:4], rows[:2])[1]["content"]
    )
    assert len(second["previous_context"]) == 2
    assert any("翻译字幕第" in line for line in logs)


def test_write_srt_and_vtt(tmp_path):
    rows = [
        {"id": "a", "start_sec": 0.0, "end_sec": 1.5, "source": "hello", "target": "你好"},
        {"id": "b", "start_sec": 2.0, "end_sec": 3.25, "source": "world", "target": "世界"},
    ]
    srt = tmp_path / "zh.srt"
    subtitles.write_srt(rows, srt)
    text = srt.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:01,500\n你好" in text
    assert "2\n00:00:02,000 --> 00:00:03,250\n世界" in text

    bilingual = tmp_path / "bi.srt"
    subtitles.write_srt(rows, bilingual, bilingual=True)
    assert "你好\nhello" in bilingual.read_text(encoding="utf-8")

    vtt = tmp_path / "zh.vtt"
    subtitles.write_vtt(rows, vtt)
    body = vtt.read_text(encoding="utf-8")
    assert body.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.500" in body


def test_write_srt_falls_back_to_source_when_target_missing(tmp_path):
    rows = [{"id": "a", "start_sec": 0.0, "end_sec": 1.0, "source": "keep me", "target": ""}]
    path = tmp_path / "zh.srt"
    subtitles.write_srt(rows, path)
    assert "keep me" in path.read_text(encoding="utf-8")


def test_is_chinese_detects_cjk_ratio():
    assert subtitles.is_chinese([{"text": "这是中文内容"}]) is True
    assert subtitles.is_chinese([{"text": "this is english text"}]) is False
    # 中英混排但中文占多数
    assert subtitles.is_chinese([{"text": "这是中文内容 with some english"}]) is True
    assert subtitles.is_chinese([]) is False


def test_passthrough_rows_copies_source_and_timecodes():
    segments = _segments(2)
    rows = subtitles.passthrough_rows(segments)
    assert rows[0]["target"] == rows[0]["source"] == "line 1"
    assert rows[0]["start_sec"] == 1.0 and rows[0]["end_sec"] == 1.9
    assert len(rows) == 2
