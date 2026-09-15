"""视频 URL 到带时间锚点图文文章的本地流水线。"""

from __future__ import annotations

import hashlib
import html
import http.client
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import markdown

from .integrations.frames import FramesError, extract_frames
from .integrations.transcribe import TranscribeError, transcribe
from .task_store import TaskStore, utc_now


SRT_TIME_PATTERN = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})"
)


class PipelineError(RuntimeError):
    """包含适合任务页面展示的流水线错误。"""


# 内置的本地 OCR 脚本（macOS Vision）。可用 VIDEODOC_OCR_SCRIPT 覆盖。
DEFAULT_OCR_SCRIPT = Path(__file__).resolve().parent / "integrations" / "vision_ocr.swift"

# 默认 LLM 端点与模型（OpenAI 兼容接口）。可用 VIDEODOC_LLM_* 覆盖。
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"


def llm_api_key() -> str | None:
    """返回 LLM API Key；兼容旧的 OPENCODE_GO_API_KEY 变量名。"""
    return os.environ.get("VIDEODOC_LLM_API_KEY") or os.environ.get("OPENCODE_GO_API_KEY")


@dataclass(frozen=True)
class PipelineConfig:
    cookie_browser: str = "chrome"
    frame_scene: float = 0.30
    frame_floor_seconds: float = 3.0
    max_frames: int = 120
    frame_width: int = 960
    max_ocr_frames: int = 24
    ocr_script: Path = DEFAULT_OCR_SCRIPT
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    llm_timeout_seconds: int = 600
    yt_dlp_python_module: Path | None = None

    @classmethod
    def from_environment(cls) -> "PipelineConfig":
        yt_dlp_python = os.environ.get("VIDEODOC_YT_DLP_PYTHON")
        ocr_script = os.environ.get("VIDEODOC_OCR_SCRIPT")
        return cls(
            cookie_browser=os.environ.get("VIDEODOC_COOKIE_BROWSER", "chrome"),
            frame_scene=float(os.environ.get("VIDEODOC_FRAME_SCENE", "0.30")),
            frame_floor_seconds=float(os.environ.get("VIDEODOC_FRAME_FLOOR", "3")),
            max_frames=int(os.environ.get("VIDEODOC_MAX_FRAMES", "120")),
            frame_width=int(os.environ.get("VIDEODOC_FRAME_WIDTH", "960")),
            max_ocr_frames=int(os.environ.get("VIDEODOC_OCR_MAX_FRAMES", "24")),
            ocr_script=(
                Path(ocr_script).expanduser() if ocr_script else DEFAULT_OCR_SCRIPT
            ),
            llm_base_url=os.environ.get("VIDEODOC_LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
            llm_model=os.environ.get("VIDEODOC_LLM_MODEL", DEFAULT_LLM_MODEL),
            llm_timeout_seconds=int(os.environ.get("VIDEODOC_LLM_TIMEOUT", "600")),
            yt_dlp_python_module=(
                Path(yt_dlp_python).expanduser() if yt_dlp_python else None
            ),
        )


def parse_srt_timestamp(value: str) -> float:
    match = SRT_TIME_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"无效 SRT 时间戳: {value}")
    parts = {key: int(number) for key, number in match.groupdict().items()}
    return parts["h"] * 3600 + parts["m"] * 60 + parts["s"] + parts["ms"] / 1000


