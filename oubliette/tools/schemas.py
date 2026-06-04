"""Tool-call schemas. Phase 0 implements `transact` fully; `give`/`take` are the
one-directional conveniences from §5 (included so the dispatch table is real)."""

from __future__ import annotations

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
    `give` moves from_ -> counterparty; `receive` moves counterparty -> from_;
    all-or-nothing."""

    from_: str = Field(alias="from_")
    counterparty: str
    give: list[ValueEntry] = Field(default_factory=list)
    receive: list[ValueEntry] = Field(default_factory=list)
    reason: str


class Give(BaseModel):
    to: str
    items: list[ValueEntry]
    reason: str


class Take(BaseModel):
    from_: str = Field(alias="from_")
    items: list[ValueEntry]
    reason: str


# The dispatch table: tool name -> schema. The only doors that exist.
TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "transact": Transact,
    "give": Give,
    "take": Take,
}
