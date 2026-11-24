"""Pass/fail checks for evaluation tasks.

Each check is a dict from the task file; `run_check(check, ctx)` returns (passed, detail).
Supported types:
  {"type": "file_exists",    "path": "fib.py", "agent": "coder"}      # agent optional -> any agent
  {"type": "file_contains",  "path": "report.md", "text": "Fibonacci"} # case-insensitive
  {"type": "answer_contains","text": "42"}                            # final answer text
  {"type": "python_runs",    "path": "fib.py", "expect": "55"}        # exit 0 (+ optional stdout text)
  {"type": "asked_human"}                                             # agents asked a clarification
  {"type": "approval_requested"}                                      # a critical action was gated
  {"type": "llm_judge",      "rubric": "..."}                         # HKGAI/DeepSeek grades 0/1
  {"type": "success"}                                                 # controller reported success
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class CheckContext:
    platform: Any                         # mas_platform.app.Platform
    report: Any                           # RunReport (or None if the run crashed)
    questions: list = field(default_factory=list)
    approvals: list = field(default_factory=list)

    @property
    def answer(self) -> str:
        return (getattr(self.report, "final_answer", "") or "") if self.report else ""


def _find_file(ctx: CheckContext, path: str, agent: str | None) -> Path | None:
    agents = [agent] if agent else ctx.platform.registry.ids()
    for a in agents:
        try:
            ws = ctx.platform.sandbox.workspace(a)
        except Exception:
            continue
        p = ws / path
        if p.is_file():
            return p
        hits = [h for h in ws.rglob(Path(path).name) if h.is_file() and "inbox" not in h.parts]
        if hits:
            return hits[0]
    return None


def check_file_exists(c: dict, ctx: CheckContext) -> tuple[bool, str]:
    p = _find_file(ctx, c["path"], c.get("agent"))
    return (p is not None, f"found {p}" if p else f"{c['path']} not found")


def check_file_contains(c: dict, ctx: CheckContext) -> tuple[bool, str]:
    p = _find_file(ctx, c["path"], c.get("agent"))
    if not p:
        return False, f"{c['path']} not found"
    texts = c["text"] if isinstance(c["text"], list) else [c["text"]]
    body = p.read_text(errors="ignore").lower()
    missing = [t for t in texts if t.lower() not in body]
    return (not missing, "ok" if not missing else f"missing {missing}")


def check_answer_contains(c: dict, ctx: CheckContext) -> tuple[bool, str]:
    texts = c["text"] if isinstance(c["text"], list) else [c["text"]]
    missing = [t for t in texts if t.lower() not in ctx.answer.lower()]
    return (not missing, "ok" if not missing else f"answer missing {missing}")


def check_python_runs(c: dict, ctx: CheckContext) -> tuple[bool, str]:
    p = _find_file(ctx, c["path"], c.get("agent"))
    if not p:
        return False, f"{c['path']} not found"
    agent = p.relative_to(ctx.platform.sandbox.root).parts[0]
    ws = ctx.platform.sandbox.workspace(agent)
    res = ctx.platform.sandbox.run_command(agent, ["python", str(p.relative_to(ws))], timeout=60)
    if res.exit_code != 0:
        return False, f"exit {res.exit_code}: {res.stderr[-300:]}"
    if c.get("expect") and str(c["expect"]) not in res.stdout:
        return False, f"stdout lacks {c['expect']!r}: {res.stdout[-200:]}"
    return True, "ran ok"


def check_asked_human(c: dict, ctx: CheckContext) -> tuple[bool, str]:
    return (len(ctx.questions) > 0, f"{len(ctx.questions)} question(s)")


def check_approval_requested(c: dict, ctx: CheckContext) -> tuple[bool, str]:
    return (len(ctx.approvals) > 0, f"{len(ctx.approvals)} approval(s)")


def check_success(c: dict, ctx: CheckContext) -> tuple[bool, str]:
    ok = bool(ctx.report and ctx.report.success)
    return ok, "controller success" if ok else "controller reported failure"


JUDGE_PROMPT = """You are grading an AI team's answer.
Task: {goal}
Rubric: {rubric}
Answer:
\"\"\"{answer}\"\"\"
Return a json object: {{"pass": true/false, "reason": "<short>"}}"""


def check_llm_judge(c: dict, ctx: CheckContext) -> tuple[bool, str]:
    goal = getattr(ctx.report, "goal", "") if ctx.report else ""
    try:
        data = ctx.platform.llm.chat_json([{"role": "user", "content": JUDGE_PROMPT.format(
            goal=goal, rubric=c.get("rubric", "The answer fully and correctly completes the task."),
            answer=ctx.answer[:4000])}], temperature=0.0, max_tokens=200)
        return bool(data.get("pass")), str(data.get("reason", ""))[:200]
    except Exception as e:
        return False, f"judge error: {e}"


CHECKS: dict[str, Callable[[dict, CheckContext], tuple[bool, str]]] = {
    "file_exists": check_file_exists,
    "file_contains": check_file_contains,
    "answer_contains": check_answer_contains,
    "python_runs": check_python_runs,
    "asked_human": check_asked_human,
    "approval_requested": check_approval_requested,
    "llm_judge": check_llm_judge,
    "success": check_success,
}


def run_check(check: dict, ctx: CheckContext) -> tuple[bool, str]:
    fn = CHECKS.get(check.get("type", ""))
    if fn is None:
        return False, f"unknown check type {check.get('type')!r}"
    try:
        return fn(check, ctx)
    except Exception as e:
        return False, f"check crashed: {type(e).__name__}: {e}"
