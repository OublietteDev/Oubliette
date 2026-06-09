"""Tests for multi-target and chain effect wiring in CombatManager.

Verifies that:
- Magic Missile pattern (target_count > 1) resolves multiple times
- Chain Lightning pattern resolves primary + secondary chain targets
- Single-target spells still work normally
- Upcast adds targets via upcast_target_count
- Multi-target attacks (Eldritch Blast beams) roll separately
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from arena.combat.manager import CombatManager
from arena.combat.events import CombatEventType
from arena.grid.coordinates import HexCoord
from arena.models.actions import (
    Action, ActionType, Attack, DamageRoll, DamageType,
    SavingThrowEffect, TargetType,
)
from arena.models.abilities import AbilityScores
from arena.models.character import Creature, PlayerCharacter
from arena.models.encounter import CombatantEntry, Encounter


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_creature(name: str, hp: int = 50, team: str = "player") -> Creature:
    return Creature(name=name, max_hit_points=hp)


def _make_encounter(
    player_creature: Creature,
    enemy_creatures: list[tuple[str, Creature, tuple[int, int]]],
    player_pos: tuple[int, int] = (2, 2),
) -> Encounter:
    """Build a minimal encounter with one player and N enemies."""
    entries = [
        CombatantEntry(
            creature_id="player_inline",
            creature_data=player_creature,
            team="player",
            starting_position=player_pos,
        ),
    ]
    for eid, creature, pos in enemy_creatures:
        entries.append(CombatantEntry(
            creature_id=eid,
            creature_data=creature,
            team="enemy",
            starting_position=pos,
        ))
    return Encounter(
        name="Multi-target Test",
        grid_width=20,
        grid_height=15,
        combatants=entries,
    )


def _setup_combat(
    player_creature: Creature,
    enemy_creatures: list[tuple[str, Creature, tuple[int, int]]],
    player_pos: tuple[int, int] = (2, 2),
) -> tuple[CombatManager, str]:
    """Create a CombatManager and advance to the player's turn."""
    enc = _make_encounter(player_creature, enemy_creatures, player_pos)
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    cm.roll_initiative()
    cm.begin_combat()

    # Find the player combatant
    player_id = None
    for cid, c in cm.combatants.items():
        if c.team == "player":
            player_id = cid
            break

    # Advance until player's turn
    safety = 0
    while cm.active_combatant and cm.active_combatant.creature_id != player_id:
        cm.end_turn()
        safety += 1
        if safety > 20:
            break

    return cm, player_id


# ------------------------------------------------------------------
# Actions
# ------------------------------------------------------------------


def _magic_missile_action() -> Action:
    """Magic Missile: 3 darts (target_count=3), auto-hit save effect."""
    return Action(
        name="Magic Missile",
        description="3 darts of force damage",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=120,
        target_count=3,
        saving_throw=SavingThrowEffect(
            ability="dexterity",
            dc=99,  # Auto-fail so damage always applies
            damage_on_fail=[DamageRoll(dice="1d4+1", damage_type=DamageType.FORCE)],
            damage_on_success="none",
        ),
    )


def _chain_lightning_action() -> Action:
    """Chain Lightning: primary target + 3 chain targets within 30ft."""
    return Action(
        name="Chain Lightning",
        description="Lightning arcs between targets",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=150,
        chain_target_count=3,
        chain_range=30,
        saving_throw=SavingThrowEffect(
            ability="dexterity",
            dc=99,  # Auto-fail
            damage_on_fail=[DamageRoll(dice="10d8", damage_type=DamageType.LIGHTNING)],
            damage_on_success="half",
        ),
    )


def _fire_bolt_action() -> Action:
    """Fire Bolt: single target cantrip."""
    return Action(
        name="Fire Bolt",
        description="Ranged fire attack",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=120,
        target_count=1,
        saving_throw=SavingThrowEffect(
            ability="dexterity",
            dc=99,
            damage_on_fail=[DamageRoll(dice="1d10", damage_type=DamageType.FIRE)],
            damage_on_success="none",
        ),
    )


def _upcast_scorching_ray_action() -> Action:
    """Scorching Ray: 3 rays base, +1 per slot above 2nd (attack-based)."""
    return Action(
        name="Scorching Ray",
        description="3 rays of fire, +1 per slot above 2nd",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=120,
        target_count=3,
        spell_level=2,
        upcast_target_count=1,
        attack=Attack(
            name="Scorching Ray",
            attack_type="ranged_spell",
            ability="intelligence",
            damage=[DamageRoll(dice="2d6", damage_type=DamageType.FIRE)],
        ),
        resource_cost={"spell_slot_2": 1},
    )


