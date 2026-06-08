"""Domain models. PROTECTED fields (gold, inventory, hp, ...) are mutated only via
the repository, which is only called by the tools dispatcher (spec §3.1)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..enums import Ability, Skill
from ..rules.checks import ability_modifier, proficiency_bonus


ItemCategory = Literal["weapon", "armor", "gear", "consumable", "treasure", "misc"]
_EQUIPPABLE = {"weapon", "armor", "gear"}


class Item(BaseModel):
    id: str
    name: str
    category: ItemCategory = "misc"
    tags: list[str] = Field(default_factory=list)
    base_value: int | None = None       # advisory hint only; never enforced (spec §11)
    armor_class: int | None = None      # AC granted when worn: armor base_ac, or a shield's +N
    armor_type: Literal["light", "medium", "heavy", "shield"] | None = None  # for AC math
    dex_cap: int | None = None          # medium armor caps DEX bonus (usually 2)
    damage: str | None = None           # weapon damage dice (e.g. "1d8") for the sheet

    @property
    def equippable(self) -> bool:
        return self.category in _EQUIPPABLE


class ItemStack(BaseModel):
    item_id: str
    qty: int = 1


class FeatureRef(BaseModel):
    """A feature on the sheet, resolved from the ruleset at creation. Carries its
    text so the sheet + DM context need no ruleset lookup to display it."""

    name: str
    source: str = ""          # "race" | "subrace" | "class" | "subclass" | "background" | "feat"
    text: str = ""
    level: int = 1


class CharacterSheet(BaseModel):
    """The D&D build behind a PC (design doc §4). Set at chargen, changed only by
    level-up. Derived numbers (AC, saves, slots…) are NOT stored here — they're
    recomputed by `rules/derive` from this + equipment + the ruleset. The PC's final
    (post-racial) ability scores live in the outer `Character.abilities`, so all
    existing code keeps working; `base_abilities` records the pre-racial picks."""

    race: str
    char_class: str
    background: str
    subrace: str | None = None
    subclass: str | None = None
    base_abilities: dict[Ability, int] = Field(default_factory=dict)  # chosen, pre-racial
    ability_method: str = "standard_array"   # standard_array | point_buy | roll
    saving_throw_proficiencies: set[Ability] = Field(default_factory=set)
    expertise: set[Skill] = Field(default_factory=set)
    armor_proficiencies: list[str] = Field(default_factory=list)
    weapon_proficiencies: list[str] = Field(default_factory=list)
    tool_proficiencies: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    features: list[FeatureRef] = Field(default_factory=list)
    feats: list[str] = Field(default_factory=list)
    speed: int = 30
    size: str = "Medium"
    alignment: str = ""
    # background flavor (shown on the sheet)
    personality_traits: list[str] = Field(default_factory=list)
    ideals: list[str] = Field(default_factory=list)
    bonds: list[str] = Field(default_factory=list)
    flaws: list[str] = Field(default_factory=list)
    # spellcasting (casters)
    spellcasting_ability: Ability | None = None
    cantrips_known: list[str] = Field(default_factory=list)
    spells_known: list[str] = Field(default_factory=list)
    spells_prepared: list[str] = Field(default_factory=list)


class Character(BaseModel):
    id: str
    name: str
    kind: Literal["pc", "npc"] = "npc"
    level: int = 1
    abilities: dict[Ability, int] = Field(default_factory=dict)
    skill_proficiencies: set[Skill] = Field(default_factory=set)
    # PROTECTED ---------------------------------------------------------------
    hp: int = 10
    max_hp: int = 10
    armor_class: int = 10
    # Phase-1 placeholder combat profile (real equipment/derivation lands later).
    attack_bonus: int = 2
    damage: str = "1d4"
    xp: int = 0
    conditions: list[str] = Field(default_factory=list)
    gold: int = 0
    inventory: list[ItemStack] = Field(default_factory=list)
    equipped: list[str] = Field(default_factory=list)   # item_ids worn/wielded (player loadout)
    # The full D&D build (PCs from chargen). NPCs leave it None and run on stat-block
    # combat stats. Protected resource trackers (mutated in CS5: rests / casting).
    sheet: CharacterSheet | None = None
    spell_slots_used: dict[int, int] = Field(default_factory=dict)   # {spell_level: used}
    hit_dice_used: int = 0
    resources_used: dict[str, int] = Field(default_factory=dict)     # {resource_name: spent}
    # OPEN (flavor; not event-sourced — D-OPEN-1) -----------------------------
    description: str = ""
    disposition: str = ""    # NPC demeanor — context for the DM's DC-setting (D8)
    home_location: str | None = None   # Place id an NPC belongs to (scopes "who's present")
    price_list: dict[str, int] = Field(default_factory=dict)  # merchant asking prices (soft, §11)

    @property
    def proficiency_bonus(self) -> int:
        return proficiency_bonus(self.level)

    def ability_mod(self, ability: Ability) -> int:
        return ability_modifier(self.abilities.get(ability, 10))

    def item_qty(self, item_id: str) -> int:
        return sum(s.qty for s in self.inventory if s.item_id == item_id)
