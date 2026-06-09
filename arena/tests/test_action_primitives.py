"""Tests for new Action primitive fields and helpers.

Tests cover:
- New field defaults (reaction_trigger, target_count, upcast_target_count,
  damage_type_choices, condition_save_to_end, condition_save_to_end_dc,
  condition_duration_type, condition_duration_rounds)
- get_effective_target_count() with and without upcast scaling
- Condition save-to-end integration in resolve_effect() and resolve_attack_damage()
- JSON round-trip serialization of new fields
"""

import pytest
from unittest.mock import patch

from arena.models.character import Creature, PlayerCharacter
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action, ActionType, TargetType, Attack, DamageRoll, DamageType,
    SavingThrowEffect,
)
from arena.models.conditions import Condition, AppliedCondition
from arena.combat.actions import (
    get_effective_target_count,
    resolve_effect,
    resolve_attack_damage,
    resolve_attack_hit,
)
from arena.grid.hexgrid import HexGrid
from arena.grid.coordinates import HexCoord


# ── Test Helpers ──────────────────────────────────────────────────────


def _make_creature(
    name: str = "Test",
    armor_class: int = 10,
    dexterity: int = 10,
    strength: int = 10,
    wisdom: int = 10,
    max_hp: int = 50,
    proficiency_bonus: int = 2,
) -> Creature:
    """Create a minimal creature for testing."""
    return Creature(
        name=name,
        max_hit_points=max_hp,
        armor_class=armor_class,
        ability_scores=AbilityScores(
            strength=strength,
            dexterity=dexterity,
            constitution=10,
            intelligence=10,
            wisdom=wisdom,
            charisma=10,
        ),
        speed={"walk": 30},
        proficiency_bonus=proficiency_bonus,
    )


def _make_pc(
    name: str = "Wizard",
    wisdom: int = 16,
    proficiency_bonus: int = 3,
    spellcasting_ability: str = "wisdom",
) -> PlayerCharacter:
    """Create a minimal PC with spellcasting ability."""
    return PlayerCharacter(
        name=name,
        max_hit_points=40,
        armor_class=12,
        ability_scores=AbilityScores(
            strength=10,
            dexterity=14,
            constitution=12,
            intelligence=10,
            wisdom=wisdom,
            charisma=10,
        ),
        speed={"walk": 30},
        proficiency_bonus=proficiency_bonus,
        character_class="Cleric",
        level=5,
        spellcasting_ability=spellcasting_ability,
    )


def _make_grid_with_creatures(caster_id: str, target_id: str):
    """Create a small grid and place two creatures adjacent."""
    grid = HexGrid(width=10, height=10)
    grid.place_creature(HexCoord(2, 2), caster_id)
    grid.place_creature(HexCoord(2, 3), target_id)
    return grid


# ══════════════════════════════════════════════════════════════════════
# 1. Field defaults
# ══════════════════════════════════════════════════════════════════════


class TestActionFieldDefaults:
    """Verify new primitive fields have correct defaults."""

    def test_action_defaults(self):
        action = Action(name="Test", description="Test")
        assert action.reaction_trigger is None
        assert action.target_count == 1
        assert action.upcast_target_count == 0
        assert action.damage_type_choices == []
        assert action.condition_save_to_end is None
        assert action.condition_save_to_end_dc is None
        assert action.condition_duration_type == "indefinite"
        assert action.condition_duration_rounds is None

    def test_fields_accept_custom_values(self):
        action = Action(
            name="Hold Person",
            description="Paralyze a humanoid",
            reaction_trigger="when hit by attack",
            target_count=2,
            upcast_target_count=1,
            damage_type_choices=["fire", "cold"],
            condition_save_to_end="wisdom",
            condition_save_to_end_dc=15,
            condition_duration_type="rounds",
            condition_duration_rounds=10,
        )
        assert action.reaction_trigger == "when hit by attack"
        assert action.target_count == 2
        assert action.upcast_target_count == 1
        assert action.damage_type_choices == ["fire", "cold"]
        assert action.condition_save_to_end == "wisdom"
        assert action.condition_save_to_end_dc == 15
        assert action.condition_duration_type == "rounds"
        assert action.condition_duration_rounds == 10


