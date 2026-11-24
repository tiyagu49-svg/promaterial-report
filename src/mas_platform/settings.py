"""Typed settings loader for env vars and YAML configs (LLM keys, paths, runtime limits)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# multi-agent-platform/ (the folder that holds configs/, src/, runtime/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LLMSettings(BaseModel):
    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-chat"
    temperature: float = 0.2
    max_tokens: int = 4096
    timeout_s: float = 120
    max_retries: int = 3


class RuntimeSettings(BaseModel):
    root_dir: str = "runtime"
    max_agent_steps: int = 15
    max_delegation_depth: int = 2


class HumanSettings(BaseModel):
    mode: str = "cli"                      # cli | auto_approve
    critical_tools: list[str] = Field(default_factory=lambda: ["delete_file", "git_push"])
    approval_timeout_s: int = 0            # 0 = wait forever (CLI); >0 = deny after timeout


class SandboxSettings(BaseModel):
    backend: str = "local"                 # local | docker
    docker_image: str = "mas-agent:latest"
    python_timeout_s: int = 60
    max_file_kb: int = 512
    network: bool = False                  # docker only


class OrchestrationSettings(BaseModel):
    negotiate: bool = True                 # agents accept/decline assignments
    parallel: bool = True                  # run independent sub-tasks concurrently
    max_workers: int = 3
    max_retries: int = 1                   # retries per failed sub-task
    replan_on_failure: bool = True
    llm_routing: bool = True               # router decides single-agent vs team plan


class MemorySettings(BaseModel):
    enabled: bool = True
    top_k: int = 5
    consolidate_every: int = 10            # write playbook.md every N new lessons


class AgentSpec(BaseModel):
    id: str
    role: str
    description: str = ""
    tools: list[str] = Field(default_factory=list)
    system_prompt: str | None = None


class Settings(BaseModel):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    human: HumanSettings = Field(default_factory=HumanSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    orchestration: OrchestrationSettings = Field(default_factory=OrchestrationSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    agents: list[AgentSpec] = Field(default_factory=list)

    @property
    def runtime_path(self) -> Path:
        p = Path(self.runtime.root_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p


def _load_dotenv() -> None:
    """Minimal .env loader (no extra dependency). Looks in project folder, then repo root.
    Existing environment variables win."""
    for candidate in (PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def load_settings(config_dir: str | Path | None = None) -> Settings:
    _load_dotenv()
    cfg_dir = Path(config_dir) if config_dir else PROJECT_ROOT / "configs"
    data = _read_yaml(cfg_dir / "system.yaml")
    data["agents"] = _read_yaml(cfg_dir / "agents.yaml").get("agents", [])

    llm = data.setdefault("llm", {})
    env_map = {
        "LLM_PROVIDER": "provider",
        "LLM_BASE_URL": "base_url",
        "LLM_API_KEY": "api_key",
        "LLM_MODEL": "model",
    }
    for env_key, field in env_map.items():
        if os.environ.get(env_key):
            llm[field] = os.environ[env_key]
    return Settings.model_validate(data)
