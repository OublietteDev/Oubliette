"""Tests for cantrip scaling (src/combat/cantrip_scaling.py).

Tests cover:
- get_cantrip_scale_factor at all breakpoints
- scale_cantrip_damage with various dice expressions
- get_cantrip_extra_beam_count
- estimate_level_from_proficiency
- get_caster_level for PlayerCharacter and base Creature
- Integration: resolve_attack_damage scales attack cantrip damage
- Integration: resolve_effect scales save cantrip damage
"""

import pytest
from unittest.mock import patch

from arena.models.character import Creature, PlayerCharacter
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action, ActionType, TargetType,
    Attack, DamageRoll, DamageType,
    SavingThrowEffect,
)
from arena.combat.cantrip_scaling import (
    get_cantrip_scale_factor,
    scale_cantrip_damage,
    get_cantrip_extra_beam_count,
    estimate_level_from_proficiency,
    get_caster_level,
)
from arena.combat.actions import resolve_attack_hit, resolve_attack_damage, resolve_effect
from arena.grid.hexgrid import HexGrid
from arena.grid.coordinates import HexCoord


# ── Test Helpers ──────────────────────────────────────────────────────


def _make_creature(
    name: str = "Test",
    max_hp: int = 50,
    proficiency_bonus: int = 2,
) -> Creature:
    """Create a minimal creature for testing."""
    return Creature(
        name=name,
        max_hit_points=max_hp,
        armor_class=10,
        proficiency_bonus=proficiency_bonus,
        ability_scores=AbilityScores(
            strength=10, dexterity=10, constitution=10,
            intelligence=10, wisdom=10, charisma=10,
        ),
    )


def _make_pc(
    name: str = "Wizard",
    level: int = 1,
    max_hp: int = 50,
    intelligence: int = 16,
) -> PlayerCharacter:
    """Create a minimal PlayerCharacter for testing."""
    return PlayerCharacter(
        name=name,
        character_class="Wizard",
        level=level,
        max_hit_points=max_hp,
        armor_class=12,
        proficiency_bonus=2 + (level - 1) // 4,
        ability_scores=AbilityScores(
            strength=10, dexterity=14, constitution=12,
            intelligence=intelligence, wisdom=10, charisma=10,
        ),
    )


def _make_fire_bolt(cantrip_scaling: bool = True) -> Action:
    """Create a Fire Bolt cantrip action."""
    return Action(
        name="Fire Bolt",
        description="Ranged spell attack, 1d10 fire damage.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=120,
        cantrip_scaling=cantrip_scaling,
        attack=Attack(
            name="Fire Bolt",
            attack_type="ranged_spell",
            ability="intelligence",
            range_normal=120,
            damage=[DamageRoll(dice="1d10", damage_type=DamageType.FIRE)],
        ),
    )


def _make_sacred_flame() -> Action:
    """Create a Sacred Flame cantrip (save-based)."""
    return Action(
        name="Sacred Flame",
        description="DEX save or 1d8 radiant damage.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=60,
        cantrip_scaling=True,
        saving_throw=SavingThrowEffect(
            ability="dexterity",
            dc=13,
            damage_on_fail=[DamageRoll(dice="1d8", damage_type=DamageType.RADIANT)],
            damage_on_success="none",
        ),
    )


def _setup_grid():
    """Create a small grid with two creatures placed."""
    grid = HexGrid(width=10, height=10)
    grid.place_creature(HexCoord(0, 0), "attacker_1")
    grid.place_creature(HexCoord(1, 0), "target_1")
    return grid


# ═══════════════════════════════════════════════════════════════════════
# Unit Tests: get_cantrip_scale_factor
# ═══════════════════════════════════════════════════════════════════════


