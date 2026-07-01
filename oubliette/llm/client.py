"""The LLMClient protocol. Async (decision D2): the edges are async, the core is
sync-pure. `complete` returns a validated instance of the requested schema —
structured output is the contract, so callers never parse free text (§9)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# A sink for streamed narration deltas (text fragments as they generate).
TextSink = Callable[[str], None]


@dataclass
class Msg:
    role: str   # "user" | "assistant"
    content: str


@dataclass
class ActResult:
    """The DM's resolve turn, restructured (W6): narration is a normal assistant
    TEXT channel (streams token-by-token), and only state changes ride validated
    tool calls (`tool_choice: auto`, not a forced `emit`). `tool_calls` is a list of
    validated tool models (the same `ToolCall` union the dispatcher consumes).
    `thinking` is an optional hidden scratchpad the UI never shows (W4; unused until
    per-turn thinking lands)."""

    narration: str
    tool_calls: list[BaseModel] = field(default_factory=list)
    thinking: str | None = None


class LLMClient(Protocol):
    async def complete(
        self, *, system: str, messages: list[Msg], schema: type[T],
        on_text: TextSink | None = None,
    ) -> T:
        """Return an instance of `schema`, validated. Provider-native structured
        output behind the scenes (D4). Used for the classification (assess) and
        session-notes (wrap) calls, which want one validated object, not a stream."""
        ...

    async def act(
        self, *, system: str, messages: list[Msg], tools: list[type[BaseModel]],
        on_text: TextSink | None = None, effort: str | None = None,
    ) -> ActResult:
        """The resolve turn (W6): the model narrates as streaming assistant text and
        emits 0+ tool calls for state changes. `tools` are the candidate tool models
        (each registered by its `tool` literal); returned `tool_calls` are validated
        instances. If `on_text` is given, narration text deltas stream to it as they
        generate — genuine token-by-token, since narration is no longer trapped in a
        forced tool's JSON. `effort` is the per-turn thinking depth (W4): None disables
        thinking for this turn, otherwise low|medium|high|xhigh|max — the caller sets it
        from the turn's stakes (see Brain.resolve)."""
        ...
