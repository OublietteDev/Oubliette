"""The derivation engine (design doc §5): every code-owned number on a PC's sheet,
computed from the build (`CharacterSheet`) + equipped items + the SRD `Ruleset`.

Pure functions — replay-safe and unit-tested against known SRD characters. Stored
= the player's *choices* + protected mutable state; derived = recomputed here,
never trusted from the wire. This is where "code owns the numbers" becomes real.

Spell/feature EFFECT resolution is out of scope until the combat arc (decision §1);
this module only computes the static sheet values.
"""

from __future__ import annotations

from ..content.ruleset import Ruleset
from ..enums import SKILL_ABILITY, Ability, Skill
from ..state.models import Character, Item

# Classes whose unarmored AC adds a second ability modifier (Unarmored Defense).
_UNARMORED_DEFENSE: dict[str, Ability] = {"barbarian": Ability.CON, "monk": Ability.WIS}


def _akey(a) -> Ability:
    return a if isinstance(a, Ability) else Ability(a)


# --- ability scores ----------------------------------------------------------
def final_abilities(base: dict, race=None, subrace=None) -> dict[Ability, int]:
    """Apply racial + subracial ability increases to the chosen base scores. The
    result is what gets written to `Character.abilities` at creation."""
    out = {a: 10 for a in Ability}
    for k, v in (base or {}).items():
        out[_akey(k)] = v
    for src in (race, subrace):
        if src is None:
            continue
        for k, v in src.ability_increases.items():
            out[_akey(k)] = out.get(_akey(k), 10) + v
    return out


# --- saves, skills, initiative ----------------------------------------------
def save_modifier(char: Character, ability: Ability) -> int:
    mod = char.ability_mod(ability)
    if char.sheet and ability in char.sheet.saving_throw_proficiencies:
        mod += char.proficiency_bonus
    return mod


def skill_modifier(char: Character, skill: Skill) -> int:
    mod = char.ability_mod(SKILL_ABILITY[skill])
    pb = char.proficiency_bonus
    if skill in char.skill_proficiencies:
        mod += pb
        if char.sheet and skill in char.sheet.expertise:
            mod += pb                       # expertise doubles the proficiency bonus
    return mod


def passive_skill(char: Character, skill: Skill) -> int:
    return 10 + skill_modifier(char, skill)


def initiative(char: Character) -> int:
    init = char.ability_mod(Ability.DEX)
    if char.sheet and "alert" in char.sheet.feats:
        init += 5
    return init


# --- armor class -------------------------------------------------------------
def armor_class(char: Character, equipped_items: list[Item]) -> int:
    """AC from worn armor + shield + DEX (per armor type) or Unarmored Defense."""
    dex = char.ability_mod(Ability.DEX)
    body = next((i for i in equipped_items
                 if i.armor_type in ("light", "medium", "heavy")), None)
    shield = sum((i.armor_class or 0) for i in equipped_items if i.armor_type == "shield")

    if body is None:
        base = 10 + dex
        cls = char.sheet.char_class if char.sheet else None
        extra = _UNARMORED_DEFENSE.get(cls)
        if extra is not None and not (cls == "monk" and shield):  # monk loses it with a shield
            base += char.ability_mod(extra)
        return base + shield

    base = body.armor_class or 10
    if body.armor_type == "light":
        base += dex
    elif body.armor_type == "medium":
        cap = body.dex_cap if body.dex_cap is not None else 2
        base += min(dex, cap)
    # heavy: no DEX bonus
    return base + shield


# --- hit points / hit dice ---------------------------------------------------
def average_hp_per_level(hit_die: int) -> int:
    """SRD fixed-HP-per-level: the average die value rounded up."""
    return hit_die // 2 + 1


def computed_max_hp(char: Character, ruleset: Ruleset, rolls: list[int] | None = None) -> int | None:
    """Max HP by the rules: full hit die at level 1 + CON each level, plus the
    average (or rolled) die per level after. Feature HP bonuses (Tough, Hill Dwarf)
    are layered in CS5. Returns None for a sheet-less character."""
    cc = _class(char, ruleset)
    if cc is None:
        return None
    hd, con = cc.hit_die, char.ability_mod(Ability.CON)
    total = hd + con
    for lvl in range(2, char.level + 1):
        gain = (rolls[lvl - 2] if rolls else average_hp_per_level(hd)) + con
        total += max(1, gain)
    return total


# --- spellcasting ------------------------------------------------------------
def _class(char: Character, ruleset: Ruleset):
    if not char.sheet:
        return None
    return ruleset.classes.get(char.sheet.char_class)


def spell_save_dc(char: Character) -> int | None:
    sa = char.sheet.spellcasting_ability if char.sheet else None
    return None if sa is None else 8 + char.proficiency_bonus + char.ability_mod(sa)


