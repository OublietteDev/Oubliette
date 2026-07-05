"""Trade window tests (spec §9).

The window is a bounded UI over the transact tool: buy/sell are code-validated
transacts at merchant-set prices. We test the service (state view + the
transacts it builds) and the loop summon path with the scripted client.
"""

from __future__ import annotations

import asyncio

import pytest

from oubliette.dm.brain import Brain
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.state.repository import StateError
from oubliette.tools.dispatch import Dispatcher, ToolApplyError
from oubliette.trade.service import build_state, buy_transact, checkout_transact, sell_transact


def _session():
    return Session.open(InMemoryEventStore())


def test_trade_state_shows_priced_stock_and_buyback():
    s = _session()
    state = build_state(s.repo, "merchant_thom")
    # seed authors gp; the engine speaks copper (×100), player money = party purse
    assert state.merchant_cp == 500_00 and state.purse_cp == 15_00
    # priced stock is surfaced
    ids = {o.item_id for o in state.buy}
    assert "waterskin" in ids and "leather_satchel" in ids
    # the player's boots show a buyback offer
    sell_ids = {o.item_id for o in state.sell}
    assert "boots" in sell_ids


def test_buy_applies_a_validated_transact():
    s = _session()
    disp = Dispatcher(s.repo, s.canon)
    pc = s.repo.pc()
    thom = s.repo.get_character("merchant_thom")

    tx = buy_transact(s.repo, "merchant_thom", "waterskin", 1)   # asking 4 gp
    rt = disp.resolve(tx)
    s.emit_state(EventKind.TOOL_APPLIED, rt.ops, tool=rt.tool, reason=rt.reason)

    assert s.repo.party_cp == (15 - 4) * 100
    assert pc.item_qty("waterskin") == 1
    assert thom.coin == (500 + 4) * 100
    assert thom.item_qty("waterskin") == 3   # one left the stock of 4


def test_cannot_buy_what_you_cannot_afford():
    s = _session()
    disp = Dispatcher(s.repo, s.canon)
    # the satchel asks 15g; the purse holds 15g — affordable once, not twice
    disp_ok = disp.resolve(buy_transact(s.repo, "merchant_thom", "leather_satchel", 1))
    s.emit_state(EventKind.TOOL_APPLIED, disp_ok.ops, tool="transact", reason="buy")
    assert s.repo.party_cp == 0
    with pytest.raises(ToolApplyError):
        disp.resolve(buy_transact(s.repo, "merchant_thom", "waterskin", 1))  # 4g, has 0


def test_sell_capped_by_buyback_and_recorded():
    s = _session()
    disp = Dispatcher(s.repo, s.canon)
    pc = s.repo.pc()
    tx = sell_transact(s.repo, "merchant_thom", "boots", 1)
    rt = disp.resolve(tx)
    s.emit_state(EventKind.TOOL_APPLIED, rt.ops, tool=rt.tool, reason=rt.reason)
    assert pc.item_qty("boots") == 0
    assert s.repo.party_cp > 15_00  # got something for the boots
    assert len(s.store.of_kind(EventKind.TOOL_APPLIED)) == 1


def test_buy_unstocked_item_rejected():
    s = _session()
    with pytest.raises(StateError):
        buy_transact(s.repo, "merchant_thom", "boots", 1)  # boots aren't in Thom's price list


def test_checkout_basket_settles_buys_and_sells_in_one_transact():
    s = _session()
    disp = Dispatcher(s.repo, s.canon)
    pc = s.repo.pc()
    thom = s.repo.get_character("merchant_thom")
    # buy a belt (5g) + waterskin (4g) = 9g; sell the boots (buyback) to offset
    boots_offer = next(o.offer_cp for o in build_state(s.repo, "merchant_thom").sell if o.item_id == "boots")
    tx = checkout_transact(s.repo, "merchant_thom",
                           buy=[("sturdy_belt", 1), ("waterskin", 1)], sell=[("boots", 1)])
    rt = disp.resolve(tx)
    s.emit_state(EventKind.TOOL_APPLIED, rt.ops, tool=rt.tool, reason=rt.reason)

    assert s.repo.party_cp == 15_00 - (9_00 - boots_offer)     # paid the net
    assert pc.item_qty("sturdy_belt") == 1 and pc.item_qty("waterskin") == 1
    assert pc.item_qty("boots") == 0
    # exactly one event for the whole basket
    assert len(s.store.of_kind(EventKind.TOOL_APPLIED)) == 1


def test_checkout_rejects_unaffordable_basket_atomically():
    s = _session()
    disp = Dispatcher(s.repo, s.canon)
    pc = s.repo.pc()
    # two satchels at 15g = 30g; player has 15g — must fail, nothing applied
    tx = checkout_transact(s.repo, "merchant_thom", buy=[("leather_satchel", 2)], sell=[])
    with pytest.raises(ToolApplyError):
        disp.resolve(tx)
    assert s.repo.party_cp == 15_00
    assert pc.item_qty("leather_satchel") == 0


def test_merchant_stock_appears_in_dm_context():
    from oubliette.dm.context import build_context
    s = _session()
    ctx = build_context(s.repo, "a market")
    assert "sells" in ctx and "leather satchel 15 gp" in ctx
    assert "PARTY PURSE: 15 gp" in ctx


def test_item_resolution_handles_abbreviated_names():
    s = _session()
    # the DM often abbreviates — these must still resolve (haggle robustness)
    assert s.repo.resolve_item_id("belt") == "sturdy_belt"
    assert s.repo.resolve_item_id("gloves") == "riding_gloves"
    assert s.repo.resolve_item_id("satchel") == "leather_satchel"
    assert s.repo.resolve_item_id("boots") == "boots"     # exact id wins over fuzzy
    with pytest.raises(StateError):
        s.repo.resolve_item_id("dragon scale")


def test_scripted_loop_summons_trade_window():
    s = _session()
    loop = TurnLoop(s, Rng(1, record=s.emit_log), Brain(ScriptedLLMClient()))
    r = asyncio.run(loop.take_turn("What do you have for sale?"))
    assert r.trade_open is not None
    assert r.trade_open.merchant_id == "merchant_thom"
    assert any(o.item_id == "waterskin" for o in r.trade_open.buy)
