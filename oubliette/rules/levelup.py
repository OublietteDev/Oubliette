"""Level-up (CS5): advance a built PC one level, by the rules.

Like chargen, the player makes *choices* (`LevelUpChoice`) and the builder validates
them against the ruleset and returns the rebuilt `Character` — protected mutable state
(gold, inventory, xp, conditions, the rest trackers) carried over untouched, the build
(level, HP, abilities, features, subclass) advanced. The caller records it in a
CHARACTER_LEVELED event that reinstalls the PC (replay-safe; the new character is stored
whole, never re-derived — D9).

Spell slots need no storage — they're computed from level by `rules.derive`. Learning new
cantrips/spells on level-up mirrors chargen's firewall: the required pick counts are
"what the class table says you should have at the new level, minus what the sheet already
carries" — so a character shorted by an older build (the pre-C3 paladin) catches up on
its next level-up instead of staying behind forever. Prepared casters' picks ARE their
prepared list (the chargen model); known casters grow `spells_known`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..content.ruleset import Ruleset
from ..enums import Ability
from ..rules.checks import ability_modifier
from ..state.models import Character, FeatureRef, Item
from . import derive

MAX_LEVEL = 20
ASI_POINTS = 2

# Cumulative XP required to BE at each level (SRD 5.1 / standard advancement table).
XP_THRESHOLDS = {1: 0, 2: 300, 3: 900, 4: 2700, 5: 6500, 6: 14000, 7: 23000,
                 8: 34000, 9: 48000, 10: 64000, 11: 85000, 12: 100000, 13: 120000,
                 14: 140000, 15: 165000, 16: 195000, 17: 225000, 18: 265000,
                 19: 305000, 20: 355000}


def xp_for_level(level: int) -> int:
    """Cumulative XP needed to reach `level` (clamped to the 1–20 table)."""
    return XP_THRESHOLDS[max(1, min(MAX_LEVEL, level))]


def level_for_xp(xp: int) -> int:
    """The highest level whose XP threshold the given total meets."""
    return max(L for L, need in XP_THRESHOLDS.items() if xp >= need)


def xp_progress(char: Character) -> dict:
    """XP-bar data for the sheet: total XP, the current level's floor and the next
    level's ceiling, how far into the tier (and the percentage), how much more is
    needed, and whether enough XP is banked to level up. `ceil`/`needed` are 0 and
    `ready` is False at the maximum level."""
    lvl = char.level
    floor_ = xp_for_level(lvl)
    if lvl >= MAX_LEVEL:
        return {"xp": char.xp, "level": lvl, "floor": floor_, "ceil": None,
                "into": max(0, char.xp - floor_), "needed": 0, "pct": 100,
                "ready": False, "is_max": True}
    ceil_ = xp_for_level(lvl + 1)
    span = ceil_ - floor_
    into = max(0, char.xp - floor_)
    pct = 100 if span <= 0 else max(0, min(100, round(100 * into / span)))
    return {"xp": char.xp, "level": lvl, "floor": floor_, "ceil": ceil_,
            "into": into, "needed": max(0, ceil_ - char.xp), "pct": pct,
            "ready": char.xp >= ceil_, "is_max": False}


class LevelUpError(Exception):
    """A level-up choice that breaks the rules. Carries the aggregated `.errors`."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("invalid level-up:\n" + "\n".join(f"  - {e}" for e in errors))


class LevelUpChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hp_method: str = "average"                       # "average" | "roll"
    hp_roll: int | None = None                       # the rolled hit-die value (caller rolls)
    ability_increases: dict[Ability, int] = Field(default_factory=dict)   # ASI: sums to 2
    feat: str | None = None                          # ASI alternative
    subclass: str | None = None                      # chosen at the class's subclass level
    new_cantrips: list[str] = Field(default_factory=list)   # casters: this level's picks
    new_spells: list[str] = Field(default_factory=list)


def _class(char: Character, ruleset: Ruleset):
    return ruleset.classes.get(char.sheet.char_class) if char.sheet else None


