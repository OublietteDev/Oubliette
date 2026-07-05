"""Character creation — the firewall (design doc §6).

A player makes *choices* (`CharacterBuild`); `build_character` validates the whole
build against the SRD `Ruleset` and, only if every rule is satisfied, produces a
fully-built `Character` (sheet + code-derived numbers + granted gear). It can't
pick more skills than the class allows, can't overspend point-buy, can't learn
spells off its list — the validator aggregates every violation into one
`ChargenError`, the same validate-whole-or-fail discipline as the pack/ruleset
loaders.

Everyone starts at level 1 (decision §10.4). The numbers on the returned character
are computed by `rules.derive` — code owns them, the player never types them in.
Spell/feature *effects* aren't resolved here (that waits for combat, decision §1).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..content.ruleset import Ruleset
from ..content.srd_schemas import CharClass, SrdEquipment
from ..enums import Ability, Skill
from ..record.rng import Rng
from ..state.models import (Character, CharacterSheet, FeatureRef, Item,
                            ItemStack)
from . import derive

# Level-1 ability generation (design §1). The standard array and the point-buy
# budget/cost table are SRD constants; 4d6-drop-lowest produces 3..18.
STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]
POINT_BUY_BUDGET = 27
POINT_BUY_COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
ABILITY_METHODS = ("standard_array", "point_buy", "roll")
START_LEVEL = 1


class ChargenError(Exception):
    """A character build that violates the rules. Carries the full aggregated list
    of problems (`.errors`) so the player sees everything wrong at once."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        body = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"invalid character build:\n{body}")


class CharacterBuild(BaseModel):
    """The player's authoring choices — the input to the firewall. Strict: an
    unexpected field is a build error, not a silent drop."""

    model_config = ConfigDict(extra="forbid")

    name: str
    race: str
    char_class: str
    background: str
    subrace: str | None = None
    subclass: str | None = None
    ability_method: str = "standard_array"
    base_abilities: dict[Ability, int] = Field(default_factory=dict)   # pre-racial picks
    skills: list[Skill] = Field(default_factory=list)                  # class skill picks
    expertise: list[Skill] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)                 # background free picks
    race_ability_choices: list[Ability] = Field(default_factory=list)  # flexible racial ASI picks (Half-Elf)
    race_skills: list[Skill] = Field(default_factory=list)             # racial skill picks (Half-Elf Versatility)
    race_languages: list[str] = Field(default_factory=list)            # race/subrace extra-language picks
    race_cantrips: list[str] = Field(default_factory=list)            # subrace bonus cantrips (High Elf)
    cantrips: list[str] = Field(default_factory=list)                  # spell ids (level 0)
    spells: list[str] = Field(default_factory=list)                    # spell ids (level 1+)
    equipment_choices: list[list[int]] = Field(default_factory=list)   # per class choice: option idxs
    alignment: str = ""
    description: str = ""
    # flavor picked from the background's tables (free text — shown on the sheet)
    personality_traits: list[str] = Field(default_factory=list)
    ideals: list[str] = Field(default_factory=list)
    bonds: list[str] = Field(default_factory=list)
    flaws: list[str] = Field(default_factory=list)


# --- ability-score generation -------------------------------------------------
def roll_ability_scores(rng: Rng) -> list[int]:
    """Generate six scores by 4d6-drop-lowest, via the seeded/logged RNG so the
    rolls land in the event log (the chargen UI assigns them; the build records the
    final assignment). Returned high-to-low for convenience."""
    scores = []
    for i in range(6):
        dice = rng.roll("4d6", purpose=f"ability_roll_{i + 1}").rolls
        scores.append(sum(sorted(dice, reverse=True)[:3]))
    return sorted(scores, reverse=True)