# ══════════════════════════════════════════════════════════════════════
# 2. get_effective_target_count()
# ══════════════════════════════════════════════════════════════════════


class TestGetEffectiveTargetCount:
    """Tests for the target count helper function."""

    def test_target_count_no_upcast(self):
        action = Action(
            name="Magic Missile", description="...",
            target_count=3, spell_level=1,
        )
        assert get_effective_target_count(action) == 3

    def test_target_count_with_upcast(self):
        action = Action(
            name="Magic Missile", description="...",
            target_count=3, spell_level=1, upcast_target_count=1,
        )
        assert get_effective_target_count(action, cast_level=3) == 5  # 3 + 2*1

    def test_target_count_no_scaling(self):
        """No upcast_target_count means target count stays constant."""
        action = Action(
            name="Fireball", description="...",
            target_count=1, spell_level=3,
        )
        assert get_effective_target_count(action, cast_level=5) == 1

    def test_target_count_at_base_level(self):
        """Upcasting at base level adds 0 extra targets."""
        action = Action(
            name="Hold Person", description="...",
            target_count=1, spell_level=2, upcast_target_count=1,
        )
        assert get_effective_target_count(action, cast_level=2) == 1

    def test_target_count_non_spell(self):
        """Non-spell action (spell_level=None) ignores cast_level."""
        action = Action(
            name="Multiattack", description="...",
            target_count=3,
        )
        assert get_effective_target_count(action, cast_level=5) == 3

    def test_target_count_no_cast_level(self):
        """Calling without cast_level returns base target_count."""
        action = Action(
            name="Scorching Ray", description="...",
            target_count=3, spell_level=2, upcast_target_count=1,
        )
        assert get_effective_target_count(action) == 3

    def test_target_count_below_spell_level(self):
        """cast_level below spell_level still returns base count."""
        action = Action(
            name="Hold Person", description="...",
            target_count=1, spell_level=2, upcast_target_count=1,
        )
        # cast_level=1 < spell_level=2: extra_levels = 0
        assert get_effective_target_count(action, cast_level=1) == 1

    def test_target_count_multi_per_level(self):
        """upcast_target_count > 1 scales faster."""
        action = Action(
            name="Custom Spell", description="...",
            target_count=2, spell_level=1, upcast_target_count=2,
        )
        # 2 + (3-1)*2 = 6
        assert get_effective_target_count(action, cast_level=3) == 6


# ══════════════════════════════════════════════════════════════════════
# 3. Condition save-to-end integration
# ══════════════════════════════════════════════════════════════════════


