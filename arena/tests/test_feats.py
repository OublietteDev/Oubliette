"""Tests for feat integration with stat_modifiers.py.

Tests cover:
- Feat model creation and defaults
- _get_feats() helper for PC vs base Creature
- Ability score aggregation from feats (+ equipment stacking, cap at 30)
- Speed aggregation from feats
- AC aggregation from feats
- Initiative bonus from feats
- Damage resistance/immunity from feats (+ deduplication)
- Condition immunity from feats
- Saving throw proficiency aggregation from feats
"""

import pytest

from arena.models.character import Creature, PlayerCharacter
from arena.models.feats import Feat
from arena.models.items import Item, ItemType, EquipmentSlot
from arena.combat.stat_modifiers import (
    _get_feats,
    get_effective_ability_score,
    get_effective_ability_modifier,
    get_effective_speed,
    get_passive_ac_bonus,
    get_effective_damage_resistances,
    get_effective_damage_immunities,
    get_effective_condition_immunities,
    get_effective_saving_throw_proficiencies,
    get_initiative_bonus,
)


# ── Test Helpers ──────────────────────────────────────────────────────


def _make_creature(**kwargs) -> Creature:
    """Create a minimal base Creature (no feats field)."""
    defaults = {
        "name": "Test Creature",
        "max_hit_points": 10,
        "armor_class": 10,
    }
    defaults.update(kwargs)
    return Creature(**defaults)


def _make_pc(**kwargs) -> PlayerCharacter:
    """Create a minimal PlayerCharacter (has feats field)."""
    defaults = {
        "name": "Test PC",
        "max_hit_points": 20,
        "armor_class": 10,
        "character_class": "Fighter",
        "level": 5,
        "race": "Human",
        "feats": [],
    }
    defaults.update(kwargs)
    return PlayerCharacter(**defaults)


def _make_feat(**kwargs) -> Feat:
    """Create a feat with defaults."""
    defaults = {"name": "Test Feat"}
    defaults.update(kwargs)
    return Feat(**defaults)


def _make_wondrous(name: str = "Ring", slot: EquipmentSlot = EquipmentSlot.RING_1, **kwargs) -> Item:
    """Create a wondrous item for testing equipment + feat stacking."""
    return Item(
        name=name,
        item_type=ItemType.WONDROUS,
        equipment_slot=slot,
        **kwargs,
    )


# ── Test _get_feats Helper ───────────────────────────────────────────


class TestGetFeats:
    """Tests for the _get_feats helper."""

    def test_base_creature_returns_empty(self):
        c = _make_creature()
        assert _get_feats(c) == []

    def test_pc_no_feats(self):
        pc = _make_pc(feats=[])
        assert _get_feats(pc) == []

    def test_pc_with_feats(self):
        feat = _make_feat(name="Alert", bonus_initiative=5)
        pc = _make_pc(feats=[feat])
        result = _get_feats(pc)
        assert len(result) == 1
        assert result[0].name == "Alert"

    def test_pc_multiple_feats(self):
        feats = [
            _make_feat(name="Alert"),
            _make_feat(name="Mobile"),
        ]
        pc = _make_pc(feats=feats)
        assert len(_get_feats(pc)) == 2


# ── Test Ability Score from Feats ────────────────────────────────────


class TestFeatAbilityScore:
    """Tests for feat bonus_ability_scores aggregation."""

    def test_no_feats_base_score(self):
        pc = _make_pc(ability_scores={"strength": 16})
        assert get_effective_ability_score(pc, "strength") == 16

    def test_single_feat_bonus(self):
        feat = _make_feat(bonus_ability_scores={"strength": 1})
        pc = _make_pc(ability_scores={"strength": 16}, feats=[feat])
        assert get_effective_ability_score(pc, "strength") == 17

    def test_multiple_feat_stacking(self):
        feats = [
            _make_feat(name="F1", bonus_ability_scores={"strength": 1}),
            _make_feat(name="F2", bonus_ability_scores={"strength": 1}),
        ]
        pc = _make_pc(ability_scores={"strength": 16}, feats=feats)
        assert get_effective_ability_score(pc, "strength") == 18

    def test_feat_plus_equipment_stacking(self):
        feat = _make_feat(bonus_ability_scores={"strength": 1})
        ring = _make_wondrous(bonus_ability_scores={"strength": 2})
        pc = _make_pc(
            ability_scores={"strength": 14},
            feats=[feat],
            equipment=[ring],
        )
        assert get_effective_ability_score(pc, "strength") == 17  # 14 + 2 + 1

    def test_capped_at_30(self):
        feat = _make_feat(bonus_ability_scores={"strength": 2})
        pc = _make_pc(ability_scores={"strength": 29}, feats=[feat])
        assert get_effective_ability_score(pc, "strength") == 30

    def test_feat_doesnt_affect_other_abilities(self):
        feat = _make_feat(bonus_ability_scores={"strength": 2})
        pc = _make_pc(
            ability_scores={"strength": 14, "dexterity": 12},
            feats=[feat],
        )
        assert get_effective_ability_score(pc, "dexterity") == 12


