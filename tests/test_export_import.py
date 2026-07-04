"""v0.9 portability: world zips and character bundles.

Worlds travel as one zip (export from the Forge; import in the Forge OR at the
game's Choose-a-World screen — the app door refuses invalid packs whole, the
Forge door installs them to fix). Heroes travel as a self-contained bundle
(snapshot + the item definitions their gear references + portrait) and join a
new campaign through the same CHARACTER_CREATED event chargen uses, so
save/replay needs nothing new.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from oubliette.content.loader import load_pack
from oubliette.content.packaging import (character_bundle, export_pack,
                                         import_pack, parse_character_bundle)
from oubliette.enums import Ability
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.session import Session
from oubliette.state.models import Character, CharacterSheet, Item, ItemStack

# --- a tiny valid world to ship around --------------------------------------

def _pack_files(pack_id: str = "t") -> dict:
    return {
        "pack.json": {"id": pack_id, "schema_version": 1, "name": "Test World",
                      "version": "1.0.0", "entry_scenario": "s"},
        "items.json": [{"id": "tide_knife", "name": "Tide Knife",
                        "category": "weapon", "weapon": {"damage": "1d4"}}],
        "places.json": [{"id": "p", "name": "P", "description": "a place", "exits": []}],
        "scenarios.json": [{"id": "s", "name": "S", "start_location": "p"}],
    }


def _write_pack(root: Path, files: dict, pack_id: str = "t") -> Path:
    d = root / pack_id
    d.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (d / name).write_text(json.dumps(content), encoding="utf-8")
    return root


def _with_asset(root: Path, pack_id: str = "t") -> Path:
    """Give the pack a binary asset so the zip proves subdirs travel."""
    d = root / pack_id / "images"
    d.mkdir(parents=True, exist_ok=True)
    (d / "map.png").write_bytes(b"\x89PNG-not-really")
    return root


# --- world zips ---------------------------------------------------------------

def test_export_import_round_trip(tmp_path):
    src = _with_asset(_write_pack(tmp_path / "src", _pack_files()))
    data = export_pack("t", packs_root=src)
    dest = tmp_path / "dest"
    dest.mkdir()
    result = import_pack(data, packs_root=dest)
    assert result["ok"] is True and result["id"] == "t"
    assert result["name"] == "Test World" and result["issues"] == []
    assert (dest / "t" / "images" / "map.png").read_bytes() == b"\x89PNG-not-really"
    world = load_pack("t", packs_root=dest)          # the game genuinely loads it
    assert world.pack_name == "Test World"


def test_a_hand_zipped_folder_imports_too(tmp_path):
    """Someone zips the pack FOLDER (a `t/` prefix on every member) — accept it."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in _pack_files().items():
            z.writestr(f"t/{name}", json.dumps(content))
    dest = tmp_path / "dest"
    dest.mkdir()
    result = import_pack(buf.getvalue(), packs_root=dest)
    assert result["ok"] is True
    assert (dest / "t" / "pack.json").is_file()


