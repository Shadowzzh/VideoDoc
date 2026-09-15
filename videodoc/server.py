"""VideoDoc 视频图文工作台 Web 服务。"""

from __future__ import annotations

import html
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import markdown
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    request,
    send_from_directory,
)

from .pipeline import PipelineConfig, PipelineError, prepare_resume, run_pipeline
from .task_store import TaskConfirmationError, TaskStateError, TaskStore


PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 运行数据默认写在用户级目录，避免污染仓库（可用 VIDEODOC_RUNTIME_DIR 覆盖）。
DEFAULT_RUNTIME_ROOT = Path.home() / ".local" / "share" / "videodoc"
DEFAULT_FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
# 示例产物目录：存放流水线跑出来的成品文章，供 /sample 页面展示。
EXAMPLES_DIR = PROJECT_ROOT / "examples"
ASSETS_DIR = EXAMPLES_DIR / "assets"
SAMPLE_ARTICLE = EXAMPLES_DIR / "2026-09-09-inkypi-eink-clock.md"
MD_EXTENSIONS = ["extra", "tables", "sane_lists", "fenced_code", "attr_list", "toc"]

# 示例文章页面：自包含 HTML（内联样式），不依赖任何模板或静态资源目录。
SAMPLE_PAGE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ · VideoDoc</title>
<style>
  :root { color-scheme: light dark; --bg:#f4f1e9; --panel:#fffdf8; --text:#191814;
          --muted:#706d64; --line:#ded9ce; --accent:#1f6f5d; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text); line-height:1.75;
         font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; }
  header { position:sticky; top:0; z-index:10; height:64px; display:flex; align-items:center;
           gap:24px; padding:0 max(24px, calc((100vw - 1100px)/2));
           border-bottom:1px solid var(--line); background:var(--panel); }
  header a { color:var(--muted); text-decoration:none; }
  header .brand { font-weight:800; color:var(--text); letter-spacing:-.02em; }
  main { max-width:1100px; margin:0 auto; padding:40px 24px 96px; }
  article { background:var(--panel); border:1px solid var(--line); border-radius:18px;
            padding:clamp(24px, 4vw, 56px); box-shadow:0 18px 50px rgba(54,47,32,.07); }
  article img { max-width:100%; height:auto; border-radius:12px; }
  article h1, article h2, article h3 { line-height:1.25; letter-spacing:-.02em; }
  article code { background:var(--bg); padding:.15em .35em; border-radius:6px; }
  article pre { background:var(--bg); padding:16px; border-radius:12px; overflow:auto; }
  article blockquote { margin:0; padding-left:16px; border-left:3px solid var(--accent);
                       color:var(--muted); }
  article table { border-collapse:collapse; width:100%; }
  article th, article td { border:1px solid var(--line); padding:8px 12px; text-align:left; }
</style>
</head>
<body>
<header>
  <a class="brand" href="/app/">VideoDoc</a>
  <a href="/app/">返回任务台</a>
