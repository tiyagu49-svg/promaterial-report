"""Creates and isolates private per-agent workspaces.

Current (baseline) isolation: each agent gets runtime/agents/<id>/workspace and every path
an agent touches is resolved *inside* that folder (no "../" escapes, no absolute paths).

TODO(Member 3 - JI Guangning): stronger isolation — run code in a Docker container per agent
(docker/Dockerfile.agent) with the workspace mounted, no network by default, CPU/mem limits;
keep this class's public API the same so tools don't change.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class SandboxViolation(PermissionError):
    pass


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    backend: str = "local"


class SandboxManager:
    def __init__(self, root: Path, settings=None):
        self.root = Path(root) / "agents"
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = settings

    def agent_dir(self, agent_id: str) -> Path:
        d = self.root / agent_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def workspace(self, agent_id: str) -> Path:
        ws = self.agent_dir(agent_id) / "workspace"
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    def resolve(self, agent_id: str, rel_path: str) -> Path:
        """Map an agent-supplied path to a real path inside its workspace, or raise."""
        ws = self.workspace(agent_id).resolve()
        p = (ws / rel_path.lstrip("/")).resolve()
        if p != ws and ws not in p.parents:
            raise SandboxViolation(f"Path '{rel_path}' escapes the workspace of agent '{agent_id}'.")
        return p

    def share(self, from_agent: str, rel_path: str, to_agent: str) -> Path:
        """Explicitly copy a file from one agent's workspace into another's `inbox/`.
        This is the ONLY sanctioned way data crosses sandboxes."""
        import shutil

        src = self.resolve(from_agent, rel_path)
        dst = self.resolve(to_agent, f"inbox/{from_agent}/{src.name}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return dst

    def run_command(self, agent_id: str, argv: list[str], timeout: int = 60, cwd: str = ".") -> CommandResult:
        """Run argv in the agent's workspace. Baseline: plain local subprocess.
        TODO(Member 3 - JI Guangning): stripped env + docker backend."""
        if argv and argv[0] == "python":
            argv = [sys.executable, *argv[1:]]
        try:
            p = subprocess.run(argv, cwd=self.resolve(agent_id, cwd), capture_output=True, text=True, timeout=timeout)
            return CommandResult(p.returncode, p.stdout, p.stderr)
        except subprocess.TimeoutExpired:
            return CommandResult(-1, "", "timeout", timed_out=True)
