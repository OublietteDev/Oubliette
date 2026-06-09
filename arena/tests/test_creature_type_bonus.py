"""Tests for creature-type bonus damage (src/combat/creature_type_bonus.py).

Tests cover:
- check_creature_type_bonus() with matching/non-matching/no bonus configured
- Multiple bonus types (e.g., ["undead", "fiend"])
- Integration: attack-based bonus damage vs matching creature type
- Integration: attack-based no bonus vs non-matching type
- Integration: save-based bonus damage vs matching creature type
"""

import pytest
from unittest.mock import patch

from arena.models.character import Creature, CreatureType
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action, ActionType, TargetType, Attack, DamageRoll, DamageType,
    SavingThrowEffect,
)
from arena.combat.creature_type_bonus import check_creature_type_bonus
from arena.combat.actions import resolve_attack_damage, resolve_effect, AttackHitResult
from arena.combat.events import CombatEventType
from arena.grid.hexgrid import HexGrid
from arena.grid.coordinates import HexCoord


# ── Test Helpers ──────────────────────────────────────────────────────


def _make_creature(
    name: str = "Test",
    creature_type: CreatureType = CreatureType.HUMANOID,
    armor_class: int = 10,
    max_hp: int = 50,
) -> Creature:
    """Create a minimal creature for testing."""
    return Creature(
        name=name,
        creature_type=creature_type,
        max_hit_points=max_hp,
        armor_class=armor_class,
        ability_scores=AbilityScores(
            strength=14,
            dexterity=10,
            constitution=10,
            intelligence=10,
            wisdom=10,
            charisma=14,
        ),
        speed={"walk": 30},
        proficiency_bonus=2,
    )


def _smite_action() -> Action:
    """A Divine Smite-like attack with creature type bonus vs undead/fiend."""
    return Action(
        name="Divine Smite Strike",
        description="Melee attack with bonus vs undead/fiend",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=5,
        attack=Attack(
            name="Longsword",
            attack_type="melee_weapon",
            ability="strength",
            reach=5,
            damage=[DamageRoll(dice="2d8", damage_type=DamageType.RADIANT, bonus=0)],
        ),
        creature_type_bonus_damage="1d8",
        creature_type_bonus_types=["undead", "fiend"],
    )


def _save_action_with_bonus() -> Action:
    """A save-based action with creature type bonus vs undead."""
    return Action(
        name="Sunbeam",
        description="Radiant beam with bonus vs undead",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=60,
        saving_throw=SavingThrowEffect(
            ability="constitution",
            dc=15,
            damage_on_fail=[
                DamageRoll(dice="6d8", damage_type=DamageType.RADIANT),
            ],
            damage_on_success="half",
        ),
        creature_type_bonus_damage="2d8",
        creature_type_bonus_types=["undead", "ooze"],
    )


# ── Unit Tests: check_creature_type_bonus ─────────────────────────────


