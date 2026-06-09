"""Tests for forced reroll mechanics."""

import pytest

from arena.models.character import Feature, PlayerCharacter, Creature
from arena.combat.forced_reroll import (
    get_forced_reroll_features,
    can_afford_reroll,
    deduct_reroll_cost,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_character(features=None, class_resources=None, **kwargs):
    """Create a basic PlayerCharacter with optional features and resources."""
    defaults = dict(
        name="TestChar",
        max_hit_points=40,
        character_class="Fighter",
        level=9,
        features=features or [],
        class_resources=class_resources or {},
    )
    defaults.update(kwargs)
    return PlayerCharacter(**defaults)


def _indomitable_feature():
    """Fighter Indomitable: reroll failed save, no class_resource cost."""
    return Feature(
        name="Indomitable",
        description="Reroll a failed saving throw",
        forced_reroll_saves=True,
        # No forced_reroll_resource — tracked via uses_per_rest on the feature
    )


def _diamond_soul_feature():
    """Monk Diamond Soul: reroll failed save for 1 ki point."""
    return Feature(
        name="Diamond Soul",
        description="Reroll a failed saving throw (1 ki)",
        forced_reroll_saves=True,
        forced_reroll_resource="ki_points",
        forced_reroll_resource_cost=1,
    )


def _lucky_feature():
    """Lucky feat as a feature: reroll any d20, costs 1 luck point."""
    return Feature(
        name="Lucky",
        description="Reroll a d20 roll",
        forced_reroll_saves=True,
        forced_reroll_resource="luck_points",
        forced_reroll_resource_cost=1,
    )


# ── get_forced_reroll_features ───────────────────────────────────────


class TestGetForcedRerollFeatures:
    def test_finds_indomitable(self):
        pc = _make_character(features=[_indomitable_feature()])
        result = get_forced_reroll_features(pc)
        assert len(result) == 1
        assert result[0].name == "Indomitable"

    def test_finds_diamond_soul(self):
        pc = _make_character(
            features=[_diamond_soul_feature()],
            class_resources={"ki_points": 10},
            character_class="Monk",
        )
        result = get_forced_reroll_features(pc)
        assert len(result) == 1
        assert result[0].name == "Diamond Soul"

    def test_finds_multiple_reroll_features(self):
        pc = _make_character(
            features=[_indomitable_feature(), _lucky_feature()],
            class_resources={"luck_points": 3},
        )
        result = get_forced_reroll_features(pc)
        assert len(result) == 2

    def test_ignores_non_reroll_features(self):
        plain = Feature(name="Action Surge", description="Extra action")
        pc = _make_character(features=[plain])
        result = get_forced_reroll_features(pc)
        assert len(result) == 0

    def test_creature_without_features(self):
        creature = Creature(name="Goblin", max_hit_points=7)
        result = get_forced_reroll_features(creature)
        assert len(result) == 0


# ── can_afford_reroll ────────────────────────────────────────────────


class TestCanAffordReroll:
    def test_no_resource_needed(self):
        """Indomitable has no resource cost — always affordable."""
        pc = _make_character(features=[_indomitable_feature()])
        assert can_afford_reroll(pc, _indomitable_feature()) is True

    def test_has_sufficient_resource(self):
        pc = _make_character(
            features=[_diamond_soul_feature()],
            class_resources={"ki_points": 5},
            character_class="Monk",
        )
        assert can_afford_reroll(pc, _diamond_soul_feature()) is True

    def test_insufficient_resource(self):
        pc = _make_character(
            features=[_diamond_soul_feature()],
            class_resources={"ki_points": 0},
            character_class="Monk",
        )
        assert can_afford_reroll(pc, _diamond_soul_feature()) is False

    def test_missing_resource_key(self):
        """Resource key doesn't exist in class_resources — can't afford."""
        pc = _make_character(
            features=[_diamond_soul_feature()],
            class_resources={},
            character_class="Monk",
        )
        assert can_afford_reroll(pc, _diamond_soul_feature()) is False

    def test_lucky_with_points(self):
        pc = _make_character(
            features=[_lucky_feature()],
            class_resources={"luck_points": 3},
        )
        assert can_afford_reroll(pc, _lucky_feature()) is True

    def test_lucky_without_points(self):
        pc = _make_character(
            features=[_lucky_feature()],
            class_resources={"luck_points": 0},
        )
        assert can_afford_reroll(pc, _lucky_feature()) is False


# ── deduct_reroll_cost ───────────────────────────────────────────────


class TestDeductRerollCost:
    def test_deducts_ki_point(self):
        pc = _make_character(
            features=[_diamond_soul_feature()],
            class_resources={"ki_points": 5},
            character_class="Monk",
        )
        deduct_reroll_cost(pc, _diamond_soul_feature())
        assert pc.class_resources["ki_points"] == 4

    def test_deducts_luck_point(self):
        pc = _make_character(
            features=[_lucky_feature()],
            class_resources={"luck_points": 3},
        )
        deduct_reroll_cost(pc, _lucky_feature())
        assert pc.class_resources["luck_points"] == 2

    def test_no_resource_is_noop(self):
        """Indomitable has no resource — deduct does nothing."""
        pc = _make_character(features=[_indomitable_feature()])
        deduct_reroll_cost(pc, _indomitable_feature())
        # No error, no side effects

    def test_floor_at_zero(self):
        pc = _make_character(
            features=[_diamond_soul_feature()],
            class_resources={"ki_points": 0},
            character_class="Monk",
        )
        deduct_reroll_cost(pc, _diamond_soul_feature())
        assert pc.class_resources["ki_points"] == 0

    def test_multiple_deductions(self):
        pc = _make_character(
            features=[_diamond_soul_feature()],
            class_resources={"ki_points": 3},
            character_class="Monk",
        )
        feat = _diamond_soul_feature()
        deduct_reroll_cost(pc, feat)
        deduct_reroll_cost(pc, feat)
        deduct_reroll_cost(pc, feat)
        assert pc.class_resources["ki_points"] == 0
