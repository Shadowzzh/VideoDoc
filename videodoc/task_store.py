"""基于 JSON 文件的单机任务存储。"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


TASK_ID_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-f0-9]{8}$")
TASK_SCHEMA_VERSION = 3

STEP_DEFINITIONS = (
    ("probe", "解析来源与元数据"),
    ("download", "下载并合并视频"),
    ("audio", "提取转写音频"),
    ("transcribe", "Whisper 带时间戳转写"),
    ("outline", "DeepSeek 生成文章大纲"),
    ("frames", "常规模式提取关键帧"),
    ("select_images", "按章节选择文章配图"),
    ("ocr", "本地 OCR 取证"),
    ("article", "DeepSeek 生成图文正文"),
    ("finalize", "整理交互式文章产物"),
)


class TaskStateError(RuntimeError):
    """任务状态不允许当前操作。"""


class TaskConfirmationError(ValueError):
    """删除确认值与目标任务不一致。"""


def utc_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class TaskStore:
    """将每个任务保存在独立目录中，适合单用户本地运行。"""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.trash_root = self.root.parent / "trash"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def task_dir(self, task_id: str) -> Path:
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise KeyError(task_id)
        return self.root / task_id

    def create(self, url: str) -> dict[str, Any]:
        now = datetime.now().astimezone()
        task_id = f"{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        task = {
            "schema_version": TASK_SCHEMA_VERSION,
            "id": task_id,
            "url": url,
            "status": "queued",
            "created_at": now.isoformat(timespec="seconds"),
            "updated_at": now.isoformat(timespec="seconds"),
            "started_at": None,
            "finished_at": None,
            "error": None,
            "metadata": {},
            "article_title": None,
            "artifacts": {},
            "resume_count": 0,
            "resume_from": None,
            "steps": [
                {
                    "key": key,
                    "label": label,
                    "status": "pending",
                    "started_at": None,
                    "finished_at": None,
                    "command": None,
                    "outputs": [],
                    "error": None,
                    "attempt_count": 0,
                    "attempts": [],
                }
                for key, label in STEP_DEFINITIONS
            ],
        }
        with self._lock:
            task_dir = self.task_dir(task_id)
            (task_dir / "logs").mkdir(parents=True)
            self._write(task)
        return copy.deepcopy(task)

    def get(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            path = self.task_dir(task_id) / "task.json"
            if not path.is_file():
                raise KeyError(task_id)
            task = json.loads(path.read_text(encoding="utf-8"))
            return self._normalize(task)

    def list(self) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        with self._lock:
            for path in self.root.glob("*/task.json"):
                try:
                    task = json.loads(path.read_text(encoding="utf-8"))
                    tasks.append(self._normalize(task))
                except (OSError, ValueError):
                    continue
        tasks.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return tasks

    def update(self, task_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            task = self.get(task_id)
            task.update(changes)
            task["updated_at"] = utc_now()
            self._write(task)
            return copy.deepcopy(task)

    def merge_artifacts(self, task_id: str, artifacts: dict[str, Any]) -> None:
        with self._lock:
            task = self.get(task_id)
            task["artifacts"].update(artifacts)
            task["updated_at"] = utc_now()
            self._write(task)

    def update_step(self, task_id: str, step_key: str, **changes: Any) -> None:
        with self._lock:
            task = self.get(task_id)
            for step in task["steps"]:
                if step["key"] == step_key:
                    step.update(changes)
                    break
            else:
                raise KeyError(step_key)
            task["updated_at"] = utc_now()
            self._write(task)

    def start_attempt(self, task_id: str, step_key: str) -> int:
        with self._lock:
            task = self.get(task_id)
            step = self._find_step(task, step_key)
            attempt_number = int(step.get("attempt_count", 0)) + 1
            started_at = utc_now()
            step["attempt_count"] = attempt_number
            step["status"] = "running"
            step["started_at"] = started_at
            step["finished_at"] = None
            step["error"] = None
            step["attempts"].append(
                {
                    "number": attempt_number,
                    "status": "running",
                    "started_at": started_at,
                    "finished_at": None,
                    "error": None,
                    "log": f"logs/{step_key}/attempt-{attempt_number:03d}.log",
                }
            )
            task["updated_at"] = started_at
            self._write(task)
            return attempt_number

    def finish_attempt(
        self,
        task_id: str,
        step_key: str,
        attempt_number: int,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        with self._lock:
            task = self.get(task_id)
            step = self._find_step(task, step_key)
            finished_at = utc_now()
            for attempt in step["attempts"]:
                if attempt["number"] == attempt_number:
                    attempt["status"] = status
                    attempt["finished_at"] = finished_at
                    attempt["error"] = error
                    break
            else:
                raise KeyError(f"{step_key} attempt {attempt_number}")
            step["status"] = status
            step["finished_at"] = finished_at
            step["error"] = error
            task["updated_at"] = finished_at
            self._write(task)

    def queue_resume(self, task_id: str, step_key: str) -> dict[str, Any]:
        """原子地把暂停任务放回队列，避免重复点击创建多个执行线程。"""
        with self._lock:
            task = self.get(task_id)
            if task.get("status") not in {"failed", "interrupted"}:
                raise TaskStateError("只有失败或中断的任务可以继续。")
            resume_step = self._resume_step(task)
            if resume_step is None:
                raise TaskStateError("任务没有可继续的阶段。")
            if resume_step["key"] != step_key:
                raise TaskStateError(
                    f"任务当前应从 {resume_step['label']} 继续，而不是 {step_key}。"
                )
            now = utc_now()
            task["status"] = "queued"
            task["error"] = None
            task["finished_at"] = None
            task["updated_at"] = now
            task["resume_count"] = int(task.get("resume_count", 0)) + 1
            task["resume_from"] = step_key
            resume_step["status"] = "pending"
            resume_step["finished_at"] = None
            resume_step["error"] = None
            self._write(task)
            return copy.deepcopy(task)

    def deletion_preview(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = self.get(task_id)
            task_dir = self.task_dir(task_id)
            groups = {
                "video": {"label": "视频", "bytes": 0, "files": 0},
                "audio": {"label": "音频", "bytes": 0, "files": 0},
                "frames": {"label": "关键帧", "bytes": 0, "files": 0},
                "other": {"label": "转写、文章与日志", "bytes": 0, "files": 0},
            }
            total_bytes = 0
            total_files = 0
            for directory, _subdirectories, filenames in os.walk(task_dir):
                for filename in filenames:
                    path = Path(directory) / filename
                    try:
                        size = path.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
                    relative = path.relative_to(task_dir).as_posix()
                    group_key = self._deletion_group(relative)
                    groups[group_key]["bytes"] += size
                    groups[group_key]["files"] += 1
                    total_bytes += size
                    total_files += 1
            title = self._article_title(task_id, task)
            if not title:
                title = task.get("metadata", {}).get("title") or task.get("url") or task_id
            return {
                "id": task_id,
                "title": title,
                "status": task.get("status"),
                "deletable": task.get("status") not in {"queued", "running"},
                "total_bytes": total_bytes,
                "total_files": total_files,
                "groups": groups,
            }

    def move_to_trash(self, task_id: str, confirmation: str) -> dict[str, Any]:
        """将任务目录原子移动到回收站，保留人工恢复能力。"""
        with self._lock:
            if confirmation != task_id:
                raise TaskConfirmationError("删除确认值与任务 ID 不一致。")
            task = self.get(task_id)
            if task.get("status") in {"queued", "running"}:
                raise TaskStateError("排队中或运行中的任务不能删除，请等待结束。")
            source = self.task_dir(task_id)
            self.trash_root.mkdir(parents=True, exist_ok=True)
            now = datetime.now().astimezone()
            trash_name = f"{task_id}-{now:%Y%m%d-%H%M%S}"
            destination = self.trash_root / trash_name
            if destination.exists():
                raise TaskStateError("回收站中已存在同名任务，请稍后重试。")
            source.replace(destination)
            return {
                "id": task_id,
                "deleted_at": now.isoformat(timespec="seconds"),
                "recoverable": True,
            }

    def append_log(
        self,
        task_id: str,
        step_key: str,
        text: str,
        attempt_number: int | None = None,
    ) -> Path:
        path = self.task_dir(task_id) / "logs" / f"{step_key}.log"
        with self._lock:
            self._append_text(path, text)
            if attempt_number is None:
                task = self.get(task_id)
                step = self._find_step(task, step_key)
                if step["attempts"] and step["attempts"][-1]["status"] == "running":
                    attempt_number = int(step["attempts"][-1]["number"])
            if attempt_number is not None:
                attempt_path = (
                    self.task_dir(task_id)
                    / "logs"
                    / step_key
                    / f"attempt-{attempt_number:03d}.log"
                )
                attempt_path.parent.mkdir(parents=True, exist_ok=True)
                self._append_text(attempt_path, text)
        return path

    def log_tail(self, task_id: str, step_key: str, max_lines: int = 120) -> str:
        path = self.task_dir(task_id) / "logs" / f"{step_key}.log"
        if not path.is_file():
            return ""
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-max_lines:])

    def public(self, task_id: str, include_logs: bool = False) -> dict[str, Any]:
        task = self.get(task_id)
        task["article_title"] = self._article_title(task_id, task)
        completed = sum(step["status"] in {"completed", "skipped"} for step in task["steps"])
        task["progress"] = {
            "completed": completed,
            "total": len(task["steps"]),
            "percent": round(completed / len(task["steps"]) * 100),
        }
        if include_logs:
            for step in task["steps"]:
                step["log_tail"] = self.log_tail(task_id, step["key"])
        resume_step = self._resume_step(task)
        task["can_resume"] = (
            task.get("status") in {"failed", "interrupted"} and resume_step is not None
        )
        if task["can_resume"]:
            task["resume_from"] = {
                "key": resume_step["key"],
                "label": resume_step["label"],
            }
        else:
            task["resume_from"] = None
        return task

    def mark_interrupted(self) -> None:
        """服务重启后，将失去执行线程的任务标记为可恢复的中断状态。"""
        for task in self.list():
            if task.get("status") not in {"queued", "running"}:
                continue
            now = utc_now()
            task["status"] = "interrupted"
            task["error"] = "服务在任务执行期间重启，可从中断阶段继续。"
            task["finished_at"] = now
            task["updated_at"] = now
            for step in task["steps"]:
                if step["status"] == "running":
                    step["status"] = "interrupted"
                    step["finished_at"] = now
                    step["error"] = "服务重启导致任务中断。"
                    if step["attempts"] and step["attempts"][-1]["status"] == "running":
                        step["attempts"][-1]["status"] = "interrupted"
                        step["attempts"][-1]["finished_at"] = now
                        step["attempts"][-1]["error"] = step["error"]
            self._write(task)

    def _normalize(self, task: dict[str, Any]) -> dict[str, Any]:
        normalized = copy.deepcopy(task)
        normalized.setdefault("schema_version", 1)
        normalized.setdefault("resume_count", 0)
        normalized.setdefault("resume_from", None)
        normalized.setdefault("article_title", None)
        for step in normalized.get("steps", []):
            attempts = step.get("attempts")
            if not isinstance(attempts, list):
                attempts = []
            if not attempts and step.get("started_at"):
                attempts = [
                    {
                        "number": 1,
                        "status": step.get("status", "failed"),
                        "started_at": step.get("started_at"),
                        "finished_at": step.get("finished_at"),
                        "error": step.get("error"),
                        "log": f"logs/{step['key']}.log",
                    }
                ]
            step["attempts"] = attempts
            step["attempt_count"] = max(
                int(step.get("attempt_count", 0)),
                len(attempts),
            )
        return normalized

    def _article_title(self, task_id: str, task: dict[str, Any]) -> str | None:
        saved_title = str(task.get("article_title") or "").strip()
        if saved_title:
            return saved_title
        relative = str(task.get("artifacts", {}).get("article_json") or "article.json")
        path = (self.task_dir(task_id) / relative).resolve()
        if not path.is_relative_to(self.task_dir(task_id)) or not path.is_file():
            return None
        try:
            article = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        title = str(article.get("title") or "").strip()
        return title or None

    @staticmethod
    def _find_step(task: dict[str, Any], step_key: str) -> dict[str, Any]:
        for step in task["steps"]:
            if step["key"] == step_key:
                return step
        raise KeyError(step_key)

    @staticmethod
    def _resume_step(task: dict[str, Any]) -> dict[str, Any] | None:
        for step in task.get("steps", []):
            if step.get("status") not in {"completed", "skipped"}:
                return step
        return None

    @staticmethod
    def _deletion_group(relative: str) -> str:
        if relative.startswith("video/"):
            return "video"
        if relative.startswith("audio/"):
            return "audio"
        if relative.startswith("analysis/keyframes/frames/"):
            return "frames"
        return "other"

    @staticmethod
    def _append_text(path: Path, text: str) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            if text and not text.endswith("\n"):
                handle.write("\n")

    def _write(self, task: dict[str, Any]) -> None:
        task["schema_version"] = TASK_SCHEMA_VERSION
        task_dir = self.task_dir(task["id"])
        task_dir.mkdir(parents=True, exist_ok=True)
        path = task_dir / "task.json"
        temp = task_dir / ".task.json.tmp"
        temp.write_text(
            json.dumps(task, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)
