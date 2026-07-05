"""Shared chargen *presentation* — the projections both character-creation
wizards render from.

`chargen_options(rs)` turns a `Ruleset` into everything the wizard needs to draw
its pickers (classes/races/backgrounds/spell lists/ability methods); pure SRD,
nothing hardcoded in the browser. `preview_payload(char, items, rs)` renders a
freshly `build_character`'d `Character` into the live derived-stats preview.

Both are pure functions of their inputs — no session, no app state — so the play
app (`oubliette.app.server`) and the Forge (`oubliette.creator.server`) drive
chargen from ONE source of truth instead of two copies that drift. (The small
display helpers below are intentionally local so this module has no dependency on
either server.)
"""

from __future__ import annotations

from ..coin import format_cp
from ..content.ruleset import Ruleset
from ..enums import Ability, Skill
from ..state.models import Character, CharacterSheet
from . import derive
from .chargen import POINT_BUY_BUDGET, POINT_BUY_COST, STANDARD_ARRAY

_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th",
             6: "6th", 7: "7th", 8: "8th", 9: "9th"}


def item_name(rs: Ruleset, item_id: str) -> str:
    it = rs.equipment.get(item_id)
    return it.name if it is not None else item_id


def spell_name(rs: Ruleset, spell_id: str | None) -> str | None:
    """Display name for a spell id; a title-cased fallback keeps an authored spell
    not in the SRD ruleset reading cleanly."""
    if not spell_id:
        return None
    s = rs.spells.get(spell_id)
    return s.name if s is not None else spell_id.replace("_", " ").title()


def stack_label(rs: Ruleset, stack) -> str:
    """An inventory line, annotated with a scroll's inscribed spell + cast level
    (e.g. 'Spell Scroll: Fireball (5th-level)')."""
    base = item_name(rs, stack.item_id)
    sp = spell_name(rs, stack.spell)
    if not sp:
        return base
    lvl = getattr(stack, "spell_level", None)
    if lvl:                                    # 0 (cantrip) and None both read plainly
        return f"{base}: {sp} ({_ORDINALS.get(lvl, str(lvl))}-level)"
    return f"{base}: {sp}"


def grant_view(rs: Ruleset, grants) -> list[dict]:
    return [{"item": g.item, "name": item_name(rs, g.item), "qty": g.qty} for g in grants]


def class_view(rs: Ruleset, cc) -> dict:
    """One class, with everything the wizard needs to render its choices and the
    level-1 caster facts (the counts the firewall enforces). Prepared-caster spell
    counts depend on the chosen ability, so the client computes those and /preview
    is the final word — here we just flag preparation mode."""
    temp = Character(id="_", name="_", kind="pc", level=1,
                     sheet=CharacterSheet(race="_", char_class=cc.id, background="_",
                                          spellcasting_ability=(Ability(cc.spellcasting.ability)
                                                                if cc.spellcasting else None)))
    sc = cc.spellcasting
    return {
        "id": cc.id, "name": cc.name, "hit_die": cc.hit_die,
        "saving_throws": list(cc.saving_throws),
        "skill_choose": cc.skill_choices.choose, "skill_from": list(cc.skill_choices.from_),
        "subclass_level": cc.subclass_level, "subclass_label": cc.subclass_label,
        "is_caster": sc is not None,
        "caster_prep": (sc.preparation if sc else None),
        "spell_ability": (sc.ability if sc else None),
        "cantrips_at_1": derive.cantrips_known(temp, rs) or 0,
        "spells_known_at_1": (None if sc and sc.preparation == "prepared"
                              else derive.spells_known_count(temp, rs)),
        "max_spell_level": max(derive.spell_slots(temp, rs), default=0),
        "equipment": {
            "fixed": grant_view(rs, cc.starting_equipment.fixed),
            "choices": [{"choose": ch.choose,
                         "options": [grant_view(rs, opt) for opt in ch.options]}
                        for ch in cc.starting_equipment.choices],
        },
        "subclasses": [{"id": s.id, "name": s.name} for s in rs.subclasses_for(cc.id)],
    }


def chargen_options(rs: Ruleset) -> dict:
    """Everything the chargen wizard renders, straight from the ruleset (no SRD
    data hardcoded in the browser)."""
    classes = [class_view(rs, cc) for cc in rs.classes.values()]
    races = [{
        "id": r.id, "name": r.name, "speed": r.speed, "size": r.size,
        "ability_increases": dict(r.ability_increases),
        "ability_score_choices": ({"choose": r.ability_score_choices.choose,
                                   "amount": r.ability_score_choices.amount}
                                  if r.ability_score_choices else None),
        "languages": list(r.languages),
        "language_choices": r.language_choices,
        "skill_choices": {"choose": r.skill_choices.choose, "from": list(r.skill_choices.from_)},
        "subraces": [{"id": s.id, "name": s.name,
                      "ability_increases": dict(s.ability_increases),
                      "language_choices": s.language_choices,
                      "bonus_cantrips": ({"choose": s.bonus_cantrips.choose,
                                          "spell_list": s.bonus_cantrips.spell_list}
                                         if s.bonus_cantrips else None)}
                     for s in rs.subraces_for(r.id)],
    } for r in rs.races.values()]
    backgrounds = [{
        "id": b.id, "name": b.name, "skills": list(b.skill_proficiencies),
        "languages": b.languages, "tool_proficiencies": list(b.tool_proficiencies),
        "starting_gold": b.starting_gold,
        "equipment": grant_view(rs, b.equipment),
        "feature": ({"name": b.feature.name, "text": b.feature.text} if b.feature else None),
        "flavor": {"personality_traits": list(b.personality_traits), "ideals": list(b.ideals),
                   "bonds": list(b.bonds), "flaws": list(b.flaws)},
    } for b in rs.backgrounds.values()]
    spells_by_class: dict = {}
    for cc in rs.classes.values():
        spells = rs.spells_for(cc.id)
        spells_by_class[cc.id] = {
            "cantrips": [{"id": s.id, "name": s.name} for s in spells if s.level == 0],
            "leveled": [{"id": s.id, "name": s.name, "level": s.level} for s in spells if s.level >= 1],
        }
    return {
        "classes": classes, "races": races, "backgrounds": backgrounds,
        "spells_by_class": spells_by_class,
        "abilities": [a.value for a in Ability],
        "skills": [s.value for s in Skill],
        "standard_array": STANDARD_ARRAY,
        "point_buy": {"budget": POINT_BUY_BUDGET, "cost": POINT_BUY_COST},
    }


def preview_payload(char: Character, items, rs: Ruleset) -> dict:
    """A built character rendered for the wizard's live preview — every number
    code-derived, the whole point of the project."""
    by_id = {it.id: it for it in items}
    equipped_items = [by_id[i] for i in char.equipped if i in by_id]
    return {
        "name": char.name,
        "abilities": {a.value: char.abilities.get(a, 10) for a in Ability},
        "max_hp": char.max_hp, "speed": char.sheet.speed, "size": char.sheet.size,
        "coin_text": format_cp(char.coin),   # the hero's chargen grant (joins the party purse)
        "derived": derive.sheet_stats(char, rs, equipped_items),
        "inventory": [{"name": stack_label(rs, s), "qty": s.qty} for s in char.inventory],
        "equipped": [item_name(rs, i) for i in char.equipped],
        "features": [{"source": f.source, "name": f.name, "text": f.text}
                     for f in char.sheet.features],
        "cantrips": [spell_name(rs, s) for s in char.sheet.cantrips_known],
        "spells": [spell_name(rs, s) for s in char.sheet.spells_prepared or char.sheet.spells_known],
    }
