"""CS1 — the derivation engine, checked against known SRD characters. Every number
here is one a player or DM could verify by hand against the rules; if the engine and
the rulebook ever disagree, the engine is wrong."""

from __future__ import annotations

from oubliette.content.ruleset import load_ruleset
from oubliette.enums import Ability, Skill
from oubliette.rules import derive
from oubliette.state.models import Character, CharacterSheet, Item

RS = load_ruleset()

CHAIN_MAIL = Item(id="chain_mail", name="Chain Mail", category="armor",
                  armor_class=16, armor_type="heavy")
SHIELD = Item(id="shield", name="Shield", category="armor", armor_class=2, armor_type="shield")
LEATHER = Item(id="leather_armor", name="Leather", category="armor",
               armor_class=11, armor_type="light")


def _fighter() -> Character:
    return Character(
        id="pc", name="Bron", kind="pc", level=1,
        abilities={Ability.STR: 16, Ability.DEX: 14, Ability.CON: 14,
                   Ability.INT: 10, Ability.WIS: 12, Ability.CHA: 8},
        skill_proficiencies={Skill.ATHLETICS, Skill.PERCEPTION},
        sheet=CharacterSheet(race="human", char_class="fighter", background="soldier",
                             saving_throw_proficiencies={Ability.STR, Ability.CON}),
    )


def _wizard() -> Character:
    return Character(
        id="pc", name="Mira", kind="pc", level=1,
        abilities={Ability.STR: 8, Ability.DEX: 14, Ability.CON: 12,
                   Ability.INT: 16, Ability.WIS: 13, Ability.CHA: 10},
        skill_proficiencies={Skill.ARCANA, Skill.INVESTIGATION},
        sheet=CharacterSheet(race="human", char_class="wizard", background="acolyte",
                             saving_throw_proficiencies={Ability.INT, Ability.WIS},
                             spellcasting_ability=Ability.INT),
    )


# --- AC ---------------------------------------------------------------------
def test_heavy_armor_and_shield():
    assert derive.armor_class(_fighter(), [CHAIN_MAIL, SHIELD]) == 18   # 16 + 2, no DEX


def test_light_armor_adds_full_dex():
    assert derive.armor_class(_fighter(), [LEATHER]) == 13              # 11 + DEX 2


def test_unarmored_is_ten_plus_dex():
    assert derive.armor_class(_wizard(), []) == 12                      # 10 + DEX 2


def test_monk_unarmored_defense_adds_wisdom():
    monk = Character(id="pc", name="Kai", kind="pc", level=1,
                     abilities={Ability.DEX: 16, Ability.WIS: 14},
                     sheet=CharacterSheet(race="human", char_class="monk", background="acolyte"))
    assert derive.armor_class(monk, []) == 15                           # 10 + DEX 3 + WIS 2
    # a shield switches off the monk's unarmored defense (per SRD): 10 + DEX + shield, no WIS
    assert derive.armor_class(monk, [SHIELD]) == 15                     # 10 + 3 + 2


# --- saves / skills / initiative --------------------------------------------
def test_saves_use_proficiency_when_proficient():
    f = _fighter()
    assert derive.save_modifier(f, Ability.STR) == 5     # +3 mod + 2 prof
    assert derive.save_modifier(f, Ability.DEX) == 2     # +2 mod, not proficient


def test_skill_modifier_and_passive():
    f = _fighter()
    assert derive.skill_modifier(f, Skill.ATHLETICS) == 5     # STR +3 + prof 2
    assert derive.skill_modifier(f, Skill.STEALTH) == 2       # DEX +2, not proficient
    assert derive.passive_skill(f, Skill.PERCEPTION) == 13    # 10 + (WIS +1 + prof 2)


def test_expertise_doubles_proficiency():
    f = _fighter()
    f.sheet.expertise = {Skill.ATHLETICS}
    assert derive.skill_modifier(f, Skill.ATHLETICS) == 7     # +3 + 2*2


def test_alert_feat_initiative():
    f = _fighter()
    assert derive.initiative(f) == 2
    f.sheet.feats = ["alert"]
    assert derive.initiative(f) == 7


# --- spellcasting -----------------------------------------------------------
def test_wizard_spell_dc_attack_and_slots():
    w = _wizard()
    assert derive.spell_save_dc(w) == 13          # 8 + prof 2 + INT 3
    assert derive.spell_attack_bonus(w) == 5      # prof 2 + INT 3
    assert derive.spell_slots(w, RS) == {1: 2}    # L1 full caster
    assert derive.cantrips_known(w, RS) == 3
    assert derive.prepared_spell_count(w, RS) == 4  # INT mod 3 + level 1


def test_fighter_has_no_spellcasting():
    f = _fighter()
    assert derive.spell_save_dc(f) is None
    assert derive.spell_slots(f, RS) == {}


def test_higher_level_wizard_slots():
    w = _wizard()
    w.level = 5
    assert derive.spell_slots(w, RS) == {1: 4, 2: 3, 3: 2}
    assert derive.prepared_spell_count(w, RS) == 8   # INT 3 + level 5


# --- HP ---------------------------------------------------------------------
def test_max_hp_level_1():
    assert derive.computed_max_hp(_fighter(), RS) == 12   # d10 + CON 2
    assert derive.computed_max_hp(_wizard(), RS) == 7     # d6 + CON 1


