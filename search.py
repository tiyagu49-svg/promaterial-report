"""Internet search / data-retrieval tools.

TODO(Member 3 - JI Guangning): implement.
  - web_search: e.g. DuckDuckGo HTML endpoint (no key) or Tavily/SerpAPI if a key is available.
    Return top-k results as "title | url | snippet" lines.
  - fetch_url: GET a page with httpx, strip HTML to readable text (keep it plain text/Markdown),
    truncate to a sane length.
Keep the names/parameters below so configs/agents.yaml keeps working.
"""
from __future__ import annotations

from ..core.schemas import ToolResult
from .gateway import Tool, ToolContext


class WebSearch(Tool):
    name = "web_search"
    description = "Search the internet. Returns a list of results (title, url, snippet)."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    }

    def run(self, ctx: ToolContext, query: str, max_results: int = 5) -> ToolResult:
        return ToolResult(ok=False, error="web_search is not implemented yet (Member 3 - JI Guangning).")


class FetchUrl(Tool):
    name = "fetch_url"
    description = "Download a web page and return its readable text content."
    parameters = {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}

    def run(self, ctx: ToolContext, url: str) -> ToolResult:
        return ToolResult(ok=False, error="fetch_url is not implemented yet (Member 3 - JI Guangning).")
