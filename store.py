"""Per-agent memory store (one store per agent, kept in that agent's own folder).

Interface used by the agent runtime:
    store.add(MemoryRecord)              -> None   (dedupes near-identical lessons)
    store.all()                          -> list[MemoryRecord]
    store.mark_used(ids, success)        -> None   (evolution signal: was the lesson in context when we succeeded?)
    store.consolidate()                  -> Path   (writes playbook.md: the agent's best lessons)

File: runtime/agents/<id>/memory.jsonl (+ playbook.md). Small, so we rewrite it on updates.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

CONSOLIDATE_EVERY = 10


class MemoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    agent_id: str
    task_goal: str
    success: bool
    summary: str                 # what happened
    lesson: str                  # reusable insight for next time ("do X", "avoid Y")
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    ts: float = Field(default_factory=time.time)
    uses: int = 0                # times injected into a prompt
    helped: int = 0              # times the task succeeded while this lesson was in context
    seen: int = 1                # times the same lesson was learned again (dedupe counter)

    @property
    def usefulness(self) -> float:
        """Laplace-smoothed success rate when this lesson was used (0..1, prior 0.5)."""
        return (self.helped + 1) / (self.uses + 2)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


class JsonMemoryStore:
    def __init__(self, agent_id: str, path: Path, consolidate_every: int = CONSOLIDATE_EVERY):
        self.agent_id = agent_id
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.consolidate_every = consolidate_every
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ io
    def all(self) -> list[MemoryRecord]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            if line.strip():
                try:
                    out.append(MemoryRecord.model_validate(json.loads(line)))
                except Exception:
                    continue
        return out

    def _write(self, records: list[MemoryRecord]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(r.model_dump_json() + "\n" for r in records))
        tmp.replace(self.path)

    # ------------------------------------------------------------------ api
    def add(self, record: MemoryRecord) -> None:
        if not record.lesson or record.lesson.startswith("(reflection failed"):
            return  # nothing reusable
        with self._lock:
            records = self.all()
            for r in records:  # dedupe: same lesson learned again -> strengthen the existing one
                if r.success == record.success and similarity(r.lesson, record.lesson) >= 0.75:
                    r.seen += 1
                    r.ts = record.ts
                    r.tags = sorted(set(r.tags) | set(record.tags))[:8]
                    self._write(records)
                    return
            records.append(record)
            self._write(records)
            if self.consolidate_every and len(records) % self.consolidate_every == 0:
                self.consolidate(records)

    def mark_used(self, ids: list[str], success: bool) -> None:
        if not ids:
            return
        with self._lock:
            records = self.all()
            wanted = set(ids)
            for r in records:
                if r.id in wanted:
                    r.uses += 1
                    r.helped += int(bool(success))
            self._write(records)

    def consolidate(self, records: list[MemoryRecord] | None = None, top: int = 12) -> Path:
        """Write playbook.md: the agent's most useful lessons, grouped into do's and don'ts."""
        records = records if records is not None else self.all()
        ranked = sorted(records, key=lambda r: (r.usefulness * (1 + 0.2 * (r.seen - 1)), r.ts), reverse=True)
        do = [r for r in ranked if r.success][:top]
        dont = [r for r in ranked if not r.success][: max(3, top // 2)]
        lines = [f"# Playbook — {self.agent_id}", "",
                 f"_{len(records)} lessons learned; regenerated {time.strftime('%Y-%m-%d %H:%M')}_", "",
                 "## What works"]
        lines += [f"- {r.lesson} _(used {r.uses}×, helped {r.helped}×, seen {r.seen}×)_" for r in do] or ["- (none yet)"]
        lines += ["", "## Pitfalls to avoid"]
        lines += [f"- {r.lesson} _(from: {r.task_goal[:60]})_" for r in dont] or ["- (none yet)"]
        out = self.path.parent / "playbook.md"
        out.write_text("\n".join(lines) + "\n")
        return out

    def stats(self) -> dict[str, Any]:
        records = self.all()
        return {
            "lessons": len(records),
            "from_success": sum(r.success for r in records),
            "from_failure": sum(not r.success for r in records),
            "total_uses": sum(r.uses for r in records),
            "avg_usefulness": round(sum(r.usefulness for r in records) / len(records), 3) if records else None,
        }

    def __len__(self) -> int:
        return len(self.all())
