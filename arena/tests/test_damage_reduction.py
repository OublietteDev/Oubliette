"""Tests for damage reduction reaction system."""

import pytest
from unittest.mock import patch

from arena.models.character import Feature, PlayerCharacter
from arena.combat.damage_reduction import (
    get_damage_reduction_features,
    can_use_damage_reduction,
    calculate_damage_reduction,
    apply_damage_reduction,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_character(features=None, **kwargs):
    """Create a basic PlayerCharacter with optional features."""
    defaults = dict(
        name="TestChar",
        max_hit_points=40,
        character_class="Fighter",
        level=5,
        features=features or [],
    )
    defaults.update(kwargs)
    return PlayerCharacter(**defaults)


def _parry_feature():
    """Battlemaster Parry: 1d8 + DEX mod reduction, melee only."""
    return Feature(
        name="Parry",
        description="Reduce melee damage by 1d8 + DEX mod",
        damage_reduction_dice="1d8",
        damage_reduction_bonus="dexterity",
        damage_reduction_type="melee_only",
    )


def _uncanny_dodge_feature():
    """Rogue Uncanny Dodge: halve attack damage."""
    return Feature(
        name="Uncanny Dodge",
        description="Halve the damage from one attack",
        damage_reduction_flat_half=True,
    )


def _deflect_missiles_feature():
    """Monk Deflect Missiles: 1d10 + DEX mod reduction, ranged only."""
    return Feature(
        name="Deflect Missiles",
        description="Reduce ranged damage by 1d10 + DEX mod",
        damage_reduction_dice="1d10",
        damage_reduction_bonus="dexterity",
        damage_reduction_type="ranged_only",
    )


# ── get_damage_reduction_features ────────────────────────────────────


class TestGetDamageReductionFeatures:
    def test_finds_dice_based_feature(self):
        pc = _make_character(features=[_parry_feature()])
        result = get_damage_reduction_features(pc)
        assert len(result) == 1
        assert result[0].name == "Parry"

    def test_finds_flat_half_feature(self):
        pc = _make_character(features=[_uncanny_dodge_feature()])
        result = get_damage_reduction_features(pc)
        assert len(result) == 1
        assert result[0].name == "Uncanny Dodge"

    def test_finds_multiple_features(self):
        pc = _make_character(features=[_parry_feature(), _uncanny_dodge_feature()])
        result = get_damage_reduction_features(pc)
        assert len(result) == 2

    def test_ignores_non_reduction_features(self):
        plain = Feature(name="Second Wind", description="Heal yourself")
        pc = _make_character(features=[plain])
        result = get_damage_reduction_features(pc)
        assert len(result) == 0

    def test_creature_without_features(self):
        from arena.models.character import Creature
        creature = Creature(name="Goblin", max_hit_points=7)
        result = get_damage_reduction_features(creature)
        assert len(result) == 0


# ── can_use_damage_reduction ─────────────────────────────────────────


class TestCanUseDamageReduction:
    def test_melee_only_blocks_ranged(self):
        feat = _parry_feature()
        assert can_use_damage_reduction(feat, is_melee=False, is_ranged=True) is False

    def test_melee_only_allows_melee(self):
        feat = _parry_feature()
        assert can_use_damage_reduction(feat, is_melee=True, is_ranged=False) is True

    def test_ranged_only_blocks_melee(self):
        feat = _deflect_missiles_feature()
        assert can_use_damage_reduction(feat, is_melee=True, is_ranged=False) is False

    def test_ranged_only_allows_ranged(self):
        feat = _deflect_missiles_feature()
        assert can_use_damage_reduction(feat, is_melee=False, is_ranged=True) is True

    def test_no_type_restriction_allows_any(self):
        feat = _uncanny_dodge_feature()
        assert can_use_damage_reduction(feat, is_melee=True) is True
        assert can_use_damage_reduction(feat, is_melee=False, is_ranged=True) is True


# ── calculate_damage_reduction ───────────────────────────────────────


class TestCalculateDamageReduction:
    @patch("arena.combat.damage_reduction.roll_expression", return_value=(5, [5]))
    def test_parry_dice_plus_ability_mod(self, mock_roll):
        """Parry with DEX 16 (+3): die roll 5 + 3 = 8."""
        from arena.models.abilities import AbilityScores
        pc = _make_character(
            features=[_parry_feature()],
            ability_scores=AbilityScores(dexterity=16),
        )
        result = calculate_damage_reduction(pc, _parry_feature())
        assert result == 8
        mock_roll.assert_called_once_with("1d8")

    @patch("arena.combat.damage_reduction.roll_expression", return_value=(7, [7]))
    def test_deflect_missiles_dice_plus_dex(self, mock_roll):
        """Deflect Missiles with DEX 18 (+4): die roll 7 + 4 = 11."""
        from arena.models.abilities import AbilityScores
        pc = _make_character(
            features=[_deflect_missiles_feature()],
            ability_scores=AbilityScores(dexterity=18),
        )
        result = calculate_damage_reduction(pc, _deflect_missiles_feature())
        assert result == 11
        mock_roll.assert_called_once_with("1d10")

    def test_flat_half_returns_sentinel(self):
        pc = _make_character(features=[_uncanny_dodge_feature()])
        result = calculate_damage_reduction(pc, _uncanny_dodge_feature())
        assert result == -1

    @patch("arena.combat.damage_reduction.roll_expression", return_value=(1, [1]))
    def test_minimum_zero(self, mock_roll):
        """Reduction can't go negative even with low ability mod."""
        from arena.models.abilities import AbilityScores
        feat = Feature(
            name="Weak Parry",
            description="test",
            damage_reduction_dice="1d4",
            # No bonus ability — total is just the die roll
        )
        pc = _make_character(
            features=[feat],
            ability_scores=AbilityScores(dexterity=10),
        )
        result = calculate_damage_reduction(pc, feat)
        assert result >= 0


# ── apply_damage_reduction ───────────────────────────────────────────


class TestApplyDamageReduction:
    def test_normal_reduction(self):
        assert apply_damage_reduction(20, 8) == 12

    def test_halving(self):
        assert apply_damage_reduction(20, -1) == 10

    def test_odd_halving_rounds_down(self):
        assert apply_damage_reduction(21, -1) == 10

    def test_reduction_exceeds_damage(self):
        assert apply_damage_reduction(5, 12) == 0

    def test_zero_damage(self):
        assert apply_damage_reduction(0, 5) == 0

    def test_zero_reduction(self):
        assert apply_damage_reduction(15, 0) == 15
