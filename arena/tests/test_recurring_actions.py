"""Tests for the recurring action engine (src/combat/recurring_actions.py).

Tests cover:
- create_recurring_action() with recurring fields → returns ActiveRecurringAction
- create_recurring_action() without recurring fields → returns None
- can_use_recurring_action() with action type and available action
- can_use_recurring_action() with bonus_action type and no bonus → False
- get_recurring_damage() returns correct dice/type
- Witch Bolt pattern: auto_hit=True, damage_dice="1d12"
- Spiritual Weapon pattern: bonus_action type, move_distance=20
- Sunbeam pattern: recurring action with full damage, re-usable as action
"""

import pytest

from arena.models.actions import Action, ActionType, DamageRoll, DamageType, SavingThrowEffect
from arena.combat.recurring_actions import (
    ActiveRecurringAction,
    create_recurring_action,
    can_use_recurring_action,
    get_recurring_damage,
)


# ── Test Helpers ──────────────────────────────────────────────────────


def _make_action(**kwargs) -> Action:
    """Create a minimal Action with overrides."""
    defaults = dict(
        name="Test Spell",
        action_type=ActionType.ACTION,
        description="A test action",
    )
    defaults.update(kwargs)
    return Action(**defaults)


def _make_witch_bolt() -> Action:
    """Create a Witch Bolt-like action."""
    return _make_action(
        name="Witch Bolt",
        requires_concentration=True,
        recurring_action_type="action",
        recurring_damage_dice="1d12",
        recurring_damage_type="lightning",
        recurring_auto_hit=True,
    )


def _make_spiritual_weapon() -> Action:
    """Create a Spiritual Weapon-like action."""
    return _make_action(
        name="Spiritual Weapon",
        action_type=ActionType.BONUS_ACTION,
        recurring_action_type="bonus_action",
        recurring_damage_dice="1d8",
        recurring_damage_type="force",
        recurring_move_distance=20,
    )


def _make_sunbeam() -> Action:
    """Create a Sunbeam-like action."""
    return _make_action(
        name="Sunbeam",
        requires_concentration=True,
        recurring_action_type="action",
        recurring_damage_dice="6d8",
        recurring_damage_type="radiant",
    )


def _make_non_recurring() -> Action:
    """Create an action with no recurring properties."""
    return _make_action(name="Fireball")


# ── create_recurring_action Tests ─────────────────────────────────────


class TestCreateRecurringAction:
    """Tests for create_recurring_action()."""

    def test_returns_none_for_non_recurring(self):
        """An action without recurring_action_type returns None."""
        action = _make_non_recurring()
        result = create_recurring_action(action)
        assert result is None

    def test_creates_from_recurring_action(self):
        """An action with recurring fields returns an ActiveRecurringAction."""
        action = _make_sunbeam()
        result = create_recurring_action(action)
        assert result is not None
        assert isinstance(result, ActiveRecurringAction)
        assert result.action_name == "Sunbeam"
        assert result.action_type == "action"

    def test_witch_bolt_fields(self):
        """Witch Bolt: auto_hit, concentration-linked, damage set."""
        action = _make_witch_bolt()
        result = create_recurring_action(action, target_id="goblin_1")
        assert result is not None
        assert result.auto_hit is True
        assert result.damage_dice == "1d12"
        assert result.damage_type == "lightning"
        assert result.linked_to_concentration is True
        assert result.target_id == "goblin_1"

    def test_spiritual_weapon_fields(self):
        """Spiritual Weapon: bonus_action type, move distance."""
        action = _make_spiritual_weapon()
        result = create_recurring_action(action)
        assert result is not None
        assert result.action_type == "bonus_action"
        assert result.move_distance == 20
        assert result.damage_dice == "1d8"
        assert result.damage_type == "force"
        assert result.linked_to_concentration is False

    def test_sunbeam_fields(self):
        """Sunbeam: action type, full damage, concentration-linked."""
        action = _make_sunbeam()
        result = create_recurring_action(action)
        assert result is not None
        assert result.action_type == "action"
        assert result.damage_dice == "6d8"
        assert result.damage_type == "radiant"
        assert result.linked_to_concentration is True
        assert result.auto_hit is False

    def test_source_action_stored(self):
        """The original Action object is stored for reference."""
        action = _make_sunbeam()
        result = create_recurring_action(action)
        assert result is not None
        assert result.source_action is action

    def test_target_id_defaults_none(self):
        """target_id defaults to None when not provided."""
        action = _make_sunbeam()
        result = create_recurring_action(action)
        assert result is not None
        assert result.target_id is None