class TestConditionSaveToEndIntegration:
    """Test that condition fields on Action flow through to AppliedCondition."""

    def test_direct_condition_with_save_to_end(self):
        """Direct conditions (no saving throw) use action's condition fields."""
        caster = _make_creature(name="Caster")
        target = _make_creature(name="Target")
        grid = _make_grid_with_creatures("caster_1", "target_1")

        action = Action(
            name="Fear Gaze",
            description="Frightens the target",
            target_type=TargetType.ONE_CREATURE,
            range=30,
            conditions_applied=["frightened"],
            condition_save_to_end="wisdom",
            condition_save_to_end_dc=14,
            condition_duration_type="rounds",
            condition_duration_rounds=10,
        )

        result = resolve_effect(
            caster, "caster_1", target, "target_1", action, grid,
        )
        assert result.success

        # Check the applied condition
        frightened = [
            ac for ac in target.active_conditions
            if ac.condition == Condition.FRIGHTENED
        ]
        assert len(frightened) == 1
        ac = frightened[0]
        assert ac.save_to_end == "wisdom"
        assert ac.save_dc == 14
        assert ac.duration_type == "rounds"
        assert ac.duration_rounds == 10

    def test_direct_condition_no_save_to_end(self):
        """Without condition_save_to_end, conditions get default (indefinite)."""
        caster = _make_creature(name="Caster")
        target = _make_creature(name="Target")
        grid = _make_grid_with_creatures("caster_1", "target_1")

        action = Action(
            name="Grapple Effect",
            description="Grapples the target",
            target_type=TargetType.ONE_CREATURE,
            range=30,
            conditions_applied=["grappled"],
        )

        result = resolve_effect(
            caster, "caster_1", target, "target_1", action, grid,
        )
        assert result.success

        grappled = [
            ac for ac in target.active_conditions
            if ac.condition == Condition.GRAPPLED
        ]
        assert len(grappled) == 1
        ac = grappled[0]
        assert ac.save_to_end is None
        assert ac.save_dc is None
        assert ac.duration_type == "indefinite"
        assert ac.duration_rounds is None

    def test_direct_condition_dc_from_spellcasting_ability(self):
        """When condition_save_to_end_dc is None, compute from PC spell save DC."""
        caster = _make_pc(
            name="Cleric", wisdom=16, proficiency_bonus=3,
            spellcasting_ability="wisdom",
        )
        target = _make_creature(name="Target")
        grid = _make_grid_with_creatures("cleric_1", "target_1")

        action = Action(
            name="Command",
            description="Command a creature",
            target_type=TargetType.ONE_CREATURE,
            range=60,
            conditions_applied=["charmed"],
            condition_save_to_end="wisdom",
            # No explicit DC -- should compute: 8 + 3 (prof) + 3 (WIS mod) = 14
            condition_duration_type="end_of_turn",
        )

        result = resolve_effect(
            caster, "cleric_1", target, "target_1", action, grid,
        )
        assert result.success

        charmed = [
            ac for ac in target.active_conditions
            if ac.condition == Condition.CHARMED
        ]
        assert len(charmed) == 1
        ac = charmed[0]
        assert ac.save_to_end == "wisdom"
        assert ac.save_dc == 14  # 8 + 3 + 3
        assert ac.duration_type == "end_of_turn"

    def test_attack_condition_with_save_to_end(self):
        """Conditions applied on attack hit also use action's condition fields."""
        attacker = _make_creature(name="Attacker", strength=16)
        target = _make_creature(name="Target", armor_class=5)
        grid = _make_grid_with_creatures("atk_1", "tgt_1")

        action = Action(
            name="Venomous Bite",
            description="Bite that poisons",
            target_type=TargetType.ONE_CREATURE,
            range=5,
            attack=Attack(
                name="Venomous Bite",
                attack_type="melee_weapon",
                ability="strength",
                reach=5,
                damage=[DamageRoll(dice="1d6", damage_type=DamageType.PIERCING)],
            ),
            conditions_applied=["poisoned"],
            condition_save_to_end="constitution",
            condition_save_to_end_dc=13,
            condition_duration_type="rounds",
            condition_duration_rounds=5,
        )

        # Force a hit with a high roll
        with patch("arena.combat.actions.roll_die", return_value=20):
            hit_result = resolve_attack_hit(
                attacker, "atk_1", target, "tgt_1", action, grid,
            )
        assert hit_result.hit

        damage_result = resolve_attack_damage(hit_result)
        assert damage_result.success

        poisoned = [
            ac for ac in target.active_conditions
            if ac.condition == Condition.POISONED
        ]
        assert len(poisoned) == 1
        ac = poisoned[0]
        assert ac.save_to_end == "constitution"
        assert ac.save_dc == 13
        assert ac.duration_type == "rounds"
        assert ac.duration_rounds == 5

    def test_dc_fallback_to_saving_throw_dc(self):
        """For non-PC casters without spellcasting_ability, fallback to save DC."""
        monster = _make_creature(name="Monster")
        target = _make_creature(name="Target")
        grid = _make_grid_with_creatures("monster_1", "target_1")

        action = Action(
            name="Terrifying Presence",
            description="Frighten nearby creatures",
            target_type=TargetType.ONE_CREATURE,
            range=60,
            saving_throw=SavingThrowEffect(
                ability="wisdom",
                dc=16,
            ),
            conditions_applied=["frightened"],
            condition_save_to_end="wisdom",
            # No explicit DC, no spellcasting_ability on Creature
            # Should fall back to saving_throw.dc = 16
            condition_duration_type="end_of_turn",
        )

        # This action has a saving throw, so conditions_applied won't go
        # through the "direct conditions" path. We need to verify the
        # direct-conditions path uses fallback DC. Create a separate action
        # without saving_throw to test the fallback.
        action_direct = Action(
            name="Terrifying Presence Direct",
            description="Frighten with no save to apply",
            target_type=TargetType.ONE_CREATURE,
            range=60,
            saving_throw=SavingThrowEffect(
                ability="wisdom",
                dc=16,
            ),
            conditions_applied=["frightened"],
            condition_save_to_end="wisdom",
            condition_duration_type="end_of_turn",
        )

        # The direct conditions path is skipped when saving_throw exists,
        # so let's just test _compute_condition_save_dc directly
        from arena.combat.actions import _compute_condition_save_dc
        dc = _compute_condition_save_dc(monster, action_direct)
        assert dc == 16


