import json
import io
import sys
import urllib.error
from pathlib import Path

import pytest

from videodoc.pipeline import (
    PipelineConfig,
    PipelineError,
    VideoArticlePipeline,
    choose_section_images,
    extract_json_object,
    format_transcript_lines,
    merge_transcript_lines,
    normalize_outline,
    parse_srt,
    strip_leading_markdown_heading,
    transcript_for_prompt,
)
from videodoc.task_store import TaskStore


SRT = """1
00:00:00,000 --> 00:00:04,200
开场介绍

2
00:00:04,200 --> 00:00:12,500
准备树莓派和墨水屏

3
00:00:12,500 --> 00:00:20,000
开始安装和配置
"""


def test_parse_srt_builds_stable_segment_ids():
    segments = parse_srt(SRT)

    assert [item["id"] for item in segments] == ["seg-00001", "seg-00002", "seg-00003"]
    assert segments[1]["start_sec"] == pytest.approx(4.2)
    assert segments[2]["end_sec"] == pytest.approx(20.0)


def test_normalize_outline_resolves_segment_times():
    segments = parse_srt(SRT)
    payload = {
        "title": "测试视频",
        "summary": "完整流程",
        "sections": [
            {
                "title": "开场",
                "summary": "介绍目标",
                "start_segment_id": "seg-00001",
                "end_segment_id": "seg-00001",
            },
            {
                "title": "制作",
                "summary": "准备并安装",
                "start_segment_id": "seg-00002",
                "end_segment_id": "seg-00003",
            },
        ],
    }

    outline = normalize_outline(payload, segments)

    assert outline["sections"][1]["start_sec"] == pytest.approx(4.2)
    assert outline["sections"][1]["end_time"] == "00:20"


def test_normalize_outline_rejects_unknown_segment():
    segments = parse_srt(SRT)
    payload = {
        "sections": [
            {
                "start_segment_id": "seg-99999",
                "end_segment_id": "seg-99999",
            }
        ]
    }

    with pytest.raises(PipelineError, match="不存在"):
        normalize_outline(payload, segments)


def test_normalize_outline_accepts_equivalent_segment_id_format():
    segments = parse_srt(SRT)
    payload = {
        "sections": [
            {
                "title": "开场",
                "start_segment_id": "segment_1",
                "end_segment_id": "seg-3",
            }
        ]
    }

    outline = normalize_outline(payload, segments)

    assert outline["sections"][0]["start_segment_id"] == "seg-00001"
    assert outline["sections"][0]["end_segment_id"] == "seg-00003"


def test_choose_section_images_uses_frames_inside_section():
    outline = {
        "sections": [
            {"id": "section-01", "title": "开场", "start_sec": 0.0, "end_sec": 10.0},
            {"id": "section-02", "title": "安装", "start_sec": 10.0, "end_sec": 20.0},
        ]
    }
    frames = [
        {"file": "frame_001.jpg", "timestamp_sec": 2.0},
        {"file": "frame_002.jpg", "timestamp_sec": 12.0},
        {"file": "frame_003.jpg", "timestamp_sec": 18.0},
    ]

    images = choose_section_images(outline, frames, max_images=10)

    assert [item["file"] for item in images] == ["frame_001.jpg", "frame_002.jpg"]
    assert images[1]["section_id"] == "section-02"


def build_long_video_segments(count: int) -> list[dict]:
    """构造与真实长视频同构的片段：约 2 秒一片、每片 8-9 字。"""
    segments = []
    for index in range(count):
        start = index * 2.0
        segments.append(
            {
                "id": f"seg-{index + 1:05d}",
                "start_sec": start,
                "end_sec": start + 2.0,
                "text": "这是一段测试用的中文转写内容",
            }
        )
    return segments