def _eldritch_blast_action() -> Action:
    """Eldritch Blast: attack-based, target_count=2 (level 5+)."""
    return Action(
        name="Eldritch Blast",
        description="Two beams of force",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=120,
        target_count=2,
        cantrip_extra_targets=True,
        attack=Attack(
            name="Eldritch Blast",
            attack_type="ranged_spell",
            ability="charisma",
            damage=[DamageRoll(dice="1d10", damage_type=DamageType.FORCE)],
        ),
    )


# ------------------------------------------------------------------
# Tests: Multi-target effect (Magic Missile pattern)
# ------------------------------------------------------------------


class TestMultiTargetEffect:
    """Magic Missile: target_count=3 resolves 3 times against the same target."""

    def test_magic_missile_resolves_three_times(self):
        """Three darts should each resolve separately against the target."""
        wizard = _make_creature("Wizard", hp=50)
        wizard.actions = [_magic_missile_action()]

        cm, player_id = _setup_combat(
            wizard,
            [("goblin_inline", _make_creature("Goblin", hp=100), (5, 2))],
        )

        # Find enemy id
        enemy_id = None
        for cid, c in cm.combatants.items():
            if c.team == "enemy":
                enemy_id = cid
                break

        enemy_hp_before = cm.combatants[enemy_id].creature.current_hit_points
        cm.select_action(cm.combatants[player_id].creature.actions[0])
        result = cm.execute_effect(enemy_id)

        assert result is not None
        assert result.success

        # Count how many DAMAGE events were produced -- should be 3
        damage_events = [
            e for e in result.events
            if e.event_type == CombatEventType.DAMAGE
        ]
        assert len(damage_events) == 3

    def test_single_target_spell_still_works(self):
        """A spell with target_count=1 should resolve exactly once."""
        wizard = _make_creature("Wizard", hp=50)
        wizard.actions = [_fire_bolt_action()]

        cm, player_id = _setup_combat(
            wizard,
            [("goblin_inline", _make_creature("Goblin", hp=100), (5, 2))],
        )

        enemy_id = None
        for cid, c in cm.combatants.items():
            if c.team == "enemy":
                enemy_id = cid
                break

        cm.select_action(cm.combatants[player_id].creature.actions[0])
        result = cm.execute_effect(enemy_id)

        assert result is not None
        assert result.success

        damage_events = [
            e for e in result.events
            if e.event_type == CombatEventType.DAMAGE
        ]
        assert len(damage_events) == 1


# ------------------------------------------------------------------
# Tests: Chain effects
# ------------------------------------------------------------------


class TestChainEffectWiring:
    """Chain Lightning: primary + secondary chain targets."""

    def test_chain_lightning_hits_primary_and_secondaries(self):
        """Chain Lightning should resolve against primary + chain targets."""
        wizard = _make_creature("Wizard", hp=50)
        wizard.actions = [_chain_lightning_action()]

        # Place enemies close together so chain can reach
        enemies = [
            ("ogre_inline", _make_creature("Ogre", hp=100), (7, 2)),
            ("gob1_inline", _make_creature("Goblin1", hp=100), (7, 3)),
            ("gob2_inline", _make_creature("Goblin2", hp=100), (7, 4)),
            ("gob3_inline", _make_creature("Goblin3", hp=100), (8, 2)),
        ]

        cm, player_id = _setup_combat(wizard, enemies)

        # Find ogre as primary target
        ogre_id = None
        for cid, c in cm.combatants.items():
            if "ogre" in c.creature.name.lower():
                ogre_id = cid
                break

        cm.select_action(cm.combatants[player_id].creature.actions[0])
        result = cm.execute_effect(ogre_id)

        assert result is not None
        assert result.success

        # Should have damage events for primary + up to 3 chain targets = 4
        damage_events = [
            e for e in result.events
            if e.event_type == CombatEventType.DAMAGE
        ]
        assert len(damage_events) == 4  # 1 primary + 3 chain

    def test_chain_lightning_no_chain_targets_when_isolated(self):
        """If no creatures within chain range, only primary is hit."""
        wizard = _make_creature("Wizard", hp=50)
        wizard.actions = [_chain_lightning_action()]

        # Only one enemy, far from others
        enemies = [
            ("ogre_inline", _make_creature("Ogre", hp=100), (7, 2)),
        ]

        cm, player_id = _setup_combat(wizard, enemies)

        enemy_id = None
        for cid, c in cm.combatants.items():
            if c.team == "enemy":
                enemy_id = cid
                break

        cm.select_action(cm.combatants[player_id].creature.actions[0])
        result = cm.execute_effect(enemy_id)

        assert result is not None
        assert result.success

        damage_events = [
            e for e in result.events
            if e.event_type == CombatEventType.DAMAGE
        ]
        assert len(damage_events) == 1  # Only primary


