"""Tests for character and creature models."""

import pytest
from arena.models.character import Creature, PlayerCharacter, CreatureSize, CreatureType, Feature
from arena.models.abilities import AbilityScores


class TestCreature:
    """Tests for the base Creature model."""

    def test_creature_creation(self):
        """Basic creature creation should work."""
        creature = Creature(name="Test Creature", max_hit_points=10)
        assert creature.name == "Test Creature"
        assert creature.max_hit_points == 10
        assert creature.current_hit_points == 10  # Auto-set from max

    def test_current_hp_defaults_to_max(self):
        """Current HP should default to max HP."""
        creature = Creature(name="Test", max_hit_points=50)
        assert creature.current_hit_points == 50

    def test_current_hp_can_be_set(self):
        """Current HP can be set explicitly."""
        creature = Creature(name="Test", max_hit_points=50, current_hit_points=25)
        assert creature.current_hit_points == 25

    def test_hp_percent(self):
        """HP percentage calculation should be correct."""
        creature = Creature(name="Test", max_hit_points=100, current_hit_points=75)
        assert creature.hp_percent == 0.75

    def test_is_bloodied(self):
        """Bloodied status should be correct at various HP levels."""
        creature = Creature(name="Test", max_hit_points=100)

        creature.current_hit_points = 100
        assert not creature.is_bloodied

        creature.current_hit_points = 51
        assert not creature.is_bloodied

        creature.current_hit_points = 50
        assert not creature.is_bloodied  # Exactly 50% is not bloodied

        creature.current_hit_points = 49
        assert creature.is_bloodied

    def test_is_conscious(self):
        """Consciousness check should be correct."""
        creature = Creature(name="Test", max_hit_points=100)

        creature.current_hit_points = 1
        assert creature.is_conscious

        creature.current_hit_points = 0
        assert not creature.is_conscious

    def test_default_size_and_type(self):
        """Default size and type should be Medium Humanoid."""
        creature = Creature(name="Test", max_hit_points=10)
        assert creature.size == CreatureSize.MEDIUM
        assert creature.creature_type == CreatureType.HUMANOID

    def test_saving_throw_modifier_without_proficiency(self):
        """Saving throw without proficiency uses just ability modifier."""
        creature = Creature(
            name="Test",
            max_hit_points=10,
            ability_scores=AbilityScores(dexterity=14),
            proficiency_bonus=2,
        )
        assert creature.get_saving_throw_modifier("dexterity") == 2  # Just +2 from DEX

    def test_saving_throw_modifier_with_proficiency(self):
        """Saving throw with proficiency adds proficiency bonus."""
        creature = Creature(
            name="Test",
            max_hit_points=10,
            ability_scores=AbilityScores(constitution=16),
            proficiency_bonus=3,
            saving_throw_proficiencies=["constitution"],
        )
        assert creature.get_saving_throw_modifier("constitution") == 6  # +3 CON + 3 prof

    def test_default_speed(self):
        """Default speed should be 30 ft walking."""
        creature = Creature(name="Test", max_hit_points=10)
        assert creature.speed == {"walk": 30}


class TestPlayerCharacter:
    """Tests for the PlayerCharacter model."""

    def test_player_character_creation(self):
        """Basic PC creation should work."""
        pc = PlayerCharacter(
            name="Test Hero",
            character_class="Fighter",
            max_hit_points=12,
        )
        assert pc.name == "Test Hero"
        assert pc.character_class == "Fighter"
        assert pc.level == 1
        assert pc.race == "Human"

    def test_total_level_without_multiclass(self):
        """Total level without multiclass should equal base level."""
        pc = PlayerCharacter(
            name="Test",
            character_class="Fighter",
            level=5,
            max_hit_points=45,
        )
        assert pc.total_level == 5

    def test_total_level_with_multiclass(self):
        """Total level should include multiclass levels."""
        pc = PlayerCharacter(
            name="Test",
            character_class="Fighter",
            level=5,
            multiclass=[{"Rogue": 3}],
            max_hit_points=60,
        )
        assert pc.total_level == 8

    def test_default_player_controlled(self):
        """PCs should be player-controlled by default."""
        pc = PlayerCharacter(
            name="Test",
            character_class="Fighter",
            max_hit_points=10,
        )
        assert pc.is_player_controlled is True

    def test_spell_slots(self):
        """Spell slot tracking should work."""
        pc = PlayerCharacter(
            name="Test Wizard",
            character_class="Wizard",
            level=3,
            max_hit_points=14,
            spell_slots={1: 4, 2: 2},
        )
        assert pc.spell_slots[1] == 4
        assert pc.spell_slots[2] == 2

    def test_features_list(self):
        """Features should be stored correctly."""
        pc = PlayerCharacter(
            name="Test",
            character_class="Fighter",
            max_hit_points=12,
            features=[
                Feature(name="Second Wind", description="Heal 1d10+level"),
                Feature(name="Fighting Style", description="+1 AC"),
            ],
        )
        assert len(pc.features) == 2
        assert pc.features[0].name == "Second Wind"


class TestCreatureSize:
    """Tests for CreatureSize enum."""

    def test_size_values(self):
        """All standard sizes should be available."""
        assert CreatureSize.TINY.value == "tiny"
        assert CreatureSize.SMALL.value == "small"
        assert CreatureSize.MEDIUM.value == "medium"
        assert CreatureSize.LARGE.value == "large"
        assert CreatureSize.HUGE.value == "huge"
        assert CreatureSize.GARGANTUAN.value == "gargantuan"
