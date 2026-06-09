# D&D 5e Combat Effect System — Design Document v2

## 1. Purpose & Scope

This document defines the data model and behavioral specification for a **universal combat effect system** capable of representing any mechanically automatable spell, class feature, racial ability, cantrip, potion, scroll, or equipment item in D&D 5th Edition.

### 1.1 What This System Is

A combat facilitator. It models the mechanical resolution of abilities during grid-based tactical combat: dealing damage, healing, applying conditions, summoning creatures, modifying stats, and tracking resources.

### 1.2 What This System Is NOT

- **Not a rule enforcer.** The system does not validate whether a level 1 Gnome Fighter "should" have a 9th-level Fireball. The DM reviews character sheets. The system just resolves what the player built.
- **Not a character manager.** Character building happens upstream. This system consumes character sheets and provides the combat resolution layer.
- **Not a narrative tool.** Spells that cannot be mechanically resolved in combat (Wish, Prestidigitation, Mending, most Divination) are excluded entirely. Players may create blank custom entries for personal tracking, but the generator does not attempt to model them.

### 1.3 Design Principles

1. **Everything is a GameEffect.** Spells, cantrips, class features, potions, scrolls, and equipment all share the same root data structure. The only differences are activation method, resource cost, and what effects they produce.
2. **Composability over special-casing.** A spell that damages AND applies a condition is two EffectBlocks in one GameEffect. No unique schemas for "damage spells" vs "debuff spells."
3. **Creature sheets are the universal reference.** Summons, familiars, Wild Shape forms, and Polymorph targets all point to creature sheets that already exist in the engine. No embedded stat blocks.
4. **Full auto-resolution.** When a spell is cast, the system rolls saves, calculates damage, and applies results immediately. No confirmation dialogs.
5. **AoE is grid-aware.** Area effects paint affected tiles and auto-detect tokens within them.
6. **Homebrew-tolerant.** No mechanical restrictions on what players can build. The generator provides structure, not guardrails.

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                       GameEffect (root)                          │
│  Universal container for ANY combat-relevant ability or item     │
├──────────────────────────────────────────────────────────────────┤
│  identity         │  Name, source, description, tags             │
│  activation       │  Action type, trigger conditions             │
│  resource_cost[]  │  Spell slots, Ki, charges, consumable, etc.  │
│  targeting        │  Self, touch, single, multi, AoE grid shape  │
│  effects[]        │  Array of EffectBlocks (mechanical changes)  │
│  duration         │  Rounds, minutes, concentration, permanent   │
│  scaling          │  Upcasting, cantrip level, class level       │
│  automatable      │  true/false — is this mechanically resolved? │
│  spell_meta?      │  Spell-specific: level, school, components   │
│  equipment_meta?  │  Equipment-specific: weapon/armor properties │
└──────────────────────────────────────────────────────────────────┘

          ┌──────────────────────────────┐
          │        EffectBlock           │
          │  One discrete mechanical     │
          │  change to game state        │
          ├──────────────────────────────┤
          │  type (damage, healing,      │
          │    stat_mod, condition, etc.) │
          │  timing (when it fires)      │
          │  saving_throw?               │
          │  attack?                     │
          │  data (type-specific payload)│
          └──────────────────────────────┘

External References:
  - Creature Sheets → summoned creatures, wild shape forms
  - Character Sheets → the caster, the target
  - Grid Engine → tile painting, token detection, range validation
  - Buff/Debuff Tracker → active effects, concentration, duration countdown
```

---

## 3. GameEffect — Top-Level Schema

```typescript
interface GameEffect {
  // ─── IDENTITY ───
  id: string;                          // Unique identifier
  name: string;                        // Display name
  source: string;                      // Freeform origin label: "Wizard", "Druid", "Potion", "Longsword"
  source_type: SourceType;             // Categorization for UI filtering
  description: string;                 // Mechanical description (not flavor)
  tags: string[];                      // Flexible tagging for filtering/search
  automatable: boolean;                // If false: excluded from mechanical resolution.
                                       // Exists only as a label in the spell list.

  // ─── ACTIVATION ───
  activation: ActivationInfo;

  // ─── RESOURCE COST ───
  resource_costs: ResourceCost[];      // What is consumed to use this. Array because some
                                       // abilities cost multiple resources simultaneously.

  // ─── TARGETING ───
  targeting: TargetingInfo;

  // ─── EFFECTS ───
  effects: EffectBlock[];              // The mechanical heart. What happens when this resolves.
  choices?: ChoiceGroup[];             // For spells with player choices (Chromatic Orb damage type,
                                       // Alter Self mode selection). Chosen effects replace or
                                       // supplement the base effects[].

  // ─── DURATION ───
  duration: DurationInfo;

  // ─── SCALING ───
  scaling?: ScalingRule[];             // How this changes with level or resource expenditure.

  // ─── SPELL-SPECIFIC ───
  spell_meta?: SpellMeta;             // Only populated for spells/cantrips.

  // ─── EQUIPMENT-SPECIFIC ───
  equipment_meta?: EquipmentMeta;      // Only populated for weapons, armor, shields, items.

  // ─── CONSUMABLE FLAG ───
  consumable: boolean;                 // If true, this GameEffect is destroyed after one use.
                                       // Applies to potions, scrolls, single-use items.
}

type SourceType =
  | "spell"              // Leveled spell
  | "cantrip"            // Level 0 spell
  | "class_feature"      // Rage, Wild Shape, Sneak Attack, etc.
  | "racial_trait"       // Breath Weapon, Fey Ancestry, etc.
  | "feat"               // Great Weapon Master, Sentinel, etc.
  | "equipment"          // Weapons, armor, shields, wondrous items
  | "potion"             // Consumable liquid
  | "scroll"             // Consumable spell scroll
  | "custom";            // Homebrew / anything else
```

---

## 4. Activation

How does this GameEffect get triggered?

```typescript
interface ActivationInfo {
  type: ActivationType;

  // ─── REACTION TRIGGER ───
  // Required when type is "reaction". Describes what event allows this to fire.
  reaction_trigger?: string;
  // Examples:
  //   "When you are hit by an attack" (Shield)
  //   "When a creature within 60 feet casts a spell" (Counterspell)
  //   "When a creature you can see within 5 feet hits a target other than you" (Sentinel)

  // ─── EXTENDED ACTIVATION TIME ───
  // For abilities that take longer than one action (rare in combat, but exists).
  activation_time?: {
    value: number;
    unit: "round" | "minute";
  };
}

type ActivationType =
  | "action"             // Standard action
  | "bonus_action"       // Bonus action
  | "reaction"           // Triggered reaction
  | "free"               // Free action / no action cost (e.g., dropping a weapon)
  | "passive"            // Always active, no activation needed (Aura of Protection)
  | "equip"              // Put on / take off equipment (the act of equipping)
  | "special";           // Anything else (describe in description field)
```

### 4.1 Equipment Activation

Equipment uses `"equip"` as its activation type. Equipping or unequipping an item toggles its passive effects on/off. Some equipment also has activated abilities (e.g., Flame Tongue's ignite command) — these are modeled as separate GameEffects nested inside the equipment's `equipment_meta.activated_abilities[]`.

---

## 5. Resource Cost

What is consumed when this GameEffect is used?

```typescript
interface ResourceCost {
  type: ResourceType;

  // ─── SPELL SLOTS ───
  slot_level?: number;                 // Minimum spell slot level (1–9)

  // ─── CLASS / CUSTOM RESOURCES ───
  resource_name?: string;              // "Ki Points", "Sorcery Points", "Rage", "Bardic Inspiration",
                                       // or any custom name the player invents
  amount?: number;                     // How many are consumed per use

  // ─── CHARGES (items) ───
  charges_used?: number;

  // ─── RECOVERY ───
  recovery: RecoveryType;

  // ─── PER-REST USES ───
  max_uses?: number;                   // For "use_per_rest" type: how many times before needing rest

  // ─── RECHARGE (monster-style) ───
  recharge_on?: number;                // e.g., 5 means "Recharge 5-6" (roll d6 at start of turn,
                                       // recharges on 5 or higher)
}

type ResourceType =
  | "spell_slot"         // Deducts a spell slot of slot_level or higher
  | "class_resource"     // Deducts from a named resource pool (Ki, Sorcery Points, etc.)
  | "item_charge"        // Deducts charges from a charged item
  | "hit_points"         // Costs HP to use (Blood Hunter features, etc.)
  | "hit_dice"           // Costs hit dice
  | "consumable"         // The item itself is consumed (potions, scrolls)
  | "use_per_rest"       // Limited uses that recover on rest
  | "recharge"           // Monster-style recharge mechanic
  | "none";              // Free to use (cantrips, passive features, at-will abilities)

type RecoveryType =
  | "short_rest"
  | "long_rest"
  | "dawn"               // Recharges at dawn (common for magic items)
  | "recharge_roll"      // Roll at start of turn (monster abilities)
  | "never"              // Once it's gone, it's gone
  | "none";              // No recovery needed (free abilities)
```

---

## 6. Targeting

Who or what does this GameEffect affect, and how does it interact with the grid?

```typescript
interface TargetingInfo {
  type: TargetType;

  // ─── RANGE ───
  range?: {
    value: number;                     // Distance in feet
    unit: "feet" | "miles" | "touch" | "self" | "unlimited";
  };

  // ─── MULTI-TARGET ───
  max_targets?: number;                // "Choose up to 3 creatures" — player selects tokens

