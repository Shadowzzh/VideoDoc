"""VideoDoc 专用的 claude-real-video CLI 入口。

claude-real-video 0.10.5 在完成抽帧后会无条件再次扫描整段视频，使用
``signalstats`` 判断是否存在补帧式慢动作。这个 temporal check 不参与
VideoDoc 的配图选择，却可能比场景检测和图片去重本身更耗时。

这里在进入第三方 CLI 前只替换该可选提示函数，保留其余命令行参数、产物和
错误处理行为。等上游提供正式关闭选项后，可以删除这个兼容层。
"""

from __future__ import annotations


def _no_temporal_hint(video_path: object, ffmpeg: str = "ffmpeg") -> None:
    """VideoDoc 不生成视频速度提示。"""
    del video_path, ffmpeg
    return None


def disable_temporal_check() -> None:
    """替换 CRV 的耗时 temporal check，必须在调用其 CLI 前执行。"""
    from claude_real_video import temporal_check

    temporal_check.temporal_hint = _no_temporal_hint


def main() -> None:
    disable_temporal_check()

    from claude_real_video.cli import main as crv_main

    crv_main()


if __name__ == "__main__":
    main()
