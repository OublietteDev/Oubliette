"""CS6 — the DM's mechanical 'character card' baked into build_context. The card
gives the DM who the character IS (class, training, features, spells) so it can
call for the right check/save, WITHOUT dumping the full sheet. It must degrade
gracefully when there is no ruleset and emit nothing for a sheet-less hero."""

from __future__ import annotations

from oubliette.content.ruleset import load_ruleset
from oubliette.dm.context import build_context
from oubliette.enums import Ability, Skill
from oubliette.state.models import Character, CharacterSheet, FeatureRef
from oubliette.state.repository import InMemoryRepository

RS = load_ruleset()


def _repo(pc: Character) -> InMemoryRepository:
    return InMemoryRepository([pc], [], pc.id)


def _rogue() -> Character:
    return Character(
        id="pc", name="Vex", kind="pc", level=3,
        abilities={Ability.STR: 10, Ability.DEX: 16, Ability.CON: 12,
                   Ability.INT: 13, Ability.WIS: 11, Ability.CHA: 14},
        skill_proficiencies={Skill.STEALTH, Skill.ACROBATICS},
        sheet=CharacterSheet(
            race="human", char_class="rogue", background="criminal",
            saving_throw_proficiencies={Ability.DEX, Ability.INT},
            expertise={Skill.STEALTH},
            weapon_proficiencies=["simple", "shortsword"],
            languages=["Common", "Thieves' Cant"],
            features=[FeatureRef(name="Sneak Attack", source="class"),
                      FeatureRef(name="Cunning Action", source="class")],
        ),
    )


def _wizard() -> Character:
    return Character(
        id="pc", name="Mira", kind="pc", level=1,
        abilities={Ability.STR: 8, Ability.DEX: 14, Ability.CON: 12,
                   Ability.INT: 16, Ability.WIS: 13, Ability.CHA: 10},
        skill_proficiencies={Skill.ARCANA},
        sheet=CharacterSheet(
            race="human", char_class="wizard", background="acolyte",
            saving_throw_proficiencies={Ability.INT, Ability.WIS},
            spellcasting_ability=Ability.INT,
            cantrips_known=["fire_bolt"],
            spells_prepared=["magic_missile"],
        ),
    )


def test_melee_card_shows_identity_and_proficient_skills_only():
    ctx = build_context(_repo(_rogue()), "a scene", ruleset=RS)
    assert "CHARACTER SHEET" in ctx
    assert "level 3" in ctx and "rogue" in ctx.lower()        # class display name
    # proficient skill with its mod + expertise: DEX +3, prof +2, expertise +2 → +7
    assert "Stealth +7 (expertise)" in ctx
    assert "Sneak Attack" in ctx                              # a feature, by name
    # untrained skills are omitted — the whole point of a compact 'card'
    assert "Intimidation" not in ctx and "Survival" not in ctx


def test_caster_card_shows_save_dc_slots_and_spell_names():
    ctx = build_context(_repo(_wizard()), "a scene", ruleset=RS)
    assert "Spellcasting (INT)" in ctx
    assert "save DC 13" in ctx                                # 8 + prof 2 + INT 3
    assert "slots 1st: 2" in ctx                              # SRD wizard at level 1
    line = next(ln for ln in ctx.splitlines() if "Spellcasting" in ln)
    assert "fire_bolt" in line or "Fire Bolt" in line        # by name (id until CS4 fills)
    assert "magic_missile" in line or "Magic Missile" in line


def test_card_without_ruleset_keeps_numbers_but_drops_slots():
    ctx = build_context(_repo(_wizard()), "a scene")         # ruleset=None
    assert "CHARACTER SHEET" in ctx
    assert "save DC 13" in ctx                                # needs only the character
    assert "Abilities:" in ctx
    assert "slots" not in ctx                                 # slot pool needs the ruleset
    assert "wizard" in ctx                                    # name falls back to the sheet id


def test_sheetless_pc_emits_no_card():
    hero = Character(id="pc", name="Quickstart", kind="pc", level=1,
                     abilities={Ability.STR: 12})
    ctx = build_context(_repo(hero), "a scene", ruleset=RS)
    assert "CHARACTER SHEET" not in ctx
    assert "Quickstart" in ctx                                # still on the PARTY line
