"""Sandbox file operations on plain-text files (.md / .txt / code).

Baseline implementation so agents can work end-to-end.
TODO(Member 3 - JI Guangning): add tests, size limits, append mode, search-in-files, nicer listings.
"""
from __future__ import annotations

from ..core.schemas import ToolResult
from .gateway import Tool, ToolContext

_PATH = {"type": "string", "description": "Path relative to your workspace, e.g. 'notes/plan.md'."}


class ReadFile(Tool):
    name = "read_file"
    description = "Read a text file from your workspace."
    parameters = {"type": "object", "properties": {"path": _PATH}, "required": ["path"]}

    def run(self, ctx: ToolContext, path: str) -> ToolResult:
        p = ctx.sandbox.resolve(ctx.agent_id, path)
        if not p.is_file():
            return ToolResult(ok=False, error=f"File not found: {path}")
        return ToolResult(ok=True, output=p.read_text(errors="replace"))


class WriteFile(Tool):
    name = "write_file"
    description = "Create or overwrite a text file in your workspace (use .md/.txt for documents)."
    parameters = {
        "type": "object",
        "properties": {"path": _PATH, "content": {"type": "string"}},
        "required": ["path", "content"],
    }

    def run(self, ctx: ToolContext, path: str, content: str) -> ToolResult:
        p = ctx.sandbox.resolve(ctx.agent_id, path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return ToolResult(ok=True, output=f"Wrote {len(content)} chars to {path}", artifacts=[str(p)])


class UpdateFile(Tool):
    name = "update_file"
    description = "Replace an exact snippet of text in an existing file with new text."
    parameters = {
        "type": "object",
        "properties": {"path": _PATH, "old": {"type": "string"}, "new": {"type": "string"}},
        "required": ["path", "old", "new"],
    }

    def run(self, ctx: ToolContext, path: str, old: str, new: str) -> ToolResult:
        p = ctx.sandbox.resolve(ctx.agent_id, path)
        if not p.is_file():
            return ToolResult(ok=False, error=f"File not found: {path}")
        text = p.read_text()
        if old not in text:
            return ToolResult(ok=False, error="The 'old' snippet was not found in the file.")
        p.write_text(text.replace(old, new, 1))
        return ToolResult(ok=True, output=f"Updated {path}", artifacts=[str(p)])


class DeleteFile(Tool):
    name = "delete_file"
    description = "Delete a file from your workspace. Requires human approval."
    parameters = {"type": "object", "properties": {"path": _PATH}, "required": ["path"]}
    critical = True

    def describe_call(self, args):
        return f"DELETE file '{args.get('path')}'"

    def run(self, ctx: ToolContext, path: str) -> ToolResult:
        p = ctx.sandbox.resolve(ctx.agent_id, path)
        if not p.is_file():
            return ToolResult(ok=False, error=f"File not found: {path}")
        p.unlink()
        return ToolResult(ok=True, output=f"Deleted {path}")


class ListFiles(Tool):
    name = "list_files"
    description = "List files in your workspace (recursively)."
    parameters = {"type": "object", "properties": {"path": {**_PATH, "default": "."}}}

    def run(self, ctx: ToolContext, path: str = ".") -> ToolResult:
        root = ctx.sandbox.resolve(ctx.agent_id, path)
        ws = ctx.workspace.resolve()
        files = [str(p.relative_to(ws)) for p in sorted(root.rglob("*")) if p.is_file()]
        return ToolResult(ok=True, output="\n".join(files) or "(empty)")


class AppendFile(Tool):
    name = "append_file"
    description = "Append text to the end of a file (creates it if missing)."
    parameters = {"type": "object", "properties": {"path": _PATH, "content": {"type": "string"}},
                  "required": ["path", "content"]}

    def run(self, ctx: ToolContext, path: str, content: str) -> ToolResult:
        return ToolResult(ok=False, error="append_file is not implemented yet (Member 3 - JI Guangning).")


class SearchFiles(Tool):
    name = "search_files"
    description = "Search text (regex) in the files of your workspace."
    parameters = {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}

    def run(self, ctx: ToolContext, pattern: str, path: str = ".") -> ToolResult:
        return ToolResult(ok=False, error="search_files is not implemented yet (Member 3 - JI Guangning).")