def _validate_abilities(build: CharacterBuild, errors: list[str]) -> None:
    abil = build.base_abilities
    missing = [a for a in Ability if a not in abil]
    if missing:
        errors.append(f"ability scores missing: {', '.join(a.value for a in missing)}")
        return
    values = list(abil.values())
    method = build.ability_method
    if method not in ABILITY_METHODS:
        errors.append(f"unknown ability_method {method!r} (use {', '.join(ABILITY_METHODS)})")
    elif method == "standard_array":
        if sorted(values) != sorted(STANDARD_ARRAY):
            errors.append(f"standard array must assign exactly {STANDARD_ARRAY} (got {sorted(values, reverse=True)})")
    elif method == "point_buy":
        bad = [v for v in values if v not in POINT_BUY_COST]
        if bad:
            errors.append(f"point-buy scores must be 8–15 before racial bonuses (got {bad})")
        else:
            spent = sum(POINT_BUY_COST[v] for v in values)
            if spent > POINT_BUY_BUDGET:
                errors.append(f"point-buy overspent: {spent} points used, budget is {POINT_BUY_BUDGET}")
    elif method == "roll":
        bad = [v for v in values if not 3 <= v <= 18]
        if bad:
            errors.append(f"rolled scores must be 3–18 (got {bad})")


# --- distinct/ membership helpers ---------------------------------------------
def _dupes(values: list) -> list:
    seen, out = set(), []
    for v in values:
        if v in seen and v not in out:
            out.append(v)
        seen.add(v)
    return out


# --- race choices (flexible ASI / skills / languages: Half-Elf, Human) --------
def _final_abilities(build: CharacterBuild, race, subrace) -> dict:
    """Final ability scores: the derivation engine's fixed racial increases, plus
    the race's FLEXIBLE +1s the player chose (Half-Elf). Applied here so validation
    and assembly agree."""
    abilities = derive.final_abilities(build.base_abilities, race, subrace)
    asc = race.ability_score_choices if race is not None else None
    if asc is not None and asc.choose:
        for ab in build.race_ability_choices:
            abilities[ab] = abilities.get(ab, 10) + asc.amount
    return abilities


def _validate_race_choices(build: CharacterBuild, race, subrace, ruleset: Ruleset,
                           taken_skills: set, errors: list[str]) -> None:
    """A race/subrace may grant the player choices the fixed fields can't hold: a
    flexible ability increase (+1 to N abilities *other* than the fixed ones), bonus
    skill proficiencies, extra languages (race + subrace, pooled), and bonus cantrips
    from another class's list (High Elf). Validate count/membership/distinctness, and
    that picks don't duplicate proficiencies or cantrips already granted elsewhere."""
    # flexible ability-score increase
    asc = race.ability_score_choices
    picks = build.race_ability_choices
    if asc is None or not asc.choose:
        if picks:
            errors.append(f"race ability choice: {race.name} grants no flexible ability increase")
    else:
        if len(picks) != asc.choose:
            errors.append(f"race ability choice: {race.name} raises {asc.choose} ability(ies), got {len(picks)}")
        for ab in _dupes(picks):
            errors.append(f"race ability choice: {ab.value!r} chosen more than once")
        for ab in picks:
            if ab.value in race.ability_increases:   # "two OTHER ability scores of your choice"
                errors.append(f"race ability choice: {ab.value!r} is already increased by {race.name} — choose another")

    # bonus skill proficiencies (Half-Elf Skill Versatility)
    sc = race.skill_choices
    rskills = build.race_skills
    if sc is None or not sc.choose:
        if rskills:
            errors.append(f"race skills: {race.name} grants no skill choice")
    else:
        allowed = set(sc.from_) if sc.from_ else {s.value for s in Skill}   # empty 'from' = any skill
        if len(rskills) != sc.choose:
            errors.append(f"race skills: {race.name} grants {sc.choose}, got {len(rskills)}")
        for sk in _dupes(rskills):
            errors.append(f"race skills: {sk.value!r} chosen more than once")
        for sk in rskills:
            if sk.value not in allowed:
                errors.append(f"race skills: {sk.value!r} is not an allowed option")
            if sk in taken_skills:
                errors.append(f"race skills: {sk.value!r} is already granted — pick another")

    # extra languages of choice — race + subrace pooled (Human, Half-Elf, High Elf)
    lang_needed = race.language_choices + (subrace.language_choices if subrace else 0)
    if len(build.race_languages) != lang_needed:
        errors.append(f"race languages: {race.name} grants {lang_needed} "
                      f"language(s) of choice, got {len(build.race_languages)}")

    # bonus cantrips from another class's list (High Elf: one wizard cantrip)
    bc = subrace.bonus_cantrips if subrace else None
    cpicks = build.race_cantrips
    if bc is None or not bc.choose:
        if cpicks:
            errors.append(f"race cantrips: {race.name} grants no bonus cantrip")
    else:
        allowed = {s.id for s in ruleset.spells_for(bc.spell_list) if s.level == 0}
        if len(cpicks) != bc.choose:
            errors.append(f"race cantrips: {subrace.name} grants {bc.choose}, got {len(cpicks)}")
        for cid in _dupes(cpicks):
            errors.append(f"race cantrips: {cid!r} chosen more than once")
        for cid in cpicks:
            if cid not in allowed:
                errors.append(f"race cantrips: {cid!r} is not a {bc.spell_list} cantrip")
            if cid in build.cantrips:
                errors.append(f"race cantrips: {cid!r} is already a class cantrip — pick another")


