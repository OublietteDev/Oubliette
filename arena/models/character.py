"""Player characters and the base Creature class."""

from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, model_validator

from .abilities import AbilityScores
from .conditions import AppliedCondition, ActiveBuff
from .actions import Action
from .feats import Feat
from .items import Item


class CreatureSize(str, Enum):
    """Creature sizes in 5e."""

    TINY = "tiny"  # 2.5 ft (0.5 hex)
    SMALL = "small"  # 5 ft (1 hex)
    MEDIUM = "medium"  # 5 ft (1 hex)
    LARGE = "large"  # 10 ft (2 hexes)
    HUGE = "huge"  # 15 ft (3 hexes)
    GARGANTUAN = "gargantuan"  # 20+ ft (4+ hexes)


class CreatureType(str, Enum):
    """Types of creatures in 5e."""

    ABERRATION = "aberration"
    BEAST = "beast"
    CELESTIAL = "celestial"
    CONSTRUCT = "construct"
    DRAGON = "dragon"
    ELEMENTAL = "elemental"
    FEY = "fey"
    FIEND = "fiend"
    GIANT = "giant"
    HUMANOID = "humanoid"
    MONSTROSITY = "monstrosity"
    OOZE = "ooze"
    PLANT = "plant"
    UNDEAD = "undead"


class RiderTrigger(str, Enum):
    """When an on-hit rider fires."""

    POST_HIT = "post_hit"    # Player chooses after hit (Divine Smite, Eldritch Smite)
    AUTOMATIC = "automatic"  # Fires on every hit (passive — Sneak Attack once/turn)


class OnHitRider(BaseModel):
    """Configurable on-hit triggered ability attached to a Feature.

    Generalizes Divine Smite, Sneak Attack, Stunning Strike, etc.
    """

    # Trigger
    trigger: RiderTrigger = RiderTrigger.POST_HIT
    once_per_turn: bool = False  # Sneak Attack, Hex damage

    # Resource cost (same pattern as Action.resource_cost)
    resource_type: str | None = None   # "spell_slot", "ki_points", etc.
    resource_cost: int = 0             # How many to spend (1 ki, 1 slot, etc.)

    # Damage
    damage_dice: str | None = None     # Base dice, e.g. "2d8" or "1d6"
    damage_type: str = "radiant"       # DamageType value
    damage_per_slot_level: str | None = None  # Scaling dice per slot level, e.g. "1d8"
    max_dice: int | None = None        # Cap on total dice count (5 for Divine Smite)

    # Save effect (Stunning Strike pattern)
    save_ability: str | None = None    # "constitution", etc.
    save_dc_ability: str | None = None  # Ability used for DC: 8 + prof + mod
    condition_on_fail: str | None = None  # "stunned", "frightened", etc.
    condition_duration: str = "end_of_turn"  # Duration type for applied condition
    condition_save_to_end: bool = True  # Target re-saves to end

    # Requirements
    requires_melee: bool = False       # Only melee weapon attacks
    requires_weapon: bool = False      # Only weapon attacks (not spell)


