"""Keeps task/sub-task state and checkpoints it to runtime/checkpoints/<run_id>.json (thread-safe)."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from ..core.schemas import Task, TaskStatus


class TaskStore:
    def __init__(self, run_id: str, checkpoint_dir: Path):
        self.run_id = run_id
        self.path = Path(checkpoint_dir) / f"{run_id}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.tasks: dict[str, Task] = {}
        self._lock = threading.RLock()

    def add(self, task: Task) -> Task:
        with self._lock:
            self.tasks[task.id] = task
            self.save()
        return task

    def update(self, task: Task) -> None:
        with self._lock:
            self.tasks[task.id] = task
            self.save()

    def get(self, task_id: str) -> Task:
        return self.tasks[task_id]

    def children(self, parent_id: str) -> list[Task]:
        with self._lock:
            return [t for t in self.tasks.values() if t.parent_id == parent_id]

    def by_status(self, status: TaskStatus) -> list[Task]:
        with self._lock:
            return [t for t in self.tasks.values() if t.status == status]

    def save(self) -> None:
        with self._lock:
            data = {k: v.model_dump(mode="json") for k, v in self.tasks.items()}
            self.path.write_text(json.dumps(data, indent=2))
