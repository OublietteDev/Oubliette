"""OpenAI-compatible model adapter (the v0.9 provider opening).

One client covers three provider rows: OpenAI itself, Google Gemini (via its
official OpenAI-compatibility endpoint), and local servers (Ollama, LM Studio,
llama.cpp — the industry-standard local surface is this same API). Only the
`base_url`, key, and model name differ.

Mirrors `anthropic_client.py` beat for beat — stdlib urllib, no SDK, the same
two `LLMClient` shapes:

- `complete`: a FORCED function call named `emit` whose parameters ARE the
  requested Pydantic schema — one validated object, retried on a dud.
- `act`: `tool_choice: auto` — narration streams as assistant text deltas,
  state changes ride function calls (arguments arrive as streamed JSON
  fragments, accumulated per tool index).

Deliberate differences from the Anthropic client: no extended thinking (the
`effort` knob is accepted for protocol conformance and ignored — reasoning
control is provider-specific and the DM plays fine without it), and tool
arguments arrive as a JSON *string* rather than an object.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .anthropic_client import _INHERIT, _coerce_input, _tool_name
from .client import ActResult, Msg, TextSink

T = TypeVar("T", bound=BaseModel)

_RETRYABLE = {408, 429, 500, 502, 503, 529}

OPENAI_BASE_URL = "https://api.openai.com/v1"
# Google's official OpenAI-compatibility surface for Gemini.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
# Ollama's default port; LM Studio uses 1234 — the field is editable in the UI.
LOCAL_BASE_URL = "http://localhost:11434/v1"


def _fn_def(model: type[BaseModel]) -> dict:
    """One OpenAI function-tool definition from a Pydantic tool model (the
    `tool` discriminator names the function, so it leaves the schema)."""
    schema = model.model_json_schema()
    schema.get("properties", {}).pop("tool", None)
    req = schema.get("required")
    if isinstance(req, list) and "tool" in req:
        schema["required"] = [r for r in req if r != "tool"]
    return {"type": "function", "function": {
        "name": _tool_name(model),
        "description": (model.__doc__ or "").strip(),
        "parameters": schema,
    }}


def _parse_args(raw: object):
    """Function-call arguments arrive as a JSON string (sometimes already a
    dict from lenient local servers). A malformed string becomes {} — the
    caller's validation/retry handles it."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {}
    return {}


class OpenAICompatClient:
    """`LLMClient` over any OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, model: str, api_key: str | None = None,
                 base_url: str = OPENAI_BASE_URL, max_tokens: int = 2048,
                 max_retries: int = 3, effort: str | None = None) -> None:
        if not model:
            raise RuntimeError("no model name set — enter the model's API id")
        self._model = model
        self._api_key = api_key            # local servers often need none
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._effort = effort              # accepted, ignored (no thinking here)

    # --- LLMClient protocol ---------------------------------------------------

    async def complete(self, *, system: str, messages: list[Msg], schema: type[T],
                       on_text: TextSink | None = None) -> T:
        payload = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": self._messages(system, messages),
            "tools": [{"type": "function", "function": {
                "name": "emit",
                "description": f"Return the {schema.__name__} for this turn.",
                "parameters": schema.model_json_schema(),
            }}],
            "tool_choice": {"type": "function", "function": {"name": "emit"}},
        }
        last_err: Exception | None = None
        for _ in range(self._max_retries):
            data = await asyncio.to_thread(self._post, payload)
            msg = (data.get("choices") or [{}])[0].get("message") or {}
            calls = msg.get("tool_calls") or []
            if not calls:
                last_err = RuntimeError("model did not emit the forced structured-output call")
                continue
            try:
                return _coerce_input(schema, _parse_args(
                    (calls[0].get("function") or {}).get("arguments")))
            except ValidationError as e:
                last_err = e            # dud generation — regenerate and try again
        raise last_err if last_err else RuntimeError("structured-output call failed")

    async def act(self, *, system: str, messages: list[Msg],
                  tools: list[type[BaseModel]], on_text: TextSink | None = None,
                  effort=_INHERIT) -> ActResult:
        by_name = {_tool_name(m): m for m in tools}
        payload = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": self._messages(system, messages),
            "tools": [_fn_def(m) for m in tools],
            "tool_choice": "auto",
        }
        if on_text is not None:
            narration, raw = await asyncio.to_thread(
                self._post_stream_act, {**payload, "stream": True}, on_text)
        else:
            narration, raw = self._collect_act(await asyncio.to_thread(self._post, payload))
        calls: list[BaseModel] = []
        for r in raw:
            model = by_name.get(r["name"])
            if model is not None:
                calls.append(_coerce_input(model, r["input"]))
        return ActResult(narration=narration, tool_calls=calls, thinking=None)

    # --- wire helpers -----------------------------------------------------------

    @staticmethod
    def _messages(system: str, messages: list[Msg]) -> list[dict]:
        """OpenAI shape: the system prompt is messages[0], not a top-level field."""
        return [{"role": "system", "content": system},
                *({"role": m.role, "content": m.content} for m in messages)]

    @staticmethod
    def _collect_act(data: dict) -> tuple[str, list[dict]]:
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        raw = [{"name": (c.get("function") or {}).get("name"),
                "input": _parse_args((c.get("function") or {}).get("arguments"))}
               for c in (msg.get("tool_calls") or [])]
        return msg.get("content") or "", raw

    def _headers(self, streaming: bool = False) -> dict:
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        if streaming:
            headers["accept"] = "text/event-stream"
        return headers

    def _post_stream_act(self, payload: dict, on_text: TextSink) -> tuple[str, list[dict]]:
        """Stream a resolve turn: assistant text deltas go to `on_text` as they
        arrive; tool calls arrive as (index, name?, arguments-fragment) chunks
        accumulated per index. Returns (narration, [{name, input}, ...])."""
        req = urllib.request.Request(self._url, data=json.dumps(payload).encode(),
                                     method="POST", headers=self._headers(streaming=True))
        narration: list[str] = []
        tools: dict[int, dict] = {}      # index -> {"name", "acc"}
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        evt = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = (evt.get("choices") or [{}])[0].get("delta") or {}
                    txt = delta.get("content")
                    if txt:
                        narration.append(txt)
                        on_text(txt)
                    for tc in delta.get("tool_calls") or []:
                        blk = tools.setdefault(tc.get("index", 0), {"name": None, "acc": ""})
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            blk["name"] = fn["name"]
                        blk["acc"] += fn.get("arguments") or ""
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"API HTTP {e.code}: {detail}") from e
        raw = [{"name": tools[i]["name"], "input": _parse_args(tools[i]["acc"])}
               for i in sorted(tools) if tools[i]["name"]]
        return "".join(narration), raw

    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload).encode()
        last_err: Exception | None = None
        for attempt in range(self._max_retries):
            req = urllib.request.Request(self._url, data=body, method="POST",
                                         headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                if e.code in _RETRYABLE and attempt < self._max_retries - 1:
                    last_err = RuntimeError(f"HTTP {e.code}: {detail}")
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"API HTTP {e.code}: {detail}") from e
            except urllib.error.URLError as e:
                last_err = e
                if attempt < self._max_retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"API connection error: {e}") from e
        raise RuntimeError(f"API failed after retries: {last_err}")
