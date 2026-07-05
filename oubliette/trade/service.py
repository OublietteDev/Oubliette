"""Trade service: build the bounded view, and turn a buy/sell into a `transact`.

The transacts go through the normal dispatcher (validated) and session
(recorded), so trade purchases are just TOOL_APPLIED events — they replay like
any other state change. Nothing here mutates state directly.

All prices are COPPER (the canonical unit); the window formats them for display.
The player's money is the shared PARTY PURSE (repo.party_cp) — the transact's
`from_` still names a PC and the repository routes their coin ops to the purse.
"""

from __future__ import annotations

from ..coin import format_cp
from ..state.repository import Repository, StateError
from ..tools.schemas import Transact, ValueEntry
from .schemas import BuyOffer, SellOffer, TradeState


def buyback_price(repo: Repository, merchant, item_id: str) -> int:
    """What the merchant offers for a player's item, in copper. Half their asking
    price if they stock it, else the item's advisory value. Placeholder for the
    soft/haggle economy (§11) — big-ticket deals still happen via a chat haggle."""
    ask = merchant.price_list.get(item_id)
    if ask:
        return max(1, ask // 2)
    item = repo.get_item(item_id)
    return max(1, item.value_cp or 1)


def build_state(repo: Repository, merchant_id: str) -> TradeState:
    merchant = repo.get_character(merchant_id)
    pc = repo.pc()
    buy = [
        BuyOffer(item_id=s.item_id, name=repo.get_item(s.item_id).name,
                 price_cp=merchant.price_list[s.item_id], qty=s.qty)
        for s in merchant.inventory
        if s.item_id in merchant.price_list and s.qty > 0
    ]
    sell = []
    for s in pc.inventory:
        offer = buyback_price(repo, merchant, s.item_id)
        sell.append(SellOffer(
            item_id=s.item_id, name=repo.get_item(s.item_id).name,
            offer_cp=offer, qty=s.qty, affordable=merchant.coin >= offer,
        ))
    return TradeState(
        merchant_id=merchant.id, merchant_name=merchant.name,
        merchant_cp=merchant.coin, purse_cp=repo.party_cp, buy=buy, sell=sell,
    )


def has_stock(repo: Repository, merchant_id: str) -> bool:
    """True if there's anything to browse — priced stock or sellable player goods."""
    try:
        state = build_state(repo, merchant_id)
    except StateError:
        return False
    return bool(state.buy or state.sell)


def buy_transact(repo: Repository, merchant_id: str, item_id: str, qty: int) -> Transact:
    merchant = repo.get_character(merchant_id)
    if item_id not in merchant.price_list:
        raise StateError(f"{item_id} is not for sale")
    if qty <= 0:
        raise StateError("qty must be positive")
    price = merchant.price_list[item_id]
    name = repo.get_item(item_id).name
    return Transact(
        from_="pc", counterparty=merchant_id,
        give=[ValueEntry.from_cp(price * qty)],
        receive=[ValueEntry(item_id=item_id, qty=qty)],
        reason=f"Bought {qty}× {name} from {merchant.name} at {format_cp(price)} each",
    )


def checkout_transact(
    repo: Repository, merchant_id: str,
    buy: list[tuple[str, int]], sell: list[tuple[str, int]],
) -> Transact:
    """Build ONE balanced transact for a whole basket: buy items at asking, sell
    items at buyback, net coin settles the difference. Validated by the dispatcher
    like any transact (the purse must cover a net cost; the merchant a net payout)."""
    merchant = repo.get_character(merchant_id)
    give: list[ValueEntry] = []      # leaves the player
    receive: list[ValueEntry] = []   # enters the player
    cost = 0
    n_buy = 0
    for item_id, qty in buy:
        if qty <= 0:
            continue
        if item_id not in merchant.price_list:
            raise StateError(f"{item_id} is not for sale")
        cost += merchant.price_list[item_id] * qty
        receive.append(ValueEntry(item_id=item_id, qty=qty))
        n_buy += qty
    value = 0
    n_sell = 0
    for item_id, qty in sell:
        if qty <= 0:
            continue
        value += buyback_price(repo, merchant, item_id) * qty
        give.append(ValueEntry(item_id=item_id, qty=qty))
        n_sell += qty
    net = cost - value
    if net > 0:
        give.append(ValueEntry.from_cp(net))        # player pays the difference
    elif net < 0:
        receive.append(ValueEntry.from_cp(-net))    # player receives the difference
    if not give and not receive:
        raise StateError("nothing selected to trade")
    settle = ("even" if net == 0
              else f"{format_cp(abs(net))} {'paid' if net > 0 else 'received'}")
    return Transact(
        from_="pc", counterparty=merchant_id, give=give, receive=receive,
        reason=f"Settled with {merchant.name}: bought {n_buy}, sold {n_sell} ({settle})",
    )


def sell_transact(repo: Repository, merchant_id: str, item_id: str, qty: int) -> Transact:
    merchant = repo.get_character(merchant_id)
    if qty <= 0:
        raise StateError("qty must be positive")
    offer = buyback_price(repo, merchant, item_id)
    name = repo.get_item(item_id).name
    return Transact(
        from_="pc", counterparty=merchant_id,
        give=[ValueEntry(item_id=item_id, qty=qty)],
        receive=[ValueEntry.from_cp(offer * qty)],
        reason=f"Sold {qty}× {name} to {merchant.name} at {format_cp(offer)} each",
    )
