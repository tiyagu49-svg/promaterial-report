"""Planning, role negotiation and re-planning.

- Planner.plan:      goal -> Plan (sub-tasks, assignees, dependencies) with one JSON-mode LLM call.
- Planner.negotiate: every assigned agent reviews its sub-task and accepts or declines
                     (suggesting a better agent); declined sub-tasks are reassigned.
- Planner.replan:    after a failure, plan only the remaining work given what succeeded/failed.
"""
from __future__ import annotations

from typing import Any, Callable

from ..core.schemas import Plan, SubtaskPlan

PLAN_PROMPT = """You are the planner of a multi-agent team. Break the user's goal into a SMALL number
(1-6) of concrete sub-tasks and assign each to the best agent.

## Agents
{roster}

## Rules
- Each sub-task must be self-contained and verifiable; say which file(s) to produce if relevant.
- Use `depends_on` to list ids of sub-tasks whose results are needed first. Sub-tasks without
  dependencies run in parallel.
- Simple goals should have just 1 sub-task. Don't invent work.
- Output documents only as .md or .txt.
- Human-in-the-loop (decide this FIRST): does a good result depend on personal or specific details
  only the human knows (a person's name, their preferences, target audience, which repo/URL to use)?
  If yes, set "needs_clarification" to ONE short question. Example: "write a poem for my friend" ->
  "What is your friend's name and what do they like?". If the goal is clear or details are
  unimportant, use null.

Return a json object:
{{"needs_clarification": "<question or null>",
  "subtasks": [{{"id": "s1", "goal": "...", "assignee": "<agent id>", "depends_on": []}}]}}

## Goal
{goal}
{extra}"""

NEGOTIATE_PROMPT = """You are {agent_id} ({role}): {description}
The manager wants to assign you this sub-task:
\"\"\"{goal}\"\"\"
Other agents: {others}
Accept if it fits your skills and tools ({tools}). Decline only if another agent is clearly better suited.
Return a json object: {{"accept": true/false, "reason": "<short>", "suggest": "<agent id or null>"}}"""

REPLAN_PROMPT = """You are the planner of a multi-agent team. The original goal was:
{goal}

Already completed:
{done}

Failed (with errors):
{failed}

Plan ONLY the remaining work needed to still reach the goal, avoiding the approach that failed.
Agents:
{roster}
Return a json object: {{"subtasks": [{{"id": "r1", "goal": "...", "assignee": "<agent id>", "depends_on": []}}]}}
Return an empty list if nothing useful can be done."""


class Planner:
    def __init__(self, llm: Any, roster_text: str, agent_ids: list[str], fallback_agent: str):
        self.llm = llm
        self.roster_text = roster_text
        self.agent_ids = agent_ids
        self.fallback_agent = fallback_agent

    # ------------------------------------------------------------------ plan
    def plan(self, goal: str, extra_context: str = "") -> Plan:
        extra = f"\n## Extra context\n{extra_context}" if extra_context else ""
        try:
            data = self.llm.chat_json([{"role": "user", "content": PLAN_PROMPT.format(
                roster=self.roster_text, goal=goal, extra=extra)}], temperature=0.0)
            subtasks = self._parse_subtasks(data, goal)
            if not subtasks:
                raise ValueError("empty plan")
            return Plan(goal=goal, subtasks=subtasks, needs_clarification=data.get("needs_clarification") or None)
        except Exception:
            return Plan(goal=goal, subtasks=[SubtaskPlan(id="s1", goal=goal, assignee=self.fallback_agent)])

    def _parse_subtasks(self, data: dict, goal: str, prefix: str = "s") -> list[SubtaskPlan]:
        subtasks = []
        for i, s in enumerate(data.get("subtasks") or []):
            assignee = s.get("assignee") if s.get("assignee") in self.agent_ids else self.fallback_agent
            subtasks.append(SubtaskPlan(
                id=str(s.get("id") or f"{prefix}{i + 1}"), goal=str(s.get("goal", goal)),
                assignee=assignee, depends_on=[str(d) for d in s.get("depends_on") or []],
            ))
        ids = {s.id for s in subtasks}
        for s in subtasks:  # drop unknown / self dependencies
            s.depends_on = [d for d in s.depends_on if d in ids and d != s.id]
        return subtasks

    # ------------------------------------------------------------------ negotiation
    def negotiate(self, plan: Plan, specs: dict[str, Any],
                  post: Callable[[str, str], None] | None = None) -> Plan:
        """Each assignee accepts or declines; declined tasks move to the suggested agent.
        `specs` maps agent id -> AgentSpec; `post(sender, text)` writes to the group chat."""
        if len(plan.subtasks) < 2:  # nothing to negotiate for a single obvious task
            return plan
        for s in plan.subtasks:
            spec = specs.get(s.assignee)
            if spec is None:
                continue
            others = ", ".join(f"{a} ({specs[a].role})" for a in specs if a != s.assignee)
            try:
                data = self.llm.chat_json([{"role": "user", "content": NEGOTIATE_PROMPT.format(
                    agent_id=spec.id, role=spec.role, description=spec.description, goal=s.goal,
                    others=others, tools=", ".join(spec.tools))}], temperature=0.0, max_tokens=200)
            except Exception:
                continue
            accept = data.get("accept", True) not in (False, "false", "no")
            reason = str(data.get("reason", ""))[:200]
            if accept:
                if post:
                    post(s.assignee, f"✔ I accept {s.id}: {reason}")
                continue
            suggest = data.get("suggest")
            if suggest in specs and suggest != s.assignee:
                if post:
                    post(s.assignee, f"✖ I decline {s.id} ({reason}); suggesting @{suggest}")
                s.assignee = suggest
            elif post:
                post(s.assignee, f"✖ I'd rather not take {s.id} ({reason}) but no better agent; keeping it")
        return plan

    # ------------------------------------------------------------------ re-planning
    def replan(self, goal: str, done: list[str], failed: list[str]) -> list[SubtaskPlan]:
        try:
            data = self.llm.chat_json([{"role": "user", "content": REPLAN_PROMPT.format(
                goal=goal, done="\n".join(done) or "(nothing)", failed="\n".join(failed) or "(nothing)",
                roster=self.roster_text)}], temperature=0.0)
            return self._parse_subtasks(data, goal, prefix="r")[:3]
        except Exception:
            return []
