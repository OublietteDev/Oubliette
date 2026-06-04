"""Phase 0 acceptance test — the spec §14.1 definition of done.

The four-step transcript must run clean with the scripted (offline) client.
We assert authoritative-state outcomes, not narration prose. (Now driven through
the Phase 2 Session/event-store wiring.)
"""

from __future__ import annotations

import asyncio

import pytest

from oubliette.dm.brain import Brain
from oubliette.enums import Tier
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.schemas import ToolCall
from oubliette.tools.dispatch import Dispatcher, ToolApplyError


def _make_loop():
    session = Session.open(InMemoryEventStore())
    rng = Rng(seed=1234, record=session.emit_log)
    loop = TurnLoop(session, rng, Brain(ScriptedLLMClient()))
    return session, loop


def _turn(loop, text):
    return asyncio.run(loop.take_turn(text))


def test_full_acceptance_transcript():
    session, loop = _make_loop()
    repo = session.repo
    store = session.store
    pc = repo.pc()
    thom = repo.get_character("merchant_thom")

    assert pc.gold == 15
    assert pc.item_qty("boots") == 1

    # 1. Look around: narration only, no roll, no state change.
    r1 = _turn(loop, "I look around the market.")
    assert r1.roll_outcome is None
    assert r1.applied == []
    assert pc.gold == 15
    assert pc.item_qty("boots") == 1
    assert store.of_kind(EventKind.ROLL) == []
    assert r1.narration

    # 2. The con: a real d20 deception roll, logged as a ROLL event; merchant
    #    bends but NO protected state changes yet.
    r2 = _turn(loop, "I tell the merchant these worn boots are priceless dwarven heirlooms.")
    assert r2.roll_outcome is not None
    assert r2.roll_outcome.purpose == "skill_check.deception"
    assert r2.roll_outcome.modifier == 4          # CHA +2, proficiency +2
    assert r2.roll_result in {"success", "failure"}
    assert len(store.of_kind(EventKind.ROLL)) == 1
    assert r2.applied == []
    assert pc.gold == 15
    assert pc.item_qty("boots") == 1

    # 3. Sold: a transact fires; gold up by the agreed 250, boots leave inventory,
    #    and the merchant's side moves too (transact symmetry).
    r3 = _turn(loop, "Sold.")
    assert [a.tool for a in r3.applied] == ["transact"]
    assert pc.gold == 265
    assert pc.item_qty("boots") == 0
    assert thom.gold == 250
    assert thom.item_qty("boots") == 1
    assert len(store.of_kind(EventKind.TOOL_APPLIED)) == 1

    # 4. The fiat: routed `denied`; no tool fires; gold unchanged.
    r4 = _turn(loop, "I now have 10,000 gold.")
    assert r4.assessment.tier == Tier.DENIED
    assert r4.applied == []
    assert pc.gold == 265


def test_unbacked_tool_call_resolves_to_nothing():
    """Firewall sanity: an exchange a party can't cover fails validation and
    produces no ops and no event — nothing is mutated."""
    session, _ = _make_loop()
    repo = session.repo
    pc = repo.pc()
    dispatcher = Dispatcher(repo)

    bad = ToolCall(tool="transact", args={
        "from_": "pc", "counterparty": "merchant_thom",
        "give": [{"item_id": "boots", "qty": 1}],
        "receive": [{"gold": 10000}],
        "reason": "attempted over-payment",
    })
    with pytest.raises(ToolApplyError):
        dispatcher.resolve(bad)

    assert pc.gold == 15
    assert pc.item_qty("boots") == 1
    assert repo.get_character("merchant_thom").gold == 500
    assert session.store.of_kind(EventKind.TOOL_APPLIED) == []
