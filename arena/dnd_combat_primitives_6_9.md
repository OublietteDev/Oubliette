# D&D 5e Combat Spell & Ability Grammar — Levels 6–9

Continuation of the primitives document. This covers 6th through 9th level spells from the PHB, focusing on combat-relevant spells and flagging new primitives as they emerge.

---

## 6th Level Spells

**Sunbeam**
```
cost_type: spell_slot | slot_level: 6
action_type: action
range_type: self
aoe_shape: line | aoe_size_primary: 60 | aoe_size_secondary: 5
aoe_anchor: caster_origin
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: CON
save_success_effect: half_damage_no_condition
damage_dice: 6d8 | damage_type: radiant
condition: blinded (until start of caster's next turn, on failed save)
recurring_action: can use action on subsequent turns to fire beam again
creature_type_bonus: undead and oozes have disadvantage on save
light_emission: bright 30ft, dim 30ft additional
dispel_effect: dispels magical darkness in area
```

**Chain Lightning**
```
cost_type: spell_slot | slot_level: 6
action_type: action
range_type: ranged | range_distance: 150
target_type: single_creature (primary)
resolution_type: saving_throw | save_ability: DEX
save_success_effect: half_damage
damage_dice: 10d8 | damage_type: lightning
chain_effect: arcs to up to 3 additional targets within 30ft of primary
    each secondary target also saves for half
upcast: +1 secondary target per slot level above 6th
NOTE: "chain_effect" — new primitive for bouncing/chaining between targets
```

**Disintegrate**
```
cost_type: spell_slot | slot_level: 6
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature or object or magical creation (up to 10ft cube)
resolution_type: saving_throw | save_ability: DEX
save_success_effect: no_effect (all or nothing)
damage_dice: 10d6+40 | damage_type: force
death_effect: "if reduced to 0 HP, target is disintegrated (turned to dust)"
object_interaction: disintegrates up to 10ft cube of nonmagical object
spell_interaction: instantly destroys Wall of Force, Forcecage (single wall), prismatic wall (one layer)
upcast: +3d6 per slot level above 6th
NOTE: "death_effect" — new primitive for what happens when target hits 0 HP from this spell
NOTE: the "no body left" aspect matters for resurrection mechanics
```

**Heal**
```
cost_type: spell_slot | slot_level: 6
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
resolution_type: automatic
heal_type: hit_points | heal_value: 70 (flat, no dice)
condition_removal: ends blindness, deafness, and any diseases
upcast: +10 HP per slot level above 6th
NOTE: "condition_removal" — new primitive for spells that remove existing conditions
```

**Harm**
```
cost_type: spell_slot | slot_level: 6
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
resolution_type: saving_throw | save_ability: CON
save_success_effect: half_damage
damage_dice: 14d6 | damage_type: necrotic
hp_floor: "can't reduce below 1 HP"
target_restriction: "not undead or construct"
NOTE: "hp_floor" — new primitive, target HP can't go below a threshold
```

**Blade Barrier**
```
cost_type: spell_slot | slot_level: 6
action_type: action
range_type: ranged | range_distance: 90
aoe_shape: wall | aoe_size_primary: 100 (length) | aoe_size_secondary: 20 (height), 5ft thick
    OR: ring, 60ft diameter, 20ft high, 5ft thick
duration_type: timed | duration_value: 10 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: DEX
save_success_effect: half_damage
damage_dice: 6d10 | damage_type: slashing
trigger_timing: on_first_enter_area_per_turn + on_start_turn_in_area
cover_interaction: provides three-quarters cover
```

**Eyebite**
```
cost_type: spell_slot | slot_level: 6
action_type: action
range_type: self (targets creature within 60ft you can see)
target_type: single_creature
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: WIS
save_success_effect: no_effect
effect_choice: caster picks one each turn:
  - Asleep: unconscious (ends if damaged or action to wake)
  - Panicked: frightened, must Dash away
  - Sickened: disadvantage on attacks and ability checks
recurring_action: can use action on subsequent turns to target a new creature
NOTE: "effect_choice" — caster picks from a menu of effects each time they use the action
      This extends `condition_choice` to a multi-option selection with different sub-effects
```

**Globe of Invulnerability**
```
cost_type: spell_slot | slot_level: 6
action_type: action
range_type: self
aoe_shape: sphere | aoe_size_primary: 10
aoe_anchor: caster_centered | aoe_moves_with_caster: false (stationary)
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: automatic
spell_immunity_threshold: spells of 5th level or lower can't affect anything inside
upcast: threshold increases by 1 per slot level above 6th
NOTE: "spell_immunity_threshold" — new primitive for blocking spells below a certain level
```

**Otto's Irresistible Dance**
```
cost_type: spell_slot | slot_level: 6
action_type: action
range_type: ranged | range_distance: 30
target_type: single_creature
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: automatic (no initial save!)
speed_modification: zero (must use movement to dance)
condition_custom: "disadvantage on attacks and DEX saves, attacks against it have advantage"
save_frequency: each_turn_end | save_ability: WIS | save_ends_effect: true
NOTE: no initial save makes this extremely powerful — the "no_initial_save" flag is important
```

**Circle of Death**
```
cost_type: spell_slot | slot_level: 6
action_type: action
range_type: ranged | range_distance: 150
aoe_shape: sphere | aoe_size_primary: 60
aoe_anchor: point_in_range
resolution_type: saving_throw | save_ability: CON
save_success_effect: half_damage
damage_dice: 8d6 | damage_type: necrotic
upcast: +2d6 per slot level above 6th
```

**Mental Prison**
```
cost_type: spell_slot | slot_level: 6
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
target_restriction: "creature with INT 4+"
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: INT
save_success_effect: no_effect
damage_dice: 5d10 | damage_type: psychic (on failed save, immediate)
condition: restrained (perceives illusory danger around it)
exit_damage: 10d10 psychic if target moves or is moved out of the space
save_frequency: none (one save only; effect ends if target is moved/takes exit damage)
NOTE: "exit_damage" — damage triggered by leaving a specific space. Related to but distinct from AoE entry damage.
```

**Tasha's Otherworldly Guise**
```
cost_type: spell_slot | slot_level: 6
action_type: bonus_action
range_type: self
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: automatic
effect_choice: Lower Planes OR Upper Planes
  Lower Planes:
    immunity: fire, poison
    condition_immunity: poisoned
  Upper Planes:
    immunity: radiant, necrotic
    condition_immunity: charmed
  Both grant:
    stat_target: AC | stat_modification_type: flat_bonus | stat_modification_value: +2
    grants_movement: flying | movement_speed: 40
    extra_attack_compatible: true (if you don't already have Extra Attack, you get it)
    weapon_enhancement: attacks count as magical, use spellcasting mod for attack/damage
NOTE: "weapon_enhancement" — modifies weapon properties (magical, stat override)
NOTE: "conditional_extra_attack" — grants Extra Attack only if you don't have it
```

**Mass Suggestion**
```
cost_type: spell_slot | slot_level: 6
action_type: action
range_type: ranged | range_distance: 60
target_type: multiple_creatures | target_count: 12
duration_type: timed | duration_value: 24 | duration_unit: hour
concentration: false
resolution_type: saving_throw | save_ability: WIS
save_success_effect: no_effect
condition: charmed (follows a "reasonable" suggestion)
target_restriction: "can hear and understand you"
upcast: duration increases (7th→10 days, 8th→30 days, 9th→1 year and 1 day)
NOTE: "suggestion" is narrative — your app may need to just flag this as
      "charmed: follows caster's stated course of action"
```

