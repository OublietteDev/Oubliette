"""JSON loading and validation utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from arena.models.character import PlayerCharacter
from arena.models.monster import Monster
from arena.models.encounter import Encounter

if TYPE_CHECKING:
    from arena.combat.manager import CombatManager


def load_json(file_path: str | Path) -> dict:
    """Load a JSON file and return its contents."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: dict, file_path: str | Path, indent: int = 2) -> None:
    """Save data to a JSON file."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent)


def load_character(file_path: str | Path) -> PlayerCharacter:
    """Load a player character from a JSON file."""
    data = load_json(file_path)
    return PlayerCharacter.model_validate(data)


def load_monster(file_path: str | Path) -> Monster:
    """Load a monster from a JSON file."""
    data = load_json(file_path)
    return Monster.model_validate(data)


def load_encounter(file_path: str | Path) -> Encounter:
    """Load an encounter from a JSON file."""
    data = load_json(file_path)
    return Encounter.model_validate(data)


def save_character(character: PlayerCharacter, file_path: str | Path) -> None:
    """Save a player character to a JSON file.

    Spell-slot keys (``spell_slot_1``, etc.) that were auto-generated
    by the ``sync_spell_slots_to_resources`` validator are stripped
    from ``class_resources`` before writing so that the spell-slot
    spinners in the Features tab remain the single source of truth.
    """
    data = character.model_dump(mode="json")
    # Strip auto-bridged spell-slot keys — they are regenerated on load
    if "class_resources" in data and "spell_slots" in data:
        bridged_keys = {
            f"spell_slot_{lvl}" for lvl in data["spell_slots"]
        }
        data["class_resources"] = {
            k: v for k, v in data["class_resources"].items()
            if k not in bridged_keys
        }
    save_json(data, file_path)


def save_monster(monster: Monster, file_path: str | Path) -> None:
    """Save a monster to a JSON file."""
    data = monster.model_dump(mode="json")
    save_json(data, file_path)


def save_encounter(encounter: Encounter, file_path: str | Path) -> None:
    """Save an encounter to a JSON file."""
    data = encounter.model_dump(mode="json")
    save_json(data, file_path)


def save_combat_state(cm: CombatManager, file_path: str | Path) -> None:
    """Serialize and save combat state to a JSON file."""
    from arena.combat.serialization import serialize_combat

    data = serialize_combat(cm)
    save_json(data, file_path)


def load_combat_state(file_path: str | Path) -> CombatManager:
    """Load combat state from a JSON file."""
    from arena.combat.serialization import deserialize_combat

    data = load_json(file_path)
    return deserialize_combat(data)
