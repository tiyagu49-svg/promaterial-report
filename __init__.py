"""Tool implementations agents use to act on the external world."""
from .files import AppendFile, DeleteFile, ListFiles, ReadFile, SearchFiles, UpdateFile, WriteFile
from .gateway import Tool, ToolContext, ToolGateway
from .git import GitCommit, GitPush
from .python_exec import RunPython, RunTests
from .search import FetchUrl, WebSearch


def default_tools() -> list[Tool]:
    return [
        ReadFile(), WriteFile(), UpdateFile(), AppendFile(), DeleteFile(), ListFiles(), SearchFiles(),
        RunPython(), RunTests(), WebSearch(), FetchUrl(), GitCommit(), GitPush(),
    ]


__all__ = ["Tool", "ToolContext", "ToolGateway", "default_tools"]