  // ─── AREA OF EFFECT (grid integration) ───
  // When present, the grid engine paints affected tiles and auto-detects tokens.
  area?: AoEShape;
}

type TargetType =
  | "self"               // Affects only the caster
  | "touch"              // Must be adjacent on grid
  | "single"             // One target token selected by player
  | "multi"              // Multiple target tokens selected by player (up to max_targets)
  | "area"               // AoE — grid paints tiles, auto-detects tokens
  | "special";           // Unusual targeting (describe in description)

interface AoEShape {
  shape: "sphere" | "cube" | "cone" | "line" | "cylinder" | "wall" | "emanation";
  size: number;                        // Radius for sphere/cylinder/emanation,
                                       // side length for cube,
                                       // length for cone/line/wall. All in feet.
  width?: number;                      // For lines and walls (feet)
  height?: number;                     // For cylinders and walls (feet)

  // Where the area originates
  origin: "self" | "point_in_range" | "target";
  // "self" → centered on caster token (auras, Thunderwave)
  // "point_in_range" → player clicks a grid tile within range
  // "target" → centered on a target token
}
```

### 6.1 AoE Grid Resolution Flow

When a player casts an AoE spell:

1. Player selects the spell and clicks "Cast."
2. If `origin` is `"point_in_range"`: the grid shows a range indicator. Player clicks a tile. The grid paints the AoE shape centered on that tile.
3. If `origin` is `"self"`: the grid immediately paints the AoE shape centered on the caster.
4. If `origin` is `"target"`: player selects a target token, AoE paints centered on that token.
5. The engine auto-detects all tokens within the painted tiles.
6. For each detected token, the engine resolves the spell's effects (saves, damage, conditions).
7. Results are applied immediately.

---

## 7. The EffectBlock System

An `EffectBlock` represents **one discrete mechanical change** to game state. A GameEffect contains one or more EffectBlocks, which are resolved in order.

```typescript
interface EffectBlock {
  id: string;                          // Unique within this GameEffect
  type: EffectType;

  // ─── TIMING ───
  // When does this effect fire relative to the triggering event?
  timing: EffectTiming;
  trigger_condition?: string;          // For "on_trigger": what specific event fires this

  // ─── SAVING THROW ───
  saving_throw?: SavingThrowInfo;      // If present, targets must save

  // ─── ATTACK ROLL ───
  attack?: AttackInfo;                 // If present, caster must roll to hit

  // ─── EFFECT PAYLOAD ───
  // The actual mechanical data. Shape depends on `type`.
  data: EffectData;

  // ─── CONDITIONAL ───
  condition?: string;                  // This effect only applies if condition is met.
                                       // e.g., "If the target is undead", "Paladin is conscious"

  // ─── REPEATING EFFECTS ───
  // For effects that recur each round (e.g., damage from standing in Wall of Fire)
  repeats?: {
    frequency: "start_of_turn" | "end_of_turn" | "each_round";
    max_occurrences?: number;          // Cap on repetitions (null = until duration ends)
  };
}

type EffectTiming =
  | "immediate"          // Resolves right now
  | "start_of_turn"      // Fires at the start of the affected creature's turn
  | "end_of_turn"        // Fires at the end of the affected creature's turn
  | "on_hit"             // Fires when an attack hits (for attack-contingent effects)
  | "on_failed_save"     // Fires only if the target fails its save
  | "on_successful_save" // Fires only if the target succeeds (e.g., half damage)
  | "while_active"       // Continuously active for the duration (buffs, auras)
  | "on_trigger";        // Fires when a specific event occurs (describe in trigger_condition)
```

### 7.1 EffectType — The Complete List

These 12 types cover every mechanically automatable effect in 5e combat.

```typescript
type EffectType =
  | "damage"             // Deal HP damage
  | "healing"            // Restore HP
  | "temp_hp"            // Grant temporary hit points
  | "stat_modifier"      // Modify AC, ability scores, speed, save bonuses, etc.
  | "condition_apply"    // Apply a 5e condition (Frightened, Prone, Stunned, etc.)
  | "condition_remove"   // Remove a condition
  | "movement"           // Grant, restrict, or force movement (fly, teleport, push/pull)
  | "summon"             // Spawn a creature token from a creature sheet reference
  | "transform"          // Swap active character sheet to a creature sheet (Wild Shape, Polymorph)
  | "area_zone"          // Create a persistent area on the grid with ongoing effects
  | "resource_modify"    // Modify resource pools (HP max, spell slots, etc.)
  | "counter";           // Negate another spell or effect (Counterspell, Dispel Magic)
```

**Excluded categories** (not modeled, not in the generator):
- **Utility** (Prestidigitation, Mending, Light) — no combat mechanics
- **Information** (Detect Magic, Identify, Scrying) — no combat mechanics
- **Narrative control** (Wish, Suggestion's open-ended commands) — not automatable

---

## 8. EffectData Definitions

Each `EffectType` has a corresponding data payload. Below is every variant.

### 8.1 DamageData

```typescript
interface DamageData {
  type: "damage";
  dice: DiceExpression;                // "8d6", "1d10+STR", "2d6+CHA"
  damage_type: DamageType;
  half_on_save: boolean;               // If true, targets that succeed on save take half damage.
  bonus_vs?: string;                   // Optional: extra context like "undead" or "fiends"
                                       // (for Smite-like conditional damage — the system applies it,
                                       // but the player decides when to declare it)
}

type DamageType =
  | "fire" | "cold" | "lightning" | "thunder" | "acid" | "poison"
  | "necrotic" | "radiant" | "force" | "psychic"
  | "bludgeoning" | "piercing" | "slashing"
  | "bludgeoning_magical" | "piercing_magical" | "slashing_magical";
```

### 8.2 HealingData

```typescript
interface HealingData {
  type: "healing";
  dice: DiceExpression;                // "2d8+WIS"
  heal_type: "restore_hp" | "restore_hp_max";
  // "restore_hp" — standard healing
  // "restore_hp_max" — restores reduced max HP (e.g., Greater Restoration curing
  //                    max HP reduction from a Wraith's Life Drain)
}
```

### 8.3 TempHPData

```typescript
interface TempHPData {
  type: "temp_hp";
  dice: DiceExpression;                // "1d4+4", "8" (flat value)
  // System rule: temp HP does not stack. Engine takes the higher value
  // if a creature already has temp HP.
}
```

### 8.4 StatModifierData

This is the workhorse for buffs, debuffs, and equipment bonuses.

```typescript
interface StatModifierData {
  type: "stat_modifier";
  stat: StatTarget;
  modification: ModificationType;
  value: number | DiceExpression | string;
  // number: flat bonus/penalty (+2, -5, set to 19)
  // DiceExpression: "1d4" (Bless adds 1d4 to attacks and saves)
  // string: "CHA" (Aura of Protection adds Charisma modifier)

  // Optional: narrow scope of the modifier
  applies_to?: string;
  // Examples:
  //   "attack_rolls" — Bless
  //   "saving_throws" — Bless, Aura of Protection
  //   "Dexterity saving throws" — specific save type
  //   "Stealth checks" — specific skill
  //   "melee_weapon_damage" — Rage
  //   "all" — applies broadly (default if omitted)
}

type StatTarget =
  | "ac"
  | "strength" | "dexterity" | "constitution"
  | "intelligence" | "wisdom" | "charisma"
  | "speed" | "speed_fly" | "speed_swim" | "speed_climb" | "speed_burrow"
  | "attack_bonus"
  | "damage_bonus"
  | "saving_throw_bonus"
  | "spell_save_dc"
  | "proficiency_bonus"
  | "initiative"
  | "hit_points_max"
  | "custom";             // Freeform — use applies_to for specifics

type ModificationType =
  | "bonus"              // Add value to stat (+2 AC, +1d4 to attacks)
  | "penalty"            // Subtract value from stat (-2 STR from Ray of Enfeeblement)
  | "set"                // Set stat to a fixed value (Barkskin sets AC to 16)
  | "multiply"           // Multiply stat (Haste doubles speed)
  | "advantage"          // Grant advantage (value field is ignored)
  | "disadvantage"       // Impose disadvantage (value field is ignored)
  | "resistance"         // Half damage from a damage type (value = the damage type string)
  | "vulnerability"      // Double damage from a damage type
  | "immunity";          // No damage from a damage type
```

### 8.5 ConditionApplyData

```typescript
interface ConditionApplyData {
  type: "condition_apply";
  condition: DndCondition;

  // How the target can end the condition early (if applicable)
  save_to_end?: {
    stat: AbilityStat;
    dc_source: "spell_save_dc" | "class_dc" | "fixed";
    dc_fixed_value?: number;           // Only when dc_source is "fixed"
    frequency: "end_of_turn" | "start_of_turn";
  };
}

type DndCondition =
  | "blinded" | "charmed" | "deafened" | "frightened" | "grappled"
  | "incapacitated" | "invisible" | "paralyzed" | "petrified"
  | "poisoned" | "prone" | "restrained" | "stunned" | "unconscious"
  | "exhaustion";        // Exhaustion has levels 1-6 which the buff/debuff tracker manages
```

### 8.6 ConditionRemoveData

```typescript
interface ConditionRemoveData {
  type: "condition_remove";
  conditions: DndCondition[];          // Which conditions can this remove
  remove_mode: "all" | "choose";       // Remove all listed, or player picks one
  max_removals?: number;               // If "choose": how many can be removed (default 1)
}
```

### 8.7 MovementData

```typescript
interface MovementData {
  type: "movement";
  movement_mode: MovementMode;

