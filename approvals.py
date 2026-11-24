"""Human-in-the-loop: agents pause to ask for clarification or for permission before critical actions.

- Every question/approval is posted on the message bus so it appears in the chat log.
- Every approval decision is appended to an audit list (`decisions`) for the report.
- CLIHuman supports an approval timeout (human.approval_timeout_s): no answer -> deny (safe default).
- Which tools are critical is configured in configs/system.yaml (human.critical_tools) and
  enforced by the ToolGateway.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Any, Protocol

from ..core.events import DEFAULT_GROUP, MessageBus
from ..core.schemas import MessageKind


class HumanInterface(Protocol):
    def ask(self, agent_id: str, question: str, channel: str = DEFAULT_GROUP) -> str: ...
    def approve(self, agent_id: str, action: str, channel: str = DEFAULT_GROUP) -> bool: ...


_input_lock = threading.Lock()  # parallel agents must not read stdin at the same time


def _timed_input(prompt: str, timeout_s: int) -> str | None:
    """input() with an optional timeout. Returns None on timeout."""
    if not timeout_s:
        return input(prompt)
    q: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: q.put(input(prompt)), daemon=True).start()
    try:
        return q.get(timeout=timeout_s)
    except queue.Empty:
        return None


class CLIHuman:
    """Blocks on stdin. Used by the interactive CLI."""

    def __init__(self, bus: MessageBus | None = None, settings: Any = None):
        self.bus = bus
        self.timeout_s = int(getattr(settings, "approval_timeout_s", 0) or 0)
        self.decisions: list[dict[str, Any]] = []

    def _log(self, channel: str, sender: str, text: str, kind: MessageKind) -> None:
        if self.bus:
            self.bus.post(channel, sender, text, kind=kind)

    def ask(self, agent_id: str, question: str, channel: str = DEFAULT_GROUP) -> str:
        self._log(channel, agent_id, question, MessageKind.QUESTION)
        with _input_lock:
            answer = (input(f"\n❓ [{agent_id}] asks: {question}\n> ") or "").strip()
        self._log(channel, "human", answer or "(no answer)", MessageKind.CHAT)
        return answer or "(no answer — use your best judgement and state your assumption)"

    def approve(self, agent_id: str, action: str, channel: str = DEFAULT_GROUP) -> bool:
        self._log(channel, agent_id, f"Requesting approval: {action}", MessageKind.APPROVAL_REQUEST)
        suffix = f" (auto-deny in {self.timeout_s}s)" if self.timeout_s else ""
        with _input_lock:
            ans = _timed_input(f"\n⚠️  [{agent_id}] wants to: {action}\nApprove? [y/N]{suffix} ", self.timeout_s)
        ok = (ans or "").strip().lower() in ("y", "yes")
        reason = "timeout" if ans is None else ("approved" if ok else "denied")
        self.decisions.append({"agent": agent_id, "action": action, "approved": ok, "reason": reason, "ts": time.time()})
        self._log(channel, "human", reason, MessageKind.CHAT)
        return ok


class AutoHuman:
    """Non-interactive human for the evaluation harness: approves everything and answers
    questions with a fixed instruction (or from a keyword -> answer dict)."""

    def __init__(self, bus: MessageBus | None = None, approve_all: bool = True,
                 default_answer: str = "No further information is available. Make a reasonable assumption, state it, and continue.",
                 answers: dict[str, str] | None = None):
        self.bus = bus
        self.approve_all = approve_all
        self.default_answer = default_answer
        self.answers = answers or {}
        self.questions_asked: list[tuple[str, str]] = []
        self.approvals_requested: list[tuple[str, str]] = []
        self.decisions: list[dict[str, Any]] = []

    def ask(self, agent_id: str, question: str, channel: str = DEFAULT_GROUP) -> str:
        self.questions_asked.append((agent_id, question))
        if self.bus:
            self.bus.post(channel, agent_id, question, kind=MessageKind.QUESTION)
        for key, ans in self.answers.items():
            if key.lower() in question.lower():
                return ans
        return self.default_answer

    def approve(self, agent_id: str, action: str, channel: str = DEFAULT_GROUP) -> bool:
        self.approvals_requested.append((agent_id, action))
        self.decisions.append({"agent": agent_id, "action": action, "approved": self.approve_all,
                               "reason": "auto", "ts": time.time()})
        if self.bus:
            self.bus.post(channel, agent_id, f"Requesting approval: {action}", kind=MessageKind.APPROVAL_REQUEST)
        return self.approve_all
