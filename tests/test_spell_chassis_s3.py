"""Module-kit Stage 3: the chassis spell builder.

A pack authors custom spells constrained to the four shapes the Arena already
executes natively — `bolt` (spell attack → damage), `blast` (save-or-take AoE),
`heal` (dice + caster's modifier), `hex` (save vs condition, held by
concentration). One source of truth: the pack `spells.json` entry IS the spell
(the standard chargen `Spell` shape plus a `chassis` block); the loader merges
it into the session ruleset like S2 backgrounds, and the bridge projects the
chassis into an Arena Action at fight time (`chassis_action`) — no generated
sidecar files. Pack ids can never shadow SRD spells (lint), so the projection
and the generated SRD library never fight over an id.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oubliette.combat.arena_bridge import (
    chassis_action,
    character_to_player,
    scroll_actions,
    spell_actions,
)
from oubliette.content.loader import PackValidationError, load_pack
from oubliette.content.ruleset import load_ruleset
from oubliette.content.schemas import CHASSIS_CONDITIONS, CHASSIS_DAMAGE_TYPES
from oubliette.content.srd_schemas import PackSpell
from oubliette.enums import Ability
from oubliette.state.models import Character, CharacterSheet, ItemStack

RS = load_ruleset()

EMBERBOLT = {
    "id": "emberbolt", "name": "Emberbolt", "level": 0, "school": "evocation",
    "range": "120 feet", "classes": ["wizard", "sorcerer"],
    "description": "A whip-crack of bay-fire.",
    "chassis": {"kind": "bolt", "range_ft": 120,
                "damage": "1d10", "damage_type": "fire"},
}
TIDESURGE = {
    "id": "tidesurge", "name": "Tidesurge", "level": 2, "school": "evocation",
    "range": "Self (15-foot cone)", "classes": ["wizard"],
    "description": "The bay answers, briefly and coldly.",
    "chassis": {"kind": "blast", "range_ft": 0, "shape": "cone", "size_ft": 15,
                "save": "dexterity", "damage": "3d8", "damage_type": "cold",
                "on_save": "half", "upcast_dice": "1d8"},
}
MENDING_TIDE = {
    "id": "mending_tide", "name": "Mending Tide", "level": 1,
    "school": "abjuration", "range": "Touch", "classes": ["cleric"],
    "description": "Salt water closes the wound.",
    "chassis": {"kind": "heal", "range_ft": 5, "healing": "1d8",
                "upcast_dice": "1d8"},
}
DROWNING_GRIP = {
    "id": "drowning_grip", "name": "Drowning Grip", "level": 2,
    "school": "enchantment", "range": "60 feet", "concentration": True,
    "duration": "Concentration, up to 1 minute", "classes": ["wizard"],
    "description": "Phantom brine fills the lungs.",
    "chassis": {"kind": "hex", "range_ft": 60, "save": "constitution",
                "conditions": ["restrained"], "save_ends": True,
                "upcast_targets": 1},
}

ALL_SPELLS = [EMBERBOLT, TIDESURGE, MENDING_TIDE, DROWNING_GRIP]


def _minimal_pack() -> dict:
    return {
        "pack.json": {
            "id": "t", "schema_version": 1, "name": "Test", "version": "1.0.0",
            "entry_scenario": "s",
        },
        "items.json": [],
        "statblocks.json": [],
        "npcs.json": [],
        "places.json": [
            {"id": "p", "name": "P", "description": "a place", "exits": []},
        ],
        "scenarios.json": [
            {"id": "s", "name": "S", "start_location": "p"},
        ],
        "spells.json": [json.loads(json.dumps(s)) for s in ALL_SPELLS],
    }


def _write_pack(root: Path, files: dict, pack_id: str = "t") -> Path:
    d = root / pack_id
    d.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (d / name).write_text(json.dumps(content), encoding="utf-8")
    return root


def _load(tmp_path, files=None):
    return load_pack("t", packs_root=_write_pack(tmp_path, files or _minimal_pack()))


def _spell(overrides: dict | None = None, **chassis) -> PackSpell:
    raw = json.loads(json.dumps(EMBERBOLT))
    raw.update(overrides or {})
    raw["chassis"].update(chassis)
    return PackSpell(**raw)


# --- the vocabularies stay honest with the Arena ---------------------------------

def test_chassis_vocabularies_match_the_arena():
    from arena.models.actions import DamageType
    from arena.models.conditions import Condition
    assert CHASSIS_DAMAGE_TYPES == {d.value for d in DamageType}
    assert CHASSIS_CONDITIONS <= {c.value for c in Condition}


# --- loading & merging ----------------------------------------------------------

def test_pack_spells_join_the_session_ruleset(tmp_path):
    world = _load(tmp_path)
    for sid in ("emberbolt", "tidesurge", "mending_tide", "drowning_grip"):
        assert sid in world.ruleset.spells
    assert "fire_bolt" in world.ruleset.spells      # the SRD set rides along
    # class spell lists serve the merged set — chargen sees them for free
    wizard_list = {s.id for s in world.ruleset.spells_for("wizard")}
    assert {"emberbolt", "tidesurge", "drowning_grip"} <= wizard_list
    # The global SRD singleton was never polluted by the merge.
    assert "emberbolt" not in RS.spells


def test_a_pack_without_spells_is_srd_only(tmp_path):
    files = _minimal_pack()
    del files["spells.json"]
    world = _load(tmp_path, files)
    assert set(world.ruleset.spells) == set(RS.spells)


# --- lint rules ------------------------------------------------------------------

def test_shadowing_an_srd_spell_is_an_error(tmp_path):
    files = _minimal_pack()
    files["spells.json"][0]["id"] = "fire_bolt"
    with pytest.raises(PackValidationError) as exc:
        _load(tmp_path, files)
    assert any("shadows an SRD spell" in e for e in exc.value.errors)


def test_unknown_class_is_an_error(tmp_path):
    files = _minimal_pack()
    files["spells.json"][0]["classes"] = ["wizard", "tidecaller"]
    with pytest.raises(PackValidationError) as exc:
        _load(tmp_path, files)
    assert any("unknown class 'tidecaller'" in e for e in exc.value.errors)


def test_duplicate_spell_ids_are_an_error(tmp_path):
    files = _minimal_pack()
    files["spells.json"].append(json.loads(json.dumps(EMBERBOLT)))
    with pytest.raises(PackValidationError) as exc:
        _load(tmp_path, files)
    assert any("duplicate id 'emberbolt'" in e for e in exc.value.errors)


def test_a_broken_chassis_is_an_aggregated_load_error(tmp_path):
    files = _minimal_pack()
    del files["spells.json"][1]["chassis"]["shape"]     # blast without a shape
    with pytest.raises(PackValidationError) as exc:
        _load(tmp_path, files)
    assert any("needs a shape" in e for e in exc.value.errors)


# --- chassis schema rules ---------------------------------------------------------

def test_cantrips_may_only_bolt_or_blast():
    with pytest.raises(ValueError, match="bolt or blast"):
        _spell({"level": 0, "chassis": dict(MENDING_TIDE["chassis"])})


def test_cantrips_refuse_upcast_fields():
    with pytest.raises(ValueError, match="scale automatically"):
        _spell(upcast_dice="1d10")


def test_a_hex_requires_concentration():
    raw = json.loads(json.dumps(DROWNING_GRIP))
    raw["concentration"] = False
    with pytest.raises(ValueError, match="concentration"):
        PackSpell(**raw)


def test_hex_conditions_come_from_the_curated_set():
    raw = json.loads(json.dumps(DROWNING_GRIP))
    raw["chassis"]["conditions"] = ["soggy"]
    with pytest.raises(ValueError, match="unknown condition 'soggy'"):
        PackSpell(**raw)


def test_damage_must_be_dice():
    with pytest.raises(ValueError, match="damage must be dice"):
        _spell(damage="a lot")


def test_fields_from_other_chassis_kinds_are_refused():
    with pytest.raises(ValueError, match="healing only belongs"):
        _spell(healing="1d8")


# --- the projection: chassis -> Arena Action --------------------------------------

def test_bolt_projects_like_a_generated_attack_cantrip():
    a = chassis_action(_spell())
    assert a.spell_level == 0 and a.cantrip_scaling is True
    assert not a.resource_cost
    assert a.target_type.value == "one_creature" and a.range == 120
    assert a.attack.attack_type == "ranged_spell"
    assert a.attack.range_normal == 120
    assert a.attack.damage[0].dice == "1d10"
    assert a.attack.damage[0].damage_type.value == "fire"
    assert "ranged spell attack" in a.description


def test_touch_bolt_is_a_melee_spell_attack():
    a = chassis_action(_spell({"level": 1}, range_ft=5))
    assert a.attack.attack_type == "melee_spell"
    assert a.attack.range_normal is None
    assert a.resource_cost == {"spell_slot_1": 1}


def test_blast_projects_like_a_generated_save_for_half_aoe():
    a = chassis_action(PackSpell(**TIDESURGE))
    assert a.target_type.value == "area_cone" and a.area_size == 15
    assert a.resource_cost == {"spell_slot_2": 1}
    st = a.saving_throw
    assert st.ability == "dexterity" and st.dc is None    # bridge stamps DC
    assert st.damage_on_fail[0].dice == "3d8"
    assert st.damage_on_fail[0].damage_type.value == "cold"
    assert st.damage_on_success == "half"
    assert a.upcast_damage_dice == "1d8"


def test_heal_projects_with_the_mod_token_and_upcast():
    a = chassis_action(PackSpell(**MENDING_TIDE))
    assert a.healing == "1d8+MOD"                 # bridge substitutes
    assert a.upcast_healing_dice == "1d8"
    assert a.target_type.value == "one_ally" and a.range == 5
    assert a.ai_priority == 7                     # heals rank like Cure Wounds


def test_hex_projects_as_save_vs_condition_under_concentration():
    a = chassis_action(PackSpell(**DROWNING_GRIP))
    assert a.requires_concentration is True
    assert a.saving_throw.conditions_on_fail == ["restrained"]
    assert a.saving_throw.conditions_no_resave is False   # save_ends=True
    assert a.upcast_target_count == 1
    assert a.resource_cost == {"spell_slot_2": 1}


def test_a_no_resave_hex_holds_until_concentration_drops():
    raw = json.loads(json.dumps(DROWNING_GRIP))
    raw["chassis"]["save_ends"] = False
    a = chassis_action(PackSpell(**raw))
    assert a.saving_throw.conditions_no_resave is True


def test_flat_damage_riders_split_into_the_bonus_field():
    a = chassis_action(_spell({"level": 1}, damage="2d6+1"))
    assert a.attack.damage[0].dice == "2d6" and a.attack.damage[0].bonus == 1


# --- the bridge bake: pack spells arrive castable ----------------------------------

def _wizard(world) -> Character:
    """L3 wizard: INT +3, prof +2 → spell DC 13."""
    return Character(
        id="skid", name="Skid", kind="pc", level=3, hp=16, max_hp=16,
        abilities={Ability.INT: 16, Ability.DEX: 12, Ability.CON: 12},
        armor_class=12, attack_bonus=4, damage="1d4+1",
        sheet=CharacterSheet(
            race="gnome", char_class="wizard", background="acolyte",
            spellcasting_ability=Ability.INT,
            cantrips_known=["emberbolt", "fire_bolt"],
            spells_known=["tidesurge", "drowning_grip"],
        ))


def test_caster_kit_serves_pack_and_srd_spells_side_by_side(tmp_path):
    world = _load(tmp_path)
    actions = {a.name: a for a in spell_actions(_wizard(world), world.ruleset)}
    assert set(actions) == {"Emberbolt", "Fire Bolt", "Tidesurge", "Drowning Grip"}
    assert actions["Emberbolt"].attack.ability == "intelligence"   # baked
    assert actions["Tidesurge"].saving_throw.dc == 13              # 8 + 2 + 3
    assert actions["Drowning Grip"].saving_throw.dc == 13


def test_without_a_ruleset_pack_spells_stay_story_side(tmp_path):
    world = _load(tmp_path)
    names = {a.name for a in spell_actions(_wizard(world))}
    assert names == {"Fire Bolt"}                 # the SRD half still works


def test_player_mapping_carries_the_pack_spell(tmp_path):
    world = _load(tmp_path)
    creature = character_to_player(_wizard(world), None, world.ruleset)
    names = [a.name for a in creature.actions]
    assert {"Emberbolt", "Tidesurge", "Drowning Grip"} <= set(names)


def test_a_scroll_of_a_pack_spell_is_castable(tmp_path):
    world = _load(tmp_path)
    char = _wizard(world)
    char.inventory.append(ItemStack(
        item_id="spell_scroll", qty=1, spell="mending_tide", spell_level=None))
    (a,) = scroll_actions(char, RS.equipment, world.ruleset)
    assert a.name == "Scroll: Mending Tide (1st-level)"
    assert a.resource_cost == {}                  # the scroll IS the cost
    assert a.healing == "1d8+3"                   # reader's INT mod baked


# --- chargen learns pack spells -----------------------------------------------------

# a level-1 wizard's exact quota here: 3 cantrips + 4 first-level spells
_WIZARD_L1_SPELLS = ["magic_missile", "shield", "mage_armor", "burning_hands"]


def _wizard_build(ruleset, cantrips, spells):
    from oubliette.rules.chargen import CharacterBuild
    wizard = ruleset.classes["wizard"]
    return CharacterBuild(
        name="Skid", race="human", char_class="wizard", background="acolyte",
        ability_method="standard_array",
        base_abilities={"int": 15, "dex": 14, "con": 13,
                        "str": 12, "wis": 10, "cha": 8},
        skills=["arcana", "investigation"],
        race_languages=["dwarvish"],
        languages=["elvish", "draconic"],     # acolyte grants two
        cantrips=cantrips, spells=spells,
        equipment_choices=[list(range(ch.choose))
                           for ch in wizard.starting_equipment.choices],
    )


def test_chargen_learns_a_pack_spell(tmp_path):
    world = _load(tmp_path)
    from oubliette.rules.chargen import build_character
    build = _wizard_build(world.ruleset,
                          cantrips=["emberbolt", "fire_bolt", "light"],
                          spells=list(_WIZARD_L1_SPELLS))
    char, _ = build_character(build, world.ruleset, "pc")
    assert "emberbolt" in char.sheet.cantrips_known


def test_chargen_still_rejects_off_list_spells(tmp_path):
    world = _load(tmp_path)
    from oubliette.rules.chargen import ChargenError, build_character
    build = _wizard_build(world.ruleset,      # heal is cleric-only, and not a cantrip
                          cantrips=["mending_tide", "fire_bolt", "light"],
                          spells=list(_WIZARD_L1_SPELLS))
    with pytest.raises(ChargenError):
        build_character(build, world.ruleset, "pc")


# --- the Forge's wizard reaches the same merge via ?pack= ---------------------------

def test_forge_chargen_options_serve_pack_spells(tmp_path, monkeypatch):
    _write_pack(tmp_path, _minimal_pack())
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(tmp_path))
    from fastapi.testclient import TestClient
    from oubliette.creator.server import app
    client = TestClient(app)
    plain = client.get("/api/chargen/options").json()
    merged = client.get("/api/chargen/options", params={"pack": "t"}).json()

    def wizard_cantrips(payload):
        return {s["id"] for s in payload["spells_by_class"]["wizard"]["cantrips"]}

    assert "emberbolt" not in wizard_cantrips(plain)
    assert {"emberbolt", "fire_bolt"} <= wizard_cantrips(merged)