  // ─── GRANTING MOVEMENT ───
  speed?: number;                      // In feet. Grants this speed for the movement mode.

  // ─── TELEPORTATION ───
  teleport_range?: number;             // Max teleport distance in feet (Misty Step: 30)

  // ─── FORCED MOVEMENT (push, pull, slide) ───
  forced?: {
    direction: "away" | "toward" | "any" | "up" | "down" | "chosen_by_caster";
    distance: number;                  // In feet
  };
}

type MovementMode =
  | "walk" | "fly" | "swim" | "climb" | "burrow"
  | "hover"              // Fly without falling when speed is 0
  | "teleport";          // Instantaneous repositioning
```

### 8.8 SummonData

**Core concept:** Summoning does not embed stat blocks. The player pre-creates creature sheets in the engine. The GameEffect references those sheets by ID. When the spell resolves, the engine prompts the player to place the creature token on the grid.

```typescript
interface SummonData {
  type: "summon";

  // ─── CREATURE SHEET REFERENCES ───
  // The player links one or more creature sheets during spell creation.
  creature_sheet_ids: string[];        // References to pre-built creature sheets.
                                       // If multiple: player selects which to summon at cast time.

  // ─── COUNT ───
  count: number;                       // How many creatures are summoned (default 1)
                                       // For Conjure Animals at higher levels, this scales.

  // ─── SPAWN BEHAVIOR ───
  spawn: {
    range: number;                     // Max distance from caster to place the token (feet)
    must_be_unoccupied: boolean;       // Token must be placed on an empty tile
    player_chooses_tile: boolean;      // Player clicks where to place (true for almost all summons)
  };

  // ─── SUMMONED CREATURE BEHAVIOR ───
  acts_on: "caster_turn" | "own_initiative" | "immediately_after_caster";
  controlled_by: "player" | "dm";      // Who moves the summoned token during combat

  // ─── PERSISTENCE ───
  persists_if_caster_drops?: boolean;  // Does the summon vanish if caster goes unconscious?
                                       // Concentration spells: yes (handled by concentration system)
                                       // Find Familiar: no (persists independently)

  // ─── MAINTENANCE ───
  // For Animate Dead-style spells: must re-cast within 24 hours to maintain control
  requires_maintenance?: {
    recast_within: number;             // Hours
    cost: ResourceCost;                // The cost to maintain
  };
}
```

### 8.8.1 Summon Resolution Flow

1. Player casts the summon spell. Resource cost is deducted.
2. If `creature_sheet_ids` has multiple entries, a selection menu appears: "Which creature do you want to summon?"
3. Player selects a creature sheet.
4. If `count > 1`, this selection repeats (or the same creature is spawned `count` times — player's choice depending on the spell).
5. Grid enters "placement mode." Player clicks tiles within `spawn.range` to place creature tokens.
6. Creature tokens appear on the grid. They are added to the initiative tracker per `acts_on`.
7. The `controlled_by` field determines who controls the token during combat.
8. When the spell's duration ends (or concentration breaks), creature tokens are removed from the grid.

### 8.9 TransformData

**Core concept:** Transformation swaps the active sheet for a token. The original character sheet is preserved. The engine needs to track both sheets and know when to revert.

```typescript
interface TransformData {
  type: "transform";

  // ─── CREATURE SHEET REFERENCES ───
  // Same pattern as summons: player pre-builds creature sheets for each form.
  form_sheet_ids: string[];            // The forms available. Player picks one at cast time.

  // ─── WHAT IS RETAINED FROM ORIGINAL FORM ───
  // This varies significantly between Wild Shape, Polymorph, and Shapechange.
  // The player configures this when building the GameEffect.
  retained: {
    mental_ability_scores: boolean;    // Keep INT, WIS, CHA from original (Wild Shape: yes)
    class_features: boolean;           // Keep class features (Wild Shape: yes, if form allows)
    proficiencies_if_higher: boolean;  // Keep proficiency if original's is higher
    spellcasting: boolean;             // Can still cast spells in new form? (Wild Shape: no, Shapechange: yes)
  };

  // ─── HIT POINT HANDLING ───
  hp_mode: "separate_pool" | "replace" | "use_new_form";
  // "separate_pool" — Wild Shape: new form has its own HP.
  //                    When it hits 0, you revert with original HP.
  // "replace" — Polymorph: target's HP becomes new form's HP.
  //             Excess damage carries over to original HP on revert.
  // "use_new_form" — Shapechange: you use new form's HP as your HP.

  overflow_damage_carries_over: boolean;  // Does excess damage carry to original form?

  // ─── REVERSION ───
  revert_on_zero_hp: boolean;          // Revert when new form HP = 0
  voluntary_revert: boolean;           // Can the player choose to revert (typically bonus action)
  voluntary_revert_cost?: ActivationType; // What action it costs to voluntarily revert

  // ─── EQUIPMENT ───
  equipment_behavior: "melds" | "drops" | "worn_if_fits";
  // "melds" — equipment merges into new form, effects suppressed (Wild Shape)
  // "drops" — equipment falls to the ground (Polymorph on unwilling target)
  // "worn_if_fits" — keeps equipment if new form can wear it (Shapechange)
}
```

### 8.9.1 Transform Resolution Flow

1. Player activates the transformation ability. Resource cost is deducted.
2. If `form_sheet_ids` has multiple entries, a selection menu appears: "Which form?"
3. The engine stores the current character sheet as "original form."
4. The token's active sheet is swapped to the selected creature sheet.
5. HP is handled per `hp_mode`:
   - `"separate_pool"`: Original HP is stored. Token HP becomes the creature sheet's HP.
   - `"replace"`: Token HP becomes creature sheet HP. Original HP stored for revert.
6. Equipment effects are toggled based on `equipment_behavior`.
7. On revert (HP hits 0, voluntary, or duration ends):
   - Token's active sheet swaps back to original character sheet.
   - HP is restored to stored original HP (minus overflow damage if applicable).
   - Equipment effects are re-applied.

### 8.10 AreaZoneData

Persistent areas on the grid (Wall of Fire, Fog Cloud, Entangle, Silence).

```typescript
interface AreaZoneData {
  type: "area_zone";

  // ─── SHAPE ───
  // Uses the same AoEShape as targeting, but this is a persistent zone.
  zone_shape: AoEShape;

  // ─── EFFECTS ON CREATURES IN THE ZONE ───
  // These are full EffectBlocks that resolve against each creature in the zone.
  effects_on_enter: EffectBlock[];     // When a creature enters or starts turn in the zone
  effects_on_end_of_turn: EffectBlock[];  // At end of a creature's turn if still in zone

  // ─── ZONE PROPERTIES ───
  blocks_vision: boolean;              // Fog Cloud, Darkness — tokens inside are unseen
  difficult_terrain: boolean;          // Entangle, Spike Growth — movement costs double
  blocks_movement: boolean;            // Wall of Force — cannot pass through
  blocks_projectiles: boolean;         // Wall of Force, Wind Wall

  // ─── ZONE MOBILITY ───
  movable: boolean;                    // Can the caster move the zone on their turn?
  move_cost?: ActivationType;          // What action type it costs to move (usually "action" or "bonus_action")
  move_range?: number;                 // How far it can be moved per turn (feet)
}
```

### 8.11 ResourceModifyData

```typescript
interface ResourceModifyData {
  type: "resource_modify";
  target_resource: "hit_points_max" | "spell_slot" | "class_resource" | "hit_dice";
  modification: "increase" | "decrease" | "restore";
  value: number | DiceExpression;
  resource_name?: string;              // For class_resource: which resource
  slot_level?: number;                 // For spell_slot: which level of slot is affected
}
```

### 8.12 CounterData

```typescript
interface CounterData {
  type: "counter";
  counter_mode: "counterspell" | "dispel" | "custom";

  // Auto-success threshold: if the target spell/effect is at or below this level,
  // the counter succeeds automatically.
  auto_success_level: number;

  // For higher-level targets: an ability check is required.
  ability_check?: {
    stat: AbilityStat | "spellcasting"; // What to roll
    dc_formula: string;                 // "10 + spell_level" — the engine parses this
  };
}
```

---

## 9. Saving Throws and Attack Rolls

### 9.1 SavingThrowInfo

```typescript
interface SavingThrowInfo {
  stat: AbilityStat;
  dc_source: "spell_save_dc" | "class_dc" | "fixed" | "item_dc";
  dc_fixed_value?: number;             // Only when dc_source is "fixed"

  // What happens on a successful save
  on_success: "no_effect" | "half_damage" | "custom";
  on_success_custom?: string;          // Description if "custom"

  // Repeated saves (for effects that last multiple rounds)
  repeat_save?: {
    frequency: "end_of_turn" | "start_of_turn";
    ends_on_success: boolean;          // Does a successful save end the effect?
  };
}
```

### 9.2 AttackInfo

```typescript
interface AttackInfo {
  type: "melee_spell" | "ranged_spell" | "melee_weapon" | "ranged_weapon";
  stat: AbilityStat | "spellcasting";  // Which modifier to add to the roll
  bonus?: number;                      // Additional flat bonus (+1 magic weapon, etc.)