def test_zip_slip_is_refused_whole(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in _pack_files().items():
            z.writestr(name, json.dumps(content))
        z.writestr("../evil.txt", "escaped")
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(ValueError, match="suspicious path"):
        import_pack(buf.getvalue(), packs_root=dest)
    assert not (tmp_path / "evil.txt").exists()
    assert not (dest / "t").exists()                  # nothing half-installed


def test_not_a_zip_and_not_a_world_are_friendly_errors(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(ValueError, match="not a zip"):
        import_pack(b"hello", packs_root=dest)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "no manifest here")
    with pytest.raises(ValueError, match="no pack.json"):
        import_pack(buf.getvalue(), packs_root=dest)


def test_existing_world_needs_overwrite_and_is_shelved_first(tmp_path):
    src = _write_pack(tmp_path / "src", _pack_files())
    data = export_pack("t", packs_root=src)
    dest = tmp_path / "packs"
    dest.mkdir()
    assert import_pack(data, packs_root=dest)["ok"] is True
    (dest / "t" / "keepsake.txt").write_text("the old copy", encoding="utf-8")

    second = import_pack(data, packs_root=dest)
    assert second["ok"] is False and second["exists"] is True

    third = import_pack(data, packs_root=dest, overwrite=True)
    assert third["ok"] is True
    assert not (dest / "t" / "keepsake.txt").exists()   # fresh copy installed...
    shelf = list((tmp_path / "pack-backups" / "t").glob("import-*/keepsake.txt"))
    assert len(shelf) == 1                              # ...old copy shelved, not lost


def test_require_valid_rolls_back_a_broken_world(tmp_path):
    files = _pack_files()
    files["scenarios.json"] = []                        # entry_scenario now dangles
    src = _write_pack(tmp_path / "src", files)
    data = export_pack("t", packs_root=src)
    dest = tmp_path / "dest"
    dest.mkdir()
    result = import_pack(data, packs_root=dest, require_valid=True)
    assert result["ok"] is False and result["issues"]
    assert not (dest / "t").exists()                    # refused whole
    # ...but the Forge door installs it anyway, issues attached, to be fixed.
    lenient = import_pack(data, packs_root=dest)
    assert lenient["ok"] is True and lenient["issues"]
    assert (dest / "t" / "pack.json").is_file()


def test_require_valid_overwrite_restores_the_original(tmp_path):
    src = _write_pack(tmp_path / "src", _pack_files())
    good = export_pack("t", packs_root=src)
    files = _pack_files()
    files["scenarios.json"] = []
    broken = export_pack("t", packs_root=_write_pack(tmp_path / "src2", files))
    dest = tmp_path / "packs"
    dest.mkdir()
    assert import_pack(good, packs_root=dest)["ok"] is True
    result = import_pack(broken, packs_root=dest, overwrite=True, require_valid=True)
    assert result["ok"] is False
    world = load_pack("t", packs_root=dest)             # the good copy is back
    assert world.pack_name == "Test World"


# --- character bundles ----------------------------------------------------------

def _hero() -> Character:
    return Character(
        id="pc", name="Vex", kind="pc", level=3, hp=20, max_hp=24, gold=37,
        abilities={Ability.INT: 16, Ability.DEX: 12, Ability.CON: 14},
        armor_class=12, attack_bonus=4, damage="1d4+1", xp=900,
        inventory=[ItemStack(item_id="tide_knife", qty=1)],
        equipped=["tide_knife"], portrait="pc.png",
        sheet=CharacterSheet(
            race="gnome", char_class="wizard", background="acolyte",
            spellcasting_ability=Ability.INT, cantrips_known=["fire_bolt"],
            spells_known=["magic_missile", "shield"]))


def _knife() -> Item:
    return Item(id="tide_knife", name="Tide Knife", category="weapon", damage="1d4")


def test_character_bundle_round_trips():
    bundle = character_bundle(_hero(), [_knife()], ("image/png", b"portrait-bytes"))
    char, items, portrait = parse_character_bundle(json.loads(json.dumps(bundle)))
    assert char.name == "Vex" and char.level == 3 and char.gold == 37
    assert char.sheet.spells_known == ["magic_missile", "shield"]
    assert char.kind == "pc"
    assert char.portrait is None            # the importer re-establishes the portrait
    assert [i.id for i in items] == ["tide_knife"]
    assert portrait == ("image/png", b"portrait-bytes")


def test_a_bare_character_json_imports_too():
    """A Forge person-NPC sidecar (a bare Character) is welcome as an import."""
    raw = _hero().model_dump(mode="json")
    raw["kind"] = "npc"
    char, items, portrait = parse_character_bundle(raw)
    assert char.kind == "pc" and items == [] and portrait is None


def test_junk_is_refused_kindly():
    with pytest.raises(ValueError, match="not a character"):
        parse_character_bundle("just text")
    with pytest.raises(ValueError, match="doesn't read as one"):
        parse_character_bundle({"character": {"nonsense": True}})
    with pytest.raises(ValueError, match="different kind of export"):
        parse_character_bundle({"format": "oubliette-world", "character": {}})


def test_a_broken_portrait_never_blocks_the_hero():
    bundle = character_bundle(_hero(), [], ("image/png", b"x"))
    bundle["portrait"]["data"] = "%%% not base64 %%%"
    char, _items, portrait = parse_character_bundle(bundle)
    assert char.name == "Vex" and portrait is None


# --- imported heroes join the party and survive replay ---------------------------

def test_imported_hero_joins_the_party_and_replays(tmp_path):
    store = InMemoryEventStore()
    live = Session.open(store)
    chars = live.emit_party_created([], imports=[(_hero(), [_knife()])])
    assert [c.id for c in chars] == ["pc"]              # import-only party: he leads
    pc = live.repo.pc()
    assert pc.name == "Vex" and pc.level == 3
    assert live.repo.get_item("tide_knife").name == "Tide Knife"   # his gear came along

    reloaded = Session.open(store)                      # fresh replay of the log
    assert reloaded.repo.pc().name == "Vex"
    assert reloaded.repo.get_item("tide_knife").damage == "1d4"


def test_imported_hero_after_built_heroes_continues_the_ids():
    from oubliette.rules.chargen import CharacterBuild
    live = Session.open(InMemoryEventStore())
    fighter = live.ruleset.classes["fighter"]
    build = CharacterBuild(
        name="Brina", race="human", char_class="fighter", background="acolyte",
        ability_method="standard_array",
        base_abilities={"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8},
        skills=["perception", "survival"], race_languages=["dwarvish"],
        languages=["elvish", "draconic"],
        equipment_choices=[list(range(ch.choose))
                           for ch in fighter.starting_equipment.choices])
    chars = live.emit_party_created([build], imports=[(_hero(), [_knife()])])
    assert [c.id for c in chars] == ["pc", "pc2"]
    assert chars[1].name == "Vex"
    # gold pooled onto the lead (shared party purse); the import's 37 gp came along
    assert chars[1].gold == 0 and chars[0].gold >= 37


# --- the HTTP surfaces --------------------------------------------------------

def test_app_new_game_import_then_export_round_trip():
    """The whole player journey: import a hero at New Game (portrait and all),
    then export them back off the sheet."""
    import os
    import tempfile
    os.environ.setdefault("OUBLIETTE_DB", os.path.join(tempfile.mkdtemp(), "exp-test.sqlite"))
    from fastapi.testclient import TestClient
    from oubliette.app import server as appserver
    client = TestClient(appserver.app)
    bundle = character_bundle(_hero(), [_knife()], ("image/png", b"png-bytes"))

    chk = client.post("/api/import-character/check",
                      json={"pack_id": "brightvale", "bundle": bundle}).json()
    assert chk["ok"] is True
    assert chk["summary"]["name"] == "Vex" and chk["summary"]["has_portrait"]

    res = client.post("/api/new",
                      json={"pack_id": "brightvale", "imports": [bundle]}).json()
    assert res["ok"] is True

    out = client.get("/api/character-export/pc")
    assert out.status_code == 200
    assert "attachment" in out.headers["content-disposition"]
    again, items, portrait = parse_character_bundle(out.json())
    assert again.name == "Vex" and again.level == 3
    assert any(i.id == "tide_knife" for i in items)
    assert portrait == ("image/png", b"png-bytes")      # survived the whole loop


def test_app_new_game_refuses_a_bad_import_without_erasing():
    import os
    import tempfile
    os.environ.setdefault("OUBLIETTE_DB", os.path.join(tempfile.mkdtemp(), "exp-test.sqlite"))
    from fastapi.testclient import TestClient
    from oubliette.app import server as appserver
    client = TestClient(appserver.app)
    res = client.post("/api/new", json={"pack_id": "brightvale",
                                        "imports": [{"character": {"junk": 1}}]})
    assert res.status_code == 400
    assert "imported hero #1" in res.json()["errors"][0]


def test_forge_export_import_endpoints(tmp_path, monkeypatch):
    _write_pack(tmp_path, _pack_files())
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(tmp_path))
    from fastapi.testclient import TestClient
    from oubliette.creator.server import app
    client = TestClient(app)

    out = client.get("/api/pack/t/export")
    assert out.status_code == 200
    assert out.headers["content-type"] == "application/zip"

    import shutil
    shutil.rmtree(tmp_path / "t")
    res = client.post("/api/pack/import", content=out.content).json()
    assert res["ok"] is True and res["id"] == "t"
    assert res["validation"]["ok"] is True

    res2 = client.post("/api/pack/import", content=out.content).json()
    assert res2["ok"] is False and res2["exists"] is True
    res3 = client.post("/api/pack/import", params={"overwrite": "true"},
                       content=out.content).json()
    assert res3["ok"] is True
