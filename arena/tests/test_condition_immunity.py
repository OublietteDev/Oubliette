"""Tests for the condition immunity system (active feature immunities)."""

import pytest

from arena.models.character import Feature, PlayerCharacter, Creature, CreatureSize
from arena.combat.condition_immunity import (
    get_active_condition_immunities,
    is_immune_to_condition,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_creature(**kwargs):
    """Create a minimal Creature for testing."""
    defaults = dict(
        name="TestCreature",
        max_hit_points=50,
    )
    defaults.update(kwargs)
    return Creature(**defaults)


def _make_pc(**kwargs):
    """Create a minimal PlayerCharacter for testing."""
    defaults = dict(
        name="TestPC",
        max_hit_points=50,
        character_class="Barbarian",
    )
    defaults.update(kwargs)
    return PlayerCharacter(**defaults)


# ── get_active_condition_immunities ──────────────────────────────────


class TestGetActiveConditionImmunities:
    """Tests for get_active_condition_immunities()."""

    def test_passive_feature_always_active(self):
        """Passive feature (no resource gate) always grants immunities."""
        pc = _make_pc(features=[
            Feature(
                name="Undying Fortitude",
                description="Immune to frightened",
                active_condition_immunities=["frightened"],
                active_condition_resource=None,
            ),
        ])
        result = get_active_condition_immunities(pc)
        assert "frightened" in result

    def test_resource_gated_feature_with_resource_active(self):
        """Resource-gated feature grants immunities when resource > 0."""
        pc = _make_pc(
            features=[
                Feature(
                    name="Mindless Rage",
                    description="Immune to charmed/frightened while raging",
                    active_condition_immunities=["charmed", "frightened"],
                    active_condition_resource="rage",
                ),
            ],
            class_resources={"rage": 3},
        )
        result = get_active_condition_immunities(pc)
        assert "charmed" in result
        assert "frightened" in result

    def test_resource_gated_feature_with_resource_depleted(self):
        """Resource-gated feature grants NO immunities when resource is 0."""
        pc = _make_pc(
            features=[
                Feature(
                    name="Mindless Rage",
                    description="Immune to charmed/frightened while raging",
                    active_condition_immunities=["charmed", "frightened"],
                    active_condition_resource="rage",
                ),
            ],
            class_resources={"rage": 0},
        )
        result = get_active_condition_immunities(pc)
        assert result == []

    def test_resource_gated_feature_resource_missing(self):
        """Resource-gated feature grants NO immunities if resource key absent."""
        pc = _make_pc(
            features=[
                Feature(
                    name="Mindless Rage",
                    description="Immune while raging",
                    active_condition_immunities=["charmed"],
                    active_condition_resource="rage",
                ),
            ],
            class_resources={},
        )
        result = get_active_condition_immunities(pc)
        assert result == []

    def test_creature_with_no_features(self):
        """Creature with no features returns empty list."""
        creature = _make_creature()
        result = get_active_condition_immunities(creature)
        assert result == []

    def test_feature_without_active_immunities_ignored(self):
        """Features without active_condition_immunities are skipped."""
        pc = _make_pc(features=[
            Feature(name="Tough", description="Extra HP"),
        ])
        result = get_active_condition_immunities(pc)
        assert result == []

    def test_multiple_features_combined(self):
        """Immunities from multiple features are combined."""
        pc = _make_pc(
            features=[
                Feature(
                    name="Passive Immunity",
                    description="Always immune to poisoned",
                    active_condition_immunities=["poisoned"],
                    active_condition_resource=None,
                ),
                Feature(
                    name="Mindless Rage",
                    description="Immune to charmed while raging",
                    active_condition_immunities=["charmed"],
                    active_condition_resource="rage",
                ),
            ],
            class_resources={"rage": 1},
        )
        result = get_active_condition_immunities(pc)
        assert "poisoned" in result
        assert "charmed" in result


# ── is_immune_to_condition ───────────────────────────────────────────


class TestIsImmuneToCondition:
    """Tests for is_immune_to_condition()."""

    def test_immune_via_static_condition_immunities(self):
        """Static condition_immunities on creature grants immunity."""
        creature = _make_creature(condition_immunities=["poisoned"])
        assert is_immune_to_condition(creature, "poisoned") is True

    def test_immune_via_active_feature(self):
        """Active feature immunities grant immunity."""
        pc = _make_pc(
            features=[
                Feature(
                    name="Mindless Rage",
                    description="Immune while raging",
                    active_condition_immunities=["charmed"],
                    active_condition_resource="rage",
                ),
            ],
            class_resources={"rage": 2},
        )
        assert is_immune_to_condition(pc, "charmed") is True

    def test_not_immune_to_unrelated_condition(self):
        """Creature is not immune to conditions not in any immunity list."""
        pc = _make_pc(
            features=[
                Feature(
                    name="Mindless Rage",
                    description="Immune to charmed while raging",
                    active_condition_immunities=["charmed"],
                    active_condition_resource="rage",
                ),
            ],
            class_resources={"rage": 2},
        )
        assert is_immune_to_condition(pc, "stunned") is False

    def test_case_insensitive_match(self):
        """Immunity check is case-insensitive."""
        creature = _make_creature(condition_immunities=["Poisoned"])
        assert is_immune_to_condition(creature, "poisoned") is True
        assert is_immune_to_condition(creature, "POISONED") is True

    def test_no_immunities_at_all(self):
        """Creature with no immunities of any kind returns False."""
        creature = _make_creature()
        assert is_immune_to_condition(creature, "frightened") is False


# ── Mindless Rage Pattern ────────────────────────────────────────────


class TestMindlessRagePattern:
    """Full integration of the Mindless Rage feature pattern."""

    def test_mindless_rage_active(self):
        """While raging (resource > 0), immune to charmed and frightened."""
        pc = _make_pc(
            features=[
                Feature(
                    name="Mindless Rage",
                    description="While raging, can't be charmed or frightened",
                    active_condition_immunities=["charmed", "frightened"],
                    active_condition_resource="rage",
                ),
            ],
            class_resources={"rage": 3},
        )
        assert is_immune_to_condition(pc, "charmed") is True
        assert is_immune_to_condition(pc, "frightened") is True
        assert is_immune_to_condition(pc, "stunned") is False

    def test_mindless_rage_inactive(self):
        """When not raging (resource = 0), not immune."""
        pc = _make_pc(
            features=[
                Feature(
                    name="Mindless Rage",
                    description="While raging, can't be charmed or frightened",
                    active_condition_immunities=["charmed", "frightened"],
                    active_condition_resource="rage",
                ),
            ],
            class_resources={"rage": 0},
        )
        assert is_immune_to_condition(pc, "charmed") is False
        assert is_immune_to_condition(pc, "frightened") is False
