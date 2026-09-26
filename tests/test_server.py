import json

import pytest

from videodoc.integrations import vision_local, vision_remote
from videodoc.server import create_app


@pytest.fixture()
def app(tmp_path):
    frontend_dist = tmp_path / "frontend-dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<div id='root'>VideoDoc React</div>", encoding="utf-8")
    (frontend_dist / "favicon.ico").write_bytes(b"favicon")
    application = create_app(
        {
            "TESTING": True,
            "RUNTIME_ROOT": tmp_path,
            "FRONTEND_DIST": frontend_dist,
            "START_BACKGROUND_TASKS": False,
        }
    )
    yield application
    application.extensions["task_executor"].shutdown(wait=True)


@pytest.fixture()
def client(app):
    return app.test_client()


def test_index_redirects_to_react_app(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == "/app/"


def test_react_app_supports_spa_fallback(client):
    response = client.get("/app/tasks/example/result")

    assert response.status_code == 200
    assert "VideoDoc React" in response.text


def test_root_favicon_uses_frontend_asset(client):
    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.data == b"favicon"


def test_legacy_interface_is_removed(client):
    # 旧 Jinja 界面已删除，React 应用是唯一入口。
    assert client.get("/legacy").status_code == 404
    assert client.get("/legacy/tasks/whatever").status_code == 404


def test_sample_page_renders_article(client):
    response = client.get("/sample")

    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]
    # 自包含页面：必须能直接引用示例文章的图片
    assert "<article>" in response.text


def test_create_task_validates_url(client):
    response = client.post("/api/tasks", json={"url": "not-a-url"})

    assert response.status_code == 400


def test_create_task_returns_detail_url(client):
    response = client.post("/api/tasks", json={"url": "https://example.com/video"})

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["url"].startswith("/app/tasks/")


def test_task_list_api_returns_created_task(client):
    created = client.post("/api/tasks", json={"url": "https://example.com/video"}).get_json()

    response = client.get("/api/tasks")

    assert response.status_code == 200
    tasks = response.get_json()
    assert tasks[0]["id"] == created["id"]


def test_failed_task_can_resume_once(app, client):
    store = app.extensions["task_store"]
    task = store.create("https://example.com/video")
    store.update(task["id"], status="failed", error="network")
    store.update_step(task["id"], "probe", status="failed", error="network")

    first = client.post(f"/api/tasks/{task['id']}/resume")
    second = client.post(f"/api/tasks/{task['id']}/resume")

    assert first.status_code == 202
    assert first.get_json()["resume_from"] == "probe"
    assert second.status_code == 409
    assert store.get(task["id"])["status"] == "queued"


def test_resume_rejects_missing_upstream_artifact(app, client):
    store = app.extensions["task_store"]
    task = store.create("https://example.com/video")
    store.update(task["id"], status="failed", error="download failed")
    store.update_step(task["id"], "probe", status="completed")
    store.update_step(task["id"], "download", status="failed")

    response = client.post(f"/api/tasks/{task['id']}/resume")

    assert response.status_code == 409
    assert "视频元数据" in response.get_json()["error"]
    assert store.get(task["id"])["status"] == "failed"


def test_completed_task_can_be_previewed_and_moved_to_trash(app, client):
    store = app.extensions["task_store"]
    task = store.create("https://example.com/video")
    task_dir = store.task_dir(task["id"])
    (task_dir / "video").mkdir()
    (task_dir / "video" / "source.mp4").write_bytes(b"video")
    store.update(task["id"], status="completed", metadata={"title": "待删除任务"})

    preview = client.get(f"/api/tasks/{task['id']}/deletion-preview")
    rejected = client.delete(
        f"/api/tasks/{task['id']}",
        json={"confirmation": "wrong-id"},
    )
    deleted = client.delete(
        f"/api/tasks/{task['id']}",
        json={"confirmation": task["id"]},
    )

    assert preview.status_code == 200
    assert preview.get_json()["groups"]["video"]["files"] == 1
    assert rejected.status_code == 400
    assert deleted.status_code == 200
    assert deleted.get_json()["recoverable"] is True
    assert client.get(f"/api/tasks/{task['id']}").status_code == 404


def test_running_task_cannot_be_deleted(app, client):
    store = app.extensions["task_store"]
    task = store.create("https://example.com/video")
    store.update(task["id"], status="running")

    response = client.delete(
        f"/api/tasks/{task['id']}",
        json={"confirmation": task["id"]},
    )

    assert response.status_code == 409
    assert store.task_dir(task["id"]).is_dir()