  // Crit behavior
  crit_range?: number;                 // Natural roll needed to crit (default: 20, Champion Fighter: 19)
  crit_extra_dice?: DiceExpression;    // Extra dice on crit beyond the normal doubling (Brutal Critical)
}
```

### 9.3 Resolution Rules

- **Attack rolls and saving throws are mutually exclusive per EffectBlock.** A single effect either requires an attack roll OR a saving throw, never both. (This is a 5e design rule, not a system restriction — homebrew can break it if they want since we don't enforce.)
- **Auto-resolution flow for attacks:** Roll d20 + stat modifier + bonus. Compare to target AC. If hit, resolve damage and on_hit effects.
- **Auto-resolution flow for saves:** Each affected target rolls d20 + relevant save modifier. Compare to DC. Resolve effects based on success or failure.

---

## 10. Choices

Some spells give the player a choice that affects which effects are applied.

```typescript
interface ChoiceGroup {
  id: string;
  prompt: string;                      // Displayed to the player: "Choose a damage type"
  options: ChoiceOption[];
  max_choices: number;                 // Usually 1
  choose_at: "cast_time" | "each_turn"; // When the choice is made
                                        // "cast_time" — Chromatic Orb: pick damage type once
                                        // "each_turn" — some abilities let you choose each round
}

interface ChoiceOption {
  label: string;                       // "Fire", "Cold", "Acid", etc.
  effects: EffectBlock[];              // What happens if this option is chosen.
                                       // These REPLACE the base effects[] for this choice.
}
```

### 10.1 Example: Chromatic Orb

The base `effects[]` array is empty. The `choices` array contains one `ChoiceGroup` with options for each damage type, each containing a DamageData EffectBlock with the appropriate type.

### 10.2 Example: Alter Self

Three `ChoiceOption` entries: "Aquatic Adaptation" (grants swim speed), "Change Appearance" (excluded — narrative only), "Natural Weapons" (grants a natural weapon attack).

---

## 11. Scaling System

### 11.1 ScalingRule

```typescript
interface ScalingRule {
  type: ScalingType;

  // ─── WHAT CHANGES ───
  target_effect_id: string;            // Which EffectBlock is modified
  target_field: string;                // Dot-path to the field: "data.dice", "data.value", "count"

  // ─── HOW IT CHANGES (linear scaling) ───
  per_increment?: {
    increment_value: DiceExpression | number;  // "+1d6" per level above base
    base_level?: number;               // Upcasting: the spell's base level
  };

  // ─── HOW IT CHANGES (breakpoint scaling) ───
  breakpoints?: ScalingBreakpoint[];   // For non-linear scaling (cantrips, class features)

  // ─── ADDITIONAL EFFECTS AT THRESHOLD ───
  // Some abilities unlock entirely new EffectBlocks at certain levels.
  additional_effects?: {
    threshold: number;                 // Level or slot at which new effects unlock
    effects: EffectBlock[];
  }[];
}

interface ScalingBreakpoint {
  level: number;                       // Character level, class level, or spell slot level
  value: DiceExpression | number | any; // The new value at this breakpoint
}

type ScalingType =
  | "upcast"             // Per spell slot level above base (Fireball: +1d6 per level above 3rd)
  | "cantrip_level"      // Per character level breakpoints (5, 11, 17)
  | "class_level"        // Per class level (Sneak Attack, Wild Shape CR limits)
  | "character_level";   // Per total character level
```

### 11.2 Cantrip Scaling Example: Eldritch Blast

Eldritch Blast gains additional beams (separate attack rolls) at character levels 5, 11, and 17. This is modeled as scaling the number of times the base EffectBlock resolves.

```json
{
  "type": "cantrip_level",
  "target_effect_id": "eldritch-blast-beam",
  "target_field": "repeat_count",
  "breakpoints": [
    { "level": 1, "value": 1 },
    { "level": 5, "value": 2 },
    { "level": 11, "value": 3 },
    { "level": 17, "value": 4 }
  ]
}
```

Each beam is a separate attack roll against potentially different targets.

### 11.3 Upcast Example: Fireball

```json
{
  "type": "upcast",
  "target_effect_id": "fireball-damage",
  "target_field": "data.dice",
  "per_increment": {
    "increment_value": "1d6",
    "base_level": 3
  }
}
```

Cast at 5th level → 8d6 + 2d6 = 10d6 fire damage.

### 11.4 Class Level Scaling Example: Sneak Attack

```json
{
  "type": "class_level",
  "target_effect_id": "sneak-attack-damage",
  "target_field": "data.dice",
  "breakpoints": [
    { "level": 1, "value": "1d6" },
    { "level": 3, "value": "2d6" },
    { "level": 5, "value": "3d6" },
    { "level": 7, "value": "4d6" },
    { "level": 9, "value": "5d6" },
    { "level": 11, "value": "6d6" },
    { "level": 13, "value": "7d6" },
    { "level": 15, "value": "8d6" },
    { "level": 17, "value": "9d6" },
    { "level": 19, "value": "10d6" }
  ]
}
```

---

## 12. Spell Metadata

Only populated when `source_type` is `"spell"` or `"cantrip"`.

```typescript
interface SpellMeta {
  level: number;                       // 0 for cantrips, 1-9 for leveled
  school: SpellSchool;
  components: {
    verbal: boolean;
    somatic: boolean;
    material: boolean;
    material_description?: string;     // "a tiny ball of bat guano and sulfur"
    material_consumed?: boolean;
    material_gp_value?: number;        // e.g., 300 for Revivify's diamond
  };
  concentration: boolean;
  ritual: boolean;                     // Excluded from combat since rituals take 10+ minutes,
                                       // but included for completeness if players want to track it.
}

type SpellSchool =
  | "abjuration" | "conjuration" | "divination" | "enchantment"
  | "evocation" | "illusion" | "necromancy" | "transmutation";
```

---

## 13. Equipment System

Equipment items are GameEffects with `source_type: "equipment"` and `activation.type: "equip"`. They have passive effects (always active while equipped) and may have activated abilities.

### 13.1 EquipmentMeta

```typescript
interface EquipmentMeta {
  slot: EquipmentSlot;
  equipment_type: EquipmentType;

  // ─── WEAPON PROPERTIES ───
  weapon?: WeaponProperties;

  // ─── ARMOR PROPERTIES ───
  armor?: ArmorProperties;

  // ─── CHARGES ───
  charges?: {
    max: number;
    current: number;                   // Tracked during combat
    recovery: RecoveryType;
    recovery_amount?: DiceExpression;  // "1d6+1" charges recovered at dawn
    destroyed_on_empty: boolean;       // Item destroyed when last charge used?
    destroy_roll?: number;             // "Roll d20; on a 1, destroyed" — threshold value
  };

  // ─── PASSIVE EFFECTS ───
  // These are EffectBlocks that are active whenever the item is equipped.
  // Toggled on/off by the equip/unequip action.
  passive_effects: EffectBlock[];

  // ─── ACTIVATED ABILITIES ───
  // Full GameEffects that can be triggered while the item is equipped.
  // e.g., Wand of Fireballs: "spend 3 charges to cast Fireball"
  // e.g., Flame Tongue: "speak the command word to ignite (bonus action)"
  activated_abilities?: GameEffect[];

  // ─── ITEM INFO ───
  rarity?: "common" | "uncommon" | "rare" | "very_rare" | "legendary" | "artifact";
  requires_attunement: boolean;
  weight?: number;                     // Pounds (informational only)
}

type EquipmentSlot =
  | "main_hand"          // Weapon or shield
  | "off_hand"           // Shield, second weapon, or free (for two-handing)
  | "both_hands"         // Two-handed weapon or versatile weapon used two-handed
  | "armor"              // Body armor
  | "head" | "cloak" | "gloves" | "boots" | "belt"
  | "ring_1" | "ring_2"
  | "amulet"
  | "other";             // Wondrous items without a specific slot

type EquipmentType =
  | "weapon" | "armor" | "shield"
  | "wand" | "staff" | "rod"
  | "ring" | "amulet" | "cloak"
  | "potion" | "scroll"
  | "wondrous" | "ammunition" | "other";
```

### 13.2 WeaponProperties

```typescript
interface WeaponProperties {
  category: "simple_melee" | "simple_ranged" | "martial_melee" | "martial_ranged";
  damage_dice: DiceExpression;         // "1d8", "2d6"
  damage_type: DamageType;             // "slashing", "piercing", "bludgeoning"
  properties: WeaponPropertyTag[];
  range_normal?: number;               // For ranged/thrown: normal range in feet
  range_long?: number;                 // Long range in feet (attacks at disadvantage)
  magic_bonus?: number;                // +1, +2, +3 (added to attack and damage)

  // ─── VERSATILE ───
  versatile_dice?: DiceExpression;     // Damage dice when used two-handed: "1d10"
                                       // When player switches to two-hand grip, the system uses this.

  // ─── EXTRA DAMAGE ───
  // For magical weapons with bonus damage (Flame Tongue, Frostbrand)
  extra_damage?: {
    dice: DiceExpression;
    damage_type: DamageType;
    active_condition?: string;         // "While ignited" — ties to an activated ability toggle
  }[];
}

type WeaponPropertyTag =
  | "ammunition" | "finesse" | "heavy" | "light" | "loading"
  | "reach" | "thrown" | "two_handed" | "versatile"
  | "silvered" | "magical";