# --- equipment ----------------------------------------------------------------
def _project_srd_item(it: SrdEquipment) -> Item:
    """SrdEquipment -> state.Item, carrying the mechanical bits the derivation
    engine needs (armor base_ac/type/dex_cap, weapon damage). Mirrors the pack
    loader's `_project_item`."""
    # SRD equipment still authors gp ints (real coin costs land with the catalog
    # re-import); worth = base_value, falling back to cost. 1 gp = 100 cp.
    worth = it.base_value if it.base_value is not None else it.cost
    return Item(
        id=it.id, name=it.name, category=it.category,
        tags=list(it.tags),
        value_cp=None if worth is None else worth * 100,
        armor_class=(it.armor.base_ac if it.armor else None),
        armor_type=(it.armor.type if it.armor else None),
        dex_cap=(it.armor.dex_cap if it.armor else None),
        damage=(it.weapon.damage if it.weapon else None),
    )


def _resolve_equipment(build: CharacterBuild, cc: CharClass, ruleset: Ruleset,
                       errors: list[str]) -> list[tuple[str, int]]:
    """Validate the class starting-equipment choices and return the granted gear as
    (item_id, qty) grants in a stable order: class fixed, the chosen class options,
    then background gear. (Item ids are already linted to exist at ruleset load.)"""
    grants: list[tuple[str, int]] = [(g.item, g.qty) for g in cc.starting_equipment.fixed]
    choices = cc.starting_equipment.choices
    picks = build.equipment_choices
    if len(picks) != len(choices):
        errors.append(f"equipment: {cc.name} has {len(choices)} choice(s) to make, got {len(picks)}")
    for i, choice in enumerate(choices):
        selected = picks[i] if i < len(picks) else []
        if len(selected) != choice.choose:
            errors.append(f"equipment: choice {i + 1} requires {choice.choose} pick(s), got {len(selected)}")
        if _dupes(selected):
            errors.append(f"equipment: choice {i + 1} picks the same option twice")
        for idx in selected:
            if not 0 <= idx < len(choice.options):
                errors.append(f"equipment: choice {i + 1} option {idx} out of range (0–{len(choice.options) - 1})")
            else:
                grants += [(g.item, g.qty) for g in choice.options[idx]]
    bg = ruleset.backgrounds.get(build.background)
    if bg is not None:
        grants += [(g.item, g.qty) for g in bg.equipment]
    return grants