---

## 7th Level Spells

**Fire Storm**
```
cost_type: spell_slot | slot_level: 7
action_type: action
range_type: ranged | range_distance: 150
aoe_shape: cube | aoe_size_primary: 10 (each cube)
aoe_count: 10 (ten 10ft cubes, each adjacent to at least one other)
resolution_type: saving_throw | save_ability: DEX
save_success_effect: half_damage
damage_dice: 7d10 | damage_type: fire
selective_targeting: caster designates which creatures in area are unaffected
object_interaction: ignites flammable objects not worn/carried (caster can choose to not ignite)
NOTE: "aoe_count" — new primitive for spells that create multiple discrete AoE zones
      that must be arranged contiguously
```

**Finger of Death**
```
cost_type: spell_slot | slot_level: 7
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
resolution_type: saving_throw | save_ability: CON
save_success_effect: half_damage
damage_dice: 7d8+30 | damage_type: necrotic
death_effect: "humanoid killed by this rises as zombie permanently under caster's control"
NOTE: extends "death_effect" — creates a permanent minion on kill
```

**Reverse Gravity**
```
cost_type: spell_slot | slot_level: 7
action_type: action
range_type: ranged | range_distance: 100
aoe_shape: cylinder | aoe_size_primary: 50 | aoe_size_secondary: 100
aoe_anchor: point_in_range
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: DEX (to grab onto something)
save_success_effect: no falling (holds on)
forced_movement_type: lift | forced_movement_distance: up to top of area
fall_damage: if hits ceiling → 1d6 bludgeoning per 10ft fallen (upward)
trigger_timing: on_cast (initial fall) + on_spell_end (fall back down)
NOTE: "gravity_reversal" — unique spatial mechanic. Fall damage on cast AND on end.
      Creatures that grab on are essentially restrained hanging.
```

**Crown of Stars**
```
cost_type: spell_slot | slot_level: 7
action_type: action
range_type: self
duration_type: timed | duration_value: 1 | duration_unit: hour
concentration: false
light_emission: dim 30ft
effect: creates 7 star motes orbiting your head
recurring_action: bonus_action to hurl one mote
  range: 120ft | resolution: spell_attack_ranged | damage: 4d12 radiant
limited_uses: 7 (one per mote)
end_condition: all motes used or duration expires
upcast: +2 motes per slot level above 7th
NOTE: "limited_uses" on recurring action — expendable charges on a buff spell
```

**Forcecage**
```
cost_type: spell_slot | slot_level: 7
action_type: action
range_type: ranged | range_distance: 100
duration_type: timed | duration_value: 1 | duration_unit: hour
concentration: false
component_material: "ruby dust worth 1500gp" (consumed)
effect_choice:
  - Cage: 20ft cube, bars 1/2 inch apart (small creatures can slip through)
  - Box: 10ft cube, solid walls of force (blocks everything including spells)
resolution_type: automatic (no save to avoid)
escape_mechanic: CHA save vs spell DC to teleport out; on fail, teleport wasted
spell_interaction: not affected by Dispel Magic; Disintegrate destroys one wall
indestructible: true (immune to damage)
NOTE: this is one of the most powerful control spells in 5e
```

**Prismatic Spray**
```
cost_type: spell_slot | slot_level: 7
action_type: action
range_type: self
aoe_shape: cone | aoe_size_primary: 60
aoe_anchor: caster_origin
resolution_type: varies per color (see below)
effect: each target rolls d8 for random color:
  1-Red: 10d6 fire, DEX save half
  2-Orange: 10d6 acid, DEX save half
  3-Yellow: 10d6 lightning, DEX save half
  4-Green: 10d6 poison, CON save half
  5-Blue: 10d6 cold, DEX save half
  6-Indigo: CON save or restrained → next turn save or petrified (permanent until freed)
  7-Violet: WIS save or blinded → next turn save or transported to another plane
  8-Special: struck by two colors (roll twice, rerolling 8s)
NOTE: "random_effect_table" — new primitive. Effect determined by random roll.
      This is rare in 5e but critical for Prismatic spells and Wild Magic.
      The Indigo/Violet effects also introduce "progressive_condition" — fail now,
      worse on next turn.
```

**Whirlwind**
```
cost_type: spell_slot | slot_level: 7
action_type: action
range_type: ranged | range_distance: 300
aoe_shape: cylinder | aoe_size_primary: 10 | aoe_size_secondary: 30
aoe_anchor: point_in_range
aoe_moveable: true | aoe_move_action_cost: action | aoe_move_distance: 30
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: DEX
save_success_effect: half_damage
damage_dice: 10d6 | damage_type: bludgeoning
trigger_timing: on_first_enter_area_per_turn + on_cast (creatures already in area)
forced_movement_on_fail: lifted, restrained, suspended in whirlwind
  takes damage again at start of each turn
  DEX save at end of each turn to be hurled out (fall damage 1d6/10ft)
NOTE: combines AoE, forced movement (lift), restrained, recurring damage,
      and ejection mechanic. Complex but decomposable with existing primitives.
```

**Teleport** *(limited combat use but including for completeness)*
```
cost_type: spell_slot | slot_level: 7
action_type: action
range_type: ranged | range_distance: 10
target_type: multiple_creatures | target_count: 8 (willing + caster)
target_restriction: willing
duration_type: instantaneous
forced_movement_type: teleport_caster + teleport_target
forced_movement_distance: unlimited (same plane)
NOTE: familiarity-based accuracy table — mostly narrative/exploration,
      but could matter for combat if teleporting to escape or reposition.
      Probably "special" handling.
```

**Plane Shift** *(combat relevant as a save-or-banish)*
```
cost_type: spell_slot | slot_level: 7
action_type: action
range_type: touch
target_type: single_creature (willing) OR unwilling
resolution_type: spell_attack_melee (unwilling) then saving_throw | save_ability: CHA
save_success_effect: no_effect
effect: target sent to another plane
component_material: "forked metal rod attuned to target plane" (not consumed)
NOTE: effectively "save or die" against unwilling targets in combat.
      Uses both attack roll AND save — rare "double resolution" mechanic.
```

**Power Word Pain**
```
cost_type: spell_slot | slot_level: 7
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
resolution_type: automatic (no save!)
hp_threshold_branch: only works if target has 100 HP or fewer
condition_custom: "disadvantage on attacks, ability checks, saves (except CON);
    speed max 10ft; if tries to cast spell, CON save DC 19 or spell wasted"
save_frequency: each_turn_end | save_ability: CON | save_ends_effect: true
NOTE: Power Word spells use "hp_threshold_no_save" — auto-hit if under HP threshold
```

---

## 8th Level Spells

**Sunburst**
```
cost_type: spell_slot | slot_level: 8
action_type: action
range_type: ranged | range_distance: 150
aoe_shape: sphere | aoe_size_primary: 60
aoe_anchor: point_in_range
resolution_type: saving_throw | save_ability: CON
save_success_effect: half_damage_no_condition
damage_dice: 12d6 | damage_type: radiant
condition: blinded (for 1 minute on failed save)
save_frequency: each_turn_end (CON save to end blindness)
dispel_effect: dispels magical darkness in area
creature_type_bonus: undead and oozes have disadvantage on save
```

