"""Registers and looks up agents by id/role for delegation and routing."""
from __future__ import annotations

from .agent import Agent


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def add(self, agent: Agent) -> None:
        self._agents[agent.id] = agent

    def get(self, agent_id: str) -> Agent:
        if agent_id not in self._agents:
            raise KeyError(f"No agent '{agent_id}'. Known: {list(self._agents)}")
        return self._agents[agent_id]

    def has(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def by_role(self, role: str) -> list[Agent]:
        return [a for a in self._agents.values() if a.spec.role.lower() == role.lower()]

    def ids(self) -> list[str]:
        return list(self._agents)

    def all(self) -> list[Agent]:
        return list(self._agents.values())

    def roster_text(self) -> str:
        return "\n".join(f"- {a.id} ({a.spec.role}): {a.spec.description}" for a in self._agents.values())
