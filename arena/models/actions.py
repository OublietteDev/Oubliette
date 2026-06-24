"""Actions, attacks, and effects that creatures can perform."""

from enum import Enum

from pydantic import BaseModel, Field

from arena.models.conditions import BuffEffect


class ActionType(str, Enum):
    """Types of actions in the action economy."""

    ACTION = "action"
    BONUS_ACTION = "bonus_action"
    REACTION = "reaction"
    LEGENDARY = "legendary"
    LAIR = "lair"
    FREE = "free"


class TargetType(str, Enum):
    """How an action selects its targets."""

    SELF = "self"
    ONE_CREATURE = "one_creature"
    ONE_ALLY = "one_ally"
    ONE_ENEMY = "one_enemy"
    AREA_SPHERE = "area_sphere"
    AREA_CONE = "area_cone"
    AREA_LINE = "area_line"
    AREA_CUBE = "area_cube"
    AREA_CYLINDER = "area_cylinder"


class DamageType(str, Enum):
    """Types of damage in 5e."""

    ACID = "acid"
    BLUDGEONING = "bludgeoning"
    COLD = "cold"
    FIRE = "fire"
    FORCE = "force"
    LIGHTNING = "lightning"
    NECROTIC = "necrotic"
    PIERCING = "piercing"
    POISON = "poison"
    PSYCHIC = "psychic"
    RADIANT = "radiant"
    SLASHING = "slashing"
    THUNDER = "thunder"


class DamageRoll(BaseModel):
    """A damage roll with dice, type, and modifiers."""

    dice: str  # e.g., "2d6"
    damage_type: DamageType
    bonus: int = 0  # Flat bonus
    ability_modifier: str | None = None  # Add this ability mod


class Attack(BaseModel):
    """A weapon or spell attack."""

    name: str
    attack_type: str  # "melee_weapon", "ranged_weapon", "melee_spell", "ranged_spell"
    ability: str  # Ability used for attack roll
    reach: int = 5  # In feet
    range_normal: int | None = None  # For ranged
    range_long: int | None = None  # Disadvantage range
    damage: list[DamageRoll] = Field(default_factory=list)
    damage_on_miss: list[DamageRoll] | None = None  # Some features deal damage on miss
    extra_effects: list[str] = Field(default_factory=list)  # Description of effects
    properties: list[str] = Field(default_factory=list)  # e.g., ["light", "finesse", "thrown"]
    # Counts as magical for overcoming "nonmagical" resistances/immunities.
    # Set on magic-weapon attacks (e.g. by the Oubliette bridge for +X gear);
    # spell attacks and "Magic Weapons" monsters are detected without this flag.
    magical: bool = False
    # The attack hits without a roll (Magic Missile darts). Never crits;
    # range/LOS checks still apply. Distinct from Action.recurring_auto_hit,
    # which only covers re-uses of sustained spells (Witch Bolt).
    auto_hit: bool = False


class SavingThrowEffect(BaseModel):
    """An effect that requires a saving throw."""

    ability: str  # e.g., "dexterity"
    dc: int | None = None  # None = use spellcasting DC
    dc_ability: str | None = None  # For monster abilities: 8 + prof + this mod
    damage_on_fail: list[DamageRoll] = Field(default_factory=list)
    damage_on_success: str = "none"  # "none", "half", "full"
    conditions_on_fail: list[str] = Field(default_factory=list)
    conditions_on_success: list[str] = Field(default_factory=list)
    # Apply conditions_on_fail with NO save-to-end re-save (normally every
    # save-applied condition gets an end-of-turn re-save, the Hold Person
    # pattern). RAW Banishment / Resilient Sphere give the victim no re-save:
    # the condition lasts until concentration ends or it's removed explicitly.
    conditions_no_resave: bool = False