**Earthquake**
```
cost_type: spell_slot | slot_level: 8
action_type: action
range_type: ranged | range_distance: 500
aoe_shape: sphere | aoe_size_primary: 100
aoe_anchor: point_in_range (on ground)
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
difficult_terrain: true (area becomes difficult terrain)
trigger_timing: on_cast + on_start_of_caster_turn (concentration check-like mechanic for creatures)
resolution_type: saving_throw | save_ability: DEX (to avoid being knocked prone)
condition: prone (on failed save each round)
effect_branches:
  - Fissures: 1d6 fissures open, DEX save or fall in (10d6 bludgeoning at bottom)
  - Structures: 100 damage to structures each round, collapse if HP reaches 0
    collapse: 5d6 bludgeoning, DEX save half, buried (escape DC 20 Athletics)
NOTE: extremely complex — multiple simultaneous effects (difficult terrain + prone check
      each round + fissures + structure damage). Needs "multi_effect_simultaneous" or
      just multiple entries in the effect array.
```

**Abi-Dalzim's Horrid Wilting**
```
cost_type: spell_slot | slot_level: 8
action_type: action
range_type: ranged | range_distance: 150
aoe_shape: cube | aoe_size_primary: 30
aoe_anchor: point_in_range
resolution_type: saving_throw | save_ability: CON
save_success_effect: half_damage
damage_dice: 12d8 | damage_type: necrotic
target_restriction: "not undead or constructs (auto-unaffected)"
creature_type_bonus: plant creatures and water elementals have disadvantage on save
object_interaction: nonmagical plants wither and die
```

**Holy Aura**
```
cost_type: spell_slot | slot_level: 8
action_type: action
range_type: self
aoe_shape: sphere | aoe_size_primary: 30
aoe_anchor: caster_centered | aoe_moves_with_caster: true
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: automatic
component_material: "tiny reliquary worth 1000gp" (not consumed)
buff_effects (to all friendly creatures in aura):
  stat_target: saving_throws | stat_modification_type: advantage
  stat_target: AC (dim light aura, others have disadvantage on attacks against)
  condition_custom: "attacks against aura creatures have disadvantage"
reactive_effect: "if fiend or undead hits aura creature with melee attack,
    attacker must make CON save or be blinded until end of spell"
NOTE: "reactive_damage_or_effect" — new primitive for effects that trigger
      when the buffed creature is attacked/hit
```

**Feeblemind**
```
cost_type: spell_slot | slot_level: 8
action_type: action
range_type: ranged | range_distance: 150
target_type: single_creature
resolution_type: saving_throw | save_ability: INT
save_success_effect: no_effect
damage_dice: 4d6 | damage_type: psychic
stat_target: INT | stat_modification_type: set_value | stat_modification_value: 1
stat_target: CHA | stat_modification_type: set_value | stat_modification_value: 1
condition_custom: "can't cast spells, use magic items, understand language, or communicate"
duration_type: until_dispelled
save_frequency: every_30_days | save_ability: INT | save_ends_effect: true
    (save DC is hard because INT is now 1 → modifier of -5)
NOTE: the "set ability score to specific value" is already in our primitives.
      The "save every 30 days" is a new duration for save_frequency.
```

**Dominate Monster**
```
cost_type: spell_slot | slot_level: 8
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
duration_type: timed | duration_value: 1 | duration_unit: hour | concentration: true
resolution_type: saving_throw | save_ability: WIS
save_success_effect: no_effect
condition: charmed
control_mechanic: caster has telepathic link, can command creature's actions
save_frequency: on_taking_damage (re-save with advantage when taking damage)
upcast: duration increases (9th → 8 hours)
NOTE: "control_mechanic" — full creature control, not just a condition.
      For your app, this might mean the controlling player can direct
      the dominated creature's token on their turn.
```

**Incendiary Cloud**
```
cost_type: spell_slot | slot_level: 8
action_type: action
range_type: ranged | range_distance: 150
aoe_shape: sphere | aoe_size_primary: 20
aoe_anchor: point_in_range
aoe_moveable: true | aoe_move_action_cost: free (moves 10ft away from caster at start of each turn)
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: DEX
save_success_effect: half_damage
damage_dice: 10d8 | damage_type: fire
trigger_timing: on_first_enter_area_per_turn + on_start_turn_in_area
heavily_obscured: true (area is heavily obscured)
NOTE: "auto_move" — new primitive. The effect moves automatically each round
      without requiring caster action. Direction: away from caster.
```

**Maze**
```
cost_type: spell_slot | slot_level: 8
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
duration_type: timed | duration_value: 10 | duration_unit: minute | concentration: true
resolution_type: automatic (no save!)
effect: target is banished to extradimensional maze
escape_mechanic: DC 20 INT check as action each turn to escape
NOTE: no save, no HP threshold — just automatic banishment.
      The "ability check to escape" is a variant of save_frequency.
      Could model as: resolution_type: automatic,
      escape: { check_ability: INT, DC: 20, action_cost: action }
```

**Power Word Stun**
```
cost_type: spell_slot | slot_level: 8
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
resolution_type: automatic (no save!)
hp_threshold_branch: only works if target has 150 HP or fewer
condition: stunned
save_frequency: each_turn_end | save_ability: CON | save_ends_effect: true
```

**Tsunami**
```
cost_type: spell_slot | slot_level: 8
action_type: 1 minute
range_type: sight
aoe_shape: wall | aoe_size_primary: 300 (length) | aoe_size_secondary: 300 (height), 50ft thick
aoe_anchor: point_in_range
aoe_moveable: true | auto_move: 50ft toward caster's chosen direction each round
duration_type: timed | duration_value: 6 | duration_unit: round | concentration: true
resolution_type: saving_throw | save_ability: STR
save_success_effect: half_damage
damage_dice: 6d10 | damage_type: bludgeoning (decreases by 1d10 each round)
trigger_timing: on_first_enter_area_per_turn + on_start_turn_in_area
forced_movement: carried along with the wave on fail
scaling_over_time: damage decreases each round (6d10 → 5d10 → 4d10... → 1d10)
NOTE: "scaling_over_time" — new primitive. Effect changes (weakens/strengthens)
      over the spell's duration. Also "auto_move" with specific direction.
```

---

## 9th Level Spells

**Meteor Swarm**
```
cost_type: spell_slot | slot_level: 9
action_type: action
range_type: ranged | range_distance: 1 mile
aoe_shape: sphere | aoe_size_primary: 40
aoe_count: 4 (four spheres, can overlap)
aoe_anchor: point_in_range
resolution_type: saving_throw | save_ability: DEX
save_success_effect: half_damage
damage_dice: 20d6 fire + 20d6 bludgeoning
overlap_rule: creature in multiple spheres saves once, takes damage once
object_interaction: ignites flammable objects not worn/carried
NOTE: "overlap_rule" — new primitive. When multiple AoEs overlap,
      what happens? (Most common: save once, damage once)
```