# ── can_use_recurring_action Tests ────────────────────────────────────


class TestCanUseRecurringAction:
    """Tests for can_use_recurring_action()."""

    def test_action_type_with_action_available(self):
        """Action-type recurring with action available → True."""
        action = _make_sunbeam()
        recurring = create_recurring_action(action)
        assert can_use_recurring_action(recurring, available_action=True)

    def test_action_type_without_action(self):
        """Action-type recurring without action available → False."""
        action = _make_sunbeam()
        recurring = create_recurring_action(action)
        assert not can_use_recurring_action(recurring, available_action=False)

    def test_bonus_action_type_with_bonus_available(self):
        """Bonus-action-type recurring with bonus available → True."""
        action = _make_spiritual_weapon()
        recurring = create_recurring_action(action)
        assert can_use_recurring_action(recurring, available_bonus=True)

    def test_bonus_action_type_without_bonus(self):
        """Bonus-action-type recurring without bonus available → False."""
        action = _make_spiritual_weapon()
        recurring = create_recurring_action(action)
        assert not can_use_recurring_action(recurring, available_bonus=False)

    def test_action_type_ignores_bonus_availability(self):
        """Action-type recurring doesn't care about bonus action."""
        action = _make_sunbeam()
        recurring = create_recurring_action(action)
        assert can_use_recurring_action(recurring, available_action=True, available_bonus=False)

    def test_bonus_type_ignores_action_availability(self):
        """Bonus-action-type recurring doesn't care about regular action."""
        action = _make_spiritual_weapon()
        recurring = create_recurring_action(action)
        assert can_use_recurring_action(recurring, available_action=False, available_bonus=True)

    def test_unknown_type_returns_false(self):
        """An unrecognized action_type returns False."""
        recurring = ActiveRecurringAction(
            action_name="Weird",
            source_action=_make_non_recurring(),
            action_type="legendary",  # Not a valid recurring type
        )
        assert not can_use_recurring_action(recurring)


# ── get_recurring_damage Tests ────────────────────────────────────────


class TestGetRecurringDamage:
    """Tests for get_recurring_damage()."""

    def test_returns_damage_dice_and_type(self):
        """Returns (dice, type) for a recurring action with damage."""
        action = _make_witch_bolt()
        recurring = create_recurring_action(action)
        dice, dtype = get_recurring_damage(recurring)
        assert dice == "1d12"
        assert dtype == "lightning"

    def test_sunbeam_damage(self):
        """Sunbeam returns full recurring damage."""
        action = _make_sunbeam()
        recurring = create_recurring_action(action)
        dice, dtype = get_recurring_damage(recurring)
        assert dice == "6d8"
        assert dtype == "radiant"

    def test_spiritual_weapon_damage(self):
        """Spiritual Weapon returns its recurring damage."""
        action = _make_spiritual_weapon()
        recurring = create_recurring_action(action)
        dice, dtype = get_recurring_damage(recurring)
        assert dice == "1d8"
        assert dtype == "force"

    def test_no_damage_returns_none_tuple(self):
        """A recurring action with no damage fields returns (None, None)."""
        recurring = ActiveRecurringAction(
            action_name="Detect Magic",
            source_action=_make_non_recurring(),
            action_type="action",
            damage_dice=None,
            damage_type=None,
        )
        dice, dtype = get_recurring_damage(recurring)
        assert dice is None
        assert dtype is None
