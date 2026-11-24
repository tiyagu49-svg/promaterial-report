"""Run trace exporter: turn runtime/logs/messages.jsonl into a readable Markdown timeline.

Used by `mas trace <run_id|last>` — handy for the report and the presentation.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .schemas import Message

ICONS = {
    "task_assign": "📌", "task_result": "✅", "question": "❓",
    "approval_request": "⚠️", "system": "⚙️", "chat": "💬",
}


def load_messages(log_path: Path) -> list[Message]:
    if not log_path.exists():
        return []
    out = []
    for line in log_path.read_text().splitlines():
        try:
            out.append(Message.model_validate(json.loads(line)))
        except Exception:
            continue
    return out


def task_ids_for_run(checkpoint_dir: Path, run_id: str) -> set[str]:
    if run_id == "last":
        files = sorted(checkpoint_dir.glob("run_*.json"), key=lambda p: p.stat().st_mtime)
        if not files:
            return set()
        path = files[-1]
    else:
        path = checkpoint_dir / f"{run_id}.json"
    if not path.exists():
        return set()
    return set(json.loads(path.read_text()).keys())


def export_trace(runtime_dir: Path, run_id: str = "last") -> str:
    msgs = load_messages(runtime_dir / "logs" / "messages.jsonl")
    ids = task_ids_for_run(runtime_dir / "checkpoints", run_id)
    if ids:
        first = min((m.ts for m in msgs if m.task_id in ids), default=0)
        last = max((m.ts for m in msgs if m.task_id in ids), default=0)
        # include task-less messages (questions/approvals) that happened during the run
        msgs = [m for m in msgs if m.task_id in ids or (m.task_id is None and first <= m.ts <= last)]
    if not msgs:
        return f"# Trace {run_id}\n\n(no messages found)\n"
    t0 = msgs[0].ts
    lines = [f"# Trace {run_id}", "",
             f"Started {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t0))}, {len(msgs)} messages", "",
             "| t (s) | channel | from | kind | message |", "|---|---|---|---|---|"]
    for m in msgs:
        text = m.content.replace("\n", " ").replace("|", "\\|")
        text = text[:200] + ("…" if len(text) > 200 else "")
        lines.append(f"| {m.ts - t0:.1f} | {m.channel} | {m.sender} | {ICONS.get(m.kind.value, '')} {m.kind.value} | {text} |")
    return "\n".join(lines) + "\n"
