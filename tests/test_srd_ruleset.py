"""CS0 — the SRD ruleset loads whole, lints its cross-references, and reaches the
session. The bundled slice (fighter/wizard, a few races/backgrounds/spells) proves
the schemas before the full SRD content fill (CS4)."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from oubliette.content.loader import load_pack
from oubliette.content.ruleset import RulesetValidationError, load_ruleset
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.session import Session


# --- the bundled slice ------------------------------------------------------
def test_bundled_ruleset_loads():
    rs = load_ruleset()
    assert rs.srd_version == "5.1"
    assert "fighter" in rs.classes and "wizard" in rs.classes
    assert "human" in rs.races and "elf" in rs.races
    assert "acolyte" in rs.backgrounds
    assert "fire_bolt" in rs.spells and "longsword" in rs.equipment


def test_full_race_and_condition_sets_present():
    """CS4 Gate 1: the SRD's full 9 races and 15 conditions are loaded (the slice
    shipped only 3 of each). Count tripwire so a future content edit can't silently
    drop one; existing subraces still cross-reference elf/dwarf."""
    rs = load_ruleset()
    assert set(rs.races) == {"human", "elf", "dwarf", "halfling", "dragonborn",
                             "gnome", "half_elf", "half_orc", "tiefling"}
    # SRD 5.1 ships exactly one subrace per applicable race.
    assert set(rs.subraces) == {"high_elf", "hill_dwarf", "lightfoot_halfling", "rock_gnome"}
    assert {s.race for s in rs.subraces.values()} == {"elf", "dwarf", "halfling", "gnome"}
    assert len(rs.conditions) == 15
    assert {"exhaustion", "unconscious", "petrified", "blinded"} <= set(rs.conditions)


def test_full_equipment_catalog_present():
    """CS4 Gate 3: the complete SRD equipment chapter is loaded (the slice shipped
    only 10 items). Transcribed deterministically from the 5e-database 2014 dataset:
    37 weapons, 13 armor, plus adventuring gear / tools / mounts & vehicles, and a
    Potion of Healing. Count tripwire so a future edit can't silently drop a row."""
    rs = load_ruleset()
    eq = rs.equipment
    assert len(eq) == 238
    by_cat = Counter(e.category for e in eq.values())
    assert by_cat == {"gear": 141, "misc": 40, "weapon": 37, "armor": 13,
                      "consumable": 7}
    # the 13-piece armor set, each with the right type for the AC engine
    armor_types = Counter(e.armor.type for e in eq.values() if e.armor)
    assert armor_types == {"light": 3, "medium": 5, "heavy": 4, "shield": 1}
    # only medium armor caps DEX (=2); light/heavy leave it unset (derive.py rules)
    assert all(e.armor.dex_cap == 2 for e in eq.values()
               if e.armor and e.armor.type == "medium")
    assert all(e.armor.dex_cap is None for e in eq.values()
               if e.armor and e.armor.type != "medium")
    # regression guard: the WebFetch reader had scrambled these artisan-tool prices
    assert eq["jewelers_tools"].cost == 25 and eq["cooks_utensils"].cost == 1
    assert eq["cartographers_tools"].cost == 15 and eq["glassblowers_tools"].cost == 30


def test_full_class_and_subclass_sets_present():
    """CS4 Gate 4: all 12 SRD classes load, each with exactly one SRD subclass.
    Count + caster-shape tripwire so a future edit can't silently drop one."""
    rs = load_ruleset()
    assert set(rs.classes) == {"barbarian", "bard", "cleric", "druid", "fighter",
                               "monk", "paladin", "ranger", "rogue", "sorcerer",
                               "warlock", "wizard"}
    assert set(rs.subclasses) == {"champion", "evocation", "life", "lore", "land",
                                  "open_hand", "devotion", "hunter", "thief"}
    for s in rs.subclasses.values():           # every subclass parent resolves
        assert s.parent in rs.classes
    # Vancian casters carry a full 20-row spell table; warlock uses Pact Magic.
    vancian = {cid for cid, c in rs.classes.items() if c.spell_progression}
    assert vancian == {"bard", "cleric", "druid", "paladin", "ranger", "sorcerer", "wizard"}
    assert all(len(rs.classes[c].spell_progression) == 20 for c in vancian)
    assert rs.classes["warlock"].pact_magic_progression
    # martial classes have no spell list at all
    noncasters = {cid for cid, c in rs.classes.items() if c.spellcasting is None}
    assert noncasters == {"barbarian", "fighter", "monk", "rogue"}
    # leveled resource pools landed where they belong
    assert {r.name for r in rs.classes["monk"].resources} == {"Ki"}
    assert {r.name for r in rs.classes["paladin"].resources} == {"Lay on Hands", "Channel Divinity"}
    assert rs.classes["rogue"].asi_levels == [4, 8, 10, 12, 16, 19]  # rogue's extra ASI


