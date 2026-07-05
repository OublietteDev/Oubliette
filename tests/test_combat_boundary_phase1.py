"""Phase 1 acceptance — the combat BOUNDARY (spec §8, §14 Phase 1).

We assert the edges, not the (placeholder) internals: live state in, a
CombatResult with absolute values out, applied to authoritative state as one
recorded COMBAT_RESULT event; ephemeral combatants never persist; non-combat
exits are first-class; recurring (persistent) foes are written back.
"""

from __future__ import annotations

import asyncio

import pytest

from oubliette.combat.boundary import result_to_ops, run_encounter
from oubliette.combat.schemas import EncounterRequest, EnemyRef, TerrainSpec
from oubliette.dm.brain import Brain
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.log import DebugLog
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.state.repository import StateError


def _make_loop(seed: int = 1234):
    session = Session.open(InMemoryEventStore())
    rng = Rng(seed=seed, record=session.emit_log)
    loop = TurnLoop(session, rng, Brain(ScriptedLLMClient()))
    return session, loop


def _turn(loop, text):
    return asyncio.run(loop.take_turn(text))


def test_attack_stages_a_fight_and_waits_for_the_arena():
    """Stage 3: a real fight no longer auto-resolves inline — it STAGES (the
    '⚔ Enter the Arena' two-step, D-COMBAT-3). The turn returns pending; nothing
    is written until the player enters the Arena (see test_combat_arena_launch)."""
    session, loop = _make_loop()
    pc = session.repo.pc()
    assert pc.xp == 0 and session.repo.party_cp == 15_00

    r = _turn(loop, "I draw my knife and attack the bandit.")

    assert r.combat_pending is True and r.combat_result is None
    assert session.pending_combat is not None
    # nothing resolved or recorded yet — the fight is held, not fought
    assert pc.xp == 0 and session.repo.party_cp == 15_00 and pc.hp == 24
    assert len(session.store.of_kind(EventKind.COMBAT_RESULT)) == 0


def test_ephemeral_combatant_never_touches_the_entity_table():
    session, loop = _make_loop()
    _turn(loop, "I draw my knife and attack the bandit.")

    with pytest.raises(StateError):
        session.repo.get_character("road bandit")


def test_parley_is_a_first_class_non_combat_exit():
    session, loop = _make_loop()
    pc = session.repo.pc()

    r = _turn(loop, "I try to talk the bandits down.")

    cr = r.combat_result
    assert cr is not None
    assert cr.outcome == "parley"
    assert cr.xp_award == 0 and cr.loot == []
    assert pc.hp == 24 and pc.xp == 0 and session.repo.party_cp == 15_00
    assert len(session.store.of_kind(EventKind.COMBAT_RESULT)) == 1


def test_persistent_foe_is_written_back_not_discarded():
    """A recurring entity used as an enemy takes its real damage back to state (D5)."""
    session = Session.open(InMemoryEventStore())
    rng = Rng(seed=1234, record=session.emit_log)

    request = EncounterRequest(
        kind="brawl", enemies=[EnemyRef(ref="merchant_thom", count=1)],
        terrain=TerrainSpec(), allow_exits=[],
    )
    result = run_encounter(request, session.repo, rng, DebugLog())
    session.emit_state(EventKind.COMBAT_RESULT, result_to_ops(result), outcome=result.outcome)

    assert result.outcome == "victory"
    assert "merchant_thom" in result.hp_final
    assert session.repo.get_character("merchant_thom").hp == 0