class TestGetCantripScaleFactor:
    """Test the cantrip scale factor at all level breakpoints."""

    def test_level_1(self):
        assert get_cantrip_scale_factor(1) == 1

    def test_level_4(self):
        assert get_cantrip_scale_factor(4) == 1

    def test_level_5(self):
        assert get_cantrip_scale_factor(5) == 2

    def test_level_10(self):
        assert get_cantrip_scale_factor(10) == 2

    def test_level_11(self):
        assert get_cantrip_scale_factor(11) == 3

    def test_level_16(self):
        assert get_cantrip_scale_factor(16) == 3

    def test_level_17(self):
        assert get_cantrip_scale_factor(17) == 4

    def test_level_20(self):
        assert get_cantrip_scale_factor(20) == 4


# ═══════════════════════════════════════════════════════════════════════
# Unit Tests: scale_cantrip_damage
# ═══════════════════════════════════════════════════════════════════════


class TestScaleCantripDamage:
    """Test dice expression scaling."""

    def test_1d10_level_1(self):
        assert scale_cantrip_damage("1d10", 1) == "1d10"

    def test_1d10_level_5(self):
        assert scale_cantrip_damage("1d10", 5) == "2d10"

    def test_1d10_level_11(self):
        assert scale_cantrip_damage("1d10", 11) == "3d10"

    def test_1d10_level_17(self):
        assert scale_cantrip_damage("1d10", 17) == "4d10"

    def test_1d8_level_5(self):
        assert scale_cantrip_damage("1d8", 5) == "2d8"

    def test_2d6_base_level_11(self):
        """Multi-dice base (e.g., hypothetical 2d6 cantrip) scales both dice."""
        assert scale_cantrip_damage("2d6", 11) == "6d6"

    def test_1d12_level_20(self):
        assert scale_cantrip_damage("1d12", 20) == "4d12"

    def test_with_modifier(self):
        """Modifier is preserved but not scaled."""
        assert scale_cantrip_damage("1d10+3", 5) == "2d10+3"

    def test_with_negative_modifier(self):
        assert scale_cantrip_damage("1d6-1", 5) == "2d6-1"

    def test_flat_number_unchanged(self):
        """Flat numbers are not scaleable."""
        assert scale_cantrip_damage("5", 11) == "5"


# ═══════════════════════════════════════════════════════════════════════
# Unit Tests: get_cantrip_extra_beam_count
# ═══════════════════════════════════════════════════════════════════════


class TestGetCantripExtraBeamCount:
    """Test Eldritch Blast beam count."""

    def test_level_1(self):
        assert get_cantrip_extra_beam_count(1) == 1

    def test_level_5(self):
        assert get_cantrip_extra_beam_count(5) == 2

    def test_level_11(self):
        assert get_cantrip_extra_beam_count(11) == 3

    def test_level_17(self):
        assert get_cantrip_extra_beam_count(17) == 4


# ═══════════════════════════════════════════════════════════════════════
# Unit Tests: estimate_level_from_proficiency
# ═══════════════════════════════════════════════════════════════════════


class TestEstimateLevelFromProficiency:
    """Test proficiency bonus to level estimation."""

    def test_prof_2(self):
        assert estimate_level_from_proficiency(2) == 1

    def test_prof_3(self):
        assert estimate_level_from_proficiency(3) == 5

    def test_prof_4(self):
        assert estimate_level_from_proficiency(4) == 9

    def test_prof_5(self):
        assert estimate_level_from_proficiency(5) == 13

    def test_prof_6(self):
        assert estimate_level_from_proficiency(6) == 17


# ═══════════════════════════════════════════════════════════════════════
# Unit Tests: get_caster_level
# ═══════════════════════════════════════════════════════════════════════


class TestGetCasterLevel:
    """Test caster level detection for PCs and monsters."""

    def test_player_character_uses_total_level(self):
        pc = _make_pc(level=7)
        assert get_caster_level(pc) == 7

    def test_creature_uses_proficiency_estimate(self):
        creature = _make_creature(proficiency_bonus=3)
        assert get_caster_level(creature) == 5

    def test_creature_prof_2_returns_1(self):
        creature = _make_creature(proficiency_bonus=2)
        assert get_caster_level(creature) == 1