def test_transcript_for_prompt_keeps_line_per_segment_within_budget():
    segments = parse_srt(SRT)

    value = transcript_for_prompt(segments)

    # 未超预算时行为不变：仍是一行一个片段
    assert value.splitlines() == format_transcript_lines(segments)
    assert value.startswith("[seg-00001 00:00-00:04] 开场介绍")


def test_transcript_for_prompt_merges_when_over_budget():
    segments = build_long_video_segments(4000)
    per_segment = "\n".join(format_transcript_lines(segments))
    assert len(per_segment) > 120_000  # 前置条件：逐条渲染确实超限

    value = transcript_for_prompt(segments)

    lines = value.splitlines()
    assert len(lines) < len(segments) / 10  # 已显著合并
    # 块头仍指向真实首尾片段，normalize_outline 能据此还原时间范围
    # 每片 2 秒、窗口 30 秒 → 每块 15 片，边界正好落在 00:30 / 01:00
    assert lines[0].startswith("[seg-00001 00:00-00:30]")
    assert lines[1].startswith("[seg-00016 00:30-01:00]")
    # 文字不丢：合并后正文字符数与原文字符总数一致
    merged_text = "".join(line.split("] ", 1)[1] for line in lines)
    assert merged_text == "".join(item["text"] for item in segments)


def test_transcript_for_prompt_still_rejects_when_merging_is_not_enough():
    segments = build_long_video_segments(6000)

    with pytest.raises(PipelineError) as error:
        transcript_for_prompt(segments, max_chars=20_000)

    # 不静默截断：报错里同时给出合并前与合并后的长度
    assert "20 秒窗口" in str(error.value) or "30 秒窗口" in str(error.value)
    assert "合并前" in str(error.value)


def test_merged_transcript_still_resolves_outline_segment_ids():
    segments = build_long_video_segments(4000)
    merged_lines = merge_transcript_lines(segments, 30.0)
    ids = [line.split(" ", 1)[0].lstrip("[") for line in merged_lines]

    payload = {
        "title": "长视频",
        "summary": "合并后仍需能生成合法大纲",
        "sections": [
            {
                "title": "第一章",
                "summary": "开头",
                "start_segment_id": ids[0],
                "end_segment_id": ids[1],
            },
            {
                "title": "第二章",
                "summary": "结尾",
                "start_segment_id": ids[-2],
                "end_segment_id": ids[-1],
            },
        ],
    }

    outline = normalize_outline(payload, segments)

    assert outline["sections"][0]["end_sec"] > outline["sections"][0]["start_sec"]
    assert outline["sections"][1]["end_sec"] > outline["sections"][0]["end_sec"]


def test_extract_json_object_accepts_fenced_json():
    payload = extract_json_object("```json\n{\"ok\": true}\n```")

    assert payload == {"ok": True}


def test_extract_json_object_rejects_non_json():
    with pytest.raises(PipelineError):
        extract_json_object("没有结构化数据")


def test_strip_leading_markdown_heading_removes_duplicate_title():
    body = "## 硬件组件\n\n正文第一段。\n\n- 项目一"

    assert strip_leading_markdown_heading(body) == "正文第一段。\n\n- 项目一"