def parse_srt(text: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    blocks = re.split(r"\r?\n\s*\r?\n", text.strip())
    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        time_index = 1 if re.fullmatch(r"\d+", lines[0].strip()) else 0
        if time_index >= len(lines) or "-->" not in lines[time_index]:
            continue
        start_text, end_text = [part.strip().split()[0] for part in lines[time_index].split("-->", 1)]
        body = " ".join(line.strip() for line in lines[time_index + 1 :]).strip()
        if not body:
            continue
        segment_number = len(segments) + 1
        segments.append(
            {
                "id": f"seg-{segment_number:05d}",
                "start_sec": parse_srt_timestamp(start_text),
                "end_sec": parse_srt_timestamp(end_text),
                "text": body,
            }
        )
    if not segments:
        raise PipelineError("Whisper 没有生成可解析的 SRT 时间轴。")
    return segments


def format_time(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def extract_json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    try:
        parsed = json.loads(value)
    except ValueError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise PipelineError("模型没有返回 JSON 对象。")
        try:
            parsed = json.loads(value[start : end + 1])
        except ValueError as error:
            raise PipelineError(f"模型 JSON 无法解析: {error}") from error
    if not isinstance(parsed, dict):
        raise PipelineError("模型返回的根节点不是 JSON 对象。")
    return parsed


def normalize_outline(
    payload: dict[str, Any],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {segment["id"]: segment for segment in segments}

    def canonical_segment_id(value: Any) -> str:
        raw = str(value or "").strip()
        if raw in by_id:
            return raw
        match = re.search(r"(\d+)$", raw)
        if match is None:
            return raw
        candidate = f"seg-{int(match.group(1)):05d}"
        return candidate if candidate in by_id else raw

    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise PipelineError("大纲缺少 sections。")

    sections: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_sections, start=1):
        if not isinstance(raw, dict):
            continue
        start_id = canonical_segment_id(raw.get("start_segment_id"))
        end_id = canonical_segment_id(raw.get("end_segment_id"))
        if start_id not in by_id or end_id not in by_id:
            raise PipelineError(f"大纲章节 {index} 引用了不存在的转写段落。")
        start = by_id[start_id]
        end = by_id[end_id]
        if end["end_sec"] < start["start_sec"]:
            raise PipelineError(f"大纲章节 {index} 的时间范围倒置。")
        sections.append(
            {
                "id": f"section-{index:02d}",
                "title": str(raw.get("title") or f"章节 {index}").strip(),
                "summary": str(raw.get("summary") or "").strip(),
                "start_segment_id": start_id,
                "end_segment_id": end_id,
                "start_sec": start["start_sec"],
                "end_sec": end["end_sec"],
                "start_time": format_time(start["start_sec"]),
                "end_time": format_time(end["end_sec"]),
            }
        )
    if not sections:
        raise PipelineError("大纲没有可用章节。")
    sections.sort(key=lambda section: section["start_sec"])
    return {
        "title": str(payload.get("title") or "视频内容大纲").strip(),
        "summary": str(payload.get("summary") or "").strip(),
        "sections": sections,
    }


def choose_section_images(
    outline: dict[str, Any],
    frames: list[dict[str, Any]],
    max_images: int,
) -> list[dict[str, Any]]:
    usable = [frame for frame in frames if isinstance(frame.get("timestamp_sec"), (int, float))]
    if not usable:
        raise PipelineError("抽帧结果为空，无法生成图文文章。")
    selected: list[dict[str, Any]] = []
    used_files: set[str] = set()
    for section in outline["sections"]:
        if len(selected) >= max_images:
            break
        start = float(section["start_sec"])
        end = float(section["end_sec"])
        target = start + max(0.0, end - start) * 0.5
        in_range = [
            frame
            for frame in usable
            if start <= float(frame["timestamp_sec"]) <= end and frame.get("file") not in used_files
        ]
        candidates = in_range or [frame for frame in usable if frame.get("file") not in used_files]
        if not candidates:
            continue
        frame = min(candidates, key=lambda item: abs(float(item["timestamp_sec"]) - target))
        used_files.add(str(frame["file"]))
        selected.append(
            {
                "section_id": section["id"],
                "section_title": section["title"],
                "file": str(frame["file"]),
                "timestamp_sec": float(frame["timestamp_sec"]),
                "timestamp": format_time(float(frame["timestamp_sec"])),
                "selection_reason": frame.get("selection_reason", ""),
                "ocr_text": "",
            }
        )
    return selected


def format_transcript_lines(segments: list[dict[str, Any]]) -> list[str]:
    """一行一个片段，保留完整 segment ID 与时间范围。"""
    return [
        f"[{segment['id']} {format_time(segment['start_sec'])}-{format_time(segment['end_sec'])}] {segment['text']}"
        for segment in segments
    ]


def merge_transcript_lines(
    segments: list[dict[str, Any]],
    window_seconds: float,
) -> list[str]:
    """把连续片段按固定时间窗口合并成一行。

    块头保留窗口内首尾片段，因此 [首ID 起-止] 仍指向真实 segment（normalize_outline
    会据此还原 start_sec / end_sec），但正文是整窗拼接，时间粒度变为 window_seconds。
    Whisper 在长视频上会把语音切成几千个 2 秒级片段，逐条列出时间戳时元数据能占到
    总体积的四分之三（127 分钟实测 3722 片 / 137244 字符里 76% 是标签）；按窗口合并
    后同一视频降到 39925 字符（29%），且不丢任何文字。
    """
    lines: list[str] = []
    window: list[dict[str, Any]] = []
    for segment in segments:
        if window and segment["end_sec"] - window[0]["start_sec"] > window_seconds:
            lines.append(_merged_line(window))
            window = []
        window.append(segment)
    if window:
        lines.append(_merged_line(window))
    return lines


def _merged_line(window: list[dict[str, Any]]) -> str:
    first, last = window[0], window[-1]
    text = "".join(segment["text"] for segment in window)
    return (
        f"[{first['id']} {format_time(first['start_sec'])}-{format_time(last['end_sec'])}] {text}"
    )


def transcript_for_prompt(
    segments: list[dict[str, Any]],
    max_chars: int = 120_000,
    merge_window_seconds: float = 30.0,
) -> str:
    """按预算渲染转写；超出预算时先按时间窗口合并，避免长视频直接失败。

    合并把体积从“取决于 Whisper 切了多少片段”变为“正比于视频时长”（实测约 314
    字符/分钟），因此能否通过预算可以在发送前算出。仍未降到预算内时不静默截断，
    而是报错——截断会让模型以为看到的是全文，生成错误大纲。
    """
    value = "\n".join(format_transcript_lines(segments))
    if len(value) <= max_chars:
        return value
    merged = "\n".join(merge_transcript_lines(segments, merge_window_seconds))
    if len(merged) > max_chars:
        raise PipelineError(
            f"转写文本按 {merge_window_seconds:g} 秒窗口合并后仍有 {len(merged)} 字符，"
            f"超过 {max_chars} 字符限制（合并前 {len(value)} 字符）。"
        )
    return merged


def strip_leading_markdown_heading(value: str) -> str:
    """正文开头若重复章节标题，则由程序移除。"""
    lines = value.strip().splitlines()
    if lines and re.match(r"^#{1,6}\s+\S", lines[0]):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).strip()


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_json_atomic(path: Path, payload: Any) -> None:
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2))