class Action(BaseModel):
    """Any action a creature can take."""

    name: str
    description: str
    action_type: ActionType = ActionType.ACTION

    # Targeting
    target_type: TargetType = TargetType.ONE_CREATURE
    range: int = 5  # In feet
    area_size: int | None = None  # Radius/length for area effects

    # Effects (one or more)
    attack: Attack | None = None
    saving_throw: SavingThrowEffect | None = None
    healing: str | None = None  # Dice expression, e.g., "2d8+3"
    conditions_applied: list[str] = Field(default_factory=list)
    conditions_removed: list[str] = Field(default_factory=list)
    # Dispel Magic (P-DISPEL): strip spell-tagged buffs/conditions from the
    # target — auto for effects at or below the cast slot level, d20 + the
    # caster's spellcasting mod vs DC 10+level above it.
    dispel: bool = False

    # Costs & Limits
    uses_per_rest: int | None = None  # None = unlimited
    rest_type: str | None = None  # "short" or "long"
    current_uses: int | None = None
    resource_cost: dict[str, int] = Field(default_factory=dict)  # e.g., {"ki_points": 2}
    legendary_action_cost: int = 1  # For legendary actions

    # Requirements
    requires_concentration: bool = False
    requires_weapon: str | None = None  # Weapon type required

    # Temporary HP (dice expression, e.g., "1d4+4" or flat "5")
    grants_temporary_hp: str | None = None

    # Zone behaviour (for persistent AoE zones)
    zone_move_cost: str | None = None  # "action" or "bonus_action"
    zone_follows_caster: bool = False  # Zone centers on and moves with caster

    # Vision/obscurement zones (P-VISION-LIGHT): create a sight-affecting
    # zone rather than a damaging one. "fog" = natural heavy obscurement;
    # "darkness" = magical (only truesight/blindsight pierce; suppressed by
    # an overlapping Daylight of >= level); "daylight" = bright light that
    # dispels lower/equal-level magical darkness it overlaps.
    obscuring_zone: str | None = None  # "fog" | "darkness" | "daylight"

    # Teleportation
    teleport_range: int | None = None  # Max teleport distance in feet (e.g., 30 for Misty Step)
    teleport_self: bool = True  # Caster teleports themselves (vs. teleporting a target)
    teleport_passenger: bool = False  # Adjacent willing ally comes along (Dimension Door)
    teleport_origin_effect: str | None = None  # Damage dice at origin (Thunder Step: "3d10")
    teleport_origin_damage_type: str | None = None  # Damage type (e.g., "thunder")

    # Forced Movement (push/pull/slide applied after attack hit or failed save)
    forced_movement_type: str | None = None  # "push", "pull", or "slide"
    forced_movement_distance: int = 0  # Distance in feet (e.g., 10 for Repelling Blast)
    forced_movement_prone: bool = False  # Also knock target prone

    # Terrain modification (terrain-altering spells: Wall of Stone, Spike Growth, Mold Earth)
    terrain_modification: str | None = None  # TerrainType value: "wall", "difficult", "normal", etc.

    # Summoning (path to creature JSON relative to data dir)
    summon_creature: str | None = None  # e.g., "monsters/wolf.json"
    is_wild_shape: bool = False  # If True, 0 HP removes summon and restores original

    # AI Hints
    ai_priority: int = 5  # 1-10 scale for AI decision making
    ai_use_condition: str | None = None  # e.g., "self.hp_percent < 50"

    # Source tracking (for auto-generated actions from equipment)
    source_item: str | None = None  # Item name that generated this action
    # The originating catalog id in the launching app (Oubliette), stamped by its
    # bridge when it generates item actions. Rides through untouched to the handoff
    # result's "consumables_used" so the story side can decrement the exact
    # inventory stack without name-matching. None for native Arena content.
    source_item_id: str | None = None
    # Scroll stack identity riders (C5): which spell (and inscribed level) the
    # consumed stack carries — scroll stacks are keyed (item, spell, level) in
    # the launching app, so the debit must name the exact variant. Ride through
    # to consumables_used like source_item_id. None for non-scroll content.
    source_item_spell: str | None = None
    source_item_spell_level: int | None = None
    # Scroll casting (C5): the action fires AT this slot level without the
    # player picking one — select_action adopts it as the cast level, so the
    # whole upcast machinery (bonus dice, dart counts, target scaling) applies
    # exactly. The scroll IS the cost: resource_cost stays empty.
    fixed_cast_level: int | None = None

    # Buff/Debuff effects applied to target (temporary stat modifications)
    buff_effects: list[BuffEffect] = Field(default_factory=list)
    buff_duration_rounds: int | None = None  # None = concentration-linked or indefinite
    buff_charges: int | None = None  # buff spent after firing N times (Branding Smite = 1)

    # Upcast scaling (spell slot level mechanics)
    spell_level: int | None = None  # Base spell level (3 for Fireball). None = not a spell.
    upcast_damage_dice: str | None = None  # Extra damage dice per step, e.g., "1d6"
    upcast_healing_dice: str | None = None  # Extra healing dice per step, e.g., "1d8"
    upcast_damage_per_levels: int = 1  # Levels per scaling step (1 = every level, 2 = Spiritual Weapon)

    # Cantrip scaling (damage dice scale at character levels 5, 11, 17)
    cantrip_scaling: bool = False  # Marks this action as a cantrip that scales with level
    cantrip_extra_targets: bool = False  # Eldritch Blast: adds extra beams instead of extra dice

    # Creature-type bonus damage (e.g., Divine Smite +1d8 vs undead/fiend)
    creature_type_bonus_damage: str | None = None  # Extra dice vs matching types, e.g., "1d8"
    creature_type_bonus_types: list[str] = Field(default_factory=list)  # e.g., ["undead", "fiend"]

    # Creature-type TARGET filter (C4: Turn Undead) — when non-empty, the
    # effect only affects creatures of these types; everyone else is skipped
    # by the AoE resolvers entirely (not even a save).
    target_creature_types: list[str] = Field(default_factory=list)

    # Reaction trigger (what triggers this reaction, e.g., "when hit by attack")
    reaction_trigger: str | None = None  # Descriptive trigger for reaction-type actions

    # Multi-target support (Magic Missile 3 darts, Scorching Ray 3 rays)
    target_count: int = 1  # Number of targets (darts/rays/beams). 1 = single target.

    # Upcast target scaling (Bane, Hold Person, Banishment get +1 target per level)
    upcast_target_count: int = 0  # Additional targets per slot level above base

    # Damage type choice (Chromatic Orb, Spirit Guardians: caster picks type on cast)
    damage_type_choices: list[str] = Field(default_factory=list)  # Available damage types to choose from. Empty = no choice.

    # Save-to-end linkage for conditions_applied (can target save to end the condition?)
    condition_save_to_end: str | None = None  # Ability to save (e.g., "wisdom"), None = no re-save
    condition_save_to_end_dc: int | None = None  # DC for the save. None = use spell save DC from caster
    condition_duration_type: str = "indefinite"  # "indefinite", "rounds", "end_of_turn", "start_of_turn"
    condition_duration_rounds: int | None = None  # Number of rounds if type is "rounds"
    # Grapple rider (C5): a "grappled" in conditions_applied stores this as the
    # escape-check DC ("escape DC 13" in monster stat blocks). The grapple has
    # no re-save — escaping is its own action (manager.execute_escape_grapple),
    # and a downed grappler releases automatically.
    grapple_escape_dc: int | None = None

    # Recurring action (Sunbeam, Witch Bolt, Spiritual Weapon: re-use on subsequent turns)
    recurring_action_type: str | None = None  # "action" or "bonus_action" to repeat on later turns
    recurring_damage_dice: str | None = None  # Damage on subsequent uses (e.g., "1d12" for Witch Bolt)
    recurring_damage_type: str | None = None  # Damage type for recurring damage
    recurring_auto_hit: bool = False  # Witch Bolt: subsequent hits are automatic (no roll)
    recurring_move_distance: int | None = None  # Spiritual Weapon: move the effect N feet before attacking

    # HP threshold effects (Power Word Kill/Stun, Toll the Dead, Sleep)
    hp_threshold: int | None = None  # Target HP must be <= this for effect (Power Word Kill: 100)
    hp_threshold_effect: str | None = None  # What happens: "kill", "condition", "bonus_damage_die"
    hp_threshold_condition: str | None = None  # Condition applied if effect is "condition" (e.g., "stunned")
    hp_threshold_alt_dice: str | None = None  # Alt damage dice when threshold met (Toll the Dead: "1d12")

    # Chain effect (Chain Lightning: arcs to secondary targets)
    chain_target_count: int = 0  # Number of secondary targets (3 for Chain Lightning)
    chain_range: int = 30  # Range from primary target to find secondaries (feet)
    chain_same_damage: bool = True  # Secondaries take same damage/save as primary

    # Counterspell / spell interruption
    is_counterspell: bool = False  # This action can interrupt another spell being cast
    counterspell_auto_level: int | None = None  # Auto-counters spells at/below this level (3 for Counterspell at base)
    counterspell_check_dc_base: int = 10  # Base DC for ability check (10 + target spell level)

    # Wall spell properties
    is_wall: bool = False  # This action creates a wall
    wall_length: int = 0  # Total length in feet (60 for Wall of Fire)
    wall_height: int = 0  # Height in feet (20 for Wall of Fire)
    wall_thickness: int = 1  # Thickness in feet
    wall_hp_per_panel: int | None = None  # HP per 10ft panel (None = indestructible, e.g., Wall of Force)
    wall_blocks_movement: bool = True  # Whether creatures can pass through
    wall_blocks_los: bool = False  # Whether the wall blocks line of sight
    wall_damage_side: str | None = None  # "one_side" or None; Wall of Fire deals damage on one chosen side
    wall_damage_on_enter: str | None = None  # Damage dice when entering/ending turn in wall, e.g., "5d8"
    wall_damage_type: str | None = None  # Damage type for wall damage, e.g., "fire"

    # Animation (visual effect played during combat)
    animation: str | None = None  # Folder name in assets/animations/

    # Route to built-in standard-action logic ("dash", "disengage", "dodge",
    # "hide") under THIS action's economy slot and resource cost — the shape of
    # Cunning Action / Step of the Wind (bonus-action Dash etc.). The manager's
    # execute_data_standard_action handles these instead of normal resolution.
    standard_effect: str | None = None