class Feature(BaseModel):
    """A class feature, racial trait, or special ability.

    Passive bonus fields mirror the Feat model so stat_modifiers.py
    can aggregate features, feats, and equipment uniformly.
    """

    name: str
    description: str
    source: str | None = None  # e.g., "Fighter 1", "Mountain Dwarf"

    # Passive stat bonuses (same pattern as Feat and Item models)
    bonus_ac: int = 0
    bonus_speed: int = 0
    bonus_ability_scores: dict[str, int] = Field(default_factory=dict)
    bonus_initiative: int = 0
    grants_damage_resistances: list[str] = Field(default_factory=list)
    grants_damage_immunities: list[str] = Field(default_factory=list)
    grants_condition_immunities: list[str] = Field(default_factory=list)
    grants_saving_throw_proficiencies: list[str] = Field(default_factory=list)

    # Special AC calculation override for Unarmored Defense
    unarmored_defense: str | None = None  # "monk" (10+DEX+WIS) or "barbarian" (10+DEX+CON)

    # Critical hit modifications
    crit_range_reduction: int = 0  # How many below 20 also crit (1 = 19-20, 2 = 18-20)
    bonus_crit_dice: int = 0  # Extra weapon damage dice on crit (Brutal Critical)

    # Evasion (Rogue/Monk: DEX saves — no damage on success, half on fail)
    has_evasion: bool = False

    # Sculpt Spells (Evocation wizard): the caster's harmful AoE spells spare
    # allies entirely. Approximation of RAW (choose 1+level creatures to
    # auto-succeed and take no damage): ALL allies are exempted.
    sculpt_spells: bool = False

    # Extra Attack (number of TOTAL attacks when taking Attack action; 0 = use default 1)
    extra_attack_count: int = 0  # 2 for most martials, 3 for Fighter 11, 4 for Fighter 20

    # Damage reduction reaction (Parry, Uncanny Dodge, Deflect Missiles)
    damage_reduction_dice: str | None = None  # Dice to roll for reduction, e.g., "1d10"
    damage_reduction_bonus: str | None = None  # Ability mod to add, e.g., "dexterity"
    damage_reduction_flat_half: bool = False  # Uncanny Dodge: just halve damage (no roll)
    damage_reduction_type: str | None = None  # "melee_only", "ranged_only", or None for any

    # Forced reroll (Indomitable, Lucky, Diamond Soul)
    forced_reroll_saves: bool = False  # Can reroll failed saving throws
    forced_reroll_resource: str | None = None  # Resource to spend, e.g., "indomitable", "ki_points"
    forced_reroll_resource_cost: int = 1  # How many of the resource to spend

    # Aura effects (Paladin Aura of Protection, Aura of Courage, etc.)
    aura_range: int = 0  # Range in feet (0 = no aura). 10 for most, 30 at 18th.
    aura_save_bonus_ability: str | None = None  # Ability mod added to saves, e.g., "charisma"
    aura_condition_immunity: list[str] = Field(default_factory=list)  # Conditions allies are immune to in aura
    aura_requires_conscious: bool = True  # Most auras require the source to be conscious

    # Condition immunity while active (Mindless Rage: immune to charmed/frightened while raging)
    active_condition_immunities: list[str] = Field(default_factory=list)  # Conditions immune to while feature is active
    active_condition_resource: str | None = None  # Resource that must be active, e.g., "rage" (None = always active/passive)

    # Death prevention (Relentless Rage, Relentless Endurance, etc.)
    death_prevention: bool = False  # Can prevent dropping to 0 HP
    death_prevention_hp: int = 1  # HP to set to on success (usually 1)
    death_prevention_save_ability: str | None = None  # Ability for save (CON for Relentless Rage), None = auto-succeed
    death_prevention_save_dc: int = 10  # Base DC (Relentless Rage: starts at 10, +5 each use)
    death_prevention_dc_increment: int = 0  # DC increase per use (5 for Relentless Rage, 0 for one-shot)
    death_prevention_resource: str | None = None  # Resource to spend, None = free / uses_per_rest on feature

    # On-hit rider (Divine Smite, Sneak Attack, Stunning Strike, etc.)
    on_hit_rider: OnHitRider | None = None

    @model_validator(mode="after")
    def auto_upgrade_divine_smite(self) -> "Feature":
        """Auto-populate on_hit_rider for legacy Divine Smite features.

        Existing creature JSONs that have a feature named "Divine Smite"
        but no on_hit_rider field will get the correct config automatically.
        """
        if self.on_hit_rider is None and self.name.lower() == "divine smite":
            self.on_hit_rider = OnHitRider(
                trigger=RiderTrigger.POST_HIT,
                resource_type="spell_slot",
                resource_cost=1,
                damage_dice="2d8",
                damage_type="radiant",
                damage_per_slot_level="1d8",
                max_dice=5,
                requires_melee=True,
                requires_weapon=True,
            )
        return self


