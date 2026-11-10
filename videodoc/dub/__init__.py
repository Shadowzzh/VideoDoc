"""配音链路的公共入口。

子模块分工：

* ``align``    —— 短段合并、吃间隙、变速上限（纯函数，可单测）
* ``tts``      —— TTS 后端协议 + Ming 实现
* ``separate`` —— 人声分离协议 + demucs 实现
* ``render``   —— 混音、字幕烧录、成片合成
* ``runner``   —— 编排、断点续跑、manifest

音节估算和配音稿 prompt 暂时留在 ``videodoc.dubbing``（已测），
这里只做 re-export，避免调用方同时 import 两处。
"""

from __future__ import annotations

from ..dubbing import (  # noqa: F401
    DEFAULT_MAX_TEMPO,
    DEFAULT_RATE,
    build_rewrite_messages,
    merge_rewrites,
    normalize_tone,
    syllables,
    target_syllables,
    tone_description,
)

__all__ = [
    "DEFAULT_MAX_TEMPO",
    "DEFAULT_RATE",
    "build_rewrite_messages",
    "merge_rewrites",
    "normalize_tone",
    "syllables",
    "target_syllables",
    "tone_description",
]
