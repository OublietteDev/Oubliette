"""Tests for granting temporary hit points via action effects."""

from unittest.mock import patch

import pytest

from arena.combat.actions import resolve_effect
from arena.combat.events import CombatEventType
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, ActionType, TargetType
from arena.models.character import Creature


# ── Helpers ──────────────────────────────────────────────────────────


def _make_creature(name: str = "Fighter", hp: int = 40, temp_hp: int = 0) -> Creature:
    c = Creature(
        name=name,
        max_hit_points=hp,
        ability_scores=AbilityScores(),
        proficiency_bonus=2,
    )
    c.temporary_hit_points = temp_hp
    return c


def _temp_hp_action(expr: str = "5") -> Action:
    return Action(
        name="False Life",
        description="Grant temp HP.",
        action_type=ActionType.ACTION,
        target_type=TargetType.SELF,
        range=0,
        grants_temporary_hp=expr,
    )


def _resolve(user, target, action):
    return resolve_effect(
        user=user,
        user_id="user",
        target=target,
        target_id="target",
        action=action,
        grid=HexGrid(10, 10),
        combatants={},
        user_pos=HexCoord(0, 0),
        target_pos=HexCoord(0, 0),
    )


# ── Tests ────────────────────────────────────────────────────────────


class TestGrantTemporaryHP:
    def test_grants_flat_temp_hp(self):
        """A flat number grants that many temp HP."""
        target = _make_creature()
        action = _temp_hp_action("5")
        result = _resolve(target, target, action)

        assert result.success
        assert target.temporary_hit_points == 5
        assert any(
            e.details and e.details.get("temp_hp_granted") == 5
            for e in result.events
        )

    @patch("arena.combat.actions.roll_expression", return_value=(7, [3, 4]))
    def test_grants_dice_expression_temp_hp(self, mock_roll):
        """A dice expression grants the rolled amount."""
        target = _make_creature()
        action = _temp_hp_action("1d4+4")
        result = _resolve(target, target, action)

        assert result.success
        assert target.temporary_hit_points == 7

    def test_no_stack_higher_wins(self):
        """If target already has lower temp HP, replace with higher."""
        target = _make_creature(temp_hp=3)
        action = _temp_hp_action("8")
        result = _resolve(target, target, action)

        assert target.temporary_hit_points == 8

    def test_no_stack_lower_ignored(self):
        """If target already has higher temp HP, keep the existing value."""
        target = _make_creature(temp_hp=10)
        action = _temp_hp_action("3")
        result = _resolve(target, target, action)

        assert target.temporary_hit_points == 10
        # Event should mention the existing temp HP is higher
        assert any("already has 10" in e.message for e in result.events)

    def test_temp_hp_zero_to_positive(self):
        """Granting temp HP when target has 0 temp HP sets it correctly."""
        target = _make_creature(temp_hp=0)
        action = _temp_hp_action("12")
        result = _resolve(target, target, action)

        assert target.temporary_hit_points == 12

    def test_combined_with_healing(self):
        """An action can both heal and grant temp HP."""
        target = _make_creature(hp=40)
        target.current_hit_points = 20  # Damaged
        action = Action(
            name="Heroism",
            description="Heal and grant temp HP.",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_CREATURE,
            range=5,
            healing="5",
            grants_temporary_hp="5",
        )
        result = _resolve(target, target, action)

        assert result.success
        assert target.current_hit_points == 25  # Healed 5
        assert target.temporary_hit_points == 5  # Got temp HP

    def test_no_temp_hp_field_does_nothing(self):
        """An action without grants_temporary_hp doesn't affect temp HP."""
        target = _make_creature(temp_hp=0)
        action = Action(
            name="Cure Wounds",
            description="Just healing.",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_CREATURE,
            range=5,
            healing="1d8+3",
        )
        result = _resolve(target, target, action)

        assert target.temporary_hit_points == 0