def _spell_picks_needed(char: Character, ruleset: Ruleset, new_level: int,
                        abilities: dict | None = None) -> tuple[int, int, int]:
    """(cantrips_needed, spells_needed, max_spell_level) at `new_level`: the
    class-table targets minus what the sheet already carries. Catch-up by
    construction — a sheet shorted by an older build owes the full difference."""
    update: dict = {"level": new_level}
    if abilities is not None:
        update["abilities"] = abilities
    probe = char.model_copy(update=update)
    want_c = derive.cantrips_known(probe, ruleset) or 0
    want_s = derive.spells_known_count(probe, ruleset) or 0
    have_c = len(char.sheet.cantrips_known) if char.sheet else 0
    have_s = len(char.sheet.spells_known) if char.sheet else 0
    max_lvl = max(derive.spell_slots(probe, ruleset), default=0)
    return max(0, want_c - have_c), max(0, want_s - have_s), max_lvl


def level_up_plan(char: Character, ruleset: Ruleset) -> dict:
    """What the *next* level requires — drives the level-up UI."""
    cc = _class(char, ruleset)
    if cc is None:
        return {"can_level": False, "reason": "this character has no class sheet to advance"}
    nxt = char.level + 1
    prog = xp_progress(char)
    if nxt > MAX_LEVEL:
        return {"can_level": False, "reason": f"already at the maximum level ({MAX_LEVEL})",
                "xp": prog}
    if char.xp < xp_for_level(nxt):
        return {"can_level": False, "next_level": nxt, "xp": prog,
                "reason": (f"not enough experience — level {nxt} needs {xp_for_level(nxt):,} XP "
                           f"(you have {char.xp:,})")}
    sub_opts = ruleset.subclasses_for(cc.id)
    needs_subclass = cc.subclass_level == nxt and bool(sub_opts) and not char.sheet.subclass
    plan = {
        "can_level": True, "next_level": nxt, "hit_die": cc.hit_die, "xp": prog,
        "average_hp_gain": derive.average_hp_per_level(cc.hit_die) + char.ability_mod(Ability.CON),
        "is_asi": nxt in cc.asi_levels,
        "needs_subclass": needs_subclass, "subclass_label": cc.subclass_label,
        "subclass_options": [{"id": s.id, "name": s.name} for s in sub_opts] if needs_subclass else [],
        # `text`/`desc` throughout feed the UI's hover tooltips — what a feature,
        # feat, or spell actually does, at the moment of choosing it.
        "new_features": [{"name": f.name, "text": f.text} for f in cc.features if f.level == nxt],
        "feats": [{"id": f.id, "name": f.name, "text": f.text} for f in ruleset.feats.values()],
    }
    if cc.spellcasting is not None:
        # Counts are computed with CURRENT abilities; a prepared caster who
        # raises their casting stat's modifier with this level's ASI owes one
        # more pick — the UI bumps the count live via `casting_ability`.
        need_c, need_s, max_lvl = _spell_picks_needed(char, ruleset, nxt)
        already = set(char.sheet.cantrips_known) | set(char.sheet.spells_known)
        class_spells = ruleset.spells_for(cc.id)
        try:
            casting_score = char.abilities.get(Ability(cc.spellcasting.ability), 10)
        except ValueError:
            casting_score = 10
        plan["spellcasting"] = {
            "cantrips_needed": need_c,
            "spells_needed": need_s,
            "max_spell_level": max_lvl,
            "is_prepared_caster": cc.spellcasting.preparation == "prepared",
            "casting_ability": cc.spellcasting.ability,
            "casting_score": casting_score,
            "cantrip_options": [{"id": s.id, "name": s.name, "desc": s.description}
                                for s in class_spells
                                if s.level == 0 and s.id not in already],
            "spell_options": [{"id": s.id, "name": s.name, "level": s.level, "desc": s.description}
                              for s in class_spells
                              if 1 <= s.level <= max_lvl and s.id not in already],
        }
    return plan


