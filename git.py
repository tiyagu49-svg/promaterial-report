"""Version-control tools: commit and push from the agent's workspace.

TODO(Member 3 - JI Guangning): implement.
  - git_commit: `git init` the workspace (or a sub-folder) if needed, `git add -A`, `git commit -m`.
  - git_push: push to a remote given by the task/human. Use GITHUB_TOKEN from env for auth
    (https://<token>@github.com/owner/repo.git) and NEVER echo the token in tool output.
  Push is `critical = True` so the human approves it (already set below).
"""
from __future__ import annotations

from ..core.schemas import ToolResult
from .gateway import Tool, ToolContext


class GitCommit(Tool):
    name = "git_commit"
    description = "Stage all changes in a workspace folder and create a git commit."
    parameters = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "repo_path": {"type": "string", "default": ".", "description": "Folder inside your workspace."},
        },
        "required": ["message"],
    }

    def run(self, ctx: ToolContext, message: str, repo_path: str = ".") -> ToolResult:
        return ToolResult(ok=False, error="git_commit is not implemented yet (Member 3 - JI Guangning).")


class GitPush(Tool):
    name = "git_push"
    description = "Push committed changes to a GitHub remote. Requires human approval."
    parameters = {
        "type": "object",
        "properties": {
            "remote_url": {"type": "string", "description": "https://github.com/owner/repo.git"},
            "branch": {"type": "string", "default": "main"},
            "repo_path": {"type": "string", "default": "."},
        },
        "required": ["remote_url"],
    }
    critical = True

    def describe_call(self, args):
        return f"PUSH '{args.get('repo_path', '.')}' to {args.get('remote_url')} ({args.get('branch', 'main')})"

    def run(self, ctx: ToolContext, remote_url: str, branch: str = "main", repo_path: str = ".") -> ToolResult:
        return ToolResult(ok=False, error="git_push is not implemented yet (Member 3 - JI Guangning).")
