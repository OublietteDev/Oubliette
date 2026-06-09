"""The enriched (full-SRD) StatBlock schema (bestiary arc).

Pins two guarantees:
  * a faithful SRD monster — descriptors, defenses, an actions list — validates
    and round-trips field-for-field;
  * the minimal hand-authored block (Brightvale's three) still validates, the
    new fields degrading to their empty defaults (graceful degradation).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from oubliette.content.schemas import Action, StatBlock


def _full_block() -> dict:
    """An Adult-dragon-shaped block exercising every enriched field."""
    return {
        "id": "young_red_dragon", "name": "Young Red Dragon", "kind": "monster",
        "size": "Large", "type": "dragon", "alignment": "chaotic evil", "cr": 10.0,
        "abilities": {"str": 23, "dex": 10, "con": 21, "int": 14, "wis": 11, "cha": 19},
        "hp": 178, "hit_dice": "17d10+85",
        "armor_class": 18, "ac_desc": "natural armor",
        "speed": {"walk": "40 ft.", "climb": "40 ft.", "fly": "80 ft."},
        "attack_bonus": 10, "damage": "2d10+6",
        "saves": {"dex": 4, "con": 9, "wis": 4, "cha": 8},
        "skills": ["perception", "stealth"],
        "skill_bonuses": {"perception": 8, "stealth": 4},
        "damage_immunities": ["fire"],
        "senses": {"blindsight": "30 ft.", "darkvision": "120 ft.", "passive_perception": "18"},
        "languages": "Common, Draconic",
        "xp": 5900,
        "traits": ["Legendary Resistance (rare). Bite, claws, and fiery breath."],
        "actions": [
            {"name": "Multiattack",
             "desc": "The dragon makes three attacks: one bite and two claws."},
            {"name": "Bite", "attack_bonus": 10, "reach": "10 ft.", "target": "one target",
             "damage": "2d10+6", "damage_type": "piercing",
             "desc": "plus 1d6 fire damage."},
        ],
        "loot": [{"gold": 400}],
        "description": "A cocky, swaggering young red dragon.",
        "srd_ref": "young-red-dragon",
    }


def test_full_srd_block_round_trips():
    raw = _full_block()
    sb = StatBlock.model_validate(raw)
    assert sb.cr == 10.0
    assert sb.size == "Large"
    assert sb.speed["fly"] == "80 ft."
    assert sb.damage_immunities == ["fire"]
    assert sb.senses["passive_perception"] == "18"
    # the actions list parses into Action models, verbatim prose preserved
    assert isinstance(sb.actions[0], Action)
    assert sb.actions[0].name == "Multiattack"
    assert sb.actions[1].attack_bonus == 10
    assert sb.actions[1].damage_type == "piercing"
    # combat-seam primary attack untouched by the enrichment
    assert sb.attack_bonus == 10 and sb.damage == "2d10+6"


def test_minimal_block_degrades_gracefully():
    """A pre-enrichment block (only the original fields) still validates; every
    new descriptor lands on its empty default."""
    minimal = {
        "id": "lean_wolf", "name": "lean wolf", "kind": "monster",
        "abilities": {"str": 12, "dex": 15, "con": 12, "int": 3, "wis": 12, "cha": 6},
        "hp": 9, "armor_class": 13, "attack_bonus": 4, "damage": "2d4",
        "xp": 50, "skills": ["perception", "stealth"], "loot": [],
        "description": "Ribs showing, eyes bright with hunger.",
    }
    sb = StatBlock.model_validate(minimal)
    assert sb.cr is None and sb.size is None and sb.type is None
    assert sb.speed == {} and sb.senses == {} and sb.saves == {}
    assert sb.actions == [] and sb.legendary_actions == [] and sb.reactions == []
    assert sb.languages == ""


def test_unknown_field_is_rejected():
    """`extra="forbid"` — a typo'd field is a load error, not a silent drop. This
    is the discipline the content fleet's deterministic parse must satisfy."""
    raw = _full_block()
    raw["challenge"] = 10          # should have been `cr`
    with pytest.raises(ValidationError):
        StatBlock.model_validate(raw)