def _auto_loadout(grants: list[tuple[str, int]], ruleset: Ruleset) -> list[str]:
    """A sensible starting loadout from the granted gear: the first body armor, the
    first shield, and the first weapon. Gives the new PC a correct AC immediately;
    the player can re-equip in play."""
    equipped: list[str] = []
    armor = shield = weapon = None
    for item_id, _ in grants:
        srd = ruleset.equipment.get(item_id)
        if srd is None:
            continue
        if srd.armor and srd.armor.type == "shield" and shield is None:
            shield = item_id
        elif srd.armor and srd.armor.type in ("light", "medium", "heavy") and armor is None:
            armor = item_id
        elif srd.weapon and weapon is None:
            weapon = item_id
    return [x for x in (armor, shield, weapon) if x is not None]


# --- spells -------------------------------------------------------------------
def _validate_spells(build: CharacterBuild, cc: CharClass, ruleset: Ruleset,
                     temp: Character, errors: list[str]) -> None:
    """A non-caster may pick no spells; a caster's cantrip/spell counts must match
    the class table and every pick must be on the class's list, distinct, and of a
    castable level."""
    if cc.spellcasting is None:
        if build.cantrips or build.spells:
            errors.append(f"{cc.name} is not a spellcaster — it cannot learn cantrips or spells")
        return

    on_list = {s.id for s in ruleset.spells_for(cc.id)}
    cantrip_ids = {s.id for s in ruleset.spells_for(cc.id) if s.level == 0}

    want_cantrips = derive.cantrips_known(temp, ruleset) or 0
    if len(build.cantrips) != want_cantrips:
        errors.append(f"cantrips: {cc.name} knows {want_cantrips} at level {START_LEVEL}, got {len(build.cantrips)}")
    for cid in _dupes(build.cantrips):
        errors.append(f"cantrips: {cid!r} chosen more than once")
    for cid in build.cantrips:
        if cid not in cantrip_ids:
            errors.append(f"cantrips: {cid!r} is not a {cc.name} cantrip")

    want_spells = derive.spells_known_count(temp, ruleset) or 0
    max_level = max(derive.spell_slots(temp, ruleset), default=0)
    if len(build.spells) != want_spells:
        errors.append(f"spells: {cc.name} prepares/knows {want_spells} at level {START_LEVEL}, got {len(build.spells)}")
    for sid in _dupes(build.spells):
        errors.append(f"spells: {sid!r} chosen more than once")
    for sid in build.spells:
        spell = ruleset.spells.get(sid)
        if spell is None or sid not in on_list or spell.level == 0:
            errors.append(f"spells: {sid!r} is not a {cc.name} spell of level 1+")
        elif spell.level > max_level:
            errors.append(f"spells: {spell.name} is level {spell.level}, above your highest slot (level {max_level})")


