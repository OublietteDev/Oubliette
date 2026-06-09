"""Tests for the Extra Attack query function in stat_modifiers.py.

Tests cover:
- Default attack count (no features/feats) returns 1
- Extra Attack feature (count=2) returns 2
- Multiple features with different counts: max wins
- Feat-based extra attack works
- Mixed features + feats: highest across both wins (no stacking)
- Base Creature (no features/feats attributes) returns 1
"""

import pytest

from arena.models.character import Creature, PlayerCharacter, Feature
from arena.models.feats import Feat
from arena.combat.stat_modifiers import get_extra_attack_count


# ── Test Helpers ──────────────────────────────────────────────────────


def _make_pc(
    features: list | None = None,
    feats: list | None = None,
) -> PlayerCharacter:
    """Create a minimal PlayerCharacter for testing."""
    return PlayerCharacter(
        name="Test Fighter",
        size="medium",
        creature_type="humanoid",
        ability_scores={
            "strength": 16, "dexterity": 10, "constitution": 14,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
        },
        armor_class=16,
        max_hit_points=50,
        current_hit_points=50,
        character_class="Fighter",
        level=5,
        features=features or [],
        feats=feats or [],
    )


def _make_creature() -> Creature:
    """Create a base Creature (monster) with no features/feats."""
    return Creature(
        name="Goblin",
        max_hit_points=7,
        armor_class=15,
        ability_scores={"dexterity": 14, "strength": 8},
    )


# ── Tests ─────────────────────────────────────────────────────────────


class TestGetExtraAttackCount:
    """Tests for get_extra_attack_count()."""

    def test_no_features_returns_1(self):
        """A PC with no features defaults to 1 attack."""
        pc = _make_pc()
        assert get_extra_attack_count(pc) == 1

    def test_extra_attack_feature_returns_2(self):
        """Standard Extra Attack (most martial classes at 5th level)."""
        pc = _make_pc(features=[
            Feature(name="Extra Attack", description="Two attacks per Attack action", extra_attack_count=2),
        ])
        assert get_extra_attack_count(pc) == 2

    def test_fighter_11_returns_3(self):
        """Fighter 11th level gets 3 attacks."""
        pc = _make_pc(features=[
            Feature(name="Extra Attack (x2)", description="Three attacks", extra_attack_count=3),
        ])
        assert get_extra_attack_count(pc) == 3

    def test_fighter_20_returns_4(self):
        """Fighter 20th level gets 4 attacks."""
        pc = _make_pc(features=[
            Feature(name="Extra Attack (x3)", description="Four attacks", extra_attack_count=4),
        ])
        assert get_extra_attack_count(pc) == 4

    def test_multiple_features_takes_max(self):
        """Multiple Extra Attack features (multiclass edge case): max wins."""
        pc = _make_pc(features=[
            Feature(name="Extra Attack", description="Two attacks", extra_attack_count=2),
            Feature(name="Extra Attack (x2)", description="Three attacks", extra_attack_count=3),
        ])
        assert get_extra_attack_count(pc) == 3

    def test_feat_with_extra_attack(self):
        """A feat granting extra attacks works."""
        pc = _make_pc(feats=[
            Feat(name="Combat Master", extra_attack_count=2),
        ])
        assert get_extra_attack_count(pc) == 2

    def test_feature_and_feat_takes_max(self):
        """Feature (2) + feat (3) = 3 (max, not sum)."""
        pc = _make_pc(
            features=[
                Feature(name="Extra Attack", description="Two attacks", extra_attack_count=2),
            ],
            feats=[
                Feat(name="Superior Combat", extra_attack_count=3),
            ],
        )
        assert get_extra_attack_count(pc) == 3

    def test_feature_higher_than_feat(self):
        """Feature (3) beats feat (2)."""
        pc = _make_pc(
            features=[
                Feature(name="Extra Attack (x2)", description="Three attacks", extra_attack_count=3),
            ],
            feats=[
                Feat(name="Minor Combat", extra_attack_count=2),
            ],
        )
        assert get_extra_attack_count(pc) == 3

    def test_base_creature_returns_1(self):
        """A base Creature (monster) with no features/feats returns 1."""
        creature = _make_creature()
        assert get_extra_attack_count(creature) == 1

    def test_zero_extra_attack_count_ignored(self):
        """Features with extra_attack_count=0 don't override the default."""
        pc = _make_pc(features=[
            Feature(name="Darkvision", description="See in dark", extra_attack_count=0),
        ])
        assert get_extra_attack_count(pc) == 1
