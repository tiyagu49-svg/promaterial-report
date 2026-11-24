"""Routes human group-chat messages to the right place.

  - "@coder do X"              -> directly to that agent
  - small request, no mention  -> LLM picks the single best agent (if llm routing is on)
  - real multi-step goal        -> None, meaning "let the controller plan it with the whole team"
"""
from __future__ import annotations

import re
from typing import Any

from ..agents.registry import AgentRegistry

_MENTION = re.compile(r"^@([\w-]+)[\s,:]+(.*)$", re.S)

ROUTE_PROMPT = """You route messages in a multi-agent team chat.
Agents:
{roster}

Message from the human:
\"\"\"{text}\"\"\"

If ONE agent can fully handle it alone in a few steps (a question, a single file, a single script),
answer with that agent's id. If it needs several specialists or several steps (research AND
writing, code AND report, ...), answer "team".
Return a json object: {{"route": "<agent id or team>", "reason": "<short>"}}"""


class Router:
    def __init__(self, registry: AgentRegistry, llm: Any = None):
        self.registry = registry
        self.llm = llm
        self.last_reason: str = ""

    def parse_mention(self, text: str) -> tuple[str | None, str]:
        """Return (agent_id, message) if the text starts with @agent, else (None, text)."""
        m = _MENTION.match(text.strip())
        if m and self.registry.has(m.group(1)):
            return m.group(1), m.group(2).strip()
        return None, text

    def route(self, text: str) -> tuple[str | None, str]:
        """(agent_id, message) for a single agent, or (None, text) for a team plan."""
        agent_id, msg = self.parse_mention(text)
        if agent_id or self.llm is None:
            return agent_id, msg
        try:
            data = self.llm.chat_json([{"role": "user", "content": ROUTE_PROMPT.format(
                roster=self.registry.roster_text(), text=text[:2000])}], temperature=0.0, max_tokens=300)
            route = str(data.get("route", "team")).strip().lower()
            self.last_reason = str(data.get("reason", ""))
            if route != "team" and self.registry.has(route):
                return route, text
        except Exception as e:
            self.last_reason = f"routing failed ({e}); using team plan"
        return None, text

    def resolve(self, preferred: str | None, fallback: str) -> str:
        return preferred if preferred and self.registry.has(preferred) else fallback
