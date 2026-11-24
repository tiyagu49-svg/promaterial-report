"""LLM API client for DeepSeek / HKGAI (both expose an OpenAI-compatible /chat/completions).

We call the HTTP API directly with httpx (no OpenAI/Anthropic SDKs, per project rules).

Usage:
    client = make_llm_client(settings.llm)
    resp = client.chat([{"role": "user", "content": "hi"}])
    resp.content, resp.tool_calls
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from ..settings import LLMSettings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def assistant_message(self) -> dict[str, Any]:
        """The message to append to history so the next turn sees this response."""
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.raw_arguments or json.dumps(tc.arguments)},
                }
                for tc in self.tool_calls
            ]
        return msg


class LLMError(RuntimeError):
    pass


class LLMFatalError(LLMError):
    """Non-retryable (401 bad key, 400 bad request, ...)."""


class UsageTracker:
    """Accumulates token usage + call counts (useful for the performance report)."""

    def __init__(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_latency_s = 0.0
        self._lock = threading.Lock()

    def add(self, usage: dict[str, int], latency: float) -> None:
        with self._lock:
            self._add(usage, latency)

    def _add(self, usage: dict[str, int], latency: float) -> None:
        self.calls += 1
        self.prompt_tokens += usage.get("prompt_tokens", 0)
        self.completion_tokens += usage.get("completion_tokens", 0)
        self.total_latency_s += latency

    def as_dict(self) -> dict[str, float]:
        return {
            "llm_calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "llm_latency_s": round(self.total_latency_s, 2),
        }


class LLMClient:
    def __init__(self, cfg: LLMSettings):
        if not cfg.api_key:
            raise LLMError("LLM_API_KEY is not set. Put it in .env (see .env.example) or use LLM_PROVIDER=mock.")
        self.cfg = cfg
        self.usage = UsageTracker()
        base = cfg.base_url.rstrip("/")
        if not base.endswith("/v1"):  # HKGAI needs /v1; DeepSeek accepts both
            base += "/v1"
        self._http = httpx.Client(
            base_url=base,
            headers={"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"},
            timeout=cfg.timeout_s,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.cfg.max_tokens,
        }
        if tools:
            payload["tools"] = tools
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_err: Exception | None = None
        for attempt in range(self.cfg.max_retries):
            t0 = time.time()
            try:
                r = self._http.post("/chat/completions", json=payload)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
                if r.status_code >= 400:  # auth / bad request: retrying won't help
                    raise LLMFatalError(f"HTTP {r.status_code} from LLM API: {r.text[:300]}")
                data = r.json()
                resp = self._parse(data)
                self.usage.add(resp.usage, time.time() - t0)
                return resp
            except LLMFatalError:
                raise
            except (httpx.HTTPError, LLMError, ValueError) as e:
                last_err = e
                time.sleep(min(2 ** attempt, 10))
        raise LLMError(f"LLM call failed after {self.cfg.max_retries} attempts: {last_err}")

    def chat_json(self, messages: list[dict[str, Any]], **kw) -> dict[str, Any]:
        """Ask for a JSON object and parse it. Prompt must mention 'json'."""
        resp = self.chat(messages, json_mode=True, **kw)
        return parse_json_loose(resp.content)

    @staticmethod
    def _parse(data: dict[str, Any]) -> LLMResponse:
        choice = data["choices"][0]
        msg = choice.get("message", {})
        calls = []
        for tc in msg.get("tool_calls") or []:
            raw = tc["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {"_raw": raw}
            calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=args, raw_arguments=raw))
        return LLMResponse(
            content=msg.get("content") or "",
            tool_calls=calls,
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage", {}),
            raw=data,
        )


def parse_json_loose(text: str) -> dict[str, Any]:
    """Parse JSON even if the model wrapped it in ```json fences or added prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


class MockLLMClient:
    """Offline stand-in for tests. Pass a `script` function that maps messages -> LLMResponse,
    or a list of canned responses that are returned in order."""

    def __init__(self, script: Callable[[list[dict[str, Any]], Any], LLMResponse] | list[LLMResponse] | None = None):
        self.script = script
        self.usage = UsageTracker()
        self._i = 0

    def chat(self, messages, tools=None, **kw) -> LLMResponse:
        self.usage.add({}, 0.0)
        if callable(self.script):
            return self.script(messages, tools)
        if isinstance(self.script, list) and self._i < len(self.script):
            r = self.script[self._i]
            self._i += 1
            return r
        # default: immediately finish with an echo
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(id="mock", name="finish", arguments={"answer": "[mock] done", "success": True})],
        )

    def chat_json(self, messages, **kw) -> dict[str, Any]:
        return parse_json_loose(self.chat(messages, **kw).content or "{}")


def make_llm_client(cfg: LLMSettings):
    if cfg.provider == "mock":
        return MockLLMClient()
    return LLMClient(cfg)
