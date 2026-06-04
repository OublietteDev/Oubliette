"""Real model adapter (decision D4: provider-native structured output).

Used for actual play when ANTHROPIC_API_KEY is set and the `anthropic` extra is
installed. Forces a single tool call whose input schema IS the requested Pydantic
model — that's the provider-native way to get validated structured output without
parsing prose. Kept deliberately thin behind the `LLMClient` protocol.

NOTE: not exercised by the Phase 0 offline test suite (no key in CI). Treat as
best-effort until first run against a live key.
"""

from __future__ import annotations

import os
from typing import TypeVar

from pydantic import BaseModel

from .client import Msg

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-sonnet-4-5"


class AnthropicLLMClient:
    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None) -> None:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "anthropic SDK not installed. `pip install -e .[anthropic]`"
            ) from e
        self._client = AsyncAnthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self._model = model

    async def complete(self, *, system: str, messages: list[Msg], schema: type[T]) -> T:
        tool = {
            "name": "emit",
            "description": f"Return the {schema.__name__} for this turn.",
            "input_schema": schema.model_json_schema(),
        }
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            tools=[tool],
            tool_choice={"type": "tool", "name": "emit"},
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                return schema.model_validate(block.input)
        raise RuntimeError("model did not emit the forced structured-output tool call")