def test_completed_result_renders_player_and_article(app, client):
    store = app.extensions["task_store"]
    task = store.create("https://example.com/video")
    task_dir = store.task_dir(task["id"])
    (task_dir / "video").mkdir()
    (task_dir / "video" / "source.mp4").write_bytes(b"video")
    (task_dir / "article.html").write_text(
        '<h1>测试文章</h1><img src="media/analysis/keyframes/frames/frame.jpg">',
        encoding="utf-8",
    )
    (task_dir / "article.json").write_text(
        json.dumps({"title": "AI 中文文章标题"}, ensure_ascii=False),
        encoding="utf-8",
    )
    result = {
        "metadata": {"title": "测试文章", "uploader": "作者", "extractor": "test"},
        "video": "video/source.mp4",
        "segments": [{"start_sec": 0, "end_sec": 2, "text": "开场"}],
        "outline": {
            "summary": "摘要",
            "sections": [
                {
                    "title": "开场",
                    "summary": "摘要",
                    "start_sec": 0,
                    "end_sec": 2,
                    "start_time": "00:00",
                    "end_time": "00:02",
                }
            ],
        },
    }
    (task_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    store.update(task["id"], status="completed")

    response = client.get(f"/api/tasks/{task['id']}/result")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["article_title"] == "AI 中文文章标题"
    assert payload["video"] == "video/source.mp4"
    assert "测试文章" in payload["article_html"]
    assert f'/tasks/{task["id"]}/media/analysis/' in payload["article_html"]


def test_media_route_does_not_expose_private_task_files(app, client):
    store = app.extensions["task_store"]
    task = store.create("https://example.com/video")
    task_dir = store.task_dir(task["id"])
    (task_dir / "private").mkdir()
    (task_dir / "private" / "source.info.json").write_text("{}", encoding="utf-8")

    response = client.get(f"/tasks/{task['id']}/media/private/source.info.json")

    assert response.status_code == 404


def test_download_route_only_allows_delivery_artifacts(app, client):
    store = app.extensions["task_store"]
    task = store.create("https://example.com/video")

    response = client.get(f"/tasks/{task['id']}/download/task.json")

    assert response.status_code == 404


def test_settings_api_returns_effective_settings_without_secrets(app, client, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODOC_SETTINGS_FILE", str(tmp_path / "settings.json"))

    response = client.get("/api/settings")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["vision"]["engine"] in payload["engines"]
    assert "api_key" not in payload["vision"]["external"]
    assert payload["protocols"][0] == "openai-chat"
    assert payload["settings_path"].endswith("settings.json")


def test_settings_api_saves_plaintext_key_but_never_echoes_it(app, client, tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    monkeypatch.setenv("VIDEODOC_SETTINGS_FILE", str(settings_file))
    monkeypatch.delenv("VIDEODOC_VISION_API_KEY", raising=False)

    response = client.put(
        "/api/settings",
        json={
            "capabilities": {
                "image_vision": {
                    "engine": "external",
                    "external.protocol": "openai-responses",
                    "external.base_url": "http://192.168.8.211:3006/v1",
                    "external.model": "gemini-3.5-flash-lite",
                    "external.api_key": "plain-secret-abcd",
                }
            }
        },
    )

    assert response.status_code == 200
    external = response.get_json()["vision"]["external"]
    assert external["api_key_configured"] is True
    assert external["api_key_hint"] == "****abcd"
    assert "plain-secret-abcd" not in json.dumps(response.get_json())
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["capabilities"]["image_vision"]["external.api_key"] == "plain-secret-abcd"
    assert client.get("/api/settings").get_json()["vision"]["engine"] == "external"


def test_settings_api_rejects_invalid_payload(app, client, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODOC_SETTINGS_FILE", str(tmp_path / "settings.json"))

    response = client.put("/api/settings", json={"vision": {"engine": "cloud"}})

    assert response.status_code == 400
    assert "通道 只能是" in response.get_json()["error"]


def test_settings_test_endpoint_probes_the_draft_payload(app, client, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODOC_SETTINGS_FILE", str(tmp_path / "settings.json"))
    seen = {}

    def fake_probe(config):
        seen["protocol"] = config.protocol
        seen["base_url"] = config.base_url
        return {"ok": True, "endpoint": "http://h/v1/models", "detail": "可达"}

    monkeypatch.setattr(vision_remote, "probe", fake_probe)

    response = client.post(
        "/api/settings/test",
        json={
            "vision": {
                "engine": "external",
                "external": {
                    "protocol": "openai-chat",
                    "base_url": "http://h/v1",
                    "model": "m",
                    "api_key": "k-1234",
                },
            }
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["external"]["ok"] is True
    assert seen == {"protocol": "openai-chat", "base_url": "http://h/v1"}


def test_settings_test_endpoint_reports_missing_channel(app, client, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODOC_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setattr(vision_local.shutil, "which", lambda name: None)

    response = client.post("/api/settings/test", json={"vision": {"engine": "local"}})

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
