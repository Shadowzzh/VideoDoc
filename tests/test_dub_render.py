"""渲染层能单测的部分：样式生成、参数夹紧、空输入保护。"""

from __future__ import annotations

from pathlib import Path

import pytest

from videodoc.dub.render import (
    RenderError,
    _atempo,
    _subtitle_style,
    mix_dub_track,
)


def test_atempo_clamps_to_safe_range():
    assert _atempo(1.0) == 1.0
    assert _atempo(1.15) == 1.15
    assert _atempo(3.0) == 2.0
    assert _atempo(0.1) == 0.5


def test_subtitle_style_boxed_uses_border_style_3():
    style = _subtitle_style("Noto Sans CJK SC", 18, 10, boxed=True)
    assert "BorderStyle=3" in style
    assert "Outline=2" in style
    assert "PrimaryColour=&H00FFFFFF" in style


def test_subtitle_style_outline_uses_border_style_1():
    style = _subtitle_style("Noto Sans CJK SC", 18, 10, boxed=False)
    assert "BorderStyle=1" in style
    assert "Outline=1" in style
    assert "MarginV=10" in style


def test_mix_requires_at_least_one_clip(tmp_path: Path):
    with pytest.raises(RenderError):
        mix_dub_track([], tmp_path / "wav", tmp_path / "out.wav")


def test_mix_skips_missing_files(tmp_path: Path):
    wav_dir = tmp_path / "wav"
    wav_dir.mkdir()
    plans = [{"id": "seg-00001", "start": 0.0, "tempo": 1.0}]
    with pytest.raises(RenderError):
        mix_dub_track(plans, wav_dir, tmp_path / "out.wav")
