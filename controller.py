"""Central controller: human goal -> plan -> negotiate -> run sub-tasks -> recover -> final answer.

Pipeline:
  1. Planner.plan (asks the human first if the goal is too ambiguous)
  2. Planner.negotiate: assignees accept/decline, declined sub-tasks get reassigned
  3. Execute in dependency "waves"; independent sub-tasks of a wave run in parallel threads
     - results + produced files of dependencies are passed on (files shared into the inbox)
     - a failed sub-task is retried (orchestration.max_retries) with the error as context
  4. If something still failed: Planner.replan the remaining work once and run it
  5. Manager-side synthesis of the final answer -> RunReport (consumed by the evaluation harness)
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..agents.registry import AgentRegistry
from ..core.events import DEFAULT_GROUP, MessageBus
from ..core.schemas import AgentOutcome, MessageKind, Plan, SubtaskPlan, Task, TaskStatus, new_id
from ..sandbox.manager import SandboxManager
from .planner import Planner
from .task_store import TaskStore


class RunReport(BaseModel):
    """Result of one top-level goal. The evaluation harness (Member 4 - GU Tianyang) consumes this."""
    run_id: str
    goal: str
    success: bool
    final_answer: str
    subtasks_total: int
    subtasks_succeeded: int
    duration_s: float
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    plan: dict[str, Any] | None = None
    error: str | None = None
    retries: int = 0
    replanned: bool = False


SYNTH_PROMPT = """The team finished working on the goal below. Write the final answer for the human.
Be concise and complete; mention any files produced (with paths) and anything that failed.

## Goal
{goal}

