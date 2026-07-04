"""The Forge — C1 (open & check). In-process tests via FastAPI's TestClient.

Pins the C1 contract: list worlds, open one read-only, and report validity using
the GAME's loader — so The Forge's ✓/⚠ and the game's load agree by construction.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from oubliette.creator.server import app, _DEFAULT_PACKS_ROOT

client = TestClient(app)


def _temp_brightvale(tmp_path, monkeypatch) -> Path:
    """Copy the real Brightvale pack into a temp packs root and point The Forge at
    it — so save/edit tests NEVER touch the committed pack."""
    packs = tmp_path / "packs"
    packs.mkdir()
    shutil.copytree(_DEFAULT_PACKS_ROOT / "brightvale", packs / "brightvale")
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(packs))
    return packs


def test_lists_brightvale_as_ready():
    r = client.get("/api/packs")
    assert r.status_code == 200
    packs = {p["id"]: p for p in r.json()["packs"]}
    assert "brightvale" in packs
    bv = packs["brightvale"]
    assert bv["ok"] is True and bv["issue_count"] == 0
    assert bv["name"] == "The Brightvale Market"


def test_open_pack_returns_contents_and_validation():
    r = client.get("/api/pack/brightvale")
    assert r.status_code == 200
    data = r.json()
    assert data["validation"]["ok"] is True
    # the five world pieces are present and readable
    c = data["contents"]
    assert any(it["id"] == "merchant_thom" for it in c["npcs"])
    assert any(it["id"] == "boots" for it in c["items"])
    assert c["pack"]["name"] == "The Brightvale Market"


def test_unknown_pack_is_404():
    assert client.get("/api/pack/does_not_exist").status_code == 404


def test_chargen_options_from_shared_ruleset():
    """Phase 4b: the Forge serves the person-NPC builder's options from the SAME
    rules.chargen_view projection the play app's wizard uses — one source of truth,
    so the two can't drift."""
    from oubliette.content.ruleset import load_ruleset
    from oubliette.rules.chargen_view import chargen_options

    r = client.get("/api/chargen/options")
    assert r.status_code == 200
    data = r.json()
    for key in ("classes", "races", "backgrounds", "spells_by_class",
                "abilities", "skills", "standard_array", "point_buy"):
        assert key in data
    assert any(c["id"] == "fighter" for c in data["classes"])
    assert any(c["id"] == "wizard" for c in data["classes"])
    assert data["standard_array"] == [15, 14, 13, 12, 10, 8]
    # byte-identical to the shared projection (JSON round-trip normalises int keys
    # like point_buy.cost, which JSON renders as strings)
    assert data == json.loads(json.dumps(chargen_options(load_ruleset())))


def test_chargen_preview_and_build():
    """Phase 4b-2: /preview derives a sheet from a valid build; /build returns the
    full Character snapshot a person-NPC stores."""
    from tests.test_chargen import _fighter

    build = _fighter().model_dump(mode="json")

    pv = client.post("/api/chargen/preview", json=build).json()
    assert pv["ok"] is True
    assert pv["preview"]["max_hp"] == 12                       # d10 + CON 2
    assert pv["preview"]["derived"]["armor_class"] == 18       # chain mail + shield

    bd = client.post("/api/chargen/build", json=build).json()
    assert bd["ok"] is True
    char = bd["character"]
    assert char["kind"] == "pc" and char["level"] == 1
    assert char["sheet"]["char_class"] == "fighter"
    assert char["max_hp"] == 12 and char["armor_class"] == 18


def test_chargen_preview_rejects_invalid_build():
    """The chargen firewall still bites through the Forge endpoint."""
    from tests.test_chargen import _fighter

    bad = _fighter(skills=[]).model_dump(mode="json")          # fighter must choose 2 skills
    r = client.post("/api/chargen/preview", json=bad).json()
    assert r["ok"] is False and r["errors"]