# ── Test Ability Modifier from Feats ─────────────────────────────────


class TestFeatAbilityModifier:
    """Tests for feat-boosted ability modifier."""

    def test_feat_changes_modifier(self):
        # STR 15 (+2) + feat +1 = 16 (+3)
        feat = _make_feat(bonus_ability_scores={"strength": 1})
        pc = _make_pc(ability_scores={"strength": 15}, feats=[feat])
        assert get_effective_ability_modifier(pc, "strength") == 3


# ── Test Speed from Feats ────────────────────────────────────────────


class TestFeatSpeed:
    """Tests for feat bonus_speed aggregation."""

    def test_no_feats_base_speed(self):
        pc = _make_pc(speed={"walk": 30})
        assert get_effective_speed(pc) == 30

    def test_mobile_feat(self):
        feat = _make_feat(name="Mobile", bonus_speed=10)
        pc = _make_pc(speed={"walk": 30}, feats=[feat])
        assert get_effective_speed(pc) == 40

    def test_feat_plus_equipment_speed(self):
        feat = _make_feat(bonus_speed=10)
        boots = _make_wondrous(name="Boots", slot=EquipmentSlot.BOOTS, bonus_speed=10)
        pc = _make_pc(speed={"walk": 30}, feats=[feat], equipment=[boots])
        assert get_effective_speed(pc) == 50

    def test_speed_minimum_zero(self):
        feat = _make_feat(bonus_speed=-50)
        pc = _make_pc(speed={"walk": 30}, feats=[feat])
        assert get_effective_speed(pc) == 0


# ── Test AC from Feats ───────────────────────────────────────────────


class TestFeatAC:
    """Tests for feat bonus_ac aggregation via get_passive_ac_bonus."""

    def test_no_feats_no_bonus(self):
        pc = _make_pc()
        assert get_passive_ac_bonus(pc) == 0

    def test_dual_wielder_feat(self):
        feat = _make_feat(name="Dual Wielder", bonus_ac=1)
        pc = _make_pc(feats=[feat])
        assert get_passive_ac_bonus(pc) == 1

    def test_feat_plus_equipment_ac(self):
        feat = _make_feat(bonus_ac=1)
        ring = _make_wondrous(name="Ring of Protection", bonus_ac=1)
        pc = _make_pc(feats=[feat], equipment=[ring])
        assert get_passive_ac_bonus(pc) == 2


# ── Test Initiative Bonus ────────────────────────────────────────────


class TestInitiativeBonus:
    """Tests for get_initiative_bonus from feats."""

    def test_no_feats_zero(self):
        pc = _make_pc()
        assert get_initiative_bonus(pc) == 0

    def test_base_creature_zero(self):
        c = _make_creature()
        assert get_initiative_bonus(c) == 0

    def test_alert_feat(self):
        feat = _make_feat(name="Alert", bonus_initiative=5)
        pc = _make_pc(feats=[feat])
        assert get_initiative_bonus(pc) == 5

    def test_multiple_feats_stack(self):
        feats = [
            _make_feat(name="Alert", bonus_initiative=5),
            _make_feat(name="Custom", bonus_initiative=2),
        ]
        pc = _make_pc(feats=feats)
        assert get_initiative_bonus(pc) == 7


# ── Test Damage Resistances from Feats ───────────────────────────────