# --- the firewall -------------------------------------------------------------
def build_character(build: CharacterBuild, ruleset: Ruleset, char_id: str = "pc"
                    ) -> tuple[Character, list[Item]]:
    """Validate a build against the ruleset and return the fully-built level-1 PC
    plus the SRD items to register into the campaign catalog. Raises `ChargenError`
    (aggregated) on any violation; never returns a partially-valid character."""
    errors: list[str] = []

    cc = ruleset.classes.get(build.char_class)
    race = ruleset.races.get(build.race)
    bg = ruleset.backgrounds.get(build.background)
    if cc is None:
        errors.append(f"unknown class {build.char_class!r}")
    if race is None:
        errors.append(f"unknown race {build.race!r}")
    if bg is None:
        errors.append(f"unknown background {build.background!r}")

    # subrace: required iff the race defines any; must belong to the chosen race.
    subrace = None
    if race is not None:
        available = ruleset.subraces_for(race.id)
        if build.subrace is not None:
            subrace = ruleset.subraces.get(build.subrace)
            if subrace is None:
                errors.append(f"unknown subrace {build.subrace!r}")
            elif subrace.race != race.id:
                errors.append(f"subrace {subrace.id!r} does not belong to race {race.id!r}")
        elif available:
            opts = ", ".join(s.id for s in available)
            errors.append(f"race {race.id!r} requires a subrace (choose one of: {opts})")

    # subclass: only when the class grants it by this level; must match the class.
    subclass = None
    if cc is not None and build.subclass is not None:
        subclass = ruleset.subclasses.get(build.subclass)
        if subclass is None:
            errors.append(f"unknown subclass {build.subclass!r}")
        elif subclass.parent != cc.id:
            errors.append(f"subclass {subclass.id!r} is not a {cc.name} subclass")
        elif cc.subclass_level is None or cc.subclass_level > START_LEVEL:
            errors.append(f"{cc.name} does not choose a subclass until level {cc.subclass_level}")

    _validate_abilities(build, errors)

    # skills: exactly the class's allotment, from its list, distinct, and not
    # duplicating what the background already grants (you can't gain a proficiency twice).
    bg_skills = {Skill(s) for s in bg.skill_proficiencies} if bg is not None else set()
    if cc is not None:
        allowed = set(cc.skill_choices.from_)
        if len(build.skills) != cc.skill_choices.choose:
            errors.append(f"skills: {cc.name} picks {cc.skill_choices.choose}, got {len(build.skills)}")
        for sk in _dupes(build.skills):
            errors.append(f"skills: {sk.value!r} chosen more than once")
        for sk in build.skills:
            if sk.value not in allowed:
                errors.append(f"skills: {sk.value!r} is not a {cc.name} skill option")
            if sk in bg_skills:
                errors.append(f"skills: {sk.value!r} is already granted by your background — pick another")

    # race/subrace choices: flexible ASI, bonus skills, extra languages, bonus cantrips.
    if race is not None:
        _validate_race_choices(build, race, subrace, ruleset,
                               set(build.skills) | bg_skills, errors)

    # expertise (rare at level 1): must be a skill you're actually proficient in.
    proficient = set(build.skills) | bg_skills | set(build.race_skills)
    for sk in build.expertise:
        if sk not in proficient:
            errors.append(f"expertise: {sk.value!r} requires proficiency in that skill first")

    # languages: the background's free-language count (the race's extra-language picks
    # are validated separately in _validate_race_choices).
    if bg is not None and len(build.languages) != bg.languages:
        errors.append(f"languages: background grants {bg.languages} free language(s), got {len(build.languages)}")

    # Spell + equipment validation need a provisional character for the derivation engine.
    grants: list[tuple[str, int]] = []
    if cc is not None and race is not None and bg is not None and not _abilities_fatal(build):
        abilities = _final_abilities(build, race, subrace)
        spell_ability = Ability(cc.spellcasting.ability) if cc.spellcasting else None
        temp = Character(
            id=char_id, name=build.name, kind="pc", level=START_LEVEL,
            abilities=abilities,
            sheet=CharacterSheet(race=race.id, char_class=cc.id, background=bg.id,
                                 spellcasting_ability=spell_ability),
        )
        _validate_spells(build, cc, ruleset, temp, errors)
        grants = _resolve_equipment(build, cc, ruleset, errors)

    if errors:
        raise ChargenError(errors)

    # --- build it (validation passed; every reference is safe) ----------------
    assert cc is not None and race is not None and bg is not None
    return _assemble(build, cc, race, subrace, subclass, bg, ruleset, grants, char_id)


def _abilities_fatal(build: CharacterBuild) -> bool:
    """Whether ability scores are too broken to derive from (missing keys). Lets the
    later stages skip cleanly while still reporting the ability errors."""
    return any(a not in build.base_abilities for a in Ability)


