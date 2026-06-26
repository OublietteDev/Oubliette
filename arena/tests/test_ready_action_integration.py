"""Integration tests for the Ready action firing through real combat paths
(D-ACT-1).

Phase 5l only ever fired CREATURE_MOVES and resolved readied *attacks*. D-ACT-1
wires the remaining triggers — CREATURE_ATTACKS (at complete_attack),
CREATURE_CASTS (at the cast chokepoint), CREATURE_ENTERS_RANGE (range-gated, on
movement) — and resolves readied *spells*, not just attacks.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from arena.combat.manager import CombatManager
from arena.combat.ready_action import TriggerType
from arena.combat.conditions import has_condition
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action, ActionType, Attack, DamageRoll, DamageType,
    SavingThrowEffect, TargetType,
)
from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.models.encounter import Encounter, CombatantEntry
from arena.grid.coordinates import HexCoord


# ── Action builders ──────────────────────────────────────────────────

def _sword() -> Action:
    return Action(
        name="Sword", description="Melee weapon attack",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        attack=Attack(
            name="Sword", attack_type="melee_weapon", ability="strength",
            reach=5,
            damage=[DamageRoll(dice="1d6", damage_type=DamageType.SLASHING,
                               ability_modifier="strength")],
        ),
    )


def _firebolt() -> Action:
    """A spell attack cantrip — both an attack and a cast."""
    return Action(
        name="Fire Bolt", description="Ranged spell attack",
        action_type=ActionType.ACTION, spell_level=0,
        target_type=TargetType.ONE_CREATURE, range=120,
        attack=Attack(
            name="Fire Bolt", attack_type="ranged_spell", ability="intelligence",
            reach=5, range_normal=120,
            damage=[DamageRoll(dice="1d10", damage_type=DamageType.FIRE)],
        ),
    )


def _hold_person() -> Action:
    """A single-target save spell (no attack) — for readied-spell resolution."""
    return Action(
        name="Hold Person", description="WIS save or paralyzed",
        action_type=ActionType.ACTION, spell_level=2,
        target_type=TargetType.ONE_ENEMY, range=60,
        requires_concentration=True,
        saving_throw=SavingThrowEffect(
            ability="wisdom", dc=20,  # high DC so the target fails
            conditions_on_fail=["paralyzed"],
        ),
    )


def _fireball() -> Action:
    """A placed radius burst — releases centered on the triggering creature."""
    return Action(
        name="Fireball", description="DEX save, 8d6 fire in 20ft",
        action_type=ActionType.ACTION, spell_level=3,
        target_type=TargetType.AREA_SPHERE, range=150, area_size=20,
        saving_throw=SavingThrowEffect(
            ability="dexterity", dc=20,
            damage_on_fail=[DamageRoll(dice="8d6", damage_type=DamageType.FIRE)],
            damage_on_success="half",
        ),
    )


def _make_creature(name, actions, is_player, hp=30, spell_slots=None):
    return Creature(
        name=name, max_hit_points=hp,
        ability_scores=AbilityScores(strength=16, dexterity=12,
                                     intelligence=16, wisdom=8),
        proficiency_bonus=3, speed={"walk": 30},
        is_player_controlled=is_player, actions=actions,
        spell_slots=spell_slots or {},
    )


def _setup(holder_actions, enemy_actions, holder_pos, enemy_pos,
           holder_slots=None, extras=None):
    combatants = [
        CombatantEntry(
            creature_id="holder",
            creature_data=_make_creature(
                "Holder", holder_actions, True, spell_slots=holder_slots),
            team="player", starting_position=holder_pos,
        ),
        CombatantEntry(
            creature_id="enemy",
            creature_data=_make_creature("Enemy", enemy_actions, False),
            team="enemy", starting_position=enemy_pos,
        ),
    ]
    for cid, pos in (extras or []):
        combatants.append(CombatantEntry(
            creature_id=cid,
            creature_data=_make_creature(cid.title(), [_sword()], False),
            team="enemy", starting_position=pos,
        ))
    encounter = Encounter(
        name="Test", grid_width=14, grid_height=14, combatants=combatants)
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    cm.roll_initiative()
    cm.begin_combat()
    return cm


def _to(cm, creature_id):
    for _ in range(20):
        a = cm.active_combatant
        if a and a.creature_id == creature_id:
            return a
        cm.end_turn()
    return None


@pytest.fixture(autouse=True)
def init_pygame():
    import pygame
    pygame.init()
    pygame.display.set_mode((1, 1))
    yield
    pygame.quit()


# ── CREATURE_ATTACKS ──────────────────────────────────────────────────

def test_readied_attack_fires_when_enemy_attacks():
    cm = _setup([_sword()], [_sword()], holder_pos=(4, 4), enemy_pos=(5, 4))

    _to(cm, "holder")
    cm.execute_ready_action(
        _sword(), TriggerType.CREATURE_ATTACKS, None, "When an enemy attacks")
    assert "holder" in cm.readied_actions
    cm.end_turn()

    enemy = _to(cm, "enemy")
    assert enemy is not None
    cm.select_action(enemy.creature.actions[0])
    with patch("arena.combat.actions.roll_die", return_value=18):
        cm.execute_attack("holder")

    # The holder's readied Sword released as a reaction at the attacker.
    assert cm.reaction_used.get("holder") is True
    assert "holder" not in cm.readied_actions


# ── CREATURE_CASTS ────────────────────────────────────────────────────

def test_readied_action_fires_when_enemy_casts():
    cm = _setup([_sword()], [_firebolt()], holder_pos=(4, 4), enemy_pos=(5, 4))

    _to(cm, "holder")
    cm.execute_ready_action(
        _sword(), TriggerType.CREATURE_CASTS, None, "When an enemy casts")
    cm.end_turn()

    enemy = _to(cm, "enemy")
    assert enemy is not None
    cm.select_action(enemy.creature.actions[0])  # Fire Bolt
    with patch("arena.combat.actions.roll_die", return_value=10):
        cm.execute_attack("holder")

    assert cm.reaction_used.get("holder") is True
    assert "holder" not in cm.readied_actions


# ── CREATURE_ENTERS_RANGE (range-gated) ───────────────────────────────

def test_readied_action_fires_when_enemy_enters_reach():
    # Enemy starts 2 hexes away (out of a 5ft sword reach), moves adjacent.
    cm = _setup([_sword()], [_sword()], holder_pos=(4, 4), enemy_pos=(6, 4))

    _to(cm, "holder")
    cm.execute_ready_action(
        _sword(), TriggerType.CREATURE_ENTERS_RANGE, None, "Brace")
    cm.end_turn()

    enemy = _to(cm, "enemy")
    assert enemy is not None
    with patch("arena.combat.actions.roll_die", return_value=18):
        moved = cm.try_move(HexCoord(5, 4))  # now adjacent to the holder
    assert moved

    assert cm.reaction_used.get("holder") is True
    assert "holder" not in cm.readied_actions


def test_enters_range_does_not_fire_while_out_of_reach():
    # Enemy moves but stays 2 hexes out of a melee reach — no trigger.
    cm = _setup([_sword()], [_sword()], holder_pos=(4, 4), enemy_pos=(8, 4))

    _to(cm, "holder")
    cm.execute_ready_action(
        _sword(), TriggerType.CREATURE_ENTERS_RANGE, None, "Brace")
    cm.end_turn()

    enemy = _to(cm, "enemy")
    assert enemy is not None
    moved = cm.try_move(HexCoord(7, 4))  # still 3 hexes from the holder
    assert moved

    assert cm.reaction_used.get("holder") is not True
    assert "holder" in cm.readied_actions  # still waiting


# ── Readied SPELL resolves (not just attacks) ─────────────────────────

def test_readied_spell_resolves_on_trigger():
    cm = _setup([_hold_person()], [_sword()], holder_pos=(4, 4),
                enemy_pos=(5, 4), holder_slots={1: 2, 2: 2})

    _to(cm, "holder")
    cm.execute_ready_action(
        _hold_person(), TriggerType.CREATURE_MOVES, None, "When an enemy moves")
    cm.end_turn()

    enemy = _to(cm, "enemy")
    assert enemy is not None
    # The enemy moves within the holder's range → readied Hold Person releases.
    with patch("arena.combat.actions.roll_die", return_value=1):  # enemy fails
        cm.try_move(HexCoord(5, 5))

    # The spell resolved: the mover is paralyzed, and the holder is now
    # concentrating on Hold Person.
    assert has_condition(cm.combatants["enemy"].creature, Condition.PARALYZED)
    assert has_condition(cm.combatants["holder"].creature, Condition.CONCENTRATING)
    assert "holder" not in cm.readied_actions


def test_readied_fireball_hits_whole_area():
    # Two enemies cluster; the holder readies a Fireball "when an enemy moves".
    # On release it should burst — hitting BOTH, not just the mover (the bug
    # OublietteDev caught: a readied AoE resolving as a single-hex hit).
    cm = _setup([_fireball()], [_sword()], holder_pos=(4, 4), enemy_pos=(8, 4),
                holder_slots={3: 2}, extras=[("enemy2", (8, 5))])

    _to(cm, "holder")
    cm.execute_ready_action(
        _fireball(), TriggerType.CREATURE_MOVES, None, "When an enemy moves")
    cm.end_turn()

    hp1 = cm.combatants["enemy"].creature.current_hit_points
    hp2 = cm.combatants["enemy2"].creature.current_hit_points

    enemy = _to(cm, "enemy")
    assert enemy is not None
    with patch("arena.combat.actions.roll_die", return_value=4):  # enemies fail
        cm.try_move(HexCoord(7, 4))  # mover stays beside enemy2

    # Both enemies took fire damage — the burst, not a single-target hit.
    assert cm.combatants["enemy"].creature.current_hit_points < hp1
    assert cm.combatants["enemy2"].creature.current_hit_points < hp2


def _multi_dart() -> Action:
    """Magic Missile shape: target_count=3 with the 3 darts bundled into the
    attack's damage list (so one resolve_attack already applies all three)."""
    return Action(
        name="Magic Missile", description="", action_type=ActionType.ACTION,
        spell_level=1, target_type=TargetType.ONE_CREATURE, range=120,
        target_count=3,
        attack=Attack(
            name="Magic Missile", attack_type="ranged_spell",
            ability="intelligence", reach=5, range_normal=120,
            damage=[DamageRoll(dice="1d4", damage_type=DamageType.FORCE)] * 3,
        ),
    )


