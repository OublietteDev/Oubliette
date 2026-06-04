"""Phase 1 acceptance — the combat BOUNDARY (spec §8, §14 Phase 1).

We assert the edges, not the (placeholder) internals: live state in, a
CombatResult with absolute values out, applied to authoritative state as one
recorded result; ephemeral combatants never persist; non-combat exits are
first-class; recurring (persistent) foes are written back.
"""

from __future__ import annotations

import asyncio

import pytest

from oubliette.combat.boundary import apply_result, run_encounter
from oubliette.combat.schemas import EncounterRequest, EnemyRef, ExitKind, TerrainSpec
from oubliette.dm.brain import Brain
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.log import DebugLog
from oubliette.record.rng import Rng
from oubliette.runtime.loop import TurnLoop
from oubliette.seed import seed_world
from oubliette.state.repository import StateError


def _make_loop(seed: int = 1234):
    repo = seed_world()
    log = DebugLog()
    rng = Rng(seed=seed, log=log)
    loop = TurnLoop(repo, rng, log, Brain(ScriptedLLMClient()))
    return repo, log, loop


def _turn(loop, text):
    return asyncio.run(loop.take_turn(text))


def test_attack_resolves_and_applies_as_one_result():
    repo, log, loop = _make_loop()
    pc = repo.pc()
    assert pc.xp == 0 and pc.gold == 15

    r = _turn(loop, "I draw my knife and attack the bandit.")

    cr = r.combat_result
    assert cr is not None
    assert cr.outcome == "victory"                 # strong PC vs one bandit
    assert cr.xp_award == 25                        # bandit template xp
    # absolute write-backs land in state
    assert pc.xp == 25
    assert pc.gold == 15 + 8                        # bandit loot: 8g
    assert 0 < pc.hp <= pc.max_hp                   # survived, maybe scuffed
    # exactly one combat_result recorded (the §8 single-event rule)
    assert len(log.of_kind("combat_result")) == 1


def test_ephemeral_combatant_never_touches_the_entity_table():
    repo, _, loop = _make_loop()
    _turn(loop, "I draw my knife and attack the bandit.")

    # The bandit was template-spawned (D5): no persistent row, gone after the fight.
    with pytest.raises(StateError):
        repo.get_character("bandit#1")
    # hp_final keys ONLY persistent entities — never the ephemeral bandit.
    # (the PC is persistent; the bandit is not)


def test_parley_is_a_first_class_non_combat_exit():
    repo, log, loop = _make_loop()
    pc = repo.pc()

    r = _turn(loop, "I try to talk the bandits down.")

    cr = r.combat_result
    assert cr is not None
    assert cr.outcome == "parley"
    assert cr.xp_award == 0 and cr.loot == []
    # a clean exit changes nothing about the sheet
    assert pc.hp == 24 and pc.xp == 0 and pc.gold == 15
    assert len(log.of_kind("combat_result")) == 1


def test_persistent_foe_is_written_back_not_discarded():
    """A recurring entity used as an enemy takes its real damage back to state (D5)."""
    repo = seed_world()
    log = DebugLog()
    rng = Rng(seed=1234, log=log)

    # Use the merchant as a (weak) recurring foe to exercise the persistent path.
    request = EncounterRequest(
        kind="brawl", enemies=[EnemyRef(ref="merchant_thom", count=1)],
        terrain=TerrainSpec(), allow_exits=[],
    )
    result = run_encounter(request, repo, rng, log)
    apply_result(result, repo, log)

    assert result.outcome == "victory"
    assert "merchant_thom" in result.hp_final          # persistent → in the result
    assert repo.get_character("merchant_thom").hp == 0  # absolute write-back applied
