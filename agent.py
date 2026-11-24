"""Single-agent loop: reason -> call tools -> observe -> ... -> finish, inside the agent's sandbox.

Uses native function calling (DeepSeek supports the OpenAI `tools` format).
Built-in tools every agent gets (not in the gateway):
    finish(answer, success)          end the task with a result
    ask_human(question)              HITL clarification (pauses until the human answers)
    delegate(agent_id, task)         hand a sub-task to another specialised agent and wait for its result
    send_message(channel, content)   post to a group chat or DM
Memory: relevant lessons are retrieved before the task and a reflection is stored after it.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable

from ..core.events import DEFAULT_GROUP, MessageBus
from ..core.schemas import AgentOutcome, MessageKind, Task, ToolResult
from ..memory import JsonMemoryStore, format_lessons, reflect, retrieve
from ..settings import AgentSpec
from ..tools.gateway import ToolContext, ToolGateway

if TYPE_CHECKING:
    from ..human.approvals import HumanInterface
    from ..sandbox.manager import SandboxManager
    from ..settings import Settings

# (from_agent, to_agent, goal, depth) -> AgentOutcome
DelegateFn = Callable[[str, str, str, int], AgentOutcome]

SYSTEM_TEMPLATE = """You are **{agent_id}**, the {role} agent in a multi-agent team.
Your speciality: {description}

## Team members you can delegate to (with the `delegate` tool)
{team}

## Your environment
- You have a PRIVATE workspace folder. All file paths are relative to it. Other agents cannot see it.
  Files other agents shared with you appear under `inbox/<agent>/`.
- Documents must be plain text: Markdown (.md) or .txt only. Never produce PDF/DOCX/PPT.
- Available tools: {tools}

## Lessons from your past tasks (use them!)
{lessons}

## Rules
1. Think step by step, then act with tools. Verify your work (e.g. run code you wrote).
2. If the task is ambiguous or missing information you cannot reasonably assume, call `ask_human`.
3. Critical actions (deleting files, pushing code) will be shown to the human for approval automatically.
4. If part of the task clearly belongs to another specialist, `delegate` it with a precise, self-contained instruction.
5. When done, call `finish` with a complete answer (include file paths you created). If you could not
   complete the task, call `finish` with success=false and explain why.