```

### 13.3 ArmorProperties

```typescript
interface ArmorProperties {
  category: "light" | "medium" | "heavy" | "shield";
  base_ac: number;                     // 11 for leather, 14 for chain shirt, 18 for plate, 2 for shield
  max_dex_bonus: number | null;        // null = unlimited (light), 2 (medium), 0 (heavy)
  strength_requirement?: number;       // 13 for chain mail, 15 for plate
  stealth_disadvantage: boolean;
  magic_bonus?: number;                // +1, +2, +3 (added to AC)
}
```

### 13.4 Equipment Resolution: Equip/Unequip Flow

1. Player selects equipment item and clicks "Equip" or "Unequip."
2. **On Equip:**
   - Slot conflict check: if the slot is occupied, the existing item is unequipped first.
   - Special case: equipping a `both_hands` weapon unequips both `main_hand` and `off_hand`.
   - Special case: equipping a shield in `off_hand` while wielding a `both_hands` weapon forces the weapon to drop or switch to one-handed (if versatile).
   - All `passive_effects` from the item are applied to the character's stats via the buff/debuff tracker.
   - `activated_abilities` become available in the character's action list.
3. **On Unequip:**
   - All `passive_effects` are removed from the character's stats.
   - `activated_abilities` are removed from the action list.
   - Any active toggled effects (e.g., Flame Tongue's ignite) are deactivated.

### 13.5 Versatile Weapon Grip Toggle

Versatile weapons need a grip toggle: one-handed (uses `damage_dice`) vs two-handed (uses `versatile_dice`).

- When equipped in `main_hand` with something in `off_hand` → one-handed automatically.
- When equipped in `main_hand` with `off_hand` empty → player can toggle grip.
- Toggling to two-handed: slot changes to `both_hands`, uses `versatile_dice`.
- Toggling back: slot changes to `main_hand`, `off_hand` becomes available.
- This toggle should be a free action (no action cost).

---

## 14. Potion & Scroll Handling

### 14.1 Potions

Potions are GameEffects with:
- `source_type: "potion"`
- `consumable: true`
- `activation.type:` whatever the player sets (action or bonus_action — house rules vary)
- `targeting.type: "self"` (most potions) or `"touch"` (administering to an unconscious ally)
- Standard `effects[]` array with healing, stat mods, or whatever the potion does

No special subsystem needed. The consumable flag tells the engine to remove the item after use.

### 14.2 Scrolls

Spell scrolls are GameEffects with:
- `source_type: "scroll"`
- `consumable: true`
- `activation.type: "action"`
- The scroll's effects mirror the contained spell, but with fixed DC and attack bonus per the scroll level table.

**Scroll Save DC & Attack Bonus Table** (hardcoded in engine):

| Spell Level | Save DC | Attack Bonus |
|-------------|---------|--------------|
| Cantrip     | 13      | +5           |
| 1st         | 13      | +5           |
| 2nd         | 13      | +5           |
| 3rd         | 15      | +7           |
| 4th         | 15      | +7           |
| 5th         | 17      | +9           |
| 6th         | 17      | +9           |
| 7th         | 18      | +10          |
| 8th         | 18      | +10          |
| 9th         | 19      | +11          |

When a scroll is created in the generator, the player specifies the spell level. The engine overrides the spell's normal DC/attack bonus with the scroll's fixed values. This override is stored in the scroll's `equipment_meta` or as a top-level field:

```typescript
interface ScrollOverrides {
  scroll_spell_level: number;
  scroll_save_dc: number;             // Looked up from the table above
  scroll_attack_bonus: number;        // Looked up from the table above
}
```

---

## 15. Duration & the Buff/Debuff Tracker

### 15.1 DurationInfo

```typescript
interface DurationInfo {
  type: DurationType;
  value?: number;
  unit?: "round" | "minute" | "hour";

  // If the effect becomes permanent after sustaining concentration
  becomes_permanent?: boolean;         // e.g., some effects last "until dispelled"
                                       // after full concentration duration
}

type DurationType =
  | "instantaneous"      // Resolves and done (Fireball, Cure Wounds)
  | "timed"              // Lasts for value × unit, then expires
  | "concentration"      // Lasts for value × unit, requires concentration, breakable
  | "until_dispelled"    // Lasts until actively removed
  | "permanent"          // Lasts forever (or until a condition is met)
  | "special";           // Unusual duration — described in GameEffect.description
