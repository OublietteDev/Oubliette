"""Tests for binding monster spell-list prose to castable spell Actions
(Brain — Slice 2: monster spellcasting).

The combat engine already casts spells; the gap was that SRD caster stat blocks
carry their spells as prose the AI never reads. These tests pin the parser, the
library binding (DC stamping, per-rest budgets, action routing), and hydration
of a real SRD Mage — which must still validate as a Monster.
"""

import json
from pathlib import Path

import pytest

from arena.models.monster import Monster
from arena.paths import DATA_DIR
from arena.util.monster_spells import (
    load_spell_library,
    parse_spellcasting,
    build_spell_actions,
    hydrate_monster_spells,
    _normalize,
)

SRD_DIR = DATA_DIR / "monsters" / "srd"

MAGE_PROSE = (
    "The mage is a 9th-level spellcaster. Its spellcasting ability is "
    "Intelligence (spell save DC 14, +6 to hit with spell attacks). The mage "
    "has the following wizard spells prepared:\n\n"
    "- Cantrips (at will): fire bolt, light, mage hand, prestidigitation\n"
    "- 1st level (4 slots): detect magic, mage armor, magic missile, shield\n"
    "- 2nd level (3 slots): misty step, suggestion\n"
    "- 3rd level (3 slots): counterspell, fireball, fly\n"
    "- 4th level (3 slots): greater invisibility, ice storm\n"
    "- 5th level (1 slot): cone of cold"
)

EFREETI_PROSE = (
    "The efreeti's innate spellcasting ability is Charisma (spell save DC 15, "
    "+7 to hit with spell attacks). It can innately cast the following spells:\n"
    "At will: detect magic\n"
    "3/day: enlarge/reduce, tongues\n"
    "1/day each: gaseous form, invisibility, wall of fire"
)


@pytest.fixture(scope="module")
def library():
    return load_spell_library()


# ── Parsing ──────────────────────────────────────────────────────────


def test_parse_reads_dc_and_attack_bonus():
    p = parse_spellcasting(MAGE_PROSE)
    assert p["dc"] == 14
    assert p["attack_bonus"] == 6


def test_parse_assigns_per_rest_from_slots_and_cantrips():
    p = parse_spellcasting(MAGE_PROSE)
    uses = dict(p["spells"])
    assert uses["fire bolt"] is None          # cantrip = unlimited
    assert uses["magic missile"] == 4         # 1st level (4 slots)
    assert uses["fireball"] == 3              # 3rd level (3 slots)
    assert uses["cone of cold"] == 1          # 5th level (1 slot)


def test_parse_innate_at_will_and_per_day():
    p = parse_spellcasting(EFREETI_PROSE)
    assert p["dc"] == 15 and p["attack_bonus"] == 7
    uses = dict(p["spells"])
    assert uses["detect magic"] is None       # at will
    assert uses["tongues"] == 3               # 3/day
    assert uses["wall of fire"] == 1          # 1/day each


def test_parse_strips_parentheticals():
    p = parse_spellcasting(
        "spell save DC 12.\n1/day each: conjure elemental (fire elemental only), gaseous form"
    )
    names = [n for n, _ in p["spells"]]
    assert "conjure elemental" in names
    assert "gaseous form" in names


# ── Binding ──────────────────────────────────────────────────────────


def test_fireball_binds_with_monster_dc(library):
    actions, _, _, _ = build_spell_actions(MAGE_PROSE, library)
    fireball = next(a for a in actions if a["name"] == "Fireball")
    assert fireball["saving_throw"]["dc"] == 14         # stamped from prose
    assert fireball["uses_per_rest"] == 3               # 3rd-level slots
    assert "resource_cost" not in fireball              # slots -> uses, not pool
    assert fireball["target_type"].startswith("area")
    assert fireball["ai_use_condition"] == "enemies_in_range >= 2"


def test_cantrip_is_unlimited(library):
    actions, _, _, _ = build_spell_actions(MAGE_PROSE, library)
    fire_bolt = next(a for a in actions if a["name"] == "Fire Bolt")
    assert "uses_per_rest" not in fire_bolt             # at-will


def test_uncovered_utility_spells_are_skipped(library):
    _, _, _, skipped = build_spell_actions(MAGE_PROSE, library)
    low = {_normalize(s) for s in skipped}
    # These utility spells aren't in the combat library -> reported, not silent.
    assert "light" in low
    assert "prestidigitation" in low
    # ...but the combat spells DID bind.
    actions, _, _, _ = build_spell_actions(MAGE_PROSE, library)
    bound = {a["name"] for a in actions}
    assert {"Fireball", "Hold Person" if "Hold Person" in bound else "Magic Missile"} & bound
    assert "Magic Missile" in bound and "Cone of Cold" in bound


# ── Hydration of a real SRD caster ───────────────────────────────────


def _unbaked_mage():
    """The SRD Mage with its spells stripped back to the pre-bake state
    (only the Dagger), so the test is independent of whether the on-disk file
    has already had spells baked in."""
    mage = json.loads((SRD_DIR / "mage.json").read_text(encoding="utf-8"))
    mage["actions"] = [a for a in mage["actions"] if a["name"] == "Dagger"]
    mage.pop("bonus_actions", None)
    mage.pop("reactions", None)
    return mage


def test_hydrate_real_srd_mage(library):
    mage = _unbaked_mage()
    assert {a["name"] for a in mage["actions"]} == {"Dagger"}   # the bug: dagger only

    summary = hydrate_monster_spells(mage, library)
    after = {a["name"] for a in mage["actions"]}

    assert summary["added"] >= 5
    assert "Fireball" in after and "Magic Missile" in after and "Cone of Cold" in after
    assert "Dagger" in after                            # kept the fallback
    # Still a valid monster after hydration.
    Monster.model_validate(mage)


def test_hydrate_is_idempotent(library):
    mage = _unbaked_mage()
    hydrate_monster_spells(mage, library)
    n_after_first = len(mage["actions"])
    second = hydrate_monster_spells(mage, library)
    assert second["added"] == 0                         # no duplicate spells
    assert len(mage["actions"]) == n_after_first


def test_non_caster_is_noop(library):
    wolf = json.loads((SRD_DIR / "wolf.json").read_text(encoding="utf-8"))
    before = len(wolf["actions"])
    summary = hydrate_monster_spells(wolf, library)
    assert summary == {"added": 0, "skipped": []}
    assert len(wolf["actions"]) == before
