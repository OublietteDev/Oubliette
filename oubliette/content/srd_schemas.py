"""Strict, versioned schemas for the SRD ruleset (design doc §3).

This is the *system* content — classes, races, backgrounds, spells, feats,
equipment — shared by every world, distinct from the world content in
`content/schemas.py`. Same discipline: every model forbids unknown fields, so a
typo in a ruleset file is a load error, not a silent drop. The loader
(`content/ruleset.py`) parses these whole and lints the cross-references.

Backbone: SRD 5.1 (CC-BY-4.0) — see the NOTICE file. The shapes are the full,
real shapes now (build through the seams) so the big content fill in CS4 adds
DATA, not schema churn.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .schemas import (ArmorProfile, ConsumableMechanics, ItemType,
                      PoisonMechanics, SpellChassis, WeaponProfile, _Strict)

# Bump on a breaking change to these shapes; the ruleset carries its own version.
RULESET_SCHEMA_VERSION = 1

AbilityKey = Literal["str", "dex", "con", "int", "wis", "cha"]
CasterType = Literal["full", "half", "third", "pact", "none"]


# --- shared little pieces -----------------------------------------------------
class Feature(_Strict):
    """A named, leveled ability granted by a race/class/subclass/background/feat.
    Effect is reference TEXT for now (the firewall: code owns numbers, the DM
    narrates); structured effect data is a later, combat-arc concern."""

    name: str
    level: int = 1                   # character level it's gained (1 for racial/background)
    text: str = ""


class EquipmentGrant(_Strict):
    """One concrete item granted (by a class/background starting kit)."""

    item: str                        # -> SrdEquipment id
    qty: int = 1


class EquipmentChoice(_Strict):
    """A 'choose N of these bundles' decision in a starting kit. Each option is a
    bundle (list) of grants, so '(a) a longsword or (b) two handaxes' is two
    one-item / two-item options."""

    choose: int = 1
    options: list[list[EquipmentGrant]] = Field(default_factory=list)


class StartingEquipment(_Strict):
    fixed: list[EquipmentGrant] = Field(default_factory=list)     # always granted
    choices: list[EquipmentChoice] = Field(default_factory=list)  # player picks


class SkillChoice(_Strict):
    choose: int = 0
    from_: list[str] = Field(default_factory=list, alias="from")   # SRD skill keys

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --- equipment ----------------------------------------------------------------
# The granular SRD item class. `category` (below) stays inside the closed set the
# state.Item model accepts, so projection (`_project_srd_item`) is unaffected;
# `item_type` is the FROZEN contract the Arena bridge reads to decide what a magic
# item *is* (Phase B). The contract shapes (`ItemType`/`ConsumableMechanics`/
# `PoisonMechanics`) live in `content/schemas.py` since the module-kit arc gave
# pack items the same fields — one contract, two catalogs, single source.


class SrdEquipment(_Strict):
    """The standard SRD gear catalog (weapons/armor/gear/etc.). Mirrors the world
    `content.Item` shape and adds the mechanical bits (cost/weight + the existing
    weapon/armor profiles). Registered into a campaign's item catalog when a
    created character is granted it.

    The magic-item fields (`item_type`/`rarity`/`magic_bonus`/`requires_attunement`/
    `mechanics`/`consumable`) are the Phase-A frozen contract: they carry the
    structured data the Arena will later consume, even though Oubliette doesn't read
    them yet. `mechanics == "none"` is a deliberate success state — the item is
    grantable and flavorful, just not combat-mechanized (see content-first plan §3)."""

    id: str
    name: str
    category: Literal["weapon", "armor", "gear", "consumable", "treasure", "misc"] = "misc"
    description: str = ""
    cost: int | None = None          # in copper? no — gold pieces (advisory; soft economy §11)
    weight: float | None = None      # lb
    base_value: int | None = None    # advisory price hint (matches content.Item)
    tags: list[str] = Field(default_factory=list)
    slot: str | None = None
    weapon: WeaponProfile | None = None
    armor: ArmorProfile | None = None
    # --- magic-item contract (Phase A freeze; consumed by the Arena bridge later) ---
    item_type: ItemType = "mundane"
    rarity: str | None = None        # common / uncommon / rare / very rare / legendary / artifact
    magic_bonus: int | None = None   # +N to attack&damage (weapon) or AC (armor/shield/ring)
    requires_attunement: bool = False  # recorded, NOT enforced (attunement mechanics deferred)
    mechanics: Literal["none", "structured"] = "none"  # does `consumable`/`magic_bonus`/`poison` carry combat data?
    consumable: ConsumableMechanics | None = None
    poison: PoisonMechanics | None = None
    # Worn boons (module-kit S1.5, same contract as content.Item): damage types
    # warded WHILE EQUIPPED. SRD entries ship empty (the generator never
    # structured them — a later backfill can); pack items author them directly.
    grants_resistances: list[str] = Field(default_factory=list)
    grants_immunities: list[str] = Field(default_factory=list)


# --- spells -------------------------------------------------------------------
class Spell(_Strict):
    id: str
    name: str
    level: int                       # 0 = cantrip
    school: str                      # abjuration, evocation, ...
    casting_time: str = "1 action"
    range: str = ""
    components: str = ""             # "V, S, M (a pinch of sulfur)"
    duration: str = "Instantaneous"
    concentration: bool = False
    ritual: bool = False
    classes: list[str] = Field(default_factory=list)   # -> CharClass ids that can learn it
    description: str = ""

    @model_validator(mode="after")
    def _level_range(self) -> "Spell":
        if not 0 <= self.level <= 9:
            raise ValueError("spell level must be 0 (cantrip) through 9")
        return self


class PackSpell(Spell):
    """A pack-authored spell (module-kit S3): the standard chargen `Spell` shape
    plus a required `chassis` — the structured combat half, constrained to the
    four shapes the Arena executes natively. Because this IS a `Spell`, the
    merged ruleset serves it to chargen/level-up/DM-context unchanged; the
    Arena bridge spots the chassis and projects it into an Action at fight
    time (`combat.arena_bridge.chassis_action`). One source of truth, no
    generated sidecar files."""

    chassis: SpellChassis

    @model_validator(mode="after")
    def _chassis_fits_the_spell(self) -> "PackSpell":
        errs: list[str] = []
        if self.level == 0 and self.chassis.kind in ("heal", "hex"):
            errs.append("cantrips can only use the bolt or blast chassis")
        if self.level == 0 and (self.chassis.upcast_dice
                                or self.chassis.upcast_targets):
            errs.append("cantrips scale automatically at levels 5/11/17 — "
                        "drop the upcast fields")
        if self.chassis.kind == "hex" and not self.concentration:
            errs.append("a hex holds its condition through concentration — "
                        "set concentration to true")
        if errs:
            raise ValueError("; ".join(errs))
        return self


# --- classes ------------------------------------------------------------------
class SpellcastingProfile(_Strict):
    ability: AbilityKey
    caster_type: CasterType = "full"
    preparation: Literal["known", "prepared"] = "known"
    ritual: bool = False
    # A "prepared" caster re-prepares from its WHOLE class spell list each long
    # rest (cleric/druid/paladin know their full list). A spellbook caster
    # (wizard) instead prepares only from spells it has learned (spells_known).
    # Ignored for "known"/pact casters. (C5: re-prepare on long rest.)
    prepares_from_spellbook: bool = False


class SpellProgressionRow(_Strict):
    """One character-level row of a caster's spell numbers — the SRD class table,
    verbatim, so it reads as the book reads and is trivially verifiable."""

    level: int                       # character level (1-20)
    cantrips_known: int | None = None
    spells_known: int | None = None  # 'known' casters only; 'prepared' compute mod+level
    spell_slots: list[int] = Field(default_factory=list)  # slots by spell level at THIS level


class PactProgressionRow(_Strict):
    """Warlock Pact Magic — a different slot model: a few slots that are ALL of the
    same (rising) level and recharge on a SHORT rest. Used when spellcasting.caster_
    type == 'pact', instead of spell_progression."""

    level: int
    cantrips_known: int | None = None
    spells_known: int | None = None
    slots: int = 0                   # number of pact slots
    slot_level: int = 0              # the (single) level those slots are cast at
    invocations_known: int | None = None


class ClassResource(_Strict):
    """A leveled class resource pool — sorcery points, ki, rage uses, channel divinity.
    `by_level` is sparse: the amount applies from that level until the next listed one
    (-1 = unlimited, e.g. barbarian rage at 20). Spending/recharge mechanics land in
    CS5; this just defines the maxima."""

    name: str
    recharge: Literal["short", "long", "none"] = "long"
    by_level: dict[int, int] = Field(default_factory=dict)   # level -> amount (-1 = unlimited)
    text: str = ""


class CharClass(_Strict):
    id: str
    name: str
    hit_die: Literal[6, 8, 10, 12]
    primary_ability: list[AbilityKey] = Field(default_factory=list)
    saving_throws: list[AbilityKey] = Field(default_factory=list)   # the two proficient saves
    armor_proficiencies: list[str] = Field(default_factory=list)
    weapon_proficiencies: list[str] = Field(default_factory=list)
    tool_proficiencies: list[str] = Field(default_factory=list)
    skill_choices: SkillChoice = Field(default_factory=SkillChoice)
    starting_equipment: StartingEquipment = Field(default_factory=StartingEquipment)
    asi_levels: list[int] = Field(default_factory=list)             # levels granting ASI/feat
    subclass_level: int | None = None        # when the subclass is chosen
    subclass_label: str = ""                 # "Martial Archetype", "Divine Domain", ...
    spellcasting: SpellcastingProfile | None = None
    features: list[Feature] = Field(default_factory=list)
    spell_progression: list[SpellProgressionRow] = Field(default_factory=list)
    pact_magic_progression: list[PactProgressionRow] = Field(default_factory=list)  # warlock
    resources: list[ClassResource] = Field(default_factory=list)   # sorcery points, ki, rage…

    @model_validator(mode="after")
    def _saves(self) -> "CharClass":
        if self.saving_throws and len(self.saving_throws) != 2:
            raise ValueError("a class has exactly two saving-throw proficiencies")
        return self


class Subclass(_Strict):
    id: str
    name: str
    parent: str                      # -> CharClass id
    label: str = ""                  # the class's subclass_label (Champion -> Martial Archetype)
    features: list[Feature] = Field(default_factory=list)
    spellcasting: SpellcastingProfile | None = None   # e.g. some domains/archetypes add casting
    spell_progression: list[SpellProgressionRow] = Field(default_factory=list)


# --- races --------------------------------------------------------------------
class AbilityScoreChoice(_Strict):
    """A race's FLEXIBLE ability-score increase (e.g. Half-Elf: +1 to two abilities
    of your choice, *other* than those the race already raises). The fixed part
    stays in `Race.ability_increases`; this is the player-chosen remainder, applied
    by chargen from the player's picks."""

    choose: int = 0                  # how many distinct abilities the player picks
    amount: int = 1                  # the bonus applied to each picked ability