class VideoArticlePipeline:
    """顺序执行任务，并将每一步状态持久化到 TaskStore。"""

    def __init__(self, store: TaskStore, task_id: str, config: PipelineConfig):
        self.store = store
        self.task_id = task_id
        self.config = config
        self.task_dir = store.task_dir(task_id)
        self.task = store.get(task_id)
        self._active_attempts: dict[str, int] = {}
        self._yt_dlp_command_cache: list[str] | None = None
        self._yt_dlp_version_cache: str | None = None

    # ---- yt-dlp 解析：优先用本服务 venv 里的 yt-dlp，避免依赖系统 PATH ----

    def _yt_dlp_command(self) -> list[str]:
        """返回 yt-dlp 启动命令（不含参数）。

        V1 里 yt-dlp 是从 PATH 上撞运气拿的（brew 全局版），导致“服务跑起来用哪版
        取决于启动它的 shell”，重装环境或换机器后直接坏。改为优先用服务 venv 自带
        的 yt-dlp：无论从哪里启动，都用与当前解释器绑定的那一个。可用
        VIDEODOC_YT_DLP 显式指定（如指向某个自定义 yt-dlp 二进制）。
        """
        if self._yt_dlp_command_cache is not None:
            return self._yt_dlp_command_cache
        explicit = os.environ.get("VIDEODOC_YT_DLP")
        if explicit:
            command = shlex.split(explicit)
        elif self.config.yt_dlp_python_module:
            command = [
                str(self.config.yt_dlp_python_module),
                "-m",
                "yt_dlp",
            ]
        else:
            command = [sys.executable, "-m", "yt_dlp"]
        self._yt_dlp_command_cache = command
        return command

    def _yt_dlp_version(self) -> str | None:
        """查询当前 yt-dlp 版本；失败（未安装等）返回 None，不抛错。"""
        if self._yt_dlp_version_cache is not None:
            return self._yt_dlp_version_cache
        try:
            result = subprocess.run(
                self._yt_dlp_command() + ["--version"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        version = result.stdout.strip() or None
        if version and result.returncode == 0:
            self._yt_dlp_version_cache = version
        return version

    def _log_yt_dlp_version(self, step: str) -> None:
        version = self._yt_dlp_version()
        if version:
            self.store.append_log(
                self.task_id,
                step,
                f"yt-dlp {version}（{shlex.join(self._yt_dlp_command())}）",
            )

    def _check_yt_dlp_up_to_date(self, step: str) -> None:
        """下载/探测失败时，对比 PyPI 最新版并给出升级指引（不阻塞）。"""
        version = self._yt_dlp_version()
        if not version:
            self.store.append_log(
                self.task_id,
                step,
                "yt-dlp 版本未知；请确认服务 venv 已安装 yt-dlp。",
            )
            return
        latest = self._latest_yt_dlp_version()
        if latest is None:
            self.store.append_log(
                self.task_id,
                step,
                "无法连接 PyPI 查询 yt-dlp 最新版（网络受限）。",
            )
            return
        if latest != version:
            self.store.append_log(
                self.task_id,
                step,
                f"yt-dlp {version} 落后于最新 {latest}：若下载失败与站点反爬更新有关，"
                "请升级后重试（改 pyproject.toml 中的版本并重新 pip install -e .）。",
            )
        else:
            self.store.append_log(
                self.task_id,
                step,
                f"yt-dlp {version} 已是最新版本。",
            )

    def _latest_yt_dlp_version(self) -> str | None:
        try:
            with urllib.request.urlopen(
                "https://pypi.org/pypi/yt-dlp/json",
                timeout=10,
            ) as response:
                return str(json.loads(response.read()).get("info", {}).get("version") or "") or None
        except (OSError, ValueError):
            return None

    def run(self, start_at: str | None = None) -> None:
        self.task = self.store.get(self.task_id)
        start_index = self._start_index(start_at)
        original_started_at = self.task.get("started_at")
        started_at = original_started_at or utc_now()
        self.store.update(
            self.task_id,
            status="running",
            started_at=started_at,
            finished_at=None,
            error=None,
        )
        try:
            previous = self._load_previous_outputs(start_index)
            metadata = previous.get("probe")
            if metadata is None:
                metadata = self._step("probe", self._probe)
            video_path = previous.get("download")
            if video_path is None:
                video_path = self._step("download", self._download)
            audio_path = previous.get("audio")
            if audio_path is None:
                audio_path = self._step("audio", lambda: self._extract_audio(video_path))
            segments = previous.get("transcribe")
            if segments is None:
                segments = self._step("transcribe", lambda: self._transcribe(audio_path))
            outline = previous.get("outline")
            if outline is None:
                outline = self._step(
                    "outline",
                    lambda: self._generate_outline(metadata, segments),
                )
            frames = previous.get("frames")
            if frames is None:
                frames = self._step("frames", lambda: self._extract_frames(video_path))
            images = previous.get("select_images")
            if images is None:
                images = self._step(
                    "select_images",
                    lambda: self._select_images(outline, frames),
                )
            ocr_images = previous.get("ocr")
            if ocr_images is None:
                images = self._step("ocr", lambda: self._ocr_images(images))
            else:
                images = ocr_images
            article = previous.get("article")
            if article is None:
                article = self._step(
                    "article",
                    lambda: self._generate_article(metadata, segments, outline, images),
                )
            if "finalize" not in previous:
                self._step(
                    "finalize",
                    lambda: self._finalize(
                        metadata,
                        video_path,
                        segments,
                        outline,
                        images,
                        article,
                    ),
                )
        except Exception as error:
            self.store.update(
                self.task_id,
                status="failed",
                error=str(error),
                finished_at=utc_now(),
            )
            return
        self.store.update(
            self.task_id,
            status="completed",
            finished_at=utc_now(),
            error=None,
        )

    def resume_step(self) -> str:
        self.task = self.store.get(self.task_id)
        if self.task.get("status") not in {"failed", "interrupted"}:
            raise PipelineError("只有失败或中断的任务可以继续。")
        for index, step in enumerate(self.task["steps"]):
            if step["status"] in {"completed", "skipped"}:
                continue
            self._load_previous_outputs(index)
            if step["key"] == "download":
                try:
                    self._load_file_artifact(
                        "source_info",
                        "private/source.info.json",
                        "下载源信息",
                    )
                except PipelineError as error:
                    raise PipelineError(f"无法继续下载：{error}") from error
            return str(step["key"])
        raise PipelineError("任务没有可继续的阶段。")

    def _start_index(self, start_at: str | None) -> int:
        if start_at is None:
            return 0
        keys = [key for key, _label in self._step_definitions()]
        try:
            return keys.index(start_at)
        except ValueError as error:
            raise PipelineError(f"未知的恢复阶段: {start_at}") from error

    def _load_previous_outputs(self, start_index: int) -> dict[str, Any]:
        loaders: list[tuple[str, Callable[[], Any]]] = [
            ("probe", self._load_metadata),
            ("download", self._load_video),
            ("audio", self._load_audio),
            ("transcribe", self._load_segments),
            ("outline", self._load_outline),
            ("frames", self._load_frames),
            ("select_images", self._load_selected_images),
            ("ocr", self._load_ocr_images),
            ("article", self._load_article),
            ("finalize", self._load_result),
        ]
        values: dict[str, Any] = {}
        for key, loader in loaders[:start_index]:
            try:
                values[key] = loader()
            except PipelineError as error:
                raise PipelineError(f"无法复用已完成的 {key} 阶段: {error}") from error
        return values

    def _load_metadata(self) -> dict[str, Any]:
        return self._load_json_object("metadata", "metadata.json", "视频元数据")

    def _load_video(self) -> Path:
        return self._load_file_artifact("video", "video/source.mp4", "视频文件")

    def _load_audio(self) -> Path:
        return self._load_file_artifact("audio", "audio/transcript.wav", "转写音频")

    def _load_segments(self) -> list[dict[str, Any]]:
        value = self._load_json_list(
            "transcript_segments",
            "transcript/segments.json",
            "转写时间轴",
        )
        if not value:
            raise PipelineError("转写时间轴为空。")
        return value

    def _load_outline(self) -> dict[str, Any]:
        value = self._load_json_object("outline", "outline.json", "文章大纲")
        if not isinstance(value.get("sections"), list) or not value["sections"]:
            raise PipelineError("文章大纲缺少章节。")
        return value

    def _load_frames(self) -> list[dict[str, Any]]:
        value = self._load_json_object(
            "frames_json",
            "analysis/keyframes/frames.json",
            "抽帧清单",
        )
        frames = value.get("frames")
        if not isinstance(frames, list) or not frames:
            raise PipelineError("抽帧清单中没有关键帧。")
        frame_dir = self.task_dir / "analysis" / "keyframes" / "frames"
        missing = [str(frame.get("file")) for frame in frames if not (frame_dir / str(frame.get("file"))).is_file()]
        if missing:
            raise PipelineError(f"缺少 {len(missing)} 个关键帧文件，第一个是 {missing[0]}。")
        return frames

    def _load_selected_images(self) -> list[dict[str, Any]]:
        return self._load_json_list(
            "article_images",
            "article-images.json",
            "章节配图清单",
        )

    def _load_ocr_images(self) -> list[dict[str, Any]]:
        return self._load_json_list("ocr", "ocr.json", "OCR 结果")

    def _load_article(self) -> dict[str, Any]:
        value = self._load_json_object("article_json", "article.json", "文章正文")
        if not isinstance(value.get("sections"), list):
            raise PipelineError("文章正文缺少章节。")
        return value

    def _load_result(self) -> dict[str, Any]:
        return self._load_json_object("result", "result.json", "最终结果")

    def _load_json_object(
        self,
        artifact_key: str,
        fallback: str,
        label: str,
    ) -> dict[str, Any]:
        value = self._load_json(artifact_key, fallback, label)
        if not isinstance(value, dict):
            raise PipelineError(f"{label}不是 JSON 对象。")
        return value

    def _load_json_list(
        self,
        artifact_key: str,
        fallback: str,
        label: str,
    ) -> list[dict[str, Any]]:
        value = self._load_json(artifact_key, fallback, label)
        if not isinstance(value, list):
            raise PipelineError(f"{label}不是 JSON 数组。")
        return value

    def _load_json(self, artifact_key: str, fallback: str, label: str) -> Any:
        path = self._load_file_artifact(artifact_key, fallback, label)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PipelineError(f"{label}无法读取或解析: {path.name}") from error

    def _load_file_artifact(self, artifact_key: str, fallback: str, label: str) -> Path:
        relative = str(self.task.get("artifacts", {}).get(artifact_key) or fallback)
        path = (self.task_dir / relative).resolve()
        if not path.is_relative_to(self.task_dir) or not path.is_file():
            raise PipelineError(f"缺少{label}: {relative}")
        return path

    def _step_definitions(self) -> tuple[tuple[str, str], ...]:
        return tuple((step["key"], step["label"]) for step in self.task["steps"])

    def _step(self, key: str, action: Callable[[], Any]) -> Any:
        attempt_number = self.store.start_attempt(self.task_id, key)
        self._active_attempts[key] = attempt_number
        self.store.append_log(
            self.task_id,
            key,
            f"[{utc_now()}] 开始阶段尝试 {attempt_number}",
            attempt_number,
        )
        try:
            result = action()
        except Exception as error:
            self.store.append_log(
                self.task_id,
                key,
                f"失败: {error}",
                attempt_number,
            )
            self.store.finish_attempt(
                self.task_id,
                key,
                attempt_number,
                status="failed",
                error=str(error),
            )
            self._active_attempts.pop(key, None)
            raise
        self.store.append_log(
            self.task_id,
            key,
            f"[{utc_now()}] 阶段尝试 {attempt_number} 完成",
            attempt_number,
        )
        self.store.finish_attempt(
            self.task_id,
            key,
            attempt_number,
            status="completed",
        )
        self._active_attempts.pop(key, None)
        return result

    def _set_command(self, step: str, command: list[str]) -> None:
        self.store.update_step(self.task_id, step, command=shlex.join(command))
        self.store.append_log(self.task_id, step, f"$ {shlex.join(command)}")

    def _run_command(
        self,
        step: str,
        command: list[str],
        *,
        cwd: Path | None = None,
        capture: bool = False,
        env: dict[str, str] | None = None,
    ) -> str:
        self._set_command(step, command)
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if capture else subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env if env is not None else os.environ.copy(),
        )
        if capture:
            stdout, stderr = process.communicate()
            if stderr:
                self.store.append_log(self.task_id, step, stderr)
            if process.returncode != 0:
                raise PipelineError(f"命令退出码 {process.returncode}: {shlex.join(command)}")
            return stdout
        assert process.stdout is not None
        output: list[str] = []
        for line in process.stdout:
            output.append(line)
            self.store.append_log(self.task_id, step, line.rstrip("\n"))
        return_code = process.wait()
        if return_code != 0:
            raise PipelineError(f"命令退出码 {return_code}: {shlex.join(command)}")
        return "".join(output)

    def _yt_dlp_prefix(self, use_cookies: bool = True) -> list[str]:
        command = self._yt_dlp_command() + ["--no-playlist"]
        hostname = (urlparse(self.task["url"]).hostname or "").lower()
        if hostname == "b23.tv" or hostname.endswith(".bilibili.com") or hostname == "bilibili.com":
            bilibili_proxy = os.environ.get("VIDEODOC_BILIBILI_PROXY")
            if bilibili_proxy is not None:
                command.extend(["--proxy", bilibili_proxy])
            command.extend(
                [
                    "--user-agent",
                    os.environ.get(
                        "VIDEODOC_BILIBILI_USER_AGENT",
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/152.0.0.0 Safari/537.36",
                    ),
                    "--add-header",
                    "Referer:https://www.bilibili.com/",
                ]
            )
        if use_cookies and self.config.cookie_browser:
            command.extend(["--cookies-from-browser", self.config.cookie_browser])
        return command

    def _run_yt_dlp_with_fallback(
        self,
        step: str,
        arguments: list[str],
        *,
        capture: bool,
    ) -> str:
        try:
            return self._run_command(
                step,
                self._yt_dlp_prefix(use_cookies=True) + arguments,
                capture=capture,
            )
        except PipelineError as first_error:
            self.store.append_log(
                self.task_id,
                step,
                f"带浏览器 Cookie 的尝试失败，改用无 Cookie 模式: {first_error}",
            )
            try:
                return self._run_command(
                    step,
                    self._yt_dlp_prefix(use_cookies=False) + arguments,
                    capture=capture,
                )
            except PipelineError as second_error:
                self._check_yt_dlp_up_to_date(step)
                raise second_error

    def _probe(self) -> dict[str, Any]:
        if self._yt_dlp_version() is None:
            raise PipelineError(
                "缺少 yt-dlp（未安装到服务 venv）。在项目根目录运行 "
                "pip install -e . 安装。"
            )
        self._log_yt_dlp_version("probe")
        private_dir = self.task_dir / "private"
        private_dir.mkdir(parents=True, exist_ok=True)
        raw = self._run_yt_dlp_with_fallback(
            "probe",
            [
                "--dump-single-json",
                "--write-info-json",
                "--skip-download",
                "--no-simulate",
                "--no-warnings",
                "-o",
                str(private_dir / "source.%(ext)s"),
                self.task["url"],
            ],
            capture=True,
        )
        try:
            source = json.loads(raw)
        except ValueError as error:
            raise PipelineError("yt-dlp 元数据不是有效 JSON。") from error
        metadata = {
            "id": source.get("id"),
            "title": source.get("title") or "未命名视频",
            "description": source.get("description") or "",
            "uploader": source.get("uploader") or source.get("channel") or "",
            "duration": source.get("duration"),
            "webpage_url": source.get("webpage_url") or self.task["url"],
            "extractor": source.get("extractor_key") or source.get("extractor") or "unknown",
            "thumbnail": source.get("thumbnail"),
        }
        path = self.task_dir / "metadata.json"
        write_json_atomic(path, metadata)
        source_info = private_dir / "source.info.json"
        if not source_info.is_file():
            raise PipelineError("yt-dlp 没有生成可复用的 source.info.json。")
        self.store.update(self.task_id, metadata=metadata)
        self.store.merge_artifacts(
            self.task_id,
            {
                "metadata": "metadata.json",
                "source_info": "private/source.info.json",
            },
        )
        self.store.update_step(
            self.task_id,
            "probe",
            outputs=["metadata.json", "private/source.info.json"],
        )
        self.store.append_log(
            self.task_id,
            "probe",
            f"识别结果: {metadata['extractor']} / {metadata['title']}",
        )
        return metadata

    def _download(self) -> Path:
        video_dir = self.task_dir / "video"
        video_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(video_dir / "source.%(ext)s")
        source_info = self.task_dir / "private" / "source.info.json"
        if not source_info.is_file():
            raise PipelineError("缺少 probe 阶段生成的 source.info.json。")
        try:
            output = self._run_command(
                "download",
                self._yt_dlp_command()
                + [
                    "--load-info-json",
                    str(source_info),
                    "-f",
                    "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]/bv*+ba/b",
                    "--merge-output-format",
                    "mp4",
                    "--remux-video",
                    "mp4",
                    "--newline",
                    "--print",
                    "after_move:filepath",
                    "-o",
                    output_template,
                ],
                capture=False,
            )
        except PipelineError as error:
            self._check_yt_dlp_up_to_date("download")
            raise error
        candidates = [
            Path(line.strip())
            for line in output.splitlines()
            if line.strip() and Path(line.strip()).is_file()
        ]
        if not candidates:
            candidates = [
                path
                for path in video_dir.glob("source.*")
                if path.suffix not in {".part", ".ytdl", ".json"}
            ]
        if not candidates:
            raise PipelineError("下载命令完成，但没有找到本地视频文件。")
        video_path = max(candidates, key=lambda path: path.stat().st_size)
        relative = video_path.relative_to(self.task_dir).as_posix()
        self.store.merge_artifacts(self.task_id, {"video": relative})
        self.store.update_step(self.task_id, "download", outputs=[relative])
        return video_path

    def _extract_audio(self, video_path: Path) -> Path:
        if shutil.which("ffmpeg") is None:
            raise PipelineError("缺少 ffmpeg。")
        audio_dir = self.task_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / "transcript.wav"
        self._run_command(
            "audio",
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(audio_path),
            ],
        )
        if not audio_path.is_file():
            raise PipelineError("ffmpeg 没有生成 WAV 音频。")
        relative = audio_path.relative_to(self.task_dir).as_posix()
        self.store.merge_artifacts(self.task_id, {"audio": relative})
        self.store.update_step(self.task_id, "audio", outputs=[relative])
        return audio_path

    def _transcribe(self, audio_path: Path) -> list[dict[str, Any]]:
        transcript_dir = self.task_dir / "transcript"
        transcript_dir.mkdir(parents=True, exist_ok=True)
        try:
            segments = transcribe(
                audio_path,
                transcript_dir,
                runner=lambda command, env: self._run_command(
                    "transcribe", command, env=env
                ),
                log=lambda line: self.store.append_log(self.task_id, "transcribe", line),
            )
        except TranscribeError as error:
            raise PipelineError(str(error)) from error
        srt_path = transcript_dir / "transcript.srt"
        text_path = transcript_dir / "transcript.txt"
        json_path = transcript_dir / "segments.json"
        write_json_atomic(json_path, segments)
        artifacts = {
            "transcript_srt": srt_path.relative_to(self.task_dir).as_posix(),
            "transcript_segments": json_path.relative_to(self.task_dir).as_posix(),
        }
        if text_path.is_file():
            artifacts["transcript_text"] = text_path.relative_to(self.task_dir).as_posix()
        self.store.merge_artifacts(self.task_id, artifacts)
        self.store.update_step(self.task_id, "transcribe", outputs=list(artifacts.values()))
        self.store.append_log(self.task_id, "transcribe", f"解析到 {len(segments)} 个时间片段。")
        return segments

    def _llm_endpoint(self) -> str:
        base = self.config.llm_base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _call_llm(
        self,
        step: str,
        messages: list[dict[str, str]],
        response_name: str | None = None,
    ) -> dict[str, Any]:
        if os.environ.get("VIDEODOC_FAKE_LLM") == "1":
            raise PipelineError("测试 LLM 只能通过专用生成函数调用。")
        api_key = llm_api_key()
        if not api_key:
            raise PipelineError(
                "缺少 LLM API Key，请设置环境变量 VIDEODOC_LLM_API_KEY。"
            )
        payload = {
            "model": self.config.llm_model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.store.update_step(
            self.task_id,
            step,
            command=f"POST {self._llm_endpoint()} model={self.config.llm_model}",
        )
        self.store.append_log(
            self.task_id,
            step,
            f"POST {self._llm_endpoint()} model={self.config.llm_model}",
        )
        request = urllib.request.Request(
            self._llm_endpoint(),
            data=request_body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "videodoc/0.1",
                "x-opencode-session": self.task_id,
            },
            method="POST",
        )
        # 默认 3 次重试：本机到 LLM 端点经 Clash 代理，实测 TLS 偶发断连率约
        # 20-40%。article 步骤有 10 次调用，重试 1 次时全任务成功率仅约 12%，
        # 3 次可到约 73%。用 VIDEODOC_LLM_RETRIES 覆盖，0 表示不重试。
        max_retries = int(os.environ.get("VIDEODOC_LLM_RETRIES", "3"))
        last_error: PipelineError | None = None
        for attempt in range(max_retries + 1):
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.config.llm_timeout_seconds,
                ) as response:
                    response_body = response.read().decode("utf-8")
                    break
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")[:2000]
                raise PipelineError(f"DeepSeek API HTTP {error.code}: {detail}") from error
            except (
                urllib.error.URLError,
                http.client.RemoteDisconnected,
                TimeoutError,
            ) as error:
                last_error = PipelineError(f"DeepSeek API 请求失败: {error}")
                if attempt < max_retries:
                    delay = 3 * (attempt + 1)
                    self.store.append_log(
                        self.task_id,
                        step,
                        f"LLM 请求失败（{error}），{delay} 秒后重试 ({attempt + 1}/{max_retries})",
                    )
                    time.sleep(delay)
                    continue
                raise last_error
        else:
            raise last_error or PipelineError("LLM 请求未得到响应。")
        private_dir = self.task_dir / "private"
        private_dir.mkdir(parents=True, exist_ok=True)
        filename = response_name or f"{step}-response"
        safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-.")
        attempt_number = self._active_attempts.get(step)
        if attempt_number is not None:
            safe_filename = f"{safe_filename}-attempt-{attempt_number:03d}"
        write_text_atomic(private_dir / f"{safe_filename}.json", response_body)
        try:
            response_json = json.loads(response_body)
            content = response_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise PipelineError("DeepSeek API 返回结构不符合预期。") from error
        usage = response_json.get("usage")
        if usage:
            self.store.append_log(self.task_id, step, f"usage={json.dumps(usage, ensure_ascii=False)}")
        return extract_json_object(str(content))

    def _fake_outline(self, metadata: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
        chunk_count = min(4, len(segments))
        chunk_size = max(1, len(segments) // chunk_count)
        sections = []
        for index in range(chunk_count):
            start_index = index * chunk_size
            end_index = len(segments) - 1 if index == chunk_count - 1 else min(len(segments) - 1, (index + 1) * chunk_size - 1)
            sections.append(
                {
                    "title": f"测试章节 {index + 1}",
                    "summary": segments[start_index]["text"],
                    "start_segment_id": segments[start_index]["id"],
                    "end_segment_id": segments[end_index]["id"],
                }
            )
        return {"title": metadata["title"], "summary": "测试模式大纲", "sections": sections}

    def _generate_outline(
        self,
        metadata: dict[str, Any],
        segments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        transcript = transcript_for_prompt(segments)
        if os.environ.get("VIDEODOC_FAKE_LLM") == "1":
            payload = self._fake_outline(metadata, segments)
        else:
            payload = self._call_llm(
                "outline",
                [
                    {
                        "role": "system",
                        "content": (
                            "你是视频文章编辑。根据带 ID 和时间戳的转写生成结构化中文大纲。"
                            "不得编造 segment ID。标题和描述中的专有名词优先于语音转写，"
                            "发现同音识别错误时应按元数据纠正。只返回 JSON 对象。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"视频标题：{metadata['title']}\n"
                            f"作者：{metadata.get('uploader', '')}\n\n"
                            f"视频描述：{metadata.get('description', '')[:4000]}\n\n"
                            "返回结构：{title, summary, sections:[{title, summary, "
                            "start_segment_id, end_segment_id}]}。章节应覆盖完整视频，通常 4-12 节。\n\n"
                            f"合法 segment ID 范围：{segments[0]['id']} 至 {segments[-1]['id']}。\n\n"
                            f"转写：\n{transcript}"
                        ),
                    },
                ],
            )
        outline = normalize_outline(payload, segments)
        path = self.task_dir / "outline.json"
        write_json_atomic(path, outline)
        self.store.merge_artifacts(self.task_id, {"outline": "outline.json"})
        self.store.update_step(self.task_id, "outline", outputs=["outline.json"])
        return outline

    def _extract_frames(self, video_path: Path) -> list[dict[str, Any]]:
        analysis_dir = self.task_dir / "analysis"
        try:
            artifact_dir, frames = extract_frames(
                video_path,
                analysis_dir,
                scene=self.config.frame_scene,
                fps_floor=self.config.frame_floor_seconds,
                max_frames=self.config.max_frames,
                frame_width=self.config.frame_width,
                why="为带时间锚点的中文图文文章选择章节配图",
                runner=lambda command, env: self._run_command(
                    "frames", command, env=env
                ),
            )
        except FramesError as error:
            raise PipelineError(str(error)) from error
        frames_json = artifact_dir / "frames.json"
        relative = frames_json.relative_to(self.task_dir).as_posix()
        self.store.merge_artifacts(
            self.task_id,
            {
                "frames_json": relative,
                "contact_sheet": "analysis/keyframes/contact-sheet.jpg",
                "frame_report": "analysis/keyframes/report.html",
            },
        )
        self.store.update_step(
            self.task_id,
            "frames",
            outputs=[relative, "analysis/keyframes/frames", "analysis/keyframes/contact-sheet.jpg"],
        )
        return frames

    def _select_images(
        self,
        outline: dict[str, Any],
        frames: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        images = choose_section_images(outline, frames, self.config.max_ocr_frames)
        path = self.task_dir / "article-images.json"
        write_json_atomic(path, images)
        self.store.merge_artifacts(self.task_id, {"article_images": "article-images.json"})
        self.store.update_step(self.task_id, "select_images", outputs=["article-images.json"])
        self.store.append_log(self.task_id, "select_images", f"为 {len(images)} 个章节选择了关键帧。")
        return images

    def _ocr_images(self, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not images:
            self.store.append_log(self.task_id, "ocr", "没有待 OCR 的章节配图。")
            return self._persist_ocr_images(images)
        if shutil.which("swift") is None:
            self.store.append_log(
                self.task_id,
                "ocr",
                "当前环境缺少 swift，保留图片并跳过 OCR。",
            )
            return self._persist_ocr_images(images)
        script = self.config.ocr_script
        if not script.is_file():
            self.store.append_log(
                self.task_id,
                "ocr",
                f"找不到本地 OCR 脚本，保留图片并跳过 OCR: {script}",
            )
            return self._persist_ocr_images(images)
        frame_dir = self.task_dir / "analysis/keyframes/frames"
        completed: list[dict[str, Any]] = []
        for image in images:
            frame_path = frame_dir / image["file"]
            command = [
                "swift",
                str(script),
                str(frame_path),
                "--lang",
                "zh-Hans,en-US",
                "--level",
                "accurate",
                "--positions",
            ]
            self.store.append_log(
                self.task_id,
                "ocr",
                f"$ {shlex.join(command)}",
            )
            copy = dict(image)
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                copy["ocr_error"] = "OCR 超过 120 秒。"
                completed.append(copy)
                continue
            if result.returncode == 0:
                copy["ocr_text"] = result.stdout.strip()
                if result.stdout.strip():
                    self.store.append_log(self.task_id, "ocr", result.stdout.strip())
            else:
                copy["ocr_error"] = result.stderr.strip() or f"退出码 {result.returncode}"
                self.store.append_log(self.task_id, "ocr", f"非阻塞失败: {copy['ocr_error']}")
            completed.append(copy)
        return self._persist_ocr_images(completed)

    def _persist_ocr_images(self, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
        path = self.task_dir / "ocr.json"
        write_json_atomic(path, images)
        self.store.merge_artifacts(self.task_id, {"ocr": "ocr.json"})
        self.store.update_step(self.task_id, "ocr", outputs=["ocr.json"])
        return images

    def _fake_article(
        self,
        metadata: dict[str, Any],
        outline: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "title": metadata["title"],
            "introduction": "这是测试模式生成的文章导语。",
            "sections": [
                {
                    "id": section["id"],
                    "body_markdown": f"{section['summary']}\n\n这是该章节的测试正文。",
                }
                for section in outline["sections"]
            ],
            "conclusion": "这是测试模式生成的文章结语。",
        }

    def _article_fingerprint(
        self,
        metadata: dict[str, Any],
        segments: list[dict[str, Any]],
        outline: dict[str, Any],
        images: list[dict[str, Any]],
    ) -> str:
        source = json.dumps(
            {
                "metadata": metadata,
                "segments": segments,
                "outline": outline,
                "images": images,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(source).hexdigest()

    def _load_article_progress(
        self,
        fingerprint: str,
        outline: dict[str, Any],
    ) -> dict[str, str]:
        checkpoint = self.task_dir / "article-progress.json"
        sections: dict[str, str] = {}
        if checkpoint.is_file():
            try:
                payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.store.append_log(
                    self.task_id,
                    "article",
                    "文章章节检查点无法解析，将忽略并重新生成。",
                )
            else:
                if payload.get("input_fingerprint") == fingerprint:
                    sections = self._validated_article_sections(
                        payload.get("sections"),
                        outline,
                    )
                else:
                    self.store.append_log(
                        self.task_id,
                        "article",
                        "文章章节检查点与当前输入不一致，将忽略旧检查点。",
                    )
        if sections:
            return sections
        return self._recover_legacy_article_sections(outline)

    def _recover_legacy_article_sections(
        self,
        outline: dict[str, Any],
    ) -> dict[str, str]:
        recovered: list[dict[str, str]] = []
        private_dir = self.task_dir / "private"
        for section in outline["sections"]:
            response_path = private_dir / f"article-{section['id']}-response.json"
            if not response_path.is_file():
                continue
            try:
                response_json = json.loads(response_path.read_text(encoding="utf-8"))
                content = response_json["choices"][0]["message"]["content"]
                payload = extract_json_object(str(content))
            except (KeyError, IndexError, TypeError, ValueError, PipelineError):
                continue
            response_id = str(payload.get("id") or section["id"])
            body = strip_leading_markdown_heading(
                str(payload.get("body_markdown") or "")
            )
            if response_id == section["id"] and body:
                recovered.append({"id": section["id"], "body_markdown": body})
        if recovered:
            self.store.append_log(
                self.task_id,
                "article",
                f"从旧响应文件恢复了 {len(recovered)} 个已完成章节。",
            )
        return {item["id"]: item["body_markdown"] for item in recovered}

    def _validated_article_sections(
        self,
        raw_sections: Any,
        outline: dict[str, Any],
    ) -> dict[str, str]:
        if not isinstance(raw_sections, list):
            return {}
        expected_ids = {str(section["id"]) for section in outline["sections"]}
        sections: dict[str, str] = {}
        for item in raw_sections:
            if not isinstance(item, dict):
                continue
            section_id = str(item.get("id") or "")
            body = strip_leading_markdown_heading(
                str(item.get("body_markdown") or "")
            )
            if section_id in expected_ids and body:
                sections[section_id] = body
        return sections

    def _save_article_progress(
        self,
        fingerprint: str,
        outline: dict[str, Any],
        sections: dict[str, str],
    ) -> None:
        ordered = [
            {"id": section["id"], "body_markdown": sections[section["id"]]}
            for section in outline["sections"]
            if section["id"] in sections
        ]
        write_json_atomic(
            self.task_dir / "article-progress.json",
            {
                "version": 1,
                "input_fingerprint": fingerprint,
                "updated_at": utc_now(),
                "sections": ordered,
            },
        )
        self.store.merge_artifacts(
            self.task_id,
            {"article_progress": "article-progress.json"},
        )
        self.store.update_step(
            self.task_id,
            "article",
            outputs=["article-progress.json"],
        )

    def _generate_article(
        self,
        metadata: dict[str, Any],
        segments: list[dict[str, Any]],
        outline: dict[str, Any],
        images: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if os.environ.get("VIDEODOC_FAKE_LLM") == "1":
            article = self._fake_article(metadata, outline)
        else:
            segment_indexes = {segment["id"]: index for index, segment in enumerate(segments)}
            image_by_section = {image["section_id"]: image for image in images}
            fingerprint = self._article_fingerprint(metadata, segments, outline, images)
            generated_by_id = self._load_article_progress(fingerprint, outline)
            if generated_by_id:
                self._save_article_progress(fingerprint, outline, generated_by_id)
            for index, section in enumerate(outline["sections"], start=1):
                if section["id"] in generated_by_id:
                    self.store.append_log(
                        self.task_id,
                        "article",
                        f"复用已完成章节 {index}/{len(outline['sections'])}: {section['title']}",
                    )
                    continue
                start_index = segment_indexes[section["start_segment_id"]]
                end_index = segment_indexes[section["end_segment_id"]]
                section_segments = segments[start_index : end_index + 1]
                transcript = transcript_for_prompt(section_segments, max_chars=40_000)
                image = image_by_section.get(section["id"], {})
                image_evidence = {
                    "timestamp": image.get("timestamp", ""),
                    "ocr_text": image.get("ocr_text", ""),
                }
                self.store.append_log(
                    self.task_id,
                    "article",
                    f"生成章节 {index}/{len(outline['sections'])}: {section['title']}",
                )
                payload = self._call_llm(
                    "article",
                    [
                        {
                            "role": "system",
                            "content": (
                                "你是严谨的中文技术文章作者。只依据当前章节转写、章节大纲和 OCR 证据写作，"
                                "不得虚构画面或事实。只返回 JSON 对象，不要插入图片，"
                                "也不要在 body_markdown 中重复章节标题。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                "返回结构：{id, body_markdown}。正文使用 Markdown，可含列表和代码块。\n\n"
                                f"视频标题：{metadata['title']}\n"
                                f"视频描述：{metadata.get('description', '')[:1200]}\n\n"
                                f"章节：{json.dumps(section, ensure_ascii=False)}\n\n"
                                f"配图 OCR：{json.dumps(image_evidence, ensure_ascii=False)}\n\n"
                                f"本章节转写：\n{transcript}"
                            ),
                        },
                    ],
                    response_name=f"article-{section['id']}-response",
                )
                response_id = str(payload.get("id") or section["id"])
                if response_id != section["id"]:
                    raise PipelineError(
                        f"文章章节返回了错误 ID: {response_id}，预期 {section['id']}。"
                    )
                body = strip_leading_markdown_heading(
                    str(payload.get("body_markdown") or "")
                )
                if not body:
                    raise PipelineError(f"文章章节 {section['id']} 正文为空。")
                generated_by_id[section["id"]] = body
                self._save_article_progress(fingerprint, outline, generated_by_id)
            generated_sections = [
                {"id": section["id"], "body_markdown": generated_by_id[section["id"]]}
                for section in outline["sections"]
            ]
            article = {
                "title": outline["title"],
                "introduction": outline["summary"],
                "sections": generated_sections,
                "conclusion": "",
            }
        raw_sections = article.get("sections")
        if not isinstance(raw_sections, list):
            raise PipelineError("文章缺少 sections。")
        bodies = {
            str(item.get("id")): str(item.get("body_markdown") or "")
            for item in raw_sections
            if isinstance(item, dict)
        }
        for section in outline["sections"]:
            if section["id"] not in bodies:
                raise PipelineError(f"文章缺少章节 {section['id']}。")
        normalized = {
            "title": str(article.get("title") or outline["title"]).strip(),
            "introduction": str(article.get("introduction") or outline["summary"]).strip(),
            "sections": [
                {
                    "id": section["id"],
                    "body_markdown": strip_leading_markdown_heading(bodies[section["id"]]),
                }
                for section in outline["sections"]
            ],
            "conclusion": str(article.get("conclusion") or "").strip(),
        }
        path = self.task_dir / "article.json"
        write_json_atomic(path, normalized)
        self.store.update(self.task_id, article_title=normalized["title"])
        self.store.merge_artifacts(self.task_id, {"article_json": "article.json"})
        outputs = ["article.json"]
        if (self.task_dir / "article-progress.json").is_file():
            outputs.insert(0, "article-progress.json")
        self.store.update_step(self.task_id, "article", outputs=outputs)
        return normalized

    def _finalize(
        self,
        metadata: dict[str, Any],
        video_path: Path,
        segments: list[dict[str, Any]],
        outline: dict[str, Any],
        images: list[dict[str, Any]],
        article: dict[str, Any],
    ) -> dict[str, Any]:
        bodies = {item["id"]: item["body_markdown"] for item in article["sections"]}
        image_by_section = {item["section_id"]: item for item in images}
        lines = [f"# {article['title']}", "", article["introduction"], ""]
        for section in outline["sections"]:
            lines.extend(
                [
                    f"## {section['title']}",
                    "",
                    f"[→ 跳到 {section['start_time']}](#t={int(section['start_sec'])})",
                    "",
                    bodies[section["id"]],
                    "",
                ]
            )
            image = image_by_section.get(section["id"])
            if image:
                image_path = f"analysis/keyframes/frames/{image['file']}"
                lines.extend(
                    [
                        f"[![{section['title']}]({image_path})](#t={int(image['timestamp_sec'])})",
                        "",
                        f"*画面时间：{image['timestamp']}*",
                        "",
                    ]
                )
        if article["conclusion"]:
            lines.extend(["## 总结", "", article["conclusion"], ""])
        markdown_text = "\n".join(lines).strip() + "\n"
        markdown_path = self.task_dir / "article.md"
        write_text_atomic(markdown_path, markdown_text)

        web_markdown = markdown_text.replace("](analysis/", "](media/analysis/")
        escaped = html.escape(web_markdown, quote=False)
        article_html = markdown.markdown(
            escaped,
            extensions=["extra", "tables", "sane_lists", "fenced_code"],
        )
        html_path = self.task_dir / "article.html"
        write_text_atomic(html_path, article_html)
        result = {
            "metadata": metadata,
            "article_title": article["title"],
            "video": video_path.relative_to(self.task_dir).as_posix(),
            "segments": segments,
            "outline": outline,
            "images": images,
            "article_markdown": "article.md",
            "article_html": "article.html",
        }
        result_path = self.task_dir / "result.json"
        write_json_atomic(result_path, result)
        artifacts = {
            "article_markdown": "article.md",
            "article_html": "article.html",
            "result": "result.json",
        }
        self.store.merge_artifacts(self.task_id, artifacts)
        self.store.update_step(self.task_id, "finalize", outputs=list(artifacts.values()))
        return result


def prepare_resume(store: TaskStore, task_id: str, config: PipelineConfig) -> str:
    pipeline = VideoArticlePipeline(store, task_id, config)
    return pipeline.resume_step()


def run_pipeline(
    store: TaskStore,
    task_id: str,
    config: PipelineConfig,
    start_at: str | None = None,
) -> None:
    pipeline = VideoArticlePipeline(store, task_id, config)
    pipeline.run(start_at=start_at)