## Sub-task results
{results}"""


class Controller:
    def __init__(self, registry: AgentRegistry, planner: Planner, bus: MessageBus,
                 sandbox: SandboxManager, checkpoint_dir, llm: Any, manager_id: str, human=None,
                 settings: Any = None):
        self.registry = registry
        self.planner = planner
        self.bus = bus
        self.sandbox = sandbox
        self.checkpoint_dir = checkpoint_dir
        self.llm = llm
        self.manager_id = manager_id
        self.human = human
        orch = getattr(settings, "orchestration", None)
        self.negotiate = getattr(orch, "negotiate", True)
        self.parallel = getattr(orch, "parallel", True)
        self.max_workers = getattr(orch, "max_workers", 3)
        self.max_retries = getattr(orch, "max_retries", 1)
        self.replan_on_failure = getattr(orch, "replan_on_failure", True)

    # ------------------------------------------------------------------
    def delegate(self, from_agent: str, to_agent: str, goal: str, depth: int) -> AgentOutcome:
        """Called by Agent.delegate tool: one agent assigning work to another."""
        self.bus.post(DEFAULT_GROUP, from_agent, f"@{to_agent} {goal}", kind=MessageKind.TASK_ASSIGN)
        task = Task(goal=goal, assignee=to_agent, created_by=from_agent)
        return self.registry.get(to_agent).run_task(task, depth=depth)

    # ------------------------------------------------------------------
    def run_goal(self, goal: str, channel: str = DEFAULT_GROUP) -> RunReport:
        t0 = time.time()
        run_id = new_id("run_")
        store = TaskStore(run_id, self.checkpoint_dir)
        root = store.add(Task(goal=goal, created_by="human", status=TaskStatus.RUNNING, started_at=t0))
        self.bus.post(channel, "human", goal, kind=MessageKind.TASK_ASSIGN, task_id=root.id)
        plan: Plan | None = None
        replanned = False
        final = ""

        try:
            plan = self.planner.plan(goal)
            if plan.needs_clarification and self.human is not None:
                answer = self.human.ask(self.manager_id, plan.needs_clarification, channel)
                plan = self.planner.plan(goal, extra_context=f"Q: {plan.needs_clarification}\nA: {answer}")
            if self.negotiate:
                specs = {a.id: a.spec for a in self.registry.all()}
                plan = self.planner.negotiate(
                    plan, specs, post=lambda s, t: self.bus.post(channel, s, t, kind=MessageKind.CHAT, task_id=root.id))
            self.bus.post(channel, self.manager_id, self._plan_text(plan), kind=MessageKind.SYSTEM, task_id=root.id)

            self._execute(self._create_tasks(plan.subtasks, root, store), store, channel)

            failed = [t for t in store.children(root.id) if t.status == TaskStatus.FAILED]
            if failed and self.replan_on_failure:
                done = [f"- {t.goal}: {(t.result or '')[:300]}" for t in store.children(root.id)
                        if t.status == TaskStatus.SUCCEEDED]
                fails = [f"- {t.goal}: {t.error}" for t in failed]
                extra = self.planner.replan(goal, done, fails)
                if extra:
                    replanned = True
                    self.bus.post(channel, self.manager_id, "Re-planning after failure:\n" +
                                  "\n".join(f"  {s.id}. [{s.assignee}] {s.goal}" for s in extra),
                                  kind=MessageKind.SYSTEM, task_id=root.id)
                    new_tasks = self._create_tasks(extra, root, store)
                    self._execute(new_tasks, store, channel)
                    if all(t.status == TaskStatus.SUCCEEDED for t in new_tasks):
                        for t in failed:  # recovered: superseded by the re-plan
                            t.metadata["superseded"] = True
                            store.update(t)

            subtasks = store.children(root.id)
            unresolved = [t for t in subtasks if t.status != TaskStatus.SUCCEEDED and not t.metadata.get("superseded")]
            final = self._synthesize(goal, subtasks)
            root.status = TaskStatus.FAILED if unresolved else TaskStatus.SUCCEEDED
            root.result = final
        except Exception as e:  # anything unexpected -> failed run, never a crash
            root.status, root.error = TaskStatus.FAILED, f"{type(e).__name__}: {e}"

        subtasks = store.children(root.id)
        ok = [t for t in subtasks if t.status == TaskStatus.SUCCEEDED]
        root.finished_at = time.time()
        store.update(root)
        self.bus.post(channel, self.manager_id, final or f"Run failed: {root.error}",
                      kind=MessageKind.TASK_RESULT, task_id=root.id)
        return RunReport(
            run_id=run_id, goal=goal, success=root.status == TaskStatus.SUCCEEDED, final_answer=final,
            subtasks_total=len(subtasks), subtasks_succeeded=len(ok), duration_s=root.finished_at - t0,
            tasks=[t.model_dump(mode="json") for t in store.tasks.values()],
            plan=plan.model_dump() if plan else None, error=root.error,
            retries=sum(t.metadata.get("attempts", 1) - 1 for t in subtasks), replanned=replanned,
        )

    # ------------------------------------------------------------------ execution
    def _create_tasks(self, subtasks: list[SubtaskPlan], root: Task, store: TaskStore) -> list[Task]:
        local: dict[str, Task] = {}
        for s in subtasks:
            local[s.id] = store.add(Task(goal=s.goal, parent_id=root.id, assignee=s.assignee,
                                         created_by=self.manager_id, metadata={"local_id": s.id}))
        for s in subtasks:  # map local dependency ids -> real task ids
            local[s.id].depends_on = [local[d].id for d in s.depends_on if d in local]
        return list(local.values())

    def _execute(self, tasks: list[Task], store: TaskStore, channel: str) -> None:
        """Run tasks in dependency waves; each wave runs in parallel (if enabled)."""
        pending = list(tasks)
        ids = {t.id for t in tasks}
        finished: set[str] = set()
        while pending:
            ready = [t for t in pending if all(d in finished or d not in ids for d in t.depends_on)]
            if not ready:  # dependency cycle -> break it by running the first one
                ready = pending[:1]
            for t in ready:
                pending.remove(t)
            if self.parallel and len(ready) > 1:
                with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                    list(pool.map(lambda t: self._run_subtask(t, store, channel), ready))
            else:
                for t in ready:
                    self._run_subtask(t, store, channel)
            finished.update(t.id for t in ready)

    def _run_subtask(self, task: Task, store: TaskStore, channel: str) -> None:
        try:
            deps = [store.get(d) for d in task.depends_on]
            failed = [d for d in deps if d.status != TaskStatus.SUCCEEDED]
            if failed:
                task.status, task.error = TaskStatus.FAILED, f"Dependency failed: {[d.id for d in failed]}"
                store.update(task)
                return
            context = self._dependency_context(task, deps)
            agent = self.registry.get(task.assignee)
            task.status, task.started_at = TaskStatus.RUNNING, time.time()
            store.update(task)
            self.bus.post(channel, self.manager_id, f"@{task.assignee} {task.goal}",
                          kind=MessageKind.TASK_ASSIGN, task_id=task.id)

            out: AgentOutcome | None = None
            attempts = 0
            for attempt in range(1 + max(0, self.max_retries)):
                attempts = attempt + 1
                ctx = context
                if out is not None:  # retry with the previous failure as context
                    ctx += (f"\n\n## Your previous attempt FAILED\nError: {out.error}\nAnswer: {out.answer}\n"
                            "Try a different approach.")
                    self.bus.post(channel, self.manager_id, f"Retrying {task.id} (attempt {attempts})",
                                  kind=MessageKind.SYSTEM, task_id=task.id)
                out = agent.run_task(task, context=ctx, channel=channel)
                if out.success:
                    break

            task.finished_at = time.time()
            task.status = TaskStatus.SUCCEEDED if out and out.success else TaskStatus.FAILED
            task.result, task.error = (out.answer, out.error) if out else ("", "no outcome")
            task.artifacts = sorted(self._artifacts_from_log(task))
            task.metadata.update({"steps": out.steps if out else 0, "attempts": attempts,
                                  "tool_calls": out.tool_calls if out else []})
        except Exception as e:  # keep one broken sub-task from killing the run
            task.status, task.error, task.finished_at = TaskStatus.FAILED, f"{type(e).__name__}: {e}", time.time()
        store.update(task)

    def _dependency_context(self, task: Task, deps: list[Task]) -> str:
        parts = []
        for d in deps:  # pass results + share produced files into the assignee's inbox
            shared = []
            if d.assignee != task.assignee:
                for art in d.artifacts:
                    try:
                        rel = str(self._rel_to_workspace(d.assignee, art))
                        shared.append(self.sandbox.share(d.assignee, rel, task.assignee).name)
                    except Exception:
                        continue
            files = f" (files in inbox/{d.assignee}/: {', '.join(shared)})" if shared else ""
            parts.append(f"### Result from {d.assignee} for '{d.goal[:80]}'{files}\n{d.result}")
        return "\n\n".join(parts)

    def _artifacts_from_log(self, task: Task) -> set[str]:
        agent = self.registry.get(task.assignee)
        return {a for entry in list(agent.gateway.call_log) if entry.get("task") == task.id and entry.get("ok")
                for a in entry.get("artifacts", [])}

    def _rel_to_workspace(self, agent_id: str, path: str) -> Path:
        return Path(path).resolve().relative_to(self.sandbox.workspace(agent_id).resolve())

    # ------------------------------------------------------------------ helpers
    def _synthesize(self, goal: str, subtasks: list[Task]) -> str:
        if len(subtasks) == 1 and subtasks[0].result:
            return subtasks[0].result
        results = "\n\n".join(
            f"### [{t.status.value}] {t.assignee}: {t.goal}\n{t.result or t.error}" for t in subtasks)
        try:
            return self.llm.chat([{"role": "user", "content": SYNTH_PROMPT.format(goal=goal, results=results)}]).content
        except Exception:
            return results

    @staticmethod
    def _plan_text(plan: Plan) -> str:
        lines = ["Plan:"]
        for s in plan.subtasks:
            dep = f" (after {', '.join(s.depends_on)})" if s.depends_on else ""
            lines.append(f"  {s.id}. [{s.assignee}] {s.goal}{dep}")
        return "\n".join(lines)
