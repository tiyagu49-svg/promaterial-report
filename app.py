"""Application bootstrap: build settings, LLM, bus, sandbox, tools, agents, and the controller.

    from mas_platform.app import build_platform
    p = build_platform()                    # interactive (CLI human)
    p = build_platform(human_mode="auto_approve", llm=MockLLMClient(...))   # tests / eval
    report = p.controller.run_goal("Write a haiku about agents to haiku.md")
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agents import Agent, AgentRegistry
from .core.events import DEFAULT_GROUP, MessageBus
from .human import AutoHuman, CLIHuman
from .llm import make_llm_client
from .orchestration import Controller, Planner, Router
from .sandbox import SandboxManager
from .settings import Settings, load_settings
from .tools import ToolGateway, default_tools


@dataclass
class Platform:
    settings: Settings
    llm: Any
    bus: MessageBus
    sandbox: SandboxManager
    gateway: ToolGateway
    registry: AgentRegistry
    router: Router
    controller: Controller
    human: Any

    def handle_group_message(self, text: str):
        """Group chat entry point: '@agent msg' talks to one agent, anything else is a team goal."""
        agent_id, msg = self.router.route(text)
        if agent_id:
            self.bus.post(DEFAULT_GROUP, "human", text)
            from .core.schemas import Task
            return self.registry.get(agent_id).run_task(Task(goal=msg, assignee=agent_id), channel=DEFAULT_GROUP)
        return self.controller.run_goal(text)


def build_platform(settings: Settings | None = None, llm: Any = None, human_mode: str | None = None) -> Platform:
    settings = settings or load_settings()
    llm = llm or make_llm_client(settings.llm)
    root = settings.runtime_path
    bus = MessageBus(log_path=root / "logs" / "messages.jsonl")
    sandbox = SandboxManager(root, settings=settings.sandbox)
    gateway = ToolGateway(default_tools())

    mode = human_mode or settings.human.mode
    human = AutoHuman(bus) if mode == "auto_approve" else CLIHuman(bus, settings=settings.human)

    if not settings.agents:
        raise ValueError("No agents configured in configs/agents.yaml")
    team = {s.id: s for s in settings.agents}
    registry = AgentRegistry()
    for spec in settings.agents:
        registry.add(Agent(spec, llm, gateway, sandbox, bus, settings, human=human, team=team))
        bus.join(DEFAULT_GROUP, spec.id)
    bus.join(DEFAULT_GROUP, "human")

    manager_id = "manager" if registry.has("manager") else registry.ids()[0]
    planner = Planner(llm, registry.roster_text(), registry.ids(), fallback_agent=manager_id)
    controller = Controller(registry, planner, bus, sandbox, root / "checkpoints", llm, manager_id,
                            human=human, settings=settings)
    for agent in registry.all():
        agent.delegate_fn = controller.delegate

    router = Router(registry, llm=llm if settings.orchestration.llm_routing else None)
    return Platform(settings, llm, bus, sandbox, gateway, registry, router, controller, human)
