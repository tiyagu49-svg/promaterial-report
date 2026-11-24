"""Runs an evaluation task set (JSONL) against the platform and records the metrics.

Task file format, one JSON object per line:
  {"id": "code_fib", "category": "code", "goal": "...", "checks": [{"type": "file_exists", "path": "fib.py"}],
   "answers": {"colour": "blue"}}      # optional: canned replies when agents ask the human

Usage:  mas eval evaluation/dev_tasks/dev.jsonl [--limit 3] [--only id1,id2] [--no-memory]
Output: evaluation/results/<timestamp>/{results.json, report.md}

- Agent memory persists across tasks in a suite (that's the evolution we want to measure);
  workspaces are wiped between tasks so one task can't pass another's checks.
- Every exception is caught: a crash counts as a failed task, the suite continues.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from ..app import build_platform
from ..settings import PROJECT_ROOT, load_settings
from .checks import CheckContext, run_check
from .metrics import compute_metrics, report_markdown


def load_tasks(path: str | Path) -> list[dict[str, Any]]:
    tasks = []
    for i, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        t = json.loads(line)
        t.setdefault("id", f"task{i}")
        t.setdefault("checks", [{"type": "success"}])
        tasks.append(t)
    return tasks


def _memory_stats(platform) -> dict[str, Any]:
    out = {}
    for a in platform.registry.all():
        try:
            out[a.id] = a.memory.stats()
        except Exception:
            out[a.id] = {"lessons": len(a.memory.all())}
    return out


def _wipe_workspaces(platform) -> None:
    for a in platform.registry.all():
        shutil.rmtree(a.workspace, ignore_errors=True)
        a.workspace.mkdir(parents=True, exist_ok=True)


def run_task(platform, task: dict[str, Any]) -> dict[str, Any]:
    human = platform.human
    human.answers = task.get("answers", {}) or {}
    q0, a0 = len(getattr(human, "questions_asked", [])), len(getattr(human, "approvals_requested", []))
    u0 = platform.llm.usage.as_dict()
    t0 = time.time()
    report, crashed, error = None, False, None
    try:
        mode = task.get("mode", "team")
        if mode.startswith("@"):  # direct single-agent task, e.g. "mode": "@coder"
            report = platform.handle_group_message(f"{mode} {task['goal']}")
            report = _outcome_as_report(report, task["goal"], time.time() - t0)
        else:
            report = platform.controller.run_goal(task["goal"])
        error = report.error
    except Exception as e:
        crashed, error = True, f"{type(e).__name__}: {e}"
    duration = time.time() - t0
    ctx = CheckContext(platform, report, questions=human.questions_asked[q0:] if hasattr(human, "questions_asked") else [],
                       approvals=human.approvals_requested[a0:] if hasattr(human, "approvals_requested") else [])
    checks = []
    for c in task["checks"]:
        ok, detail = run_check(c, ctx) if not crashed else (False, "run crashed")
        checks.append({"type": c.get("type"), "passed": ok, "detail": detail})
    u1 = platform.llm.usage.as_dict()
    return {
        "id": task["id"], "category": task.get("category", "general"), "goal": task["goal"],
        "passed": (not crashed) and all(c["passed"] for c in checks), "crashed": crashed, "error": error,
        "duration_s": round(duration, 2), "checks": checks,
        "subtasks_total": getattr(report, "subtasks_total", 0), "subtasks_succeeded": getattr(report, "subtasks_succeeded", 0),
        "retries": getattr(report, "retries", 0), "replanned": getattr(report, "replanned", False),
        "llm_calls": u1["llm_calls"] - u0["llm_calls"],
        "tokens": (u1["prompt_tokens"] + u1["completion_tokens"]) - (u0["prompt_tokens"] + u0["completion_tokens"]),
        "answer": (getattr(report, "final_answer", "") or "")[:2000],
        "run_id": getattr(report, "run_id", None),
    }


def _outcome_as_report(out, goal: str, duration: float):
    """Wrap a single-agent AgentOutcome so it looks like a RunReport for the checks/metrics."""
    from ..orchestration.controller import RunReport
    if isinstance(out, RunReport):
        return out
    return RunReport(run_id=f"direct_{out.task_id}", goal=goal, success=out.success, final_answer=out.answer or "",
                     subtasks_total=1, subtasks_succeeded=int(out.success), duration_s=duration, error=out.error)


def run_suite(tasks_file: str | Path, limit: int | None = None, memory: bool = True, only: str | None = None,
              verbose: bool = True, out_dir: str | Path | None = None, settings=None, llm=None) -> dict[str, Any]:
    tasks = load_tasks(tasks_file)
    if only:
        wanted = {x.strip() for x in only.split(",")}
        tasks = [t for t in tasks if t["id"] in wanted]
    if limit:
        tasks = tasks[:limit]

    settings = settings or load_settings()
    settings.memory.enabled = memory
    # separate runtime so eval runs don't mix with interactive use (and memory on/off don't mix)
    settings.runtime.root_dir = str(Path(settings.runtime.root_dir) / ("eval" if memory else "eval_nomem"))
    platform = build_platform(settings=settings, llm=llm, human_mode="auto_approve")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(out_dir) if out_dir else PROJECT_ROOT / "evaluation" / "results" / f"{stamp}{'' if memory else '_nomem'}"
    out.mkdir(parents=True, exist_ok=True)

    mem_before = _memory_stats(platform)
    results = []
    for i, task in enumerate(tasks, 1):
        _wipe_workspaces(platform)
        if verbose:
            print(f"[eval] ({i}/{len(tasks)}) {task['id']}: {task['goal'][:80]}")
        r = run_task(platform, task)
        results.append(r)
        if verbose:
            print(f"[eval]   -> {'PASS' if r['passed'] else 'FAIL'} in {r['duration_s']}s "
                  f"({r['llm_calls']} calls, {r['tokens']} tokens)")
        (out / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))  # save progress
    for a in platform.registry.all():  # refresh playbooks for the report
        try:
            a.memory.consolidate()
        except Exception:
            pass
    mem_after = _memory_stats(platform)

    metrics = compute_metrics(results)
    config = {"tasks_file": Path(tasks_file).name, "memory": memory, "model": settings.llm.model,
              "parallel": settings.orchestration.parallel, "negotiate": settings.orchestration.negotiate}
    (out / "results.json").write_text(json.dumps(
        {"config": config, "metrics": metrics, "memory_before": mem_before, "memory_after": mem_after,
         "results": results}, indent=2, ensure_ascii=False))
    (out / "report.md").write_text(report_markdown(
        f"Evaluation report — {stamp}", metrics, results, mem_before, mem_after, config))
    return {"metrics": metrics, "report": str(out / "report.md"), "results": str(out / "results.json")}