def test_chargen_levelup_builds_a_higher_level_npc():
    """Phase 4b-2: from a level-1 build (xp=0), the Forge levels the character to 3
    — authoring grants the XP so it isn't gated by a grind. HP grows each level."""
    from tests.test_chargen import _fighter

    char = client.post("/api/chargen/build", json=_fighter().model_dump(mode="json")).json()["character"]

    for target in (2, 3):
        plan = client.post("/api/chargen/levelup/plan", json=char).json()
        assert plan["can_level"] is True and plan["next_level"] == target   # not gated by xp=0
        choice = {"hp_method": "average"}
        if plan.get("needs_subclass"):                          # fighter picks an archetype at 3
            choice["subclass"] = plan["subclass_options"][0]["id"]
        out = client.post("/api/chargen/levelup",
                          json={"character": char, "choice": choice}).json()
        assert out["ok"] is True, out
        char = out["character"]
        assert char["level"] == target
    assert char["sheet"]["subclass"]                            # the archetype stuck
    assert char["max_hp"] > 12                                  # leveled HP > level-1 HP


def test_person_npc_roundtrip_build_save_load(tmp_path, monkeypatch):
    """Phase 4b-3: build a character, save it as a person-NPC's sidecar, add the NPC,
    and confirm load_pack produces a runtime Character with the chargen combat stats
    + the NPC's authored identity/flavor — the whole person-NPC loop end to end."""
    from oubliette.content.loader import load_pack
    from tests.test_chargen import _fighter

    packs = _temp_brightvale(tmp_path, monkeypatch)             # temp copy; never the committed pack

    char = client.post("/api/chargen/build",
                       json=_fighter().model_dump(mode="json")).json()["character"]

    # save the snapshot, then confirm the pack read badges the built person-NPC
    assert client.put("/api/pack/brightvale/character/capt_aldric",
                      json={"character": char}).json()["ok"] is True
    assert "capt_aldric" in client.get("/api/pack/brightvale").json()["character_files"]

    # add the person NPC to npcs.json on disk and load the pack for real
    npcs_path = packs / "brightvale" / "npcs.json"
    data = json.loads(npcs_path.read_text(encoding="utf-8"))
    data.append({"id": "capt_aldric", "name": "Captain Aldric", "combat_kind": "person",
                 "disposition": "stern but fair", "home_location": "brightvale_market"})
    npcs_path.write_text(json.dumps(data), encoding="utf-8")

    world = load_pack("brightvale", packs_root=packs)
    aldric = next(c for c in world.repository.npcs() if c.id == "capt_aldric")
    assert aldric.kind == "npc"
    assert aldric.name == "Captain Aldric"                      # NPC identity wins
    assert aldric.disposition == "stern but fair"              # flavor overlay
    assert aldric.max_hp == 12 and aldric.armor_class == 18    # chargen combat stats survive
    assert aldric.sheet is not None and aldric.sheet.char_class == "fighter"


def test_chargen_sheet_renders_a_built_character():
    """Phase 4b-4c: a stored Character renders to the same derived sheet the build
    preview shows, so a person-NPC can be reviewed without rebuilding."""
    from tests.test_chargen import _fighter

    char = client.post("/api/chargen/build", json=_fighter().model_dump(mode="json")).json()["character"]
    r = client.post("/api/chargen/sheet", json=char).json()
    assert r["ok"] is True
    assert r["preview"]["max_hp"] == 12
    assert r["preview"]["derived"]["armor_class"] == 18
    assert any(f["name"] == "Second Wind" for f in r["preview"]["features"])


def test_save_person_character_rejects_invalid(tmp_path, monkeypatch):
    """The sidecar save validates against the engine Character model — a broken
    snapshot can't be written (it would hard-fail the pack at load)."""
    _temp_brightvale(tmp_path, monkeypatch)
    r = client.put("/api/pack/brightvale/character/whoever",
                   json={"character": {"id": "x", "armor_class": "not a number"}})
    assert r.status_code == 400 and "invalid character" in r.json()["error"]


def test_path_traversal_is_refused():
    # an id that tries to climb out of the packs root must not resolve
    assert client.get("/api/pack/..").status_code == 404


def test_broken_pack_reports_issues(tmp_path, monkeypatch):
    """Point The Forge at a temp packs root holding a deliberately broken world;
    the validity report must surface the loader's aggregated issues."""
    d = tmp_path / "broken"
    d.mkdir()
    (d / "pack.json").write_text(json.dumps({
        "id": "broken", "schema_version": 1, "name": "Broken World",
        "version": "0.1.0", "entry_scenario": "missing"}), encoding="utf-8")
    (d / "npcs.json").write_text(json.dumps([
        {"id": "n", "name": "N", "home_location": "nowhere"}]), encoding="utf-8")
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(tmp_path))

    listing = {p["id"]: p for p in client.get("/api/packs").json()["packs"]}
    assert listing["broken"]["ok"] is False
    assert listing["broken"]["issue_count"] >= 1

    report = client.get("/api/pack/broken").json()["validation"]
    assert report["ok"] is False
    assert any("nowhere" in i for i in report["issues"])