class TestCheckCreatureTypeBonus:
    """Tests for the pure check_creature_type_bonus() function."""

    def test_matching_type_returns_bonus_dice(self):
        action = _smite_action()
        target = _make_creature(creature_type=CreatureType.UNDEAD)
        result = check_creature_type_bonus(action, target)
        assert result == "1d8"

    def test_second_matching_type_returns_bonus_dice(self):
        action = _smite_action()
        target = _make_creature(creature_type=CreatureType.FIEND)
        result = check_creature_type_bonus(action, target)
        assert result == "1d8"

    def test_non_matching_type_returns_none(self):
        action = _smite_action()
        target = _make_creature(creature_type=CreatureType.HUMANOID)
        result = check_creature_type_bonus(action, target)
        assert result is None

    def test_no_bonus_configured_returns_none(self):
        """Action with no creature_type_bonus fields returns None."""
        action = Action(
            name="Normal Attack",
            description="Just a regular attack",
            attack=Attack(
                name="Sword",
                attack_type="melee_weapon",
                ability="strength",
                damage=[DamageRoll(dice="1d8", damage_type=DamageType.SLASHING)],
            ),
        )
        target = _make_creature(creature_type=CreatureType.UNDEAD)
        result = check_creature_type_bonus(action, target)
        assert result is None

    def test_bonus_damage_set_but_no_types_returns_none(self):
        """Having bonus_damage but empty types list returns None."""
        action = Action(
            name="Partial Config",
            description="Has dice but no types",
            creature_type_bonus_damage="1d8",
            creature_type_bonus_types=[],
        )
        target = _make_creature(creature_type=CreatureType.UNDEAD)
        result = check_creature_type_bonus(action, target)
        assert result is None

    def test_types_set_but_no_bonus_damage_returns_none(self):
        """Having types but no bonus_damage returns None."""
        action = Action(
            name="Partial Config",
            description="Has types but no dice",
            creature_type_bonus_damage=None,
            creature_type_bonus_types=["undead"],
        )
        target = _make_creature(creature_type=CreatureType.UNDEAD)
        result = check_creature_type_bonus(action, target)
        assert result is None

    def test_case_insensitive_matching(self):
        """Bonus types are matched case-insensitively."""
        action = Action(
            name="Mixed Case",
            description="Mixed case types",
            creature_type_bonus_damage="1d6",
            creature_type_bonus_types=["Undead", "FIEND"],
        )
        target = _make_creature(creature_type=CreatureType.UNDEAD)
        result = check_creature_type_bonus(action, target)
        assert result == "1d6"

    def test_multiple_types_only_matching_triggers(self):
        """With multiple types configured, only matching target triggers."""
        action = _save_action_with_bonus()  # undead + ooze
        # Dragon is not in the list
        target = _make_creature(creature_type=CreatureType.DRAGON)
        result = check_creature_type_bonus(action, target)
        assert result is None

        # Ooze IS in the list
        target_ooze = _make_creature(creature_type=CreatureType.OOZE)
        result = check_creature_type_bonus(action, target_ooze)
        assert result == "2d8"


# ── Integration Tests: Attack-based bonus ─────────────────────────────


class TestAttackCreatureTypeBonus:
    """Integration tests for creature type bonus in resolve_attack_damage()."""

    @patch("arena.combat.actions.roll_expression", return_value=(5, [5]))
    def test_attack_vs_undead_adds_bonus_damage(self, mock_roll_expr):
        """Hitting an undead target should add creature type bonus damage."""
        attacker = _make_creature(name="Paladin")
        target = _make_creature(name="Zombie", creature_type=CreatureType.UNDEAD, max_hp=100)

        action = _smite_action()
        attack = action.attack

        # Build a hit result (simulating a successful hit)
        hit_result = AttackHitResult(
            hit=True,
            critical=False,
            natural_roll=15,
            modifier=4,
            total_roll=19,
            target_ac=10,
            effective_advantage=0,
            events=[],
            attacker=attacker,
            attacker_id="paladin_1",
            target=target,
            target_id="zombie_1",
            action=action,
            attack=attack,
            combatants={"paladin_1": attacker, "zombie_1": target},
        )

        with patch("arena.combat.actions.roll_damage", return_value=(10, [{"dice": "2d8", "total": 10, "type": "radiant"}])):
            result = resolve_attack_damage(hit_result)

        # Should have events: damage event + creature type bonus INFO
        info_events = [
            e for e in result.events
            if e.event_type == CombatEventType.INFO
            and "bonus damage vs undead" in e.message
        ]
        assert len(info_events) == 1
        assert "5 bonus damage vs undead" in info_events[0].message

    @patch("arena.combat.actions.roll_expression", return_value=(5, [5]))
    def test_attack_vs_humanoid_no_bonus(self, mock_roll_expr):
        """Hitting a humanoid (non-matching) should NOT add bonus damage."""
        attacker = _make_creature(name="Paladin")
        target = _make_creature(name="Bandit", creature_type=CreatureType.HUMANOID, max_hp=100)

        action = _smite_action()

        hit_result = AttackHitResult(
            hit=True,
            critical=False,
            natural_roll=15,
            modifier=4,
            total_roll=19,
            target_ac=10,
            effective_advantage=0,
            events=[],
            attacker=attacker,
            attacker_id="paladin_1",
            target=target,
            target_id="bandit_1",
            action=action,
            attack=action.attack,
            combatants={"paladin_1": attacker, "bandit_1": target},
        )

        with patch("arena.combat.actions.roll_damage", return_value=(10, [{"dice": "2d8", "total": 10, "type": "radiant"}])):
            result = resolve_attack_damage(hit_result)

        # Should NOT have creature type bonus event
        info_events = [
            e for e in result.events
            if e.event_type == CombatEventType.INFO
            and "bonus damage" in e.message
        ]
        assert len(info_events) == 0

    @patch("arena.combat.actions.roll_expression", return_value=(4, [4]))
    def test_attack_vs_fiend_adds_bonus(self, mock_roll_expr):
        """Hitting a fiend (second matching type) should add bonus."""
        attacker = _make_creature(name="Paladin")
        target = _make_creature(name="Imp", creature_type=CreatureType.FIEND, max_hp=100)

        action = _smite_action()

        hit_result = AttackHitResult(
            hit=True,
            critical=False,
            natural_roll=15,
            modifier=4,
            total_roll=19,
            target_ac=10,
            effective_advantage=0,
            events=[],
            attacker=attacker,
            attacker_id="paladin_1",
            target=target,
            target_id="imp_1",
            action=action,
            attack=action.attack,
            combatants={"paladin_1": attacker, "imp_1": target},
        )

        with patch("arena.combat.actions.roll_damage", return_value=(10, [{"dice": "2d8", "total": 10, "type": "radiant"}])):
            result = resolve_attack_damage(hit_result)

        info_events = [
            e for e in result.events
            if e.event_type == CombatEventType.INFO
            and "bonus damage vs fiend" in e.message
        ]
        assert len(info_events) == 1

    def test_miss_does_not_add_bonus(self):
        """A miss should not trigger creature type bonus."""
        attacker = _make_creature(name="Paladin")
        target = _make_creature(name="Zombie", creature_type=CreatureType.UNDEAD, max_hp=100)

        action = _smite_action()

        hit_result = AttackHitResult(
            hit=False,
            critical=False,
            natural_roll=3,
            modifier=4,
            total_roll=7,
            target_ac=15,
            effective_advantage=0,
            events=[],
            attacker=attacker,
            attacker_id="paladin_1",
            target=target,
            target_id="zombie_1",
            action=action,
            attack=action.attack,
            combatants={"paladin_1": attacker, "zombie_1": target},
        )

        result = resolve_attack_damage(hit_result)

        info_events = [
            e for e in result.events
            if e.event_type == CombatEventType.INFO
            and "bonus damage" in e.message
        ]
        assert len(info_events) == 0


