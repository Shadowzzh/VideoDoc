"""本地 OCR 引擎：调用 macOS Vision（经随包 Swift 脚本）。

平台边界说明：这是**唯一**依赖 macOS 的通道（Vision 框架 + swift）。
非 macOS 上 ``available()`` 返回 False，流水线会改走远端视觉引擎或跳过该通道。

从 ``pipeline.py`` 迁出，保持命令与参数完全一致（含 ``--positions``），
迁移后同一张图的 ``ocr_text`` 与迁移前字节级一致。
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SWIFT_BIN = "swift"
DEFAULT_LANGUAGE = "zh-Hans,en-US"
DEFAULT_LEVEL = "accurate"
DEFAULT_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class LocalVisionConfig:
    script: Path
    language: str = DEFAULT_LANGUAGE
    level: str = DEFAULT_LEVEL
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def available(self) -> tuple[bool, str]:
        """返回 (是否可用, 不可用原因)。"""
        if shutil.which(SWIFT_BIN) is None:
            return False, "当前环境缺少 swift，无法使用本地 macOS Vision OCR。"
        if not self.script.is_file():
            return False, f"找不到本地 OCR 脚本: {self.script}"
        return True, ""

    def command(self, image_path: Path) -> list[str]:
        return [
            SWIFT_BIN,
            str(self.script),
            str(image_path),
            "--lang",
            self.language,
            "--level",
            self.level,
            "--positions",
        ]


def recognize(config: LocalVisionConfig, image_path: Path) -> str:
    """对单张图片做本地 OCR，返回逐行文本（含 ``text\tx\ty`` 坐标列）。

    失败时抛 ``LocalVisionError``，由调用方记录成该图的 ``ocr_error``。
    """
    try:
        result = subprocess.run(
            config.command(image_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=config.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise LocalVisionError(f"OCR 超过 {config.timeout_seconds} 秒。") from error
    if result.returncode != 0:
        raise LocalVisionError(result.stderr.strip() or f"退出码 {result.returncode}")
    return result.stdout.strip()


class LocalVisionError(RuntimeError):
    """本地 OCR 失败（非阻塞：调用方记录后继续）。"""