class TestFeatDamageResistances:
    """Tests for feat-granted damage resistances."""

    def test_no_feats_base_only(self):
        pc = _make_pc(damage_resistances=["fire"])
        assert get_effective_damage_resistances(pc) == ["fire"]

    def test_feat_adds_resistance(self):
        feat = _make_feat(grants_damage_resistances=["cold"])
        pc = _make_pc(feats=[feat])
        assert "cold" in get_effective_damage_resistances(pc)

    def test_feat_deduplicates_with_base(self):
        feat = _make_feat(grants_damage_resistances=["fire"])
        pc = _make_pc(damage_resistances=["fire"], feats=[feat])
        result = get_effective_damage_resistances(pc)
        assert result.count("fire") == 1

    def test_feat_deduplicates_with_equipment(self):
        feat = _make_feat(grants_damage_resistances=["fire"])
        ring = _make_wondrous(grants_damage_resistances=["fire"])
        pc = _make_pc(feats=[feat], equipment=[ring])
        result = get_effective_damage_resistances(pc)
        assert result.count("fire") == 1


# ── Test Damage Immunities from Feats ────────────────────────────────


class TestFeatDamageImmunities:
    """Tests for feat-granted damage immunities."""

    def test_feat_adds_immunity(self):
        feat = _make_feat(grants_damage_immunities=["poison"])
        pc = _make_pc(feats=[feat])
        assert "poison" in get_effective_damage_immunities(pc)

    def test_feat_deduplicates(self):
        feat = _make_feat(grants_damage_immunities=["poison"])
        pc = _make_pc(damage_immunities=["poison"], feats=[feat])
        result = get_effective_damage_immunities(pc)
        assert result.count("poison") == 1


# ── Test Condition Immunities from Feats ─────────────────────────────


class TestFeatConditionImmunities:
    """Tests for feat-granted condition immunities."""

    def test_feat_adds_condition_immunity(self):
        feat = _make_feat(grants_condition_immunities=["frightened"])
        pc = _make_pc(feats=[feat])
        assert "frightened" in get_effective_condition_immunities(pc)

    def test_feat_deduplicates(self):
        feat = _make_feat(grants_condition_immunities=["frightened"])
        pc = _make_pc(condition_immunities=["frightened"], feats=[feat])
        result = get_effective_condition_immunities(pc)
        assert result.count("frightened") == 1


# ── Test Saving Throw Proficiencies from Feats ───────────────────────


class TestFeatSavingThrowProficiencies:
    """Tests for get_effective_saving_throw_proficiencies."""

    def test_no_feats_base_only(self):
        pc = _make_pc(saving_throw_proficiencies=["strength", "constitution"])
        result = get_effective_saving_throw_proficiencies(pc)
        assert "strength" in result
        assert "constitution" in result

    def test_base_creature(self):
        c = _make_creature(saving_throw_proficiencies=["wisdom"])
        result = get_effective_saving_throw_proficiencies(c)
        assert "wisdom" in result

    def test_feat_adds_proficiency(self):
        feat = _make_feat(
            name="Resilient",
            grants_saving_throw_proficiencies=["dexterity"],
        )
        pc = _make_pc(
            saving_throw_proficiencies=["strength"],
            feats=[feat],
        )
        result = get_effective_saving_throw_proficiencies(pc)
        assert "strength" in result
        assert "dexterity" in result

    def test_feat_deduplicates(self):
        feat = _make_feat(
            grants_saving_throw_proficiencies=["strength"],
        )
        pc = _make_pc(
            saving_throw_proficiencies=["strength"],
            feats=[feat],
        )
        result = get_effective_saving_throw_proficiencies(pc)
        assert result.count("strength") == 1

    def test_multiple_feats(self):
        feats = [
            _make_feat(name="R1", grants_saving_throw_proficiencies=["dexterity"]),
            _make_feat(name="R2", grants_saving_throw_proficiencies=["wisdom"]),
        ]
        pc = _make_pc(
            saving_throw_proficiencies=["strength"],
            feats=feats,
        )
        result = get_effective_saving_throw_proficiencies(pc)
        assert "strength" in result
        assert "dexterity" in result
        assert "wisdom" in result

    def test_empty_feats_empty_base(self):
        pc = _make_pc(saving_throw_proficiencies=[])
        assert get_effective_saving_throw_proficiencies(pc) == []