# ══════════════════════════════════════════════════════════════════════
# 4. Serialization round-trip
# ══════════════════════════════════════════════════════════════════════


class TestActionSerialization:
    """Verify JSON round-tripping of new fields."""

    def test_action_serialization_basic(self):
        action = Action(
            name="Chromatic Orb", description="Hurl an orb of elemental energy",
            damage_type_choices=["acid", "cold", "fire", "lightning", "poison", "thunder"],
            reaction_trigger=None,
            target_count=1,
        )
        data = action.model_dump()
        restored = Action(**data)
        assert restored.damage_type_choices == action.damage_type_choices
        assert restored.reaction_trigger is None
        assert restored.target_count == 1

    def test_action_serialization_all_new_fields(self):
        action = Action(
            name="Hold Person",
            description="Paralyze a humanoid",
            reaction_trigger="when hit by attack",
            target_count=1,
            upcast_target_count=1,
            damage_type_choices=["fire"],
            condition_save_to_end="wisdom",
            condition_save_to_end_dc=15,
            condition_duration_type="end_of_turn",
            condition_duration_rounds=None,
            spell_level=2,
        )
        data = action.model_dump()
        restored = Action(**data)
        assert restored.reaction_trigger == "when hit by attack"
        assert restored.target_count == 1
        assert restored.upcast_target_count == 1
        assert restored.damage_type_choices == ["fire"]
        assert restored.condition_save_to_end == "wisdom"
        assert restored.condition_save_to_end_dc == 15
        assert restored.condition_duration_type == "end_of_turn"
        assert restored.condition_duration_rounds is None

    def test_action_json_round_trip(self):
        """Full JSON string round-trip."""
        action = Action(
            name="Test Spell",
            description="A test spell",
            target_count=3,
            upcast_target_count=1,
            spell_level=2,
            condition_save_to_end="charisma",
            condition_save_to_end_dc=12,
            condition_duration_type="rounds",
            condition_duration_rounds=5,
        )
        json_str = action.model_dump_json()
        restored = Action.model_validate_json(json_str)
        assert restored.target_count == 3
        assert restored.upcast_target_count == 1
        assert restored.condition_save_to_end == "charisma"
        assert restored.condition_save_to_end_dc == 12
        assert restored.condition_duration_type == "rounds"
        assert restored.condition_duration_rounds == 5
