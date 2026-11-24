"""Post-task reflection: turn a finished task (success or failure) into a reusable lesson.

For failures the prompt asks for the root cause (wrong tool, missing info, bad assumption, ...)
so the lesson tells the agent what to do differently next time.
"""
from __future__ import annotations

import json
from typing import Any

from ..core.schemas import AgentOutcome
from .store import MemoryRecord

REFLECT_PROMPT = """You are {agent_id}, reviewing your own just-finished task to learn from it.
Task goal: {goal}
Outcome: {status}
Final answer / error: {answer}
Tool calls made (tool, ok): {tools}

{guidance}

Return a json object with keys:
  "summary": one sentence of what happened,
  "root_cause": {root_cause_hint},
  "lesson": one or two sentences of concrete, reusable advice for SIMILAR future tasks
            (general, not specific to this exact file name),
  "tags": 2-5 short lowercase keywords (task type, tools involved).
"""

SUCCESS_GUIDE = "It succeeded. What made it work efficiently? Could it have been done in fewer steps?"
FAILURE_GUIDE = ("It FAILED. Identify the root cause: wrong/missing tool, misunderstood goal, missing information "
                 "(should have asked the human?), bad assumption, code error, or step limit.")


def reflect(llm: Any, agent_id: str, goal: str, outcome: AgentOutcome) -> MemoryRecord:
    tools = [(c.get("tool"), c.get("ok")) for c in outcome.tool_calls]
    failed_tools = sum(1 for _, ok in tools if not ok)
    try:
        data = llm.chat_json([{
            "role": "user",
            "content": REFLECT_PROMPT.format(
                agent_id=agent_id, goal=goal[:1500], status="SUCCESS" if outcome.success else "FAILURE",
                answer=(outcome.answer or outcome.error or "")[:1500], tools=json.dumps(tools)[:1200],
                guidance=SUCCESS_GUIDE if outcome.success else FAILURE_GUIDE,
                root_cause_hint='"none"' if outcome.success else "short root cause of the failure",
            ),
        }], temperature=0.0, max_tokens=400)
        return MemoryRecord(
            agent_id=agent_id, task_goal=goal[:500], success=outcome.success,
            summary=str(data.get("summary", ""))[:500], lesson=str(data.get("lesson", ""))[:800],
            tags=[str(t).lower() for t in data.get("tags", [])][:5],
            metadata={"steps": outcome.steps, "task_id": outcome.task_id, "failed_tool_calls": failed_tools,
                      "root_cause": str(data.get("root_cause", ""))[:300]},
        )
    except Exception as e:
        return MemoryRecord(
            agent_id=agent_id, task_goal=goal[:500], success=outcome.success,
            summary=(outcome.answer or outcome.error or "")[:300],
            lesson="(reflection failed)", metadata={"reflection_error": str(e), "task_id": outcome.task_id},
        )
