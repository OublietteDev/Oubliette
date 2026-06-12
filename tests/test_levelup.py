"""CS5 — the level-up builder. The player chooses (HP method, ASI/feat, subclass);
the builder validates against the rules and rebuilds the character one level higher,
carrying protected state over untouched."""

from __future__ import annotations

import pytest

from oubliette.content.ruleset import load_ruleset
from oubliette.enums import Ability
from oubliette.rules.levelup import (LevelUpChoice, LevelUpError, level_up, level_up_plan,
                                     level_for_xp, xp_for_level, xp_progress)
from oubliette.state.models import Character, CharacterSheet, ItemStack

RS = load_ruleset()


def _fighter(level=1, **over) -> Character:
    base = dict(
        id="pc", name="Bron", kind="pc", level=level, hp=12, max_hp=12, gold=10,
        xp=400_000,                       # above the level-20 threshold: XP never gates these

        abilities={Ability.STR: 16, Ability.DEX: 14, Ability.CON: 14,
                   Ability.INT: 10, Ability.WIS: 12, Ability.CHA: 8},
        inventory=[ItemStack(item_id="longsword", qty=1)],
        sheet=CharacterSheet(race="human", char_class="fighter", background="acolyte",
                             saving_throw_proficiencies={Ability.STR, Ability.CON}),
    )
    base.update(over)
    return Character(**base)


def _why(char, choice) -> str:
    with pytest.raises(LevelUpError) as ei:
        level_up(char, RS, choice)
    return "\n".join(ei.value.errors)


# --- the happy path ---------------------------------------------------------
def test_plain_level_grants_hp_and_features():
    leveled = level_up(_fighter(1), RS, LevelUpChoice())
    assert leveled.level == 2
    assert leveled.max_hp == 20 and leveled.hp == 20      # 12 + (avg d10 = 6 + CON 2)
    assert any(f.name == "Action Surge" for f in leveled.sheet.features)   # gained at L2
    assert leveled.gold == 10 and leveled.item_qty("longsword") == 1       # protected state carried


def test_rolled_hp_uses_the_roll():
    leveled = level_up(_fighter(1), RS, LevelUpChoice(hp_method="roll", hp_roll=10))
    assert leveled.max_hp == 24                            # 12 + (10 + CON 2)


def test_asi_raises_abilities():
    leveled = level_up(_fighter(3), RS, LevelUpChoice(ability_increases={Ability.STR: 2}))
    assert leveled.level == 4 and leveled.abilities[Ability.STR] == 18


def test_feat_at_asi_level_is_recorded():
    leveled = level_up(_fighter(3), RS, LevelUpChoice(feat="grappler"))   # SRD's only feat
    assert "grappler" in leveled.sheet.feats
    assert any(f.source == "feat" and f.name == "Grappler" for f in leveled.sheet.features)


# --- the firewall -----------------------------------------------------------
def test_asi_level_requires_a_choice():
    assert "distributes exactly 2 points" in _why(_fighter(3), LevelUpChoice())


def test_asi_must_total_two_points():
    assert "distributes exactly 2 points" in _why(
        _fighter(3), LevelUpChoice(ability_increases={Ability.STR: 1}))


def test_asi_cannot_exceed_twenty():
    high = _fighter(3, abilities={Ability.STR: 19, Ability.DEX: 14, Ability.CON: 14,
                                  Ability.INT: 10, Ability.WIS: 12, Ability.CHA: 8})
    assert "exceed 20" in _why(high, LevelUpChoice(ability_increases={Ability.STR: 2}))


def test_asi_and_feat_are_mutually_exclusive():
    assert "not both" in _why(
        _fighter(3), LevelUpChoice(feat="grappler", ability_increases={Ability.STR: 2}))


def test_non_asi_level_rejects_improvements():
    assert "grants no ability score improvement" in _why(
        _fighter(1), LevelUpChoice(ability_increases={Ability.STR: 2}))