class Creature(BaseModel):
    """Base class for all creatures (PCs, NPCs, Monsters)."""

    # Identity
    name: str
    size: CreatureSize = CreatureSize.MEDIUM
    creature_type: CreatureType = CreatureType.HUMANOID
    alignment: str | None = None

    # Core Stats
    ability_scores: AbilityScores = Field(default_factory=AbilityScores)
    armor_class: int = Field(ge=1, default=10)
    max_hit_points: int = Field(ge=1)
    current_hit_points: int | None = None  # None = use max
    temporary_hit_points: int = 0
    hit_dice: str | None = None  # e.g., "8d8"

    # Combat Stats
    speed: dict[str, int] = Field(default_factory=lambda: {"walk": 30})
    proficiency_bonus: int = Field(ge=2, le=9, default=2)

    # Defense
    saving_throw_proficiencies: list[str] = Field(default_factory=list)
    damage_resistances: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    damage_vulnerabilities: list[str] = Field(default_factory=list)
    condition_immunities: list[str] = Field(default_factory=list)

    # Senses
    senses: dict[str, int] = Field(default_factory=dict)  # e.g., {"darkvision": 60}
    passive_perception: int | None = None

    # Actions
    actions: list[Action] = Field(default_factory=list)
    bonus_actions: list[Action] = Field(default_factory=list)
    reactions: list[Action] = Field(default_factory=list)

    # Conditions
    active_conditions: list[AppliedCondition] = Field(default_factory=list)

    # Active buffs/debuffs (temporary stat modifications from spells/abilities)
    active_buffs: list[ActiveBuff] = Field(default_factory=list)

    # Visuals
    token_image: str | None = None  # Path to image file
    token_color: str = "#808080"  # Fallback color

    # Equipment
    equipment: list[Item] = Field(default_factory=list)

    # AI Control
    is_player_controlled: bool = True
    ai_profile: str | None = None  # Reference to AI behavior profile

    @model_validator(mode="after")
    def set_current_hp(self) -> "Creature":
        """Set current HP to max if not specified."""
        if self.current_hit_points is None:
            self.current_hit_points = self.max_hit_points
        return self

    @property
    def hp_percent(self) -> float:
        """Get current HP as a percentage of max."""
        if self.max_hit_points == 0:
            return 0.0
        return (self.current_hit_points or 0) / self.max_hit_points

    @property
    def is_bloodied(self) -> bool:
        """Check if creature is below 50% HP."""
        return self.hp_percent < 0.5

    @property
    def is_conscious(self) -> bool:
        """Check if creature is conscious (HP > 0)."""
        return (self.current_hit_points or 0) > 0

    def get_saving_throw_modifier(self, ability: str) -> int:
        """Calculate saving throw modifier for an ability."""
        modifier = self.ability_scores.get_modifier(ability)
        if ability.lower() in [s.lower() for s in self.saving_throw_proficiencies]:
            modifier += self.proficiency_bonus
        return modifier


class PlayerCharacter(Creature):
    """A player-controlled character."""

    # Class & Level
    character_class: str  # e.g., "Fighter"
    subclass: str | None = None
    level: int = Field(ge=1, le=20, default=1)

    # Secondary classes for multiclassing
    multiclass: list[dict[str, int]] = Field(default_factory=list)

    # Background & Flavor
    background: str | None = None
    race: str = "Human"

    # Resources
    spell_slots: dict[int, int] = Field(default_factory=dict)  # level: count
    current_spell_slots: dict[int, int] | None = None
    class_resources: dict[str, int] = Field(default_factory=dict)  # e.g., {"ki_points": 5}

    # Skills
    skill_proficiencies: list[str] = Field(default_factory=list)
    skill_expertise: list[str] = Field(default_factory=list)

    # Equipment (legacy string-based fields for backward compat)
    equipped_armor: str | None = None
    equipped_shield: bool = False
    equipped_weapons: list[str] = Field(default_factory=list)

    # Features & Feats
    features: list[Feature] = Field(default_factory=list)
    feats: list[Feat] = Field(default_factory=list)

    # Spellcasting
    spellcasting_ability: str | None = None  # e.g., "wisdom"
    spells_known: list[str] = Field(default_factory=list)  # Spell names
    spells_prepared: list[str] = Field(default_factory=list)  # Names of prepared spells

    # Death saves
    death_save_successes: int = Field(ge=0, le=3, default=0)
    death_save_failures: int = Field(ge=0, le=3, default=0)
    is_stabilized: bool = False

    @model_validator(mode="after")
    def sync_spell_slots_to_resources(self) -> "PlayerCharacter":
        """Ensure spell_slots entries are available as class_resources.

        The combat system checks ``class_resources`` for keys like
        ``spell_slot_1``, ``spell_slot_2``, etc.  If the character has
        ``spell_slots`` defined (from the Features tab) but the
        corresponding ``class_resources`` key is missing, fill it in
        automatically so spells with ``resource_cost`` work out of the box.

        Existing class_resources values are *not* overwritten, allowing
        manual overrides or partially-spent state to be preserved.
        """
        if self.spell_slots:
            for level, count in self.spell_slots.items():
                key = f"spell_slot_{level}"
                if key not in self.class_resources:
                    self.class_resources[key] = count
        return self

    @property
    def total_level(self) -> int:
        """Calculate total character level including multiclass."""
        total = self.level
        for mc in self.multiclass:
            total += sum(mc.values())
        return total
