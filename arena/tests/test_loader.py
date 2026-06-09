"""Tests for JSON loading utilities."""

import pytest
import json
import tempfile
from pathlib import Path
from arena.util.loader import (
    load_json,
    save_json,
    load_character,
    load_monster,
    load_encounter,
    save_character,
    save_monster,
    save_encounter,
)
from arena.models.character import PlayerCharacter
from arena.models.monster import Monster
from arena.models.encounter import Encounter


class TestJsonIO:
    """Tests for basic JSON I/O."""

    def test_load_json(self, tmp_path):
        """Load a JSON file."""
        test_data = {"name": "Test", "value": 42}
        file_path = tmp_path / "test.json"
        file_path.write_text(json.dumps(test_data))

        result = load_json(file_path)
        assert result == test_data

    def test_load_json_not_found(self):
        """Loading nonexistent file raises error."""
        with pytest.raises(FileNotFoundError):
            load_json("nonexistent.json")

    def test_save_json(self, tmp_path):
        """Save data to JSON file."""
        test_data = {"name": "Test", "value": 42}
        file_path = tmp_path / "output.json"

        save_json(test_data, file_path)

        assert file_path.exists()
        loaded = json.loads(file_path.read_text())
        assert loaded == test_data

    def test_save_json_creates_dirs(self, tmp_path):
        """Save should create parent directories."""
        test_data = {"test": True}
        file_path = tmp_path / "subdir" / "deep" / "output.json"

        save_json(test_data, file_path)

        assert file_path.exists()


class TestLoadSampleFiles:
    """Tests for loading the sample data files."""

    def test_load_thorin(self):
        """Load the Thorin sample character."""
        thorin = load_character("data/characters/thorin.json")
        assert thorin.name == "Thorin Ironforge"
        assert thorin.character_class == "Fighter"
        assert thorin.level == 5
        assert thorin.max_hit_points == 52
        assert thorin.armor_class == 18

    def test_load_elara(self):
        """Load the Elara sample character."""
        elara = load_character("data/characters/elara.json")
        assert elara.name == "Elara Nightwhisper"
        assert elara.character_class == "Wizard"
        assert len(elara.spells_known) > 0

    def test_load_goblin(self):
        """Load the Goblin sample monster."""
        goblin = load_monster("data/monsters/goblin.json")
        assert goblin.name == "Goblin"
        assert goblin.challenge_rating == 0.25
        assert goblin.ai_profile == "coward"

    def test_load_goblin_boss(self):
        """Load the Goblin Boss sample monster."""
        boss = load_monster("data/monsters/goblin_boss.json")
        assert boss.name == "Goblin Boss"
        assert boss.challenge_rating == 1

    def test_load_wolf(self):
        """Load the Wolf sample monster."""
        wolf = load_monster("data/monsters/wolf.json")
        assert wolf.name == "Wolf"
        assert len(wolf.special_abilities) == 2

    def test_load_goblin_ambush(self):
        """Load the Goblin Ambush encounter."""
        encounter = load_encounter("data/encounters/goblin_ambush.json")
        assert encounter.name == "Goblin Ambush"
        assert len(encounter.combatants) == 7
        assert len(encounter.terrain) > 0


class TestRoundTrip:
    """Tests for saving and reloading models."""

    def test_character_roundtrip(self, tmp_path):
        """Save and reload a character."""
        original = PlayerCharacter(
            name="Test Hero",
            character_class="Paladin",
            level=3,
            max_hit_points=28,
            armor_class=16,
        )
        file_path = tmp_path / "test_char.json"

        save_character(original, file_path)
        loaded = load_character(file_path)

        assert loaded.name == original.name
        assert loaded.character_class == original.character_class
        assert loaded.level == original.level

    def test_monster_roundtrip(self, tmp_path):
        """Save and reload a monster."""
        original = Monster(
            name="Test Monster",
            max_hit_points=45,
            challenge_rating=3,
        )
        file_path = tmp_path / "test_monster.json"

        save_monster(original, file_path)
        loaded = load_monster(file_path)

        assert loaded.name == original.name
        assert loaded.challenge_rating == original.challenge_rating

    def test_encounter_roundtrip(self, tmp_path):
        """Save and reload an encounter."""
        from arena.models.encounter import CombatantEntry, TerrainHex, TerrainType

        original = Encounter(
            name="Test Battle",
            grid_width=15,
            grid_height=10,
            combatants=[
                CombatantEntry(creature_id="test.json", team="player"),
            ],
            terrain=[
                TerrainHex(position=(5, 5), terrain_type=TerrainType.DIFFICULT),
            ],
        )
        file_path = tmp_path / "test_encounter.json"

        save_encounter(original, file_path)
        loaded = load_encounter(file_path)

        assert loaded.name == original.name
        assert loaded.grid_width == original.grid_width
        assert len(loaded.combatants) == 1
        assert len(loaded.terrain) == 1