**Power Word Kill**
```
cost_type: spell_slot | slot_level: 9
action_type: action
range_type: ranged | range_distance: 60
target_type: single_creature
resolution_type: automatic (no save!)
hp_threshold_branch: only works if target has 100 HP or fewer
death_effect: target dies instantly (no damage, just death)
NOTE: the ultimate "hp_threshold_no_save" — instant death, no roll.
```

**Power Word Heal**
```
cost_type: spell_slot | slot_level: 9
action_type: action
range_type: touch
target_type: single_creature
resolution_type: automatic
heal_type: hit_points | heal_value: all (restore to full HP)
condition_removal: ends charmed, frightened, paralyzed, stunned
forced_movement_type: stand (creature can use reaction to stand up)
NOTE: "heal_to_full" — new primitive (or just set heal_value to a very high number/flag)
```

**True Polymorph**
```
cost_type: spell_slot | slot_level: 9
action_type: action
range_type: ranged | range_distance: 30
target_type: single_creature or nonmagical object
duration_type: timed | duration_value: 1 | duration_unit: hour | concentration: true
resolution_type: saving_throw | save_ability: WIS (unwilling creatures)
save_success_effect: no_effect
effect_choice:
  - Creature → Creature: new form CR <= target level/CR
  - Creature → Object: target becomes nonmagical object
  - Object → Creature: object becomes creature CR <= object size equivalent
summon_stat_block: linked character sheet (your swap solution)
permanence: "if concentration maintained for full duration, effect is permanent until dispelled"
excess_damage_carryover: true (if reduced to 0 HP, reverts)
NOTE: "permanence" — new primitive. Effect becomes permanent if concentration is maintained
      for the full duration. Distinct from "until_dispelled" because it starts as concentration.
```

**Prismatic Wall**
```
cost_type: spell_slot | slot_level: 9
action_type: action
range_type: ranged | range_distance: 60
aoe_shape: wall | aoe_size_primary: 90 | aoe_size_secondary: 30, 1ft thick
    OR: sphere 30ft radius (caster inside)
duration_type: timed | duration_value: 10 | duration_unit: minute
concentration: false
resolution_type: varies by layer (see below)
layers: 7 layers, each with different effect:
  Red: 10d6 fire, DEX save half. Destroyed by cold damage.
  Orange: 10d6 acid, DEX save half. Destroyed by strong wind.
  Yellow: 10d6 lightning, DEX save half. Destroyed by force damage.
  Green: 10d6 poison, CON save half. Destroyed by daylight.
  Blue: 10d6 cold, DEX save half. Destroyed by dispel magic.
  Indigo: CON save or restrained → next turn STR save or petrified. Destroyed by daylight.
  Violet: WIS save or blinded → next turn WIS save or transported to plane. Dispel magic.
trigger_timing: on_enter + on_start_turn_adjacent (within 20ft: blinded for 1 minute, CON save)
layer_destruction: each layer can be destroyed by a specific counter
NOTE: "layered_effect" — new primitive. Effect has multiple layers that are
      independently destroyable. Very rare — basically only Prismatic Wall/Sphere.
```

**Psychic Scream**
```
cost_type: spell_slot | slot_level: 9
action_type: action
range_type: ranged | range_distance: 90
target_type: multiple_creatures | target_count: 10
target_restriction: "creatures with INT 2+"
resolution_type: saving_throw | save_ability: INT
save_success_effect: half_damage_no_condition
damage_dice: 14d6 | damage_type: psychic
condition: stunned (for 1 minute on failed save)
save_frequency: each_turn_end | save_ability: INT | save_ends_effect: true
death_effect: "if killed by this spell, target's head explodes"
NOTE: the head explosion is mostly flavor but prevents certain resurrection methods
```

**Blade of Disaster**
```
cost_type: spell_slot | slot_level: 9
action_type: bonus_action
range_type: ranged | range_distance: 60
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
summon_type: object (planar rift blade)
recurring_action: bonus_action to move 30ft + make 2 melee spell attacks
  resolution_type: spell_attack_melee | range: 5ft from blade
  damage_dice: 4d12 | damage_type: force
  crit_range: 18-20 (crits on 18, 19, or 20)
  crit_damage: 12d12 force (instead of normal crit calculation)
NOTE: "crit_range" — new primitive. Modified critical hit threshold.
      "crit_override" — custom crit damage instead of doubling dice.
```

**Weird**
```
cost_type: spell_slot | slot_level: 9
action_type: action
range_type: ranged | range_distance: 120
target_type: multiple_creatures (any number in range you can see)
duration_type: timed | duration_value: 1 | duration_unit: minute | concentration: true
resolution_type: saving_throw | save_ability: WIS
save_success_effect: no_effect
condition: frightened
damage_dice: 4d10 | damage_type: psychic (at start of each of target's turns)
trigger_timing: on_start_of_target_turn (damage)
save_frequency: each_turn_end | save_ends_effect: true
```

**Shapechange**
```
cost_type: spell_slot | slot_level: 9
action_type: action
range_type: self
duration_type: timed | duration_value: 1 | duration_unit: hour | concentration: true
component_material: "jade circlet worth 1500gp" (not consumed)
summon_stat_block: any creature CR <= your level that you've seen (linked character sheet!)
retain_features: "keep your INT, WIS, CHA; keep class features, proficiencies"
action_to_change: can use action to change form again mid-spell
excess_damage_carryover: false (unlike Polymorph — you just revert if you hit 0)
NOTE: more flexible than Polymorph — retain mental stats and class features.
      Your stat block swap solution works, but may need a "retain_stats" flag
      that keeps certain stats from the original sheet.
```

**Foresight**
```
cost_type: spell_slot | slot_level: 9
action_type: 1 minute
range_type: touch
target_type: willing_creature
duration_type: timed | duration_value: 8 | duration_unit: hour
concentration: false
resolution_type: automatic
buff_effects:
  stat_target: attack_rolls | stat_modification_type: advantage
  stat_target: ability_checks | stat_modification_type: advantage
  stat_target: saving_throws | stat_modification_type: advantage
  condition_custom: "can't be surprised, attacks against target have disadvantage"
```

**Invulnerability**
```
cost_type: spell_slot | slot_level: 9
action_type: action
range_type: self
duration_type: timed | duration_value: 10 | duration_unit: minute | concentration: true
component_material: "adamantine worth 500gp" (consumed)
resolution_type: automatic
damage_immunity: all damage types
NOTE: "damage_immunity: all" — immune to all damage for duration.
      Simple primitive but extremely powerful.
```

**Mass Heal**
```
cost_type: spell_slot | slot_level: 9
action_type: action
range_type: ranged | range_distance: 60
target_type: multiple_creatures (any number within range)
resolution_type: automatic
heal_type: hit_points | heal_value: 700 (distributed as caster chooses)
condition_removal: ends blindness, deafness, and any diseases on healed creatures
NOTE: "distributable_healing" — new primitive. A pool of HP distributed by caster choice.
      Similar concept to Sleep's HP pool but for healing.
```

---

## ALL NEW PRIMITIVES FROM LEVELS 6–9