# ------------------------------------------------------------------
# Tests: Upcast adds targets
# ------------------------------------------------------------------


class TestUpcastTargetCount:
    """Scorching Ray at 3rd level gets an extra ray (4 total via execute_attack)."""

    def test_upcast_adds_targets_in_effect(self):
        """An effect spell with upcast_target_count gains extra resolutions."""
        upcast_effect = Action(
            name="Upcast Bolts",
            description="3 bolts base, +1 per slot above 2nd",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_CREATURE,
            range=120,
            target_count=3,
            spell_level=2,
            upcast_target_count=1,
            saving_throw=SavingThrowEffect(
                ability="dexterity",
                dc=99,
                damage_on_fail=[DamageRoll(dice="2d6", damage_type=DamageType.FIRE)],
                damage_on_success="none",
            ),
            resource_cost={"spell_slot_2": 1},
        )
        wizard = PlayerCharacter(
            name="Wizard",
            max_hit_points=50,
            character_class="Wizard",
            actions=[upcast_effect],
            class_resources={"spell_slot_2": 1, "spell_slot_3": 1},
        )

        cm, player_id = _setup_combat(
            wizard,
            [("goblin_inline", _make_creature("Goblin", hp=200), (5, 2))],
        )

        enemy_id = None
        for cid, c in cm.combatants.items():
            if c.team == "enemy":
                enemy_id = cid
                break

        # Cast at 3rd level: 3 base + 1 extra = 4 bolts
        cm.select_action(
            cm.combatants[player_id].creature.actions[0],
            cast_level=3,
        )
        result = cm.execute_effect(enemy_id)

        assert result is not None
        assert result.success

        damage_events = [
            e for e in result.events
            if e.event_type == CombatEventType.DAMAGE
        ]
        assert len(damage_events) == 4  # 3 base + 1 upcast


# ------------------------------------------------------------------
# Tests: Multi-target attacks (Eldritch Blast)
# ------------------------------------------------------------------


class TestMultiTargetAttack:
    """Eldritch Blast with target_count=2 should produce two separate attack rolls."""

    def test_eldritch_blast_two_beams(self):
        """Two beams should each produce attack roll events."""
        warlock = Creature(
            name="Warlock",
            max_hit_points=50,
            proficiency_bonus=3,
            ability_scores=AbilityScores(
                strength=10, dexterity=14, constitution=12,
                intelligence=10, wisdom=12, charisma=18,
            ),
            actions=[_eldritch_blast_action()],
        )

        cm, player_id = _setup_combat(
            warlock,
            [("goblin_inline", _make_creature("Goblin", hp=100), (5, 2))],
        )

        enemy_id = None
        for cid, c in cm.combatants.items():
            if c.team == "enemy":
                enemy_id = cid
                break

        cm.select_action(cm.combatants[player_id].creature.actions[0])
        result = cm.execute_attack(enemy_id)

        assert result is not None

        # Count attack roll events (each beam produces one)
        attack_events = [
            e for e in result.events
            if e.event_type == CombatEventType.ATTACK_ROLL
        ]
        assert len(attack_events) == 2

    def test_single_attack_still_works(self):
        """An attack with target_count=1 resolves exactly once."""
        single_attack = Action(
            name="Longsword",
            description="Melee weapon attack",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_CREATURE,
            range=5,
            target_count=1,
            attack=Attack(
                name="Longsword",
                attack_type="melee_weapon",
                ability="strength",
                damage=[DamageRoll(dice="1d8", damage_type=DamageType.SLASHING)],
            ),
        )
        fighter = Creature(
            name="Fighter",
            max_hit_points=50,
            proficiency_bonus=3,
            ability_scores=AbilityScores(
                strength=18, dexterity=14, constitution=14,
                intelligence=10, wisdom=12, charisma=10,
            ),
            actions=[single_attack],
        )

        cm, player_id = _setup_combat(
            fighter,
            [("goblin_inline", _make_creature("Goblin", hp=100), (3, 2))],
        )

        enemy_id = None
        for cid, c in cm.combatants.items():
            if c.team == "enemy":
                enemy_id = cid
                break

        cm.select_action(cm.combatants[player_id].creature.actions[0])
        result = cm.execute_attack(enemy_id)

        assert result is not None

        attack_events = [
            e for e in result.events
            if e.event_type == CombatEventType.ATTACK_ROLL
        ]
        assert len(attack_events) == 1