def spell_attack_bonus(char: Character) -> int | None:
    sa = char.sheet.spellcasting_ability if char.sheet else None
    return None if sa is None else char.proficiency_bonus + char.ability_mod(sa)


def _vancian_row(char: Character, ruleset: Ruleset):
    cc = _class(char, ruleset)
    if cc is None or not cc.spell_progression:
        return None
    return next((r for r in cc.spell_progression if r.level == char.level), None)


def _pact_row(char: Character, ruleset: Ruleset):
    cc = _class(char, ruleset)
    if cc is None or not cc.pact_magic_progression:
        return None
    return next((r for r in cc.pact_magic_progression if r.level == char.level), None)


def _is_pact(char: Character, ruleset: Ruleset) -> bool:
    cc = _class(char, ruleset)
    return bool(cc and cc.spellcasting and cc.spellcasting.caster_type == "pact")


def spell_slots(char: Character, ruleset: Ruleset) -> dict[int, int]:
    """Max spell slots by spell level. Warlock Pact Magic returns its single-level
    pool (e.g. {3: 2}); every other caster returns the Vancian table row."""
    if _is_pact(char, ruleset):
        row = _pact_row(char, ruleset)
        return {row.slot_level: row.slots} if row and row.slots else {}
    row = _vancian_row(char, ruleset)
    if row is None:
        return {}
    return {i + 1: n for i, n in enumerate(row.spell_slots) if n}


def slots_recharge(char: Character, ruleset: Ruleset) -> str:
    """Which rest restores spell slots: 'short' for pact magic, 'long' otherwise."""
    return "short" if _is_pact(char, ruleset) else "long"


def cantrips_known(char: Character, ruleset: Ruleset) -> int | None:
    row = _vancian_row(char, ruleset) or _pact_row(char, ruleset)
    return row.cantrips_known if row is not None else None


def prepared_spell_count(char: Character, ruleset: Ruleset) -> int | None:
    """For 'prepared' casters: ability modifier + class level (min 1). 'Known' casters
    (and pact casters) return None — they don't prepare."""
    cc = _class(char, ruleset)
    if cc is None or not cc.spellcasting or cc.spellcasting.preparation != "prepared":
        return None
    return max(1, char.ability_mod(_akey(cc.spellcasting.ability)) + char.level)


def spells_known_count(char: Character, ruleset: Ruleset) -> int | None:
    """How many leveled spells the caster has access to at its current level —
    the count chargen enforces. 'Prepared' casters → prepared_spell_count (mod +
    level); 'known'/pact casters → the progression table's spells_known. None for
    non-casters (the firewall then forbids any leveled-spell picks)."""
    cc = _class(char, ruleset)
    if cc is None or cc.spellcasting is None:
        return None
    if cc.spellcasting.preparation == "prepared":
        return prepared_spell_count(char, ruleset)
    row = _vancian_row(char, ruleset) or _pact_row(char, ruleset)
    return row.spells_known if row is not None else None


def _resource_at(by_level: dict[int, int], level: int) -> int:
    """The amount in effect at `level`: the value of the highest listed level <= it
    (0 if none). A -1 (unlimited) passes straight through."""
    applicable = [lv for lv in by_level if lv <= level]
    return by_level[max(applicable)] if applicable else 0


def class_resources(char: Character, ruleset: Ruleset) -> dict[str, dict]:
    """Leveled class-resource maxima at the character's level — sorcery points, ki,
    rage, channel divinity: {name: {max, recharge, unlimited}}."""
    cc = _class(char, ruleset)
    if cc is None:
        return {}
    out: dict[str, dict] = {}
    for res in cc.resources:
        amt = _resource_at(res.by_level, char.level)
        if amt != 0:
            out[res.name] = {"max": amt, "recharge": res.recharge, "unlimited": amt == -1}
    return out


# --- a full snapshot for the sheet / API / DM context ------------------------
def sheet_stats(char: Character, ruleset: Ruleset, equipped_items: list[Item]) -> dict:
    """Everything derived, ready to render — the read-only mechanical sheet."""
    return {
        "proficiency_bonus": char.proficiency_bonus,
        "armor_class": armor_class(char, equipped_items),
        "initiative": initiative(char),
        "ability_mods": {a.value: char.ability_mod(a) for a in Ability},
        "saves": {a.value: save_modifier(char, a) for a in Ability},
        "skills": {s.value: skill_modifier(char, s) for s in Skill},
        "passive_perception": passive_skill(char, Skill.PERCEPTION),
        "spell_save_dc": spell_save_dc(char),
        "spell_attack_bonus": spell_attack_bonus(char),
        "spell_slots": spell_slots(char, ruleset),
        "spell_slots_recharge": slots_recharge(char, ruleset),
        "cantrips_known": cantrips_known(char, ruleset),
        "prepared_count": prepared_spell_count(char, ruleset),
        "class_resources": class_resources(char, ruleset),
    }