def test_full_spell_list_present():
    """CS4 Gate 5: the complete SRD spell list (319) loads, mapped deterministically
    from the 5e-database 2014 dataset. Count + per-level tripwire; also asserts the
    High Elf wizard 3-cantrip gap is closed (the slice shipped only 2 wizard cantrips)."""
    rs = load_ruleset()
    assert len(rs.spells) == 319
    by_level = Counter(s.level for s in rs.spells.values())
    assert by_level == {0: 24, 1: 49, 2: 54, 3: 42, 4: 31, 5: 37, 6: 31, 7: 20,
                        8: 16, 9: 15}
    wizard_cantrips = [s for s in rs.spells.values() if s.level == 0 and "wizard" in s.classes]
    assert len(wizard_cantrips) >= 3        # High Elf wizard can now pick 3
    # every spell's class list resolves to real classes
    for sp in rs.spells.values():
        for cid in sp.classes:
            assert cid in rs.classes


def test_bundled_bestiary_loads_sorted_by_cr():
    """The global SRD bestiary layer (bestiary arc). A seed of 8 iconic monsters
    across the CR range; the content fleet grows it to the full SRD list. Spot-check
    the schema's enriched fields survived the round-trip and the CR sort is stable."""
    rs = load_ruleset()
    assert set(rs.bestiary) == {"goblin", "wolf", "skeleton", "zombie", "orc",
                                "brown_bear", "ogre", "young_red_dragon"}
    # monsters_by_cr is the panel's order: ascending CR, then name.
    names = [s.name for s in rs.monsters_by_cr()]
    assert names[0] in {"Goblin", "Skeleton", "Wolf", "Zombie"}  # the CR-1/4 cohort
    assert names[-1] == "Young Red Dragon"                       # CR 10, the top
    crs = [s.cr for s in rs.monsters_by_cr()]
    assert crs == sorted(crs)
    # enriched fields round-trip: descriptors, defenses, and an actions list.
    drake = rs.bestiary["young_red_dragon"]
    assert drake.size == "Large" and drake.type == "dragon" and drake.cr == 10.0
    assert drake.damage_immunities == ["fire"]
    assert drake.speed["fly"] == "80 ft."
    assert drake.actions[0].name == "Multiattack"
    assert any(a.name.startswith("Fire Breath") for a in drake.actions)
    # the combat seam still reads a single primary attack off the top level.
    assert drake.attack_bonus == 10 and drake.damage == "2d10+6"


def test_bad_skill_in_bestiary_flagged(tmp_path):
    root = _write_srd(tmp_path, bestiary=[{
        "id": "griffon", "name": "Griffon", "hp": 59, "armor_class": 12,
        "skills": ["falconry"],
    }])
    with pytest.raises(RulesetValidationError) as e:
        load_ruleset(srd_root=root)
    assert any("falconry" in m for m in e.value.errors)


def test_unknown_bestiary_loot_ref_flagged(tmp_path):
    root = _write_srd(tmp_path, bestiary=[{
        "id": "mimic", "name": "Mimic", "hp": 58, "armor_class": 12,
        "loot": [{"item": "phantom_blade", "qty": 1}],
    }])
    with pytest.raises(RulesetValidationError) as e:
        load_ruleset(srd_root=root)
    assert any("phantom_blade" in m for m in e.value.errors)


def test_only_srd_legal_backgrounds_and_feats():
    """Strict-SRD guard. SRD 5.1 contains exactly ONE background (Acolyte) and ONE
    feat (Grappler). This tripwire fails if non-SRD content sneaks back in — a prior
    pass had injected Soldier + Alert/Tough/Resilient from memory, a WotC-copyright
    risk. Enriching chargen later with ORIGINAL-flavor content is a deliberate change
    that updates this test on purpose."""
    rs = load_ruleset()
    assert set(rs.backgrounds) == {"acolyte"}
    assert set(rs.feats) == {"grappler"}


def test_wizard_is_a_full_caster_with_the_srd_slot_table():
    rs = load_ruleset()
    wiz = rs.classes["wizard"]
    assert wiz.hit_die == 6
    assert wiz.spellcasting and wiz.spellcasting.caster_type == "full"
    assert wiz.spellcasting.ability == "int"
    rows = {r.level: r for r in wiz.spell_progression}
    assert len(rows) == 20
    assert rows[1].spell_slots == [2]
    assert rows[5].spell_slots == [4, 3, 2]      # the SRD full-caster row, verbatim
    assert rows[20].spell_slots == [4, 3, 3, 3, 3, 2, 2, 1, 1]
    assert rows[1].cantrips_known == 3 and rows[10].cantrips_known == 5