def _assemble(build: CharacterBuild, cc: CharClass, race, subrace, subclass, bg,
              ruleset: Ruleset, grants: list[tuple[str, int]], char_id: str
              ) -> tuple[Character, list[Item]]:
    abilities = _final_abilities(build, race, subrace)
    spell_ability = Ability(cc.spellcasting.ability) if cc.spellcasting else None

    features: list[FeatureRef] = []
    for trait in race.traits:
        features.append(FeatureRef(name=trait.name, source="race", text=trait.text, level=trait.level))
    if subrace is not None:
        for trait in subrace.traits:
            features.append(FeatureRef(name=trait.name, source="subrace", text=trait.text, level=trait.level))
    for feat in cc.features:
        if feat.level <= START_LEVEL:
            features.append(FeatureRef(name=feat.name, source="class", text=feat.text, level=feat.level))
    if subclass is not None:
        for feat in subclass.features:
            if feat.level <= START_LEVEL:
                features.append(FeatureRef(name=feat.name, source="subclass", text=feat.text, level=feat.level))
    if bg.feature is not None:
        features.append(FeatureRef(name=bg.feature.name, source="background", text=bg.feature.text))

    sheet = CharacterSheet(
        race=race.id, subrace=(subrace.id if subrace else None),
        char_class=cc.id, subclass=(subclass.id if subclass else None),
        background=bg.id,
        base_abilities=dict(build.base_abilities), ability_method=build.ability_method,
        saving_throw_proficiencies={Ability(a) for a in cc.saving_throws},
        expertise=set(build.expertise),
        armor_proficiencies=list(cc.armor_proficiencies),
        weapon_proficiencies=list(cc.weapon_proficiencies),
        tool_proficiencies=list(cc.tool_proficiencies) + list(bg.tool_proficiencies),
        languages=list(race.languages) + list(build.languages) + list(build.race_languages),
        features=features,
        speed=race.speed, size=race.size, alignment=build.alignment,
        personality_traits=list(build.personality_traits), ideals=list(build.ideals),
        bonds=list(build.bonds), flaws=list(build.flaws),
        spellcasting_ability=spell_ability,
        cantrips_known=list(build.cantrips) + list(build.race_cantrips),
        spells_known=list(build.spells),
        spells_prepared=(list(build.spells) if cc.spellcasting
                         and cc.spellcasting.preparation == "prepared" else []),
    )

    # gear: fold grants into stacks; project the distinct SRD items for the catalog.
    qty_by_id: dict[str, int] = {}
    order: list[str] = []
    for item_id, qty in grants:
        if item_id not in qty_by_id:
            order.append(item_id)
        qty_by_id[item_id] = qty_by_id.get(item_id, 0) + qty
    inventory = [ItemStack(item_id=i, qty=qty_by_id[i]) for i in order]
    items = [_project_srd_item(ruleset.equipment[i]) for i in order if i in ruleset.equipment]
    equipped = _auto_loadout(grants, ruleset)
    item_by_id = {it.id: it for it in items}
    equipped_items = [item_by_id[i] for i in equipped if i in item_by_id]

    char = Character(
        id=char_id, name=build.name, kind="pc", level=START_LEVEL,
        abilities=abilities,
        skill_proficiencies=(set(build.skills) | {Skill(s) for s in bg.skill_proficiencies}
                             | set(build.race_skills)),
        coin=bg.starting_gold * 100,     # backgrounds author gp; wallet is copper
        inventory=inventory, equipped=equipped,
        sheet=sheet, description=build.description,
    )
    char.max_hp = derive.computed_max_hp(char, ruleset) or char.max_hp
    char.hp = char.max_hp
    char.armor_class = derive.armor_class(char, equipped_items)
    # Phase-1 placeholder combat profile (real attack/damage derivation = combat arc).
    weapon = next((it for it in equipped_items if it.damage), None)
    if weapon is not None:
        best = max(char.ability_mod(Ability.STR), char.ability_mod(Ability.DEX))
        char.attack_bonus = char.proficiency_bonus + best
        char.damage = weapon.damage or char.damage
    return char, items