def test_readied_attack_resolves_once_not_per_target_count(monkeypatch):
    # A readied multi-dart spell (target_count=3) must resolve as ONE attack —
    # its darts are bundled into the damage list, so looping would 3x it.
    cm = _setup([_multi_dart()], [_sword()], holder_pos=(4, 4), enemy_pos=(5, 4),
                holder_slots={1: 3})
    _to(cm, "holder")
    cm.execute_ready_action(
        _multi_dart(), TriggerType.CREATURE_MOVES, None, "x")
    cm.end_turn()

    enemy = _to(cm, "enemy")
    assert enemy is not None

    import arena.combat.actions as A
    calls = {"n": 0}
    orig = A.resolve_attack

    def _counting(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)

    monkeypatch.setattr(A, "resolve_attack", _counting)
    cm.try_move(HexCoord(5, 5))
    assert calls["n"] == 1


def test_readied_paralysis_halts_the_mover():
    # A held Hold Person that paralyzes a creature mid-move must stop its
    # remaining movement (the AI walks a path hex-by-hex via try_move).
    cm = _setup([_hold_person()], [_sword()], holder_pos=(4, 4),
                enemy_pos=(8, 4), holder_slots={1: 2, 2: 2})
    _to(cm, "holder")
    cm.execute_ready_action(
        _hold_person(), TriggerType.CREATURE_MOVES, None, "x")
    cm.end_turn()

    enemy = _to(cm, "enemy")
    assert enemy is not None
    # Step 1: the move lands and triggers Hold Person → paralyzed.
    with patch("arena.combat.actions.roll_die", return_value=1):
        assert cm.try_move(HexCoord(7, 4)) is True
    assert has_condition(cm.combatants["enemy"].creature, Condition.PARALYZED)

    # Step 2: now paralyzed (speed 0) → the next step is refused, mover frozen.
    pos = cm.combatants["enemy"].position
    assert cm.try_move(HexCoord(6, 4)) is False
    assert cm.combatants["enemy"].position == pos
