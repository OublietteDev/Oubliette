# D&D 5e Combat Spell & Ability Grammar — Composable Primitives

## How to Read This Document

Every spell or combat ability in 5e can be decomposed into a combination of the primitives listed below. Think of each spell as a "sentence" constructed from these building blocks. The goal is for your app's character editor to expose these primitives as configurable fields, so users can construct any spell by selecting the right combination.

At the end of this document, I've included a decomposition of PHB spells organized by level to stress-test the grammar.

---

## 1. RESOURCE COST

What it takes to use the ability.

| Primitive | Values / Notes |
|---|---|
| `cost_type` | `cantrip`, `spell_slot`, `class_resource`, `item_charge`, `free` |
| `slot_level` | 1–9 (for spell_slot type) |
| `resource_name` | e.g., "Ki Point", "Sorcery Point", "Channel Divinity", "Superiority Die", "Rage", "Bardic Inspiration", "Wild Shape" |
| `resource_amount` | Integer (how many of the resource are consumed) |
| `component_verbal` | Boolean |
| `component_somatic` | Boolean |
| `component_material` | String or null (description + whether consumed + GP value if relevant) |
| `ritual_castable` | Boolean |

---

## 2. CASTING TIME / ACTION ECONOMY

| Primitive | Values / Notes |
|---|---|
| `action_type` | `action`, `bonus_action`, `reaction`, `minute(s)`, `hour(s)`, `free_action`, `special` |
| `action_count` | Integer (usually 1; for "10 minutes" this would be 10 with type `minute(s)`) |
| `reaction_trigger` | String description of trigger condition (for reactions only). e.g., "when you or a creature within 60 feet is hit by an attack", "when a creature you can see within 60 feet casts a spell" |

---

## 3. RANGE & TARGETING

### 3a. Range

| Primitive | Values / Notes |
|---|---|
| `range_type` | `self`, `touch`, `ranged`, `sight`, `unlimited` |
| `range_distance` | Integer in feet (for ranged). e.g., 30, 60, 120, 150 |

### 3b. Target Selection

| Primitive | Values / Notes |
|---|---|
| `target_type` | `single_creature`, `multiple_creatures`, `single_object`, `area`, `self`, `point_in_space`, `willing_creature`, `creature_or_object` |
| `target_count` | Integer or formula. e.g., 1, 3, "one per slot level above 1st" |
| `target_count_scaling` | How target count changes on upcast (see Scaling section) |
| `target_restriction` | Optional filter. e.g., "creature you can see", "humanoid", "beast of CR 1/4 or lower", "friendly creature", "hostile creature" |
| `line_of_sight_required` | Boolean |

### 3c. Area of Effect (if target_type is `area`)

| Primitive | Values / Notes |
|---|---|
| `aoe_shape` | `sphere`, `cube`, `cone`, `line`, `cylinder`, `hemisphere`, `ring`, `wall`, `aura` |
| `aoe_size_primary` | Integer in feet (radius, side length, or length depending on shape) |
| `aoe_size_secondary` | Integer in feet (width for lines/walls, height for cylinders/walls) |
| `aoe_anchor` | `caster_centered`, `point_in_range`, `caster_origin` (cones/lines emanating from caster), `target_centered` |
| `aoe_moves_with_caster` | Boolean (true for Spirit Guardians, false for Moonbeam) |
| `aoe_moveable` | Boolean — can caster reposition the effect on subsequent turns? |
| `aoe_move_action_cost` | `action`, `bonus_action`, `free`, `none` |
| `aoe_move_distance` | Integer in feet (max distance per move, e.g., Moonbeam 60ft) |

---

## 4. DURATION & CONCENTRATION

| Primitive | Values / Notes |
|---|---|
| `duration_type` | `instantaneous`, `timed`, `until_dispelled`, `special` |
| `duration_value` | Integer |
| `duration_unit` | `round`, `minute`, `hour`, `day` |
| `concentration` | Boolean |

---

## 5. ATTACK / SAVE MECHANIC

How the effect resolves against a target.

| Primitive | Values / Notes |
|---|---|
| `resolution_type` | `spell_attack_ranged`, `spell_attack_melee`, `saving_throw`, `automatic`, `contested_check`, `weapon_attack_modifier` |
| `save_ability` | `STR`, `DEX`, `CON`, `INT`, `WIS`, `CHA` |
| `save_success_effect` | `no_effect`, `half_damage`, `half_damage_no_condition`, `special` |
| `save_frequency` | `once`, `each_turn_start`, `each_turn_end`, `on_entry`, `on_damage` (when does target re-save?) |
| `save_ends_effect` | Boolean (does a successful subsequent save end the effect?) |
| `contested_attacker_ability` | For contested checks (e.g., grapple) |
| `contested_defender_ability` | For contested checks |

---

## 6. EFFECTS

This is the big one. A single spell can have **multiple effects**, so this should be modeled as a list/array. Each effect in the list has:

### 6a. Damage

| Primitive | Values / Notes |
|---|---|
| `damage_dice_count` | Integer |
| `damage_dice_size` | `d4`, `d6`, `d8`, `d10`, `d12` |
| `damage_bonus` | Integer or `spellcasting_mod`, `ability_mod` |
| `damage_type` | `acid`, `bludgeoning`, `cold`, `fire`, `force`, `lightning`, `necrotic`, `piercing`, `poison`, `psychic`, `radiant`, `slashing`, `thunder` |
| `damage_on_save` | `full`, `half`, `none` |
| `damage_rider` | Optional secondary damage instance (some spells deal two types) |

### 6b. Healing

| Primitive | Values / Notes |
|---|---|
| `heal_dice_count` | Integer |
| `heal_dice_size` | `d4`, `d6`, `d8`, `d10`, `d12` |
| `heal_bonus` | Integer or `spellcasting_mod` |
| `heal_type` | `hit_points`, `temp_hp`, `max_hp_restore` |

### 6c. Conditions Applied

| Primitive | Values / Notes |
|---|---|
| `condition` | `blinded`, `charmed`, `deafened`, `frightened`, `grappled`, `incapacitated`, `invisible`, `paralyzed`, `petrified`, `poisoned`, `prone`, `restrained`, `stunned`, `unconscious`, `exhaustion` |
| `condition_duration` | Same duration primitives as above, or `save_ends` |
| `condition_custom` | String — for non-standard conditions like "can't take reactions", "speed is 0", "disadvantage on next attack" |

### 6d. Movement Effects

| Primitive | Values / Notes |
|---|---|
| `forced_movement_type` | `push`, `pull`, `teleport_caster`, `teleport_target`, `lift`, `swap` |
| `forced_movement_distance` | Integer in feet |
| `forced_movement_direction` | `away_from_caster`, `toward_caster`, `choice`, `up`, `specific_point` |
| `speed_modification` | `halved`, `zero`, `bonus_feet`, `reduced_by_N` |
| `speed_modification_value` | Integer (for bonus_feet or reduced_by_N) |
| `difficult_terrain` | Boolean — does the area create difficult terrain? |

### 6e. Buffs / Debuffs (Stat Modifications)

| Primitive | Values / Notes |
|---|---|
| `stat_target` | `AC`, `attack_rolls`, `damage_rolls`, `saving_throws`, `ability_checks`, `speed`, `HP_max`, `specific_ability_score` |
| `stat_modification_type` | `flat_bonus`, `flat_penalty`, `advantage`, `disadvantage`, `set_value`, `resistance`, `immunity`, `vulnerability` |
| `stat_modification_value` | Integer or dice expression |
| `stat_scope` | Which ability/damage type this applies to. e.g., "all", "DEX saves", "fire damage" |

### 6f. Summon / Create

| Primitive | Values / Notes |
|---|---|
| `summon_type` | `creature`, `object`, `terrain`, `barrier` |
| `summon_stat_block` | Reference to linked character sheet (your Wildshape solution!) |
| `summon_count` | Integer or formula |
| `summon_duration` | Duration primitives |
| `summon_behavior` | `obeys_commands`, `acts_independently`, `hostile_to_all`, `stationary` |
| `wall_properties` | For wall spells — length, height, thickness, HP per panel, etc. |

### 6g. Utility / Status Effects

| Primitive | Values / Notes |
|---|---|
| `grants_sense` | `darkvision`, `truesight`, `blindsight`, `tremorsense` |
| `sense_range` | Integer in feet |
| `grants_movement` | `flying`, `swimming`, `climbing`, `burrowing`, `hover` |
| `movement_speed` | Integer in feet |
| `light_emission` | `bright`, `dim` + radius |
| `dispel_effect` | Boolean — does this dispel other effects? |
| `counter_effect` | Boolean — does this prevent/interrupt another action? |
| `proficiency_grant` | Specific proficiency granted |
| `language_grant` | Language-related effects |

---

## 7. EFFECT TRIGGERS & TIMING

When do the effects actually fire? A spell can have multiple trigger points.

| Primitive | Values / Notes |
|---|---|
| `trigger_timing` | `on_cast`, `on_hit`, `start_of_target_turn`, `end_of_target_turn`, `start_of_caster_turn`, `on_enter_area`, `on_first_enter_area_per_turn`, `on_end_turn_in_area`, `on_start_turn_in_area`, `on_taking_damage`, `on_failing_save`, `on_attack_against_target`, `on_being_attacked`, `reaction_trigger`, `delayed` |
| `trigger_who` | `caster`, `target`, `any_creature`, `ally`, `enemy` |
| `trigger_frequency` | `once`, `once_per_turn`, `each_occurrence`, `limited_uses` |
| `trigger_uses` | Integer (for limited_uses) |
| `delayed_rounds` | Integer (for delayed trigger, like Delayed Blast Fireball) |

---

## 8. SCALING

### 8a. Cantrip Scaling (by character level)

| Primitive | Values / Notes |
|---|---|
| `cantrip_scale_levels` | Array: `[5, 11, 17]` (standard breakpoints) |
| `cantrip_scale_effect` | What changes per breakpoint. Usually `+1 damage die` |
| `cantrip_scale_extra` | Additional targets/beams (e.g., Eldritch Blast gains beams) |

### 8b. Upcast Scaling (by slot level above base)

| Primitive | Values / Notes |
|---|---|
| `upcast_per_level` | What changes per additional slot level |
| `upcast_damage_dice` | Additional dice per level (e.g., "+1d6 per level") |
| `upcast_target_count` | Additional targets per level |
| `upcast_duration` | Additional duration per level |
| `upcast_healing_dice` | Additional healing dice per level |
| `upcast_effect_threshold` | Some spells gain new effects at specific higher levels (e.g., Animate Dead at 4th+) |
| `upcast_special` | String description for complex scaling |

---

## 9. SPECIAL MECHANICS

These are less common but crop up enough to be worth encoding.

