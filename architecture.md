# Architecture

> Living document. Each member expands the section for their area. This is the basis of the final System Architecture Document.

```
 Human (CLI: group chat / DM)
        │
        ▼
 Router ──@agent──► single Agent (direct request)
        │
        └─goal──► Controller ──► Planner (LLM, JSON plan: subtasks + assignees + depends_on)
                      │              └─ needs_clarification? → HumanInterface.ask
                      ▼
               run subtasks in dependency order
                      │   (results + shared files of dependencies → next agent's context/inbox)
                      ▼
                 Agent.run_task  ◄──── memory: retrieve lessons → system prompt
                   loop: LLM (DeepSeek function calling)
                     ├─ gateway tools (files, python, search, git) → inside own sandbox
                     │     └─ critical tool → HumanInterface.approve
                     ├─ ask_human → HITL
                     ├─ delegate → Controller.delegate → another Agent
                     └─ finish → AgentOutcome
                   after: reflect → MemoryRecord appended to the agent's memory.jsonl
                      ▼
               Synthesizer (LLM) → final answer + RunReport (metrics)
```

## 1. Multi-agent routing and delegation (LIU Jiayu)
- **Entry points:** in group chat, `@agent msg` goes straight to that agent. Otherwise the Router makes one LLM call to decide between a single agent (small request) and a team plan. `/dm agent` opens a private 1-on-1 channel (`dm:<agent>`).
- **Planning:** the Planner turns the goal into 1–6 sub-tasks `{id, goal, assignee, depends_on}` with JSON mode. Unknown agents or dependencies are cleaned up.
- **Negotiation:** for plans with 2 or more sub-tasks, each assignee gets a short LLM call to accept or decline (with a reason and a suggested agent). Declined sub-tasks are reassigned, and all of it is posted to the group chat.
- **Execution:** sub-tasks run in dependency waves. Independent sub-tasks in a wave run in parallel (ThreadPoolExecutor, `max_workers`). Results of dependencies go to the next agent as context, and produced files are copied into its `inbox/`.
- **Agent-to-agent delegation:** any agent can call `delegate(agent_id, task)` at runtime, up to `max_delegation_depth`.
- **Recovery:** a failed sub-task is retried (`max_retries`) with the previous error as context. If it still fails, the Planner re-plans the remaining work once. Sub-tasks that are recovered this way are marked as superseded.

## 2. Memory and evolution — Member 4: GU Tianyang
- Each agent has its own `runtime/agents/<id>/memory.jsonl`.
- After every task, a reflection writes `{summary, lesson, success, tags}`.
- Before every task, the top-k relevant lessons go into the system prompt, so agents learn from both successes and failures.

## 3. Sandbox and isolation — Member 3: JI Guangning
- Each agent has a private workspace, `runtime/agents/<id>/workspace`, and every path is resolved inside it.
- The only cross-agent data flow is the explicit `sandbox.share` into `inbox/`.
- Python runs as a subprocess with cwd set to the workspace and a timeout. Planned: a Docker container per agent.

## 4. Human-in-the-loop (LIU Jiayu)
- **Clarification before planning:** the planner sets `needs_clarification` when the result depends on details only the human knows, such as names or preferences. The manager asks before work starts.
- **Clarification during work:** agents have an `ask_human` tool.
- **Permission:** tools listed in `human.critical_tools` (default: delete_file, git_push), plus any tool marked `critical`, need approval through the ToolGateway. The CLI supports `approval_timeout_s` (no answer means deny). Every decision is kept in an audit list.
- **Evaluation mode:** `AutoHuman` approves and answers from a per-task answer dict, so the test set runs unattended.

## 5. Evaluation — Member 4: GU Tianyang
- `RunReport` gives success, sub-task counts, and `duration_s`.
- `llm.usage` gives token counts.
