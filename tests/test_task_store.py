import pytest

from videodoc.task_store import TaskConfirmationError, TaskStateError, TaskStore


def test_task_store_persists_steps_and_logs(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")

    store.update(task["id"], status="running")
    store.update_step(task["id"], "probe", status="completed", outputs=["metadata.json"])
    store.append_log(task["id"], "probe", "metadata ready")

    public = store.public(task["id"], include_logs=True)
    assert public["status"] == "running"
    assert public["steps"][0]["outputs"] == ["metadata.json"]
    assert public["steps"][0]["log_tail"] == "metadata ready"
    assert public["progress"]["percent"] == 10


def test_public_task_uses_existing_article_title_for_legacy_task(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    task_dir = store.task_dir(task["id"])
    (task_dir / "article.json").write_text(
        '{"title":"AI 中文文章标题"}',
        encoding="utf-8",
    )
    store.update(
        task["id"],
        status="completed",
        metadata={"title": "Original English Video Title"},
    )

    public = store.public(task["id"])

    assert public["article_title"] == "AI 中文文章标题"


def test_mark_interrupted_preserves_resumable_task(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    store.update(task["id"], status="running")
    attempt = store.start_attempt(task["id"], "download")

    store.mark_interrupted()

    interrupted = store.get(task["id"])
    assert interrupted["status"] == "interrupted"
    assert "服务" in interrupted["error"]
    download = interrupted["steps"][1]
    assert download["status"] == "interrupted"
    assert download["attempts"][-1]["number"] == attempt
    assert download["attempts"][-1]["status"] == "interrupted"


def test_task_store_records_each_attempt_and_separate_log(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")

    first = store.start_attempt(task["id"], "probe")
    store.append_log(task["id"], "probe", "first failure")
    store.finish_attempt(task["id"], "probe", first, status="failed", error="network")
    second = store.start_attempt(task["id"], "probe")
    store.append_log(task["id"], "probe", "second success")
    store.finish_attempt(task["id"], "probe", second, status="completed")

    saved = store.get(task["id"])
    probe = saved["steps"][0]
    assert probe["attempt_count"] == 2
    assert [item["status"] for item in probe["attempts"]] == ["failed", "completed"]
    first_log = store.task_dir(task["id"]) / "logs" / "probe" / "attempt-001.log"
    second_log = store.task_dir(task["id"]) / "logs" / "probe" / "attempt-002.log"
    assert first_log.read_text(encoding="utf-8").strip() == "first failure"
    assert second_log.read_text(encoding="utf-8").strip() == "second success"


def test_queue_resume_is_atomic_and_only_accepts_paused_task(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    store.update(task["id"], status="failed", error="network")
    store.update_step(task["id"], "probe", status="failed", error="network")

    resumed = store.queue_resume(task["id"], "probe")

    assert resumed["status"] == "queued"
    assert resumed["steps"][0]["status"] == "pending"
    assert resumed["resume_count"] == 1
    with pytest.raises(TaskStateError, match="只有失败或中断"):
        store.queue_resume(task["id"], "probe")


def test_deletion_preview_groups_files_and_move_to_trash(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    task_dir = store.task_dir(task["id"])
    files = {
        "video/source.mp4": b"video-data",
        "audio/transcript.wav": b"audio",
        "analysis/keyframes/frames/frame.jpg": b"frame-data",
        "article.md": b"article",
    }
    for relative, content in files.items():
        path = task_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    store.update(task["id"], status="completed", metadata={"title": "测试任务"})

    preview = store.deletion_preview(task["id"])
    deleted = store.move_to_trash(task["id"], task["id"])

    assert preview["title"] == "测试任务"
    assert preview["deletable"] is True
    assert preview["groups"]["video"]["files"] == 1
    assert preview["groups"]["audio"]["files"] == 1
    assert preview["groups"]["frames"]["files"] == 1
    assert preview["total_bytes"] >= sum(len(content) for content in files.values())
    assert deleted["recoverable"] is True
    assert not task_dir.exists()
    trashed = list(store.trash_root.glob(f"{task['id']}-*"))
    assert len(trashed) == 1
    assert (trashed[0] / "article.md").is_file()


def test_move_to_trash_requires_confirmation_and_idle_task(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")

    with pytest.raises(TaskConfirmationError, match="任务 ID"):
        store.move_to_trash(task["id"], "wrong-id")
    with pytest.raises(TaskStateError, match="不能删除"):
        store.move_to_trash(task["id"], task["id"])

    assert store.task_dir(task["id"]).is_dir()