"""

BUILTIN_TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "finish",
        "description": "End the task and report the final result.",
        "parameters": {"type": "object", "properties": {
            "answer": {"type": "string", "description": "Final answer / summary of what was done."},
            "success": {"type": "boolean", "description": "False if the task could not be completed."},
        }, "required": ["answer"]}}},
    {"type": "function", "function": {
        "name": "ask_human",
        "description": "Ask the human a clarification question and wait for the reply.",
        "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}},
    {"type": "function", "function": {
        "name": "delegate",
        "description": "Assign a sub-task to another agent and wait for its result.",
        "parameters": {"type": "object", "properties": {
            "agent_id": {"type": "string"},
            "task": {"type": "string", "description": "Self-contained instruction for that agent."},
        }, "required": ["agent_id", "task"]}}},
    {"type": "function", "function": {
        "name": "send_message",
        "description": "Post a message to a chat channel ('group:main' or 'dm:<agent_id>').",
        "parameters": {"type": "object", "properties": {
            "channel": {"type": "string"}, "content": {"type": "string"},
        }, "required": ["channel", "content"]}}},
]


class Agent:
    def __init__(
        self,
        spec: AgentSpec,
        llm: Any,
        gateway: ToolGateway,
        sandbox: "SandboxManager",
        bus: MessageBus,
        settings: "Settings",
        human: "HumanInterface | None" = None,
        team: dict[str, AgentSpec] | None = None,
    ):
        self.spec = spec
        self.id = spec.id
        self.llm = llm
        self.gateway = gateway
        self.sandbox = sandbox
        self.bus = bus
        self.settings = settings
        self.human = human
        self.team = team or {}
        self.delegate_fn: DelegateFn | None = None
        self.workspace = sandbox.workspace(self.id)
        self.memory = JsonMemoryStore(self.id, sandbox.agent_dir(self.id) / "memory.jsonl")

    # ------------------------------------------------------------------ prompt
    def system_prompt(self, goal: str) -> str:
        return self._build_prompt(goal)[0]

    def _build_prompt(self, goal: str) -> tuple[str, list]:
        """Returns (system prompt, memory records that were injected)."""
        if self.spec.system_prompt:
            return self.spec.system_prompt, []
        team = "\n".join(f"- {a.id} ({a.role}): {a.description}" for a in self.team.values() if a.id != self.id)
        used = retrieve(self.memory, goal, k=self.settings.memory.top_k) if self.settings.memory.enabled else []
        prompt = SYSTEM_TEMPLATE.format(
            agent_id=self.id, role=self.spec.role, description=self.spec.description,
            team=team or "(none)", tools=", ".join(self.spec.tools) or "(none)", lessons=format_lessons(used),
        )
        return prompt, used

    # ------------------------------------------------------------------ main loop
    def run_task(self, task: Task, context: str = "", channel: str = DEFAULT_GROUP, depth: int = 0,
                 learn: bool = True) -> AgentOutcome:
        user_msg = f"## Task\n{task.goal}"
        if context:
            user_msg += f"\n\n## Context from teammates / previous steps\n{context}"
        system, used_lessons = self._build_prompt(task.goal)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]
        tools = self.gateway.schemas(self.spec.tools) + BUILTIN_TOOLS
        ctx = ToolContext(agent_id=self.id, workspace=self.workspace, sandbox=self.sandbox,
                          settings=self.settings, human=self.human, task_id=task.id)
        calls: list[dict[str, Any]] = []
        max_steps = self.settings.runtime.max_agent_steps
        self.bus.post(channel, self.id, f"Starting: {task.goal[:200]}", kind=MessageKind.SYSTEM, task_id=task.id)

        outcome: AgentOutcome | None = None
        step = 0
        nudged = False
        try:
            for step in range(1, max_steps + 1):
                _trim_context(messages)
                resp = self.llm.chat(messages, tools=tools)
                messages.append(resp.assistant_message())

                if not resp.tool_calls:
                    # The model answered in plain text; nudge it to use finish (once), else accept.
                    if step < max_steps and not nudged:
                        nudged = True
                        messages.append({"role": "user", "content": "If you are done, call `finish` with your answer. Otherwise continue using tools."})
                        continue
                    outcome = AgentOutcome(task_id=task.id, agent_id=self.id, success=True,
                                           answer=resp.content, steps=step, tool_calls=calls)
                    break

                for tc in resp.tool_calls:
                    if tc.name == "finish":
                        outcome = AgentOutcome(
                            task_id=task.id, agent_id=self.id,
                            success=bool(tc.arguments.get("success", True)),
                            answer=str(tc.arguments.get("answer", "")), steps=step, tool_calls=calls,
                        )
                        result = ToolResult(ok=True, output="finished")
                    else:
                        result = self._call_tool(ctx, tc.name, tc.arguments, channel, depth)
                        calls.append({"tool": tc.name, "args": _short(tc.arguments), "ok": result.ok})
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result.to_llm()})
                if outcome:
                    break
            if outcome is None:
                outcome = AgentOutcome(task_id=task.id, agent_id=self.id, success=False, answer="",
                                       steps=step, tool_calls=calls,
                                       error=f"Step limit ({max_steps}) reached without finishing.")
        except Exception as e:  # LLM outage etc. -> a failed (not crashed) task
            outcome = AgentOutcome(task_id=task.id, agent_id=self.id, success=False, answer="",
                                   steps=step, tool_calls=calls, error=f"{type(e).__name__}: {e}")

        self.bus.post(channel, self.id, outcome.answer or f"FAILED: {outcome.error}",
                      kind=MessageKind.TASK_RESULT, task_id=task.id, metadata={"success": outcome.success})
        if learn and self.settings.memory.enabled:
            self.learn(task.goal, outcome)
            try:  # evolution signal: which injected lessons were present when we succeeded/failed
                self.memory.mark_used([r.id for r in used_lessons], outcome.success)
            except Exception as e:
                print(f"[{self.id}] mark_used failed: {e}")
        return outcome

    # ------------------------------------------------------------------ tools
    def _call_tool(self, ctx: ToolContext, name: str, args: dict[str, Any], channel: str, depth: int) -> ToolResult:
        if name == "ask_human":
            if self.human is None:
                return ToolResult(ok=False, error="No human available; make a reasonable assumption.")
            return ToolResult(ok=True, output=self.human.ask(self.id, str(args.get("question", "")), channel))
        if name == "send_message":
            self.bus.post(str(args.get("channel", channel)), self.id, str(args.get("content", "")))
            return ToolResult(ok=True, output="sent")
        if name == "delegate":
            return self._delegate(str(args.get("agent_id", "")), str(args.get("task", "")), depth)
        return self.gateway.dispatch(ctx, name, args, self.spec.tools)

    def _delegate(self, to_agent: str, goal: str, depth: int) -> ToolResult:
        if self.delegate_fn is None:
            return ToolResult(ok=False, error="Delegation is not available in this context.")
        if to_agent == self.id:
            return ToolResult(ok=False, error="You cannot delegate to yourself.")
        if to_agent not in self.team:
            return ToolResult(ok=False, error=f"Unknown agent '{to_agent}'. Team: {list(self.team)}")
        if depth >= self.settings.runtime.max_delegation_depth:
            return ToolResult(ok=False, error="Max delegation depth reached; do it yourself.")
        out = self.delegate_fn(self.id, to_agent, goal, depth + 1)
        text = f"[{to_agent}] success={out.success}\n{out.answer or out.error}"
        return ToolResult(ok=out.success, output=text, error=None if out.success else out.error)

    # ------------------------------------------------------------------ memory
    def learn(self, goal: str, outcome: AgentOutcome) -> None:
        if outcome.error and outcome.error.startswith(("LLMError", "LLMFatalError")):
            return  # infrastructure outage, not a lesson about the task
        try:
            self.memory.add(reflect(self.llm, self.id, goal, outcome))
        except Exception as e:
            print(f"[{self.id}] memory write failed: {e}")

    # ------------------------------------------------------------------ 1-on-1 chat
    def chat(self, text: str) -> str:
        """Private DM with the human: treat the message as a task on the agent's DM channel."""
        channel = f"dm:{self.id}"
        history = self.bus.transcript(channel, limit=10)
        self.bus.post(channel, "human", text)
        task = Task(goal=text, assignee=self.id, metadata={"mode": "dm"})
        out = self.run_task(task, context=f"Recent DM history:\n{history}" if history else "", channel=channel)
        return out.answer or f"(failed: {out.error})"


def _short(args: dict[str, Any], n: int = 300) -> dict[str, Any]:
    s = json.dumps(args, ensure_ascii=False)
    return args if len(s) <= n else {"_truncated": s[:n]}


def _trim_context(messages: list[dict[str, Any]], max_chars: int = 60000, keep_last: int = 6) -> None:
    """Context-window guard: when the history gets long, shorten old tool outputs in place."""
    total = sum(len(str(m.get("content") or "")) for m in messages)
    if total <= max_chars:
        return
    for m in messages[2:-keep_last]:
        if m.get("role") == "tool" and len(m.get("content") or "") > 400:
            m["content"] = m["content"][:400] + "\n...[older output trimmed]"
