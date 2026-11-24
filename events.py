"""Message bus for agent communication: 1-on-1 DMs, group chats, task updates, and HITL signals.

Simple in-process pub/sub. Every message is also appended to runtime/logs/messages.jsonl
so runs can be inspected and replayed for the report.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from pathlib import Path
from typing import Callable

from .schemas import Message

Subscriber = Callable[[Message], None]

DEFAULT_GROUP = "group:main"


def dm_channel(agent_id: str) -> str:
    return f"dm:{agent_id}"


def group_channel(name: str = "main") -> str:
    return f"group:{name}"


class MessageBus:
    def __init__(self, log_path: Path | None = None):
        self._subs: dict[str, list[Subscriber]] = defaultdict(list)
        self._history: dict[str, list[Message]] = defaultdict(list)
        self._members: dict[str, set[str]] = defaultdict(set)  # group channel -> member ids
        self._lock = threading.RLock()
        self._log_path = log_path
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)

    # -- membership ---------------------------------------------------------
    def join(self, channel: str, member_id: str) -> None:
        with self._lock:
            self._members[channel].add(member_id)

    def members(self, channel: str) -> set[str]:
        return set(self._members.get(channel, set()))

    # -- pub/sub ------------------------------------------------------------
    def subscribe(self, channel: str, fn: Subscriber) -> None:
        """channel="*" receives every message."""
        with self._lock:
            self._subs[channel].append(fn)

    def publish(self, msg: Message) -> Message:
        with self._lock:
            self._history[msg.channel].append(msg)
            subs = list(self._subs.get(msg.channel, [])) + list(self._subs.get("*", []))
            if self._log_path:
                with self._log_path.open("a") as f:
                    f.write(msg.model_dump_json() + "\n")
        for fn in subs:
            try:
                fn(msg)
            except Exception as e:  # a bad subscriber must never crash the run
                print(f"[bus] subscriber error on {msg.channel}: {e}")
        return msg

    def post(self, channel: str, sender: str, content: str, **kw) -> Message:
        return self.publish(Message(channel=channel, sender=sender, content=content, **kw))

    def history(self, channel: str, limit: int | None = None) -> list[Message]:
        with self._lock:
            msgs = list(self._history.get(channel, []))
        return msgs[-limit:] if limit else msgs

    def transcript(self, channel: str, limit: int = 20) -> str:
        """Readable recent history, handy for putting chat context into a prompt."""
        return "\n".join(f"[{m.sender}] {m.content}" for m in self.history(channel, limit))
