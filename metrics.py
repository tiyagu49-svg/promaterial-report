"""Computes and reports the course metrics: task completion rate and execution time (+ extras).

Input: list of per-task result dicts produced by runner.run_suite.
"""
from __future__ import annotations

import statistics
from typing import Any


def _pct(a: float, b: float) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def compute_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results)
    passed = sum(r["passed"] for r in results)
    crashed = sum(1 for r in results if r.get("crashed"))
    sub_total = sum(r.get("subtasks_total", 0) for r in results)
    sub_ok = sum(r.get("subtasks_succeeded", 0) for r in results)
    times = [r["duration_s"] for r in results]
    checks_total = sum(len(r.get("checks", [])) for r in results)
    checks_ok = sum(sum(c["passed"] for c in r.get("checks", [])) for r in results)
    by_cat: dict[str, list[bool]] = {}
    for r in results:
        by_cat.setdefault(r.get("category", "general"), []).append(r["passed"])
    return {
        "tasks": n,
        "goal_completion_rate": _pct(passed, n),
        "subtask_completion_rate": _pct(sub_ok, sub_total),
        "check_pass_rate": _pct(checks_ok, checks_total),
        "crash_rate": _pct(crashed, n),
        "time_total_s": round(sum(times), 1),
        "time_mean_s": round(statistics.mean(times), 1) if times else 0.0,
        "time_median_s": round(statistics.median(times), 1) if times else 0.0,
        "time_p90_s": round(percentile(times, 0.9), 1),
        "llm_calls": sum(r.get("llm_calls", 0) for r in results),
        "tokens": sum(r.get("tokens", 0) for r in results),
        "retries": sum(r.get("retries", 0) for r in results),
        "replans": sum(1 for r in results if r.get("replanned")),
        "by_category": {k: _pct(sum(v), len(v)) for k, v in sorted(by_cat.items())},
    }


def report_markdown(title: str, metrics: dict[str, Any], results: list[dict[str, Any]],
                    memory_before: dict[str, Any], memory_after: dict[str, Any], config: dict[str, Any]) -> str:
    m = metrics
    lines = [
        f"# {title}", "",
        f"Config: {', '.join(f'{k}={v}' for k, v in config.items())}", "",
        "## Core metrics", "",
        "| Metric | Value |", "|---|---|",
        f"| Goal completion rate | **{m['goal_completion_rate']}%** ({sum(r['passed'] for r in results)}/{m['tasks']}) |",
        f"| Sub-task completion rate | {m['subtask_completion_rate']}% |",
        f"| Check pass rate | {m['check_pass_rate']}% |",
        f"| Crash rate | {m['crash_rate']}% |",
        f"| Execution time total / mean / median / p90 | {m['time_total_s']}s / {m['time_mean_s']}s / {m['time_median_s']}s / {m['time_p90_s']}s |",
        f"| LLM calls / tokens | {m['llm_calls']} / {m['tokens']} |",
        f"| Retries / re-plans | {m['retries']} / {m['replans']} |",
        "", "## By category", "", "| Category | Completion |", "|---|---|",
    ]
    lines += [f"| {k} | {v}% |" for k, v in m["by_category"].items()]
    lines += ["", "## Per task", "", "| id | category | pass | time (s) | sub-tasks | failed checks |", "|---|---|---|---|---|---|"]
    for r in results:
        failed = "; ".join(f"{c['type']}: {c['detail']}" for c in r.get("checks", []) if not c["passed"])
        if r.get("crashed"):
            failed = f"CRASH: {r.get('error', '')}"
        lines.append(f"| {r['id']} | {r.get('category', '')} | {'✅' if r['passed'] else '❌'} | {r['duration_s']:.1f} | "
                     f"{r.get('subtasks_succeeded', 0)}/{r.get('subtasks_total', 0)} | {failed.replace('|', '/')[:200]} |")
    lines += ["", "## Memory evolution", "", "| Agent | lessons before | lessons after | avg usefulness after |", "|---|---|---|---|"]
    for agent in sorted(set(memory_before) | set(memory_after)):
        b, a = memory_before.get(agent, {}), memory_after.get(agent, {})
        lines.append(f"| {agent} | {b.get('lessons', 0)} | {a.get('lessons', 0)} | {a.get('avg_usefulness')} |")
    failures = [r for r in results if not r["passed"]]
    if failures:
        lines += ["", "## Failure modes (auto-extracted)", ""]
        for r in failures:
            lines.append(f"- **{r['id']}**: {(r.get('error') or r.get('answer', ''))[:200].replace(chr(10), ' ')}")
    return "\n".join(lines) + "\n"
