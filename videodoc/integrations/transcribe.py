"""音频转写适配层。

默认后端是 ``pywhispercpp``（whisper.cpp 的 Python 绑定），它以预编译 wheel
分发，macOS 上还会带上 Metal 后端，因此各平台都能 ``pip install`` 直接用，
无需自行编译 whisper.cpp。

如果设置了 ``VIDEODOC_WHISPER_BIN``，则改用外部 whisper CLI：命令会以
``<bin> <audio> -of <prefix>`` 调用，并读取它写出的 ``<prefix>.srt``。
这条路径用于兼容自备的 whisper.cpp 构建。

模型来源：

* ``VIDEODOC_WHISPER_MODEL``：模型名（如 ``large-v3-turbo``）或 ``.bin`` 绝对路径；
* ``VIDEODOC_WHISPER_MODEL_DIR``：模型搜索目录。

默认只给模型名，首次运行会从 HuggingFace 下载（约 1.5GB）。内网环境可以先
自行下载 ``ggml-*.bin``，再用 ``VIDEODOC_WHISPER_MODEL`` 指向本地文件。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

DEFAULT_MODEL = "large-v3-turbo"
DEFAULT_LANGUAGE = "auto"
SRT_PREFIX = "transcript"


class TranscribeError(RuntimeError):
    """转写失败；消息可直接展示到任务页面。"""


def model_reference() -> str:
    return os.environ.get("VIDEODOC_WHISPER_MODEL", DEFAULT_MODEL)


def model_dir() -> str | None:
    value = os.environ.get("VIDEODOC_WHISPER_MODEL_DIR")
    return value or None


def language() -> str | None:
    value = os.environ.get("VIDEODOC_WHISPER_LANGUAGE", DEFAULT_LANGUAGE)
    # whisper.cpp 用省略参数表示自动识别；显式传 "auto" 会打一条无用的告警。
    if value in {"", "auto"}:
        return None
    return value


def thread_count() -> int:
    raw = os.environ.get("VIDEODOC_WHISPER_THREADS")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return max(1, min(8, os.cpu_count() or 4))


def format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def to_pipeline_segments(raw_segments: list[Any]) -> list[dict[str, Any]]:
    """把 whisper 原始分段转成流水线统一格式（t0/t1 单位是厘秒）。"""
    segments: list[dict[str, Any]] = []
    for raw in raw_segments:
        text = (getattr(raw, "text", "") or "").strip()
        if not text:
            continue
        segments.append(
            {
                "id": f"seg-{len(segments) + 1:05d}",
                "start_sec": float(raw.t0) / 100.0,
                "end_sec": float(raw.t1) / 100.0,
                "text": text,
            }
        )
    return segments


def write_srt(segments: list[dict[str, Any]], path: Path) -> None:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n"
            f"{format_srt_timestamp(segment['start_sec'])} --> "
            f"{format_srt_timestamp(segment['end_sec'])}\n"
            f"{segment['text']}"
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def write_text(segments: list[dict[str, Any]], path: Path) -> None:
    path.write_text(
        "\n".join(segment["text"] for segment in segments) + "\n", encoding="utf-8"
    )


def _run_pywhispercpp(
    audio_path: Path,
    log_path: Path,
    *,
    log: Callable[[str], None] | None,
) -> list[dict[str, Any]]:
    try:
        from pywhispercpp.model import Model
    except ImportError as exc:  # pragma: no cover - 依赖缺失时的可读提示
        raise TranscribeError(
            "缺少 pywhispercpp，请先安装依赖：在项目根目录运行 pip install -e ."
        ) from exc

    reference = model_reference()
    directory = model_dir()
    if not Path(reference).is_file() and directory is None:
        if log:
            log(
                f"未发现本地模型 {reference}，首次运行会从 HuggingFace 下载（约 1.5GB）；"
                "内网环境可用 VIDEODOC_WHISPER_MODEL 指向已下载的 .bin 文件。"
            )

    model = Model(
        model=reference,
        models_dir=directory,
        n_threads=thread_count(),
        redirect_whispercpp_logs_to=str(log_path),
    )
    raw = model.transcribe(
        str(audio_path),
        language=language(),
        print_progress=True,
    )
    return to_pipeline_segments(list(raw))


def _run_cli(
    audio_path: Path,
    prefix: Path,
    *,
    runner: Callable[[list[str], dict[str, str]], None] | None,
) -> list[dict[str, Any]]:
    binary = os.environ.get("VIDEODOC_WHISPER_BIN", "")
    resolved = shutil.which(binary) or binary
    if not resolved or not Path(resolved).exists():
        raise TranscribeError(f"找不到 whisper 可执行文件: {binary}")

    command = [resolved, str(audio_path), "-of", str(prefix)]
    env = dict(os.environ)
    if runner is not None:
        runner(command, env)
    else:
        try:
            result = subprocess.run(command, env=env, check=False)
        except FileNotFoundError as exc:
            raise TranscribeError(f"找不到 whisper 可执行文件: {resolved}（{exc}）") from exc
        if result.returncode != 0:
            raise TranscribeError(f"whisper 退出码 {result.returncode}")

    srt_path = prefix.with_suffix(".srt")
    if not srt_path.is_file():
        raise TranscribeError("Whisper 没有生成 transcript.srt。")
    return parse_srt(srt_path.read_text(encoding="utf-8", errors="replace"))


def parse_srt(text: str) -> list[dict[str, Any]]:
    """解析 SRT；仅用于外部 CLI 后端。"""
    import re

    pattern = re.compile(r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})")
    segments: list[dict[str, Any]] = []
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        time_index = 1 if lines[0].strip().isdigit() else 0
        if time_index >= len(lines) or "-->" not in lines[time_index]:
            continue
        start_text, end_text = [
            part.strip().split()[0] for part in lines[time_index].split("-->", 1)
        ]

        def seconds(value: str) -> float:
            match = pattern.fullmatch(value)
            if match is None:
                raise ValueError(f"无效 SRT 时间戳: {value}")
            parts = {key: int(number) for key, number in match.groupdict().items()}
            return parts["h"] * 3600 + parts["m"] * 60 + parts["s"] + parts["ms"] / 1000

        body = " ".join(line.strip() for line in lines[time_index + 1 :]).strip()
        if not body:
            continue
        segments.append(
            {
                "id": f"seg-{len(segments) + 1:05d}",
                "start_sec": seconds(start_text),
                "end_sec": seconds(end_text),
                "text": body,
            }
        )
    if not segments:
        raise TranscribeError("Whisper 没有生成可解析的 SRT 时间轴。")
    return segments


def transcribe(
    audio_path: Path,
    transcript_dir: Path,
    *,
    runner: Callable[[list[str], dict[str, str]], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """转写音频，写出 ``transcript.srt`` / ``transcript.txt`` 并返回分段。

    分段格式与流水线一致：``{id, start_sec, end_sec, text}``。
    """
    if not audio_path.is_file():
        raise TranscribeError(f"找不到待转写的音频: {audio_path}")

    transcript_dir.mkdir(parents=True, exist_ok=True)
    prefix = transcript_dir / SRT_PREFIX
    srt_path = prefix.with_suffix(".srt")
    text_path = prefix.with_suffix(".txt")

    if os.environ.get("VIDEODOC_WHISPER_BIN"):
        if log:
            log(f"使用外部 whisper CLI: {os.environ['VIDEODOC_WHISPER_BIN']}")
        segments = _run_cli(audio_path, prefix, runner=runner)
        if not text_path.is_file():
            write_text(segments, text_path)
    else:
        log_path = transcript_dir / "whisper.log"
        if log:
            log(
                f"使用 pywhispercpp 转写（模型 {model_reference()}，"
                f"线程 {thread_count()}）"
            )
        segments = _run_pywhispercpp(audio_path, log_path, log=log)
        write_srt(segments, srt_path)
        write_text(segments, text_path)

    if not srt_path.is_file():
        raise TranscribeError("Whisper 没有生成 transcript.srt。")
    if not segments:
        raise TranscribeError("Whisper 没有识别出任何语音片段。")
    return segments
