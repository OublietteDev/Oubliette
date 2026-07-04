"""Real model adapter (decision D4: provider-native structured output).

Talks to the Anthropic Messages API over the stdlib (urllib) — no third-party
HTTP dependency. Two call shapes behind the `LLMClient` protocol:

- `complete` (assess + wrap): forces a single tool call whose input schema IS the
  requested Pydantic model — the provider-native way to get one validated object
  without parsing prose.
- `act` (the resolve turn, W6): `tool_choice: auto`, so narration streams as normal
  assistant TEXT (real token-by-token) and only state changes come back as tool
  calls — narration is prose, so it no longer lives inside a forced tool's JSON.

Blocking HTTP runs in a thread so the coroutines stay honestly async (decision D2).
Used for real play when ANTHROPIC_API_KEY is set; kept thin so it stays swappable.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .client import ActResult, Msg, TextSink

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-sonnet-5"
_API_URL = "https://api.anthropic.com/v1/messages"
_RETRYABLE = {429, 500, 502, 503, 529}

# W4 per-turn thinking. claude-sonnet-5 (and the 4.6+ family) take ADAPTIVE thinking —
# `thinking: {type: "adaptive"}` — NOT the old `{type: "enabled", budget_tokens: N}` (that
# 400s). The model decides per turn whether to think, so trivial turns spend no pause while
# a contested adjudication gets a beat. `output_config.effort` is the depth/spend dial
# (low|medium|high|xhigh|max); `low` keeps the pre-narration pause short. `display:
# "summarized"` is what makes the thinking text visible to us at all (default "omitted"
# streams empty thinking blocks) — we log it to the debug channel; the player never sees it.
DEFAULT_EFFORT = "low"

# Sentinel: act(effort=...) omitted → inherit the client's constructed default; passed
# explicitly (including None) → use that value for this one turn. Lets Brain.resolve set
# per-turn effort by stakes while direct callers keep the instance default.
_INHERIT = object()


def _tool_name(model: type[BaseModel]) -> str:
    """The Anthropic tool name for a tool model = its `tool` discriminator literal."""
    return model.model_fields["tool"].default


def _tool_def(model: type[BaseModel]) -> dict:
    """One Anthropic tool definition from a Pydantic tool model. The `tool`
    discriminator identifies the tool via its name, so we drop it from the input
    schema (the model shouldn't have to fill a constant)."""
    schema = model.model_json_schema()
    schema.get("properties", {}).pop("tool", None)
    req = schema.get("required")
    if isinstance(req, list) and "tool" in req:
        schema["required"] = [r for r in req if r != "tool"]
    return {
        "name": _tool_name(model),
        "description": (model.__doc__ or "").strip(),
        "input_schema": schema,
    }


def _coerce_input(schema: type[T], inp: object) -> T:
    """Validate a forced-tool input into `schema`, tolerating a bogus single-key envelope.
    As of 2026-07, claude-sonnet-5 intermittently wraps the tool input under a lone key
    (observed 'parameters' / 'parameter') instead of returning the schema's fields at the top
    level — e.g. `{"parameters": {"intent": …, "tier": …}}` rather than `{"intent": …}`. The
    nested content is otherwise correct, so when the direct shape doesn't validate we unwrap
    ONE such envelope and retry before surfacing the error. A no-op on well-formed input."""
    try:
        return schema.model_validate(inp)
    except ValidationError:
        if isinstance(inp, dict) and len(inp) == 1:
            (only,) = inp.values()
            if isinstance(only, dict):
                return schema.model_validate(only)
        raise


class AnthropicLLMClient:
    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None,
                 max_tokens: int = 2048, max_retries: int = 3,
                 effort: str | None = DEFAULT_EFFORT) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._model = model
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        # Effort level for the resolve turn's adaptive thinking (`act`). None disables
        # thinking entirely; otherwise one of low|medium|high|xhigh|max.
        self._effort = effort

    async def complete(self, *, system: str, messages: list[Msg], schema: type[T],
                       on_text: TextSink | None = None) -> T:
        """Forced structured output for the classification (assess) and session-notes
        (wrap) calls — one validated object, no streaming (`on_text` is accepted for
        protocol conformance but unused; the streaming resolve turn is `act`)."""
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
            # Classification/summarization want no thinking — and a forced tool_choice is
            # incompatible with thinking anyway. Disable it explicitly so sonnet-5 doesn't
            # fall into its adaptive-on default and add an unwanted pause here.
            "thinking": {"type": "disabled"},
        }
        # Sonnet-5 intermittently emits an EMPTY forced call — `emit({})` — which fails
        # validation (e.g. assess needs intent+tier). Unlike the resolve turn (whose loop
        # retries), assess/wrap have no upstream retry, so a single dud would crash the
        # turn. Re-request a few times; a fresh generation almost always comes back valid.
        last_err: Exception | None = None
        for _ in range(self._max_retries):
            data = await asyncio.to_thread(self._post, payload)
            inp = next((b["input"] for b in data.get("content", [])
                        if b.get("type") == "tool_use"), None)
            if inp is None:
                last_err = RuntimeError("model did not emit the forced structured-output tool call")
                continue
            try:
                return _coerce_input(schema, inp)
            except ValidationError as e:
                last_err = e            # empty/partial emit — regenerate and try again
        raise last_err if last_err else RuntimeError("structured-output call failed")

    async def act(self, *, system: str, messages: list[Msg],
                  tools: list[type[BaseModel]], on_text: TextSink | None = None,
                  effort=_INHERIT) -> ActResult:
        """Resolve turn (W6): narration streams as assistant TEXT; state changes come
        back as `tool_choice: auto` tool calls. No forced `emit` — narration is prose,
        so it leaves the validated schema and streams token-by-token for real. `effort`
        is the per-turn thinking depth (W4); omitted → the client default, None → no
        thinking this turn, else low|medium|high|xhigh|max."""
        eff = self._effort if effort is _INHERIT else effort
        by_name = {_tool_name(m): m for m in tools}
        payload = {
            "model": self._model,
            # max_tokens is a CAP, not a spend — thinking + narration + tool JSON all
            # share it, and hitting it truncates SILENTLY (no stop_reason handling),
            # which starves the narration: the model emits its tool calls and the
            # player-facing prose never gets generated (v0.9 playtest: a quest-reveal
            # faction was created with 0 chars of story text). Keep the ceiling high.
            "max_tokens": max(self._max_tokens, 8192),
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "tools": [_tool_def(m) for m in tools],
            "tool_choice": {"type": "auto"},
        }
        if eff is not None:
            # W4 per-turn thinking. `tool_choice: auto` (never forced) is a hard requirement
            # for thinking — which is exactly our resolve shape. Adaptive thinking + effort;
            # `display: summarized` so the reasoning is captured (not empty). High-effort
            # thinking alone can run thousands of tokens, so give it real headroom.
            payload["thinking"] = {"type": "adaptive", "display": "summarized"}
            payload["output_config"] = {"effort": eff}
            payload["max_tokens"] = max(self._max_tokens, 16384)
        if on_text is not None:
            narration, raw, thinking = await asyncio.to_thread(
                self._post_stream_act, {**payload, "stream": True}, on_text)
        else:
            narration, raw, thinking = self._collect_act(await asyncio.to_thread(self._post, payload))
        # Validate each tool_use block into its model (tolerating the sonnet-5 envelope
        # bug). A malformed tool raises ValidationError → the loop retries the turn.
        calls: list[BaseModel] = []
        for r in raw:
            model = by_name.get(r["name"])
            if model is not None:
                calls.append(_coerce_input(model, r["input"]))
        return ActResult(narration=narration, tool_calls=calls, thinking=thinking or None)

    @staticmethod
    def _collect_act(data: dict) -> tuple[str, list[dict], str]:
        """Non-streaming: split a Messages response into (narration text, tool_use blocks,
        thinking text). Thinking is the hidden per-turn scratchpad (W4) — captured, never shown."""
        narration: list[str] = []
        thinking: list[str] = []
        raw: list[dict] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                narration.append(block.get("text", ""))
            elif block.get("type") == "thinking":
                thinking.append(block.get("thinking", ""))
            elif block.get("type") == "tool_use":
                raw.append({"name": block.get("name"), "input": block.get("input", {})})
        return "".join(narration), raw, "".join(thinking)

    def _post_stream_act(self, payload: dict, on_text: TextSink) -> tuple[str, list[dict], str]:
        """Stream a resolve turn: emit assistant TEXT deltas as narration the moment they
        arrive (real token-by-token), accumulate each tool_use block's input JSON, and
        collect any extended-thinking deltas (W4 scratchpad — captured, NEVER sent to
        on_text). Returns (full narration, [{name, input}, ...], thinking text)."""
        body = json.dumps(payload).encode()
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        req = urllib.request.Request(_API_URL, data=body, method="POST", headers=headers)
        blocks: dict[int, dict] = {}     # index -> {"type", "name", "acc"}
        narration: list[str] = []
        thinking: list[str] = []
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw in resp:
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
                    kind = evt.get("type")
                    if kind == "content_block_start":
                        cb = evt.get("content_block", {})
                        blocks[evt.get("index")] = {
                            "type": cb.get("type"), "name": cb.get("name"), "acc": ""}
                    elif kind == "content_block_delta":
                        delta = evt.get("delta", {})
                        dtype = delta.get("type")
                        if dtype == "text_delta":
                            txt = delta.get("text", "")
                            if txt:
                                narration.append(txt)
                                on_text(txt)          # only NARRATION streams to the player
                        elif dtype == "thinking_delta":
                            thinking.append(delta.get("thinking", ""))   # hidden scratchpad
                        elif dtype == "input_json_delta":
                            blk = blocks.get(evt.get("index"))
                            if blk is not None:
                                blk["acc"] += delta.get("partial_json", "")
                        # signature_delta (thinking-block signature) is intentionally ignored:
                        # we don't feed thinking back in a tool loop, so we never replay it.
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"Anthropic API HTTP {e.code}: {detail}") from e
        tool_blocks: list[dict] = []
        for idx in sorted(blocks):
            blk = blocks[idx]
            if blk.get("type") != "tool_use":
                continue
            acc = blk.get("acc") or ""
            try:
                inp = json.loads(acc) if acc else {}
            except json.JSONDecodeError:
                inp = {}
            tool_blocks.append({"name": blk.get("name"), "input": inp})
        return "".join(narration), tool_blocks, "".join(thinking)

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
                # 300s, not 60: the session-wrap notes call hands the model the FULL
                # transcript of a long session — at 60s it can time out, and the swallowed
                # failure sealed a session with EMPTY notes (v0.9 playtest, finding #6).
                with urllib.request.urlopen(req, timeout=300) as resp:
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