| Primitive | Values / Notes |
|---|---|
| `requires_concentration_check` | Boolean (auto-true if concentration, but also for some damage effects) |
| `spell_interaction` | `counterspell_target` (this spell can be counterspelled), `dispellable`, `non_magical` |
| `attack_replacement` | Does this spell replace the Attack action? (Blade cantrips like Booming Blade) |
| `extra_attack_compatible` | Boolean |
| `bonus_action_followup` | Can the caster use a bonus action for additional effect? (e.g., Spiritual Weapon) |
| `death_save_interaction` | Effect on death saves (e.g., auto-fail, auto-crit) |
| `creature_type_bonus` | Extra damage/effects against specific creature types |
| `object_interaction` | Does it affect objects? Ignite flammable? Extinguish? |
| `cover_interaction` | Does it go around cover? Ignore cover? |

---

## 10. CONDITIONAL / BRANCHING EFFECTS

Some spells do different things depending on circumstances.

| Primitive | Values / Notes |
|---|---|
| `condition_branch` | Array of `{ if: condition, then: effect }` |
| `melee_vs_ranged_option` | Some spells have a melee or ranged mode (e.g., Thorn Whip is always ranged, but Flame Blade creates a melee weapon) |
| `target_type_branch` | Different effects on different target types (e.g., Sunbeam does extra vs undead) |
| `hp_threshold_branch` | e.g., Sleep affects creatures under certain HP total |
| `willing_vs_unwilling` | Different handling for willing vs unwilling targets |

---

## SPELL DECOMPOSITION EXAMPLES

Below is a decomposition of PHB spells by level to validate the grammar. I'll flag any spell that needs a primitive not yet covered.

### Cantrips

**Fire Bolt**
```
cost_type: cantrip
action_type: action
range_type: ranged | range_distance: 120
target_type: single_creature
resolution_type: spell_attack_ranged
damage_dice: 1d10 | damage_type: fire
cantrip_scale: [5,11,17] → +1d10 per tier
object_interaction: ignites flammable unattended objects
```

**Chill Touch**
```
cost_type: cantrip
action_type: action
range_type: ranged | range_distance: 120
target_type: single_creature
resolution_type: spell_attack_ranged
damage_dice: 1d8 | damage_type: necrotic
cantrip_scale: [5,11,17] → +1d8 per tier
condition_custom: "target can't regain HP until start of your next turn"
creature_type_bonus: vs undead → also disadvantage on attacks against caster
```

**Eldritch Blast**
```
cost_type: cantrip
action_type: action
range_type: ranged | range_distance: 120
target_type: single_creature (per beam)
target_count: 1 (scales: 2 at 5, 3 at 11, 4 at 17)
resolution_type: spell_attack_ranged (per beam)
damage_dice: 1d10 | damage_type: force
cantrip_scale: [5,11,17] → +1 beam per tier
NOTE: each beam can target different creatures
```

**Sacred Flame**
```
cost_type: cantrip
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
resolution_type: saving_throw | save_ability: DEX
save_success_effect: no_effect
damage_dice: 1d8 | damage_type: radiant
cantrip_scale: [5,11,17] → +1d8
cover_interaction: target gains no benefit from cover
```

**Booming Blade**
```
cost_type: cantrip
action_type: action
range_type: touch (5ft, self targeting melee weapon)
attack_replacement: true (make melee weapon attack as part of spell)
resolution_type: weapon_attack_modifier
damage_dice: 0 (at level 1; weapon damage only)
cantrip_scale: [5] → +1d8 thunder on hit; [11] → +2d8; [17] → +3d8
conditional_extra_damage: if target willingly moves → 1d8 thunder (scales +1d8 at 5/11/17)
trigger_timing: on_target_movement (voluntary)
```

**Toll the Dead**
```
cost_type: cantrip
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
resolution_type: saving_throw | save_ability: WIS
save_success_effect: no_effect
damage_dice: 1d8 | damage_type: necrotic
hp_threshold_branch: if target is missing HP → 1d12 instead of 1d8
cantrip_scale: [5,11,17] → +1 die (d8 or d12 depending on branch)
```

**Vicious Mockery**
```
cost_type: cantrip
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
resolution_type: saving_throw | save_ability: WIS
save_success_effect: no_effect
damage_dice: 1d4 | damage_type: psychic
condition_custom: "disadvantage on next attack roll before end of its next turn"
cantrip_scale: [5,11,17] → +1d4
```

**Sword Burst**
```
cost_type: cantrip
action_type: action
range_type: self
aoe_shape: sphere | aoe_size_primary: 5
aoe_anchor: caster_centered
resolution_type: saving_throw | save_ability: DEX
save_success_effect: no_effect
damage_dice: 1d6 | damage_type: force
cantrip_scale: [5,11,17] → +1d6
```

**Spare the Dying**
```
cost_type: cantrip
action_type: action
range_type: touch
target_type: single_creature
target_restriction: "creature with 0 HP"
resolution_type: automatic
effect: stabilize (creature is stable, no more death saves)
```

### 1st Level Spells

**Magic Missile**
```
cost_type: spell_slot | slot_level: 1
action_type: action
range_type: ranged | range_distance: 120
target_type: multiple_creatures
target_count: 3 (darts, can target same or different)
resolution_type: automatic (no attack roll, no save)
damage_dice: 1d4+1 per dart | damage_type: force
upcast: +1 dart per slot level above 1st
spell_interaction: blocked by Shield spell
```

**Shield**
```
cost_type: spell_slot | slot_level: 1
action_type: reaction
reaction_trigger: "when you are hit by an attack or targeted by magic missile"
range_type: self
duration_type: timed | duration_value: 1 | duration_unit: round
concentration: false
stat_target: AC | stat_modification_type: flat_bonus | stat_modification_value: +5
spell_interaction: blocks magic missile entirely
```

**Cure Wounds**
```
cost_type: spell_slot | slot_level: 1
action_type: action
range_type: touch
target_type: willing_creature
resolution_type: automatic
heal_dice: 1d8 | heal_bonus: spellcasting_mod | heal_type: hit_points
target_restriction: "creature that is not undead or construct"
upcast: +1d8 per slot level above 1st
```

**Healing Word**
```
cost_type: spell_slot | slot_level: 1
action_type: bonus_action
range_type: ranged | range_distance: 60
target_type: willing_creature
resolution_type: automatic
heal_dice: 1d4 | heal_bonus: spellcasting_mod | heal_type: hit_points
target_restriction: "creature that is not undead or construct"
upcast: +1d4 per slot level above 1st
```

**Guiding Bolt**
```
cost_type: spell_slot | slot_level: 1
action_type: action
range_type: ranged | range_distance: 120
target_type: single_creature
resolution_type: spell_attack_ranged
damage_dice: 4d6 | damage_type: radiant
condition_custom: "next attack against target before end of your next turn has advantage"
upcast: +1d6 per slot level above 1st
```

**Thunderwave**
```
cost_type: spell_slot | slot_level: 1
action_type: action
range_type: self
aoe_shape: cube | aoe_size_primary: 15
aoe_anchor: caster_origin (emanates from caster)
resolution_type: saving_throw | save_ability: CON
save_success_effect: half_damage
damage_dice: 2d8 | damage_type: thunder
forced_movement_type: push | forced_movement_distance: 10 | forced_movement_direction: away_from_caster
NOTE: push only on failed save
upcast: +1d8 per slot level above 1st
object_interaction: unsecured objects pushed 10ft, audible 300ft
```

**Bless**
```
cost_type: spell_slot | slot_level: 1
action_type: action
range_type: ranged | range_distance: 30
target_type: multiple_creatures | target_count: 3
target_restriction: willing_creature
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: automatic
stat_target: attack_rolls + saving_throws
stat_modification_type: flat_bonus | stat_modification_value: 1d4
upcast: +1 target per slot level above 1st
```

**Bane**
```
cost_type: spell_slot | slot_level: 1
action_type: action
range_type: ranged | range_distance: 30
target_type: multiple_creatures | target_count: 3
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: CHA
save_success_effect: no_effect
stat_target: attack_rolls + saving_throws
stat_modification_type: flat_penalty | stat_modification_value: 1d4
upcast: +1 target per slot level above 1st
```

**Hex**
```
cost_type: spell_slot | slot_level: 1
action_type: bonus_action
range_type: ranged | range_distance: 90
target_type: single_creature
duration_type: timed | duration_value: 1 | duration_unit: hour | concentration: true
resolution_type: automatic
trigger_timing: on_hit (when you hit target with attack)
damage_dice: 1d6 | damage_type: necrotic (bonus damage per hit)
stat_target: ability_checks | stat_scope: chosen ability | stat_modification_type: disadvantage
bonus_action_followup: can move hex to new target when current target drops to 0 HP
upcast: duration increases (3rd→8h, 5th→24h)
```

**Hunter's Mark**
```
cost_type: spell_slot | slot_level: 1
action_type: bonus_action
range_type: ranged | range_distance: 90
target_type: single_creature
duration_type: timed | duration_value: 1 | duration_unit: hour | concentration: true
resolution_type: automatic
trigger_timing: on_hit (when you hit target with weapon attack)
damage_dice: 1d6 | damage_type: (same as weapon)
grants_sense: advantage on WIS (Perception) and WIS (Survival) to find target
bonus_action_followup: can move mark to new target when current target drops to 0 HP
upcast: duration increases (3rd→8h, 5th→24h)
```

**Faerie Fire**
```
cost_type: spell_slot | slot_level: 1
action_type: action
range_type: ranged | range_distance: 60
aoe_shape: cube | aoe_size_primary: 20
aoe_anchor: point_in_range
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: DEX
save_success_effect: no_effect
condition_custom: "outlined in light, attacks against it have advantage, can't benefit from invisible"
light_emission: dim, 10ft radius from each affected creature
```

**Entangle**
```
cost_type: spell_slot | slot_level: 1
action_type: action
range_type: ranged | range_distance: 90
aoe_shape: square | aoe_size_primary: 20
aoe_anchor: point_in_range
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: STR
save_success_effect: no_effect
condition: restrained
save_frequency: each_turn (action to repeat STR check)
difficult_terrain: true (area is difficult terrain for duration)
```

**Sleep**
```
cost_type: spell_slot | slot_level: 1
action_type: action
range_type: ranged | range_distance: 90
aoe_shape: sphere | aoe_size_primary: 20
aoe_anchor: point_in_range
resolution_type: automatic (no save — HP pool mechanic)
hp_threshold_branch: roll 5d8 → affects creatures in ascending HP order
condition: unconscious
condition_duration: 1 minute OR until damaged OR until another creature uses action to wake
upcast: +2d8 to HP pool per slot level above 1st
target_restriction: "not undead, not immune to charmed"
NOTE: unique HP-pool mechanic — may need special handling
```

**Burning Hands**
```
cost_type: spell_slot | slot_level: 1
action_type: action
range_type: self
aoe_shape: cone | aoe_size_primary: 15
aoe_anchor: caster_origin
resolution_type: saving_throw | save_ability: DEX
save_success_effect: half_damage
damage_dice: 3d6 | damage_type: fire
upcast: +1d6 per slot level above 1st
object_interaction: ignites flammable unattended objects
```

