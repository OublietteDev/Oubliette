"""Trade boundary schemas (spec §9)."""

from __future__ import annotations

from pydantic import BaseModel


class TradeRequest(BaseModel):
    """Emitted by the DM to summon the trade window for a merchant."""

    merchant_id: str


class BuyOffer(BaseModel):
    item_id: str
    name: str
    price_cp: int     # asking price, in copper
    qty: int          # how many the merchant has in stock


class SellOffer(BaseModel):
    item_id: str
    name: str
    offer_cp: int     # what the merchant will pay per unit, in copper
    qty: int          # how many this owner holds
    affordable: bool  # merchant can cover at least one (their pocket caps buyback)
    owner: str        # which party member carries it (sell aggregates the party)
    owner_name: str


class TradeState(BaseModel):
    """The bounded view the window renders — all of it authoritative state.
    Money in copper; the window formats denominations."""

    merchant_id: str
    merchant_name: str
    merchant_cp: int
    purse_cp: int     # the shared party purse (what the player spends from)
    buy: list[BuyOffer]
    sell: list[SellOffer]
