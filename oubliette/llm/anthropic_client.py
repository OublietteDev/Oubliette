"""Real model adapter (decision D4: provider-native structured output).

Talks to the Anthropic Messages API over the stdlib (urllib) — no third-party
HTTP dependency. It forces a single tool call whose input schema IS the requested
Pydantic model, which is the provider-native way to get validated structured
output without parsing prose. The blocking HTTP call is run in a thread so the
`LLMClient.complete` coroutine stays honestly async (decision D2).

Used for real play when ANTHROPIC_API_KEY is set. Kept thin behind the
`LLMClient` protocol so it stays swappable.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from typing import TypeVar

from pydantic import BaseModel

from .client import Msg, TextSink
from .streaming import extract_string_field

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-sonnet-4-5"
_API_URL = "https://api.anthropic.com/v1/messages"
_RETRYABLE = {429, 500, 502, 503, 529}


class AnthropicLLMClient:
    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None,
                 max_tokens: int = 1024, max_retries: int = 3) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._model = model
        self._max_tokens = max_tokens
        self._max_retries = max_retries

    async def complete(self, *, system: str, messages: list[Msg], schema: type[T],
                       on_text: TextSink | None = None) -> T:
        payload = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "tools": [{
                "name": "emit",
                "description": f"Return the {schema.__name__} for this turn.",
                "input_schema": schema.model_json_schema(),
            }],
            "tool_choice": {"type": "tool", "name": "emit"},
        }
        if on_text is not None:
            payload["stream"] = True
            inp = await asyncio.to_thread(self._post_stream, payload, on_text)
            return schema.model_validate(inp)

        data = await asyncio.to_thread(self._post, payload)
        for block in data.get("content", []):
            if block.get("type") == "tool_use":
                return schema.model_validate(block["input"])
        raise RuntimeError("model did not emit the forced structured-output tool call")

    def _post_stream(self, payload: dict, on_text: TextSink) -> dict:
        """Stream the forced tool_use input, emitting `narration` deltas as they
        arrive, and return the fully-parsed tool input."""
        body = json.dumps(payload).encode()
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        req = urllib.request.Request(_API_URL, data=body, method="POST", headers=headers)
        acc = ""        # accumulated tool-input JSON
        emitted = ""    # narration emitted so far
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw in resp:                       # SSE lines, as they arrive
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        evt = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if evt.get("type") == "content_block_delta":
                        delta = evt.get("delta", {})
                        if delta.get("type") == "input_json_delta":
                            acc += delta.get("partial_json", "")
                            val = extract_string_field(acc, "narration")
                            if len(val) > len(emitted):
                                on_text(val[len(emitted):])
                                emitted = val
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"Anthropic API HTTP {e.code}: {detail}") from e
        try:
            return json.loads(acc) if acc else {}
        except json.JSONDecodeError as e:
            raise RuntimeError(f"streamed tool input was not valid JSON: {acc[:200]}") from e

    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload).encode()
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        last_err: Exception | None = None
        for attempt in range(self._max_retries):
            req = urllib.request.Request(_API_URL, data=body, method="POST", headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                if e.code in _RETRYABLE and attempt < self._max_retries - 1:
                    last_err = RuntimeError(f"HTTP {e.code}: {detail}")
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Anthropic API HTTP {e.code}: {detail}") from e
            except urllib.error.URLError as e:
                last_err = e
                if attempt < self._max_retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Anthropic API connection error: {e}") from e
        raise RuntimeError(f"Anthropic API failed after retries: {last_err}")
