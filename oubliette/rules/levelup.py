"""Level-up (CS5): advance a built PC one level, by the rules.

Like chargen, the player makes *choices* (`LevelUpChoice`) and the builder validates
them against the ruleset and returns the rebuilt `Character` — protected mutable state
(gold, inventory, xp, conditions, the rest trackers) carried over untouched, the build
(level, HP, abilities, features, subclass) advanced. The caller records it in a
CHARACTER_LEVELED event that reinstalls the PC (replay-safe; the new character is stored
whole, never re-derived — D9).

Spell slots need no storage — they're computed from level by `rules.derive`. Learning new
cantrips/spells on level-up is deferred until the SRD spell content lands (CS4); no caster
is buildable until then, so it can't arise yet.
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


def _class(char: Character, ruleset: Ruleset):
    return ruleset.classes.get(char.sheet.char_class) if char.sheet else None


def level_up_plan(char: Character, ruleset: Ruleset) -> dict:
    """What the *next* level requires — drives the level-up UI."""
    cc = _class(char, ruleset)
    if cc is None:
        return {"can_level": False, "reason": "this character has no class sheet to advance"}
    nxt = char.level + 1
    if nxt > MAX_LEVEL:
        return {"can_level": False, "reason": f"already at the maximum level ({MAX_LEVEL})"}
    sub_opts = ruleset.subclasses_for(cc.id)
    needs_subclass = cc.subclass_level == nxt and bool(sub_opts) and not char.sheet.subclass
    return {
        "can_level": True, "next_level": nxt, "hit_die": cc.hit_die,
        "average_hp_gain": derive.average_hp_per_level(cc.hit_die) + char.ability_mod(Ability.CON),
        "is_asi": nxt in cc.asi_levels,
        "needs_subclass": needs_subclass, "subclass_label": cc.subclass_label,
        "subclass_options": [{"id": s.id, "name": s.name} for s in sub_opts] if needs_subclass else [],
        "new_features": [f.name for f in cc.features if f.level == nxt],
        "feats": [{"id": f.id, "name": f.name} for f in ruleset.feats.values()],
    }


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

    new_sheet = char.sheet.model_copy(update={
        "subclass": new_subclass, "features": features, "feats": new_feats,
    })
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
