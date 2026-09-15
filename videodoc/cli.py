"""videodoc 命令行入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="videodoc",
        description="把视频链接转成带时间锚点和配图的图文文章",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"监听地址（默认 {DEFAULT_HOST}）")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"监听端口（默认 {DEFAULT_PORT}）"
    )
    return parser


def frontend_dist_dir() -> Path:
    from .server import DEFAULT_FRONTEND_DIST

    return DEFAULT_FRONTEND_DIST


def ensure_frontend_built() -> None:
    """前端是本项目的主界面，未构建时不静默启动。"""
    dist = frontend_dist_dir()
    if (dist / "index.html").is_file():
        return
    project_root = dist.parent.parent
    print(
        "前端尚未构建，无法提供网页界面。\n"
        f"缺少构建产物: {dist}\n"
        "请先在项目根目录执行：\n"
        f"  pnpm --dir {project_root / 'frontend'} install\n"
        f"  pnpm --dir {project_root / 'frontend'} build\n"
        "或直接使用 ./scripts/serve.sh（会自动完成安装与构建）。",
        file=sys.stderr,
    )
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # .env 必须在 create_app() 之前载入：运行目录等配置在应用创建时读取；
    # 已存在的真实环境变量优先，.env 只做兜底。
    from .config import default_env_file, load_env_file

    project_root = frontend_dist_dir().parent.parent
    applied = load_env_file(default_env_file(project_root))
    if applied:
        print(f"已从环境文件载入 {len(applied)} 项配置")

    ensure_frontend_built()

    from .server import create_app

    app = create_app()
    print(f"运行数据: {app.config['RUNTIME_ROOT']}")
    print(f"访问入口: http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
