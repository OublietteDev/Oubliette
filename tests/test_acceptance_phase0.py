"""Phase 0 acceptance test — the spec §14.1 definition of done.

The four-step transcript must run clean with the scripted (offline) client.
We assert authoritative-state outcomes, not narration prose.
"""

from __future__ import annotations

import asyncio

import pytest

from oubliette.dm.brain import Brain
from oubliette.enums import Tier
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.log import DebugLog
from oubliette.record.rng import Rng
from oubliette.runtime.loop import TurnLoop
from oubliette.schemas import ToolCall
from oubliette.seed import seed_world
from oubliette.tools.dispatch import Dispatcher, ToolApplyError


def _make_loop():
    repo = seed_world()
    log = DebugLog()
    rng = Rng(seed=1234, log=log)
    loop = TurnLoop(repo, rng, log, Brain(ScriptedLLMClient()))
    return repo, log, loop


def _turn(loop, text):
    return asyncio.run(loop.take_turn(text))


def test_full_acceptance_transcript():
    repo, log, loop = _make_loop()
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
    assert log.of_kind("roll") == []
    assert r1.narration  # the DM said *something*

    # 2. The con: a real d20 deception roll happens and is logged; merchant bends
    #    but NO protected state changes yet.
    r2 = _turn(loop, "I tell the merchant these worn boots are priceless dwarven heirlooms.")
    assert r2.roll_outcome is not None
    assert r2.roll_outcome.purpose == "skill_check.deception"
    # code supplied the bonus from the sheet: CHA +2, proficiency +2 => +4
    assert r2.roll_outcome.modifier == 4
    assert r2.roll_result in {"success", "failure"}
    assert len(log.of_kind("roll")) == 1
    assert r2.applied == []
    assert pc.gold == 15
    assert pc.item_qty("boots") == 1

    # 3. Sold: a transact fires; gold up by the agreed 250, boots leave inventory,
    #    and the merchant's side moves too (transact symmetry).
    r3 = _turn(loop, "Sold.")
    assert [a.tool for a in r3.applied] == ["transact"]
    assert pc.gold == 265              # 15 + 250
    assert pc.item_qty("boots") == 0
    assert thom.gold == 250            # 500 - 250
    assert thom.item_qty("boots") == 1
    assert len(log.of_kind("tool_applied")) == 1

    # 4. The fiat: routed `denied`; no tool fires; gold unchanged.
    r4 = _turn(loop, "I now have 10,000 gold.")
    assert r4.assessment.tier == Tier.DENIED
    assert r4.applied == []
    assert pc.gold == 265


def test_player_cannot_be_minted_gold_by_an_unbacked_tool_call():
    """Firewall sanity: even a malformed/unbacked tool call mutates nothing.
    (The player can't emit one at all; this checks the dispatcher refuses an
    exchange a party can't cover, rather than partially applying it.)"""
    repo, log, _ = _make_loop()
    pc = repo.pc()
    dispatcher = Dispatcher(repo, log)

    # Thom 'pays' 10000g he doesn't have -> must be rejected, no mutation.
    bad = ToolCall(tool="transact", args={
        "from_": "pc", "counterparty": "merchant_thom",
        "give": [{"item_id": "boots", "qty": 1}],
        "receive": [{"gold": 10000}],
        "reason": "attempted over-payment",
    })
    with pytest.raises(ToolApplyError):
        dispatcher.apply(bad)

    assert pc.gold == 15               # unchanged
    assert pc.item_qty("boots") == 1   # boots NOT taken
    assert repo.get_character("merchant_thom").gold == 500
    assert log.of_kind("tool_applied") == []