def test_rolled_hp_must_be_in_die_range():
    assert "must be 1–10" in _why(_fighter(1), LevelUpChoice(hp_method="roll", hp_roll=11))


def test_unknown_subclass_rejected():
    assert "unknown subclass" in _why(_fighter(2), LevelUpChoice(subclass="sharpshooter"))


def test_subclass_chosen_at_its_level_grants_features():
    leveled = level_up(_fighter(2), RS, LevelUpChoice(subclass="champion"))   # fighter picks at L3
    assert leveled.level == 3 and leveled.sheet.subclass == "champion"
    assert any(f.source == "subclass" for f in leveled.sheet.features)


def test_subclass_required_at_its_level():
    assert "requires choosing" in _why(_fighter(2), LevelUpChoice())   # L3 fighter must pick


def test_subclass_cannot_be_chosen_early():
    assert "does not choose a subclass until level 3" in _why(
        _fighter(1), LevelUpChoice(subclass="champion"))


def test_cannot_exceed_max_level():
    assert "maximum level" in _why(_fighter(20), LevelUpChoice())


# --- XP-driven advancement --------------------------------------------------
def test_xp_threshold_helpers():
    assert xp_for_level(1) == 0 and xp_for_level(2) == 300 and xp_for_level(20) == 355_000
    assert level_for_xp(0) == 1 and level_for_xp(299) == 1 and level_for_xp(300) == 2
    assert level_for_xp(900) == 3 and level_for_xp(10_000_000) == 20


def test_xp_progress_bar_math():
    p = xp_progress(_fighter(1, xp=150))          # halfway from 0 to 300
    assert p["floor"] == 0 and p["ceil"] == 300 and p["into"] == 150
    assert p["pct"] == 50 and p["needed"] == 150 and p["ready"] is False
    assert xp_progress(_fighter(1, xp=300))["ready"] is True      # banked enough for L2
    assert xp_progress(_fighter(20, xp=400_000))["is_max"] is True


def test_level_up_is_gated_on_xp():
    rookie = _fighter(1, xp=299)                   # 1 short of level 2
    plan = level_up_plan(rookie, RS)
    assert plan["can_level"] is False and "not enough experience" in plan["reason"]
    assert plan["xp"]["needed"] == 1
    with pytest.raises(LevelUpError) as ei:
        level_up(rookie, RS, LevelUpChoice())
    assert "not enough experience" in "\n".join(ei.value.errors)
    # one more XP and the gate opens
    assert level_up_plan(_fighter(1, xp=300), RS)["can_level"] is True


# --- the plan ---------------------------------------------------------------
def test_plan_flags_asi_levels():
    assert level_up_plan(_fighter(1), RS)["is_asi"] is False
    assert level_up_plan(_fighter(3), RS)["is_asi"] is True     # next level is 4
    assert level_up_plan(_fighter(20), RS)["can_level"] is False


# --- C3.x: learning spells on level-up (the leveled-paladin bug) -------------
def _paladin(level=1, cha=16, spells=None, **over) -> Character:
    base = dict(
        id="pc", name="Sera", kind="pc", level=level, hp=12, max_hp=12,
        xp=400_000,
        abilities={Ability.STR: 16, Ability.DEX: 10, Ability.CON: 14,
                   Ability.INT: 10, Ability.WIS: 12, Ability.CHA: cha},
        sheet=CharacterSheet(race="human", char_class="paladin", background="acolyte",
                             spellcasting_ability=Ability.CHA,
                             spells_known=spells or [], spells_prepared=spells or []),
    )
    base.update(over)
    return Character(**base)


def _bard(level=1) -> Character:
    return Character(
        id="pc", name="Lyre", kind="pc", level=level, hp=10, max_hp=10, xp=400_000,
        abilities={Ability.CHA: 16, Ability.DEX: 14, Ability.CON: 12,
                   Ability.STR: 8, Ability.INT: 10, Ability.WIS: 10},
        sheet=CharacterSheet(race="human", char_class="bard", background="acolyte",
                             spellcasting_ability=Ability.CHA,
                             cantrips_known=["dancing_lights", "light"],
                             spells_known=["bane", "charm_person",
                                           "cure_wounds", "detect_magic"]))