# ── Integration Tests: Save-based bonus ───────────────────────────────


class TestSaveCreatureTypeBonus:
    """Integration tests for creature type bonus in resolve_effect()."""

    def test_save_vs_undead_adds_bonus_damage(self):
        """Save-based action vs undead should add creature type bonus damage."""
        user = _make_creature(name="Cleric")
        target = _make_creature(name="Skeleton", creature_type=CreatureType.UNDEAD, max_hp=100)
        action = _save_action_with_bonus()

        grid = HexGrid(15, 15)
        grid.place_creature(HexCoord(5, 5), "cleric_1", user.size)
        grid.place_creature(HexCoord(7, 5), "skeleton_1", target.size)

        # Patch roll_die so save fails (roll low), and roll_expression for damage
        with patch("arena.combat.actions.roll_die", return_value=2), \
             patch("arena.combat.actions.roll_expression", return_value=(10, [10])):
            result = resolve_effect(
                user, "cleric_1", target, "skeleton_1",
                action, grid,
                combatants={"cleric_1": user, "skeleton_1": target},
            )

        info_events = [
            e for e in result.events
            if e.event_type == CombatEventType.INFO
            and "bonus damage vs undead" in e.message
        ]
        assert len(info_events) == 1

    def test_save_vs_humanoid_no_bonus(self):
        """Save-based action vs humanoid should NOT add bonus damage."""
        user = _make_creature(name="Cleric")
        target = _make_creature(name="Bandit", creature_type=CreatureType.HUMANOID, max_hp=100)
        action = _save_action_with_bonus()

        grid = HexGrid(15, 15)
        grid.place_creature(HexCoord(5, 5), "cleric_1", user.size)
        grid.place_creature(HexCoord(7, 5), "bandit_1", target.size)

        with patch("arena.combat.actions.roll_die", return_value=2), \
             patch("arena.combat.actions.roll_expression", return_value=(10, [10])):
            result = resolve_effect(
                user, "cleric_1", target, "bandit_1",
                action, grid,
                combatants={"cleric_1": user, "bandit_1": target},
            )

        info_events = [
            e for e in result.events
            if e.event_type == CombatEventType.INFO
            and "bonus damage" in e.message
        ]
        assert len(info_events) == 0
