"""P1 of the authored-content pipeline (design doc §8).

Pins the two guarantees that make the migration safe:
  * `load_pack("brightvale")` produces a repository BYTE-IDENTICAL to the old
    hand-coded `seed_world()` (repo parity) — nothing downstream changes.
  * A broken pack fails at load with one AGGREGATED, clear error — never partially.

Replay-after-pack is exercised by the rest of the suite, which now routes
`Session.open` through the pack; `test_default_session_matches_seed` pins it here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oubliette.content.loader import DEFAULT_PACK, PackValidationError, load_pack
from oubliette.record.events import EventKind
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.session import Session
from oubliette.seed import DEFAULT_SCENE, seed_world


# --- repo parity: the heart of the migration ---------------------------------
def _state(repo):
    """(characters, items, pc_id) — the full materialized baseline."""
    return repo._chars, repo._items, repo._pc_id


def test_load_pack_repository_equals_old_seed():
    world = load_pack(DEFAULT_PACK)
    pack_chars, pack_items, pack_pc = _state(world.repository)
    seed_chars, seed_items, seed_pc = _state(seed_world())

    assert pack_pc == seed_pc
    assert pack_items == seed_items                 # projected items == hand-coded items
    assert pack_chars == seed_chars                 # PC + Thom, field-for-field


def test_load_pack_scene_and_metadata():
    world = load_pack(DEFAULT_PACK)
    assert world.scene == DEFAULT_SCENE             # opening scene unchanged
    assert world.pack_id == "brightvale"
    assert world.pack_version == "1.0.0"


def test_default_session_matches_seed_and_pins_pack():
    """Session.open with no custom seed loads the pack and records pack id/version
    on the start marker, while producing the same baseline as the old seed."""
    session = Session.open(InMemoryEventStore())
    assert _state(session.repo) == _state(seed_world())
    assert session.scene == DEFAULT_SCENE

    start = session.store.read_all()[0]
    assert start.kind == EventKind.SESSION_MARKER.value
    assert start.payload["pack_id"] == "brightvale"
    assert start.payload["pack_version"] == "1.0.0"


# --- validation: broken packs fail loudly and wholly -------------------------
def _minimal_pack() -> dict:
    """A small, fully-valid pack. Tests mutate one file to make it broken."""
    return {
        "pack.json": {
            "id": "t", "schema_version": 1, "name": "Test", "version": "1.0.0",
            "entry_scenario": "s",
        },
        "items.json": [
            {"id": "sword", "name": "sword", "category": "weapon", "base_value": 5},
        ],
        "statblocks.json": [
            {"id": "sb", "name": "guard", "hp": 8, "armor_class": 12},
        ],
        "npcs.json": [
            {
                "id": "n", "name": "N", "stat_block": "sb", "home_location": "p",
                "inventory": [{"item": "sword", "qty": 1}],
                "price_list": {"sword": 5},
            },
        ],
        "places.json": [
            {"id": "p", "name": "P", "description": "a place", "exits": []},
        ],
        "scenarios.json": [
            {
                "id": "s", "name": "S", "start_location": "p",
                "party_source": "default",
                "default_party": [{
                    "id": "pc", "name": "PC", "kind": "pc",
                    "inventory": [{"item_id": "sword", "qty": 1}],
                    "equipped": ["sword"],
                }],
            },
        ],
    }


def _write_pack(root: Path, files: dict, pack_id: str = "t") -> Path:
    d = root / pack_id
    d.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (d / name).write_text(json.dumps(content), encoding="utf-8")
    return root


def test_minimal_pack_is_valid(tmp_path):
    root = _write_pack(tmp_path, _minimal_pack())
    world = load_pack("t", packs_root=root)         # does not raise
    assert world.repository.pc().id == "pc"


def test_missing_required_field(tmp_path):
    files = _minimal_pack()
    del files["statblocks.json"][0]["hp"]           # hp is required
    root = _write_pack(tmp_path, files)
    with pytest.raises(PackValidationError) as exc:
        load_pack("t", packs_root=root)
    assert any("hp" in e for e in exc.value.errors)


def test_unknown_reference(tmp_path):
    files = _minimal_pack()
    files["npcs.json"][0]["home_location"] = "nowhere"
    root = _write_pack(tmp_path, files)
    with pytest.raises(PackValidationError) as exc:
        load_pack("t", packs_root=root)
    assert any("unknown place 'nowhere'" in e for e in exc.value.errors)


def test_duplicate_id(tmp_path):
    files = _minimal_pack()
    files["items.json"].append(
        {"id": "sword", "name": "another sword", "category": "weapon"})
    root = _write_pack(tmp_path, files)
    with pytest.raises(PackValidationError) as exc:
        load_pack("t", packs_root=root)
    assert any("duplicate id 'sword'" in e for e in exc.value.errors)


def test_priced_but_unstocked(tmp_path):
    files = _minimal_pack()
    files["items.json"].append({"id": "shield", "name": "shield", "category": "armor"})
    files["npcs.json"][0]["price_list"]["shield"] = 2   # priced, never stocked
    root = _write_pack(tmp_path, files)
    with pytest.raises(PackValidationError) as exc:
        load_pack("t", packs_root=root)
    assert any("not in inventory" in e for e in exc.value.errors)


def test_errors_are_aggregated(tmp_path):
    """Multiple problems are reported together, not one-at-a-time."""
    files = _minimal_pack()
    files["npcs.json"][0]["home_location"] = "nowhere"          # bad place ref
    files["npcs.json"][0]["stat_block"] = "missing"             # bad statblock ref
    files["scenarios.json"][0]["start_location"] = "void"       # bad start ref
    root = _write_pack(tmp_path, files)
    with pytest.raises(PackValidationError) as exc:
        load_pack("t", packs_root=root)
    assert len(exc.value.errors) >= 3