def level_up(char: Character, ruleset: Ruleset, choice: LevelUpChoice,
             equipped_items: list[Item] | None = None, char_id: str = "pc") -> Character:
    """Validate the choice and return the character one level higher. Raises
    `LevelUpError` (aggregated) on any violation."""
    errors: list[str] = []
    cc = _class(char, ruleset)
    if cc is None or char.sheet is None:
        raise LevelUpError(["this character has no class sheet to advance"])
    new_level = char.level + 1
    if new_level > MAX_LEVEL:
        raise LevelUpError([f"already at the maximum level ({MAX_LEVEL})"])
    if char.xp < xp_for_level(new_level):
        raise LevelUpError([f"not enough experience for level {new_level} "
                            f"(needs {xp_for_level(new_level)} XP, has {char.xp})"])

    # --- ability score improvement / feat -----------------------------------
    increases: dict[Ability, int] = {}
    is_asi = new_level in cc.asi_levels
    feat = None
    if is_asi:
        if choice.feat is not None:
            feat = ruleset.feats.get(choice.feat)
            if feat is None:
                errors.append(f"unknown feat {choice.feat!r}")
            if choice.ability_increases:
                errors.append("choose an ASI or a feat, not both")
            if feat is not None:
                for k, v in feat.ability_increases.items():
                    increases[Ability(k)] = increases.get(Ability(k), 0) + v
        else:
            total = sum(choice.ability_increases.values())
            if total != ASI_POINTS:
                errors.append(f"an ASI distributes exactly {ASI_POINTS} points (got {total})")
            for ab, v in choice.ability_increases.items():
                if v < 1 or v > 2:
                    errors.append(f"ASI to {ab.value!r} must be +1 or +2 (got {v})")
                if char.abilities.get(ab, 10) + v > 20:
                    errors.append(f"{ab.value.upper()} would exceed 20")
                increases[ab] = increases.get(ab, 0) + v
    else:
        if choice.ability_increases or choice.feat:
            errors.append(f"level {new_level} grants no ability score improvement or feat")

    # --- subclass ------------------------------------------------------------
    sub_opts = ruleset.subclasses_for(cc.id)
    needs_subclass = cc.subclass_level == new_level and bool(sub_opts) and not char.sheet.subclass
    new_subclass = char.sheet.subclass
    chosen_sub = None
    if choice.subclass is not None:
        chosen_sub = ruleset.subclasses.get(choice.subclass)
        if chosen_sub is None:
            errors.append(f"unknown subclass {choice.subclass!r}")
        elif chosen_sub.parent != cc.id:
            errors.append(f"subclass {chosen_sub.id!r} is not a {cc.name} subclass")
        elif char.sheet.subclass:
            errors.append("a subclass is already chosen")
        elif cc.subclass_level is None or cc.subclass_level > new_level:
            errors.append(f"{cc.name} does not choose a subclass until level {cc.subclass_level}")
        else:
            new_subclass = chosen_sub.id
    elif needs_subclass:
        errors.append(f"level {new_level} requires choosing a {cc.subclass_label or 'subclass'}")

    # --- new cantrips / spells (chargen's firewall, at the new level) --------
    if cc.spellcasting is None:
        if choice.new_cantrips or choice.new_spells:
            errors.append(f"{cc.name} is not a spellcaster — it cannot learn "
                          "cantrips or spells")
    else:
        # Counts use the POST-ASI abilities (a casting-stat bump can add a
        # prepared slot) and the new level's slot table.
        prov_abilities = dict(char.abilities)
        for ab, v in increases.items():
            prov_abilities[ab] = prov_abilities.get(ab, 10) + v
        need_c, need_s, max_lvl = _spell_picks_needed(
            char, ruleset, new_level, abilities=prov_abilities)
        on_list = {s.id for s in ruleset.spells_for(cc.id)}
        cantrip_ids = {s.id for s in ruleset.spells_for(cc.id) if s.level == 0}
        already = set(char.sheet.cantrips_known) | set(char.sheet.spells_known)

        if len(choice.new_cantrips) != need_c:
            errors.append(f"cantrips: level {new_level} calls for {need_c} new "
                          f"pick(s), got {len(choice.new_cantrips)}")
        if len(choice.new_spells) != need_s:
            errors.append(f"spells: level {new_level} calls for {need_s} new "
                          f"pick(s), got {len(choice.new_spells)}")
        picks = choice.new_cantrips + choice.new_spells
        seen: set[str] = set()
        for pid in picks:
            if pid in seen:
                errors.append(f"{pid!r} chosen more than once")
            seen.add(pid)
            if pid in already:
                errors.append(f"{pid!r} is already on the sheet")
        for cid in choice.new_cantrips:
            if cid not in cantrip_ids:
                errors.append(f"cantrips: {cid!r} is not a {cc.name} cantrip")
        for sid in choice.new_spells:
            spell = ruleset.spells.get(sid)
            if spell is None or sid not in on_list or spell.level == 0:
                errors.append(f"spells: {sid!r} is not a {cc.name} spell of level 1+")
            elif spell.level > max_lvl:
                errors.append(f"spells: {spell.name} is level {spell.level}, above "
                              f"your highest slot at level {new_level} ({max_lvl})")

    # --- HP ------------------------------------------------------------------
    if choice.hp_method == "roll":
        if choice.hp_roll is None or not 1 <= choice.hp_roll <= cc.hit_die:
            errors.append(f"a rolled hit die must be 1–{cc.hit_die}")

    if errors:
        raise LevelUpError(errors)

    # --- build the advanced character (validation passed) -------------------
    new_abilities = dict(char.abilities)
    for ab, v in increases.items():
        new_abilities[ab] = new_abilities.get(ab, 10) + v
    new_con = ability_modifier(new_abilities.get(Ability.CON, 10))
    die_value = choice.hp_roll if choice.hp_method == "roll" else derive.average_hp_per_level(cc.hit_die)
    gain = max(1, die_value + new_con)

    features = list(char.sheet.features)
    for f in cc.features:
        if f.level == new_level:
            features.append(FeatureRef(name=f.name, source="class", text=f.text, level=f.level))
    if chosen_sub is not None:                       # newly chosen → grant its features up to here
        for f in chosen_sub.features:
            if f.level <= new_level:
                features.append(FeatureRef(name=f.name, source="subclass", text=f.text, level=f.level))
    elif new_subclass is not None:                   # existing subclass → only this level's features
        sc = ruleset.subclasses.get(new_subclass)
        for f in (sc.features if sc else []):
            if f.level == new_level:
                features.append(FeatureRef(name=f.name, source="subclass", text=f.text, level=f.level))
    new_feats = list(char.sheet.feats)
    if feat is not None:
        new_feats.append(feat.id)
        features.append(FeatureRef(name=feat.name, source="feat", text=feat.text, level=new_level))

    sheet_update: dict = {
        "subclass": new_subclass, "features": features, "feats": new_feats,
    }
    if choice.new_cantrips or choice.new_spells:
        new_known = list(char.sheet.spells_known) + list(choice.new_spells)
        sheet_update["cantrips_known"] = (list(char.sheet.cantrips_known)
                                          + list(choice.new_cantrips))
        sheet_update["spells_known"] = new_known
        if cc.spellcasting and cc.spellcasting.preparation == "prepared":
            # The chargen model: a prepared caster's picks ARE the prepared list.
            sheet_update["spells_prepared"] = new_known
    new_sheet = char.sheet.model_copy(update=sheet_update)
    new_char = char.model_copy(update={
        "level": new_level, "abilities": new_abilities, "sheet": new_sheet,
        "max_hp": char.max_hp + gain, "hp": char.hp + gain,
    })
    # recompute equipment-dependent placeholders (an ASI to DEX can move AC, etc.)
    items = equipped_items or []
    new_char.armor_class = derive.armor_class(new_char, items)
    weapon = next((it for it in items if it.damage), None)
    if weapon is not None:
        best = max(new_char.ability_mod(Ability.STR), new_char.ability_mod(Ability.DEX))
        new_char.attack_bonus = new_char.proficiency_bonus + best
        new_char.damage = weapon.damage or new_char.damage
    return new_char
