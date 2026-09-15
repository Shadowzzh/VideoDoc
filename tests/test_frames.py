"""抽帧适配层单元测试：不调用真实 crv。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from videodoc.integrations import frames as frames_module
from videodoc.integrations.frames import (
    CONTACT_SHEET_NAME,
    FramesError,
    build_command,
    crv_command,
    extract_frames,
    read_frames,
)


def make_fake_crv(*, frame_count: int = 3, with_frames_json: bool = True):
    """构造一个假 crv：按命令里的 -o 目录写出产物。"""

    def runner(command: list[str], env: dict[str, str]) -> None:
        output_dir = Path(command[command.index("-o") + 1])
        (output_dir / "frames").mkdir(parents=True, exist_ok=True)
        (output_dir / "dropped").mkdir(parents=True, exist_ok=True)
        payload = []
        for index in range(1, frame_count + 1):
            name = f"frame_{index:03d}.jpg"
            Image.new("RGB", (32, 18), "white").save(output_dir / "frames" / name)
            payload.append(
                {
                    "file": name,
                    "timestamp_sec": float(index),
                    "timestamp": f"00:00:0{index}.000",
                    "selection_reason": "test",
                }
            )
        if with_frames_json:
            (output_dir / "frames.json").write_text(
                json.dumps({"frames": payload}), encoding="utf-8"
            )
        (output_dir / "MANIFEST.txt").write_text("manifest", encoding="utf-8")
        (output_dir / "report.html").write_text("<html></html>", encoding="utf-8")
        # crv 会把原视频复制进输出目录，必须被丢弃
        (output_dir / "source.mp4").write_bytes(b"fake-video")

    return runner


@pytest.fixture()
def video(tmp_path: Path) -> Path:
    path = tmp_path / "input" / "source.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    return path


def test_build_command_carries_pipeline_parameters(tmp_path: Path) -> None:
    command = build_command(
        tmp_path / "v.mp4",
        tmp_path / "out",
        scene=0.3,
        fps_floor=3.0,
        max_frames=120,
        frame_width=960,
        why="为文章选配图",
    )
    assert command[command.index("--scene") + 1] == "0.3"
    assert command[command.index("--fps-floor") + 1] == "3.0"
    assert command[command.index("--max-frames") + 1] == "120"
    assert command[command.index("--frame-width") + 1] == "960"
    assert command[command.index("--why") + 1] == "为文章选配图"
    assert "--report" in command
    # 转写由本流水线自己的步骤负责，不能让 crv 重复跑一遍
    assert "--no-transcribe" in command
    assert "-o" in command


def test_crv_command_respects_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIDEODOC_CRV", "/custom/crv")
    assert crv_command() == ["/custom/crv"]
    monkeypatch.delenv("VIDEODOC_CRV")
    assert crv_command()[1:] == ["-m", "claude_real_video"]


def test_extract_frames_collects_artifacts(tmp_path: Path, video: Path) -> None:
    analysis_dir = tmp_path / "analysis"
    artifact_dir, result = extract_frames(
        video,
        analysis_dir,
        scene=0.3,
        fps_floor=3.0,
        max_frames=120,
        frame_width=960,
        runner=make_fake_crv(frame_count=3),
    )

    assert artifact_dir == analysis_dir / "keyframes"
    assert [frame["file"] for frame in result] == [
        "frame_001.jpg",
        "frame_002.jpg",
        "frame_003.jpg",
    ]
    assert (artifact_dir / "frames.json").is_file()
    assert (artifact_dir / "MANIFEST.txt").is_file()
    assert (artifact_dir / "report.html").is_file()
    assert (artifact_dir / "frames" / "frame_001.jpg").is_file()
    assert (artifact_dir / "dropped").is_dir()
    assert (artifact_dir / CONTACT_SHEET_NAME).is_file()


def test_extract_frames_drops_crv_video_copy(tmp_path: Path, video: Path) -> None:
    artifact_dir, _ = extract_frames(
        video,
        tmp_path / "analysis",
        scene=0.3,
        fps_floor=3.0,
        max_frames=120,
        frame_width=960,
        runner=make_fake_crv(),
    )
    # 原视频已在任务 video/ 下，不能因为 crv 的复制行为再存一份
    assert not (artifact_dir / "source.mp4").exists()


def test_extract_frames_cleans_work_directory(tmp_path: Path, video: Path) -> None:
    analysis_dir = tmp_path / "analysis"
    extract_frames(
        video,
        analysis_dir,
        scene=0.3,
        fps_floor=3.0,
        max_frames=120,
        frame_width=960,
        runner=make_fake_crv(),
    )
    assert not (analysis_dir / ".keyframes-work").exists()
    assert sorted(p.name for p in analysis_dir.iterdir()) == ["keyframes"]


def test_extract_frames_cleans_work_directory_on_failure(
    tmp_path: Path, video: Path
) -> None:
    analysis_dir = tmp_path / "analysis"

    def boom(command: list[str], env: dict[str, str]) -> None:
        output_dir = Path(command[command.index("-o") + 1])
        (output_dir / "partial.bin").write_bytes(b"x")
        raise FramesError("crv 退出码 1")

    with pytest.raises(FramesError):
        extract_frames(
            video,
            analysis_dir,
            scene=0.3,
            fps_floor=3.0,
            max_frames=120,
            frame_width=960,
            runner=boom,
        )
    assert not (analysis_dir / ".keyframes-work").exists()


def test_extract_frames_requires_frames_json(tmp_path: Path, video: Path) -> None:
    with pytest.raises(FramesError, match="frames.json"):
        extract_frames(
            video,
            tmp_path / "analysis",
            scene=0.3,
            fps_floor=3.0,
            max_frames=120,
            frame_width=960,
            runner=make_fake_crv(with_frames_json=False),
        )


def test_extract_frames_rejects_missing_video(tmp_path: Path) -> None:
    with pytest.raises(FramesError, match="找不到待抽帧的视频"):
        extract_frames(
            tmp_path / "missing.mp4",
            tmp_path / "analysis",
            scene=0.3,
            fps_floor=3.0,
            max_frames=120,
            frame_width=960,
            runner=make_fake_crv(),
        )


def test_extract_frames_sets_crv_isolation_flags(
    tmp_path: Path, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CRV_NO_MEMORY", raising=False)
    seen: dict[str, str] = {}

    def capture(command: list[str], env: dict[str, str]) -> None:
        seen.update(env)
        make_fake_crv()(command, env)

    extract_frames(
        video,
        tmp_path / "analysis",
        scene=0.3,
        fps_floor=3.0,
        max_frames=120,
        frame_width=960,
        runner=capture,
    )
    assert seen["CRV_NO_MEMORY"] == "1"
    assert seen["CRV_NO_HINT"] == "1"


def test_read_frames_rejects_empty_payload(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "keyframes"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "frames.json").write_text(json.dumps({"frames": []}), encoding="utf-8")
    with pytest.raises(FramesError, match="没有关键帧"):
        read_frames(artifact_dir)


def test_read_frames_rejects_broken_json(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "keyframes"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "frames.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(FramesError, match="解析失败"):
        read_frames(artifact_dir)


def test_contact_sheet_requires_frames(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "keyframes"
    artifact_dir.mkdir(parents=True)
    with pytest.raises(FramesError, match="没有可用的关键帧"):
        frames_module.make_contact_sheet(artifact_dir)
