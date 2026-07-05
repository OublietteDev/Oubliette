"""CS2 — character creation, the firewall (design doc §6).

The validator is the whole point: a player makes choices, and the backend refuses
any build that breaks the rules (too many skills, overspent point-buy, spells off
your list, …) while computing every number itself. These tests pin both the
acceptances (a clean build assembles correctly) and the refusals (each rule bites),
plus the CHARACTER_CREATED event's record-then-replay round trip.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from oubliette.content.ruleset import load_ruleset
from oubliette.content.srd_schemas import Spell
from oubliette.enums import Ability, Skill
from oubliette.record.store import InMemoryEventStore
from oubliette.rules import derive
from oubliette.rules.chargen import (CharacterBuild, ChargenError,
                                     build_character)
from oubliette.runtime.session import Session

RS = load_ruleset()

# A wizard needs 3 cantrips but the content slice ships only 2 (CS4 fills the rest);
# inject one so the *successful caster* path is exercisable now.
_RS_W = replace(RS, spells={**RS.spells,
    "light": Spell(id="light", name="Light", level=0, school="evocation", classes=["wizard"])})

STD = {Ability.STR: 15, Ability.DEX: 14, Ability.CON: 13,
       Ability.INT: 12, Ability.WIS: 10, Ability.CHA: 8}


def _fighter(**over) -> CharacterBuild:
    base = dict(
        name="Bron", race="human", char_class="fighter", background="acolyte",
        ability_method="standard_array", base_abilities=dict(STD),
        skills=[Skill.PERCEPTION, Skill.SURVIVAL],     # acolyte already grants insight/religion
        languages=["Draconic", "Celestial"],           # acolyte grants 2 free languages
        race_languages=["Orc"],                        # human grants 1 extra language of choice
        equipment_choices=[[0], [0], [0]],             # chain mail; longsword+shield; light crossbow
    )
    base.update(over)
    return CharacterBuild(**base)


def _wizard(**over) -> CharacterBuild:
    base = dict(
        name="Mira", race="human", char_class="wizard", background="acolyte",
        ability_method="standard_array",
        base_abilities={Ability.INT: 15, Ability.DEX: 14, Ability.CON: 13,
                        Ability.WIS: 12, Ability.STR: 10, Ability.CHA: 8},
        skills=[Skill.ARCANA, Skill.INVESTIGATION],
        languages=["Draconic", "Celestial"],           # acolyte grants 2 free languages
        race_languages=["Orc"],                         # human grants 1 extra language of choice
        cantrips=["fire_bolt", "mage_hand", "light"],
        spells=["magic_missile", "shield", "burning_hands", "detect_magic"],
        equipment_choices=[[1]],                        # dagger
    )
    base.update(over)
    return CharacterBuild(**base)


# --- a clean build assembles correctly ---------------------------------------
def test_fighter_build_is_fully_derived():
    char, items = build_character(_fighter(), RS)
    # racial bonuses applied (human +1 to all)
    assert char.abilities[Ability.STR] == 16 and char.abilities[Ability.CON] == 14
    # code owns the numbers
    assert char.max_hp == 12 and char.hp == 12            # d10 + CON 2
    assert char.armor_class == 18                          # chain mail 16 + shield 2
    assert char.attack_bonus == 5                          # prof 2 + STR 3
    assert char.damage == "1d8"                            # longsword
    # proficiencies = class picks + background grants
    assert char.skill_proficiencies == {Skill.PERCEPTION, Skill.SURVIVAL,
                                         Skill.INSIGHT, Skill.RELIGION}
    assert char.sheet.saving_throw_proficiencies == {Ability.STR, Ability.CON}
    # gear: explorer's pack granted twice (class fixed + background) → qty 2
    assert char.item_qty("explorers_pack") == 2
    assert set(char.equipped) == {"chain_mail", "shield", "longsword"}
    assert char.coin == 15_00      # acolyte's 15 gp grant, in copper
    # the granted SRD gear is handed back for catalog registration
    assert {it.id for it in items} == {"explorers_pack", "chain_mail", "longsword",
                                       "shield", "light_crossbow"}
    # features carry their source + text (no ruleset lookup needed to render them)
    names = {(f.source, f.name) for f in char.sheet.features}
    assert ("class", "Second Wind") in names
    assert ("background", "Shelter of the Faithful") in names


def test_subrace_traits_and_abilities_fold_in():
    # base _fighter supplies 1 race_language ("Orc") — High Elf grants exactly 1.
    char, _ = build_character(
        _fighter(race="elf", subrace="high_elf", race_cantrips=["fire_bolt"]), RS)
    assert char.abilities[Ability.DEX] == 16    # base 14 + elf 2
    assert char.abilities[Ability.INT] == 13    # base 12 + high-elf 1
    assert "Elvish" in char.sheet.languages and "Orc" in char.sheet.languages   # high-elf extra
    assert "fire_bolt" in char.sheet.cantrips_known                              # high-elf cantrip
    sources = {f.source for f in char.sheet.features}
    assert "race" in sources and "subrace" in sources


def test_caster_spells_land_on_the_sheet():
    char, _ = build_character(_wizard(), _RS_W)
    assert char.sheet.spellcasting_ability == Ability.INT
    assert set(char.sheet.cantrips_known) == {"fire_bolt", "mage_hand", "light"}
    # prepared casters fill spells_prepared (INT mod 3 + level 1 = 4)
    assert len(char.sheet.spells_prepared) == 4
    assert derive.spell_save_dc(char) == 13     # 8 + prof 2 + INT 3


def test_point_buy_and_roll_methods_accepted():
    pb = _fighter(ability_method="point_buy",
                  base_abilities={Ability.STR: 15, Ability.DEX: 15, Ability.CON: 15,
                                  Ability.INT: 8, Ability.WIS: 8, Ability.CHA: 8})  # 27 pts
    assert build_character(pb, RS)[0].sheet.ability_method == "point_buy"
    rolled = _fighter(ability_method="roll",
                      base_abilities={Ability.STR: 17, Ability.DEX: 16, Ability.CON: 15,
                                      Ability.INT: 12, Ability.WIS: 11, Ability.CHA: 9})
    assert build_character(rolled, RS)[0].abilities[Ability.STR] == 18   # 17 + human 1


# --- the firewall refuses bad builds -----------------------------------------
def _why(build, ruleset=RS) -> str:
    with pytest.raises(ChargenError) as ei:
        build_character(build, ruleset)
    return "\n".join(ei.value.errors)


def test_unknown_references_are_rejected():
    # warlord is not an SRD class (all 12 real classes now load via CS4)
    errs = _why(_fighter(char_class="warlord", race="orc", background="pirate"))
    assert "unknown class 'warlord'" in errs
    assert "unknown race 'orc'" in errs
    assert "unknown background 'pirate'" in errs


def test_paladin_half_caster_needs_no_spells_at_level_1():
    """Regression (CS4): a half caster has no spellcasting at level 1, so chargen must
    require ZERO prepared spells even with positive Charisma. derive.prepared_spell_count
    gates on actually having slots; the paladin assembles spell-less and wears its kit."""
    build = CharacterBuild(
        name="Greer", race="human", char_class="paladin", background="acolyte",
        ability_method="standard_array",
        base_abilities={Ability.STR: 15, Ability.CHA: 14, Ability.CON: 13,
                        Ability.DEX: 12, Ability.WIS: 10, Ability.INT: 8},
        skills=[Skill.ATHLETICS, Skill.PERSUASION],
        languages=["Celestial", "Abyssal"], race_languages=["Orc"],
        equipment_choices=[[0], [0], [0]],     # longsword+shield; 5 javelins; priest's pack
    )
    char, _ = build_character(build, RS)
    assert derive.prepared_spell_count(char, RS) == 0
    assert char.armor_class == 18              # chain mail 16 + shield 2


def test_standard_array_must_match_exactly():
    bad = _fighter(base_abilities={**STD, Ability.STR: 18})   # 18 isn't in the array
    assert "standard array must assign" in _why(bad)


def test_point_buy_budget_enforced():
    over = _fighter(ability_method="point_buy",
                    base_abilities={a: 15 for a in Ability})   # 54 points
    assert "point-buy overspent" in _why(over)


def test_rolled_scores_must_be_in_range():
    bad = _fighter(ability_method="roll", base_abilities={**STD, Ability.STR: 19})
    assert "rolled scores must be 3–18" in _why(bad)


def test_cannot_pick_too_many_or_off_list_skills():
    too_many = _fighter(skills=[Skill.PERCEPTION, Skill.SURVIVAL, Skill.ATHLETICS])
    assert "picks 2, got 3" in _why(too_many)
    off_list = _fighter(skills=[Skill.PERCEPTION, Skill.ARCANA])   # arcana not a fighter option
    assert "is not a Fighter skill option" in _why(off_list)


def test_cannot_duplicate_a_background_skill():
    dup = _fighter(skills=[Skill.PERCEPTION, Skill.INSIGHT])   # acolyte already grants insight
    assert "already granted by your background" in _why(dup)


# --- race choices: flexible ASI, bonus skills, extra languages (Half-Elf, Human) ---
def _half_elf(**over) -> CharacterBuild:
    base = dict(
        name="Aria", race="half_elf", char_class="fighter", background="acolyte",
        ability_method="standard_array", base_abilities=dict(STD),
        skills=[Skill.PERCEPTION, Skill.SURVIVAL],
        race_ability_choices=[Ability.DEX, Ability.CON],   # Half-Elf: +1 to two OTHER abilities
        race_skills=[Skill.STEALTH, Skill.ATHLETICS],      # Skill Versatility: any two
        languages=["Draconic", "Celestial"],               # acolyte's two
        race_languages=["Orc"],                            # Half-Elf's one extra
        equipment_choices=[[0], [0], [0]],
    )
    base.update(over)
    return CharacterBuild(**base)


def test_half_elf_choices_apply():
    char, _ = build_character(_half_elf(), RS)
    assert char.abilities[Ability.CHA] == 10      # 8 + 2 fixed
    assert char.abilities[Ability.DEX] == 15      # 14 + 1 chosen
    assert char.abilities[Ability.CON] == 14      # 13 + 1 chosen
    assert {Skill.STEALTH, Skill.ATHLETICS} <= char.skill_proficiencies
    assert "Orc" in char.sheet.languages and "Elvish" in char.sheet.languages


def test_half_elf_ability_choice_must_be_other():
    # "two OTHER ability scores of your choice" — can't stack the +1 onto the fixed CHA
    assert "already increased" in _why(_half_elf(race_ability_choices=[Ability.CHA, Ability.DEX]))


def test_half_elf_ability_choice_count_enforced():
    assert "raises 2 ability" in _why(_half_elf(race_ability_choices=[Ability.DEX]))


def test_half_elf_skill_choice_count_and_dups_enforced():
    assert "grants 2" in _why(_half_elf(race_skills=[Skill.STEALTH]))
    assert "already granted" in _why(_half_elf(race_skills=[Skill.INSIGHT, Skill.STEALTH]))


def test_human_requires_its_extra_language():
    assert "language(s) of choice" in _why(_fighter(race_languages=[]))


def _high_elf(**over) -> CharacterBuild:
    base = dict(race="elf", subrace="high_elf", race_cantrips=["fire_bolt"])
    base.update(over)
    return _fighter(**base)   # base _fighter already supplies 1 race_language for High Elf's grant


def test_high_elf_bonus_cantrip_count_and_list_enforced():
    assert "grants 1" in _why(_high_elf(race_cantrips=[]))                    # wrong count
    assert "not a wizard cantrip" in _why(_high_elf(race_cantrips=["made_up"]))  # off the list


def test_non_caster_cannot_take_spells():
    assert "not a spellcaster" in _why(_fighter(cantrips=["fire_bolt"]))


def test_caster_cantrip_count_and_spell_list_enforced():
    # only 2 wizard cantrips exist in the slice → count is wrong, and a level-1
    # spell offered as a cantrip is refused
    short = _wizard(cantrips=["fire_bolt", "mage_hand"], spells=[])  # against real RS
    errs = _why(short)
    assert "knows 3 at level 1, got 2" in errs
    off = _wizard(cantrips=["fire_bolt", "mage_hand", "magic_missile"],  # level-1 spell, not a cantrip
                  spells=["shield", "burning_hands", "detect_magic", "fire_bolt"])
    errs2 = _why(off)
    assert "is not a Wizard cantrip" in errs2


def test_subrace_required_and_must_match_race():
    assert "requires a subrace" in _why(_fighter(race="elf"))            # elf needs one
    assert "does not belong to race" in _why(_fighter(race="elf", subrace="hill_dwarf"))


def test_subclass_not_offered_at_level_one():
    # fighter chooses its archetype at level 3, not creation
    assert "does not choose a subclass until level 3" in _why(
        _fighter(subclass="champion")) or "unknown subclass" in _why(_fighter(subclass="champion"))


def test_equipment_choices_must_be_complete_and_in_range():
    assert "choice(s) to make" in _why(_fighter(equipment_choices=[[0]]))   # fighter has 3
    assert "out of range" in _why(_fighter(equipment_choices=[[9], [0], [0]]))


def test_language_count_must_match_background():
    assert "background grants 2 free language" in _why(_wizard(languages=["Draconic"]), _RS_W)


def test_errors_aggregate():
    # two independent violations reported together: missing subrace + a bad array
    errs = _why(_fighter(race="elf", base_abilities={**STD, Ability.STR: 18}))
    assert "requires a subrace" in errs
    assert "standard array must assign" in errs
    assert len(errs.splitlines()) >= 2


# --- the event: record, then replay byte-identically -------------------------
def _snapshot(repo) -> dict:
    pc = repo.pc()
    return {
        "char": pc.model_dump(mode="json"),
        "catalog": sorted(repo.get_item(i).id for i in
                          ("chain_mail", "longsword", "shield")),
    }


def test_character_created_event_round_trips():
    store = InMemoryEventStore()
    live = Session.open(store)              # default pack carries the SRD ruleset
    char = live.emit_character_created(_fighter())

    assert live.repo.pc().id == "pc" and live.repo.pc().name == "Bron"
    assert live.repo.pc().max_hp == 12
    assert live.repo.get_item("chain_mail").armor_type == "heavy"   # SRD gear registered
    live_snap = _snapshot(live.repo)

    # reload from the same log: seed the pack baseline + replay → must match exactly,
    # and the default-party stopgap PC must be gone (replaced, not duplicated)
    reloaded = Session.open(store)
    assert _snapshot(reloaded.repo) == live_snap
    assert len(reloaded.repo.party()) == 1
    assert reloaded.repo.pc().name == "Bron"
