"""Tests for damage calculation and application."""

import pytest
from unittest.mock import patch
from arena.combat.damage import roll_damage, apply_damage
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import DamageRoll, DamageType
from arena.models.character import Creature


def _make_creature(hp=20, strength=16, dexterity=14):
    """Create a simple creature for testing."""
    return Creature(
        name="Test Creature",
        max_hit_points=hp,
        current_hit_points=hp,
        ability_scores=AbilityScores(strength=strength, dexterity=dexterity),
    )


class TestRollDamage:
    """Tests for roll_damage function."""

    @patch("arena.combat.damage.roll_expression")
    def test_basic_damage_roll(self, mock_roll):
        mock_roll.return_value = (5, [5])
        attacker = _make_creature(strength=16)
        damage_rolls = [
            DamageRoll(dice="1d8", damage_type=DamageType.SLASHING, ability_modifier="strength"),
        ]
        total, details = roll_damage(damage_rolls, attacker)
        # 5 (dice) + 3 (str mod) = 8
        assert total == 8
        assert len(details) == 1
        assert details[0]["ability_bonus"] == 3
        assert details[0]["damage_type"] == "slashing"

    @patch("arena.combat.damage.roll_expression")
    def test_critical_doubles_dice(self, mock_roll):
        mock_roll.return_value = (4, [4])
        attacker = _make_creature(strength=16)
        damage_rolls = [
            DamageRoll(dice="1d8", damage_type=DamageType.SLASHING, ability_modifier="strength"),
        ]
        total, details = roll_damage(damage_rolls, attacker, is_critical=True)
        # 4 + 4 (doubled dice) + 3 (str mod, not doubled) = 11
        assert total == 11
        assert mock_roll.call_count == 2  # Called twice for critical

    @patch("arena.combat.damage.roll_expression")
    def test_damage_with_flat_bonus(self, mock_roll):
        mock_roll.return_value = (3, [3])
        attacker = _make_creature()
        damage_rolls = [
            DamageRoll(dice="1d6", damage_type=DamageType.FIRE, bonus=2),
        ]
        total, details = roll_damage(damage_rolls, attacker)
        # 3 (dice) + 2 (bonus) = 5
        assert total == 5
        assert details[0]["bonus"] == 2

    @patch("arena.combat.damage.roll_expression")
    def test_multiple_damage_rolls(self, mock_roll):
        mock_roll.side_effect = [(3, [3]), (4, [4])]
        attacker = _make_creature()
        damage_rolls = [
            DamageRoll(dice="1d6", damage_type=DamageType.SLASHING),
            DamageRoll(dice="1d4", damage_type=DamageType.FIRE),
        ]
        total, details = roll_damage(damage_rolls, attacker)
        assert total == 7
        assert len(details) == 2

    @patch("arena.combat.damage.roll_expression")
    def test_damage_minimum_zero(self, mock_roll):
        mock_roll.return_value = (1, [1])
        attacker = _make_creature(strength=6)  # -2 modifier
        damage_rolls = [
            DamageRoll(dice="1d4", damage_type=DamageType.BLUDGEONING, bonus=-3, ability_modifier="strength"),
        ]
        total, details = roll_damage(damage_rolls, attacker)
        # 1 (dice) + (-3) bonus + (-2) str mod = -4, floored to 0
        assert total == 0


class TestApplyDamage:
    """Tests for apply_damage function."""

    def test_basic_damage(self):
        target = _make_creature(hp=20)
        event, _ = apply_damage(target, 8, "slashing")
        assert target.current_hit_points == 12
        assert event.event_type == CombatEventType.DAMAGE
        assert event.details["damage"] == 8
        assert event.details["old_hp"] == 20
        assert event.details["new_hp"] == 12
        assert event.details["knocked_out"] is False

    def test_damage_floors_at_zero(self):
        target = _make_creature(hp=5)
        event, _ = apply_damage(target, 10, "fire")
        assert target.current_hit_points == 0
        assert event.details["new_hp"] == 0

    def test_knocked_unconscious(self):
        target = _make_creature(hp=3)
        event, _ = apply_damage(target, 5, "slashing")
        assert target.current_hit_points == 0
        assert event.details["knocked_out"] is True
        assert "unconscious" in event.message

    def test_damage_to_already_unconscious(self):
        target = _make_creature(hp=20)
        target.current_hit_points = 0
        event, _ = apply_damage(target, 5, "slashing")
        assert target.current_hit_points == 0
        # Not "knocked out" since already at 0
        assert event.details["knocked_out"] is False

    def test_damage_message_includes_type(self):
        target = _make_creature(hp=20)
        event, _ = apply_damage(target, 7, "fire")
        assert "fire" in event.message
        assert "7" in event.message
