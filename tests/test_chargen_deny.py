"""Per-world SRD allow/deny lists (Forge v2.0): a world switches character
options off, and character creation honors it.

The rule is enforced at the chargen DOORS only — options never offer a denied
pick, preview/new reject a crafted one — and deliberately nowhere else:

* the session plays and replays on the FULL ruleset, so a save whose hero
  predates a deny keeps working forever;
* imported heroes are exempt (a carried hero predates the world's rules,
  exactly like an existing save);
* the Forge's own chargen (the author's NPC builder) stays unfiltered — an
  author may WANT a forbidden-class NPC (the world's last warlock).
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
from oubliette.content.loader import (PackValidationError, chargen_ruleset,  # noqa: E402
                                      load_pack)
from oubliette.content.ruleset import load_ruleset  # noqa: E402
from oubliette.content.schemas import ChargenDeny  # noqa: E402
from oubliette.record.store import InMemoryEventStore  # noqa: E402
from oubliette.rules.chargen import CharacterBuild  # noqa: E402
from oubliette.rules.chargen_view import chargen_options  # noqa: E402
from oubliette.runtime.session import Session  # noqa: E402

client = TestClient(app)
RS = load_ruleset()

DENY = {"classes": ["barbarian"], "races": ["tiefling"], "backgrounds": ["acolyte"]}

# The world ships its own background and hides the SRD's only one (acolyte) —
# the realistic shape of a themed world, and why the "leave at least one"
# lint counts pack-authored backgrounds.
DOCK_RAT = {
    "id": "dock_rat",
    "name": "Dock Rat",
    "skill_proficiencies": ["athletics", "insight"],
    "equipment": [],
    "starting_gold": 10,
    "feature": {"name": "Harbor Ties", "level": 1,
                "text": "Dockworkers across the bay treat you as one of their own."},
}

_PACK_FILES = {
    "pack.json": {"id": "t", "schema_version": 1, "name": "Test", "version": "1.0.0",
                  "entry_scenario": "s", "chargen_deny": DENY},
    "items.json": [],
    "statblocks.json": [],
    "npcs.json": [],
    "places.json": [{"id": "p", "name": "P", "description": "a place", "exits": []}],
    "scenarios.json": [{"id": "s", "name": "S", "start_location": "p"}],
    "backgrounds.json": [DOCK_RAT],
}


def _write_pack(root: Path, deny: dict | None = DENY) -> Path:
    d = root / "t"
    d.mkdir(parents=True, exist_ok=True)
    for name, content in _PACK_FILES.items():
        if name == "pack.json":
            content = dict(content)
            content.pop("chargen_deny", None)
            if deny is not None:
                content["chargen_deny"] = deny
        (d / name).write_text(json.dumps(content), encoding="utf-8")
    return root


def _build(char_class: str = "fighter", race: str = "human") -> dict:
    cc = RS.classes[char_class]
    return CharacterBuild(
        name="Brina", race=race, char_class=char_class,
        background="dock_rat", ability_method="standard_array",
        base_abilities={"str": 15, "dex": 14, "con": 13,
                        "int": 12, "wis": 10, "cha": 8},
        skills=["perception", "survival"],
        race_languages=["dwarvish"],       # Human: one free language of choice
        equipment_choices=[list(range(ch.choose))
                           for ch in cc.starting_equipment.choices],
    ).model_dump(mode="json")


@pytest.fixture
def temp_packs(tmp_path, monkeypatch):
    root = _write_pack(tmp_path)
    monkeypatch.setattr(loader, "_PACKS_ROOT", root)
    monkeypatch.setattr(server, "_PACKS_ROOT", root)
    server._WIZARD_WORLDS.clear()
    yield root
    server._WIZARD_WORLDS.clear()


# --- the pack door -----------------------------------------------------------

def test_manifest_parses_and_rides_the_loaded_world(temp_packs):
    world = load_pack("t")
    assert world.chargen_deny.classes == ["barbarian"]
    assert world.chargen_deny.races == ["tiefling"]


def test_a_typoed_deny_id_fails_at_the_pack_door(tmp_path, monkeypatch):
    root = _write_pack(tmp_path, deny={"classes": ["warlok"]})
    monkeypatch.setattr(loader, "_PACKS_ROOT", root)
    with pytest.raises(PackValidationError) as e:
        load_pack("t")
    assert "unknown class 'warlok'" in str(e.value)


def test_denying_every_race_fails_at_the_pack_door(tmp_path, monkeypatch):
    root = _write_pack(tmp_path, deny={"races": sorted(RS.races)})
    monkeypatch.setattr(loader, "_PACKS_ROOT", root)
    with pytest.raises(PackValidationError) as e:
        load_pack("t")
    assert "denies every race" in str(e.value)


# --- the filter ----------------------------------------------------------------

def test_filtered_ruleset_prunes_only_the_denied():
    rs = chargen_ruleset(RS, ChargenDeny(**DENY))
    assert "barbarian" not in rs.classes and "fighter" in rs.classes
    assert "tiefling" not in rs.races and "human" in rs.races
    assert "acolyte" not in rs.backgrounds
    opts = chargen_options(rs)
    assert "barbarian" not in {c["id"] for c in opts["classes"]}
    assert "tiefling" not in {r["id"] for r in opts["races"]}


def test_no_deny_returns_the_ruleset_untouched():
    assert chargen_ruleset(RS, None) is RS
    assert chargen_ruleset(RS, ChargenDeny()) is RS


# --- the play app's doors ------------------------------------------------------

def test_options_omit_the_denied(temp_packs):
    o = client.get("/api/chargen/options", params={"pack": "t"}).json()
    assert "barbarian" not in {c["id"] for c in o["classes"]}
    assert "tiefling" not in {r["id"] for r in o["races"]}
    assert "acolyte" not in {b["id"] for b in o["backgrounds"]}
    assert "fighter" in {c["id"] for c in o["classes"]}   # the rest still offered


def test_preview_rejects_a_denied_pick(temp_packs):
    r = client.post("/api/chargen/preview", params={"pack": "t"},
                    json=_build("barbarian")).json()
    assert r["ok"] is False
    assert any("barbarian" in e for e in r["errors"])


def test_new_game_rejects_a_denied_build_and_accepts_an_allowed_one(tmp_path):
    from oubliette.content.loader import DEFAULT_PACK
    root = _write_pack(tmp_path)
    real_root = loader._PACKS_ROOT
    loader._PACKS_ROOT = server._PACKS_ROOT = root
    server._WIZARD_WORLDS.clear()
    try:
        refused = client.post("/api/new",
                              json={"pack_id": "t", "builds": [_build("barbarian")]})
        assert refused.status_code == 400
        assert any("barbarian" in e for e in refused.json()["errors"])
        ok = client.post("/api/new",
                         json={"pack_id": "t", "builds": [_build("fighter")]}).json()
        assert ok["ok"] is True, ok.get("errors")
    finally:
        # Put the table back on the real default world (the temp root vanishes).
        loader._PACKS_ROOT = server._PACKS_ROOT = real_root
        server._WIZARD_WORLDS.clear()
        client.post("/api/new", json={"pack_id": DEFAULT_PACK})


# --- what the rule must NEVER touch ---------------------------------------------

def test_replay_keeps_a_grandfathered_hero(temp_packs):
    """A save whose hero predates the deny replays forever: the SESSION builds
    party members on the FULL ruleset — only the chargen doors filter."""
    s = Session.open(InMemoryEventStore(), pack_id="t")
    chars = s.emit_party_created([CharacterBuild(**{
        **{k: v for k, v in _build("barbarian").items()}})])
    assert chars[0].sheet.char_class == "barbarian"


def test_the_forges_own_chargen_stays_unfiltered(temp_packs, monkeypatch):
    """The author's NPC builder deliberately ignores the world's deny lists —
    an author may WANT a forbidden-class NPC (the world's last warlock)."""
    from oubliette.creator.server import app as forge_app
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(temp_packs))
    forge = TestClient(forge_app)
    o = forge.get("/api/chargen/options", params={"pack": "t"}).json()
    assert "barbarian" in {c["id"] for c in o["classes"]}
    assert "tiefling" in {r["id"] for r in o["races"]}