**Chromatic Orb**
```
cost_type: spell_slot | slot_level: 1
action_type: action
range_type: ranged | range_distance: 90
target_type: single_creature
resolution_type: spell_attack_ranged
damage_dice: 3d8 | damage_type: CHOICE (acid, cold, fire, lightning, poison, or thunder)
component_material: "diamond worth 50gp" (not consumed)
upcast: +1d8 per slot level above 1st
NOTE: caster chooses damage type on cast — needs a `damage_type_choice` primitive
```

**Witch Bolt**
```
cost_type: spell_slot | slot_level: 1
action_type: action
range_type: ranged | range_distance: 30
target_type: single_creature
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: spell_attack_ranged
damage_dice: 1d12 | damage_type: lightning
recurring_effect: on each subsequent turn, can use action to auto-deal 1d12 lightning (no roll)
upcast: +1d12 to initial damage per slot level above 1st (subsequent turns still 1d12)
end_condition: "target moves out of range, you don't use action, lose line of sight"
```

**Absorb Elements**
```
cost_type: spell_slot | slot_level: 1
action_type: reaction
reaction_trigger: "when you take acid, cold, fire, lightning, or thunder damage"
range_type: self
duration_type: timed | duration_value: 1 | duration_unit: round
concentration: false
buff: resistance to triggering damage type until start of next turn
damage_rider: next melee attack deals +1d6 of triggering type
upcast: +1d6 to rider per slot level above 1st
```

**Sanctuary**
```
cost_type: spell_slot | slot_level: 1
action_type: bonus_action
range_type: ranged | range_distance: 30
target_type: willing_creature
duration_type: timed | duration_value: 1 | duration_unit: minute
concentration: false
resolution_type: saving_throw | save_ability: WIS (enemy must save to target warded creature)
save_success_effect: no_effect (attacker can target normally)
save_frequency: each_occurrence (each time an enemy tries to target)
end_condition: "warded creature makes an attack, casts offensive spell, or deals damage"
```

**Command**
```
cost_type: spell_slot | slot_level: 1
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
resolution_type: saving_throw | save_ability: WIS
save_success_effect: no_effect
target_restriction: "not undead, understands your language"
effect: target follows one-word command on next turn (approach, drop, flee, grovel, halt)
NOTE: the specific command chosen determines the mechanical effect — may need enumerated sub-options
upcast: +1 target per slot level above 1st
```

### 2nd Level Spells

**Moonbeam**
```
cost_type: spell_slot | slot_level: 2
action_type: action
range_type: ranged | range_distance: 120
aoe_shape: cylinder | aoe_size_primary: 5 (radius) | aoe_size_secondary: 40 (height)
aoe_anchor: point_in_range
aoe_moves_with_caster: false
aoe_moveable: true | aoe_move_action_cost: action | aoe_move_distance: 60
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: CON
save_success_effect: half_damage
damage_dice: 2d10 | damage_type: radiant
trigger_timing: on_first_enter_area_per_turn + on_start_turn_in_area
creature_type_bonus: shapechangers have disadvantage on save
upcast: +1d10 per slot level above 2nd
```

**Spiritual Weapon**
```
cost_type: spell_slot | slot_level: 2
action_type: bonus_action
range_type: ranged | range_distance: 60
target_type: single_creature (within 5ft of weapon)
duration_type: timed | duration_value: 1 | duration_unit: minute
concentration: false
resolution_type: spell_attack_melee
damage_dice: 1d8 | damage_bonus: spellcasting_mod | damage_type: force
bonus_action_followup: on subsequent turns, bonus action to move weapon 20ft + attack
upcast: +1d8 damage per 2 slot levels above 2nd
summon_type: object (floating weapon)
```

**Hold Person**
```
cost_type: spell_slot | slot_level: 2
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
target_restriction: humanoid
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: WIS
save_success_effect: no_effect
condition: paralyzed
save_frequency: each_turn_end | save_ends_effect: true
death_save_interaction: attacks within 5ft are auto-crits vs paralyzed
upcast: +1 target per slot level above 2nd
```

**Misty Step**
```
cost_type: spell_slot | slot_level: 2
action_type: bonus_action
range_type: self
duration_type: instantaneous
resolution_type: automatic
forced_movement_type: teleport_caster
forced_movement_distance: 30
NOTE: "to an unoccupied space you can see"
```

**Scorching Ray**
```
cost_type: spell_slot | slot_level: 2
action_type: action
range_type: ranged | range_distance: 120
target_type: multiple_creatures | target_count: 3 (rays, each can target same or different)
resolution_type: spell_attack_ranged (per ray)
damage_dice: 2d6 per ray | damage_type: fire
upcast: +1 ray per slot level above 2nd
```

**Shatter**
```
cost_type: spell_slot | slot_level: 2
action_type: action
range_type: ranged | range_distance: 60
aoe_shape: sphere | aoe_size_primary: 10
aoe_anchor: point_in_range
resolution_type: saving_throw | save_ability: CON
save_success_effect: half_damage
damage_dice: 3d8 | damage_type: thunder
creature_type_bonus: creatures made of inorganic material have disadvantage on save
object_interaction: nonmagical objects not worn/carried also take damage
upcast: +1d8 per slot level above 2nd
```

**Spike Growth**
```
cost_type: spell_slot | slot_level: 2
action_type: action
range_type: ranged | range_distance: 150
aoe_shape: sphere | aoe_size_primary: 20
aoe_anchor: point_in_range
duration_type: timed | duration_value: 10 | duration_unit: minute | concentration: true
difficult_terrain: true
trigger_timing: on movement through area
damage_dice: 2d4 per 5ft moved | damage_type: piercing
resolution_type: automatic (no save for damage)
NOTE: damage per 5ft of movement is a somewhat unique mechanic — "damage_per_5ft_moved"
```

**Web**
```
cost_type: spell_slot | slot_level: 2
action_type: action
range_type: ranged | range_distance: 60
aoe_shape: cube | aoe_size_primary: 20
aoe_anchor: point_in_range
duration_type: timed | duration_value: 1 | duration_unit: hour | concentration: true
difficult_terrain: true
resolution_type: saving_throw | save_ability: DEX
save_success_effect: no_effect (not restrained initially, but still difficult terrain)
condition: restrained (on failed save)
save_frequency: action to break free (STR check vs spell DC)
object_interaction: flammable — fire deals 2d4 to creatures in area
```

**Heat Metal**
```
cost_type: spell_slot | slot_level: 2
action_type: action
range_type: ranged | range_distance: 60
target_type: single_object (metal object)
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: CON (to avoid dropping)
damage_dice: 2d8 | damage_type: fire
trigger_timing: on_cast + bonus_action on subsequent turns
condition_custom: "if holding object and fails save, must drop it; if wearing it, disadvantage on attacks and ability checks"
upcast: +1d8 per slot level above 2nd
```

**Blindness/Deafness**
```
cost_type: spell_slot | slot_level: 2
action_type: action
range_type: ranged | range_distance: 30
target_type: single_creature
duration_type: timed | duration_value: 1 | duration_unit: minute
concentration: false
resolution_type: saving_throw | save_ability: CON
save_success_effect: no_effect
condition: blinded OR deafened (caster chooses)
save_frequency: each_turn_end | save_ends_effect: true
upcast: +1 target per slot level above 2nd
NOTE: needs `condition_choice` primitive — caster picks which condition
```

### 3rd Level Spells

**Fireball**
```
cost_type: spell_slot | slot_level: 3
action_type: action
range_type: ranged | range_distance: 150
aoe_shape: sphere | aoe_size_primary: 20
aoe_anchor: point_in_range
resolution_type: saving_throw | save_ability: DEX
save_success_effect: half_damage
damage_dice: 8d6 | damage_type: fire
upcast: +1d6 per slot level above 3rd
object_interaction: ignites flammable objects not worn/carried
cover_interaction: spreads around corners
```

**Spirit Guardians**
```
cost_type: spell_slot | slot_level: 3
action_type: action
range_type: self
aoe_shape: sphere | aoe_size_primary: 15
aoe_anchor: caster_centered | aoe_moves_with_caster: true
duration_type: timed | duration_value: 10 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: WIS
save_success_effect: half_damage
damage_dice: 3d8 | damage_type: radiant OR necrotic (caster chooses on cast, based on alignment)
trigger_timing: on_first_enter_area_per_turn + on_start_turn_in_area
speed_modification: halved (for enemies in area)
upcast: +1d8 per slot level above 3rd
```

**Counterspell**
```
cost_type: spell_slot | slot_level: 3
action_type: reaction
reaction_trigger: "when a creature within 60 feet casts a spell"
range_type: ranged | range_distance: 60
duration_type: instantaneous
resolution_type: automatic if target spell level <= slot level used
    OTHERWISE: ability check DC = 10 + target spell level
counter_effect: true — interrupts and negates the target spell
upcast: automatically counters spells of slot level used or lower
NOTE: unique mechanic — ability check to counter higher-level spells
```

**Dispel Magic**
```
cost_type: spell_slot | slot_level: 3
action_type: action
range_type: ranged | range_distance: 120
target_type: creature_or_object (or magical effect)
duration_type: instantaneous
resolution_type: automatic if target spell level <= 3
    OTHERWISE: ability check DC = 10 + target spell level
dispel_effect: true — ends one spell on target
upcast: automatically dispels spells of slot level used or lower
```

**Haste**
```
cost_type: spell_slot | slot_level: 3
action_type: action
range_type: ranged | range_distance: 30
target_type: willing_creature
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: automatic
stat_target: speed | stat_modification_type: set_value (doubled)
stat_target: AC | stat_modification_type: flat_bonus | stat_modification_value: +2
stat_target: saving_throws | stat_scope: DEX | stat_modification_type: advantage
grants_extra_action: "one additional action per turn (attack one weapon only, dash, disengage, hide, use object)"
end_effect: "when spell ends, target can't move or take actions until after next turn" (lethargy)
NOTE: the "extra action" and "lethargy" are fairly unique — may need `grants_extra_action` and `end_penalty` primitives
```

**Slow**
```
cost_type: spell_slot | slot_level: 3
action_type: action
range_type: ranged | range_distance: 120
target_type: multiple_creatures | target_count: 6
aoe_shape: cube | aoe_size_primary: 40
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: WIS
save_success_effect: no_effect
speed_modification: halved
stat_target: AC | stat_modification_type: flat_penalty | stat_modification_value: -2
stat_target: saving_throws | stat_scope: DEX | stat_modification_type: flat_penalty | stat_modification_value: -2
condition_custom: "can't use reactions, can use action OR bonus action (not both), multiattack limited to one attack, spellcasting may be delayed one round (50%)"
save_frequency: each_turn_end | save_ends_effect: true
```

**Lightning Bolt**
```
cost_type: spell_slot | slot_level: 3
action_type: action
range_type: self
aoe_shape: line | aoe_size_primary: 100 | aoe_size_secondary: 5
aoe_anchor: caster_origin
resolution_type: saving_throw | save_ability: DEX
save_success_effect: half_damage
damage_dice: 8d6 | damage_type: lightning
upcast: +1d6 per slot level above 3rd
object_interaction: ignites flammable objects not worn/carried
```