def test_fighter_is_martial_with_two_saves():
    rs = load_ruleset()
    fig = rs.classes["fighter"]
    assert fig.hit_die == 10
    assert set(fig.saving_throws) == {"str", "con"}
    assert fig.spellcasting is None
    assert fig.skill_choices.choose == 2 and "athletics" in fig.skill_choices.from_


def test_hard_classes_loaded_with_their_mechanics():
    rs = load_ruleset()
    # warlock: pact magic, no Vancian table
    wl = rs.classes["warlock"]
    assert wl.spellcasting.caster_type == "pact"
    assert len(wl.pact_magic_progression) == 20 and not wl.spell_progression
    assert wl.pact_magic_progression[0].slots == 1 and wl.pact_magic_progression[0].slot_level == 1
    # sorcerer: full caster + a Sorcery Points resource
    sor = rs.classes["sorcerer"]
    assert any(r.name == "Sorcery Points" for r in sor.resources)
    assert len(sor.spell_progression) == 20
    # barbarian: a Rage resource that ends unlimited, no spellcasting
    bar = rs.classes["barbarian"]
    assert bar.spellcasting is None
    rage = next(r for r in bar.resources if r.name == "Rage")
    assert rage.by_level[20] == -1


def test_lookups():
    rs = load_ruleset()
    assert [s.id for s in rs.subclasses_for("fighter")] == ["champion"]
    assert [s.id for s in rs.subraces_for("elf")] == ["high_elf"]
    assert {s.id for s in rs.spells_for("wizard")} >= {"fire_bolt", "magic_missile"}


def test_starting_equipment_references_resolve():
    rs = load_ruleset()
    fig = rs.classes["fighter"]
    # every granted item id exists in the equipment catalog
    refs = {g.item for g in fig.starting_equipment.fixed}
    for ch in fig.starting_equipment.choices:
        for opt in ch.options:
            refs |= {g.item for g in opt}
    assert refs <= set(rs.equipment)


# --- the linter catches bad cross-references --------------------------------
def _write_srd(tmp, **files):
    d = tmp / "srd"
    d.mkdir(parents=True)
    (d / "ruleset.json").write_text(json.dumps({"srd_version": "5.1"}), encoding="utf-8")
    for name, data in files.items():
        (d / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return d


def test_unknown_equipment_ref_flagged(tmp_path):
    root = _write_srd(tmp_path, classes=[{
        "id": "fighter", "name": "Fighter", "hit_die": 10,
        "starting_equipment": {"fixed": [{"item": "ghost_sword"}]},
    }])
    with pytest.raises(RulesetValidationError) as e:
        load_ruleset(srd_root=root)
    assert any("ghost_sword" in m for m in e.value.errors)


def test_unknown_subclass_parent_flagged(tmp_path):
    root = _write_srd(tmp_path, subclasses=[{"id": "champion", "name": "Champion", "parent": "ranger"}])
    with pytest.raises(RulesetValidationError) as e:
        load_ruleset(srd_root=root)
    assert any("ranger" in m for m in e.value.errors)


def test_unknown_spell_class_flagged(tmp_path):
    root = _write_srd(tmp_path, spells=[{
        "id": "fire_bolt", "name": "Fire Bolt", "level": 0, "school": "evocation",
        "classes": ["sorcerer"],
    }])
    with pytest.raises(RulesetValidationError) as e:
        load_ruleset(srd_root=root)
    assert any("sorcerer" in m for m in e.value.errors)


def test_bad_skill_in_class_flagged(tmp_path):
    root = _write_srd(tmp_path, classes=[{
        "id": "fighter", "name": "Fighter", "hit_die": 10,
        "skill_choices": {"choose": 1, "from": ["jousting"]},
    }])
    with pytest.raises(RulesetValidationError) as e:
        load_ruleset(srd_root=root)
    assert any("jousting" in m for m in e.value.errors)


# --- it reaches the world + session -----------------------------------------
def test_loaded_world_carries_the_ruleset():
    world = load_pack("brightvale")
    assert world.ruleset is not None and "wizard" in world.ruleset.classes


def test_session_carries_the_ruleset():
    session = Session.open(InMemoryEventStore())
    assert session.ruleset is not None and "fighter" in session.ruleset.classes