```

### 15.2 Integration with Existing Buff/Debuff Tracker

The engine already tracks buffs and debuffs. When a GameEffect with a non-instantaneous duration resolves:

1. **Register with tracker:** The effect is added to the buff/debuff tracker on the affected token(s) with its duration, source (caster), and all active EffectBlocks.
2. **Duration countdown:** The tracker decrements each round. When duration expires, all associated EffectBlocks are removed.
3. **Concentration:** If `duration.type === "concentration"`:
   - The caster is flagged as concentrating on this effect.
   - If the caster takes damage, the engine auto-rolls a Constitution save (DC = max(10, damage/2)).
   - On failure: concentration breaks, effect is removed from all targets, summoned tokens are removed, transformed characters revert.
   - If the caster casts another concentration spell: previous concentration effect ends automatically.
4. **Stat modifier cleanup:** When a stat_modifier EffectBlock expires, the engine reverses the modification. For "bonus" effects, the bonus is removed. For "set" effects, the stat reverts to its pre-set value (engine must store the original).

---

## 16. Complete Worked Examples

### 16.1 Fireball (Damage AoE Spell)

```json
{
  "id": "fireball",
  "name": "Fireball",
  "source": "Wizard",
  "source_type": "spell",
  "description": "A bright streak flashes to a point within range and then blossoms with a low roar into a 20-foot-radius sphere of fire.",
  "tags": ["evocation", "fire", "aoe", "damage"],
  "automatable": true,
  "activation": { "type": "action" },
  "resource_costs": [{ "type": "spell_slot", "slot_level": 3, "recovery": "long_rest" }],
  "targeting": {
    "type": "area",
    "range": { "value": 150, "unit": "feet" },
    "area": { "shape": "sphere", "size": 20, "origin": "point_in_range" }
  },
  "effects": [{
    "id": "fireball-damage",
    "type": "damage",
    "timing": "immediate",
    "saving_throw": {
      "stat": "dexterity",
      "dc_source": "spell_save_dc",
      "on_success": "half_damage",
      "repeat_save": null
    },
    "data": {
      "type": "damage",
      "dice": "8d6",
      "damage_type": "fire",
      "half_on_save": true
    }
  }],
  "duration": { "type": "instantaneous" },
  "scaling": [{
    "type": "upcast",
    "target_effect_id": "fireball-damage",
    "target_field": "data.dice",
    "per_increment": { "increment_value": "1d6", "base_level": 3 }
  }],
  "spell_meta": {
    "level": 3,
    "school": "evocation",
    "components": { "verbal": true, "somatic": true, "material": true, "material_description": "a tiny ball of bat guano and sulfur" },
    "concentration": false,
    "ritual": false
  },
  "consumable": false
}
```

### 16.2 Wild Shape (Class Feature — Transformation)

```json
{
  "id": "wild-shape",
  "name": "Wild Shape",
  "source": "Druid",
  "source_type": "class_feature",
  "description": "Magically assume the shape of a beast you have seen before.",
  "tags": ["druid", "transformation"],
  "automatable": true,
  "activation": { "type": "action" },
  "resource_costs": [{
    "type": "use_per_rest",
    "max_uses": 2,
    "recovery": "short_rest"
  }],
  "targeting": { "type": "self" },
  "effects": [{
    "id": "wild-shape-transform",
    "type": "transform",
    "timing": "immediate",
    "data": {
      "type": "transform",
      "form_sheet_ids": ["brown-bear-sheet", "dire-wolf-sheet", "giant-spider-sheet"],
      "retained": {
        "mental_ability_scores": true,
        "class_features": true,
        "proficiencies_if_higher": true,
        "spellcasting": false
      },
      "hp_mode": "separate_pool",
      "overflow_damage_carries_over": true,
      "revert_on_zero_hp": true,
      "voluntary_revert": true,
      "voluntary_revert_cost": "bonus_action",
      "equipment_behavior": "melds"
    }
  }],
  "duration": {
    "type": "timed",
    "value": null,
    "unit": "hour"
  },
  "scaling": [{
    "type": "class_level",
    "target_effect_id": "wild-shape-transform",
    "target_field": "duration.value",
    "breakpoints": [
      { "level": 2, "value": 1 },
      { "level": 4, "value": 2 },
      { "level": 8, "value": 4 }
    ]
  }],
  "consumable": false
}
```

**Note:** The `form_sheet_ids` reference creature sheets the player has already built. The player creates a "Brown Bear" creature sheet, a "Dire Wolf" creature sheet, etc. When they activate Wild Shape, a menu appears asking which form they want.

### 16.3 Animate Dead (Summoning Spell with Maintenance)

```json
{
  "id": "animate-dead",
  "name": "Animate Dead",
  "source": "Wizard",
  "source_type": "spell",
  "description": "Create an undead servant from a pile of bones or a corpse.",
  "tags": ["necromancy", "summoning", "undead"],
  "automatable": true,
  "activation": {
    "type": "special",
    "activation_time": { "value": 1, "unit": "minute" }
  },
  "resource_costs": [{ "type": "spell_slot", "slot_level": 3, "recovery": "long_rest" }],
  "targeting": {
    "type": "single",
    "range": { "value": 10, "unit": "feet" }
  },
  "effects": [{
    "id": "animate-dead-summon",
    "type": "summon",
    "timing": "immediate",
    "data": {
      "type": "summon",
      "creature_sheet_ids": ["skeleton-sheet", "zombie-sheet"],
      "count": 1,
      "spawn": {
        "range": 10,
        "must_be_unoccupied": true,
        "player_chooses_tile": true
      },
      "acts_on": "immediately_after_caster",
      "controlled_by": "player",
      "persists_if_caster_drops": true,
      "requires_maintenance": {
        "recast_within": 24,
        "cost": { "type": "spell_slot", "slot_level": 3, "recovery": "long_rest" }
      }
    }
  }],
  "duration": { "type": "special" },
  "scaling": [{
    "type": "upcast",
    "target_effect_id": "animate-dead-summon",
    "target_field": "data.count",
    "per_increment": { "increment_value": 2, "base_level": 3 }
  }],
  "spell_meta": {
    "level": 3,
    "school": "necromancy",
    "components": { "verbal": true, "somatic": true, "material": true, "material_description": "a drop of blood, a piece of flesh, and a pinch of bone dust" },
    "concentration": false,
    "ritual": false
  },
  "consumable": false
}
```

### 16.4 Shield (Reaction Spell)

```json
{
  "id": "shield-spell",
  "name": "Shield",
  "source": "Wizard",
  "source_type": "spell",
  "description": "An invisible barrier of magical force appears and protects you. +5 AC until the start of your next turn, including against the triggering attack.",
  "tags": ["abjuration", "reaction", "defense"],
  "automatable": true,
  "activation": {
    "type": "reaction",
    "reaction_trigger": "When you are hit by an attack or targeted by the magic missile spell"
  },
  "resource_costs": [{ "type": "spell_slot", "slot_level": 1, "recovery": "long_rest" }],
  "targeting": { "type": "self" },
  "effects": [{
    "id": "shield-ac",
    "type": "stat_modifier",
    "timing": "immediate",
    "data": {
      "type": "stat_modifier",
      "stat": "ac",
      "modification": "bonus",
      "value": 5
    }
  }],
  "duration": { "type": "timed", "value": 1, "unit": "round" },
  "spell_meta": {
    "level": 1,
    "school": "abjuration",
    "components": { "verbal": true, "somatic": true, "material": false },
    "concentration": false,
    "ritual": false
  },
  "consumable": false
}
```

### 16.5 +1 Shield (Equipment)

```json
{
  "id": "plus-1-shield",
  "name": "+1 Shield",
  "source": "Magic Item",
  "source_type": "equipment",
  "description": "A shield with a +1 magical bonus to AC (total +3 AC when equipped).",
  "tags": ["armor", "shield", "magical"],
  "automatable": true,
  "activation": { "type": "equip" },
  "resource_costs": [{ "type": "none", "recovery": "none" }],
  "targeting": { "type": "self" },
  "effects": [{
    "id": "shield-ac-passive",
    "type": "stat_modifier",
    "timing": "while_active",
    "data": {
      "type": "stat_modifier",
      "stat": "ac",
      "modification": "bonus",
      "value": 3
    }
  }],
  "duration": { "type": "permanent" },
  "consumable": false,
  "equipment_meta": {
    "slot": "off_hand",
    "equipment_type": "shield",
    "armor": {
      "category": "shield",
      "base_ac": 2,
      "max_dex_bonus": null,
      "stealth_disadvantage": false,
      "magic_bonus": 1
    },
    "requires_attunement": false,
    "passive_effects": [],
    "charges": null
  }
}
```

### 16.6 Flame Tongue Longsword (Weapon with Activated Ability)

```json
{
  "id": "flame-tongue-longsword",
  "name": "Flame Tongue Longsword",
  "source": "Magic Item",
  "source_type": "equipment",
  "description": "A magical longsword that can be ignited to deal extra fire damage.",
  "tags": ["weapon", "sword", "fire", "magical"],
  "automatable": true,
  "activation": { "type": "equip" },
  "resource_costs": [{ "type": "none", "recovery": "none" }],
  "targeting": { "type": "self" },
  "effects": [],
  "duration": { "type": "permanent" },
  "consumable": false,
  "equipment_meta": {
    "slot": "main_hand",
    "equipment_type": "weapon",
    "weapon": {
      "category": "martial_melee",
      "damage_dice": "1d8",
      "damage_type": "slashing",
      "properties": ["versatile", "magical"],
      "versatile_dice": "1d10",
      "magic_bonus": 0,
      "extra_damage": [{
        "dice": "2d6",
        "damage_type": "fire",
        "active_condition": "ignited"
      }]
    },
    "requires_attunement": true,
    "passive_effects": [],
    "activated_abilities": [{
      "id": "flame-tongue-ignite",
      "name": "Ignite Flame Tongue",
      "source": "Flame Tongue Longsword",
      "source_type": "equipment",
      "description": "Speak the command word to ignite or extinguish the blade.",
      "tags": ["toggle", "fire"],
      "automatable": true,
      "activation": { "type": "bonus_action" },
      "resource_costs": [{ "type": "none", "recovery": "none" }],
      "targeting": { "type": "self" },
      "effects": [{
        "id": "ignite-toggle",
        "type": "stat_modifier",
        "timing": "while_active",
        "data": {
          "type": "stat_modifier",
          "stat": "custom",
          "modification": "bonus",
          "value": 0,
          "applies_to": "flame_tongue_ignited"
        }
      }],
      "duration": { "type": "until_dispelled" },
      "consumable": false
    }],
    "charges": null
  }
}
```

**Note on the ignite toggle:** The `"active_condition": "ignited"` on the weapon's `extra_damage` references the toggle state set by the activated ability. When the "Ignite" ability is active (tracked by the buff/debuff system), the weapon's extra 2d6 fire damage is included in attack rolls. When deactivated, it isn't. The engine needs to check for active conditions on extra damage at attack resolution time.

### 16.7 Potion of Greater Healing

```json
{
  "id": "potion-of-greater-healing",
  "name": "Potion of Greater Healing",
  "source": "Potion",
  "source_type": "potion",
  "description": "Drink to regain 4d4+4 hit points.",
  "tags": ["healing", "consumable"],
  "automatable": true,
  "activation": { "type": "bonus_action" },
  "resource_costs": [{ "type": "consumable", "recovery": "never" }],
  "targeting": { "type": "self" },
  "effects": [{
    "id": "potion-heal",
    "type": "healing",
    "timing": "immediate",
    "data": {
      "type": "healing",
      "dice": "4d4+4",
      "heal_type": "restore_hp"
    }
  }],
  "duration": { "type": "instantaneous" },
  "consumable": true
}
```

### 16.8 Chromatic Orb (Choice Spell)

```json
{
  "id": "chromatic-orb",
  "name": "Chromatic Orb",
  "source": "Sorcerer",
  "source_type": "spell",
  "description": "Hurl a sphere of energy. Choose acid, cold, fire, lightning, poison, or thunder damage.",
  "tags": ["evocation", "damage", "choice"],
  "automatable": true,
  "activation": { "type": "action" },
  "resource_costs": [{ "type": "spell_slot", "slot_level": 1, "recovery": "long_rest" }],
  "targeting": {
    "type": "single",
    "range": { "value": 90, "unit": "feet" }
  },
  "effects": [],
  "choices": [{
    "id": "damage-type-choice",
    "prompt": "Choose a damage type",
    "max_choices": 1,
    "choose_at": "cast_time",
    "options": [
      {
        "label": "Acid",
        "effects": [{
          "id": "chromatic-orb-acid", "type": "damage", "timing": "immediate",
          "attack": { "type": "ranged_spell", "stat": "spellcasting" },
          "data": { "type": "damage", "dice": "3d8", "damage_type": "acid", "half_on_save": false }
        }]
      },
      {
        "label": "Cold",
        "effects": [{
          "id": "chromatic-orb-cold", "type": "damage", "timing": "immediate",
          "attack": { "type": "ranged_spell", "stat": "spellcasting" },
          "data": { "type": "damage", "dice": "3d8", "damage_type": "cold", "half_on_save": false }
        }]
      },
      {
        "label": "Fire",
        "effects": [{
          "id": "chromatic-orb-fire", "type": "damage", "timing": "immediate",
          "attack": { "type": "ranged_spell", "stat": "spellcasting" },
          "data": { "type": "damage", "dice": "3d8", "damage_type": "fire", "half_on_save": false }
        }]
      },
      {
        "label": "Lightning",
        "effects": [{
          "id": "chromatic-orb-lightning", "type": "damage", "timing": "immediate",
          "attack": { "type": "ranged_spell", "stat": "spellcasting" },
          "data": { "type": "damage", "dice": "3d8", "damage_type": "lightning", "half_on_save": false }
        }]
      },
      {
        "label": "Poison",
        "effects": [{
          "id": "chromatic-orb-poison", "type": "damage", "timing": "immediate",
          "attack": { "type": "ranged_spell", "stat": "spellcasting" },
          "data": { "type": "damage", "dice": "3d8", "damage_type": "poison", "half_on_save": false }
        }]
      },
      {
        "label": "Thunder",
        "effects": [{
          "id": "chromatic-orb-thunder", "type": "damage", "timing": "immediate",
          "attack": { "type": "ranged_spell", "stat": "spellcasting" },
          "data": { "type": "damage", "dice": "3d8", "damage_type": "thunder", "half_on_save": false }
        }]
      }
    ]
  }],
  "duration": { "type": "instantaneous" },
  "scaling": [{
    "type": "upcast",
    "target_effect_id": "chromatic-orb-acid",
    "target_field": "data.dice",
    "per_increment": { "increment_value": "1d8", "base_level": 1 }
  }],
  "spell_meta": {
    "level": 1,
    "school": "evocation",
    "components": { "verbal": true, "somatic": true, "material": true, "material_description": "a diamond worth at least 50 gp", "material_gp_value": 50 },
    "concentration": false,
    "ritual": false
  },
  "consumable": false
}
```

**Note on Chromatic Orb scaling:** The scaling rule references one effect ID, but the engine should apply the same upcast scaling to whichever option the player picks. Implementation can either duplicate the scaling rule for each option or have the engine infer that all choices scale identically when they share the same base dice pattern.

### 16.9 Wall of Fire (Persistent Area Zone)

```json
{
  "id": "wall-of-fire",
  "name": "Wall of Fire",
  "source": "Wizard",
  "source_type": "spell",
  "description": "Create a wall of fire on the grid. One side (chosen at cast) deals 5d8 fire damage to creatures within 10 feet when they enter or start their turn there.",
  "tags": ["evocation", "fire", "zone", "concentration"],
  "automatable": true,
  "activation": { "type": "action" },
  "resource_costs": [{ "type": "spell_slot", "slot_level": 4, "recovery": "long_rest" }],
  "targeting": {
    "type": "area",
    "range": { "value": 120, "unit": "feet" },
    "area": { "shape": "wall", "size": 60, "width": 1, "height": 20, "origin": "point_in_range" }
  },
  "effects": [{
    "id": "wall-zone",
    "type": "area_zone",
    "timing": "immediate",
    "data": {
      "type": "area_zone",
      "zone_shape": { "shape": "wall", "size": 60, "width": 1, "height": 20, "origin": "point_in_range" },
      "effects_on_enter": [{
        "id": "wall-fire-damage",
        "type": "damage",
        "timing": "immediate",
        "saving_throw": {
          "stat": "dexterity",
          "dc_source": "spell_save_dc",
          "on_success": "half_damage"
        },
        "data": {
          "type": "damage",
          "dice": "5d8",
          "damage_type": "fire",
          "half_on_save": true
        }
      }],
      "effects_on_end_of_turn": [],
      "blocks_vision": false,
      "difficult_terrain": false,
      "blocks_movement": false,
      "blocks_projectiles": false,
      "movable": false
    }
  }],
  "duration": { "type": "concentration", "value": 1, "unit": "minute" },
  "scaling": [{
    "type": "upcast",
    "target_effect_id": "wall-fire-damage",
    "target_field": "data.dice",
    "per_increment": { "increment_value": "1d8", "base_level": 4 }
  }],
  "spell_meta": {
    "level": 4,
    "school": "evocation",
    "components": { "verbal": true, "somatic": true, "material": true, "material_description": "a small piece of phosphorus" },
    "concentration": true,
    "ritual": false
  },
  "consumable": false
}
```

---

## 17. Generator UI Flow

### 17.1 Template Selection

When a player opens the ability/spell generator, they first pick a starting template:

| Template | Pre-fills |
|----------|-----------|
| **Attack Spell** | Activation: action. Targeting: single/area. Effect: damage. Duration: instantaneous. |
| **Healing Spell** | Activation: action. Targeting: single/self. Effect: healing. Duration: instantaneous. |
| **Buff / Debuff** | Activation: action/bonus. Effect: stat_modifier or condition_apply. Duration: concentration/timed. |
| **Summoning** | Activation: action. Effect: summon. Creature sheet picker. Duration: concentration. |
| **Transformation** | Activation: action. Effect: transform. Creature sheet picker. |
| **Area / Zone** | Activation: action. Effect: area_zone. AoE shape picker. Duration: concentration. |
| **Equipment** | Activation: equip. Equipment slot/type picker. Passive effects. |
| **Potion** | Activation: bonus_action. Consumable. Targeting: self. |
| **Scroll** | Activation: action. Consumable. Spell level picker (auto-fills DC/attack from table). |
| **Reaction** | Activation: reaction. Reaction trigger field. |
| **Custom / Blank** | Empty GameEffect. Player fills everything manually. |

### 17.2 Step-by-Step Builder

After template selection, the builder walks through these sections in order. Each section is a collapsible panel. The template pre-fills reasonable defaults that the player can override.

1. **Identity** — Name, source label, source type, tags, description
2. **Activation** — Action type, reaction trigger (if reaction)
3. **Resource Cost** — Add one or more costs. Spell slot level picker, class resource name/amount, charges, etc.
4. **Targeting** — Target type, range, max targets, AoE shape builder (visual grid preview)
5. **Effects** — Add EffectBlocks. Each block has a type selector that reveals the appropriate form fields for that type. Multiple blocks can be added.
6. **Choices** — (Optional) Add choice groups for spells like Chromatic Orb. Each option has its own EffectBlock sub-builder.
7. **Duration** — Duration type, value, concentration flag
8. **Scaling** — (Optional) Add scaling rules. Upcast, cantrip level, class level selectors.
9. **Spell Metadata** — (Only for spells/cantrips) Level, school, components
10. **Equipment Metadata** — (Only for equipment) Slot, weapon/armor properties, charges, activated abilities
11. **Review** — Full summary card showing the complete GameEffect. Validate. Save.

### 17.3 Creature Sheet Linking

For summon and transform effects, the builder includes a "Link Creature Sheet" panel:

- Shows a list of all creature sheets the player has created.
- Player checks one or more sheets to link.
- For transforms: these become the available forms.
- For summons: if multiple are linked, a selection menu appears at cast time.
- "Create New Creature Sheet" button opens the creature sheet builder inline or in a new tab.

---

## 18. Shared Types Reference

```typescript
type AbilityStat = "strength" | "dexterity" | "constitution"
                 | "intelligence" | "wisdom" | "charisma";

