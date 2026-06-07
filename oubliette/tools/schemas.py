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


class CreateEntity(BaseModel):
    """Introduce new world content (an NPC, place, lore...). Always born
    `provisional` (spec §7/§11) — the runtime forces that; the DM cannot create
    confirmed canon directly."""

    tool: Literal["create_entity"] = "create_entity"
    entity_type: Literal["npc", "place", "lore", "item", "quest", "faction"]
    name: str = Field(description="short name/title for the entity")
    text: str = Field(default="", description="the canon — who/what this is")
    origin: Literal["recombined", "freestyle"] = "freestyle"
    reason: str


class PromoteCanon(BaseModel):
    """Promote a provisional entity to confirmed canon (spec §11)."""

    tool: Literal["promote_canon"] = "promote_canon"
    entity_id: str = Field(description="the canon id, e.g. 'canon-0'")
    reason: str


class Travel(BaseModel):
    """Move the party to another location. Code updates the scene and who's
    present; emit this when the party goes somewhere in the world."""

    tool: Literal["travel"] = "travel"
    to: str = Field(description="destination place id (or its name) from WHERE YOU CAN GO")
    reason: str = Field(description="the fiction for the move, e.g. 'the party walks to the inn'")


class EndSession(BaseModel):
    """End the game cleanly. Exists for the DM's protection — you may emit this to
    step away from a hostile or bad-faith interaction. The session closes and the
    reason is logged."""

    tool: Literal["end_session"] = "end_session"
    reason: str = Field(description="a brief, honest reason for ending (logged, not shown as fiction)")


# The only doors into protected state + canon, as a discriminated union (the schema
# the model fills in). To add a tool: add a model + a `tool` literal, and a resolver
# branch in tools/dispatch.py.
ToolCall = Annotated[
    Union[Transact, Give, Take, CreateEntity, PromoteCanon, Travel, EndSession],
    Field(discriminator="tool"),
]