# --- C2: editing, saving, backups ------------------------------------------
def test_save_writes_changes_and_backs_up(tmp_path, monkeypatch):
    packs = _temp_brightvale(tmp_path, monkeypatch)

    contents = client.get("/api/pack/brightvale").json()["contents"]
    contents["items"].append({"id": "lantern", "name": "brass lantern",
                              "category": "gear", "base_value": 5})
    r = client.post("/api/pack/brightvale/save", json={"contents": contents})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["validation"]["ok"] is True

    # the change is on disk, still valid for the game to load
    written = json.loads((packs / "brightvale" / "items.json").read_text(encoding="utf-8"))
    assert any(it["id"] == "lantern" for it in written)

    # a timestamped backup of the PREVIOUS version exists, WITHOUT the new item
    backups = list((tmp_path / "pack-backups" / "brightvale").iterdir())
    assert len(backups) == 1
    prior = json.loads((backups[0] / "items.json").read_text(encoding="utf-8"))
    assert not any(it["id"] == "lantern" for it in prior)


def test_save_persists_the_bestiary_gate_and_the_loader_reads_it(tmp_path, monkeypatch):
    """The world-settings panel writes the knowledge gate into pack.json; the game's
    own loader must read it back — so The Forge and the game agree by construction."""
    packs = _temp_brightvale(tmp_path, monkeypatch)

    contents = client.get("/api/pack/brightvale").json()["contents"]
    contents["pack"]["bestiary_gate"] = {"enabled": True, "max_known_cr": 0.25}
    r = client.post("/api/pack/brightvale/save", json={"contents": contents})
    assert r.status_code == 200 and r.json()["validation"]["ok"] is True

    written = json.loads((packs / "brightvale" / "pack.json").read_text(encoding="utf-8"))
    assert written["bestiary_gate"] == {"enabled": True, "max_known_cr": 0.25}

    from oubliette.content.loader import load_pack
    world = load_pack("brightvale", packs_root=packs)
    assert world.bestiary_gate.enabled is True
    assert world.bestiary_gate.max_known_cr == 0.25