</header>
<main><article>__BODY__</article></main>
</body>
</html>
"""


def render_sample_page(title: str, body: str) -> str:
    return SAMPLE_PAGE_HTML.replace("__TITLE__", html.escape(title)).replace("__BODY__", body)


def valid_source_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        RUNTIME_ROOT=Path(os.environ.get("VIDEODOC_RUNTIME_DIR", DEFAULT_RUNTIME_ROOT)),
        FRONTEND_DIST=Path(os.environ.get("VIDEODOC_FRONTEND_DIST", DEFAULT_FRONTEND_DIST)),
        START_BACKGROUND_TASKS=True,
        MAX_WORKERS=1,
    )
    if config:
        app.config.update(config)

    runtime_root = Path(app.config["RUNTIME_ROOT"]).expanduser().resolve()
    store = TaskStore(runtime_root / "tasks")
    if app.config["START_BACKGROUND_TASKS"]:
        store.mark_interrupted()
    executor = ThreadPoolExecutor(
        max_workers=int(app.config["MAX_WORKERS"]),
        thread_name_prefix="videodoc-pipeline",
    )
    pipeline_config = PipelineConfig.from_environment()
    app.extensions["task_store"] = store
    app.extensions["task_executor"] = executor
    app.extensions["pipeline_config"] = pipeline_config

    @app.get("/")
    def index():
        return redirect("/app/")

    @app.get("/favicon.ico")
    def favicon():
        frontend_dist = Path(app.config["FRONTEND_DIST"]).expanduser().resolve()
        return send_from_directory(frontend_dist, "favicon.ico")

    @app.get("/app/")
    @app.get("/app/<path:filename>")
    def frontend_app(filename: str = ""):
        frontend_dist = Path(app.config["FRONTEND_DIST"]).expanduser().resolve()
        index_path = frontend_dist / "index.html"
        if not index_path.is_file():
            return "VideoDoc 前端尚未构建，请运行 pnpm --dir frontend build。", 503
        candidate = frontend_dist / filename
        if filename and candidate.is_file() and candidate.is_relative_to(frontend_dist):
            return send_from_directory(frontend_dist, filename)
        return send_from_directory(frontend_dist, "index.html")

    @app.get("/api/tasks")
    def tasks_api():
        return jsonify([store.public(task["id"]) for task in store.list()])

    @app.post("/api/tasks")
    def create_task():
        payload = request.get_json(silent=True) or request.form
        source_url = str(payload.get("url", "")).strip()
        if not valid_source_url(source_url):
            return jsonify({"error": "请输入有效的 http:// 或 https:// 视频链接。"}), 400
        task = store.create(source_url)
        if app.config["START_BACKGROUND_TASKS"]:
            executor.submit(run_pipeline, store, task["id"], pipeline_config)
        return jsonify({"id": task["id"], "url": f"/app/tasks/{task['id']}"}), 202

    @app.get("/tasks/<task_id>")
    def task_detail(task_id: str):
        try:
            store.get(task_id)
        except KeyError:
            abort(404)
        return redirect(f"/app/tasks/{task_id}")

    @app.get("/api/tasks/<task_id>")
    def task_api(task_id: str):
        try:
            task = store.public(task_id, include_logs=True)
        except KeyError:
            abort(404)
        return jsonify(task)

    @app.get("/api/tasks/<task_id>/deletion-preview")
    def task_deletion_preview_api(task_id: str):
        try:
            preview = store.deletion_preview(task_id)
        except KeyError:
            abort(404)
        return jsonify(preview)

    @app.delete("/api/tasks/<task_id>")
    def delete_task_api(task_id: str):
        payload = request.get_json(silent=True) or {}
        confirmation = str(payload.get("confirmation", ""))
        try:
            result = store.move_to_trash(task_id, confirmation)
        except KeyError:
            abort(404)
        except TaskConfirmationError as error:
            return jsonify({"error": str(error)}), 400
        except TaskStateError as error:
            return jsonify({"error": str(error)}), 409
        return jsonify(result)

    @app.post("/api/tasks/<task_id>/resume")
    def resume_task_api(task_id: str):
        try:
            step_key = prepare_resume(store, task_id, pipeline_config)
            store.queue_resume(task_id, step_key)
        except KeyError:
            abort(404)
        except (PipelineError, TaskStateError) as error:
            return jsonify({"error": str(error)}), 409
        if app.config["START_BACKGROUND_TASKS"]:
            executor.submit(
                run_pipeline,
                store,
                task_id,
                pipeline_config,
                step_key,
            )
        return jsonify({"id": task_id, "resume_from": step_key}), 202

    @app.get("/tasks/<task_id>/result")
    def task_result(task_id: str):
        try:
            task = store.get(task_id)
        except KeyError:
            abort(404)
        if task["status"] != "completed":
            return redirect(f"/app/tasks/{task_id}")
        return redirect(f"/app/tasks/{task_id}/result")

    @app.get("/api/tasks/<task_id>/result")
    def task_result_api(task_id: str):
        try:
            task = store.public(task_id)
            task_dir = store.task_dir(task_id)
        except KeyError:
            abort(404)
        result_path = task_dir / "result.json"
        article_path = task_dir / "article.html"
        if task["status"] != "completed" or not result_path.is_file() or not article_path.is_file():
            return jsonify({"error": "任务尚未生成完整结果。"}), 409
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["article_title"] = (
            result.get("article_title")
            or task.get("article_title")
            or result.get("outline", {}).get("title")
            or result.get("metadata", {}).get("title")
        )
        article_html = article_path.read_text(encoding="utf-8")
        result["article_html"] = article_html.replace(
            'src="media/',
            f'src="/tasks/{task_id}/media/',
        )
        return jsonify(result)

    @app.get("/tasks/<task_id>/media/<path:filename>")
    def task_media(task_id: str, filename: str):
        allowed_prefixes = ("video/", "analysis/keyframes/frames/")
        if not filename.startswith(allowed_prefixes):
            abort(404)
        try:
            task_dir = store.task_dir(task_id)
        except KeyError:
            abort(404)
        return send_from_directory(task_dir, filename, conditional=True)

    @app.get("/tasks/<task_id>/download/<path:filename>")
    def task_download(task_id: str, filename: str):
        if filename not in {"article.md", "result.json"}:
            abort(404)
        try:
            task_dir = store.task_dir(task_id)
        except KeyError:
            abort(404)
        return send_from_directory(task_dir, filename, as_attachment=True)

    @app.get("/sample")
    def sample_article():
        if not SAMPLE_ARTICLE.is_file():
            abort(404)
        source = SAMPLE_ARTICLE.read_text(encoding="utf-8")
        body = markdown.markdown(source, extensions=MD_EXTENSIONS)
        return render_sample_page("InkyPi 示例文章", body)

    @app.get("/assets/<path:filename>")
    def assets(filename: str):
        return send_from_directory(ASSETS_DIR, filename)

    return app


def main() -> int:
    """保留 ``python -m videodoc.server`` 入口，统一走 cli。"""
    from .cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
