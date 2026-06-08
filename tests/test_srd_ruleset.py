"""CS0 — the SRD ruleset loads whole, lints its cross-references, and reaches the
session. The bundled slice (fighter/wizard, a few races/backgrounds/spells) proves
the schemas before the full SRD content fill (CS4)."""

from __future__ import annotations

import json

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
    assert "soldier" in rs.backgrounds
    assert "fire_bolt" in rs.spells and "longsword" in rs.equipment


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
