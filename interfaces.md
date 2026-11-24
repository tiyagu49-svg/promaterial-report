# Interfaces

The contracts between modules. If you need to change one, tell the team first and update this file.

## Data models — `core/schemas.py`
- `Message(channel, sender, content, kind, task_id, metadata)`. Channels are `dm:<agent_id>` (1-on-1 with the human) or `group:<name>` (default `group:main`).
- `Task(id, goal, parent_id, assignee, depends_on, status, result, error, artifacts, started_at, finished_at)`
- `Plan(goal, subtasks: [SubtaskPlan(id, goal, assignee, depends_on)], needs_clarification)`
- `ToolResult(ok, output, error, artifacts)`
- `AgentOutcome(task_id, agent_id, success, answer, steps, tool_calls, error)`

## Message bus — `core/events.py`
`bus.post(channel, sender, content, kind=...)`, `bus.subscribe(channel | "*", fn)`, `bus.history(channel)`, `bus.transcript(channel)`.
Every message is also appended to `runtime/logs/messages.jsonl`.

## LLM — `llm/client.py`
`llm.chat(messages, tools=None, json_mode=False) -> LLMResponse(content, tool_calls)`, `llm.chat_json(messages) -> dict`, `llm.usage.as_dict()`.
`MockLLMClient(script)` is for offline tests: `script(messages, tools) -> LLMResponse`.

## Tools — `tools/gateway.py`
Subclass `Tool` (`name`, `description`, `parameters` JSON schema, `critical`, `run(ctx, **args) -> ToolResult`), then register it in `tools/__init__.py:default_tools()` and allow it per agent in `configs/agents.yaml`.
`ToolContext` gives the tool `agent_id`, `workspace`, `sandbox`, `settings`, `human`, and `task_id`.
Critical tools ask `human.approve()` automatically. Tools must never raise: return `ToolResult(ok=False, error=...)`.

## Sandbox — `sandbox/manager.py`
`sandbox.workspace(agent_id) -> Path`, `sandbox.resolve(agent_id, rel_path)` (raises `SandboxViolation` on escape), and `sandbox.share(from, rel_path, to)`, which copies into `<to>/workspace/inbox/<from>/`.

## Human-in-the-loop — `human/approvals.py`
`HumanInterface.ask(agent_id, question, channel) -> str` and `HumanInterface.approve(agent_id, action, channel) -> bool`.
Implementations: `CLIHuman` (interactive) and `AutoHuman` (evaluation; approves everything and gives a default answer).

## Memory — `memory/`
- `JsonMemoryStore(agent_id, path)`: `.add(MemoryRecord)`, `.all()`
- `retrieve(store, query, k) -> list[MemoryRecord]`, `format_lessons(records) -> str` (goes into the agent's system prompt)
- `reflect(llm, agent_id, goal, outcome) -> MemoryRecord` (called after every task)

## Agent — `agents/agent.py`
`agent.run_task(task, context="", channel=..., depth=0) -> AgentOutcome` and `agent.chat(text) -> str` (DM).
Built-in LLM tools: `finish`, `ask_human`, `delegate`, `send_message`.

## Orchestration — `orchestration/controller.py`
`controller.run_goal(goal) -> RunReport(run_id, goal, success, final_answer, subtasks_total, subtasks_succeeded, duration_s, tasks, plan, error)`.
`controller.delegate(from, to, goal, depth) -> AgentOutcome`. This is wired as every agent's `delegate_fn`.

## App — `app.py`
`build_platform(settings=None, llm=None, human_mode=None) -> Platform` (bundles settings, llm, bus, sandbox, gateway, registry, router, controller, human).
