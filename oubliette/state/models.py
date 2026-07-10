"""Domain models. PROTECTED fields (gold, inventory, hp, ...) are mutated only via
the repository, which is only called by the tools dispatcher (spec §3.1)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..enums import Ability, Skill
from ..rules.checks import ability_modifier, proficiency_bonus


ItemCategory = Literal["weapon", "armor", "gear", "consumable", "treasure", "misc"]
_EQUIPPABLE = {"weapon", "armor", "gear"}


class Item(BaseModel):
    id: str
    name: str
    category: ItemCategory = "misc"
    tags: list[str] = Field(default_factory=list)
    value_cp: int | None = None         # advisory worth in COPPER; never enforced (spec §11)
    armor_class: int | None = None      # AC granted when worn: armor base_ac, or a shield's +N
    armor_type: Literal["light", "medium", "heavy", "shield"] | None = None  # for AC math
    dex_cap: int | None = None          # medium armor caps DEX bonus (usually 2)
    damage: str | None = None           # weapon damage dice (e.g. "1d8") for the sheet

    @model_validator(mode="before")
    @classmethod
    def _legacy_base_value(cls, data):
        """Items recorded before the coin migration carry `base_value` in GOLD
        (CHARACTER_CREATED payloads, character bundles). Convert on read: 1 gp
        = 100 cp. New dumps write `value_cp` only."""
        if isinstance(data, dict) and data.get("value_cp") is None \
                and data.get("base_value") is not None:
            data = dict(data)
            data["value_cp"] = int(data["base_value"]) * 100
        return data

    @property
    def equippable(self) -> bool:
        return self.category in _EQUIPPABLE


class ItemStack(BaseModel):
    item_id: str
    qty: int = 1
    # Per-instance rider (A5). For a Spell Scroll, the spell inscribed on it (any spell
    # id — SRD or authored) — so one generic `spell_scroll` catalog item covers every
    # spell with no item explosion, and the Arena bridge just reads this. None for plain
    # items. Stack identity is (item_id, spell, spell_level): two differently-inscribed
    # scrolls are distinct stacks; two identical ones stack.
    spell: str | None = None
    # The level the scroll casts the spell at (a commissioned/upcast scroll). None =
    # the spell's own base level. Can't be below it (enforced where the ruleset is known).
    spell_level: int | None = None


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
    # Standing party membership for an NPC (companions arc S1). A companion travels
    # with the party, fights player-controlled in every encounter, and counts toward
    # party strength. Membership is PROTECTED state, event-sourced via
    # COMPANION_RECRUITED / COMPANION_DISMISSED — never set it outside those paths.
    # `kind` stays "npc": a companion is a promoted NPC, not a new species of member.
    companion: bool = False
    companion_origin: Literal["recruited", "purchased"] | None = None
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
    # Money, in COPPER (1 gp = 100 cp). For an NPC this is their own pocket (a
    # merchant's buyback cap); for a PC it is only the pre-pool chargen grant —
    # at install the repository sweeps every PC's coin into the shared PARTY
    # PURSE (repository.party_cp) and PC wallets stay 0 thereafter.
    coin: int = 0
    inventory: list[ItemStack] = Field(default_factory=list)
    equipped: list[str] = Field(default_factory=list)   # item_ids worn/wielded (player loadout)
    # The full D&D build (PCs from chargen). NPCs leave it None and run on stat-block
    # combat stats. Protected resource trackers (mutated in CS5: rests / casting).
    sheet: CharacterSheet | None = None
    spell_slots_used: dict[int, int] = Field(default_factory=dict)   # {spell_level: used}
    hit_dice_used: int = 0
    resources_used: dict[str, int] = Field(default_factory=dict)     # {resource_name: spent}
    # Portrait token art (A3). Set live by the player (uploaded after chargen), so —
    # unlike the flavor fields below — it IS event-sourced (PORTRAIT_SET) to survive
    # replay. Value is a filename in the campaign's character-portraits/ dir; the bytes
    # live on disk (like authored monster portraits), the event records the reference.
    portrait: str | None = None
    # OPEN (flavor; not event-sourced — D-OPEN-1) -----------------------------
    description: str = ""
    disposition: str = ""    # NPC demeanor — context for the DM's DC-setting (D8)
    home_location: str | None = None   # Place id an NPC belongs to (scopes "who's present")
    price_list: dict[str, int] = Field(default_factory=dict)  # merchant asking prices in CP (soft, §11)

    @model_validator(mode="before")
    @classmethod
    def _legacy_gold(cls, data):
        """Characters recorded before the coin migration carry `gold` in GOLD
        pieces (old CHARACTER_CREATED payloads, exported character bundles, and
        seed/test constructors). Convert on read: 1 gp = 100 cp. Their
        price_lists were gp too (merchants are seeded, not event-sourced, so
        only bundles/tests hit this path — convert for consistency)."""
        if isinstance(data, dict) and "coin" not in data and "gold" in data:
            data = dict(data)
            data["coin"] = int(data.pop("gold")) * 100
            if data.get("price_list"):
                data["price_list"] = {k: int(v) * 100 for k, v in data["price_list"].items()}
        return data

    @property
    def proficiency_bonus(self) -> int:
        return proficiency_bonus(self.level)

    def ability_mod(self, ability: Ability) -> int:
        return ability_modifier(self.abilities.get(ability, 10))

    def item_qty(self, item_id: str) -> int:
        """Total held across every rider variant (the loose 'do you have any')."""
        return sum(s.qty for s in self.inventory if s.item_id == item_id)

    def variant_qty(self, item_id: str, spell: str | None = None,
                    spell_level: int | None = None) -> int:
        """Held count of the EXACT (item_id, spell, spell_level) stack — e.g. scrolls of
        one spell at one cast level."""
        return sum(s.qty for s in self.inventory if s.item_id == item_id
                   and s.spell == spell and s.spell_level == spell_level)