def test_max_hp_multi_level_average():
    f = _fighter()
    f.level = 3
    # 12 at L1, then +6 (avg d10=6 + CON 2) per level: 12 + 8 + 8 = wait
    # average_hp_per_level(10)=6; gain per level = 6 + CON 2 = 8 -> 12 + 8 + 8 = 28
    assert derive.computed_max_hp(f, RS) == 28


# --- racial ability application ---------------------------------------------
def test_final_abilities_apply_race_and_subrace():
    base = {Ability.STR: 15, Ability.DEX: 14, Ability.CON: 13,
            Ability.INT: 12, Ability.WIS: 10, Ability.CHA: 8}
    elf, high_elf = RS.races["elf"], RS.subraces["high_elf"]
    final = derive.final_abilities(base, elf, high_elf)
    assert final[Ability.DEX] == 16    # 14 + 2 (elf)
    assert final[Ability.INT] == 13    # 12 + 1 (high elf)
    assert final[Ability.STR] == 15    # unchanged


def test_human_boosts_everything():
    base = {a: 10 for a in Ability}
    final = derive.final_abilities(base, RS.races["human"])
    assert all(final[a] == 11 for a in Ability)


def test_sheet_stats_snapshot():
    stats = derive.sheet_stats(_fighter(), RS, [CHAIN_MAIL, SHIELD])
    assert stats["armor_class"] == 18
    assert stats["saves"]["str"] == 5
    assert stats["skills"]["athletics"] == 5
    assert stats["proficiency_bonus"] == 2


# --- hard classes (schema-stress) -------------------------------------------
def _barbarian(level: int = 1) -> Character:
    return Character(id="pc", name="Grog", kind="pc", level=level,
                     abilities={Ability.STR: 16, Ability.DEX: 14, Ability.CON: 16,
                                Ability.INT: 8, Ability.WIS: 12, Ability.CHA: 10},
                     sheet=CharacterSheet(race="human", char_class="barbarian", background="soldier"))


def _warlock(level: int = 1) -> Character:
    return Character(id="pc", name="Vex", kind="pc", level=level,
                     abilities={Ability.CHA: 16, Ability.DEX: 14, Ability.CON: 14, Ability.WIS: 10},
                     sheet=CharacterSheet(race="human", char_class="warlock", background="acolyte",
                                          spellcasting_ability=Ability.CHA))


def _sorcerer(level: int = 1) -> Character:
    return Character(id="pc", name="Tann", kind="pc", level=level,
                     abilities={Ability.CHA: 16, Ability.DEX: 14, Ability.CON: 13},
                     sheet=CharacterSheet(race="human", char_class="sorcerer", background="acolyte",
                                          spellcasting_ability=Ability.CHA))


def test_barbarian_unarmored_defense_uses_constitution():
    b = _barbarian()
    assert derive.armor_class(b, []) == 15            # 10 + DEX 2 + CON 3
    assert derive.armor_class(b, [SHIELD]) == 17      # barbarian KEEPS it with a shield


def test_barbarian_rage_resource_scales_and_goes_unlimited():
    assert derive.class_resources(_barbarian(1), RS)["Rage"] == {
        "max": 2, "recharge": "long", "unlimited": False}
    assert derive.class_resources(_barbarian(3), RS)["Rage"]["max"] == 3
    assert derive.class_resources(_barbarian(6), RS)["Rage"]["max"] == 4
    twenty = derive.class_resources(_barbarian(20), RS)["Rage"]
    assert twenty["max"] == -1 and twenty["unlimited"] is True


def test_warlock_pact_magic_slots_and_short_rest():
    assert derive.spell_slots(_warlock(1), RS) == {1: 1}
    assert derive.spell_slots(_warlock(3), RS) == {2: 2}
    assert derive.spell_slots(_warlock(5), RS) == {3: 2}
    assert derive.spell_slots(_warlock(11), RS) == {5: 3}
    assert derive.spell_slots(_warlock(17), RS) == {5: 4}
    assert derive.slots_recharge(_warlock(5), RS) == "short"   # pact magic recharges on a short rest
    assert derive.cantrips_known(_warlock(1), RS) == 2
    assert derive.prepared_spell_count(_warlock(5), RS) is None   # known caster, not prepared


def test_warlock_spell_dc_uses_charisma():
    assert derive.spell_save_dc(_warlock(1)) == 13     # 8 + prof 2 + CHA 3
    assert derive.spell_attack_bonus(_warlock(1)) == 5


def test_sorcerer_sorcery_points_and_full_slots():
    assert "Sorcery Points" not in derive.class_resources(_sorcerer(1), RS)   # none at level 1
    assert derive.class_resources(_sorcerer(5), RS)["Sorcery Points"]["max"] == 5
    assert derive.class_resources(_sorcerer(20), RS)["Sorcery Points"]["max"] == 20
    assert derive.spell_slots(_sorcerer(5), RS) == {1: 4, 2: 3, 3: 2}   # full caster
    assert derive.slots_recharge(_sorcerer(5), RS) == "long"
    assert derive.cantrips_known(_sorcerer(1), RS) == 4
