"""Tool gateway: tool base class, permission checks, HITL approval for critical tools, dispatch.

How to add a tool (Member 3 - JI Guangning):
    class MyTool(Tool):
        name = "my_tool"
        description = "What it does (the LLM reads this)."
        parameters = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        critical = False          # True => human must approve before it runs
        def run(self, ctx: ToolContext, x: str) -> ToolResult: ...
    then add it to `default_tools()` in tools/__init__.py and to an agent's `tools:` in configs/agents.yaml.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.schemas import ToolResult

if TYPE_CHECKING:
    from ..human.approvals import HumanInterface
    from ..sandbox.manager import SandboxManager
    from ..settings import Settings


@dataclass
class ToolContext:
    """Everything a tool needs to act on behalf of one agent."""
    agent_id: str
    workspace: Path                       # the agent's private sandbox folder
    sandbox: "SandboxManager"
    settings: "Settings"
    human: "HumanInterface | None" = None
    task_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Tool:
    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    critical: bool = False               # requires human approval (delete, push, ...)

    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:  # pragma: no cover - interface
        raise NotImplementedError

    def schema(self) -> dict[str, Any]:
        """OpenAI-compatible function schema (DeepSeek uses the same format)."""
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }

    def describe_call(self, args: dict[str, Any]) -> str:
        """Human-readable summary shown in approval prompts. Override for nicer text."""
        return f"{self.name}({args})"


class ToolGateway:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        self.call_log: list[dict[str, Any]] = []
        for t in tools or []:
            self.register(t)

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError(f"{tool!r} has no name")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self, allowed: list[str]) -> list[dict[str, Any]]:
        return [self._tools[n].schema() for n in allowed if n in self._tools]

    def dispatch(self, ctx: ToolContext, name: str, args: dict[str, Any], allowed: list[str]) -> ToolResult:
        t0 = time.time()
        result = self._dispatch(ctx, name, args, allowed)
        self.call_log.append({
            "agent": ctx.agent_id, "task": ctx.task_id, "tool": name, "args": args,
            "ok": result.ok, "error": result.error, "artifacts": result.artifacts, "duration_s": round(time.time() - t0, 3),
        })
        return result

    def _dispatch(self, ctx: ToolContext, name: str, args: dict[str, Any], allowed: list[str]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"Unknown tool '{name}'. Available: {allowed}")
        if name not in allowed:
            return ToolResult(ok=False, error=f"Agent '{ctx.agent_id}' is not permitted to use '{name}'.")
        if "_raw" in args:
            return ToolResult(ok=False, error=f"Arguments were not valid JSON: {args['_raw'][:200]}")
        critical = tool.critical or name in getattr(ctx.settings.human, "critical_tools", [])
        if critical and ctx.human is not None:
            if not ctx.human.approve(ctx.agent_id, tool.describe_call(args)):
                return ToolResult(ok=False, error="Human denied permission for this action.")
        try:
            return tool.run(ctx, **args)
        except TypeError as e:  # wrong/missing arguments from the LLM
            return ToolResult(ok=False, error=f"Bad arguments for {name}: {e}")
        except Exception as e:  # never let a tool crash the agent
            return ToolResult(ok=False, error=f"{type(e).__name__}: {e}")
