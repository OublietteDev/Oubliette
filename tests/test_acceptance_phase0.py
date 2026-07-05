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
from oubliette.record.events import Event, EventKind, StateOp, apply_ops, replay
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.state.repository import StateError
from oubliette.tools.dispatch import Dispatcher, ToolApplyError
from oubliette.tools.schemas import AwardXp, Give, Transact, ValueEntry
from pydantic import ValidationError


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

    assert repo.party_cp == 15_00          # seed gp -> copper purse
    assert pc.item_qty("boots") == 1

    # 1. Look around: narration only, no roll, no state change.
    r1 = _turn(loop, "I look around the market.")
    assert r1.roll_outcome is None
    assert r1.applied == []
    assert repo.party_cp == 15_00
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
    assert repo.party_cp == 15_00
    assert pc.item_qty("boots") == 1

    # 3. Sold: a transact fires; gold up by the agreed 250, boots leave inventory,
    #    and the merchant's side moves too (transact symmetry).
    r3 = _turn(loop, "Sold.")
    assert [a.tool for a in r3.applied] == ["transact"]
    assert repo.party_cp == 265_00
    assert pc.item_qty("boots") == 0
    assert thom.coin == 250_00
    assert thom.item_qty("boots") == 1
    assert len(store.of_kind(EventKind.TOOL_APPLIED)) == 1

    # 4. The fiat: routed `denied`; no tool fires; gold unchanged.
    r4 = _turn(loop, "I now have 10,000 gold.")
    assert r4.assessment.tier == Tier.DENIED
    assert r4.applied == []
    assert repo.party_cp == 265_00


def test_award_xp_tool_grants_experience():
    """The award_xp DM tool resolves to an XP StateOp the session applies — the
    sanctioned path for the DM to administer experience (it proposes, code applies)."""
    session, _ = _make_loop()
    repo = session.repo
    pc = repo.pc()
    start = pc.xp
    dispatcher = Dispatcher(repo)
    resolved = dispatcher.resolve(AwardXp(to="pc", amount=500, reason="resolved the standoff"))
    assert [(o.op, o.char, o.delta) for o in resolved.ops] == [("xp", "pc", 500)]
    for op in resolved.ops:
        op.apply(repo)
    assert pc.xp == start + 500


def test_award_xp_rejects_nonpositive_and_unknown_target():
    session, _ = _make_loop()
    dispatcher = Dispatcher(session.repo)
    with pytest.raises(ValidationError):           # schema guards the amount
        AwardXp(to="pc", amount=0, reason="nothing earned")
    with pytest.raises(ToolApplyError):            # recipient must exist
        dispatcher.resolve(AwardXp(to="ghost", amount=10, reason="who?"))


def test_give_to_noncharacter_is_rejected():
    """Regression (bricked-save bug): granting gold/items to a non-character — e.g. a
    provisional NPC the DM just created — is refused at resolve time, so the bad op is
    never recorded. (Previously it slipped through and crashed replay on reopen.)"""
    session, _ = _make_loop()
    dispatcher = Dispatcher(session.repo)
    with pytest.raises(ToolApplyError):
        dispatcher.resolve(Give(to="marro_the_dockhand", items=[ValueEntry(gold=50)],
                                reason="a purse for the new dockhand"))


def test_replay_tolerates_legacy_ops_against_missing_characters():
    """Defense in depth: a save whose log already holds an op targeting a character
    that never existed still reopens — replay skips the bad op instead of bricking the
    save. Live application stays strict (an unexpected bad op there is a real bug)."""
    session, _ = _make_loop()
    repo = session.repo
    bad = Event(seq=9999, kind=EventKind.TOOL_APPLIED.value,
                payload={"ops": [StateOp.coin("ghost", 50_00).model_dump()]})
    with pytest.raises(StateError):                 # strict (live) surfaces it
        apply_ops(bad.state_ops(), repo, strict=True)
    replay([bad], repo)                             # tolerant replay does not raise


def test_unbacked_tool_call_resolves_to_nothing():
    """Firewall sanity: an exchange a party can't cover fails validation and
    produces no ops and no event — nothing is mutated."""
    session, _ = _make_loop()
    repo = session.repo
    pc = repo.pc()
    dispatcher = Dispatcher(repo)

    bad = Transact(
        from_="pc", counterparty="merchant_thom",
        give=[ValueEntry(item_id="boots", qty=1)],
        receive=[ValueEntry(gold=10000)],
        reason="attempted over-payment",
    )
    with pytest.raises(ToolApplyError):
        dispatcher.resolve(bad)

    assert repo.party_cp == 15_00
    assert pc.item_qty("boots") == 1
    assert repo.get_character("merchant_thom").coin == 500_00
    assert session.store.of_kind(EventKind.TOOL_APPLIED) == []
