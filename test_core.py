"""Offline tests (no API key needed) using MockLLMClient."""
from __future__ import annotations

import pytest

from mas_platform.app import build_platform
from mas_platform.core.schemas import Task
from mas_platform.llm import LLMResponse, MockLLMClient, ToolCall
from mas_platform.sandbox import SandboxManager, SandboxViolation


def _call(name, **args):
    return LLMResponse(content="", tool_calls=[ToolCall(id=f"c_{name}", name=name, arguments=args)])


def test_sandbox_blocks_escape(tmp_path):
    sb = SandboxManager(tmp_path)
    assert sb.resolve("a", "x/y.md").is_relative_to(sb.workspace("a").resolve())
    with pytest.raises(SandboxViolation):
        sb.resolve("a", "../b/workspace/secret.txt")


def test_agent_writes_file_and_learns(settings):
    def script(messages, tools):
        if tools is None:  # reflection call (json mode, no tools)
            return LLMResponse(content='{"summary":"wrote file","lesson":"keep it short","tags":["file"]}')
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        if not tool_msgs:
            return _call("write_file", path="hello.md", content="# Hello")
        return _call("finish", answer="created hello.md", success=True)

    p = build_platform(settings=settings, llm=MockLLMClient(script), human_mode="auto_approve")
    writer = p.registry.get("writer")
    out = writer.run_task(Task(goal="write hello.md", assignee="writer"))
    assert out.success
    assert (writer.workspace / "hello.md").read_text() == "# Hello"
    assert not (p.registry.get("coder").workspace / "hello.md").exists()  # isolation
    assert writer.memory.all()[0].lesson == "keep it short"


def test_permission_denied_for_unlisted_tool(settings):
    def script(messages, tools):
        if tools is None:
            return LLMResponse(content="{}")
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        if not tool_msgs:
            return _call("run_python", code="print(1)")  # writer may not run code
        return _call("finish", answer=tool_msgs[-1]["content"], success=False)

    p = build_platform(settings=settings, llm=MockLLMClient(script), human_mode="auto_approve")
    out = p.registry.get("writer").run_task(Task(goal="x"))
    assert "not permitted" in out.answer


def test_controller_runs_plan_with_dependency(settings):
    plan = ('{"subtasks":[{"id":"s1","goal":"make data","assignee":"coder","depends_on":[]},'
            '{"id":"s2","goal":"write report","assignee":"writer","depends_on":["s1"]}],'
            '"needs_clarification":null}')

    def script(messages, tools):
        first = messages[0]["content"]
        if tools is None:
            if "planner" in first:
                return LLMResponse(content=plan)
            if "finished working" in first:
                return LLMResponse(content="FINAL")
            return LLMResponse(content='{"summary":"","lesson":"ok","tags":[]}')
        if not any(m["role"] == "tool" for m in messages):
            return _call("write_file", path="out.txt", content="data")
        return _call("finish", answer="done", success=True)

    p = build_platform(settings=settings, llm=MockLLMClient(script), human_mode="auto_approve")
    report = p.controller.run_goal("make data then report")
    assert report.success and report.subtasks_total == 2 and report.subtasks_succeeded == 2
    assert report.final_answer == "FINAL"
    # coder's file was shared into writer's inbox because s2 depends on s1
    assert (p.registry.get("writer").workspace / "inbox" / "coder" / "out.txt").exists()