class Race(_Strict):
    id: str
    name: str
    ability_increases: dict[AbilityKey, int] = Field(default_factory=dict)
    ability_score_choices: AbilityScoreChoice | None = None   # flexible ASI (Half-Elf)
    size: Literal["Small", "Medium", "Large"] = "Medium"
    speed: int = 30
    darkvision: int = 0              # range in feet (0 = none)
    languages: list[str] = Field(default_factory=list)
    language_choices: int = 0        # extra languages of the player's choice (Human, Half-Elf)
    skill_choices: SkillChoice = Field(default_factory=SkillChoice)  # e.g. Half-Elf Skill Versatility
    traits: list[Feature] = Field(default_factory=list)


class BonusCantrips(_Strict):
    """A race/subrace grant of cantrip(s) the player chooses from another class's
    list (e.g. High Elf: one cantrip of your choice from the wizard list, cast with
    Intelligence). Independent of the character's own class spellcasting."""

    choose: int = 0
    spell_list: str = ""             # -> CharClass id whose cantrip list to choose from
    ability: AbilityKey | None = None  # the spellcasting ability for these cantrips


class Subrace(_Strict):
    id: str
    name: str
    race: str                        # -> Race id
    ability_increases: dict[AbilityKey, int] = Field(default_factory=dict)
    language_choices: int = 0        # extra languages of the player's choice (High Elf)
    bonus_cantrips: BonusCantrips | None = None   # High Elf: a wizard cantrip of choice
    traits: list[Feature] = Field(default_factory=list)


# --- backgrounds --------------------------------------------------------------
class Background(_Strict):
    id: str
    name: str
    skill_proficiencies: list[str] = Field(default_factory=list)
    tool_proficiencies: list[str] = Field(default_factory=list)
    languages: int = 0               # number of free languages of the player's choice
    equipment: list[EquipmentGrant] = Field(default_factory=list)
    starting_gold: int = 0
    feature: Feature | None = None
    # flavor tables (personality/ideal/bond/flaw) shown on the sheet
    personality_traits: list[str] = Field(default_factory=list)
    ideals: list[str] = Field(default_factory=list)
    bonds: list[str] = Field(default_factory=list)
    flaws: list[str] = Field(default_factory=list)


# --- feats --------------------------------------------------------------------
class Feat(_Strict):
    id: str
    name: str
    prerequisite: str = ""
    ability_increases: dict[AbilityKey, int] = Field(default_factory=dict)  # half-feats
    text: str = ""


# --- conditions ---------------------------------------------------------------
class Condition(_Strict):
    """An SRD condition — reference text now; the combat arc applies its effects."""

    id: str
    name: str
    text: str = ""