**Revivify**
```
cost_type: spell_slot | slot_level: 3
action_type: action
range_type: touch
target_type: single_creature
target_restriction: "died within last minute, not undead or construct"
resolution_type: automatic
heal_type: hit_points | heal_value: 1
component_material: "diamonds worth 300gp" (consumed)
NOTE: unique "resurrection" mechanic — brings dead creature back to life
```

**Hypnotic Pattern**
```
cost_type: spell_slot | slot_level: 3
action_type: action
range_type: ranged | range_distance: 120
aoe_shape: cube | aoe_size_primary: 30
aoe_anchor: point_in_range
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: WIS
save_success_effect: no_effect
condition: charmed + incapacitated + speed_zero
end_condition: "takes damage or another creature uses action to shake it free"
target_restriction: "creature that can see the pattern"
```

**Call Lightning**
```
cost_type: spell_slot | slot_level: 3
action_type: action
range_type: ranged | range_distance: 120
aoe_shape: cylinder | aoe_size_primary: 60 (storm cloud radius) | aoe_size_secondary: 10 (height)
duration_type: timed | duration_value: 10 | duration_unit: minute | concentration: true
NOTE — the cloud is placed, then each turn:
action_on_subsequent_turns: action to call bolt
bolt_aoe: sphere | aoe_size_primary: 5 | centered on point under cloud
resolution_type: saving_throw | save_ability: DEX
save_success_effect: half_damage
damage_dice: 3d10 | damage_type: lightning
upcast: +1d10 per slot level above 3rd
condition_branch: if already stormy outdoors → +1d10 damage
NOTE: "persistent effect that uses action on subsequent turns to trigger damage" — recurring action usage
```

**Animate Dead**
```
cost_type: spell_slot | slot_level: 3
action_type: 1 minute
range_type: ranged | range_distance: 10
target_type: single_object (pile of bones or corpse)
duration_type: instantaneous (but creature persists)
summon_type: creature
summon_stat_block: skeleton or zombie (linked character sheet)
summon_count: 1
summon_behavior: obeys_commands (bonus action to command)
summon_duration: 24 hours (must recast to maintain)
upcast: +2 creatures per slot level above 3rd
NOTE: the "must recast within 24h to maintain control" is a unique maintenance mechanic
```

### 4th Level Spells

**Wall of Fire**
```
cost_type: spell_slot | slot_level: 4
action_type: action
range_type: ranged | range_distance: 120
aoe_shape: wall | aoe_size_primary: 60 (length) | aoe_size_secondary: 20 (height), 1ft thick
    OR: ring, 20ft diameter, 20ft high, 1ft thick
aoe_anchor: point_in_range
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: DEX
save_success_effect: half_damage
damage_dice: 5d8 | damage_type: fire
trigger_timing: on_first_enter_area_per_turn (one side chosen by caster) + on_end_turn_in_wall
upcast: +1d8 per slot level above 4th
```

**Banishment**
```
cost_type: spell_slot | slot_level: 4
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: CHA
save_success_effect: no_effect
condition_custom: "target is sent to harmless demiplane (incapacitated)"
condition_branch: if target is not native to current plane → permanent banishment if concentration maintained full duration
save_frequency: none (one save only)
upcast: +1 target per slot level above 4th
```

**Polymorph**
```
cost_type: spell_slot | slot_level: 4
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
duration_type: timed | duration_value: 1 | duration_unit: hour | concentration: true
resolution_type: saving_throw | save_ability: WIS (unwilling only)
save_success_effect: no_effect
target_restriction: "not shapechanger"
summon_stat_block: beast of CR <= target's level (linked character sheet — your swap solution!)
end_condition: "drops to 0 HP in beast form (excess damage carries over) or spell ends"
willing_vs_unwilling: willing targets auto-fail save
```

**Greater Invisibility**
```
cost_type: spell_slot | slot_level: 4
action_type: action
range_type: touch
target_type: willing_creature
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: automatic
condition: invisible
NOTE: unlike regular Invisibility, doesn't end on attack/spell
```

**Ice Storm**
```
cost_type: spell_slot | slot_level: 4
action_type: action
range_type: ranged | range_distance: 300
aoe_shape: cylinder | aoe_size_primary: 20 | aoe_size_secondary: 40
aoe_anchor: point_in_range
resolution_type: saving_throw | save_ability: DEX
save_success_effect: half_damage_no_condition
damage_dice: 2d8 bludgeoning + 4d6 cold
difficult_terrain: true (ground ices over, lasts until end of next turn)
upcast: +1d8 bludgeoning per slot level above 4th
```

### 5th Level Spells

**Wall of Force**
```
cost_type: spell_slot | slot_level: 5
action_type: action
range_type: ranged | range_distance: 120
aoe_shape: wall (10 panels, 10x10 each, contiguous) OR sphere/hemisphere 10ft radius
duration_type: timed | duration_value: 10 | duration_unit: minute | concentration: true
resolution_type: automatic (no save)
wall_properties: indestructible, immune to damage, blocks physical/magical passage
spell_interaction: destroyed by Disintegrate
NOTE: one of the most powerful control spells — the "indestructible barrier" mechanic is fairly unique
```

**Animate Objects**
```
cost_type: spell_slot | slot_level: 5
action_type: action
range_type: ranged | range_distance: 120
target_type: multiple_objects | target_count: 10 (varies by size: 10 tiny, 2 huge, etc.)
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
summon_type: creature (animated objects)
summon_behavior: obeys_commands (bonus action)
summon_stat_block: varies by object size (linked sheets)
upcast: +2 objects per slot level above 5th
```

**Synaptic Static**
```
cost_type: spell_slot | slot_level: 5
action_type: action
range_type: ranged | range_distance: 120
aoe_shape: sphere | aoe_size_primary: 20
aoe_anchor: point_in_range
resolution_type: saving_throw | save_ability: INT
save_success_effect: half_damage_no_condition
damage_dice: 8d6 | damage_type: psychic
target_restriction: "creatures with INT 3+"
condition_custom: "subtract 1d6 from attack rolls, ability checks, and concentration saves for 1 minute"
save_frequency: each_turn_end (to end the debuff only)
```

**Destructive Wave (Paladin)**
```
cost_type: spell_slot | slot_level: 5
action_type: action
range_type: self
aoe_shape: sphere | aoe_size_primary: 30
aoe_anchor: caster_centered
resolution_type: saving_throw | save_ability: CON
save_success_effect: half_damage_no_condition
damage_dice: 5d6 thunder + 5d6 radiant OR necrotic (caster chooses)
condition: prone (on failed save)
target_restriction: caster chooses which creatures in range are affected
```

---

## PRIMITIVES IDENTIFIED FROM DECOMPOSITION

Here is the consolidated list of every primitive needed, including ones that emerged during the decomposition:

### New Primitives Discovered

| Primitive | Why Needed | Example Spell |
|---|---|---|
| `damage_type_choice` | Caster picks damage type at cast time | Chromatic Orb, Spirit Guardians |
| `condition_choice` | Caster picks which condition to apply | Blindness/Deafness |
| `damage_per_5ft_moved` | Damage based on movement through area | Spike Growth |
| `recurring_action` | Use action/bonus action on later turns for more effects | Witch Bolt, Spiritual Weapon, Call Lightning |
| `end_penalty` | Negative effect when spell ends | Haste (lethargy) |
| `grants_extra_action` | Target gains additional action | Haste |
| `maintenance_recast` | Must recast to maintain control | Animate Dead |
| `hp_pool_mechanic` | Effects determined by HP pool, not saves | Sleep |
| `excess_damage_carryover` | Damage beyond form HP carries to real HP | Polymorph |
| `selective_targeting` | Caster can exclude specific creatures in AoE | Spirit Guardians, Destructive Wave |
| `transfer_on_death` | Effect moves to new target when current drops to 0 | Hex, Hunter's Mark |
| `wall_panels` | Wall built from discrete panels | Wall of Force, Wall of Fire |
| `indestructible` | Effect cannot be destroyed by damage | Wall of Force |
| `environmental_condition_bonus` | Extra effect if certain conditions met | Call Lightning (stormy weather) |
| `delayed_spell_chance` | Percentage chance of delaying a spell | Slow (50% spell delay) |
| `multiattack_reduction` | Limits number of attacks | Slow |
| `action_or_bonus_restriction` | Can only use one, not both | Slow |
| `auto_crit_condition` | Attacks become auto-crits under conditions | Hold Person (paralyzed + within 5ft) |
| `size_category_scaling` | Effect varies by target/object size | Animate Objects |

---

## WHAT THIS GRAMMAR PROBABLY CAN'T COVER

Some spells are fundamentally narrative or have mechanics so unique they may need hardcoded special handling:

1. **Wish** — literally anything (you're already skipping this)
2. **Prestidigitation / Thaumaturgy / Druidcraft** — too open-ended (skipping)
3. **Simulacrum** — creates a half-HP duplicate of a creature
4. **Maze** — banishes to extradimensional maze, INT check to escape
5. **Imprisonment** — multiple mode choices with vastly different mechanics
6. **Contingency** — stores a spell with a conditional trigger
7. **Glyph of Warding** — similar to Contingency
8. **Time Stop** — grants 1d4+1 extra turns
9. **Power Word Kill/Stun/Heal** — HP threshold with no save
10. **Feeblemind** — INT and CHA become 1

Some of these (Power Word spells, Feeblemind) could be handled with the existing `hp_threshold_branch` and `stat_modification: set_value` primitives. Others like Contingency and Time Stop probably need special handling or could simply be flagged as "DM-assisted" spells in your app.

---

## NEXT STEPS

1. **Map these primitives to your character editor fields** — see which ones you already support
2. **Identify gaps** — which primitives are missing from your editor?
3. **Prioritize by frequency** — the "core" primitives (damage, saves, AoE, conditions, concentration) cover ~80% of spells. The "discovered" primitives from the table above are less common but still important.
4. **Playtester audit** — have your friends each pick 5-10 spells they plan to use and try to build them. This will quickly surface any remaining holes.
5. **I can continue decomposing** — I covered cantrips through 5th level here. Want me to do 6th–9th as well?

---

## AUDIT RESULTS (v0.16.0)

Audit performed against dnd_combat_sim v0.13.1, updated for v0.14.0 (on-hit riders), v0.15.0 (buff/debuff system), and v0.16.0 (upcast scaling). Each primitive is rated:
- **SUPPORTED** = Field exists on the model AND the combat engine processes it
- **PARTIAL** = Some aspect works but gaps remain
- **NOT SUPPORTED** = No field or runtime handling exists

### 1. RESOURCE COST

| Primitive | Status | Implementation Notes |
|---|---|---|
| `cost_type` | **SUPPORTED** | Cantrip = no `resource_cost`; spell = `spell_slot_N` key in `resource_cost`; class resource = named key (e.g., `"ki_points"`). Detected by radial menu for categorization. |
| `slot_level` | **SUPPORTED** | `PlayerCharacter.spell_slots: dict[int, int]` configured in Features tab. Auto-bridged to `class_resources` via `sync_spell_slots_to_resources` validator as `spell_slot_1` through `spell_slot_9`. Actions tab has spell level dropdown. |
| `resource_name` | **SUPPORTED** | `Action.resource_cost: dict[str, int]` — arbitrary named keys. |
| `resource_amount` | **SUPPORTED** | Values in `resource_cost` dict. `check_resource_cost()` and `deduct_resource_cost()` in `src/combat/actions.py` handle checking and deduction. |
| `component_verbal` | **NOT SUPPORTED** | No spell component tracking. Low combat impact (flavor/Silence interaction only). |
| `component_somatic` | **NOT SUPPORTED** | Same as above. |
| `component_material` | **PARTIAL** | No explicit field, but physical components (e.g., "300gp diamond") can be modeled as a class resource with a count tied to a spell's `resource_cost`. Functional but not first-class. |
| `ritual_castable` | **NOT SUPPORTED** | No ritual casting mechanic. Would need a bool field + "cast as ritual" option that skips slot cost but takes 10 minutes. |

**Key files**: `src/models/character.py` (spell_slots, validator), `src/combat/actions.py` (check/deduct), `src/gui/screens/creature_builder_tabs/features_tab.py` (spell slot spinners), `actions_tab.py` (spell level dropdown), `src/gui/spell_popup.py` (slot display).

### 2. CASTING TIME / ACTION ECONOMY

| Primitive | Status | Implementation Notes |
|---|---|---|
| `action_type` | **SUPPORTED** | `ActionType` enum: ACTION, BONUS_ACTION, REACTION, LEGENDARY, LAIR, FREE. Covers all combat-relevant casting times. |
| `action_count` | **NOT SUPPORTED** | No multi-minute/hour casting times (e.g., Animate Dead = 1 minute). Low combat priority — these spells are typically cast before initiative. |
| `reaction_trigger` | **NOT SUPPORTED** | No trigger description field. Reactions function mechanically (Shield, Counterspell can be used as reactions) but there's no way to define *when* they trigger. Currently the player just chooses to use them manually. |

### 3. RANGE & TARGETING

| Primitive | Status | Implementation Notes |
|---|---|---|
| `range_type` | **PARTIAL** | `range: int` handles distance. Self is via `TargetType.SELF`. No explicit touch/sight/unlimited distinction — touch is just `range: 5`, sight would need special handling. |
| `range_distance` | **SUPPORTED** | `Action.range: int` in feet. |
| `target_type` | **PARTIAL** | `TargetType` enum has: SELF, ONE_CREATURE, ONE_ALLY, ONE_ENEMY, AREA_SPHERE, AREA_CONE, AREA_LINE, AREA_CUBE, AREA_CYLINDER. Missing: MULTIPLE_CREATURES, WILLING_CREATURE, POINT_IN_SPACE, CREATURE_OR_OBJECT, SINGLE_OBJECT. |
| `target_count` | **NOT SUPPORTED** | No multi-target field. Magic Missile (3 darts), Scorching Ray (3 rays), Eldritch Blast (multiple beams), Hold Person upcast (+1 target) all require this. **High-impact gap.** |
| `target_count_scaling` | **NOT SUPPORTED** | Depends on upcast system (see Scaling). |
| `target_restriction` | **NOT SUPPORTED** | No humanoid/beast/undead filter. Would be flavor/UI only since the sim doesn't enforce creature type targeting. |
| `line_of_sight_required` | **NOT SUPPORTED** | Not tracked. Low priority — most combat assumes LoS. |
| `aoe_shape` | **MOSTLY SUPPORTED** | Via TargetType area subtypes: sphere, cone, line, cube, cylinder. Missing: wall, hemisphere, ring, aura. Wall is partially addressed by `terrain_modification="wall"` but not as an AoE shape. |
| `aoe_size_primary` | **SUPPORTED** | `Action.area_size: int` (radius/length in feet). |
| `aoe_size_secondary` | **NOT SUPPORTED** | No secondary dimension field. Lines have no width, cylinders have no height, walls have no height/thickness. Affects Lightning Bolt (100ft x 5ft), Moonbeam (5ft radius x 40ft height), Wall of Fire (60ft x 20ft). |
| `aoe_anchor` | **PARTIAL** | Implicit from context: SELF target_type = caster_centered, AREA_* = point_in_range (click-to-place). `zone_follows_caster` handles caster-centered zones. No explicit anchor field for caster_origin (cones/lines emanating from caster). |
| `aoe_moves_with_caster` | **SUPPORTED** | `Action.zone_follows_caster: bool`. Zone system in `src/combat/zones.py` re-centers on caster each turn. |
| `aoe_moveable` | **SUPPORTED** | Implied by `zone_move_cost` being set. |
| `aoe_move_action_cost` | **SUPPORTED** | `Action.zone_move_cost: str` — "action" or "bonus_action". |
| `aoe_move_distance` | **NOT SUPPORTED** | No max move distance per repositioning (Moonbeam: 60ft per move). Zones currently move without distance limit. |

### 4. DURATION & CONCENTRATION

| Primitive | Status | Implementation Notes |
|---|---|---|
| `duration_type` | **PARTIAL** | No general duration field on Action, but `Action.buff_duration_rounds: int` handles buff/debuff durations. Conditions have duration via `AppliedCondition.duration_type`. Buffs have duration via `ActiveBuff.duration_type` ("indefinite", "rounds", "end_of_turn", "start_of_turn") + `duration_rounds`. **(Updated v0.15.0)** |
| `duration_value` | **PARTIAL** | `buff_duration_rounds` on Action covers buff durations. No general duration for other non-condition, non-buff effects. |
| `duration_unit` | **NOT SUPPORTED** | No minute/hour/day unit. Buff durations are in rounds only. |
| `concentration` | **SUPPORTED** | `Action.requires_concentration: bool`. Full concentration tracking in combat: only one spell, CON saves on damage, lost on incapacitation. Zones, terrain mods, and **buffs** are removed on concentration loss. **(Updated v0.15.0: concentration now tracks and cleans up linked buffs via `linked_buffs` in extra_data.)** |

**Note**: Duration gaps are partially mitigated by:
- Zones: persist until concentration lost (implicit duration)
- Conditions: have their own duration tracking via `AppliedCondition`
- Terrain modifications: persist until concentration lost or permanently
- **Buffs (v0.15.0)**: `ActiveBuff` has full duration tracking (rounds, save-to-end, concentration-linked). Covers Shield (+5 AC for 1 round), Haste (concentration), Bane (save-to-end each turn), etc.

The remaining gap is for timed non-condition, non-zone, non-buff effects and minute/hour duration units.

### 5. ATTACK / SAVE MECHANIC

| Primitive | Status | Implementation Notes |
|---|---|---|
| `spell_attack_ranged` | **SUPPORTED** | `Attack.attack_type = "ranged_spell"`. |
| `spell_attack_melee` | **SUPPORTED** | `Attack.attack_type = "melee_spell"`. |
| `saving_throw` | **SUPPORTED** | `SavingThrowEffect` with `ability`, `dc`, `dc_ability`, `damage_on_fail`, `damage_on_success`, `conditions_on_fail/success`. |
| `automatic` | **SUPPORTED** | Omit both `attack` and `saving_throw` — effect applies automatically. |
| `contested_check` | **PARTIAL** | Shove uses contested Athletics vs Athletics/Acrobatics internally in `src/combat/forced_movement.py`, but not user-configurable. No generic contested check on Action. |
| `save_ability` | **SUPPORTED** | `SavingThrowEffect.ability` (e.g., "dexterity"). |
| `save_success_effect` | **SUPPORTED** | `SavingThrowEffect.damage_on_success`: "none", "half", "full". Conditions have separate `conditions_on_success` list. |
| `save_frequency` | **PARTIAL** | `AppliedCondition.save_to_end` + `save_dc` handle end-of-turn re-saves. `duration_type = "start_of_turn"` + `"end_of_turn"` cover when conditions check. Missing: on-action re-saves (Entangle's "use action to repeat STR check"), on-damage re-saves. |
| `save_ends_effect` | **PARTIAL** | Via `AppliedCondition.save_to_end` — successful save removes the condition. Works for end-of-turn saves. |
| `contested_attacker_ability` | **NOT CONFIGURABLE** | Hardcoded in shove system. |
| `contested_defender_ability` | **NOT CONFIGURABLE** | Hardcoded in shove system. |

### 6. EFFECTS

#### 6a. Damage

| Primitive | Status | Implementation Notes |
|---|---|---|
| `damage_dice_count/size` | **SUPPORTED** | `DamageRoll.dice` (e.g., "2d6", "8d6"). |
| `damage_bonus` | **SUPPORTED** | `DamageRoll.bonus` (flat) + `DamageRoll.ability_modifier` (e.g., "strength"). |
| `damage_type` | **SUPPORTED** | Full 13-type `DamageType` enum. |
| `damage_on_save` | **SUPPORTED** | `SavingThrowEffect.damage_on_success`: "none", "half", "full". |
| `damage_rider` (multi-type same action) | **SUPPORTED** | `Attack.damage: list[DamageRoll]` and `SavingThrowEffect.damage_on_fail: list[DamageRoll]` both accept multiple entries. UI supports up to 3 damage rows for attacks, 2 for saves. Ice Storm (2d8 bludgeoning + 4d6 cold) works. `roll_damage()` in `src/combat/damage.py` loops through all entries. |
| `damage_rider` (deferred on-hit bonus) | **NOT SUPPORTED** | Hex/Hunter's Mark style "add 1d6 to every future attack hit" has no mechanism. This is an effect trigger gap (see Section 7). |

**Known limitation**: Resistance/immunity is applied only to the **primary damage type** (first `DamageRoll` in the list). For Ice Storm, if cold is listed second and the target resists cold, that resistance won't apply. Per-type resistance would need `apply_damage()` to process each `DamageRoll` independently.

#### 6b. Healing

| Primitive | Status | Implementation Notes |
|---|---|---|
| `heal_dice/bonus` | **SUPPORTED** | `Action.healing: str` — dice expression (e.g., "2d8+3"). Resolved via `roll_expression()`. |
| `heal_type: hit_points` | **SUPPORTED** | Default healing behavior. |
| `heal_type: temp_hp` | **SUPPORTED** | `Action.grants_temporary_hp: str` — dice expression. |
| `heal_type: max_hp_restore` | **NOT SUPPORTED** | No max HP restoration (Greater Restoration, Heal). Would need a field to increase `max_hp` back toward original. |

#### 6c. Conditions Applied

| Primitive | Status | Implementation Notes |
|---|---|---|
| Standard conditions | **SUPPORTED** | `Condition` enum has all 15 standard 5e conditions (blinded, charmed, deafened, exhaustion, frightened, grappled, incapacitated, invisible, paralyzed, petrified, poisoned, prone, restrained, stunned, unconscious) plus combat pseudo-conditions (concentrating, dodging, helped, hidden). `Action.conditions_applied: list[str]` and `SavingThrowEffect.conditions_on_fail: list[str]`. |
| `condition_duration` | **PARTIAL** | `AppliedCondition` has: `duration_type` ("indefinite", "rounds", "end_of_turn", "start_of_turn"), `duration_rounds`, `save_to_end`, `save_dc`. However, these are set during combat resolution, not configurable on the Action model. The Action has no fields to specify "apply blinded for 3 rounds with WIS DC 15 save to end each turn." This is handled implicitly in some code paths but not uniformly configurable. |
| `condition_custom` | **NOT SUPPORTED** | No non-standard conditions like "can't take reactions", "speed is 0", "disadvantage on next attack roll". These would need either a free-text custom condition or specific mechanical fields. |

#### 6d. Movement Effects

| Primitive | Status | Implementation Notes |
|---|---|---|
| `forced_movement_type` push/pull/slide | **SUPPORTED** | `Action.forced_movement_type: str` — "push", "pull", or "slide". Resolved via `src/combat/forced_movement.py`. |
| `forced_movement_distance` | **SUPPORTED** | `Action.forced_movement_distance: int` in feet. |
| `forced_movement_direction` | **PARTIAL** | Push = away from caster, pull = toward caster. No "choice" or "specific_point" direction. The "slide" type allows lateral movement. |
| Teleport (caster) | **SUPPORTED** | `Action.teleport_range`, `teleport_self=True`. Full system with visual effects, OA bypass. |
| Teleport (target) | **SUPPORTED** | `teleport_self=False`. |
| Teleport (passenger) | **SUPPORTED** | `teleport_passenger=True` with `PassengerPopup` for ally selection. |
| `speed_modification` | **SUPPORTED (v0.15.0)** | Buff system supports speed modification: `BuffEffect(stat="speed", modifier_type="flat_bonus")` for flat bonuses (Longstrider +10) and `BuffEffect(stat="speed", modifier_type="multiply", value=2.0)` for multipliers (Haste x2, Slow x0.5). Integrated into `get_effective_speed()`. |
| `difficult_terrain` | **SUPPORTED** | `Action.terrain_modification = "difficult"`. Full terrain modification system in `src/combat/terrain_effects.py`. |

#### 6e. Buffs / Debuffs (Stat Modifications from Spells) — **RESOLVED (v0.15.0)**

| Primitive | Status | Implementation Notes |
|---|---|---|
| `stat_target` | **SUPPORTED (v0.15.0)** | `BuffEffect.stat`: "ac", "attack_rolls", "saving_throws", "speed", "ability_checks", "damage_resistance". Defined on `Action.buff_effects: list[BuffEffect]`. |
| `stat_modification_type` | **SUPPORTED (v0.15.0)** | `BuffEffect.modifier_type`: "flat_bonus", "advantage", "disadvantage", "resistance", "immunity", "multiply". |
| `stat_modification_value` | **SUPPORTED (v0.15.0)** | `BuffEffect.value`: int (Shield +5), str dice expression (Bless "1d4"), float multiplier (Haste 2.0), str damage type (Absorb Elements "fire"), or None (advantage/disadvantage). |
| `stat_scope` | **SUPPORTED (v0.15.0)** | `BuffEffect.scope`: "all" (default), or specific ability/type (e.g., "dexterity" for Haste DEX save advantage). |

**Context**: Full buff/debuff system implemented in v0.15.0. `Action.buff_effects: list[BuffEffect]` + `Action.buff_duration_rounds: int | None` define temporary stat modifications. `ActiveBuff` tracks live buffs on `Creature.active_buffs`. Pure query functions in `src/combat/buff_effects.py` integrated into stat_modifiers.py (AC, speed, resistances, immunities), condition_effects.py (advantage/disadvantage), and actions.py (attack/save roll bonuses including dice expressions). Supports target-side debuffs via `BuffEffect.target_grants_to_attacker` (Faerie Fire pattern). Duration: concentration-linked (auto-removed on concentration loss via `linked_buffs`), fixed rounds (ticked at turn start), save-to-end (rolled at turn end). 57 tests in `test_buff_effects.py`. Unlocks: Shield, Bless, Bane, Haste, Slow, Faerie Fire, Absorb Elements, Shield of Faith, Longstrider, and arbitrary homebrew buff/debuff spells.

#### 6f. Summon / Create

| Primitive | Status | Implementation Notes |
|---|---|---|
| `summon_type: creature` | **SUPPORTED** | `Action.summon_creature: str` — path to creature JSON. |
| `summon_stat_block` | **SUPPORTED** | Linked creature sheet loaded from JSON. |
| `is_wild_shape` | **SUPPORTED** | `Action.is_wild_shape: bool` — 0 HP removes summon, restores original form with HP overflow. |
| `summon_count` | **NOT SUPPORTED** | Always summons exactly 1 creature. Animate Dead (+2 per level above 3rd), Animate Objects (10 tiny objects) not possible. |
| `summon_duration` | **NOT SUPPORTED** | No timed removal of summons. Currently persist until killed or combat ends. |
| `summon_behavior` | **NOT SUPPORTED** | No command mechanic (bonus action to command). Summons use AI or player control based on team. |
| `wall_properties` | **NOT SUPPORTED** | No wall panels, HP per section, or barrier mechanics. Wall of Fire/Force not modellable beyond terrain modification. |

#### 6g. Utility / Status Effects

| Primitive | Status | Implementation Notes |
|---|---|---|
| `grants_sense` | **NOT SUPPORTED** | No darkvision/truesight/blindsight granting. |
| `grants_movement` | **NOT SUPPORTED** | No flying/swimming/climbing speed granting. |
| `light_emission` | **NOT SUPPORTED** | No light radius mechanic. |
| `dispel_effect` | **NOT SUPPORTED** | No Dispel Magic / remove-spell mechanic. |
| `counter_effect` | **NOT SUPPORTED** | No Counterspell / interrupt mechanic. |
| `proficiency_grant` | **NOT SUPPORTED** | Low combat priority. |
| `language_grant` | **NOT SUPPORTED** | Not combat-relevant. |

### 7. EFFECT TRIGGERS & TIMING

| Primitive | Status | Implementation Notes |
|---|---|---|
| `on_cast` | **SUPPORTED** | Default behavior — effect resolves immediately when action is used. |
| `on_first_enter_area_per_turn` | **SUPPORTED** | Zone system: `process_zone_entry()` triggers on movement into zone, `already_damaged` set prevents double-dip per round. |
| `on_start_turn_in_area` | **SUPPORTED** | Zone system: `process_zone_start_of_turn()` checks each creature at turn start. |
| `on_hit` (deferred rider) | **SUPPORTED (v0.14.0)** | Generalized on-hit rider system via `Feature.on_hit_rider: OnHitRider`. Supports POST_HIT (player chooses, e.g. Divine Smite) and AUTOMATIC (fires every hit, e.g. Sneak Attack) triggers. Configurable resource cost (spell slots, ki, etc.), bonus damage with per-slot scaling, saving throws with conditions on fail, once-per-turn tracking. Engine: `src/combat/riders.py`. GUI: `RiderPopup` sequential queue. AI: two-phase attack with `_score_rider_for_ai()`. Builder: rider editor in features_tab.py. RIDER_PRESETS: divine_smite, sneak_attack, stunning_strike, eldritch_smite, hex_damage. Hex/Hunter's Mark "on next hit" buff spells still need the buff/debuff system to apply the rider via a spell — but the rider engine itself is fully operational when configured on a Feature. |
| `on_target_movement` | **NOT SUPPORTED** | Booming Blade's "if target willingly moves" trigger. |
| `on_being_attacked` | **NOT SUPPORTED** | Shield's "when hit by attack" trigger. |
| `start_of_target_turn` / `end_of_target_turn` | **PARTIAL** | Condition saves work (save_to_end). Zone damage at turn start works. But no general "deal damage at start of target's turn" outside the zone system. |
| `bonus_action_followup` | **NOT SUPPORTED** | Spiritual Weapon (bonus action on later turns to attack again), Heat Metal (bonus action to re-deal damage), Hex transfer (bonus action to move to new target). No recurring action framework. |
| `trigger_who` | **PARTIAL** | Zone has `affects_enemies_only`. No general friend/foe/self/any targeting for triggers. |
| `trigger_frequency` | **PARTIAL** | Zone has `already_damaged` per-round tracking (once per turn). No configurable frequency. |
| `trigger_uses` | **NOT SUPPORTED** | |
| `delayed_rounds` | **NOT SUPPORTED** | |

### 8. SCALING

| Primitive | Status | Implementation Notes |
|---|---|---|
| `cantrip_scale_levels` | **NOT SUPPORTED** | No cantrip scaling by character level. Users must manually increase damage dice or create separate actions per tier. |
| `cantrip_scale_effect` | **NOT SUPPORTED** | |
| `cantrip_scale_extra` | **NOT SUPPORTED** | Eldritch Blast beam count scaling not possible. |
| `upcast_per_level` | **SUPPORTED** | `Action.upcast_damage_per_levels: int` (default 1). Supports per-2-level scaling (Spiritual Weapon). `Action.spell_level: int` stores base spell level. Engine computes bonus dice automatically from `cast_level`. (v0.16.0) |
| `upcast_damage_dice` | **SUPPORTED** | `Action.upcast_damage_dice: str` (e.g., "1d6"). `src/combat/upcast.py::calculate_upcast_bonus_damage()` computes bonus `DamageRoll` list. Wired into `resolve_attack_damage()` and `resolve_effect()`. Zone spells bake upcast dice into zone at creation. (v0.16.0) |
| `upcast_target_count` | **NOT SUPPORTED** | No `upcast_extra_targets` field. Hold Person (+1 target), Animate Dead (+2 undead), Scorching Ray (+1 ray) need this. |
| `upcast_duration` | **NOT SUPPORTED** | Rare for levels 1-5. Low priority. |
| `upcast_healing_dice` | **SUPPORTED** | `Action.upcast_healing_dice: str` (e.g., "1d8"). `src/combat/upcast.py::calculate_upcast_bonus_healing()` computes bonus expression. Wired into `resolve_effect()` healing path. (v0.16.0) |
| `upcast_effect_threshold` | **NOT SUPPORTED** | Bestow Curse (5th: no concentration), Animate Dead (qualitative changes). Hard to systematize. |
| `upcast_special` | **NOT SUPPORTED** | Complex per-spell logic. Low priority for engine. |

### 9. SPECIAL MECHANICS

| Primitive | Status | Implementation Notes |
|---|---|---|
| `attack_replacement` | **NOT SUPPORTED** | Booming Blade / Green-Flame Blade "make a weapon attack as part of the spell" not modellable. |
| `extra_attack_compatible` | **NOT SUPPORTED** | |
| `bonus_action_followup` | **NOT SUPPORTED** | See Triggers section. |
| `creature_type_bonus` | **NOT SUPPORTED** | Moonbeam disadvantage vs shapechangers, bonus damage vs undead, etc. |
| `death_save_interaction` | **NOT SUPPORTED** | Auto-crit on paralyzed within 5ft is a 5e rule, not currently enforced. |
| `object_interaction` | **NOT SUPPORTED** | "Ignites flammable objects" — flavor, low combat priority. |
| `cover_interaction` | **NOT SUPPORTED** | "Spreads around corners" — would need cover system first. |

### 10. CONDITIONAL / BRANCHING EFFECTS

| Primitive | Status | Implementation Notes |
|---|---|---|
| `condition_branch` | **NOT SUPPORTED** | No if/then branching on spell effects. |
| `damage_type_choice` | **NOT SUPPORTED** | Chromatic Orb "choose acid/cold/fire/etc." not modellable. User would need to create separate actions per damage type. |
| `condition_choice` | **NOT SUPPORTED** | Blindness/Deafness "choose blinded or deafened" not modellable. |
| `hp_threshold_branch` | **NOT SUPPORTED** | Sleep's HP pool mechanic, Toll the Dead's d8 vs d12 based on missing HP. |
| `selective_targeting` | **NOT SUPPORTED** | Spirit Guardians "choose which creatures are affected in AoE" — `ActiveZone.affects_enemies_only` is the closest, but only friend/foe, not per-creature selection. |
| `willing_vs_unwilling` | **NOT SUPPORTED** | Polymorph auto-fail for willing targets. |

### NEW PRIMITIVES FROM DECOMPOSITION — Audit

| Primitive | Status | Notes |
|---|---|---|
| `damage_type_choice` | **NOT SUPPORTED** | Need cast-time prompt or separate actions per type. |
| `condition_choice` | **NOT SUPPORTED** | Same as above. |
| `damage_per_5ft_moved` | **NOT SUPPORTED** | Spike Growth's per-5ft damage. Zone system deals damage on entry but not proportional to distance moved. |
| `recurring_action` | **NOT SUPPORTED** | Witch Bolt, Spiritual Weapon, Call Lightning subsequent-turn actions. |
| `end_penalty` | **NOT SUPPORTED** | Haste lethargy when spell ends. |
| `grants_extra_action` | **NOT SUPPORTED** | Haste's additional action per turn. |
| `maintenance_recast` | **NOT SUPPORTED** | Animate Dead 24-hour recast requirement. |
| `hp_pool_mechanic` | **NOT SUPPORTED** | Sleep's ascending-HP targeting. |
| `excess_damage_carryover` | **SUPPORTED** | Wild Shape system handles HP overflow back to original form via `is_wild_shape`. |
| `selective_targeting` | **PARTIAL** | `ActiveZone.affects_enemies_only` handles friend/foe. No per-creature selection in AoE. |
| `transfer_on_death` | **NOT SUPPORTED** | Hex/Hunter's Mark "move to new target when current dies." |
| `wall_panels` | **NOT SUPPORTED** | No discrete wall panel system. |
| `indestructible` | **NOT SUPPORTED** | Wall of Force immunity to damage. |
| `environmental_condition_bonus` | **NOT SUPPORTED** | Call Lightning stormy weather bonus. |
| `delayed_spell_chance` | **NOT SUPPORTED** | Slow's 50% spell delay. |
| `multiattack_reduction` | **NOT SUPPORTED** | Slow limits multiattack to one. |
| `action_or_bonus_restriction` | **NOT SUPPORTED** | Slow's "action OR bonus, not both." |
| `auto_crit_condition` | **NOT SUPPORTED** | Paralyzed + within 5ft = auto-crit (5e rule, not enforced). |
| `size_category_scaling` | **NOT SUPPORTED** | Animate Objects size-based stat variation. |

### SUMMARY SCORECARD (Updated v0.15.0)

| Category | Supported | Partial | Not Supported | Notes |
|---|---|---|---|---|
| 1. Resource Cost | 4 | 1 | 2 | Spell slots fully working. Components are flavor. |
| 2. Casting Time | 1 | 0 | 2 | Core action economy solid. Long cast times irrelevant to combat. |
| 3. Range & Targeting | 6 | 3 | 4 | AoE and zones strong. Multi-target is the big gap. |
| 4. Duration & Concentration | 1 | 2 | 1 | Concentration excellent. Buff durations working (v0.15.0). General duration unit still missing. |
| 5. Attack / Save | 5 | 3 | 2 | Strongest category. Contested checks and re-save variants are gaps. |
| 6a. Damage | 5 | 0 | 1 | Multi-damage works. Per-type resistance is a minor limitation. |
| 6b. Healing | 3 | 0 | 1 | Max HP restore only gap. |
| 6c. Conditions | 1 | 1 | 1 | Standard conditions strong. Custom conditions missing. |
| 6d. Movement | 6 | 1 | 0 | Teleport + forced movement + speed modification (v0.15.0) strong. |
| 6e. Buffs/Debuffs | 4 | 0 | 0 | **RESOLVED (v0.15.0).** Full buff/debuff system: stat_target, modifier_type, value, scope all supported. |
| 6f. Summon/Create | 3 | 0 | 4 | Single summon works. Multi-summon, walls, duration missing. |
| 6g. Utility | 0 | 0 | 7 | All missing. Most are low combat priority. |
| 7. Triggers & Timing | 4 | 2 | 4 | Zones handle AoE triggers. On-hit riders now supported (v0.14.0). Recurring actions still missing. |
| 8. Scaling | 3 | 0 | 5 | Upcast damage/healing dice + per-level scaling supported (v0.16.0). Cantrip scaling, upcast target count, duration, effect thresholds still missing. |
| 9. Special Mechanics | 0 | 0 | 5 | All missing. Mixed priority. |
| 10. Branching | 0 | 0 | 5 | All missing. Workaround: separate actions per choice. |
| **TOTALS** | **46** | **13** | **43** | **(was 43/13/46 at v0.15.0, 38/11/53 at v0.13.1)** |

### TOP 5 HIGHEST-IMPACT GAPS (by spell count affected)

1. ~~**Buff/Debuff system (6e)**~~ — **RESOLVED (v0.15.0)**. Full buff/debuff system: `Action.buff_effects: list[BuffEffect]` defines temporary stat modifications (AC, attack rolls, saving throws, speed, damage resistance). `ActiveBuff` on creatures with duration tracking (rounds, save-to-end, concentration-linked). Integrated into stat_modifiers.py, condition_effects.py, actions.py, concentration.py, and manager.py. Target-side debuffs supported (Faerie Fire). 57 tests. Unlocks: Shield, Bless, Bane, Haste, Slow, Faerie Fire, Absorb Elements, Shield of Faith, Longstrider, and homebrew.

2. **Upcast scaling (8)** — **PARTIALLY RESOLVED (v0.16.0)**. Upcast damage dice (`upcast_damage_dice`), healing dice (`upcast_healing_dice`), and per-level step (`upcast_damage_per_levels`) now supported. `cast_level` threaded through entire resolution pipeline. AI scores upcast variants automatically. Zone spells (Spirit Guardians) bake upcast bonus into zone damage. **Remaining gaps**: upcast extra targets (Hold Person, Animate Dead), cantrip scaling, upcast duration, effect thresholds.

3. **Multi-target spells (3b)** — Magic Missile (3 darts), Scorching Ray (3 rays), Eldritch Blast (beams), Hold Person upcast, Bless/Bane (3 targets). No `target_count` field. Each target may be different, requiring a targeting loop.

4. ~~**On-hit rider / trigger system (7)**~~ — **RESOLVED (v0.14.0)**. Generalized on-hit rider system implemented on `Feature.on_hit_rider`. Covers Divine Smite, Sneak Attack, Stunning Strike, Eldritch Smite, and more via configurable trigger/cost/damage/save/condition fields. Engine (`src/combat/riders.py`), GUI (`RiderPopup`), AI (two-phase attack scoring), and Builder UI all complete. Remaining sub-gaps: Hex/Hunter's Mark still need the buff/debuff system to *apply* the rider via a spell (buff system now exists in v0.15.0, but Hex/Hunter's Mark combo still needs a "rider applied by buff" bridge); Booming Blade movement trigger (`on_target_movement`) still unsupported.

5. **Recurring actions / bonus action followup (7)** — Spiritual Weapon, Heat Metal, Call Lightning, Witch Bolt. Spells where the caster uses an action or bonus action on subsequent turns to re-trigger effects. No framework for "this spell gives you a new action option while active."

---

## PHASE 2: UI EXPOSURE AUDIT (v0.13.1)

> **Audit date**: 2026-02-25
> **Scope**: Can users actually configure these primitives in the Character Builder?
> **Method**: Systematic review of all 7 builder tabs (Identity, Abilities, Combat, Actions, Features, Token/AI, Equipment)

### UI Architecture Summary

The Character Builder has 7 tabs. The **Actions Tab** is by far the most relevant for spell/ability creation — it's a master-detail editor where each Action can be configured with ~35+ fields. The **Features Tab** handles passive bonuses and class resources. The **Equipment Tab** handles items with passive and consumable effects.

### Builder Tab Inventory

| Tab | What It Configures | Relevant to Spell Building? |
|-----|-------------------|----------------------------|
| **Actions** | Attack, Save, Damage, Healing, Conditions, Teleport, Forced Movement, Terrain, Zones, Summons, Resource Cost, AI hints | **Primary** — this is where spells/abilities live |
| **Features** | Passive stat bonuses, class resources, spell slots, feats, spellcasting ability | **Secondary** — resources and passive effects |
| **Equipment** | Weapons, armor, consumables with effects, passive bonuses | **Niche** — consumable items with spell-like effects |
| **Combat** | AC, HP, speeds, saves, resistances, immunities | **Base stats** only |
| **Abilities** | 6 ability scores | **Base stats** only |
| **Identity** | Name, race, class, size, creature type | **Metadata** only |
| **Token/AI** | Token visuals, AI profile | **AI behavior** only |

### Actions Tab — Complete Widget Inventory

The Actions Tab exposes these configurable fields per action:

**Header**: Name, Description, Target Type (9 options), Range (0-300 ft), Area Size (0-120 ft)
**Classification**: Spell Level (cantrip through 9th), Animation dropdown
**Attack Section** (collapsible): Attack Type (4 options), Ability (6), Reach, Range Normal/Long, 3 Damage Rows (dice + type + ability mod + bonus each)
**Save Section** (collapsible): Save Ability (6), DC (1-30), DC Ability (auto-calc), On Success (none/half/full), 2 Damage-on-Fail Rows, Conditions on Fail (list), Conditions on Success (list)
**Effects**: Healing (dice expr), Temp HP (dice expr), Uses/Rest, Rest Type, Concentration (checkbox)
**Zones**: Zone Follows Caster (checkbox), Zone Move Cost (action/bonus)
**Teleport**: Range, Self (checkbox), Passenger (checkbox), Origin Damage, Origin Type
**Forced Movement**: Type (push/pull/slide), Distance, Also Knock Prone
**Terrain**: Terrain Modification (10 terrain types)
**Summon**: Creature Path, Wild Shape (checkbox)
**Conditions**: Conditions Applied (list), Conditions Removed (list)
**Resource Cost**: 3 key-value rows (resource name + amount)
**AI**: Priority (1-10), Use Condition (expression)
**Legendary**: Action Cost (1-3, legendary category only)

### Per-Primitive UI Exposure

#### Section 1: Resource Cost
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| cost_type (spell slot) | ✅ | Spell Level dropdown → auto-generates `spell_slot_N` in resource_cost | ✅ EXPOSED |
| slot_level | ✅ | Spell Level dropdown (cantrip through 9th) | ✅ EXPOSED |
| material_component | ⚠️ | Generic Resource Cost rows (name + amount) — usable but not dedicated | ⚠️ WORKAROUND |
| ritual_casting | ❌ | No widget | ❌ NOT EXPOSED |
| component_consumed | ❌ | No widget | ❌ NOT EXPOSED |
| gold_value_check | ❌ | No widget | ❌ NOT EXPOSED |

#### Section 2: Casting Time / Duration
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| casting_time | ✅ | Action lives in category (Actions/Bonus Actions/Reactions) | ✅ EXPOSED |
| duration_type | ⚠️ | Concentration checkbox only. No explicit duration field (rounds, minutes) | ⚠️ PARTIAL |
| requires_concentration | ✅ | Checkbox | ✅ EXPOSED |

**Gap**: No "Duration" dropdown or spinner. Users cannot specify "lasts 1 minute" or "lasts 10 rounds". Concentration handles some cases, but non-concentration durations (e.g., Mage Armor lasting 8 hours) have no UI.

#### Section 3: Range / Targeting
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| range | ✅ | Number spinner (0-300, step 5) | ✅ EXPOSED |
| target_type | ✅ | 9-option dropdown (self through area_cylinder) | ✅ EXPOSED |
| area_shape | ✅ | Part of target_type dropdown | ✅ EXPOSED |
| area_size | ✅ | Number spinner (0-120, step 5) | ✅ EXPOSED |
| target_count | ❌ | No widget | ❌ NOT EXPOSED |
| line_of_sight | ❌ | No widget | ❌ NOT EXPOSED |

#### Section 4: Attack Roll
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| attack_type | ✅ | 4-option dropdown | ✅ EXPOSED |
| attack_ability | ✅ | 6-option dropdown | ✅ EXPOSED |
| reach | ✅ | Number spinner (0-30) | ✅ EXPOSED |
| range_normal | ✅ | Number spinner (0-600) | ✅ EXPOSED |
| range_long | ✅ | Number spinner (0-600) | ✅ EXPOSED |

#### Section 5: Saving Throw
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| save_ability | ✅ | 6-option dropdown | ✅ EXPOSED |
| save_dc | ✅ | Number spinner (1-30) | ✅ EXPOSED |
| dc_ability | ✅ | Auto-calc dropdown (8 + prof + ability mod) | ✅ EXPOSED |
| damage_on_success | ✅ | 3-option dropdown (none/half/full) | ✅ EXPOSED |
| damage_on_fail | ✅ | 2 damage rows (dice + type + mod + bonus) | ✅ EXPOSED |
| conditions_on_fail | ✅ | ListEditor (19 conditions) | ✅ EXPOSED |
| conditions_on_success | ✅ | ListEditor (19 conditions) | ✅ EXPOSED |

#### Section 6a: Damage
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| damage_dice | ✅ | Text input per row (3 attack rows, 2 save rows) | ✅ EXPOSED |
| damage_type | ✅ | 13-option dropdown per row | ✅ EXPOSED |
| ability_modifier | ✅ | Dropdown per row (6 abilities + none) | ✅ EXPOSED |
| flat_bonus | ✅ | Number spinner per row | ✅ EXPOSED |
| multi_damage_type | ✅ | Multiple damage rows per attack/save | ✅ EXPOSED |
| damage_on_miss | ✅ Engine | **No widget** — `Attack.damage_on_miss` field exists but is not in the UI | ❌ NOT EXPOSED |

**Gap**: `damage_on_miss` is an easy win — the engine supports it, just needs a damage row section in the UI.

#### Section 6b: Healing
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| healing_dice | ✅ | Text input (dice expression) | ✅ EXPOSED |
| grants_temporary_hp | ✅ | Text input (dice expression) | ✅ EXPOSED |

#### Section 6c: Conditions Applied/Removed
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| conditions_applied | ✅ | ListEditor — pick from 19 condition names | ✅ EXPOSED |
| conditions_removed | ✅ | ListEditor — pick from 19 condition names | ✅ EXPOSED |
| **condition_duration** | ⚠️ Engine | **No widget** | ❌ NOT EXPOSED |
| **save_to_end** | ⚠️ Engine | **No widget** | ❌ NOT EXPOSED |
| **condition_extra_data** | ⚠️ Engine | **No widget** | ❌ NOT EXPOSED |

**MAJOR GAP**: The `AppliedCondition` model supports `duration_type` (indefinite/rounds/end_of_turn/start_of_turn), `duration_rounds`, `save_to_end` (ability), `save_dc`, and `extra_data` (e.g., `{"frightened_of": "Dragon"}`). But the Actions Tab only lets users pick condition NAMES. Users cannot configure:
- How long a condition lasts
- What save ends it (for recurring saves at end of turn)
- Extra data like the source of Frightened

This means **every spell that applies a condition with a duration** (Hold Person, Fear, Blindness/Deafness, Banishment, etc.) cannot be fully configured. The condition will apply but with incorrect default duration behavior.

#### Section 6d: Buff/Debuff — **(Updated v0.15.0)**
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| buff_effects (stat, modifier_type, value, scope) | ✅ Engine (v0.15.0) | No dedicated widget yet | ❌ NOT EXPOSED |
| buff_duration_rounds | ✅ Engine (v0.15.0) | No widget | ❌ NOT EXPOSED |
| target_grants_to_attacker | ✅ Engine (v0.15.0) | No widget | ❌ NOT EXPOSED |

Engine fully supports buff/debuff system (v0.15.0). UI widgets needed: buff effect editor (stat dropdown, modifier type dropdown, value input, scope input, target_grants_to_attacker checkbox) + buff duration spinner. Unlocks: Shield, Bless, Bane, Haste, Slow, Faerie Fire, Absorb Elements, etc.

#### Section 7: Recurring Actions / On-Hit Riders
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| zone_follows_caster | ✅ | Checkbox | ✅ EXPOSED |
| zone_move_cost | ✅ | Dropdown (none/action/bonus_action) | ✅ EXPOSED |
| on_hit_rider | ✅ Engine (v0.14.0) | Rider editor in Features Tab (trigger, resource, damage, save, condition, melee/weapon checkboxes) | ✅ EXPOSED |
| recurring_action | ❌ Engine | No widget | ❌ NOT EXPOSED |

#### Section 8: Upcast / Cantrip Scaling
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| spell_level | ✅ Engine (v0.16.0) | No widget | ❌ NOT EXPOSED |
| upcast_damage_dice | ✅ Engine (v0.16.0) | No widget | ❌ NOT EXPOSED |
| upcast_healing_dice | ✅ Engine (v0.16.0) | No widget | ❌ NOT EXPOSED |
| upcast_damage_per_levels | ✅ Engine (v0.16.0) | No widget | ❌ NOT EXPOSED |
| cantrip scaling | ❌ Engine | No widget | ❌ NOT EXPOSED |
| upcast_target_count | ❌ Engine | No widget | ❌ NOT EXPOSED |
| upcast_duration | ❌ Engine | No widget | ❌ NOT EXPOSED |
| upcast_effect_threshold | ❌ Engine | No widget | ❌ NOT EXPOSED |

#### Section 9: Summon / Transform
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| summon_creature | ✅ | Text input (creature JSON path) | ✅ EXPOSED |
| is_wild_shape | ✅ | Checkbox | ✅ EXPOSED |

#### Section 10: Forced Movement
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| forced_movement_type | ✅ | 4-option dropdown | ✅ EXPOSED |
| forced_movement_distance | ✅ | Number spinner (0-60 ft) | ✅ EXPOSED |
| forced_movement_prone | ✅ | Checkbox | ✅ EXPOSED |

#### Bonus: Teleportation (not in original primitives)
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| teleport_range | ✅ | Number spinner (0-500) | ✅ EXPOSED |
| teleport_self | ✅ | Checkbox | ✅ EXPOSED |
| teleport_passenger | ✅ | Checkbox | ✅ EXPOSED |
| teleport_origin_effect | ✅ | Text input (dice expr) | ✅ EXPOSED |
| teleport_origin_damage_type | ✅ | Dropdown (13 types + none) | ✅ EXPOSED |

#### Bonus: Terrain Modification
| Primitive | Engine | UI Widget | Status |
|-----------|--------|-----------|--------|
| terrain_modification | ✅ | 10-option dropdown | ✅ EXPOSED |

### Phase 2 Scorecard (Levels 1-5) — Updated v0.16.0

| Status | Count | Notes |
|--------|-------|-------|
| ✅ Engine Supported + UI Exposed | **36** | The vast majority of what the engine can do IS exposed (on_hit_rider added v0.14.0) |
| ⚠️ Engine Supported, UI Workaround | **2** | material_component (generic resources), duration (concentration only) |
| ❌ Engine Supported, UI NOT Exposed | **11** | damage_on_miss, condition_duration, save_to_end, condition_extra_data, buff_effects, buff_duration_rounds, target_grants_to_attacker (v0.15.0), **spell_level, upcast_damage_dice, upcast_healing_dice, upcast_damage_per_levels** (added v0.16.0) |
| ❌ Engine NOT Supported + No UI | **42** | Cantrip scaling, upcast targets/duration/thresholds, multi-target, recurring actions, etc. (riders resolved v0.14.0, buffs resolved v0.15.0, upcast dice resolved v0.16.0) |

### KEY PHASE 2 FINDING

**The UI is remarkably well-aligned with the engine.** Of the 56 engine-supported primitives (48 original + on_hit_rider v0.14.0 + 7 buff/debuff v0.15.0), 36 are fully exposed and 2 have workarounds. **7 primitives** fall into the "engine can do it but UI doesn't expose it" category — the biggest groups being **condition duration parameters** and **buff/debuff configuration** (which needs a buff effect editor in the Actions tab).

### Actionable Easy Wins (UI-Only Changes)

1. **Condition Duration Widget** (HIGH PRIORITY): When a user adds a condition (via conditions_applied, conditions_on_fail, or conditions_on_success), they should be able to set: duration_type dropdown (indefinite/rounds/end_of_turn/start_of_turn), duration_rounds spinner, save_to_end ability dropdown, save_dc spinner. This would make Hold Person, Blindness/Deafness, Fear, Banishment, and dozens of other condition-applying spells fully configurable.

2. **Damage on Miss Row** (LOW PRIORITY): Add a collapsible damage row section for `Attack.damage_on_miss`. Rare but exists on some monster abilities and features.

3. **Spell Duration Field** (MEDIUM PRIORITY): Add a "Duration" section with type dropdown (instantaneous/rounds/minutes/hours/concentration) and a value spinner. While concentration is handled, non-concentration durations (Mage Armor, Aid, etc.) have no UI representation.
