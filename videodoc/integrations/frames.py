"""关键帧抽取：包装 claude-real-video (crv) 并整理为任务产物。

crv 是第三方 MIT 项目（https://github.com/HUANGCHIHHUNGLeo/claude-real-video），
负责场景检测、去重和逐帧源视频时间戳映射。这里只做三件事：

1. 用固定参数调用 crv；
2. 把 crv 的产物搬进任务目录，并丢弃它自带的原视频副本；
3. 补一张联系表（crv 只出 3x3 网格，这里是逐帧缩略总览）。

不直接让 crv 写进任务目录，是因为它会把整段原视频再复制一份进输出目录，
而视频已经在任务的 video/ 下，重复保存会让任务体积翻倍。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

# crv 产物中需要保留的部分；source.mp4 是 crv 自带的原视频副本，直接丢弃。
COPIED_FILES = ("frames.json", "MANIFEST.txt", "report.html")
COPIED_DIRS = ("frames", "dropped")

CONTACT_SHEET_NAME = "contact-sheet.jpg"
CONTACT_SHEET_COLUMNS = 8
THUMBNAIL_WIDTH = 160
THUMBNAIL_HEIGHT = 90
LABEL_HEIGHT = 18

# crv 会把分析过的视频记进 ~/.crv/memory.db，并在同源同参数时短路跳过。
# 本流水线每次产物独立，不依赖该记忆，禁用后重跑行为可预期。
# CRV_NO_HINT 关掉 crv 结尾的 Pro 提示。
CRV_ENV = {"CRV_NO_MEMORY": "1", "CRV_NO_HINT": "1"}


class FramesError(RuntimeError):
    """抽帧失败；消息可直接展示到任务页面。"""


def crv_command() -> list[str]:
    """返回 crv 的命令前缀。

    默认用当前解释器执行 ``python -m claude_real_video``，不依赖 PATH；
    可用 ``VIDEODOC_CRV`` 覆盖为自定义二进制。
    """
    override = os.environ.get("VIDEODOC_CRV")
    if override:
        return [override]
    return [sys.executable, "-m", "claude_real_video"]


def build_command(
    video_path: Path,
    output_dir: Path,
    *,
    scene: float,
    fps_floor: float,
    max_frames: int,
    frame_width: int,
    why: str | None = None,
) -> list[str]:
    """构造 crv 调用命令。"""
    command = [
        *crv_command(),
        str(video_path),
        "-o",
        str(output_dir),
        "--overwrite",
        "--report",
        "--no-transcribe",
        "--scene",
        str(scene),
        "--fps-floor",
        str(fps_floor),
        "--max-frames",
        str(max_frames),
        "--frame-width",
        str(frame_width),
    ]
    if why:
        command += ["--why", why]
    return command


def _default_runner(command: list[str], env: dict[str, str]) -> None:
    """默认执行器：边跑边把输出透到 stderr/stdout。"""
    try:
        result = subprocess.run(command, env=env, check=False)
    except FileNotFoundError as exc:
        raise FramesError(f"找不到 crv 命令: {command[0]}（{exc}）") from exc
    if result.returncode != 0:
        raise FramesError(f"crv 退出码 {result.returncode}")


def _collect(output_dir: Path, artifact_dir: Path) -> None:
    """把 crv 产物从工作目录搬到任务产物目录。"""
    frames_json = output_dir / "frames.json"
    if not frames_json.is_file():
        raise FramesError("crv 没有生成 frames.json。")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    for filename in COPIED_FILES:
        source = output_dir / filename
        if source.is_file():
            shutil.copy2(source, artifact_dir / filename)
    for dirname in COPIED_DIRS:
        source = output_dir / dirname
        if source.is_dir():
            target = artifact_dir / dirname
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)


def make_contact_sheet(artifact_dir: Path) -> None:
    """把关键帧拼成一张带文件名的缩略总览图。"""
    from PIL import Image, ImageDraw

    frames = sorted((artifact_dir / "frames").glob("frame_*.jpg"))
    if not frames:
        raise FramesError("没有可用的关键帧，无法生成联系表。")

    columns = CONTACT_SHEET_COLUMNS
    import math

    rows = math.ceil(len(frames) / columns)
    sheet = Image.new(
        "RGB",
        (columns * THUMBNAIL_WIDTH, rows * (THUMBNAIL_HEIGHT + LABEL_HEIGHT)),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(frames):
        image = Image.open(path).convert("RGB")
        image = image.resize((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT))
        x = (index % columns) * THUMBNAIL_WIDTH
        y = (index // columns) * (THUMBNAIL_HEIGHT + LABEL_HEIGHT)
        sheet.paste(image, (x, y))
        draw.text((x + 4, y + THUMBNAIL_HEIGHT + 2), path.stem, fill=(0, 0, 0))
    sheet.save(artifact_dir / CONTACT_SHEET_NAME, quality=88)


def read_frames(artifact_dir: Path) -> list[dict]:
    """读取并校验 frames.json。"""
    frames_json = artifact_dir / "frames.json"
    if not frames_json.is_file():
        raise FramesError("抽帧工具没有生成 frames.json。")
    try:
        data = json.loads(frames_json.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise FramesError(f"frames.json 解析失败: {exc}") from exc
    frames = data.get("frames")
    if not isinstance(frames, list) or not frames:
        raise FramesError("frames.json 中没有关键帧。")
    return frames


def extract_frames(
    video_path: Path,
    analysis_dir: Path,
    *,
    scene: float,
    fps_floor: float,
    max_frames: int,
    frame_width: int,
    why: str | None = None,
    name: str = "keyframes",
    runner: Callable[[list[str], dict[str, str]], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[Path, list[dict]]:
    """抽取关键帧。

    返回 ``(产物目录, 帧列表)``；产物目录为 ``analysis_dir/name``。
    """
    if not video_path.is_file():
        raise FramesError(f"找不到待抽帧的视频: {video_path}")

    artifact_dir = analysis_dir / name
    work_dir = analysis_dir / f".{name}-work"
    # crv 拒绝写入非空输出目录（避免混入其他视频），每次运行前清空。
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    command = build_command(
        video_path,
        work_dir,
        scene=scene,
        fps_floor=fps_floor,
        max_frames=max_frames,
        frame_width=frame_width,
        why=why,
    )
    env = dict(os.environ)
    env.update(CRV_ENV)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)

    if log:
        log(f"$ {' '.join(command)}")
    try:
        (runner or _default_runner)(command, env)
        _collect(work_dir, artifact_dir)
        make_contact_sheet(artifact_dir)
        frames = read_frames(artifact_dir)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return artifact_dir, frames
