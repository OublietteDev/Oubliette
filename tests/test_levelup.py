"""CS5 — the level-up builder. The player chooses (HP method, ASI/feat, subclass);
the builder validates against the rules and rebuilds the character one level higher,
carrying protected state over untouched."""

from __future__ import annotations

import pytest

from oubliette.content.ruleset import load_ruleset
from oubliette.enums import Ability
from oubliette.rules.levelup import LevelUpChoice, LevelUpError, level_up, level_up_plan
from oubliette.state.models import Character, CharacterSheet, ItemStack

RS = load_ruleset()


def _fighter(level=1, **over) -> Character:
    base = dict(
        id="pc", name="Bron", kind="pc", level=level, hp=12, max_hp=12, gold=10,
        abilities={Ability.STR: 16, Ability.DEX: 14, Ability.CON: 14,
                   Ability.INT: 10, Ability.WIS: 12, Ability.CHA: 8},
        inventory=[ItemStack(item_id="longsword", qty=1)],
        sheet=CharacterSheet(race="human", char_class="fighter", background="soldier",
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
    leveled = level_up(_fighter(3), RS, LevelUpChoice(feat="resilient"))
    assert leveled.abilities[Ability.CON] == 15            # resilient bumps CON +1
    assert "resilient" in leveled.sheet.feats
    assert any(f.source == "feat" and f.name == "Resilient" for f in leveled.sheet.features)


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
        _fighter(3), LevelUpChoice(feat="resilient", ability_increases={Ability.STR: 2}))


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


# --- the plan ---------------------------------------------------------------
def test_plan_flags_asi_levels():
    assert level_up_plan(_fighter(1), RS)["is_asi"] is False
    assert level_up_plan(_fighter(3), RS)["is_asi"] is True     # next level is 4
    assert level_up_plan(_fighter(20), RS)["can_level"] is False