def test_bilibili_yt_dlp_prefix_inherits_system_proxy_by_default(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://www.bilibili.com/video/BV1234567890")
    pipeline = VideoArticlePipeline(store, task["id"], PipelineConfig())

    monkeypatch.delenv("VIDEODOC_BILIBILI_PROXY", raising=False)
    command = pipeline._yt_dlp_prefix(use_cookies=False)

    # 默认不传 --proxy：yt-dlp 自动继承 http_proxy/https_proxy 系统代理
    assert "--proxy" not in command
    assert "Referer:https://www.bilibili.com/" in command


def test_bilibili_yt_dlp_prefix_respects_explicit_proxy(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://www.bilibili.com/video/BV1234567890")
    pipeline = VideoArticlePipeline(store, task["id"], PipelineConfig())

    monkeypatch.setenv("VIDEODOC_BILIBILI_PROXY", "http://127.0.0.1:7890")
    command = pipeline._yt_dlp_prefix(use_cookies=False)

    assert command[command.index("--proxy") + 1] == "http://127.0.0.1:7890"
    assert "Referer:https://www.bilibili.com/" in command


def test_youtube_yt_dlp_prefix_keeps_environment_proxy(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://www.youtube.com/watch?v=test")
    pipeline = VideoArticlePipeline(store, task["id"], PipelineConfig())

    command = pipeline._yt_dlp_prefix(use_cookies=False)

    assert "--proxy" not in command


def test_yt_dlp_command_defaults_to_current_interpreter(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://www.bilibili.com/video/BV1")
    pipeline = VideoArticlePipeline(store, task["id"], PipelineConfig())

    assert pipeline._yt_dlp_command() == [sys.executable, "-m", "yt_dlp"]


def test_yt_dlp_command_respects_config_python_module(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://www.bilibili.com/video/BV1")
    config = PipelineConfig(yt_dlp_python_module=Path("/opt/custom/python"))
    pipeline = VideoArticlePipeline(store, task["id"], config)

    assert pipeline._yt_dlp_command() == ["/opt/custom/python", "-m", "yt_dlp"]


def test_yt_dlp_command_respects_environment_override(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://www.bilibili.com/video/BV1")
    pipeline = VideoArticlePipeline(store, task["id"], PipelineConfig())

    monkeypatch.setenv("VIDEODOC_YT_DLP", "/usr/local/bin/yt-dlp --no-update")
    assert pipeline._yt_dlp_command() == ["/usr/local/bin/yt-dlp", "--no-update"]


def test_probe_records_yt_dlp_version(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://www.bilibili.com/video/BV1")
    pipeline = VideoArticlePipeline(store, task["id"], PipelineConfig())
    pipeline._yt_dlp_version = lambda: "2026.8.19"  # type: ignore[method-assign]

    def fake_run_yt_dlp(step, arguments, capture):
        # 模拟 yt-dlp 生成 source.info.json（真实流程由 --write-info-json 产出）
        source_info = pipeline.task_dir / "private" / "source.info.json"
        source_info.parent.mkdir(parents=True, exist_ok=True)
        source_info.write_text(json.dumps({"id": "BV1", "title": "t"}), encoding="utf-8")
        return '{"id": "BV1", "title": "t", "extractor_key": "bilibili", "duration": 10}'

    pipeline._run_yt_dlp_with_fallback = fake_run_yt_dlp  # type: ignore[method-assign]

    pipeline._probe()

    log = store.log_tail(task["id"], "probe")
    assert "yt-dlp 2026.8.19" in log


def test_check_yt_dlp_up_to_date_warns_when_behind(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://www.bilibili.com/video/BV1")
    pipeline = VideoArticlePipeline(store, task["id"], PipelineConfig())
    pipeline._yt_dlp_version = lambda: "2026.07.04"  # type: ignore[method-assign]
    pipeline._latest_yt_dlp_version = lambda: "2026.8.19"  # type: ignore[method-assign]

    pipeline._check_yt_dlp_up_to_date("probe")

    log = store.log_tail(task["id"], "probe")
    assert "落后于最新 2026.8.19" in log


def test_check_yt_dlp_up_to_date_silent_when_current(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://www.bilibili.com/video/BV1")
    pipeline = VideoArticlePipeline(store, task["id"], PipelineConfig())
    pipeline._yt_dlp_version = lambda: "2026.8.19"  # type: ignore[method-assign]
    pipeline._latest_yt_dlp_version = lambda: "2026.8.19"  # type: ignore[method-assign]

    pipeline._check_yt_dlp_up_to_date("probe")

    log = store.log_tail(task["id"], "probe")
    assert "已是最新版本" in log


def test_check_yt_dlp_up_to_date_handles_network_failure(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://www.bilibili.com/video/BV1")
    pipeline = VideoArticlePipeline(store, task["id"], PipelineConfig())
    pipeline._yt_dlp_version = lambda: "2026.8.19"  # type: ignore[method-assign]
    pipeline._latest_yt_dlp_version = lambda: None  # type: ignore[method-assign]

    pipeline._check_yt_dlp_up_to_date("probe")

    log = store.log_tail(task["id"], "probe")
    assert "无法连接 PyPI" in log


def test_pipeline_orchestration_builds_article_with_real_frame_path(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")

    class FakePipeline(VideoArticlePipeline):
        def _probe(self):
            return {"title": "测试视频", "uploader": "作者", "extractor": "test"}

        def _download(self):
            path = self.task_dir / "video" / "source.mp4"
            path.parent.mkdir()
            path.write_bytes(b"video")
            return path

        def _extract_audio(self, video_path):
            path = self.task_dir / "audio" / "transcript.wav"
            path.parent.mkdir()
            path.write_bytes(b"audio")
            return path

        def _transcribe(self, audio_path):
            return parse_srt(SRT)

        def _generate_outline(self, metadata, segments):
            return normalize_outline(
                {
                    "title": "测试视频",
                    "summary": "摘要",
                    "sections": [
                        {
                            "title": "完整流程",
                            "summary": "从开场到安装",
                            "start_segment_id": "seg-00001",
                            "end_segment_id": "seg-00003",
                        }
                    ],
                },
                segments,
            )

        def _extract_frames(self, video_path):
            frame_dir = self.task_dir / "analysis" / "keyframes" / "frames"
            frame_dir.mkdir(parents=True)
            (frame_dir / "frame_001.jpg").write_bytes(b"image")
            return [{"file": "frame_001.jpg", "timestamp_sec": 2.0}]

        def _select_images(self, outline, frames):
            return choose_section_images(outline, frames, 10)

        def _ocr_images(self, images):
            images[0]["ocr_text"] = "测试文字"
            return images

        def _generate_article(self, metadata, segments, outline, images):
            return {
                "title": "测试视频",
                "introduction": "文章导语",
                "sections": [{"id": "section-01", "body_markdown": "文章正文"}],
                "conclusion": "文章结语",
            }

    pipeline = FakePipeline(store, task["id"], PipelineConfig())
    pipeline.run()

    completed = store.get(task["id"])
    article_markdown = (store.task_dir(task["id"]) / "article.md").read_text(encoding="utf-8")
    article_html = (store.task_dir(task["id"]) / "article.html").read_text(encoding="utf-8")
    assert completed["status"] == "completed"
    assert "analysis/keyframes/frames/frame_001.jpg" in article_markdown
    assert "media/analysis/keyframes/frames/frame_001.jpg" in article_html
    assert "#t=0" in article_markdown


def test_generate_article_calls_llm_once_per_section(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODOC_FAKE_LLM", raising=False)
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    segments = parse_srt(SRT)
    outline = normalize_outline(
        {
            "title": "测试视频",
            "summary": "摘要",
            "sections": [
                {
                    "title": "开场",
                    "start_segment_id": "seg-00001",
                    "end_segment_id": "seg-00001",
                },
                {
                    "title": "制作",
                    "start_segment_id": "seg-00002",
                    "end_segment_id": "seg-00003",
                },
            ],
        },
        segments,
    )
    calls = []

    class SectionPipeline(VideoArticlePipeline):
        def _call_llm(self, step, messages, response_name=None):
            calls.append(response_name)
            section_id = f"section-{len(calls):02d}"
            return {"id": section_id, "body_markdown": f"## 重复标题\n\n正文 {section_id}"}

    pipeline = SectionPipeline(store, task["id"], PipelineConfig())
    article = pipeline._generate_article(
        {"title": "测试视频", "description": ""},
        segments,
        outline,
        [],
    )

    assert calls == ["article-section-01-response", "article-section-02-response"]
    assert article["sections"][0]["body_markdown"] == "正文 section-01"
    assert store.get(task["id"])["article_title"] == "测试视频"


def test_call_llm_retries_once_on_transient_error(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODOC_FAKE_LLM", raising=False)
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    pipeline = VideoArticlePipeline(store, task["id"], PipelineConfig())

    sleeps = []
    calls = {"n": 0}

    def fake_sleep(seconds):
        sleeps.append(seconds)

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("UNEXPECTED_EOF_WHILE_READING")
        response_body = json.dumps(
            {"choices": [{"message": {"content": '{"ok": true}'}}]},
            ensure_ascii=False,
        ).encode("utf-8")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return response_body

        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", fake_sleep)

    result = pipeline._call_llm("outline", [{"role": "user", "content": "hi"}])

    assert result == {"ok": True}
    assert calls["n"] == 2  # 第一次失败 + 重试一次成功
    assert sleeps == [3]  # 3 秒后重试


def test_call_llm_gives_up_after_retries(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODOC_FAKE_LLM", raising=False)
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    pipeline = VideoArticlePipeline(store, task["id"], PipelineConfig())

    def fake_sleep(seconds):
        pass

    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", fake_sleep)

    with pytest.raises(PipelineError) as error:
        pipeline._call_llm("outline", [{"role": "user", "content": "hi"}])

    assert "DeepSeek API 请求失败" in str(error.value)
    assert "boom" in str(error.value)


def test_call_llm_does_not_retry_http_4xx(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODOC_FAKE_LLM", raising=False)
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    pipeline = VideoArticlePipeline(store, task["id"], PipelineConfig())

    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(
            "url", 400, "Bad Request", {}, io.BytesIO(b'{"error":"bad"}')
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(PipelineError) as error:
        pipeline._call_llm("outline", [{"role": "user", "content": "hi"}])

    assert "HTTP 400" in str(error.value)
    assert calls["n"] == 1  # 4xx 不重试


def test_step_waits_for_manual_retry_and_records_attempts(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    pipeline = VideoArticlePipeline(store, task["id"], PipelineConfig())
    calls = 0

    def flaky_action():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PipelineError("temporary")
        return "ready"

    with pytest.raises(PipelineError, match="temporary"):
        pipeline._step("probe", flaky_action)

    failed_probe = store.get(task["id"])["steps"][0]
    assert calls == 1
    assert failed_probe["attempt_count"] == 1
    assert failed_probe["status"] == "failed"

    result = pipeline._step("probe", flaky_action)

    assert result == "ready"
    probe = store.get(task["id"])["steps"][0]
    assert calls == 2
    assert probe["attempt_count"] == 2
    assert [item["status"] for item in probe["attempts"]] == [
        "failed",
        "completed",
    ]


def test_article_retry_reuses_completed_section_checkpoint(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODOC_FAKE_LLM", raising=False)
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    segments = parse_srt(SRT)
    outline = normalize_outline(
        {
            "title": "测试视频",
            "summary": "摘要",
            "sections": [
                {
                    "title": "开场",
                    "start_segment_id": "seg-00001",
                    "end_segment_id": "seg-00001",
                },
                {
                    "title": "制作",
                    "start_segment_id": "seg-00002",
                    "end_segment_id": "seg-00003",
                },
            ],
        },
        segments,
    )
    calls: list[str] = []
    fail_second_section = True

    class CheckpointPipeline(VideoArticlePipeline):
        def _call_llm(self, step, messages, response_name=None):
            nonlocal fail_second_section
            calls.append(response_name)
            section_id = str(response_name).removeprefix("article-").removesuffix("-response")
            if section_id == "section-02" and fail_second_section:
                fail_second_section = False
                raise PipelineError("invalid json")
            return {"id": section_id, "body_markdown": f"正文 {section_id}"}

    pipeline = CheckpointPipeline(store, task["id"], PipelineConfig())
    metadata = {"title": "测试视频", "description": ""}

    with pytest.raises(PipelineError, match="invalid json"):
        pipeline._generate_article(metadata, segments, outline, [])
    article = pipeline._generate_article(metadata, segments, outline, [])

    assert calls == [
        "article-section-01-response",
        "article-section-02-response",
        "article-section-02-response",
    ]
    assert [item["id"] for item in article["sections"]] == [
        "section-01",
        "section-02",
    ]
    checkpoint = json.loads(
        (store.task_dir(task["id"]) / "article-progress.json").read_text(encoding="utf-8")
    )
    assert len(checkpoint["sections"]) == 2


def test_resume_from_article_reuses_all_upstream_outputs(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    task_dir = store.task_dir(task["id"])
    segments = parse_srt(SRT)
    outline = normalize_outline(
        {
            "title": "测试视频",
            "summary": "摘要",
            "sections": [
                {
                    "title": "完整流程",
                    "start_segment_id": "seg-00001",
                    "end_segment_id": "seg-00003",
                }
            ],
        },
        segments,
    )
    metadata = {"title": "测试视频", "description": ""}
    video = task_dir / "video" / "source.mp4"
    audio = task_dir / "audio" / "transcript.wav"
    frame = task_dir / "analysis" / "keyframes" / "frames" / "frame_001.jpg"
    video.parent.mkdir(parents=True)
    audio.parent.mkdir(parents=True)
    frame.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    frame.write_bytes(b"image")
    artifacts = {
        "metadata": "metadata.json",
        "video": "video/source.mp4",
        "audio": "audio/transcript.wav",
        "transcript_segments": "transcript/segments.json",
        "outline": "outline.json",
        "frames_json": "analysis/keyframes/frames.json",
        "article_images": "article-images.json",
        "ocr": "ocr.json",
    }
    files = {
        "metadata.json": metadata,
        "transcript/segments.json": segments,
        "outline.json": outline,
        "analysis/keyframes/frames.json": {
            "frames": [{"file": "frame_001.jpg", "timestamp_sec": 1.0}]
        },
        "article-images.json": [],
        "ocr.json": [],
    }
    for relative, payload in files.items():
        path = task_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    store.merge_artifacts(task["id"], artifacts)
    for step in store.get(task["id"])["steps"][:8]:
        store.update_step(task["id"], step["key"], status="completed")
    store.update_step(task["id"], "article", status="failed", error="invalid json")
    store.update(task["id"], status="failed", error="invalid json")
    executed: list[str] = []

    class ResumePipeline(VideoArticlePipeline):
        def _generate_article(self, metadata, segments, outline, images):
            executed.append("article")
            article = {
                "title": "测试视频",
                "introduction": "摘要",
                "sections": [{"id": "section-01", "body_markdown": "正文"}],
                "conclusion": "",
            }
            path = self.task_dir / "article.json"
            path.write_text(json.dumps(article, ensure_ascii=False), encoding="utf-8")
            self.store.merge_artifacts(self.task_id, {"article_json": "article.json"})
            return article

        def _finalize(self, metadata, video_path, segments, outline, images, article):
            executed.append("finalize")
            result = {"ok": True}
            path = self.task_dir / "result.json"
            path.write_text(json.dumps(result), encoding="utf-8")
            self.store.merge_artifacts(self.task_id, {"result": "result.json"})
            return result

    pipeline = ResumePipeline(
        store,
        task["id"],
        PipelineConfig(),
    )
    assert pipeline.resume_step() == "article"
    store.queue_resume(task["id"], "article")
    pipeline.run(start_at="article")

    saved = store.get(task["id"])
    assert saved["status"] == "completed"
    assert executed == ["article", "finalize"]
    assert all(step["attempt_count"] == 0 for step in saved["steps"][:8])
    assert saved["steps"][8]["attempt_count"] == 1
    assert saved["steps"][9]["attempt_count"] == 1
