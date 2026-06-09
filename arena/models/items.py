"""Equipment, weapons, armor, and other items."""

from enum import Enum

from pydantic import BaseModel, Field


class ItemType(str, Enum):
    """Categories of items."""

    WEAPON = "weapon"
    ARMOR = "armor"
    SHIELD = "shield"
    POTION = "potion"
    SCROLL = "scroll"
    WONDROUS = "wondrous"
    TOOL = "tool"
    GEAR = "gear"


class WeaponProperty(str, Enum):
    """Weapon properties from 5e."""

    AMMUNITION = "ammunition"
    FINESSE = "finesse"
    HEAVY = "heavy"
    LIGHT = "light"
    LOADING = "loading"
    REACH = "reach"
    SPECIAL = "special"
    THROWN = "thrown"
    TWO_HANDED = "two_handed"
    VERSATILE = "versatile"


class EquipmentSlot(str, Enum):
    """Where an item can be equipped on a creature."""

    MAIN_HAND = "main_hand"
    OFF_HAND = "off_hand"
    BOTH_HANDS = "both_hands"
    ARMOR = "armor"
    HEAD = "head"
    CLOAK = "cloak"
    GLOVES = "gloves"
    BOOTS = "boots"
    BELT = "belt"
    AMULET = "amulet"
    RING_1 = "ring_1"
    RING_2 = "ring_2"
    RING_3 = "ring_3"
    NONE = "none"


class Rarity(str, Enum):
    """Item rarity tiers from 5e."""

    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    VERY_RARE = "very_rare"
    LEGENDARY = "legendary"
    ARTIFACT = "artifact"


class Item(BaseModel):
    """An item that can be carried or equipped."""

    name: str
    item_type: ItemType
    description: str | None = None

    # Equipment properties
    equipment_slot: EquipmentSlot = EquipmentSlot.NONE
    rarity: Rarity = Rarity.COMMON
    magic_bonus: int = Field(ge=0, le=3, default=0)
    requires_attunement: bool = False
    is_magical: bool = False
    weight: float = Field(ge=0.0, default=0.0)

    # Weapon properties
    weapon_properties: list[WeaponProperty] = Field(default_factory=list)
    damage_dice: str | None = None  # e.g., "1d8"
    damage_type: str | None = None  # e.g., "slashing"
    versatile_dice: str | None = None  # Damage when used two-handed

    # Armor properties
    armor_class: int | None = None  # Base AC for armor
    armor_type: str | None = None  # "light", "medium", "heavy"
    max_dex_bonus: int | None = None  # None = unlimited
    stealth_disadvantage: bool = False
    strength_requirement: int | None = None

    # Range (for ranged weapons)
    range_normal: int | None = None
    range_long: int | None = None

    # Consumable properties
    charges: int | None = None
    current_charges: int | None = None

    # Consumable action configuration (potions & scrolls)
    potion_action_type: str | None = None  # "action" or "bonus_action"

    # Consumable effects (potions & scrolls)
    effect_healing: str | None = None  # Dice expression, e.g., "2d4+2"
    effect_damage_dice: str | None = None  # e.g., "8d6"
    effect_damage_type: str | None = None  # e.g., "fire"
    effect_target_type: str | None = None  # e.g., "self", "one_creature"
    effect_range: int | None = None  # Range in feet for targeted effects
    effect_save_ability: str | None = None  # e.g., "dexterity"
    effect_save_dc: int | None = None  # e.g., 15
    effect_save_damage_on_success: str | None = None  # "none", "half", "full"
    effect_conditions_applied: list[str] = Field(default_factory=list)
    effect_conditions_removed: list[str] = Field(default_factory=list)

    # Passive effect fields (any equipped item can grant these)
    bonus_ability_scores: dict[str, int] = Field(default_factory=dict)
    bonus_speed: int = 0
    bonus_ac: int = 0
    grants_damage_resistances: list[str] = Field(default_factory=list)
    grants_damage_immunities: list[str] = Field(default_factory=list)
    grants_condition_immunities: list[str] = Field(default_factory=list)
    grants_senses: dict[str, int] = Field(default_factory=dict)
