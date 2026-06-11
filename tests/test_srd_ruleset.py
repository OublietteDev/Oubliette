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
    """CS4 Gate 3: the complete SRD MUNDANE equipment chapter is loaded (the slice
    shipped only 10 items). Transcribed deterministically from the 5e-database 2014
    dataset: 37 weapons, 13 armor, plus adventuring gear / tools / mounts & vehicles,
    and a Potion of Healing. The magic-item chapter (A1) is tagged `magic` and lives
    alongside it — split it out here so this base tripwire still catches a dropped row."""
    rs = load_ruleset()
    base = {k: e for k, e in rs.equipment.items()
            if "magic" not in e.tags and "poison" not in e.tags}
    assert len(base) == 238
    by_cat = Counter(e.category for e in base.values())
    assert by_cat == {"gear": 141, "misc": 40, "weapon": 37, "armor": 13,
                      "consumable": 7}
    # the 13-piece armor set, each with the right type for the AC engine
    armor_types = Counter(e.armor.type for e in base.values() if e.armor)
    assert armor_types == {"light": 3, "medium": 5, "heavy": 4, "shield": 1}
    # only medium armor caps DEX (=2); light/heavy leave it unset (derive.py rules)
    assert all(e.armor.dex_cap == 2 for e in base.values()
               if e.armor and e.armor.type == "medium")
    assert all(e.armor.dex_cap is None for e in base.values()
               if e.armor and e.armor.type != "medium")
    # regression guard: the WebFetch reader had scrambled these artisan-tool prices
    assert base["jewelers_tools"].cost == 25 and base["cooks_utensils"].cost == 1
    assert base["cartographers_tools"].cost == 15 and base["glassblowers_tools"].cost == 30


def test_srd_magic_item_chapter_present():
    """A1 (content-first plan §3): the SRD magic-item chapter is folded into the same
    catalog, deterministically parsed from 5e-database (tools/gen_magic_items.py). Count
    + family tripwire so a future edit can't silently drop a row or a structured field.
    `mechanics == "structured"` marks the families the Arena bridge can carry into
    combat (healing / +X bonus / ability-set / resistance); the long tail ships as prose
    with `mechanics == "none"` — a deliberate success state, not a gap."""
    rs = load_ruleset()
    magic = {k: e for k, e in rs.equipment.items() if "magic" in e.tags}
    assert len(magic) == 331
    by_type = Counter(e.item_type for e in magic.values())
    # scroll == 1: the 10 per-level Spell Scrolls collapse to one generic record; the
    # spell (and thus the level) is inscribed per-inventory-item at grant time (A5).
    assert by_type == {"wondrous": 167, "ring": 34, "potion": 36, "weapon": 29,
                       "armor": 27, "wand": 15, "staff": 12, "scroll": 1,
                       "rod": 6, "ammunition": 4}
    assert "mundane" not in by_type            # every magic item carries a granular type
    assert rs.equipment["spell_scroll"].item_type == "scroll"   # the single generic scroll
    # the four healing tiers keep their structured dice for the bridge
    healing = {rs.equipment[i].consumable.healing for i in
               ("potion_of_healing", "potion_of_healing_greater",
                "potion_of_healing_superior", "potion_of_healing_supreme")}
    assert healing == {"2d4+2", "4d4+4", "8d4+8", "10d4+20"}
    # +X gear carries the magic_bonus the AC/to-hit math will honor
    assert rs.equipment["weapon_3"].magic_bonus == 3
    assert rs.equipment["armor_2"].magic_bonus == 2
    assert rs.equipment["ring_of_protection"].magic_bonus == 1
    assert rs.equipment["ring_of_protection"].requires_attunement is True
    # the structured/prose split is real and non-trivial on both sides
    structured = [e for e in magic.values() if e.mechanics == "structured"]
    assert 60 <= len(structured) <= 70
    assert all(e.consumable or e.magic_bonus is not None for e in structured)


def test_srd_poison_catalog_present():
    """A2 (completeness sweep): the SRD poison chapter (the one combat-relevant gap the
    sweep found) is parsed from the prose 'Poisons' rule-section (tools/gen_poisons.py).
    14 sample poisons carry the `poison` tag; the pre-existing basic poison vial keeps
    its place in the mundane 238 but is enriched with the same structured shape, so all
    15 carry combat mechanics (Con save DC, type, failed-save damage and/or conditions)."""
    rs = load_ruleset()
    tagged = {k: e for k, e in rs.equipment.items() if "poison" in e.tags}
    assert len(tagged) == 14                    # the 14 SRD sample poisons
    poisons = [e for e in rs.equipment.values() if e.item_type == "poison"]
    assert len(poisons) == 15                   # + the enriched basic vial
    for e in poisons:                           # every one is fully structured
        assert e.mechanics == "structured" and e.poison is not None
        assert e.poison.save_ability == "con" and e.poison.save_dc > 0
        assert e.poison.damage or e.poison.conditions   # damage and/or a condition
    # the four poison types are all represented (the bridge keys delivery off this)
    assert {e.poison.poison_type for e in poisons} == {"contact", "ingested", "inhaled", "injury"}
    # spot-check the extraction against the SRD table
    wyvern = rs.equipment["wyvern_poison"].poison
    assert wyvern.poison_type == "injury" and wyvern.save_dc == 15 and wyvern.damage == "7d6"
    crawler = rs.equipment["crawler_mucus"].poison
    assert crawler.conditions == ["poisoned", "paralyzed"] and crawler.damage is None
    # the harvesting flavor ("a dead or incapacitated purple worm") is NOT read as an effect
    assert rs.equipment["purple_worm_poison"].poison.conditions == []


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


def test_full_srd_bestiary_present():
    """The global SRD bestiary (content fleet): the complete SRD 5.1 monster list,
    mapped deterministically from the 5e-database 2014 dataset (NOT LLM recall — see
    tools/gen_bestiary.py). Count tripwire so a future edit can't silently drop a row;
    the enriched schema round-trips descriptors, defenses, and an actions list."""
    rs = load_ruleset()
    assert len(rs.bestiary) == 334
    # staples across the CR range all loaded
    assert {"goblin", "wolf", "orc", "ogre", "young_red_dragon", "tarrasque",
            "commoner", "lich"} <= set(rs.bestiary)
    # monsters_by_cr is the panel's order: ascending CR, then name — stable.
    crs = [s.cr for s in rs.monsters_by_cr()]
    assert crs == sorted(crs)
    assert rs.monsters_by_cr()[-1].cr == 30.0          # the Tarrasque, CR 30
    # enriched fields round-trip on a representative rich monster.
    drake = rs.bestiary["young_red_dragon"]
    assert drake.size == "Large" and drake.type == "dragon" and drake.cr == 10.0
    assert drake.damage_immunities == ["fire"]
    assert drake.speed["fly"] == "80 ft."
    assert drake.actions[0].name == "Multiattack"
    # the combat seam reads a single primary attack off the top level (the bite).
    assert drake.attack_bonus == 10 and drake.damage == "2d10+6"
    # actions keep BOTH structured fields and the verbatim SRD prose.
    bite = next(a for a in drake.actions if a.name == "Bite")
    assert bite.attack_bonus == 10 and bite.damage == "2d10+6"
    assert "Melee Weapon Attack" in bite.desc


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
