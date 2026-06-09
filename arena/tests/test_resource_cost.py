"""Tests for class resource cost checking and deduction.

Tests cover:
- No resource_cost → always passes
- Sufficient resources → passes and deducted
- Insufficient resources → fails with message
- Multiple resource types
- Zero cost → passes
- Base Creature (no class_resources) → passes
- Deduction edge cases
"""

import pytest

from arena.models.character import Creature, PlayerCharacter
from arena.models.actions import Action, ActionType
from arena.combat.actions import check_resource_cost, deduct_resource_cost


# ── Test Helpers ──────────────────────────────────────────────────────


def _make_pc(class_resources: dict | None = None) -> PlayerCharacter:
    """Create a minimal PlayerCharacter with given resources."""
    return PlayerCharacter(
        name="Test Monk",
        max_hit_points=20,
        armor_class=10,
        character_class="Monk",
        level=5,
        race="Human",
        class_resources=class_resources or {},
    )


def _make_creature() -> Creature:
    """Create a base Creature (no class_resources)."""
    return Creature(name="Goblin", max_hit_points=7, armor_class=13)


def _make_action(resource_cost: dict | None = None, name: str = "Flurry") -> Action:
    """Create a minimal action with optional resource cost."""
    return Action(
        name=name,
        description="Test action",
        action_type=ActionType.ACTION,
        resource_cost=resource_cost or {},
    )


# ── Test check_resource_cost ─────────────────────────────────────────


class TestCheckResourceCost:
    """Tests for check_resource_cost()."""

    def test_no_cost_always_passes(self):
        pc = _make_pc(class_resources={"ki_points": 5})
        action = _make_action(resource_cost={})
        can_use, reason = check_resource_cost(pc, action)
        assert can_use is True
        assert reason == ""

    def test_sufficient_single_resource(self):
        pc = _make_pc(class_resources={"ki_points": 5})
        action = _make_action(resource_cost={"ki_points": 2})
        can_use, reason = check_resource_cost(pc, action)
        assert can_use is True

    def test_exact_amount_passes(self):
        pc = _make_pc(class_resources={"ki_points": 2})
        action = _make_action(resource_cost={"ki_points": 2})
        can_use, reason = check_resource_cost(pc, action)
        assert can_use is True

    def test_insufficient_single_resource(self):
        pc = _make_pc(class_resources={"ki_points": 1})
        action = _make_action(resource_cost={"ki_points": 2})
        can_use, reason = check_resource_cost(pc, action)
        assert can_use is False
        assert "ki_points" in reason
        assert "1/2" in reason

    def test_zero_resources_fails(self):
        pc = _make_pc(class_resources={"ki_points": 0})
        action = _make_action(resource_cost={"ki_points": 1})
        can_use, reason = check_resource_cost(pc, action)
        assert can_use is False

    def test_missing_resource_fails(self):
        pc = _make_pc(class_resources={})
        action = _make_action(resource_cost={"ki_points": 1})
        can_use, reason = check_resource_cost(pc, action)
        assert can_use is False

    def test_multiple_resources_all_sufficient(self):
        pc = _make_pc(class_resources={"ki_points": 5, "superiority_dice": 3})
        action = _make_action(resource_cost={"ki_points": 2, "superiority_dice": 1})
        can_use, reason = check_resource_cost(pc, action)
        assert can_use is True

    def test_multiple_resources_one_insufficient(self):
        pc = _make_pc(class_resources={"ki_points": 5, "superiority_dice": 0})
        action = _make_action(resource_cost={"ki_points": 2, "superiority_dice": 1})
        can_use, reason = check_resource_cost(pc, action)
        assert can_use is False
        assert "superiority_dice" in reason

    def test_base_creature_no_cost_passes(self):
        c = _make_creature()
        action = _make_action(resource_cost={})
        can_use, reason = check_resource_cost(c, action)
        assert can_use is True

    def test_base_creature_with_cost_fails(self):
        c = _make_creature()
        action = _make_action(resource_cost={"ki_points": 1})
        can_use, reason = check_resource_cost(c, action)
        assert can_use is False

    def test_zero_cost_passes(self):
        pc = _make_pc(class_resources={"ki_points": 0})
        action = _make_action(resource_cost={"ki_points": 0})
        # 0 >= 0, should pass
        can_use, reason = check_resource_cost(pc, action)
        assert can_use is True


# ── Test deduct_resource_cost ────────────────────────────────────────


class TestDeductResourceCost:
    """Tests for deduct_resource_cost()."""

    def test_no_cost_no_change(self):
        pc = _make_pc(class_resources={"ki_points": 5})
        action = _make_action(resource_cost={})
        deduct_resource_cost(pc, action)
        assert pc.class_resources["ki_points"] == 5

    def test_single_resource_deducted(self):
        pc = _make_pc(class_resources={"ki_points": 5})
        action = _make_action(resource_cost={"ki_points": 2})
        deduct_resource_cost(pc, action)
        assert pc.class_resources["ki_points"] == 3

    def test_deduct_to_zero(self):
        pc = _make_pc(class_resources={"ki_points": 2})
        action = _make_action(resource_cost={"ki_points": 2})
        deduct_resource_cost(pc, action)
        assert pc.class_resources["ki_points"] == 0

    def test_multiple_resources_deducted(self):
        pc = _make_pc(class_resources={"ki_points": 5, "superiority_dice": 3})
        action = _make_action(resource_cost={"ki_points": 2, "superiority_dice": 1})
        deduct_resource_cost(pc, action)
        assert pc.class_resources["ki_points"] == 3
        assert pc.class_resources["superiority_dice"] == 2

    def test_deduct_wont_go_negative(self):
        pc = _make_pc(class_resources={"ki_points": 1})
        action = _make_action(resource_cost={"ki_points": 5})
        deduct_resource_cost(pc, action)
        assert pc.class_resources["ki_points"] == 0

    def test_deduct_missing_resource_ignored(self):
        pc = _make_pc(class_resources={})
        action = _make_action(resource_cost={"ki_points": 1})
        # Should not raise an error
        deduct_resource_cost(pc, action)
