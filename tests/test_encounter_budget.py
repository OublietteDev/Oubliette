"""Difficulty S2 — the encounter budget: the math, the staging backstop, the
invisible bounce, and the DM's context line.

The contract: caps derive from party strength × the encounter dial; the DM
sees its budget in context; an over-budget improvised fight raises at the
staging funnel and the loop re-asks the DM (the player never sees it); the
developer codeword bypasses everything; recurring entity foes are exempt;
a CR-less creature can't sneak under the cap. No floors are enforced — a
trivial fight stays possible at every difficulty.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from oubliette.combat import arena_launch
from oubliette.combat.arena_launch import stage_combat
from oubliette.combat.budget import (
    BudgetError,
    budget_for,
    check_encounter,
    format_cr,
)
from oubliette.combat.schemas import EncounterRequest, EnemyRef, TerrainSpec
from oubliette.difficulty import preset_settings
from oubliette.dm.brain import Brain
from oubliette.dm.context import build_context
from oubliette.enums import Tier, Verb
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.schemas import Intent, TurnAssessment


def _party(*levels):
    return [SimpleNamespace(level=lv) for lv in levels]


def _inst(name, cr, entity_id=None):
    return SimpleNamespace(creature=SimpleNamespace(name=name), cr=cr, entity_id=entity_id)


# --- the math ----------------------------------------------------------------

def test_bands_scale_from_party_strength():
    four_l3 = _party(3, 3, 3, 3)
    std = budget_for(four_l3, "standard")
    assert (std.single_cap, std.total_cap) == (3.0, 6.0)
    assert std.party_size == 4 and std.level_low == std.level_high == 3

    gentle = budget_for(four_l3, "gentle")
    assert (gentle.single_cap, gentle.total_cap) == (1.5, 4.5)

    punishing = budget_for(four_l3, "punishing")
    assert (punishing.single_cap, punishing.total_cap) == (4.5, 9.0)


def test_small_parties_keep_a_sane_floor():
    solo = budget_for(_party(1), "standard")
    assert solo.single_cap == 1.0
    assert solo.total_cap == 1.0            # total never drops below single
    assert budget_for([], "standard").party_size == 1   # empty degrades to a L1 party
    assert budget_for(_party(1), "gentle").single_cap == 0.5
    assert budget_for(_party(1), "nonsense_dial").band == "standard"


def test_format_cr_speaks_player():
    assert format_cr(0.125) == "1/8" and format_cr(0.25) == "1/4"
    assert format_cr(0.5) == "1/2" and format_cr(3.0) == "3" and format_cr(4.5) == "4.5"


# --- the check ---------------------------------------------------------------

def test_single_cap_violation_names_the_creature_and_budget():
    b = budget_for(_party(3, 3, 3, 3), "standard")
    with pytest.raises(BudgetError) as e:
        check_encounter([_inst("Adult Red Dragon", 17.0)], b)
    msg = str(e.value)
    assert "Adult Red Dragon" in msg and "CR 17" in msg and "budget" in msg


def test_total_cap_violation_sums_the_pack():
    b = budget_for(_party(1), "standard")           # total cap 1.0
    wolves = [_inst("Wolf", 0.25) for _ in range(8)]  # sums to 2.0
    with pytest.raises(BudgetError) as e:
        check_encounter(wolves, b)
    assert "8× Wolf" in str(e.value)


def test_recurring_entity_foes_are_exempt():
    b = budget_for(_party(1), "gentle")
    check_encounter([_inst("Seraphel", 23.0, entity_id="seraphel")], b)  # no raise


def test_a_crless_creature_cannot_sneak_under_the_cap():
    b = budget_for(_party(20, 20, 20, 20), "punishing")   # a huge budget
    with pytest.raises(BudgetError) as e:
        check_encounter([_inst("Mystery Beast", None)], b)
    assert "challenge rating" in str(e.value)


def test_a_fair_fight_passes():
    b = budget_for(_party(3, 3, 3, 3), "standard")
    check_encounter([_inst("Ogre", 2.0), _inst("Wolf", 0.25), _inst("Wolf", 0.25)], b)


# --- the staging funnel --------------------------------------------------------

def _session() -> Session:
    return Session.open(InMemoryEventStore())


def _dragon_request() -> EncounterRequest:
    return EncounterRequest(kind="ambush", enemies=[EnemyRef(ref="adult red dragon")],
                            terrain=TerrainSpec())


def test_stage_combat_enforces_a_given_budget_and_skips_without_one():
    s = _session()
    budget = budget_for(s.repo.party(), "standard")
    with pytest.raises(BudgetError):
        stage_combat(_dragon_request(), s.repo, s, budget=budget)
    # No budget (direct/authored callers): the same fight stages fine.
    pending = stage_combat(_dragon_request(), s.repo, s).pending
    assert pending is not None
    arena_launch.cleanup(pending)


# --- the loop: bounce, give-up, and the developer bypass -----------------------

def _loop(session: Session) -> TurnLoop:
    return TurnLoop(session, Rng(seed=1234, record=session.emit_log),
                    Brain(ScriptedLLMClient()))


def _dragon_assessment(text: str) -> TurnAssessment:
    return TurnAssessment(
        intent=Intent(raw_text=text, verb=Verb.ATTACK),
        tier=Tier.RECOMBINED, resolution_hint="hostility",
        encounter=_dragon_request(),
    )


def test_over_budget_encounter_bounces_and_the_dm_repicks():
    """First pick: a dragon (over budget). The bounce re-asks the scripted DM,
    whose read of 'attack the raiders' is a road bandit — legal — so the turn
    ends staged for the Arena. The player saw none of it."""
    s = _session()
    loop = _loop(s)
    text = "I draw my knife and attack the raiders."
    r = asyncio.run(loop._run_combat(text, _dragon_assessment(text)))
    assert r.combat_pending is True
    names = [c.name_override for c in s.pending_combat.plan.encounter.combatants
             if c.team == "enemy"]
    assert any("road bandit" in n for n in names)      # the re-pick, not the dragon
    arena_launch.cleanup(s.pending_combat)
    s.pending_combat = None


def test_bounce_gives_up_gracefully_when_no_legal_fight_emerges():
    """The re-assess yields no encounter (the scripted DM sees no hostility in
    'Hello there') → the existing no-fight narration, nothing staged."""
    s = _session()
    loop = _loop(s)
    r = asyncio.run(loop._run_combat("Hello there.", _dragon_assessment("Hello there.")))
    assert not r.combat_pending
    assert s.pending_combat is None
    assert "dissolves" in r.narration
    assert "budget" in (r.meta_notice or "")


def test_developer_codeword_bypasses_the_budget():
    s = _session()
    loop = _loop(s)
    text = "Etteilbuo: an adult red dragon attacks me."
    r = asyncio.run(loop._run_combat(text, _dragon_assessment(text)))
    assert r.combat_pending is True                    # staged, unbudgeted
    arena_launch.cleanup(s.pending_combat)
    s.pending_combat = None


# --- the DM's context line ------------------------------------------------------

def test_context_carries_party_strength_and_budget():
    s = _session()
    ctx = build_context(s.repo, difficulty=preset_settings("adventure"))
    assert "PARTY STRENGTH:" in ctx and "ENCOUNTER BUDGET (adventure table)" in ctx
    assert "toughest single foe CR ≤" in ctx
    assert "trivial encounters" not in ctx             # the punishing tail is band-gated

    spicy = build_context(s.repo, difficulty=preset_settings("challenge"))
    assert "ENCOUNTER BUDGET (challenge table)" in spicy
    assert "trivial encounters" in spicy               # punishing guidance, prompt-only


def test_context_without_difficulty_stays_clean():
    s = _session()
    assert "ENCOUNTER BUDGET" not in build_context(s.repo)
