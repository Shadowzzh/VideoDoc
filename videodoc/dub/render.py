"""渲染：配音轨混音、背景音乐叠加、字幕烧录、成片合成。

两个容易踩的坑：

* **段数多了不能一次 amix。** 240 个输入会让命令行超限、CPU 打满，所以按
  ``GROUP_SIZE`` 分段混，再把几段混成总轨。
* **烧字幕的滤镜顺序。** ``drawbox`` 必须在 ``subtitles`` 前面，否则黑条会盖住字。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Sequence

SAMPLE_RATE = 44100
# 每组合并多少条轨；超过这个数就分组，避免命令行过长。
GROUP_SIZE = 40
# 字幕默认样式：白字 + 底部黑条（能盖住原片硬字幕）。
DEFAULT_FONT = "Noto Sans CJK SC"
DEFAULT_FONT_SIZE = 16
DEFAULT_BAR_HEIGHT = 52
DEFAULT_BAR_ALPHA = 0.72
DEFAULT_MARGIN_V = 10
DEFAULT_ENCODER = "libx264"


class RenderError(RuntimeError):
    """ffmpeg 失败。"""


def _run(args: Sequence[str], timeout: float = 1800) -> None:
    try:
        result = subprocess.run(list(args), capture_output=True, text=True,
                                timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RenderError("ffmpeg 超时") from exc
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-5:]
        raise RenderError("ffmpeg 失败: " + " / ".join(tail))


def _atempo(value: float) -> float:
    """ffmpeg 单次 atempo 的安全区间；超出就夹住。"""
    return min(2.0, max(0.5, float(value)))


def _mix_group(items: list[tuple[Path, float, int]], out: Path) -> Path:
    """把一组「音频 + 变速 + 延迟」混成一条轨。"""
    if not items:
        raise RenderError("没有可混合的音频")
    args: list[str] = ["ffmpeg", "-y"]
    for path, _, _ in items:
        args += ["-i", str(path)]

    filters = []
    for index, (_, tempo, delay_ms) in enumerate(items):
        filters.append(
            f"[{index}:a]atempo={_atempo(tempo):.3f},"
            f"adelay={delay_ms}|{delay_ms},"
            f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo"
            f"[a{index}]"
        )
    joined = "".join(f"[a{index}]" for index in range(len(items)))
    filters.append(
        f"{joined}amix=inputs={len(items)}:normalize=0:dropout_transition=0[out]"
    )
    args += ["-filter_complex", ";".join(filters), "-map", "[out]",
             "-ar", str(SAMPLE_RATE), "-ac", "2", str(out)]
    _run(args)
    return out


def _concat(paths: list[Path], out: Path) -> Path:
    """把几条已对齐的轨直接相加（不再变速/延迟）。"""
    if len(paths) == 1:
        paths[0].replace(out)
        return out
    args: list[str] = ["ffmpeg", "-y"]
    for path in paths:
        args += ["-i", str(path)]
    joined = "".join(f"[{i}:a]" for i in range(len(paths)))
    args += ["-filter_complex",
             f"{joined}amix=inputs={len(paths)}:normalize=0[out]",
             "-map", "[out]", "-ar", str(SAMPLE_RATE), "-ac", "2", str(out)]
    _run(args)
    return out


def mix_dub_track(
    plans: list[dict[str, Any]],
    wav_dir: Path,
    out: Path,
    *,
    group_size: int = GROUP_SIZE,
) -> Path:
    """按计划把每句配音摆到时间轴上，混成一条配音轨。"""
    items: list[tuple[Path, float, int]] = []
    for plan in plans:
        path = wav_dir / f"{plan['id']}.wav"
        if not path.is_file():
            continue
        delay = int(round(float(plan.get("start") or 0) * 1000))
        items.append((path, float(plan.get("tempo") or 1.0), delay))
    if not items:
        raise RenderError("没有任何已合成的配音片段")

    out.parent.mkdir(parents=True, exist_ok=True)
    if len(items) <= group_size:
        return _mix_group(items, out)

    parts: list[Path] = []
    for index in range(0, len(items), group_size):
        chunk = items[index:index + group_size]
        part = out.with_name(f"{out.stem}-part{index // group_size}{out.suffix}")
        parts.append(_mix_group(chunk, part))
    try:
        return _concat(parts, out)
    finally:
        for part in parts:
            part.unlink(missing_ok=True)


def overlay_background(
    dub: Path,
    background: Path,
    out: Path,
    *,
    gain: float = 1.0,
) -> Path:
    """把背景音乐叠到配音轨上。``gain`` 是线性倍数，1.0 保持原音量。"""
    args = [
        "ffmpeg", "-y", "-i", str(dub), "-i", str(background),
        "-filter_complex",
        f"[0:a]aformat=sample_rates={SAMPLE_RATE}:channel_layouts=stereo[d];"
        f"[1:a]volume={gain},aformat=sample_rates={SAMPLE_RATE}:channel_layouts=stereo[b];"
        f"[d][b]amix=inputs=2:normalize=0:duration=first[m]",
        "-map", "[m]", "-ar", str(SAMPLE_RATE), "-ac", "2", str(out),
    ]
    _run(args)
    return out


def _video_height(path: Path) -> int:
    """读视频高度，用来按比例算字号和黑条；读不到时按 1080p 处理。"""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=height", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 1080


def _subtitle_style(
    font: str,
    font_size: int,
    margin_v: int,
    boxed: bool,
) -> str:
    """生成 ASS 覆盖样式。``boxed`` 为真时用背景框而不是描边。"""
    border_style = 3 if boxed else 1
    outline = 2 if boxed else 1
    return (
        f"FontName={font},FontSize={font_size},"
        f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        f"BorderStyle={border_style},Outline={outline},Shadow=0,MarginV={margin_v}"
    )


def burn_subtitles(
    video: Path,
    srt: Path,
    out: Path,
    *,
    bar: bool = True,
    bar_height: int | None = None,
    bar_alpha: float = DEFAULT_BAR_ALPHA,
    font: str = DEFAULT_FONT,
    font_size: int | None = None,
    margin_v: int | None = None,
    encoder: str = DEFAULT_ENCODER,
    crf: int = 20,
) -> Path:
    """烧录硬字幕。``bar`` 为真时先在底部铺一条半透明黑带。

    字号和黑条默认按视频高度比例算：1080p 用 54px 字号、156px 黑条，360p 自动
    缩到 18px / 52px。写死像素会让同一套样式在两种分辨率上差异巨大。
    """
    height = _video_height(video)
    if font_size is None:
        # ASS 的 FontSize 是相对 PlayResY 的单位，不随像素高度变：
        # 18 在 360p 和 1080p 上占的画面比例相同。按像素算会放大成巨字。
        font_size = DEFAULT_FONT_SIZE
    if bar_height is None:
        bar_height = max(40, round(height * 0.145))
    if margin_v is None:
        margin_v = max(8, round(height * 0.028))

    filters: list[str] = []
    if bar:
        filters.append(
            f"drawbox=x=0:y=ih-{bar_height}:w=iw:h={bar_height}"
            f":color=black@{bar_alpha}:t=fill"
        )
    style = _subtitle_style(font, font_size, margin_v, boxed=False)
    filters.append(f"subtitles={srt}:force_style='{style}'")

    args = [
        "ffmpeg", "-y", "-i", str(video), "-vf", ",".join(filters),
        "-c:a", "copy", "-c:v", encoder, "-crf", str(crf),
        "-preset", "medium", str(out),
    ]
    _run(args)
    return out


def compose(
    video: Path,
    audio: Path,
    out: Path,
    *,
    srt: Path | None = None,
    encoder: str = "copy",
) -> Path:
    """把画面和配音合成成片；``srt`` 给了就同时挂一条软字幕。"""
    args = ["ffmpeg", "-y", "-i", str(video), "-i", str(audio)]
    if srt is not None:
        args += ["-i", str(srt)]
        args += ["-map", "0:v", "-map", "1:a", "-map", "2:s",
                 "-c:s", "mov_text", "-metadata:s:s:0", "language=chi"]
    else:
        args += ["-map", "0:v", "-map", "1:a"]
    args += ["-c:v", encoder]
    if encoder != "copy":
        args += ["-crf", "20", "-preset", "medium"]
    args += ["-c:a", "aac", "-b:a", "192k", "-shortest", str(out)]
    _run(args)
    return out
