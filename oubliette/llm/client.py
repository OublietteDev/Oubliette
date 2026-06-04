"""The LLMClient protocol. Async (decision D2): the edges are async, the core is
sync-pure. `complete` returns a validated instance of the requested schema —
structured output is the contract, so callers never parse free text (§9)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# A sink for streamed narration deltas (text fragments as they generate).
TextSink = Callable[[str], None]


@dataclass
class Msg:
    role: str   # "user" | "assistant"
    content: str


class LLMClient(Protocol):
    async def complete(
        self, *, system: str, messages: list[Msg], schema: type[T],
        on_text: TextSink | None = None,
    ) -> T:
        """Return an instance of `schema`, validated. Provider-native structured
        output behind the scenes (D4). If `on_text` is given, stream the
        `narration` field's text deltas to it as they arrive."""
        ...
