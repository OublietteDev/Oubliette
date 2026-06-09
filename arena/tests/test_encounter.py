"""Tests for encounter models."""

import pytest
from arena.models.encounter import Encounter, CombatantEntry, TerrainHex, TerrainType


class TestTerrainType:
    """Tests for TerrainType enum."""

    def test_terrain_types(self):
        """All terrain types should be available."""
        terrain_types = [
            "normal", "difficult", "hazard", "water", "pit", "wall",
            "cover_half", "cover_three_quarters", "cover_full",
        ]
        for tt in terrain_types:
            assert TerrainType(tt) is not None


class TestTerrainHex:
    """Tests for TerrainHex model."""

    def test_basic_terrain(self):
        """Basic terrain hex creation."""
        terrain = TerrainHex(
            position=(5, 5),
            terrain_type=TerrainType.DIFFICULT,
        )
        assert terrain.position == (5, 5)
        assert terrain.terrain_type == TerrainType.DIFFICULT

    def test_hazard_with_data(self):
        """Hazard terrain with extra data."""
        terrain = TerrainHex(
            position=(10, 10),
            terrain_type=TerrainType.HAZARD,
            extra_data={"damage": "1d6", "damage_type": "fire"},
        )
        assert terrain.extra_data["damage"] == "1d6"


class TestCombatantEntry:
    """Tests for CombatantEntry model."""

    def test_basic_combatant(self):
        """Basic combatant entry."""
        entry = CombatantEntry(
            creature_id="monsters/goblin.json",
            team="enemy",
        )
        assert entry.creature_id == "monsters/goblin.json"
        assert entry.team == "enemy"
        assert entry.count == 1

    def test_multiple_creatures(self):
        """Multiple identical creatures."""
        entry = CombatantEntry(
            creature_id="monsters/goblin.json",
            team="enemy",
            count=4,
        )
        assert entry.count == 4

    def test_combatant_with_position(self):
        """Combatant with starting position."""
        entry = CombatantEntry(
            creature_id="characters/fighter.json",
            team="player",
            starting_position=(3, 5),
        )
        assert entry.starting_position == (3, 5)

    def test_name_override(self):
        """Combatant with custom name."""
        entry = CombatantEntry(
            creature_id="monsters/goblin_boss.json",
            team="enemy",
            name_override="Grak the Sneaky",
        )
        assert entry.name_override == "Grak the Sneaky"


class TestEncounter:
    """Tests for Encounter model."""

    def test_basic_encounter(self):
        """Basic encounter creation."""
        encounter = Encounter(name="Test Encounter")
        assert encounter.name == "Test Encounter"
        assert encounter.grid_width == 20
        assert encounter.grid_height == 15

    def test_encounter_with_combatants(self):
        """Encounter with combatants."""
        encounter = Encounter(
            name="Battle",
            combatants=[
                CombatantEntry(creature_id="characters/fighter.json", team="player"),
                CombatantEntry(creature_id="monsters/goblin.json", team="enemy", count=3),
            ],
        )
        assert len(encounter.combatants) == 2

    def test_encounter_with_terrain(self):
        """Encounter with terrain modifications."""
        encounter = Encounter(
            name="Forest Battle",
            terrain=[
                TerrainHex(position=(5, 5), terrain_type=TerrainType.DIFFICULT),
                TerrainHex(position=(10, 10), terrain_type=TerrainType.COVER_HALF),
            ],
        )
        assert len(encounter.terrain) == 2

    def test_encounter_settings(self):
        """Encounter configuration settings."""
        encounter = Encounter(
            name="Test",
            use_ai_for_enemies=True,
            use_ai_for_allies=True,
            auto_roll_initiative=False,
            lighting="dim",
        )
        assert encounter.use_ai_for_enemies is True
        assert encounter.use_ai_for_allies is True
        assert encounter.auto_roll_initiative is False
        assert encounter.lighting == "dim"

    def test_custom_grid_size(self):
        """Encounter with custom grid size."""
        encounter = Encounter(
            name="Large Battle",
            grid_width=40,
            grid_height=30,
        )
        assert encounter.grid_width == 40
        assert encounter.grid_height == 30

    def test_environmental_effects(self):
        """Encounter with environmental effects."""
        encounter = Encounter(
            name="Stormy Battle",
            environmental_effects=["heavy_rain", "strong_wind"],
        )
        assert "heavy_rain" in encounter.environmental_effects
        assert len(encounter.environmental_effects) == 2