| Primitive | Why Needed | Example Spell |
|---|---|---|
| `chain_effect` | Damage/effect bounces to additional nearby targets | Chain Lightning |
| `death_effect` | Special outcome when target is reduced to 0 HP by this spell | Disintegrate, Finger of Death, Power Word Kill |
| `condition_removal` | Spell removes existing conditions | Heal, Power Word Heal, Mass Heal |
| `hp_floor` | Damage can't reduce target below a threshold | Harm |
| `spell_immunity_threshold` | Blocks spells of a certain level or lower | Globe of Invulnerability |
| `effect_choice_menu` | Caster picks from multiple distinct effect options each use | Eyebite, Tasha's Otherworldly Guise |
| `reactive_effect` | Effect triggers when buffed creature is attacked/hit | Holy Aura |
| `weapon_enhancement` | Modifies weapon attack properties (magical, stat override) | Tasha's Otherworldly Guise |
| `conditional_extra_attack` | Grants Extra Attack if creature doesn't have it | Tasha's Otherworldly Guise |
| `escape_mechanic` | Ability check (not save) to escape an effect | Maze, Forcecage |
| `random_effect_table` | Effect determined by dice roll from a table | Prismatic Spray |
| `progressive_condition` | Condition worsens on subsequent failed saves | Prismatic Spray (Indigo/Violet) |
| `aoe_count` | Multiple discrete AoE zones that must be arranged together | Fire Storm, Meteor Swarm |
| `overlap_rule` | How overlapping AoE zones interact | Meteor Swarm |
| `auto_move` | Effect moves automatically without caster action | Incendiary Cloud, Tsunami |
| `scaling_over_time` | Effect changes (strengthens/weakens) over duration | Tsunami |
| `permanence` | Effect becomes permanent after maintaining concentration | True Polymorph |
| `layered_effect` | Multiple independent layers, each destroyable separately | Prismatic Wall |
| `crit_range` | Modified critical hit threshold (e.g., 18-20) | Blade of Disaster |
| `crit_override` | Custom critical hit damage instead of doubling dice | Blade of Disaster |
| `retain_stats` | Keep certain stats from original form during transformation | Shapechange |
| `distributable_healing` | HP pool distributed by caster choice among targets | Mass Heal |
| `damage_immunity_all` | Immune to all damage | Invulnerability |
| `heavily_obscured` | Area blocks vision entirely | Incendiary Cloud |
| `control_mechanic` | Full creature control (direct target's actions) | Dominate Monster |
| `exit_damage` | Damage triggered specifically by leaving a space | Mental Prison |
| `hp_threshold_no_save` | Auto-hit effect if target is below HP threshold | Power Word Kill/Stun/Pain |
| `no_initial_save` | Effect is automatic on cast; saves only to end it on later turns | Otto's Irresistible Dance, Maze |

---

## COMPLETE PRIMITIVE REGISTRY (CONSOLIDATED)

Combining both documents, here is the full master list of every primitive category:

### Core Primitives (Cover ~80% of spells)
1. Resource Cost (cost_type, slot_level, components, ritual)
2. Action Economy (action_type, reaction_trigger)
3. Range (range_type, range_distance)
4. Target Selection (target_type, target_count, target_restriction)
5. Area of Effect (aoe_shape, aoe_size, aoe_anchor, aoe_moves_with_caster)
6. Duration (duration_type, duration_value, concentration)
7. Resolution (spell_attack, saving_throw, automatic, contested_check)
8. Damage (dice, type, on_save)
9. Healing (dice, bonus, type)
10. Conditions (standard 5e conditions + custom conditions)
11. Forced Movement (push, pull, teleport, lift)
12. Speed Modification (halved, zero, bonus)
13. Stat Buffs/Debuffs (flat bonus, advantage/disadvantage, resistance/immunity)
14. Scaling (cantrip tiers, upcast per level)

### Extended Primitives (Cover ~15% more)
15. AoE Movement (aoe_moveable, move_action_cost, move_distance)
16. Recurring Action (use action/bonus on subsequent turns for effect)
17. Save Frequency (when targets re-save: turn start/end, on damage, etc.)
18. Damage Type Choice (caster picks element)
19. Condition Choice (caster picks condition)
20. Effect Triggers (on_cast, on_hit, on_enter, on_turn_start, etc.)
21. Selective Targeting (exclude allies/specific creatures from AoE)
22. Transfer on Death (move effect to new target when current dies)
23. Summon/Create (creatures, objects, barriers with linked stat blocks)
24. Wall Properties (length, height, thickness, HP per panel)
25. Difficult Terrain creation
26. Light Emission (bright/dim radius)
27. Object Interaction (ignite, destroy, etc.)
28. Cover Interaction (spreads around corners, ignores cover)

### Rare Primitives (Cover remaining ~5%)
29. HP Pool Mechanic (Sleep)
30. HP Threshold No Save (Power Word spells)
31. Death Effect (special outcome on kill)
32. Chain Effect (bouncing between targets)
33. Random Effect Table (Prismatic Spray)
34. Progressive Condition (worsens on subsequent fails)
35. Layered Effect (Prismatic Wall)
36. Multiple Discrete AoEs (Fire Storm, Meteor Swarm)
37. Overlap Rules (for multiple AoEs)
38. Auto Move (effect moves without action)
39. Scaling Over Time (effect changes during duration)
40. Permanence (concentration → permanent)
41. Escape Mechanic (ability check, not save)
42. Exit Damage (damage on leaving a space)
43. Reactive Effect (triggers when buffed creature is attacked)
44. Control Mechanic (full creature control)
45. Crit Range / Override (modified crit thresholds)
46. Condition Removal (removes existing conditions)
47. Distributable Pool (HP pool split among targets by choice)
48. Spell Immunity Threshold (blocks spells below X level)
49. Weapon Enhancement (magical, stat override for attacks)
50. Heavily Obscured (blocks vision in area)
51. No Initial Save (automatic on cast, save to end later)
52. End Penalty (negative effect when spell ends — Haste)
53. Grants Extra Action (Haste)
54. Retain Stats (keep certain stats during transformation)
55. Damage Immunity All (immune to everything)
56. Damage Per Distance Moved (Spike Growth)
57. Effect Choice Menu (pick from distinct effect options each use)

---

## NOTES FOR IMPLEMENTATION

### Priority Order for Building
1. **Build Core Primitives first** — these handle most spells players actually use frequently
2. **Extended Primitives next** — these unlock the "interesting" spells that make builds fun
3. **Rare Primitives last** — many of these only apply to 1-3 spells each; your playtesters will tell you which ones they actually need

### Spells That Probably Need Hardcoded Special Handling
Even with all 57 primitives, some spells may be easier to implement as special cases:
- **Wish** (skipping)
- **Prestidigitation / Thaumaturgy / Druidcraft** (skipping)
- **Contingency** (stores a spell with a conditional trigger — essentially "programming")
- **Glyph of Warding** (similar to Contingency)
- **Time Stop** (grants 1d4+1 consecutive turns — unique turn manipulation)
- **Simulacrum** (creates a half-HP duplicate — could work with your stat block swap?)
- **Antipathy/Sympathy** (30-day compulsion with very specific behavioral effects)

### Things Your Playtesters Will Definitely Ask About
- Smite spells (Thunderous Smite, Wrathful Smite, etc.) — these are "on next weapon hit" buffs (the on-hit rider engine exists as of v0.14.0, but applying riders via concentration buff spells still needs the buff/debuff system)
- Eldritch Invocations modifying Eldritch Blast (Agonizing Blast, Repelling Blast, etc.)
- Metamagic interactions (Twinned Spell doubling single-target spells, etc.)
- Monk Ki abilities (Stunning Strike, Flurry of Blows) — **Stunning Strike now buildable via on-hit rider system (v0.14.0)**
- Battlemaster Maneuvers (these decompose similarly to spells) — **many now buildable via on-hit rider system (v0.14.0)**
- Wildshape variations (Moon Druid combat forms)

These class features follow the same grammar — they're just not "spells" per se. As of v0.14.0, the generalized on-hit rider system (`Feature.on_hit_rider`) covers a large portion of these (see `dnd_class_features_primitives.md` for full coverage).

---

## AUDIT RESULTS (v0.13.1)

Audit performed against dnd_combat_sim v0.13.1. Focuses on **new primitives** introduced in levels 6-9 that were not already covered in the 1-5 audit. Primitives that repeat from the 1-5 document (e.g., recurring_action, buff/debuff, creature_type_bonus) are noted as "See 1-5 audit" rather than re-audited.

### Spell-by-Spell Buildability

How much of each spell can be constructed using the current Action model + combat engine?

#### 6th Level

| Spell | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Sunbeam | **PARTIAL** | Line AoE + CON save + radiant damage + blinded condition (first cast). | Recurring action (fire again on later turns), creature type bonus (undead disadvantage), dispel darkness, light emission. |
| Chain Lightning | **NOT BUILDABLE** | Single-target DEX save + lightning damage works. | Chain/bounce mechanic to secondary targets doesn't exist. |
| Disintegrate | **MOSTLY** | Single target + DEX save + force damage + "no_effect" on success. | Death effect (disintegrated on 0 HP), spell interaction (destroys Wall of Force). |
| Heal | **SUPPORTED** | Flat healing via `healing: "70"` + `conditions_removed: ["blinded", "deafened"]`. Works as-is. | Upcast scaling (+10 per level). |
| Harm | **MOSTLY** | Single target + CON save + necrotic damage. | HP floor ("can't reduce below 1"), target restriction (not undead/construct). |
| Blade Barrier | **PARTIAL** | Zone system could approximate: AoE damage + save + concentration. | Wall AoE shape, wall dimensions (100x20x5ft), cover interaction. |
| Eyebite | **NOT BUILDABLE** | Single target + WIS save + condition. | Recurring action (new target each turn), effect choice menu (asleep/panicked/sickened). |
| Globe of Invulnerability | **NOT BUILDABLE** | None. | Spell immunity threshold is entirely new. |
| Otto's Irresistible Dance | **PARTIAL** | Automatic (no save) + conditions. | Speed modification (zero), custom conditions (disadvantage on attacks/DEX saves, advantage for attackers), end-of-turn save to end. Condition *application* works but the mechanical effects of the custom condition don't. |
| Circle of Death | **SUPPORTED** | AoE sphere + CON save + half damage + necrotic. Fully buildable. | Upcast scaling only. |
| Mental Prison | **PARTIAL** | Single target + INT save + psychic damage + restrained. | Exit damage (10d10 on leaving space). |
| Tasha's Otherworldly Guise | **NOT BUILDABLE** | None meaningfully. | Buff system (AC bonus, flying, immunity, weapon enhancement, conditional Extra Attack). |
| Mass Suggestion | **PARTIAL** | Multi-target... no, needs `target_count: 12`. WIS save + charmed. | target_count, narrative "suggestion" effect. |

#### 7th Level

| Spell | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Fire Storm | **NOT BUILDABLE** | Standard save damage. | Multiple discrete AoE zones (`aoe_count: 10`), selective targeting. |
| Finger of Death | **MOSTLY** | Single target + CON save + necrotic damage. | Death effect (zombie creation on kill). |
| Reverse Gravity | **NOT BUILDABLE** | None meaningfully. | Lift forced movement, fall damage, gravity reversal. |
| Crown of Stars | **NOT BUILDABLE** | None. | Recurring bonus action, limited charges (7 motes), ranged spell attack from motes. |
| Forcecage | **NOT BUILDABLE** | None. | Indestructible barrier, escape mechanic (CHA save to teleport out), effect choice (cage vs box). |
| Prismatic Spray | **NOT BUILDABLE** | Cone AoE shape. | Random effect table (d8 per target), different save abilities per color, progressive conditions. |
| Whirlwind | **PARTIAL** | Moveable zone + save + bludgeoning damage. | Lift + restrained in zone, ejection mechanic, recurring damage while suspended. |
| Teleport | **PARTIAL** | Teleport system exists. | Multi-target teleport (8 creatures), unlimited range. |
| Plane Shift | **NOT BUILDABLE** | Melee spell attack exists. | Double resolution (attack roll THEN save), banishment to other plane. |
| Power Word Pain | **NOT BUILDABLE** | None. | HP threshold no-save, custom condition block (disadvantage on everything, speed 10ft, spell disruption). |

#### 8th Level

| Spell | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Sunburst | **MOSTLY** | AoE sphere + CON save + radiant damage + blinded. | Creature type bonus (undead/ooze disadvantage), dispel darkness. End-of-turn save to end blindness works via AppliedCondition. |
| Earthquake | **NOT BUILDABLE** | Difficult terrain creation works. | Recurring prone saves, fissures, structure damage, multi-effect simultaneous. |
| Abi-Dalzim's Horrid Wilting | **MOSTLY** | AoE cube + CON save + necrotic damage. | Creature type bonus (plant/water elemental disadvantage), target restriction. |
| Holy Aura | **NOT BUILDABLE** | None meaningfully. | Buff system (advantage on saves, disadvantage on attacks against), reactive effect (blind attacker). |
| Feeblemind | **PARTIAL** | INT save + psychic damage. | Set ability score to value (INT=1, CHA=1), custom condition (can't cast spells), 30-day re-save. |
| Dominate Monster | **NOT BUILDABLE** | WIS save + charmed condition. | Control mechanic (direct creature's actions), re-save on damage. |
| Incendiary Cloud | **PARTIAL** | Moveable zone + DEX save + fire damage + zone triggers. | Auto-move (drifts 10ft/round without action), heavily obscured. |
| Maze | **NOT BUILDABLE** | None. | Automatic banishment (no save), escape mechanic (INT check DC 20). |
| Power Word Stun | **PARTIAL** | Stunned condition + end-of-turn CON save works via AppliedCondition. | HP threshold no-save (150 HP or fewer), automatic resolution without attack/save. Could approximate: automatic + stunned, but no HP check. |
| Tsunami | **NOT BUILDABLE** | None meaningfully. | Wall shape, auto-move, scaling damage over time, forced movement (carried by wave). |

#### 9th Level

| Spell | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Meteor Swarm | **PARTIAL** | AoE sphere + DEX save + multi-damage (fire + bludgeoning). | Multiple AoE zones (4 spheres), overlap rules, 1 mile range. |
| Power Word Kill | **NOT BUILDABLE** | None. | HP threshold no-save + instant death (no damage roll). |
| Power Word Heal | **PARTIAL** | Healing + conditions_removed works. | Heal-to-full (no "all HP" option), stand-up reaction. |
| True Polymorph | **PARTIAL** | Summon/Wild Shape system for creature swap. | Effect choice (creature→creature, creature→object, object→creature), permanence, WIS save for unwilling. |
| Prismatic Wall | **NOT BUILDABLE** | None. | Layered effect (7 independent layers), per-layer destruction, wall shape. |
| Psychic Scream | **PARTIAL** | INT save + psychic damage + stunned with end-of-turn save. | target_count: 10, target restriction (INT 2+), death effect. |
| Blade of Disaster | **NOT BUILDABLE** | None. | Recurring bonus action attacks, crit range (18-20), crit override (12d12), summoned weapon. |
| Weird | **PARTIAL** | WIS save + frightened condition + end-of-turn save. | Multi-target (any number), recurring psychic damage at start of target turn (outside zone system). |
| Shapechange | **PARTIAL** | Summon/creature swap. | Retain stats (keep INT/WIS/CHA), action to change form mid-spell. |
| Foresight | **NOT BUILDABLE** | None. | Buff system (advantage on attacks, checks, saves; disadvantage on attacks against). |
| Invulnerability | **NOT BUILDABLE** | None. | Damage immunity all. |
| Mass Heal | **NOT BUILDABLE** | Healing works. | Distributable HP pool (700 HP split by choice), multi-target, condition removal. |

### Buildability Summary

| Rating | Count | Spells |
|---|---|---|
| **SUPPORTED** (fully buildable) | 2 | Heal, Circle of Death |
| **MOSTLY** (minor gaps only) | 5 | Disintegrate, Harm, Finger of Death, Sunburst, Abi-Dalzim's Horrid Wilting |
| **PARTIAL** (core works, key features missing) | 14 | Sunbeam, Otto's Dance, Blade Barrier, Mental Prison, Mass Suggestion, Whirlwind, Teleport, Incendiary Cloud, Power Word Stun, Meteor Swarm, Power Word Heal, True Polymorph, Psychic Scream, Weird, Shapechange |
| **NOT BUILDABLE** (fundamental mechanic missing) | 16 | Chain Lightning, Eyebite, Globe of Invulnerability, Tasha's Guise, Fire Storm, Reverse Gravity, Crown of Stars, Forcecage, Prismatic Spray, Plane Shift, Power Word Pain, Holy Aura, Dominate Monster, Earthquake, Maze, Tsunami, Power Word Kill, Prismatic Wall, Blade of Disaster, Foresight, Invulnerability, Mass Heal |

**Pattern**: Spells that are "just damage + save + AoE" work well. Anything involving buffs, recurring actions, HP thresholds, multi-AoE, or unique control mechanics doesn't.

### New Primitives from Levels 6-9 — Audit

| Primitive | Status | Implementation Notes |
|---|---|---|
| `chain_effect` | **NOT SUPPORTED** | Bouncing between targets (Chain Lightning). No chaining mechanic. |
| `death_effect` | **NOT SUPPORTED** | Special on-kill outcome (Disintegrate, Finger of Death, Power Word Kill). No post-death trigger. |
| `condition_removal` | **SUPPORTED** | `Action.conditions_removed: list[str]` exists, processed in `resolve_effect()` at `actions.py:823`, exposed in actions_tab UI. Heal's "ends blinded, deafened" works today. |
| `hp_floor` | **NOT SUPPORTED** | "Can't reduce below 1 HP" (Harm). No minimum HP threshold on damage. |
| `spell_immunity_threshold` | **NOT SUPPORTED** | Block spells below level N (Globe of Invulnerability). No spell-level filtering system. |
| `effect_choice_menu` | **NOT SUPPORTED** | Pick from distinct effect options (Eyebite: asleep/panicked/sickened). No branching effect selection at cast time. Workaround: create separate actions per choice. |
| `reactive_effect` | **NOT SUPPORTED** | Trigger when buffed creature is attacked (Holy Aura blinds melee attackers). No on-attacked trigger system. |
| `weapon_enhancement` | **NOT SUPPORTED** | Make attacks magical, override attack stat (Tasha's Guise). No spell-applied weapon modification. |
| `conditional_extra_attack` | **NOT SUPPORTED** | Grant Extra Attack if not already present. No Extra Attack system at all (multiattack is modeled differently). |
| `escape_mechanic` | **NOT SUPPORTED** | Ability check to escape (Maze: INT DC 20, Forcecage: CHA save to teleport). Distinct from save_to_end; uses action + ability check rather than end-of-turn save. |
| `random_effect_table` | **NOT SUPPORTED** | Random d8 determines effect (Prismatic Spray). No random branching mechanic. |
| `progressive_condition` | **NOT SUPPORTED** | Condition worsens on subsequent failed saves (Prismatic Spray: restrained → petrified). Conditions are static once applied. |
| `aoe_count` | **NOT SUPPORTED** | Multiple discrete AoE zones placed together (Fire Storm: 10 cubes, Meteor Swarm: 4 spheres). Only one AoE per action. |
| `overlap_rule` | **NOT SUPPORTED** | How overlapping AoEs interact (Meteor Swarm: save once, damage once). Depends on aoe_count. |
| `auto_move` | **NOT SUPPORTED** | Effect moves without caster action (Incendiary Cloud drifts 10ft/round). Zone system requires action/bonus action to reposition. |
| `scaling_over_time` | **NOT SUPPORTED** | Effect weakens/strengthens over duration (Tsunami: 6d10→5d10→...→1d10). No temporal scaling. |
| `permanence` | **NOT SUPPORTED** | Concentration → permanent after full duration (True Polymorph). Concentration loss always ends the effect. |
| `layered_effect` | **NOT SUPPORTED** | Multiple independent layers, each destroyable (Prismatic Wall: 7 color layers). Extremely rare (2 spells). |
| `crit_range` | **NOT SUPPORTED** | Modified critical threshold, e.g., 18-20 (Blade of Disaster). Attack resolution hardcodes crit on natural 20. |
| `crit_override` | **NOT SUPPORTED** | Custom crit damage instead of doubling dice (Blade of Disaster: 12d12). Crit always doubles dice. |
| `retain_stats` | **NOT SUPPORTED** | Keep INT/WIS/CHA during transformation (Shapechange). Creature swap replaces entire stat block. |
| `distributable_healing` | **NOT SUPPORTED** | HP pool distributed by caster choice (Mass Heal: 700 HP). No distributable pool mechanic. |
| `damage_immunity_all` | **NOT SUPPORTED** | Immune to all damage (Invulnerability). No spell-applied immunity. Part of the buff/debuff gap. |
| `heavily_obscured` | **NOT SUPPORTED** | Area blocks vision (Incendiary Cloud). No vision/obscurement system. |
| `control_mechanic` | **NOT SUPPORTED** | Direct creature's actions (Dominate Monster). No team-swap or puppet control. |
| `exit_damage` | **NOT SUPPORTED** | Damage on leaving a space (Mental Prison: 10d10 psychic). Zones damage on *entry*, not exit. |
| `hp_threshold_no_save` | **NOT SUPPORTED** | Auto-hit if target under HP threshold (Power Word Kill/Stun/Pain). No HP check before resolution. |
| `no_initial_save` | **PARTIAL** | Technically achievable: set resolution to automatic + apply condition with `save_to_end`. But there's no explicit flag, and the condition's save parameters must be set during combat resolution, not on the Action model. |

### Overlap with 1-5 Audit Gaps

Many spells in the 6-9 range fail for the **same reasons** already identified in the 1-5 audit:

| Gap from 1-5 Audit | 6-9 Spells Affected |
|---|---|
| **Buff/Debuff system** | Tasha's Guise, Holy Aura, Foresight, Invulnerability, Otto's Dance |
| **Upcast scaling** | Heal, Circle of Death, Disintegrate, Chain Lightning, Dominate Monster |
| **Multi-target** | Mass Suggestion (12), Psychic Scream (10), Weird (any number), Fire Storm, Meteor Swarm |
| **Recurring actions** | Sunbeam, Eyebite, Crown of Stars, Blade of Disaster, Call Lightning pattern |
| **Speed modification** | Otto's Dance, Power Word Pain |
| **Creature type bonus** | Sunbeam/Sunburst (undead), Abi-Dalzim's (plant/water) |
| **Custom conditions** | Otto's Dance, Power Word Pain, Feeblemind |

### New High-Impact Gaps (unique to 6-9)

These are gaps that didn't appear in levels 1-5 or are significantly more impactful at higher levels:

1. **HP threshold no-save** — All Power Word spells (Pain, Stun, Kill) plus Sleep from level 1. Auto-hit based on current HP. 3-4 spells.

2. **Death effects** — Disintegrate (no body), Finger of Death (creates zombie), Power Word Kill (instant death). 3+ spells but high player interest.

3. **Chain/bounce effects** — Chain Lightning primarily. Rare but iconic.

4. **Crit range/override** — Blade of Disaster, Champion Fighter's Improved Critical. Affects both spells and class features.

5. **Escape mechanics** — Maze (INT check), Forcecage (CHA save to teleport), Entangle (STR check). Ability check (not save) to escape, costing an action. 3+ spells.

### Combined Scorecard (1-9 New Primitives Only)

| Status | Count | Primitives |
|---|---|---|
| **SUPPORTED** | 1 | condition_removal |
| **PARTIAL** | 1 | no_initial_save |
| **NOT SUPPORTED** | 26 | chain_effect, death_effect, hp_floor, spell_immunity_threshold, effect_choice_menu, reactive_effect, weapon_enhancement, conditional_extra_attack, escape_mechanic, random_effect_table, progressive_condition, aoe_count, overlap_rule, auto_move, scaling_over_time, permanence, layered_effect, crit_range, crit_override, retain_stats, distributable_healing, damage_immunity_all, heavily_obscured, control_mechanic, exit_damage, hp_threshold_no_save |

### Summary

Levels 6-9 introduce 28 new primitives. Only 1 is fully supported (`condition_removal`), 1 is partially achievable (`no_initial_save`), and 26 are not supported. However, many of these are **rare primitives** used by 1-3 spells each. The highest-impact gaps remain the same as identified in the 1-5 audit: buff/debuff, upcast scaling, multi-target, and recurring actions. (Note: the on-hit rider gap from the 1-5 audit was **resolved in v0.14.0** — see updated 1-5 audit and `dnd_class_features_primitives.md`.) The new high-impact additions from 6-9 are **HP threshold no-save** (Power Word family) and **crit range modification** (Blade of Disaster + Champion Fighter).

---

## PHASE 2: UI EXPOSURE AUDIT (v0.13.1)

> **Audit date**: 2026-02-25
> **Scope**: Of the 28 new primitives from levels 6-9, which are exposed in the Character Builder UI?
> **Reference**: See Document 1 Phase 2 for the full Actions Tab widget inventory and shared primitive audit.

### New Primitives from 6-9: UI Exposure

Of the 28 new primitives introduced in the 6-9 audit, only `condition_removal` was engine-supported. Here's the UI status:

| Primitive | Engine Status | UI Exposed? | Notes |
|-----------|-------------|-------------|-------|
| condition_removal | ✅ Supported | ✅ **EXPOSED** | Conditions Removed ListEditor in Actions Tab |
| no_initial_save | ⚠️ Partial | ⚠️ Partial | Can create zone-only action (save triggers on turn start, not on cast) |
| chain_effect | ❌ | ❌ | No engine or UI |
| death_effect | ❌ | ❌ | No engine or UI |
| hp_floor | ❌ | ❌ | No engine or UI |
| spell_immunity_threshold | ❌ | ❌ | No engine or UI |
| effect_choice_menu | ❌ | ❌ | No engine or UI |
| reactive_effect | ❌ | ❌ | No engine or UI |
| weapon_enhancement | ❌ | ❌ | No engine or UI |
| conditional_extra_attack | ❌ | ❌ | No engine or UI |
| escape_mechanic | ❌ | ❌ | No engine or UI |
| random_effect_table | ❌ | ❌ | No engine or UI |
| progressive_condition | ❌ | ❌ | No engine or UI |
| aoe_count | ❌ | ❌ | No engine or UI |
| overlap_rule | ❌ | ❌ | No engine or UI |
| auto_move | ❌ | ❌ | No engine or UI |
| scaling_over_time | ❌ | ❌ | No engine or UI |
| permanence | ❌ | ❌ | No engine or UI |
| layered_effect | ❌ | ❌ | No engine or UI |
| crit_range | ❌ | ❌ | No engine or UI |
| crit_override | ❌ | ❌ | No engine or UI |
| retain_stats | ❌ | ❌ | No engine or UI |
| distributable_healing | ❌ | ❌ | No engine or UI |
| damage_immunity_all | ❌ | ❌ | No engine or UI |
| heavily_obscured | ❌ | ❌ | No engine or UI |
| control_mechanic | ❌ | ❌ | No engine or UI |
| exit_damage | ❌ | ❌ | No engine or UI |
| hp_threshold_no_save | ❌ | ❌ | No engine or UI |

### Phase 2 Finding for Levels 6-9

**No new UI gaps were identified.** The single engine-supported primitive (`condition_removal`) IS exposed in the UI via the Conditions Removed ListEditor. All other 6-9 primitives are blocked at the engine level — the UI cannot expose what the engine doesn't support.

The Phase 2 easy wins from the 1-5 audit (condition duration parameters, damage_on_miss, spell duration field) apply here equally — many 6-9 spells that apply conditions (Feeblemind, Flesh to Stone, Mass Suggestion) would benefit from condition duration configuration.

### Spell Buildability With UI (Updated)

Revisiting the spell-by-spell table from Phase 1, now considering UI exposure:

| Spell | Phase 1 Buildability | UI Buildable? | Missing UI Elements |
|-------|---------------------|---------------|-------------------|
| Heal | ✅ Fully | ✅ Yes | None — healing text input |
| Circle of Death | ✅ Fully | ✅ Yes | None — save + damage + necrotic |
| Sunbeam | ⚠️ Mostly | ⚠️ Mostly | Condition duration params for Blinded |
| Disintegrate | ⚠️ Mostly | ⚠️ Mostly | No death-on-0-HP field |
| Finger of Death | ⚠️ Mostly | ⚠️ Mostly | No death/zombie creation |
| Fire Storm | ⚠️ Mostly | ⚠️ Mostly | No multi-area placement |
| Prismatic Spray | ❌ Not buildable | ❌ Not buildable | Random effect table |

The UI status tracks the engine status almost exactly. Where the engine supports a spell, the UI exposes it.
