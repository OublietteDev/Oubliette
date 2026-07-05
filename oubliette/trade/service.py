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
    buy = [
        BuyOffer(item_id=s.item_id, name=repo.get_item(s.item_id).name,
                 price_cp=merchant.price_list[s.item_id], qty=s.qty)
        for s in merchant.inventory
        if s.item_id in merchant.price_list and s.qty > 0
    ]
    # The sell column aggregates the WHOLE party — any member can put their goods
    # on the counter (the payout lands in the shared purse either way).
    sell = []
    for member in repo.party():
        for s in member.inventory:
            offer = buyback_price(repo, merchant, s.item_id)
            sell.append(SellOffer(
                item_id=s.item_id, name=repo.get_item(s.item_id).name,
                offer_cp=offer, qty=s.qty, affordable=merchant.coin >= offer,
                owner=member.id, owner_name=member.name,
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


def buy_transact(repo: Repository, merchant_id: str, item_id: str, qty: int,
                 recipient: str = "pc") -> Transact:
    merchant = repo.get_character(merchant_id)
    if item_id not in merchant.price_list:
        raise StateError(f"{item_id} is not for sale")
    if qty <= 0:
        raise StateError("qty must be positive")
    price = merchant.price_list[item_id]
    name = repo.get_item(item_id).name
    return Transact(
        from_=recipient, counterparty=merchant_id,
        give=[ValueEntry.from_cp(price * qty)],
        receive=[ValueEntry(item_id=item_id, qty=qty)],
        reason=f"Bought {qty}× {name} from {merchant.name} at {format_cp(price)} each",
    )


def checkout_ops(
    repo: Repository, merchant_id: str,
    buy: list[tuple[str, int]], sell: list[tuple[str, str, int]],
    recipient: str = "pc",
) -> tuple[list["StateOp"], str]:
    """Settle a whole basket as ONE recorded event: buys at asking go to
    `recipient` (any party member), sells at buyback leave each item's `owner`
    (sell entries are (owner, item_id, qty)), and ONE net coin move settles the
    difference against the shared purse. Fully validated here — a transact can't
    express a three-plus-party basket — then emitted as a single TOOL_APPLIED,
    so a checkout stays one atomic, replayable event."""
    from ..record.events import StateOp
    merchant = repo.get_character(merchant_id)
    rcp = repo.get_character(recipient)
    if rcp.kind != "pc":
        raise StateError(f"purchases must go to a party member, not {rcp.name}")
    ops: list[StateOp] = []
    cost = 0
    n_buy = 0
    for item_id, qty in buy:
        if qty <= 0:
            continue
        if item_id not in merchant.price_list:
            raise StateError(f"{item_id} is not for sale")
        if merchant.variant_qty(item_id) < qty:
            raise StateError(f"{merchant.name} does not have {qty}x {item_id} in stock")
        cost += merchant.price_list[item_id] * qty
        ops += [StateOp.item(merchant_id, item_id, -qty),
                StateOp.item(recipient, item_id, qty)]
        n_buy += qty
    value = 0
    n_sell = 0
    for owner, item_id, qty in sell:
        if qty <= 0:
            continue
        seller = repo.get_character(owner)
        if seller.kind != "pc":
            raise StateError(f"only party members can sell here (not {seller.name})")
        if seller.variant_qty(item_id) < qty:
            raise StateError(f"{seller.name} does not hold {qty}x {item_id}")
        value += buyback_price(repo, merchant, item_id) * qty
        ops += [StateOp.item(owner, item_id, -qty),
                StateOp.item(merchant_id, item_id, qty)]
        n_sell += qty
    if not ops:
        raise StateError("nothing selected to trade")
    net = cost - value
    if net > 0:
        if repo.party_cp < net:
            raise StateError(f"the party purse cannot cover {format_cp(net)} "
                             f"(has {format_cp(repo.party_cp)})")
        ops += [StateOp.coin(recipient, -net), StateOp.coin(merchant_id, net)]
    elif net < 0:
        if merchant.coin < -net:
            raise StateError(f"{merchant.name} cannot pay out {format_cp(-net)} "
                             f"(has {format_cp(merchant.coin)})")
        ops += [StateOp.coin(merchant_id, net), StateOp.coin(recipient, -net)]
    settle = ("even" if net == 0
              else f"{format_cp(abs(net))} {'paid' if net > 0 else 'received'}")
    reason = (f"Settled with {merchant.name}: bought {n_buy} (to {rcp.name}), "
              f"sold {n_sell} ({settle})")
    return ops, reason


def sell_transact(repo: Repository, merchant_id: str, item_id: str, qty: int,
                  owner: str = "pc") -> Transact:
    merchant = repo.get_character(merchant_id)
    if qty <= 0:
        raise StateError("qty must be positive")
    offer = buyback_price(repo, merchant, item_id)
    name = repo.get_item(item_id).name
    return Transact(
        from_=owner, counterparty=merchant_id,
        give=[ValueEntry(item_id=item_id, qty=qty)],
        receive=[ValueEntry.from_cp(offer * qty)],
        reason=f"Sold {qty}× {name} to {merchant.name} at {format_cp(offer)} each",
    )


def hand_over_transact(repo: Repository, from_id: str, to_id: str, item_id: str,
                       qty: int = 1, spell: str | None = None,
                       spell_level: int | None = None) -> Transact:
    """A bounded player action: one party member hands an item to another (the
    bard passes the wizard that wand). Validated by the dispatcher like any
    transact — the giver must actually hold the exact stack."""
    giver = repo.get_character(from_id)
    taker = repo.get_character(to_id)
    if giver.kind != "pc" or taker.kind != "pc":
        raise StateError("hand-over moves items between party members only")
    if from_id == to_id:
        raise StateError("that would be handing it to yourself")
    if qty <= 0:
        raise StateError("qty must be positive")
    name = repo.get_item(item_id).name
    return Transact(
        from_=from_id, counterparty=to_id,
        give=[ValueEntry(item_id=item_id, qty=qty, spell=spell, spell_level=spell_level)],
        receive=[],
        reason=f"{giver.name} hands {qty}× {name} to {taker.name}",
    )
