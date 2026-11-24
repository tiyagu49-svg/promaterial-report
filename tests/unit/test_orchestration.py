"""Orchestration + HITL tests (LIU Jiayu). Offline, MockLLMClient."""
import json
import threading
import time

from conftest import call
from mas_platform.app import build_platform
from mas_platform.human.approvals import AutoHuman
from mas_platform.llm import LLMResponse, MockLLMClient
from mas_platform.orchestration.planner import Planner
from mas_platform.core.schemas import Plan, SubtaskPlan


def test_negotiation_reassigns_declined_task(settings):
    def script(messages, tools):
        if "wants to assign you" in messages[0]["content"] and "You are writer" in messages[0]["content"]:
            return LLMResponse(content='{"accept": false, "reason": "this is code", "suggest": "coder"}')
        return LLMResponse(content='{"accept": true, "reason": "fits"}')
    p = build_platform(settings=settings, llm=MockLLMClient(script), human_mode="auto_approve")
    plan = Plan(goal="g", subtasks=[SubtaskPlan(id="s1", goal="write code", assignee="writer"),
                                     SubtaskPlan(id="s2", goal="write doc", assignee="writer")])
    out = p.controller.planner.negotiate(plan, {a.id: a.spec for a in p.registry.all()})
    assert [s.assignee for s in out.subtasks] == ["coder", "coder"]


def test_parallel_wave_runs_concurrently(settings):
    plan = ('{"subtasks":[{"id":"s1","goal":"A","assignee":"coder","depends_on":[]},'
            '{"id":"s2","goal":"B","assignee":"writer","depends_on":[]}],"needs_clarification":null}')
    active, peak, lock = [0], [0], threading.Lock()

    def script(messages, tools):
        first = messages[0]["content"]
        if tools is None:
            if "planner" in first:
                return LLMResponse(content=plan)
            if "wants to assign you" in first:
                return LLMResponse(content='{"accept": true}')
            return LLMResponse(content='{"summary":"","lesson":"ok","tags":[]}' if "reviewing" in first else "FINAL")
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.2)
        with lock:
            active[0] -= 1
        return call("finish", answer="done", success=True)

    p = build_platform(settings=settings, llm=MockLLMClient(script), human_mode="auto_approve")
    report = p.controller.run_goal("do A and B")
    assert report.success and report.subtasks_succeeded == 2
    assert peak[0] == 2  # both sub-tasks ran at the same time


def test_retry_then_success(settings):
    attempts = []

    def script(messages, tools):
        first = messages[0]["content"]
        if tools is None:
            if "planner" in first:
                return LLMResponse(content='{"subtasks":[{"id":"s1","goal":"X","assignee":"coder"}]}')
            return LLMResponse(content='{"summary":"","lesson":"retry helps","tags":[]}')
        attempts.append(1)
        ok = len(attempts) > 1
        return call("finish", answer="ok" if ok else "", success=ok)

    p = build_platform(settings=settings, llm=MockLLMClient(script), human_mode="auto_approve")
    report = p.controller.run_goal("x")
    assert report.success and report.retries == 1


def test_router_llm_picks_single_agent(settings):
    llm = MockLLMClient(lambda m, t: LLMResponse(content='{"route": "coder", "reason": "code"}'))
    p = build_platform(settings=settings, llm=llm, human_mode="auto_approve")
    assert p.router.route("print hello in python") == ("coder", "print hello in python")
    assert p.router.route("@writer hi") == ("writer", "hi")


def test_critical_tool_from_config_needs_approval(settings):
    settings.human.critical_tools = ["write_file"]
    human_denies = AutoHuman(approve_all=False)

    def script(messages, tools):
        if tools is None:
            return LLMResponse(content="{}")
        if not any(m["role"] == "tool" for m in messages):
            return call("write_file", path="a.md", content="x")
        return call("finish", answer=messages[-1]["content"], success=False)

    p = build_platform(settings=settings, llm=MockLLMClient(script), human_mode="auto_approve")
    for a in p.registry.all():
        a.human = human_denies
    from mas_platform.core.schemas import Task
    out = p.registry.get("writer").run_task(Task(goal="write"))
    assert "denied" in out.answer and human_denies.decisions[0]["approved"] is False
