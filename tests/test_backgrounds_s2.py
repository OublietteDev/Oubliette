"""Module-kit Stage 2: pack-authored backgrounds.

SRD 5.1 ships exactly ONE background (Acolyte), so a world that wants its
characters to feel native authors its own. Packs gain a `backgrounds.json`
(the SRD `Background` shape); the loader lints it (no SRD shadowing, real
skills, resolvable equipment grants) and hands the session a PACK-MERGED
ruleset — backgrounds joined, and `ruleset.equipment` now the same merged
mechanics catalog the bridge uses, so a background can grant pack items and
chargen just works. The Forge's person-NPC wizard reaches the same merge via
`?pack=` on the /api/chargen endpoints.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oubliette.content.loader import PackValidationError, load_pack
from oubliette.content.ruleset import load_ruleset
from oubliette.rules.chargen import CharacterBuild, build_character

RS = load_ruleset()

DOCKHAND = {
    "id": "silverfin_dockhand",
    "name": "Silverfin Dockhand",
    "skill_proficiencies": ["athletics", "insight"],
    "tool_proficiencies": ["cargo hook"],
    "equipment": [{"item": "sword", "qty": 1}],       # a PACK item (S1 synergy)
    "starting_gold": 10,
    "feature": {"name": "Dock Rat", "level": 1,
                "text": "Dockworkers across the bay treat you as one of their own."},
    "personality_traits": ["I size up cargo, and people, by weight."],
    "ideals": ["The tide feeds everyone or no one."],
    "bonds": ["The Silverfin docks raised me."],
    "flaws": ["I can't leave a wager alone."],
}


def _minimal_pack() -> dict:
    return {
        "pack.json": {
            "id": "t", "schema_version": 1, "name": "Test", "version": "1.0.0",
            "entry_scenario": "s",
        },
        "items.json": [
            {"id": "sword", "name": "Dockhand's Sword", "category": "weapon",
             "base_value": 5},
        ],
        "statblocks.json": [],
        "npcs.json": [],
        "places.json": [
            {"id": "p", "name": "P", "description": "a place", "exits": []},
        ],
        "scenarios.json": [
            {"id": "s", "name": "S", "start_location": "p"},
        ],
        "backgrounds.json": [dict(DOCKHAND)],
    }


def _write_pack(root: Path, files: dict, pack_id: str = "t") -> Path:
    d = root / pack_id
    d.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (d / name).write_text(json.dumps(content), encoding="utf-8")
    return root


def _load(tmp_path, files=None):
    return load_pack("t", packs_root=_write_pack(tmp_path, files or _minimal_pack()))


# --- loading & merging ----------------------------------------------------------

def test_pack_background_joins_the_session_ruleset(tmp_path):
    world = _load(tmp_path)
    assert "silverfin_dockhand" in world.ruleset.backgrounds
    assert "acolyte" in world.ruleset.backgrounds          # the SRD set rides along
    bg = world.ruleset.backgrounds["silverfin_dockhand"]
    assert bg.skill_proficiencies == ["athletics", "insight"]
    assert bg.feature.name == "Dock Rat"


def test_a_pack_without_backgrounds_is_srd_only(tmp_path):
    files = _minimal_pack()
    del files["backgrounds.json"]
    world = _load(tmp_path, files)
    assert set(world.ruleset.backgrounds) == set(RS.backgrounds)


def test_ruleset_equipment_is_the_merged_catalog(tmp_path):
    world = _load(tmp_path)
    assert "sword" in world.ruleset.equipment              # pack item joined
    assert "potion_of_healing" in world.ruleset.equipment  # SRD still whole
    assert world.ruleset.equipment is world.mechanics_catalog
    # The global SRD singleton was never polluted by the merge.
    assert "sword" not in RS.equipment and "silverfin_dockhand" not in RS.backgrounds


# --- lint rules ------------------------------------------------------------------

def test_shadowing_an_srd_background_is_an_error(tmp_path):
    files = _minimal_pack()
    files["backgrounds.json"][0]["id"] = "acolyte"
    with pytest.raises(PackValidationError) as exc:
        _load(tmp_path, files)
    assert any("shadows an SRD background" in e for e in exc.value.errors)


def test_unknown_skill_is_an_error(tmp_path):
    files = _minimal_pack()
    files["backgrounds.json"][0]["skill_proficiencies"] = ["athletics", "barnacle_scraping"]
    with pytest.raises(PackValidationError) as exc:
        _load(tmp_path, files)
    assert any("unknown skill 'barnacle_scraping'" in e for e in exc.value.errors)


def test_unresolvable_equipment_grant_is_an_error(tmp_path):
    files = _minimal_pack()
    files["backgrounds.json"][0]["equipment"] = [{"item": "ghost_crate", "qty": 1}]
    with pytest.raises(PackValidationError) as exc:
        _load(tmp_path, files)
    assert any("unknown item 'ghost_crate'" in e for e in exc.value.errors)


def test_srd_equipment_grants_are_fine(tmp_path):
    files = _minimal_pack()
    files["backgrounds.json"][0]["equipment"] = [{"item": "rope_hempen_50_feet", "qty": 1}]
    world = _load(tmp_path, files)
    assert (world.ruleset.backgrounds["silverfin_dockhand"].equipment[0].item
            == "rope_hempen_50_feet")


def test_duplicate_background_ids_are_an_error(tmp_path):
    files = _minimal_pack()
    files["backgrounds.json"].append(dict(DOCKHAND))
    with pytest.raises(PackValidationError) as exc:
        _load(tmp_path, files)
    assert any("duplicate id 'silverfin_dockhand'" in e for e in exc.value.errors)


# --- chargen builds a character on a pack background ------------------------------

def _fighter_build(ruleset, background: str) -> CharacterBuild:
    fighter = ruleset.classes["fighter"]
    return CharacterBuild(
        name="Brina", race="human", char_class="fighter", background=background,
        ability_method="standard_array",
        base_abilities={"str": 15, "dex": 14, "con": 13,
                        "int": 12, "wis": 10, "cha": 8},
        skills=["perception", "survival"],
        race_languages=["dwarvish"],       # Human: one free language of choice
        equipment_choices=[list(range(ch.choose))
                           for ch in fighter.starting_equipment.choices],
    )


def test_chargen_grants_the_pack_backgrounds_kit(tmp_path):
    world = _load(tmp_path)
    char, items = build_character(_fighter_build(world.ruleset, "silverfin_dockhand"),
                                  world.ruleset, "pc")
    assert char.sheet.background == "silverfin_dockhand"
    # Background skills join the class picks on the character...
    assert {"athletics", "insight"} <= {s.value for s in char.skill_proficiencies}
    # ...and the PACK item grant materialized into a real inventory stack.
    assert any(s.item_id == "sword" for s in char.inventory)
    assert any(i.id == "sword" for i in items)


def test_chargen_still_rejects_an_unknown_background(tmp_path):
    world = _load(tmp_path)
    from oubliette.rules.chargen import ChargenError
    with pytest.raises(ChargenError):
        build_character(_fighter_build(world.ruleset, "noble"), world.ruleset, "pc")


# --- the Forge's wizard reaches the same merge via ?pack= --------------------------

def test_forge_chargen_options_merge_the_pack(tmp_path, monkeypatch):
    _write_pack(tmp_path, _minimal_pack())
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(tmp_path))
    from fastapi.testclient import TestClient
    from oubliette.creator.server import app
    client = TestClient(app)
    plain = client.get("/api/chargen/options").json()
    merged = client.get("/api/chargen/options", params={"pack": "t"}).json()
    assert "silverfin_dockhand" not in {b["id"] for b in plain["backgrounds"]}
    ids = {b["id"] for b in merged["backgrounds"]}
    assert {"silverfin_dockhand", "acolyte"} <= ids


def test_forge_chargen_builds_on_a_pack_background(tmp_path, monkeypatch):
    _write_pack(tmp_path, _minimal_pack())
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(tmp_path))
    from fastapi.testclient import TestClient
    from oubliette.creator.server import app
    client = TestClient(app)
    build = _fighter_build(RS, "silverfin_dockhand").model_dump(mode="json")
    refused = client.post("/api/chargen/build", json=build).json()
    assert refused["ok"] is False           # bare SRD: no such background
    built = client.post("/api/chargen/build", params={"pack": "t"}, json=build).json()
    assert built["ok"] is True
    assert built["character"]["sheet"]["background"] == "silverfin_dockhand"
    assert any(s["item_id"] == "sword" for s in built["character"]["inventory"])
