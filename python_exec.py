"""Run Python code inside the agent's workspace.

Baseline: runs `python <file>` as a subprocess with cwd = workspace and a timeout.
TODO(Member 3 - JI Guangning): run inside the agent's Docker sandbox, add a `run_tests` (pytest) tool,
restrict network/env vars, cap output size and memory.
"""
from __future__ import annotations

import subprocess
import sys

from ..core.schemas import ToolResult
from .gateway import Tool, ToolContext


class RunPython(Tool):
    name = "run_python"
    description = (
        "Execute Python. Either pass `code` (saved to a temp file and run) or `path` of a .py file in "
        "your workspace. Returns stdout/stderr and the exit code."
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python source to run."},
            "path": {"type": "string", "description": "Existing .py file in workspace to run."},
            "args": {"type": "array", "items": {"type": "string"}, "description": "CLI args."},
        },
    }

    def run(self, ctx: ToolContext, code: str | None = None, path: str | None = None,
            args: list[str] | None = None) -> ToolResult:
        if not code and not path:
            return ToolResult(ok=False, error="Provide `code` or `path`.")
        if code:
            path = "_scratch/run.py"
            f = ctx.sandbox.resolve(ctx.agent_id, path)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(code)
        target = ctx.sandbox.resolve(ctx.agent_id, path)
        if not target.is_file():
            return ToolResult(ok=False, error=f"File not found: {path}")
        try:
            proc = subprocess.run(
                [sys.executable, str(target), *(args or [])],
                cwd=ctx.workspace, capture_output=True, text=True,
                timeout=ctx.settings.sandbox.python_timeout_s,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error=f"Timed out after {ctx.settings.sandbox.python_timeout_s}s")
        out = f"exit_code={proc.returncode}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        return ToolResult(ok=proc.returncode == 0, output=out,
                          error=None if proc.returncode == 0 else "Non-zero exit code")


class RunTests(Tool):
    name = "run_tests"
    description = "Run pytest on a test file or folder in your workspace."
    parameters = {"type": "object", "properties": {"path": {"type": "string", "default": "."}}}

    def run(self, ctx: ToolContext, path: str = ".") -> ToolResult:
        return ToolResult(ok=False, error="run_tests is not implemented yet (Member 3 - JI Guangning).")