def test_paladin_gains_prepared_spells_at_level_two():
    """The reported bug: a leveled paladin arrived in the Arena spell-less.
    L2 is where paladin casting begins — the plan demands CHA mod + level/2
    picks and the build writes them to BOTH spells_known and spells_prepared."""
    plan = level_up_plan(_paladin(1), RS)
    sc = plan["spellcasting"]
    assert sc["spells_needed"] == 4              # CHA +3 + level 2 // 2, min 1
    assert sc["cantrips_needed"] == 0            # paladins have no cantrips
    assert sc["max_spell_level"] == 1
    assert sc["is_prepared_caster"] is True
    assert {"id": "bless", "name": "Bless", "level": 1} in sc["spell_options"]

    picks = ["bless", "cure_wounds", "shield_of_faith", "command"]
    leveled = level_up(_paladin(1), RS, LevelUpChoice(new_spells=picks))
    assert leveled.sheet.spells_known == picks
    assert leveled.sheet.spells_prepared == picks  # prepared casters: picks ARE the list


def test_leveled_paladin_spells_reach_the_arena():
    """End to end: the new prepared spells stage as Arena actions."""
    from oubliette.combat.arena_bridge import spell_actions

    leveled = level_up(_paladin(1), RS, LevelUpChoice(
        new_spells=["bless", "cure_wounds", "shield_of_faith", "command"]))
    names = {a.name for a in spell_actions(leveled)}
    assert {"Bless", "Cure Wounds", "Shield of Faith", "Command"} <= names


def test_known_caster_grows_spells_known_only():
    plan = level_up_plan(_bard(1), RS)
    sc = plan["spellcasting"]
    assert sc["spells_needed"] == 1 and sc["cantrips_needed"] == 0
    leveled = level_up(_bard(1), RS, LevelUpChoice(new_spells=["animal_friendship"]))
    assert "animal_friendship" in leveled.sheet.spells_known
    assert leveled.sheet.spells_prepared == []   # known casters never prepare


def test_spell_pick_firewall():
    # wrong count
    assert "calls for 4" in _why(_paladin(1), LevelUpChoice())
    # off-list / wrong class
    bad = ["fireball", "bless", "cure_wounds", "command"]
    assert "not a Paladin spell" in _why(_paladin(1), LevelUpChoice(new_spells=bad))
    # already on the sheet
    have = _paladin(2, spells=["bless", "cure_wounds", "shield_of_faith", "command"])
    msg = _why(have, LevelUpChoice(new_spells=["bless"]))
    assert "already on the sheet" in msg
    # non-casters pick nothing
    assert "not a spellcaster" in _why(
        _fighter(1), LevelUpChoice(new_spells=["bless"]))


def test_asi_into_the_casting_stat_owes_an_extra_prepared_pick():
    """L3->4 paladin, CHA 16 -> 18: prepared count 5 -> 6, so the ASI level
    demands two picks where a non-casting ASI would demand one."""
    pal = _paladin(3, spells=["bless", "cure_wounds", "shield_of_faith", "command"])
    msg = _why(pal, LevelUpChoice(ability_increases={Ability.CHA: 2},
                                  new_spells=["heroism"]))
    assert "calls for 2" in msg
    leveled = level_up(pal, RS, LevelUpChoice(
        ability_increases={Ability.CHA: 2},
        new_spells=["heroism", "divine_favor"]))
    assert len(leveled.sheet.spells_prepared) == 6


def test_catch_up_for_sheets_shorted_by_older_builds():
    """A paladin who leveled before spell-learning existed owes the FULL
    difference on the next level-up, not just the delta."""
    shorted = _paladin(2, spells=[])              # L2 with zero spells (the bug)
    plan = level_up_plan(shorted, RS)
    assert plan["spellcasting"]["spells_needed"] == 4   # mod 3 + 3//2 = 4 at L3
