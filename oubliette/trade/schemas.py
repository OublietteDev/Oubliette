"""Trade boundary schemas (spec §9)."""

from __future__ import annotations

from pydantic import BaseModel


class TradeRequest(BaseModel):
    """Emitted by the DM to summon the trade window for a merchant."""

    merchant_id: str


class BuyOffer(BaseModel):
    item_id: str
    name: str
    price: int
    qty: int          # how many the merchant has in stock


class SellOffer(BaseModel):
    item_id: str
    name: str
    offer: int        # what the merchant will pay, per unit
    qty: int          # how many the player holds
    affordable: bool  # merchant can cover at least one (their gold caps buyback)


class TradeState(BaseModel):
    """The bounded view the window renders — all of it authoritative state."""

    merchant_id: str
    merchant_name: str
    merchant_gold: int
    player_gold: int
    buy: list[BuyOffer]
    sell: list[SellOffer]
