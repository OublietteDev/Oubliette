"""Tool-call schemas — a typed, discriminated union so the model sees each tool's
argument shape (fix for harness gap G1). Phase 0 implemented `transact` fully;
`give`/`take` are the one-directional conveniences from §5.

The `tool` literal is the discriminator. `TurnResolution.tool_calls` is a list of
these, so the JSON schema handed to the model carries the full arg shapes — no
more guessing key names.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator


class ValueEntry(BaseModel):
    """One side of an exchange: either gold OR an item stack, never both."""

    gold: int | None = None
    item_id: str | None = None
    qty: int = 1

    @model_validator(mode="after")
    def _exactly_one(self) -> "ValueEntry":
        has_gold = self.gold is not None
        has_item = self.item_id is not None
        if has_gold == has_item:
            raise ValueError("ValueEntry must set exactly one of {gold, item_id}")
        if has_gold and self.gold <= 0:
            raise ValueError("gold amount must be positive")
        if has_item and self.qty <= 0:
            raise ValueError("item qty must be positive")
        return self


class Transact(BaseModel):
    """Atomic, BALANCED exchange between two parties (spec §5).
    `give` moves from_ -> counterparty; `receive` moves counterparty -> from_."""

    tool: Literal["transact"] = "transact"
    from_: str = Field(description="entity giving `give` and receiving `receive` (usually 'pc')")
    counterparty: str = Field(description="the other party, e.g. a merchant entity id")
    give: list[ValueEntry] = Field(default_factory=list, description="what from_ hands over")
    receive: list[ValueEntry] = Field(default_factory=list, description="what from_ gets back")
    reason: str = Field(description="the fiction that justifies this exchange")


class Give(BaseModel):
    """Grant items/gold to someone (no counter-exchange)."""

    tool: Literal["give"] = "give"
    to: str
    items: list[ValueEntry]
    reason: str


class Take(BaseModel):
    """Remove items/gold from someone (no counter-exchange)."""

    tool: Literal["take"] = "take"
    from_: str
    items: list[ValueEntry]
    reason: str


# The only doors into protected state, as a discriminated union (the schema the
# model fills in). To add a tool: add a model + a `tool` literal, and a resolver
# branch in tools/dispatch.py.
ToolCall = Annotated[Union[Transact, Give, Take], Field(discriminator="tool")]
