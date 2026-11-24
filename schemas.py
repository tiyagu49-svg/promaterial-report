"""Shared data models for tasks, messages, and tool I/O.

These are the CONTRACTS between team members' modules. Change them only after
agreeing with the team (and update docs/interfaces.md).
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


# ----------------------------------------------------------------------------- messages
class MessageKind(str, Enum):
    CHAT = "chat"                  # normal conversation
    TASK_ASSIGN = "task_assign"    # a task handed to an agent
    TASK_RESULT = "task_result"    # an agent reporting a result
    QUESTION = "question"          # HITL: agent asks human for clarification
    APPROVAL_REQUEST = "approval_request"  # HITL: agent asks permission for a critical action
    SYSTEM = "system"              # system notices / status updates


class Message(BaseModel):
    """One message on the bus.

    channel naming:
      - "dm:<agent_id>"   private 1-on-1 chat between the human and that agent
      - "group:<name>"    multi-agent + human group chat (default group: "group:main")
    """
    id: str = Field(default_factory=lambda: new_id("m_"))
    channel: str
    sender: str                    # agent id or "human" or "system"
    content: str
    kind: MessageKind = MessageKind.CHAT
    task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    ts: float = Field(default_factory=time.time)


# ----------------------------------------------------------------------------- tasks
class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Task(BaseModel):
    id: str = Field(default_factory=lambda: new_id("t_"))
    goal: str
    parent_id: str | None = None
    assignee: str | None = None            # agent id
    created_by: str = "human"
    depends_on: list[str] = Field(default_factory=list)   # task ids
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    error: str | None = None
    artifacts: list[str] = Field(default_factory=list)    # file paths produced
    started_at: float | None = None
    finished_at: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration_s(self) -> float | None:
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return None


class SubtaskPlan(BaseModel):
    """One item of a plan produced by the planner."""
    id: str                       # short local id, e.g. "s1"
    goal: str
    assignee: str                 # agent id
    depends_on: list[str] = Field(default_factory=list)   # local ids


class Plan(BaseModel):
    goal: str
    subtasks: list[SubtaskPlan]
    needs_clarification: str | None = None   # if set, ask the human this before running


# ----------------------------------------------------------------------------- tools
class ToolResult(BaseModel):
    ok: bool
    output: str = ""
    error: str | None = None
    artifacts: list[str] = Field(default_factory=list)

    def to_llm(self, max_chars: int = 6000) -> str:
        text = self.output if self.ok else f"ERROR: {self.error}\n{self.output}"
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n...[truncated {len(text) - max_chars} chars]"
        return text


# ----------------------------------------------------------------------------- agent outcome
class AgentOutcome(BaseModel):
    """What Agent.run_task returns."""
    task_id: str
    agent_id: str
    success: bool
    answer: str
    steps: int
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
