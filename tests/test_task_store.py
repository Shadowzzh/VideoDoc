import json

import pytest

from videodoc.task_store import (
    TaskConfirmationError,
    TaskStateError,
    TaskStore,
    utc_now,
)


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
    # 步骤数由「核心步骤 + 已注册能力步骤」决定，测试里的 store 未注入能力步骤（9 步）。
    assert public["progress"]["percent"] == round(1 / len(public["steps"]) * 100)


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
    with pytest.raises(TaskStateError, match="只有失败、中断或已取消"):
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


def test_move_to_trash_requires_confirmation_and_blocks_only_running(tmp_path):
    store = TaskStore(tmp_path / "tasks")

    queued = store.create("https://example.com/video")
    with pytest.raises(TaskConfirmationError, match="任务 ID"):
        store.move_to_trash(queued["id"], "wrong-id")
    # 等待中的任务可以删：它只是已提交线程池、还没轮到执行，目录里没有任何产物。
    deleted = store.move_to_trash(queued["id"], queued["id"])
    assert deleted["recoverable"] is True
    assert not store.task_dir(queued["id"]).is_dir()

    running = store.create("https://example.com/video")
    store.update(running["id"], status="running")
    with pytest.raises(TaskStateError, match="不能删除"):
        store.move_to_trash(running["id"], running["id"])
    assert store.task_dir(running["id"]).is_dir()


def test_deletion_preview_says_queued_is_deletable(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    queued = store.create("https://example.com/video")
    running = store.create("https://example.com/video")
    store.update(running["id"], status="running")

    assert store.deletion_preview(queued["id"])["deletable"] is True
    assert store.deletion_preview(running["id"])["deletable"] is False


def test_record_metric_writes_jsonl_and_aggregates_into_step(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    task_id = task["id"]

    store.record_metric(
        task_id,
        "probe",
        {
            "kind": "command",
            "program": "ffmpeg",
            "arguments": 3,
            "started_at": "2026-10-04T12:00:00+08:00",
            "duration_ms": 1200,
            "exit_code": 0,
        },
    )
    store.record_derived(task_id, "probe", bytes=1024, megabytes_per_second=1.5)
    store.append_metric(
        task_id,
        {"kind": "heartbeat", "step": "probe", "pid": 42, "elapsed_ms": 15000},
    )

    events = store.read_metrics(task_id)
    assert [event["kind"] for event in events] == ["command", "derived", "heartbeat"]
    assert events[0]["step"] == "probe"

    step = store.public(task_id, include_logs=True)["steps"][0]
    assert step["metrics"]["command"][0]["program"] == "ffmpeg"
    assert step["metrics"]["derived"] == {"bytes": 1024, "megabytes_per_second": 1.5}
    assert step["heartbeat"]["elapsed_ms"] == 15000


def test_step_duration_is_derived_from_timestamps(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    store.start_attempt(task["id"], "probe")
    store.finish_attempt(task["id"], "probe", 1, status="completed")

    step = store.public(task["id"])["steps"][0]
    assert step["duration_ms"] is not None
    assert step["duration_ms"] >= 0

    pending = store.public(task["id"])["steps"][1]
    assert pending["duration_ms"] is None


def test_record_metric_survives_missing_step_slot(tmp_path):
    """能力下线后步骤位不存在：只留明细，不能把任务搞挂。"""
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")

    store.record_metric(task["id"], "removed-capability", {"kind": "command", "duration_ms": 1})
    store.record_derived(task["id"], "removed-capability", seconds=1)

    assert len(store.read_metrics(task["id"])) == 2


def test_metrics_file_counts_toward_deletion_preview(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    store.append_metric(task["id"], {"kind": "heartbeat", "step": "probe", "elapsed_ms": 1})

    preview = store.deletion_preview(task["id"])

    assert preview["groups"]["other"]["files"] >= 1


def test_request_cancel_settles_queued_task_immediately(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")

    requested = store.request_cancel(task["id"])

    # 等待中的任务没有在跑的进程，也没有半成品需要流水线收尾：直接落 cancelled。
    assert requested["status"] == "cancelled"
    assert requested["cancel_requested_at"]
    assert store.get(task["id"])["finished_at"] is not None
    # 取消不是失败：不能把任务变成「可删除但不可恢复」的死胡同。
    assert store.public(task["id"])["can_resume"] is True


def test_request_cancel_only_flags_running_task(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    store.update(task["id"], status="running")
    store.start_attempt(task["id"], "probe")

    requested = store.request_cancel(task["id"])

    # 状态由流水线在自己的检查点收敛成 cancelled，避免与流水线写盘竞争。
    assert requested["status"] == "running"
    assert requested["cancel_requested_at"]
    assert store.running_step_key(task["id"]) == "probe"


def test_request_cancel_rejects_finished_task(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    store.update(task["id"], status="completed")

    with pytest.raises(TaskStateError, match="等待中或运行中"):
        store.request_cancel(task["id"])

    # 已完成的任务不能被取消改写成别的状态。
    assert store.get(task["id"])["status"] == "completed"


def test_cancelled_task_can_resume_and_clears_cancel_flag(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    store.update(task["id"], status="running")
    store.start_attempt(task["id"], "probe")
    store.update(
        task["id"],
        status="cancelled",
        finished_at=utc_now(),
        cancel_requested_at=utc_now(),
    )

    resumed = store.queue_resume(task["id"], "probe")

    assert resumed["status"] == "queued"
    assert resumed["resume_from"] == "probe"
    # 不清掉取消标记的话，重新排队的任务会被新线程立刻当成「已取消」而直接退出。
    assert resumed["cancel_requested_at"] is None


def test_mark_interrupted_clears_stale_cancel_flag(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    store.update(task["id"], status="running", cancel_requested_at=utc_now())

    store.mark_interrupted()

    interrupted = store.get(task["id"])
    assert interrupted["status"] == "interrupted"
    # 服务重启后进程全没了，原来的取消请求已经没有意义。
    assert interrupted["cancel_requested_at"] is None


def test_legacy_task_without_cancel_field_normalizes_to_none(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    task = store.create("https://example.com/video")
    path = store.task_dir(task["id"]) / "task.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("cancel_requested_at", None)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert store.get(task["id"])["cancel_requested_at"] is None