# ═══════════════════════════════════════════════════════════════════════
# Integration Tests: Attack Cantrip (Fire Bolt)
# ═══════════════════════════════════════════════════════════════════════


class TestAttackCantripIntegration:
    """Verify resolve_attack_damage scales cantrip attack damage."""

    @patch("arena.combat.actions.roll_die", return_value=15)
    def test_fire_bolt_level_1_base_damage(self, mock_roll):
        """Level 1: Fire Bolt should roll 1d10."""
        pc = _make_pc(level=1)
        target = _make_creature(name="Goblin")
        grid = _setup_grid()
        action = _make_fire_bolt()

        hit_result = resolve_attack_hit(
            pc, "attacker_1", target, "target_1", action, grid,
        )
        assert hit_result.hit

        result = resolve_attack_damage(hit_result)
        # With roll_die always returning 15, a d10 is rolled via roll_expression
        # which calls roll_die. The damage event should exist.
        damage_events = [
            e for e in result.events
            if e.details.get("damage") is not None
        ]
        assert len(damage_events) == 1
        # At level 1, 1d10 = one die roll
        roll_details = damage_events[0].details.get("roll_details", [])
        assert len(roll_details) >= 1
        assert roll_details[0]["dice"] == "1d10"

    @patch("arena.combat.actions.roll_die", return_value=15)
    def test_fire_bolt_level_5_scaled_damage(self, mock_roll):
        """Level 5: Fire Bolt should roll 2d10."""
        pc = _make_pc(level=5)
        target = _make_creature(name="Goblin")
        grid = _setup_grid()
        action = _make_fire_bolt()

        hit_result = resolve_attack_hit(
            pc, "attacker_1", target, "target_1", action, grid,
        )
        assert hit_result.hit

        result = resolve_attack_damage(hit_result)
        damage_events = [
            e for e in result.events
            if e.details.get("damage") is not None
        ]
        assert len(damage_events) == 1
        roll_details = damage_events[0].details.get("roll_details", [])
        assert roll_details[0]["dice"] == "2d10"

    @patch("arena.combat.actions.roll_die", return_value=15)
    def test_fire_bolt_level_11_scaled_damage(self, mock_roll):
        """Level 11: Fire Bolt should roll 3d10."""
        pc = _make_pc(level=11)
        target = _make_creature(name="Goblin")
        grid = _setup_grid()
        action = _make_fire_bolt()

        hit_result = resolve_attack_hit(
            pc, "attacker_1", target, "target_1", action, grid,
        )
        assert hit_result.hit

        result = resolve_attack_damage(hit_result)
        damage_events = [
            e for e in result.events
            if e.details.get("damage") is not None
        ]
        assert len(damage_events) == 1
        roll_details = damage_events[0].details.get("roll_details", [])
        assert roll_details[0]["dice"] == "3d10"

    @patch("arena.combat.actions.roll_die", return_value=15)
    def test_fire_bolt_level_17_scaled_damage(self, mock_roll):
        """Level 17: Fire Bolt should roll 4d10."""
        pc = _make_pc(level=17)
        target = _make_creature(name="Goblin")
        grid = _setup_grid()
        action = _make_fire_bolt()

        hit_result = resolve_attack_hit(
            pc, "attacker_1", target, "target_1", action, grid,
        )
        assert hit_result.hit

        result = resolve_attack_damage(hit_result)
        damage_events = [
            e for e in result.events
            if e.details.get("damage") is not None
        ]
        assert len(damage_events) == 1
        roll_details = damage_events[0].details.get("roll_details", [])
        assert roll_details[0]["dice"] == "4d10"

    @patch("arena.combat.actions.roll_die", return_value=15)
    def test_non_cantrip_not_scaled(self, mock_roll):
        """Actions without cantrip_scaling should not be modified."""
        pc = _make_pc(level=11)
        target = _make_creature(name="Goblin")
        grid = _setup_grid()
        action = _make_fire_bolt(cantrip_scaling=False)

        hit_result = resolve_attack_hit(
            pc, "attacker_1", target, "target_1", action, grid,
        )
        assert hit_result.hit

        result = resolve_attack_damage(hit_result)
        damage_events = [
            e for e in result.events
            if e.details.get("damage") is not None
        ]
        assert len(damage_events) == 1
        roll_details = damage_events[0].details.get("roll_details", [])
        # Should remain 1d10 — not scaled
        assert roll_details[0]["dice"] == "1d10"

    @patch("arena.combat.actions.roll_die", return_value=15)
    def test_monster_cantrip_scales_by_proficiency(self, mock_roll):
        """Monsters use proficiency bonus to estimate level for scaling."""
        monster = _make_creature(name="Lich", proficiency_bonus=5)  # Est. level 13
        target = _make_creature(name="Hero")
        grid = _setup_grid()
        action = _make_fire_bolt()

        hit_result = resolve_attack_hit(
            monster, "attacker_1", target, "target_1", action, grid,
        )
        assert hit_result.hit

        result = resolve_attack_damage(hit_result)
        damage_events = [
            e for e in result.events
            if e.details.get("damage") is not None
        ]
        assert len(damage_events) == 1
        roll_details = damage_events[0].details.get("roll_details", [])
        # Prof 5 → estimated level 13 → scale factor 3 → 3d10
        assert roll_details[0]["dice"] == "3d10"


