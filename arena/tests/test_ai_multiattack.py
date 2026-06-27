"""Tests for AI Multiattack (Brain — Slice 1).

A monster with a Multiattack stat-block ability (extra_attack_count > 1)
should plan ALL of its swings, not just one — the engine already enforces
the action economy (only the last swing spends the action). And when an
early swing drops its target, the remaining swings re-target a living foe
instead of flailing at a corpse.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from arena.ai.controller import AIController, TurnStepType
from arena.ai.executor import _resolve_attack_target
from arena.combat.manager import CombatManager
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature, Feature
from arena.models.monster import Monster
from arena.models.encounter import Encounter, CombatantEntry


# ── Helpers ──────────────────────────────────────────────────────────


def _claw():
    return Action(
        name="Claw",
        description="Melee weapon attack",
        action_type=ActionType.ACTION,
        attack=Attack(
            name="Claw",
            attack_type="melee_weapon",
            ability="strength",
            reach=5,
            damage=[
                DamageRoll(
                    dice="1d6",
                    damage_type=DamageType.SLASHING,
                    ability_modifier="strength",
                )
            ],
        ),
    )


def _monster(name="Beast", extra_attacks=0):
    """An AI monster, optionally with a Multiattack ability."""
    special = []
    if extra_attacks:
        special = [Feature(
            name="Multiattack",
            description=f"The creature makes {extra_attacks} attacks.",
            extra_attack_count=extra_attacks,
        )]
    return Monster(
        name=name,
        max_hit_points=40,
        armor_class=13,
        ability_scores=AbilityScores(strength=16, dexterity=12),
        proficiency_bonus=2,
        is_player_controlled=False,
        ai_profile="berserker",  # aggressive, melee, never flees → will attack
        actions=[_claw()],
        special_abilities=special,
    )


def _player(name="Hero", pos_hp=30):
    return Creature(
        name=name,
        max_hit_points=pos_hp,
        armor_class=14,
        ability_scores=AbilityScores(strength=14, dexterity=12),
        proficiency_bonus=2,
        is_player_controlled=True,
        actions=[_claw()],
    )


def _start(combatants):
    enc = Encounter(name="MA Test", grid_width=12, grid_height=12, combatants=combatants)
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", return_value=10):
        cm.roll_initiative()
    cm.begin_combat()
    return cm


def _advance_to(cm, creature_id):
    """End turns until ``creature_id`` is the active combatant."""
    for _ in range(len(cm.combatants) + 1):
        if cm.active_combatant and cm.active_combatant.creature_id == creature_id:
            return
        cm.end_turn()
    raise AssertionError(f"never reached {creature_id}'s turn")


def _count_attacks(plan):
    return sum(1 for s in plan.steps if s.step_type == TurnStepType.EXECUTE_ATTACK)


# ── Plan-level tests ─────────────────────────────────────────────────


def test_multiattack_monster_plans_all_swings():
    """A monster with extra_attack_count=3 plans three attack swings."""
    cm = _start([
        CombatantEntry(creature_id="beast", creature_data=_monster(extra_attacks=3),
                       team="enemy", starting_position=(3, 3)),
        CombatantEntry(creature_id="hero", creature_data=_player(),
                       team="player", starting_position=(4, 3)),  # adjacent
    ])
    _advance_to(cm, "beast")

    plan = AIController(randomness=0.0).plan_turn(cm)
    assert _count_attacks(plan) == 3


def test_single_attack_monster_plans_one_swing():
    """A monster with no Multiattack still plans exactly one swing."""
    cm = _start([
        CombatantEntry(creature_id="beast", creature_data=_monster(extra_attacks=0),
                       team="enemy", starting_position=(3, 3)),
        CombatantEntry(creature_id="hero", creature_data=_player(),
                       team="player", starting_position=(4, 3)),
    ])
    _advance_to(cm, "beast")

    plan = AIController(randomness=0.0).plan_turn(cm)
    assert _count_attacks(plan) == 1


# ── Re-target (executor helper) tests ────────────────────────────────


def test_resolve_target_keeps_valid_target():
    """When the planned target is alive and hostile, keep it."""
    cm = _start([
        CombatantEntry(creature_id="beast", creature_data=_monster(extra_attacks=3),
                       team="enemy", starting_position=(3, 3)),
        CombatantEntry(creature_id="hero", creature_data=_player(),
                       team="player", starting_position=(4, 3)),
    ])
    _advance_to(cm, "beast")
    assert _resolve_attack_target(cm, "hero") == "hero"


def test_resolve_target_redirects_from_downed():
    """When the planned target is unconscious, redirect to a living enemy."""
    cm = _start([
        CombatantEntry(creature_id="beast", creature_data=_monster(extra_attacks=3),
                       team="enemy", starting_position=(3, 3)),
        CombatantEntry(creature_id="hero", creature_data=_player("Hero"),
                       team="player", starting_position=(4, 3)),
        CombatantEntry(creature_id="ally", creature_data=_player("Ally"),
                       team="player", starting_position=(3, 4)),
    ])
    _advance_to(cm, "beast")

    # Drop the primary target.
    cm.combatants["hero"].creature.current_hit_points = 0
    assert cm.combatants["hero"].creature.is_conscious is False

    redirected = _resolve_attack_target(cm, "hero")
    assert redirected == "ally"


def test_resolve_target_none_when_no_enemies_left():
    """No living enemies → no target (swing is skipped, not flailed)."""
    cm = _start([
        CombatantEntry(creature_id="beast", creature_data=_monster(extra_attacks=3),
                       team="enemy", starting_position=(3, 3)),
        CombatantEntry(creature_id="hero", creature_data=_player(),
                       team="player", starting_position=(4, 3)),
    ])
    _advance_to(cm, "beast")
    cm.combatants["hero"].creature.current_hit_points = 0
    assert _resolve_attack_target(cm, "hero") is None