// Dice expressions are strings parsed by the engine's dice roller.
// Format: [count]d[sides][+/-modifier]
// Modifier can be a number or an ability stat abbreviation.
// Examples:
//   "8d6"         → roll 8d6
//   "2d8+3"       → roll 2d8, add 3
//   "1d10+STR"    → roll 1d10, add Strength modifier
//   "1d4+CHA"     → roll 1d4, add Charisma modifier
//   "4"            → flat value, no roll
//   "1d8+SPELL"   → roll 1d8, add spellcasting ability modifier
//   "1d4+PROF"    → roll 1d4, add proficiency bonus
type DiceExpression = string;

// EffectData is a discriminated union. The `type` field determines the shape.
type EffectData =
  | DamageData
  | HealingData
  | TempHPData
  | StatModifierData
  | ConditionApplyData
  | ConditionRemoveData
  | MovementData
  | SummonData
  | TransformData
  | AreaZoneData
  | ResourceModifyData
  | CounterData;
```

---

## 19. Implementation Priorities

### Phase 1: Core Framework
- Implement the GameEffect and EffectBlock data structures
- Build the dice expression parser (handles "2d6+STR", "8d6", flat values)
- Implement DamageData, HealingData, TempHPData, StatModifierData, ConditionApplyData
- Wire effects into the existing buff/debuff tracker and grid engine
- Build the generator UI with template selection and step-by-step builder
- Validate schema on save

### Phase 2: Combat Resolution Integration
- AoE tile painting and token detection
- Auto-resolution: save rolling, damage calculation, immediate application
- Concentration tracking integration (already partially exists in engine)
- Scaling engine: upcast calculations, cantrip level breakpoints
- Reaction system: trigger detection, interrupt flow

### Phase 3: Summons, Transforms, Equipment
- SummonData: creature sheet linking, spawn placement mode, initiative insertion
- TransformData: sheet swapping, HP pool management, revert logic
- EquipmentMeta: equip/unequip stat toggling, slot management, versatile grip toggle
- Activated abilities on equipment (Flame Tongue ignite, Wand of Fireballs)
- Charge tracking and depletion

### Phase 4: Advanced Effects & Polish
- AreaZoneData: persistent zone painting, entry/exit detection, ongoing effects
- CounterData: counterspell/dispel resolution
- ChoiceGroup: cast-time choice menus
- MovementData: forced movement on grid, teleport placement
- Potion and scroll handling (consumable flag, scroll DC override table)
- Homebrew import/export (JSON)

---

## 20. Tag Taxonomy

Tags are freeform strings, but the following are recommended as a standard vocabulary for filtering and search in the UI.

**Source:** `spell`, `cantrip`, `class_feature`, `racial_trait`, `feat`, `equipment`, `potion`, `scroll`, `custom`

**School:** `abjuration`, `conjuration`, `divination`, `enchantment`, `evocation`, `illusion`, `necromancy`, `transmutation`

**Effect:** `damage`, `healing`, `buff`, `debuff`, `aoe`, `summoning`, `transformation`, `zone`, `counter`, `reaction`, `defense`, `control`, `movement`, `teleportation`

**Damage type:** `fire`, `cold`, `lightning`, `thunder`, `acid`, `poison`, `necrotic`, `radiant`, `force`, `psychic`, `bludgeoning`, `piercing`, `slashing`

**Class:** `barbarian`, `bard`, `cleric`, `druid`, `fighter`, `monk`, `paladin`, `ranger`, `rogue`, `sorcerer`, `warlock`, `wizard`, `artificer`

**Mechanic:** `concentration`, `ritual`, `toggle`, `passive`, `consumable`, `magical`

---

## 21. Implementation Status (updated 8 Feb 2026 — v0.10.0)

This section documents what has been implemented from this design document and important notes about the approach taken.

### 21.1 What Has Been Implemented

#### Potions & Scrolls as Consumables (Section 14)
**Status: IMPLEMENTED**

Potions and scrolls work as consumable items in combat. The implementation covers:
- Healing potions: dice expression rolled, healing applied, capped at max HP, can revive unconscious creatures
- Scrolls with saving throws: target rolls save, damage on fail (full or half on success), conditions applied on fail/success
- Scrolls with direct conditions: apply/remove conditions without saves
- Use tracking: `current_uses` decremented on use, actions disabled at 0 uses remaining
- Self-targeting: potions and self-targeted effects allow clicking on the user's own token
- AI integration: NPCs with healing potions use them when at low HP

#### Combat Effect Resolution (Sections 7.1, 7.2, 7.5, 7.6)
**Status: PARTIALLY IMPLEMENTED (via existing Action model)**

The following EffectBlock types have working combat resolution:
- **Damage** (`damage`): Full attack resolution with d20 rolls, modifiers, AC comparison, critical hits, damage rolls with type-based resistance/immunity/vulnerability
- **Healing** (`healing`): Dice expression healing with `roll_expression()`, applied via `apply_healing()`, caps at max HP
- **Condition Apply** (`condition_apply`): Conditions applied directly or as a result of failed/successful saving throws
- **Condition Remove** (`condition_remove`): Conditions removed by effect (e.g., Lesser Restoration-style scrolls)

#### Equipment System (Section 13)
**Status: MOSTLY IMPLEMENTED**

What works:
- `Item` Pydantic model with equipment slots, weapon/armor properties, rarity, attunement
- Equipment Tab (7th tab) in the Creature Builder UI — full inventory management with equip/unequip, slot assignment, item creation/editing
- Auto-generation of weapon attack Actions from equipped weapons (melee + ranged, finesse logic, proficiency)
- Potion and scroll items generate Actions with healing, saving throw, and condition data
- **Passive stat modifiers from equipment at runtime** (Phase 2): 7 passive fields on Item model (`bonus_ability_scores`, `bonus_speed`, `bonus_ac`, `grants_damage_resistances`, `grants_damage_immunities`, `grants_condition_immunities`, `grants_senses`). All aggregated by `stat_modifiers.py` and wired into combat resolution + GUI display
- **AC recalculation from equipped armor** (Phase 1): `get_effective_armor_class()` computes AC from armor type (light/medium/heavy), DEX modifier, shield, magic bonuses, and passive AC bonuses. Backward compatible — creatures without equipment use stored AC
- **Weapon magic bonus on attack rolls** (Phase 1): `get_weapon_attack_bonus()` adds magic_bonus to attack rolls for equipment-generated weapon actions
- **Stealth disadvantage from armor** (Phase 1): `has_stealth_disadvantage()` checks equipped armor and applies disadvantage to Hide checks
- **Passive Effects section in Equipment Tab GUI**: NumberSpinners and ListEditors for all passive bonus fields

What is NOT yet implemented:
- `EquipmentMeta` schema as described in Section 13
- Versatile grip toggling
- Activated abilities on equipment (e.g., Flame Tongue ignite)

#### Radial Menu Integration (Section 15 — UI)
**Status: IMPLEMENTED**

- New "Items" category in the radial action menu for consumable/utility actions
- Items popup listing all non-weapon, non-spell actions with use counters
- Disabled state when uses exhausted or action economy slot already spent
- Tooltips showing healing dice, save DC, conditions, uses remaining

#### AI Effect Execution (Section 16 — AI)
**Status: PARTIALLY IMPLEMENTED**

- `EXECUTE_EFFECT` step type added to AI TurnPlan system
- Heal actions route through `execute_effect()` instead of `execute_attack()`
- AI correctly selects healing targets and uses consumable items

### 21.2 What Has NOT Been Implemented

The following proposed systems from this document remain unbuilt:

- **GameEffect data model** (Section 3): The universal `GameEffect` container was not created. Instead, the existing `Action` model was extended to handle potions/scrolls/consumables alongside weapon attacks and spells.
- **EffectBlock composability** (Section 7): No composable effect block system. Effects are fields on the Action model (healing, saving_throw, conditions_applied, conditions_removed) rather than an array of typed blocks.
- **TempHP effects** (Section 7.3): Not implemented.
- **Stat Modifier effects** (Section 7.4): IMPLEMENTED via `stat_modifiers.py` pure query functions (not the EffectBlock approach). Equipment passive bonuses and feat bonuses are aggregated for ability scores, speed, AC, resistances, immunities, condition immunities, saving throw proficiencies, and initiative.
- **Duration/Buff Tracker integration** (Section 8): No new buff/debuff tracking beyond what the existing condition system provides.
- **Scaling engine** (Section 9): No upcast calculations or cantrip level breakpoints.
- **AoE targeting** (Section 10): No area-of-effect tile painting or multi-target resolution.
- **Summon/Transform** (Sections 11–12): Not implemented.
- **Area Zones** (Section 7.9): No persistent zone painting or entry/exit detection.
- **Counter system** (Section 7.12): No counterspell/dispel resolution.
- **Choice groups** (Section 6): No cast-time choice menus.
- **Movement effects** (Section 7.7): No forced movement or teleportation effects.
- **Generator UI** (Section 15): No dedicated GameEffect builder screen; items and actions are created through the existing Creature Builder tabs.
- **Resource management** beyond use tracking: IMPLEMENTED. `PlayerCharacter.class_resources: dict[str, int]` with `check_resource_cost()` and `deduct_resource_cost()` in `actions.py`, wired into `resolve_attack()` and `resolve_effect()`. Class Resources UI in Features Tab. Resources displayed in creature_info panel with gold bar. Actions grayed out in radial menu when resources insufficient.

### 21.3 Important Implementation Notes

1. **Pragmatic approach over architectural purity.** Rather than building the full `GameEffect` → `EffectBlock[]` architecture proposed in this document, the implementation extended the existing `Action` Pydantic model. This was a deliberate choice: the Action model already had `attack`, `damage`, `saving_throw`, and `resource_cost` fields, and adding `healing`, `conditions_applied`, `conditions_removed`, and `current_uses` fields was far less disruptive than introducing an entirely new data model. The tradeoff is less composability — an action can heal OR deal damage via saves, but complex multi-stage effects (damage + heal + summon in one action) would require multiple Actions.

2. **`resolve_effect()` parallels `resolve_attack()`.** The new function in `src/combat/actions.py` handles all non-attack action resolution. It checks range, processes healing, resolves saving throws (with damage/conditions on fail/success), applies/removes direct conditions, and tracks uses. It returns an `ActionResult` with combat events, same as `resolve_attack()`.

3. **`execute_effect()` parallels `execute_attack()`.** The new method on `CombatManager` calls `resolve_effect()`, marks the appropriate action economy slot used (action or bonus_action), clears the selection, and checks victory conditions.

4. **Self-targeting is manual, not automatic.** Per the project owner's decision, self-targeted effects (like healing potions) still require the player to click on their own token during the `SELECTING_TARGET` phase. The system allows self-clicks for non-attack actions but blocks them for attack actions.

5. **Items category in radial menu.** Actions that don't fit into weapons, cantrips, or leveled spells are collected into an "Items" slot. The categorization logic (`_get_item_actions()`) filters out any action already claimed by those three groups and presents the remainder as consumable/utility items.

6. **The contractor document (this document) may describe features that assume systems which don't exist.** For example, Section 13's `EquipmentMeta` assumes a `GameEffect` model that was never built. The equipment system uses the `Item` Pydantic model from `src/models/items.py` directly, with weapon properties generating Actions rather than GameEffects.

7. **Test coverage.** 26 new tests in `tests/test_resolve_effect.py` cover healing, saving throws, conditions, self-targeting, use tracking, out-of-range, knockout detection, CombatManager integration, AI execution, and radial menu categorization.

8. **Stat Modifier Framework (Phases 1-2).** `src/combat/stat_modifiers.py` provides pure query functions that aggregate effective stats from equipment and feats without mutating state. Pattern follows `condition_effects.py`. Key functions: `get_effective_armor_class()` (full 5e AC calculation from armor type/DEX/shield/magic/passive bonuses), `get_effective_ability_score()` (base + equipment + feat, capped at 30), `get_effective_speed()`, `get_effective_damage_resistances/immunities()`, `get_effective_condition_immunities()`, `get_effective_saving_throw_proficiencies()`, `get_initiative_bonus()`. All combat resolution code (damage.py, conditions.py, actions.py, manager.py, standard_actions.py) and GUI panels use these effective values instead of raw creature fields. Backward compatible — empty equipment returns stored values unchanged.

9. **Feat system (Phase 3+4).** `src/models/feats.py` — `Feat` Pydantic model with the same passive bonus fields as the `Item` model, enabling uniform aggregation in `stat_modifiers.py`. `feats: list[Feat]` on `PlayerCharacter`. `FEATS` list (42 PHB feats) and `FEAT_DATA` dict in `dnd_data.py` provide dropdown selection with auto-populated bonuses. Feats section in Features Tab GUI. The `_get_feats()` helper uses `getattr(creature, "feats", [])` so base `Creature` (monsters) returns empty without error.

10. **Class resource consumption (Phase 3+4).** `Action.resource_cost: dict[str, int]` (which existed but was unused) is now checked and deducted during combat. `check_resource_cost()` verifies the creature's `class_resources` dict has sufficient values; `deduct_resource_cost()` subtracts costs. Both wired into the top of `resolve_attack()` and `resolve_effect()`. `Combatant.max_resources` snapshots class_resources at initiative roll for display purposes. Resources shown in creature_info panel with gold bar. Actions grayed out in radial menu and action bar when resources insufficient.

11. **Updated test coverage.** Total project test count: 1054 passing, 4 skipped. Key new test files: `tests/test_stat_modifiers.py` (83 tests), `tests/test_feats.py` (36 tests), `tests/test_resource_cost.py` (17 tests).