def test_save_allows_work_in_progress_with_issues(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    contents = client.get("/api/pack/brightvale").json()["contents"]
    # add a place whose exit points nowhere — a real world wouldn't load, but the
    # author should still be able to save the half-finished work
    contents["places"].append({"id": "void", "name": "The Void", "description": "...",
                               "exits": [{"to": "nowhere"}]})
    r = client.post("/api/pack/brightvale/save", json={"contents": contents})
    assert r.json()["ok"] is True                       # save succeeded
    assert r.json()["validation"]["ok"] is False        # but it's flagged not-yet-playable


def test_saved_files_are_pretty_and_newline_terminated(tmp_path, monkeypatch):
    packs = _temp_brightvale(tmp_path, monkeypatch)
    contents = client.get("/api/pack/brightvale").json()["contents"]
    client.post("/api/pack/brightvale/save", json={"contents": contents})
    text = (packs / "brightvale" / "items.json").read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "\n  " in text                                # indented (pretty-printed)


def test_save_unknown_pack_is_404(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    r = client.post("/api/pack/ghost/save", json={"contents": {}})
    assert r.status_code == 404


# --- illustrations ----------------------------------------------------------
_TINY_PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChw"
             "GA60e6kgAAAABJRU5ErkJggg==")


def test_upload_then_serve_pack_image(tmp_path, monkeypatch):
    packs = _temp_brightvale(tmp_path, monkeypatch)
    r = client.post("/api/pack/brightvale/image",
                    json={"filename": "brightvale.jpg", "data": "data:image/png;base64," + _TINY_PNG})
    assert r.status_code == 200 and r.json()["filename"] == "brightvale.jpg"
    assert (packs / "brightvale" / "images" / "brightvale.jpg").is_file()

    got = client.get("/api/pack/brightvale/image/brightvale.jpg")
    assert got.status_code == 200
    assert got.content[:8] == b"\x89PNG\r\n\x1a\n"          # the bytes we stored


def test_upload_rejects_unsafe_filename(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    r = client.post("/api/pack/brightvale/image", json={"filename": "../evil.jpg", "data": _TINY_PNG})
    assert r.status_code == 400


def test_upload_rejects_bad_data(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    r = client.post("/api/pack/brightvale/image", json={"filename": "ok.jpg", "data": "not-base64!!!"})
    assert r.status_code == 400


def test_missing_pack_image_is_404(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    assert client.get("/api/pack/brightvale/image/nope.jpg").status_code == 404


# --- C3: creatures, NPCs (stock + prices), opening setup --------------------
def test_save_new_creature_and_merchant_stays_valid(tmp_path, monkeypatch):
    """Mimic the C3 editors' output (new creature + new shopkeeper wired by the
    pickers) and confirm the world still loads for the game."""
    packs = _temp_brightvale(tmp_path, monkeypatch)
    c = client.get("/api/pack/brightvale").json()["contents"]

    c["statblocks"].append({
        "id": "market_cat", "name": "market cat", "kind": "monster",
        "abilities": {"str": 6, "dex": 15, "con": 10, "int": 3, "wis": 12, "cha": 7},
        "hp": 3, "armor_class": 12, "attack_bonus": 4, "damage": "1d4", "xp": 10,
    })
    # a second merchant: home + stat block chosen from existing things; one item
    # in stock, priced (boots already exist in the pack)
    c["npcs"].append({
        "id": "grocer_mae", "name": "Mae", "stat_block": "commoner",
        "home_location": "brightvale_market", "role": "grocer", "gold": 40,
        "disposition": "warm but no pushover",
        "inventory": [{"item": "boots"}], "price_list": {"boots": 3},
    })
    r = client.post("/api/pack/brightvale/save", json={"contents": c})
    assert r.json()["validation"]["ok"] is True

    written = json.loads((packs / "brightvale" / "npcs.json").read_text(encoding="utf-8"))
    assert any(n["id"] == "grocer_mae" for n in written)


def test_pricing_unstocked_item_is_flagged(tmp_path, monkeypatch):
    """The UI folds price into the stock row so this can't happen by hand — but the
    loader is the real guarantee, so prove an unstocked price is still caught."""
    _temp_brightvale(tmp_path, monkeypatch)
    c = client.get("/api/pack/brightvale").json()["contents"]
    c["npcs"].append({
        "id": "bad_merchant", "name": "Sly", "inventory": [],
        "price_list": {"boots": 5},          # priced but not stocked
    })
    r = client.post("/api/pack/brightvale/save", json={"contents": c})
    assert r.json()["ok"] is True                              # WIP save still allowed
    assert r.json()["validation"]["ok"] is False
    assert any("not in inventory" in i for i in r.json()["validation"]["issues"])


def test_scenario_edit_preserves_party(tmp_path, monkeypatch):
    """Editing the opening setup (start/scene) must not drop the starter party —
    the editor merges onto the original, so the chargen-stopgap party survives."""
    _temp_brightvale(tmp_path, monkeypatch)
    c = client.get("/api/pack/brightvale").json()["contents"]
    sc = c["scenarios"][0]
    sc["scene_override"] = "Dawn light slants across the market."
    client.post("/api/pack/brightvale/save", json={"contents": c})

    reread = client.get("/api/pack/brightvale").json()["contents"]["scenarios"][0]
    assert reread["scene_override"] == "Dawn light slants across the market."
    assert len(reread["default_party"]) == 1
    assert reread["default_party"][0]["name"] == "You"


# --- C4: new-world scaffold, friendly errors --------------------------------
def test_new_world_scaffolds_a_ready_pack(tmp_path, monkeypatch):
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(tmp_path / "packs"))
    r = client.post("/api/pack/new", json={"name": "Test Realm"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "test_realm"
    assert body["validation"]["ok"] is True            # a fresh world already loads

    contents = client.get("/api/pack/test_realm").json()["contents"]
    assert contents["pack"]["name"] == "Test Realm"
    assert any(p["id"] == "town_square" for p in contents["places"])
    assert contents["scenarios"][0]["start_location"] == "town_square"


def test_new_world_duplicate_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(tmp_path / "packs"))
    assert client.post("/api/pack/new", json={"name": "Twice"}).status_code == 200
    assert client.post("/api/pack/new", json={"name": "Twice"}).status_code == 409


# --- authored quests --------------------------------------------------------
def test_save_authored_quest_chain_stays_valid(tmp_path, monkeypatch):
    """Author a branching quest chain (the Forge quest editor's output) and confirm the
    world still loads — a giver-NPC root that forks to a place-given follow-up."""
    packs = _temp_brightvale(tmp_path, monkeypatch)
    c = client.get("/api/pack/brightvale").json()["contents"]
    assert c["quests"] in ([], None)                       # a pack with no quests yet
    c["quests"] = [
        {"id": "missing_cargo", "title": "The Missing Cargo", "hook": "find Thom's shipment",
         "rumor": "traders mutter about vanishing crates", "briefing": "the porter took it",
         "giver_npc": "merchant_thom", "root": True,
         "reward": {"gold": 25, "note": "and Thom's goodwill"},
         "branches": [{"outcome": "recovered", "to": "the_porter"}]},
        {"id": "the_porter", "title": "The Guilty Porter", "hook": "confront the porter",
         "giver_place": "brightvale_market", "discovery": "a notice nailed to a post"},
    ]
    r = client.post("/api/pack/brightvale/save", json={"contents": c})
    assert r.status_code == 200 and r.json()["validation"]["ok"] is True

    written = json.loads((packs / "brightvale" / "quests.json").read_text(encoding="utf-8"))
    assert {q["id"] for q in written} == {"missing_cargo", "the_porter"}

    # the game's own loader accepts it (Forge ✓ == game loads, by construction)
    from oubliette.content.loader import load_pack
    world = load_pack("brightvale", packs_root=packs)
    assert {q.id for q in world.quests} == {"missing_cargo", "the_porter"}


def test_quest_friendly_error_for_dangling_branch(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    c = client.get("/api/pack/brightvale").json()["contents"]
    c["quests"] = [{"id": "q1", "title": "Lonely Lead", "giver_npc": "merchant_thom",
                    "root": True, "branches": [{"outcome": "done", "to": "ghost_quest"}]}]
    r = client.post("/api/pack/brightvale/save", json={"contents": c})
    v = r.json()["validation"]
    assert v["ok"] is False
    assert any("ghost_quest" in i for i in v["issues"])
    friendly = [f for f in v["friendly"] if "ghost_quest" in f["message"]]
    assert friendly and friendly[0]["section"] == "quests"


def test_new_world_scaffolds_an_empty_quests_section(tmp_path, monkeypatch):
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(tmp_path / "packs"))
    client.post("/api/pack/new", json={"name": "Quest Realm"})
    contents = client.get("/api/pack/quest_realm").json()["contents"]
    assert contents["quests"] == []


def test_friendly_errors_are_plain_with_suggestions(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    c = client.get("/api/pack/brightvale").json()["contents"]
    # a character carrying a mistyped item id close to a real one ('sturdy belt')
    c["npcs"].append({"id": "x", "name": "Wanderer", "inventory": [{"item": "belt"}]})
    r = client.post("/api/pack/brightvale/save", json={"contents": c})
    v = r.json()["validation"]
    assert v["ok"] is False
    # raw issues stay available (the guarantee); friendly rephrases with a section
    assert any("belt" in i for i in v["issues"])
    belt = [f for f in v["friendly"] if "belt" in f["message"]]
    assert belt and belt[0]["section"] == "npcs"
    assert any("Did you mean" in f["message"] and "sturdy belt" in f["message"] for f in v["friendly"])


# --- AI personalities (Forge Phase 2b storage layer) --------------------

def test_ai_profiles_persist_and_the_loader_reads_them(tmp_path, monkeypatch):
    """An authored personality saves into the pack and the GAME's loader reads
    it back — so the Forge and the game agree by construction."""
    packs = _temp_brightvale(tmp_path, monkeypatch)
    contents = client.get("/api/pack/brightvale").json()["contents"]
    # Brightvale has no ai_profiles.json yet, so it loads as None — back-compat.
    assert contents.get("ai_profiles") in (None, [])
    contents["ai_profiles"] = [{
        "id": "cowardly_goblin", "name": "Cowardly Goblin",
        "aggression": 0.5, "self_preservation": 1.5,
        "will_flee": True, "retreat_threshold": 0.5, "prefers_melee": True,
    }]
    r = client.post("/api/pack/brightvale/save", json={"contents": contents})
    assert r.status_code == 200 and r.json()["validation"]["ok"] is True

    from oubliette.content.loader import load_pack
    world = load_pack("brightvale", packs_root=packs)
    names = {p.id: p for p in world.ai_profiles}
    assert "cowardly_goblin" in names
    assert names["cowardly_goblin"].will_flee is True


def test_new_world_scaffolds_an_empty_ai_profiles_section(tmp_path, monkeypatch):
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(tmp_path / "packs"))
    client.post("/api/pack/new", json={"name": "Personality Realm"})
    contents = client.get("/api/pack/personality_realm").json()["contents"]
    assert contents["ai_profiles"] == []


def test_out_of_range_ai_profile_value_is_rejected(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    contents = client.get("/api/pack/brightvale").json()["contents"]
    contents["ai_profiles"] = [{
        "id": "broken", "name": "Broken", "aggression": 9.0,  # > 2.0 ceiling
    }]
    r = client.post("/api/pack/brightvale/save", json={"contents": contents})
    assert r.json()["validation"]["ok"] is False


def test_duplicate_ai_profile_ids_are_rejected(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    contents = client.get("/api/pack/brightvale").json()["contents"]
    contents["ai_profiles"] = [
        {"id": "dup", "name": "One"},
        {"id": "dup", "name": "Two"},
    ]
    r = client.post("/api/pack/brightvale/save", json={"contents": contents})
    v = r.json()["validation"]
    assert v["ok"] is False
    assert any("dup" in i for i in v["issues"])


# --- creature portraits (Phase 3a) ------------------------------------------
# A tiny valid 1x1 PNG (raw bytes), used to exercise the portrait upload path.
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001 0d0a2db40000000049454e44ae426082".replace(" ", "")
)


def test_portrait_upload_stores_and_serves(tmp_path, monkeypatch):
    packs = _temp_brightvale(tmp_path, monkeypatch)
    r = client.post("/api/pack/brightvale/portrait/lean_wolf",
                    content=_PNG_1x1, headers={"Content-Type": "image/png"})
    assert r.status_code == 200 and r.json() == {"ok": True, "filename": "lean_wolf.png"}
    # written into the pack's portraits/ dir, where the game + Arena read it
    assert (packs / "brightvale" / "portraits" / "lean_wolf.png").read_bytes() == _PNG_1x1
    # and served back for the editor's preview
    g = client.get("/api/pack/brightvale/portrait/lean_wolf.png")
    assert g.status_code == 200 and g.content == _PNG_1x1


def test_portrait_upload_replaces_prior_extension(tmp_path, monkeypatch):
    packs = _temp_brightvale(tmp_path, monkeypatch)
    client.post("/api/pack/brightvale/portrait/lean_wolf",
                content=_PNG_1x1, headers={"Content-Type": "image/png"})
    # re-upload as a different format → the old-extension file is dropped
    r = client.post("/api/pack/brightvale/portrait/lean_wolf",
                    content=_PNG_1x1, headers={"Content-Type": "image/jpeg"})
    assert r.json()["filename"] == "lean_wolf.jpg"
    pdir = packs / "brightvale" / "portraits"
    assert not (pdir / "lean_wolf.png").exists()
    assert (pdir / "lean_wolf.jpg").exists()


def test_portrait_upload_rejects_unsupported_type(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    r = client.post("/api/pack/brightvale/portrait/lean_wolf",
                    content=b"<svg/>", headers={"Content-Type": "image/svg+xml"})
    assert r.status_code == 400


def test_portrait_endpoints_guard_unknown_pack_and_traversal(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    assert client.post("/api/pack/nope/portrait/x", content=_PNG_1x1,
                       headers={"Content-Type": "image/png"}).status_code == 404
    # a traversal-y filename on the GET must not resolve
    assert client.get("/api/pack/brightvale/portrait/..%2F..%2Fpack.json").status_code == 404


# --- creature combat files (Phase 3b-1) -------------------------------------
def _valid_arena_monster() -> dict:
    """A minimal-but-valid Arena Monster JSON, built via the engine model so the
    test can't drift from the real shape."""
    from arena.models.monster import Monster
    return Monster(name="Gloom Beast", max_hit_points=40, armor_class=14,
                   challenge_rating=3).model_dump(mode="json")


def test_monster_combat_file_round_trips(tmp_path, monkeypatch):
    packs = _temp_brightvale(tmp_path, monkeypatch)
    mon = _valid_arena_monster()
    r = client.put("/api/pack/brightvale/monster/lean_wolf", json={"monster": mon})
    assert r.status_code == 200 and r.json()["filename"] == "lean_wolf.json"
    # written into the pack's monsters/ dir, where the bridge reads it
    assert (packs / "brightvale" / "monsters" / "lean_wolf.json").is_file()
    # and read back
    g = client.get("/api/pack/brightvale/monster/lean_wolf")
    assert g.status_code == 200 and g.json()["monster"]["name"] == "Gloom Beast"
    # surfaced in the open-pack listing so the editor can badge it
    assert "lean_wolf" in client.get("/api/pack/brightvale").json()["monster_files"]


def test_monster_combat_file_invalid_is_rejected(tmp_path, monkeypatch):
    packs = _temp_brightvale(tmp_path, monkeypatch)
    # armor_class as a string is not a valid Monster → 400, nothing written
    r = client.put("/api/pack/brightvale/monster/lean_wolf",
                   json={"monster": {"name": "Bad", "armor_class": "lots"}})
    assert r.status_code == 400
    assert not (packs / "brightvale" / "monsters" / "lean_wolf.json").exists()


def test_monster_combat_file_delete_reverts(tmp_path, monkeypatch):
    packs = _temp_brightvale(tmp_path, monkeypatch)
    client.put("/api/pack/brightvale/monster/lean_wolf", json={"monster": _valid_arena_monster()})
    r = client.delete("/api/pack/brightvale/monster/lean_wolf")
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert not (packs / "brightvale" / "monsters" / "lean_wolf.json").exists()
    # idempotent: deleting again is fine
    assert client.delete("/api/pack/brightvale/monster/lean_wolf").json()["deleted"] is False
    # GET on a creature with no combat file is a 404
    assert client.get("/api/pack/brightvale/monster/lean_wolf").status_code == 404


def test_monster_combat_file_guards_unknown_pack_and_traversal(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    assert client.put("/api/pack/nope/monster/x", json={"monster": _valid_arena_monster()}).status_code == 404
    assert client.get("/api/pack/brightvale/monster/..%2F..%2Fpack").status_code == 404


# --- SRD clone sources (Phase 3b-2) -----------------------------------------
def test_srd_monsters_list_is_offered():
    r = client.get("/api/srd/monsters")
    assert r.status_code == 200
    monsters = {m["id"]: m for m in r.json()["monsters"]}
    assert "owlbear" in monsters and monsters["owlbear"]["name"] == "Owlbear"
    assert len(monsters) > 300                      # the full SRD bestiary


def test_srd_monster_returns_statblock_and_combat():
    r = client.get("/api/srd/monster/owlbear")
    assert r.status_code == 200
    data = r.json()
    assert data["statblock"]["id"] == "owlbear"
    assert data["statblock"].get("description")     # rich identity carried
    # the full combat file rides too (two distinct attacks)
    assert data["combat"]["name"] == "Owlbear"
    assert len(data["combat"]["actions"]) == 2


def test_srd_monster_unknown_is_404():
    assert client.get("/api/srd/monster/not_a_monster").status_code == 404


# --- baseline projection for the attacks editor (Phase 3b-3a) ---------------
def test_monster_baseline_projects_statblock(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    sb = {"id": "gloom", "name": "Gloom Beast", "hp": 40, "armor_class": 14,
          "attack_bonus": 5, "damage": "2d6+3", "cr": 3.0,
          "abilities": {"str": 17, "dex": 12, "con": 15, "int": 3, "wis": 12, "cha": 6},
          "damage_resistances": ["cold"]}
    r = client.post("/api/pack/brightvale/monster-baseline", json={"statblock": sb})
    assert r.status_code == 200
    m = r.json()["monster"]
    assert m["max_hit_points"] == 40 and m["armor_class"] == 14
    assert m["ability_scores"]["strength"] == 17     # carried for to-hit derivation
    assert "cold" in m["damage_resistances"]         # defenses carried
    assert len(m["actions"]) == 1                    # a single starter attack


def test_monster_baseline_rejects_garbage(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    r = client.post("/api/pack/brightvale/monster-baseline",
                    json={"statblock": {"name": "no id or hp"}})
    assert r.status_code == 400


# --- the battlefield editor endpoint (location-battles S3) -------------------
# The GUI subprocess is faked: the stand-in reads the spec the server wrote,
# optionally writes an out-file, and the tests pin the whole contract around it
# (asset-path resolution, cancel = no out-file, crash = 500, re-validation).

def _fake_editor(write_battle=None, returncode=0, stderr=""):
    """A subprocess.run stand-in for `python -m arena.battlefield_editor`."""
    import types

    def run(cmd, **kw):
        run.spec = json.loads(Path(cmd[-2]).read_text(encoding="utf-8"))
        if write_battle is not None:
            Path(cmd[-1]).write_text(
                json.dumps({"battle": write_battle}), encoding="utf-8")
        return types.SimpleNamespace(returncode=returncode, stderr=stderr)
    return run


def _battle_block(**over):
    base = {"background_image": "brawl.png", "music_track": "brawl.mp3",
            "grid_width": 12, "grid_height": 9,
            "terrain": [{"position": [3, 3], "terrain_type": "wall"}]}
    base.update(over)
    return base


def test_battle_editor_resolves_assets_and_returns_the_edited_block(
        tmp_path, monkeypatch):
    packs = _temp_brightvale(tmp_path, monkeypatch)
    (packs / "brightvale" / "images").mkdir(exist_ok=True)
    (packs / "brightvale" / "audio").mkdir(exist_ok=True)
    (packs / "brightvale" / "images" / "brawl.png").write_bytes(b"png")
    (packs / "brightvale" / "audio" / "brawl.mp3").write_bytes(b"mp3")

    edited = _battle_block(grid_width=15,
                           terrain=[{"position": [1, 1], "terrain_type": "cover_half"}])
    fake = _fake_editor(write_battle=edited)
    monkeypatch.setattr("oubliette.creator.server.subprocess.run", fake)

    r = client.post("/api/pack/brightvale/battle-editor",
                    json={"place_name": "The Tap", "battle": _battle_block()})
    assert r.status_code == 200
    out = r.json()
    assert out["ok"] is True and "cancelled" not in out
    assert out["battle"]["grid_width"] == 15
    assert out["battle"]["terrain"][0]["terrain_type"] == "cover_half"
    # the spec the editor received: absolute, existing asset paths + the name
    assert fake.spec["place_name"] == "The Tap"
    assert fake.spec["background_path"].endswith("brawl.png")
    assert Path(fake.spec["background_path"]).is_absolute()
    assert fake.spec["music_path"].endswith("brawl.mp3")


def test_battle_editor_missing_assets_resolve_to_none(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)   # no images/ or audio/ files created
    fake = _fake_editor(write_battle=_battle_block())
    monkeypatch.setattr("oubliette.creator.server.subprocess.run", fake)
    r = client.post("/api/pack/brightvale/battle-editor",
                    json={"place_name": "X", "battle": _battle_block()})
    assert r.status_code == 200
    assert fake.spec["background_path"] is None
    assert fake.spec["music_path"] is None


def test_battle_editor_no_out_file_means_cancelled(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    monkeypatch.setattr("oubliette.creator.server.subprocess.run", _fake_editor())
    r = client.post("/api/pack/brightvale/battle-editor",
                    json={"place_name": "X", "battle": _battle_block()})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "cancelled": True}


def test_battle_editor_crash_is_500_with_stderr_tail(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    monkeypatch.setattr("oubliette.creator.server.subprocess.run",
                        _fake_editor(returncode=2, stderr="pygame exploded"))
    r = client.post("/api/pack/brightvale/battle-editor",
                    json={"place_name": "X", "battle": _battle_block()})
    assert r.status_code == 500
    assert "pygame exploded" in r.json()["error"]


def test_battle_editor_rejects_bad_blocks_both_ways(tmp_path, monkeypatch):
    _temp_brightvale(tmp_path, monkeypatch)
    # in: an invalid block never reaches the subprocess
    r = client.post("/api/pack/brightvale/battle-editor",
                    json={"place_name": "X", "battle": {"grid_width": 999}})
    assert r.status_code == 400
    # out: an editor that returns garbage doesn't corrupt the client's form
    monkeypatch.setattr("oubliette.creator.server.subprocess.run",
                        _fake_editor(write_battle={"grid_width": 999}))
    r = client.post("/api/pack/brightvale/battle-editor",
                    json={"place_name": "X", "battle": _battle_block()})
    assert r.status_code == 500


def test_battle_editor_unknown_pack_is_404():
    assert client.post("/api/pack/nope/battle-editor",
                       json={"place_name": "X", "battle": {}}).status_code == 404