# ═══════════════════════════════════════════════════════════════════════
# Integration Tests: Save Cantrip (Sacred Flame)
# ═══════════════════════════════════════════════════════════════════════


class TestSaveCantripIntegration:
    """Verify resolve_effect scales cantrip save damage."""

    @patch("arena.combat.actions.roll_die", return_value=3)
    def test_sacred_flame_level_1(self, mock_roll):
        """Level 1: Sacred Flame damage_on_fail should be 1d8."""
        pc = _make_pc(level=1)
        target = _make_creature(name="Skeleton")
        grid = _setup_grid()
        action = _make_sacred_flame()

        result = resolve_effect(
            pc, "attacker_1", target, "target_1", action, grid,
        )
        # Target should have failed the save (low roll) and taken damage
        damage_events = [
            e for e in result.events
            if e.details.get("damage") is not None
        ]
        assert len(damage_events) == 1
        roll_details = damage_events[0].details.get("roll_details", [])
        assert roll_details[0]["dice"] == "1d8"

    @patch("arena.combat.actions.roll_die", return_value=3)
    def test_sacred_flame_level_5(self, mock_roll):
        """Level 5: Sacred Flame damage_on_fail should be 2d8."""
        pc = _make_pc(level=5)
        target = _make_creature(name="Skeleton")
        grid = _setup_grid()
        action = _make_sacred_flame()

        result = resolve_effect(
            pc, "attacker_1", target, "target_1", action, grid,
        )
        damage_events = [
            e for e in result.events
            if e.details.get("damage") is not None
        ]
        assert len(damage_events) == 1
        roll_details = damage_events[0].details.get("roll_details", [])
        assert roll_details[0]["dice"] == "2d8"

    @patch("arena.combat.actions.roll_die", return_value=3)
    def test_sacred_flame_level_17(self, mock_roll):
        """Level 17: Sacred Flame damage_on_fail should be 4d8."""
        pc = _make_pc(level=17)
        target = _make_creature(name="Skeleton")
        grid = _setup_grid()
        action = _make_sacred_flame()

        result = resolve_effect(
            pc, "attacker_1", target, "target_1", action, grid,
        )
        damage_events = [
            e for e in result.events
            if e.details.get("damage") is not None
        ]
        assert len(damage_events) == 1
        roll_details = damage_events[0].details.get("roll_details", [])
        assert roll_details[0]["dice"] == "4d8"
