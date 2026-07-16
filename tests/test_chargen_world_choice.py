"""New Game chargen builds FOR a world that isn't loaded yet.

The wizard chooses a world in step 1, but the chosen world only loads at
POST /api/new — so the options, the live preview, and the final validation
must all run against the CHOSEN world's pack-merged ruleset (via `?pack=`,
the same contract the Forge's chargen endpoints already honor), not against
whichever world the session still has open. The old behavior offered the
previous world's backgrounds and spells until a New Game had loaded the
chosen world once ("start the game twice" workaround).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# Must be set BEFORE importing the server (it builds the game at import time).
os.environ.setdefault("OUBLIETTE_DB", os.path.join(tempfile.mkdtemp(), "test.sqlite"))
os.environ.setdefault("OUBLIETTE_CONFIG", os.path.join(tempfile.mkdtemp(), "cfg.json"))
os.environ.pop("ANTHROPIC_API_KEY", None)  # force the scripted client

from fastapi.testclient import TestClient  # noqa: E402

import oubliette.app.server as server  # noqa: E402
import oubliette.content.loader as loader  # noqa: E402
from oubliette.app.server import app  # noqa: E402
from oubliette.content.loader import DEFAULT_PACK  # noqa: E402
from oubliette.content.ruleset import load_ruleset  # noqa: E402
from oubliette.rules.chargen import CharacterBuild  # noqa: E402

client = TestClient(app)
RS = load_ruleset()

# A world ("t") whose ONLY difference from the SRD is its own background that
# grants its own item — exactly what the session's ruleset can't know about.
DOCKHAND = {
    "id": "silverfin_dockhand",
    "name": "Silverfin Dockhand",
    "skill_proficiencies": ["athletics", "insight"],
    "equipment": [{"item": "sword", "qty": 1}],
    "starting_gold": 10,
    "feature": {"name": "Dock Rat", "level": 1,
                "text": "Dockworkers across the bay treat you as one of their own."},
}

_PACK_FILES = {
    "pack.json": {"id": "t", "schema_version": 1, "name": "Test", "version": "1.0.0",
                  "entry_scenario": "s"},
    "items.json": [{"id": "sword", "name": "Dockhand's Sword", "category": "weapon",
                    "base_value": 5}],
    "statblocks.json": [],
    "npcs.json": [],
    "places.json": [{"id": "p", "name": "P", "description": "a place", "exits": []}],
    "scenarios.json": [{"id": "s", "name": "S", "start_location": "p"}],
    "backgrounds.json": [DOCKHAND],
}


def _write_pack(root: Path) -> Path:
    d = root / "t"
    d.mkdir(parents=True, exist_ok=True)
    for name, content in _PACK_FILES.items():
        (d / name).write_text(json.dumps(content), encoding="utf-8")
    return root


def _dockhand_build() -> dict:
    fighter = RS.classes["fighter"]
    return CharacterBuild(
        name="Brina", race="human", char_class="fighter",
        background="silverfin_dockhand", ability_method="standard_array",
        base_abilities={"str": 15, "dex": 14, "con": 13,
                        "int": 12, "wis": 10, "cha": 8},
        skills=["perception", "survival"],
        race_languages=["dwarvish"],       # Human: one free language of choice
        equipment_choices=[list(range(ch.choose))
                           for ch in fighter.starting_equipment.choices],
    ).model_dump(mode="json")


@pytest.fixture
def temp_packs(tmp_path, monkeypatch):
    """Point the play server's pack loading at a temp root holding world 't'.
    The live session (opened on the real default pack at import) is untouched —
    which is the point: 't' is a world the session has never loaded."""
    root = _write_pack(tmp_path)
    monkeypatch.setattr(loader, "_PACKS_ROOT", root)
    monkeypatch.setattr(server, "_PACKS_ROOT", root)
    server._WIZARD_WORLDS.clear()
    yield root
    server._WIZARD_WORLDS.clear()


def test_options_serve_the_chosen_world(temp_packs):
    plain = client.get("/api/chargen/options").json()
    assert "silverfin_dockhand" not in {b["id"] for b in plain["backgrounds"]}
    chosen = client.get("/api/chargen/options", params={"pack": "t"}).json()
    ids = {b["id"] for b in chosen["backgrounds"]}
    assert {"silverfin_dockhand", "acolyte"} <= ids     # pack joined, SRD rides along


def test_options_refuse_a_world_that_wont_load(temp_packs):
    r = client.get("/api/chargen/options", params={"pack": "nope"})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_preview_judges_by_the_chosen_world(temp_packs):
    build = _dockhand_build()
    refused = client.post("/api/chargen/preview", json=build).json()
    assert refused["ok"] is False          # the loaded world knows no dockhand
    ok = client.post("/api/chargen/preview", params={"pack": "t"}, json=build).json()
    assert ok["ok"] is True, ok.get("errors")


def test_new_game_validates_builds_against_the_target_world(tmp_path):
    root = _write_pack(tmp_path)
    real_root = loader._PACKS_ROOT
    loader._PACKS_ROOT = server._PACKS_ROOT = root
    server._WIZARD_WORLDS.clear()
    try:
        d = client.post("/api/new",
                        json={"pack_id": "t", "builds": [_dockhand_build()]}).json()
        assert d["ok"] is True, d.get("errors")
        assert d["pack_id"] == "t"
        # The background's PACK item materialized on the new hero.
        assert any(i["id"] == "sword" for i in d["state"]["pc"]["inventory"])
    finally:
        # Put the table back on the real default world so later modules'
        # /api/new (which keeps the current pack) doesn't reopen 't' from a
        # temp dir that no longer resolves.
        loader._PACKS_ROOT = server._PACKS_ROOT = real_root
        server._WIZARD_WORLDS.clear()
        client.post("/api/new", json={"pack_id": DEFAULT_PACK})
