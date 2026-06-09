# D&D 5e Class Feature & Ability Grammar — Composable Primitives

Continuation of the spell primitives documents. This covers combat-relevant class features,
subclass features, and racial abilities, decomposed using the same grammar.

**Key Insight**: Your Smite popup system — "trigger after confirming a hit, spend a resource,
add an effect" — is actually the pattern for a LOT of class features. I'll call this the
**"on-hit rider" pattern** throughout this document and flag every ability that uses it.
By the end, you'll see that generalizing your Smite system covers a huge chunk of martial
class features.

> **UPDATE (v0.14.0)**: The generalized on-hit rider system has been **IMPLEMENTED**. `Feature.on_hit_rider: OnHitRider` supports POST_HIT (player-chosen) and AUTOMATIC triggers, configurable resource costs (spell slots, ki, etc.), bonus damage with per-slot scaling, saving throws with conditions, and once-per-turn tracking. Engine: `src/combat/riders.py`. GUI: `RiderPopup` (replaces `SmitePopup`). AI: two-phase attack with scoring. Builder: rider editor in Features Tab. RIDER_PRESETS: divine_smite, sneak_attack, stunning_strike, eldritch_smite, hex_damage. See the formalized primitive below for coverage details.

---

## THE ON-HIT RIDER PATTERN (Smite Generalized)

Your Smite popup is actually this primitive:

```
trigger: on_confirmed_hit (you hit with an attack and CHOOSE to activate)
decision_point: after_hit_confirmed (player decides after seeing the hit land)
cost: resource (spell slot, ki, superiority die, channel divinity, etc.)
effect: bonus damage, condition, forced movement, or combination
target: the creature you hit
```

**Every ability that uses this pattern:**
- Divine Smite (Paladin)
- All Smite spells (Thunderous, Wrathful, Branding, Blinding, Staggering, Banishing)
- Eldritch Smite (Warlock Invocation)
- Sneak Attack (Rogue) — no cost, but same decision point
- Stunning Strike (Monk)
- Battlemaster Maneuvers (many of them)
- Savage Attacker (feat — reroll damage dice)
- Great Weapon Master bonus damage (feat — choose to take -5/+10)
- Sharpshooter bonus damage (feat — choose to take -5/+10)
- Colossus Slayer (Ranger: Hunter)
- Dread Ambusher extra damage (Ranger: Gloom Stalker)
- Divine Strike / Potent Spellcasting (various Cleric domains)
- Hex Warrior / Hexblade's Curse bonus damage (Warlock)
- Booming Blade / Green-Flame Blade rider damage (cantrips)

So your "annoying one-off Smite system" is actually one of the most reusable
patterns in the entire game. Let's formalize it. **(v0.14.0: This generalization has been implemented.)**

### Formalized On-Hit Rider Primitive

```
on_hit_rider: {
  trigger: on_confirmed_hit | on_confirmed_crit | on_weapon_hit | on_melee_hit | on_ranged_hit
  decision_point: after_hit (player chooses) | automatic (always applies) | once_per_turn
  cost: { type: spell_slot | ki | superiority_die | channel_divinity | none, amount: N }
  damage_bonus: { dice: NdX, type: damage_type }
  condition_applied: { condition: X, save: ability, DC: spell_save_DC | 8+prof+mod }
  forced_movement: { type: push|pull|prone, distance: N }
  extra_effects: string (for unusual riders)
  frequency: per_hit | once_per_turn | once_per_round | limited_per_rest
}
```

> **v0.14.0 Implementation Coverage** of the above fields:
> | Field | Implemented? | Implementation |
> |-------|-------------|----------------|
> | trigger: on_confirmed_hit | ✅ | `RiderTrigger.POST_HIT` (player chooses) and `RiderTrigger.AUTOMATIC` |
> | trigger: on_confirmed_crit | ❌ | No crit-only trigger; AI scores crits higher but riders fire on any hit |
> | trigger: on_weapon_hit / on_melee_hit / on_ranged_hit | ✅ | `OnHitRider.requires_weapon` and `OnHitRider.requires_melee` checkboxes |
> | decision_point | ✅ | POST_HIT = popup queue, AUTOMATIC = silent resolution |
> | once_per_turn | ✅ | `OnHitRider.once_per_turn` + `TurnResources.used_riders` tracking |
> | cost: spell_slot | ✅ | `resource_type="spell_slot"` with level selection in RiderPopup |
> | cost: ki / other | ✅ | `resource_type="ki_points"` (or any custom) with flat `resource_cost` |
> | cost: superiority_die | ⚠️ | Works via generic resource (`resource_type="superiority_dice"`), but no "roll the die for damage" mechanic |
> | damage_bonus | ✅ | `damage_dice`, `damage_type`, `damage_per_slot_level` scaling, `max_dice` cap |
> | condition_applied | ✅ | `save_ability`, `save_dc_ability`, `condition_on_fail`, `condition_duration`, `condition_save_to_end` |
> | forced_movement | ❌ | Not on OnHitRider model; forced movement is on Action model only |
> | extra_effects | ❌ | No freeform effect field |
> | frequency: limited_per_rest | ❌ | Only `once_per_turn`; per-rest limits need uses_per_rest on Feature (not yet wired) |

---

## BARBARIAN

### Rage
```
activation: bonus_action
cost: class_resource (rage charges, varies by level)
duration: 1 minute (ends early if unconscious, don't attack/take damage for a turn)
concentration: false (but has a "maintenance" condition)
effects:
  stat_target: melee_damage | stat_modification_type: flat_bonus
    stat_modification_value: +2 (scales: +3 at 9th, +4 at 16th)
  stat_target: STR_checks + STR_saves | stat_modification_type: advantage
  damage_resistance: bludgeoning, piercing, slashing (nonmagical for base; all for Bear Totem)
  restriction: "can't cast or concentrate on spells"
maintenance_condition: "must attack or take damage each turn or rage ends"
NOTE: the "maintenance_condition" is like concentration but for a non-spell.
      Could reuse your concentration mechanic with a custom trigger.
```

### Reckless Attack
```
activation: free_action (declared on first attack of turn)
cost: none
duration: until start of next turn
effects:
  stat_target: melee_attack_rolls (STR-based) | stat_modification_type: advantage
  penalty: "all attacks against you have advantage until start of your next turn"
NOTE: "trade_off" primitive — gain advantage but grant advantage to enemies.
      This is a "self_debuff_as_cost" pattern.
```

### Danger Sense
```
activation: passive
trigger: saving_throw against effect you can see (DEX saves)
effects:
  stat_target: DEX_saves | stat_modification_type: advantage
  restriction: "not blinded, deafened, or incapacitated"
NOTE: passive conditional advantage — "passive_conditional_buff"
```

### Brutal Critical
```
activation: passive
trigger: on_confirmed_crit
effects:
  bonus_crit_dice: +1 (scales: +2 at 13th, +3 at 17th)
NOTE: adds extra dice on crit beyond normal doubling.
      "crit_bonus_dice" primitive.
```

### Feral Instinct
```
activation: passive
effects:
  stat_target: initiative | stat_modification_type: advantage
  special: "can act normally on first turn even if surprised (must rage)"
```

### Relentless Rage
```
activation: passive (automatic trigger)
trigger: "drop to 0 HP while raging"
effects:
  save: CON save DC 10 (increases by 5 each use, resets on rest)
  success: drop to 1 HP instead
NOTE: "death_prevention" primitive with escalating DC.
```

### Path of the Totem Warrior (selected features)

**Bear Totem (3rd)**
```
modifies: Rage
effect_modification: damage_resistance becomes ALL damage types except psychic
```

**Wolf Totem (3rd)**
```
modifies: Rage
aoe_shape: aura | aoe_size_primary: 5
aoe_anchor: caster_centered | aoe_moves_with_caster: true
effect: friendly creatures in aura have advantage on melee attacks vs enemies adjacent to barbarian
NOTE: the "grant allies advantage" aura pattern — "ally_buff_aura"
```

**Eagle Totem (3rd)**
```
modifies: Rage
effect: enemies have disadvantage on opportunity attacks against you
grants: Dash as bonus action
```

### Path of the Berserker

**Frenzy**
```
modifies: Rage
effect: can make one melee weapon attack as bonus action each turn
end_penalty: gain one level of exhaustion when rage ends
NOTE: reuses the "end_penalty" primitive from Haste
```

**Mindless Rage**
```
modifies: Rage
effect: can't be charmed or frightened while raging
    if charmed/frightened when entering rage, effect is suspended
NOTE: "condition_immunity_while_active" primitive
```

---

## FIGHTER

### Action Surge
```
activation: free_action (on your turn)
cost: class_resource (1/rest, 2/rest at 17th)
duration: current turn only
effects:
  grants_extra_action: one additional action this turn
NOTE: same "grants_extra_action" as Haste but once per rest, no restrictions
      on what the action can be, and no end penalty.
```

### Second Wind
```
activation: bonus_action
cost: class_resource (1/rest)
duration: instantaneous
effects:
  heal_dice: 1d10 | heal_bonus: fighter_level | heal_type: hit_points
  target: self
```

### Indomitable
```
activation: free_action (reaction-like timing)
trigger: "you fail a saving throw"
cost: class_resource (1/rest, scales to 3/rest)
effects:
  reroll: reroll the saving throw, must use new result
NOTE: "forced_reroll" primitive — reroll a failed save/check/attack.
      Also used by Lucky feat, Halfling Lucky, etc.
```

### Extra Attack
```
activation: passive
effects:
  attack_count_modification: 2 attacks per Attack action (3 at 11th for some, 4 at 20th)
NOTE: "extra_attack" is so fundamental it's basically a core primitive.
      Needs to track how many attacks per Attack action.
```

### Battlemaster Maneuvers

All Battlemaster Maneuvers follow a consistent pattern:

```
cost: 1 superiority_die (d8, scales to d10/d12)
frequency: per_attack or per_turn (varies)
```

**Commander's Strike**
```
trigger: in_place_of_attack (uses one of your attacks)
cost: 1 superiority_die + your bonus action
target: ally within 30ft who can hear you
effect: ally uses reaction to make one weapon attack + add superiority die to damage
NOTE: "grant_ally_reaction_attack" primitive
```

**Disarming Attack**
```
pattern: on_hit_rider
trigger: on_confirmed_hit
damage_bonus: +superiority_die
condition_applied: target drops held item (STR save vs maneuver DC to resist)
```

**Distracting Strike**
```
pattern: on_hit_rider
trigger: on_confirmed_hit
damage_bonus: +superiority_die
effect: next attack by someone other than you has advantage (before start of your next turn)
NOTE: "grant_advantage_to_next_ally_attack" — similar to Guiding Bolt
```

**Evasive Footwork**
```
trigger: when you move
cost: 1 superiority_die
duration: until you stop moving
effects:
  stat_target: AC | stat_modification_type: flat_bonus | value: superiority_die roll
```

**Feinting Attack**
```
trigger: on_your_turn (bonus action)
cost: 1 superiority_die
target: creature within 5ft
effect: advantage on next attack against target + superiority_die bonus damage on hit
NOTE: bonus_action setup → benefit on next attack. "setup_attack" pattern.
```

**Goading Attack**
```
pattern: on_hit_rider
trigger: on_confirmed_hit
damage_bonus: +superiority_die
condition_applied: WIS save or target has disadvantage on attacks against anyone but you (until end of your next turn)
NOTE: "taunt" or "forced_focus" mechanic
```

**Lunging Attack**
```
pattern: on_hit_rider (sort of — declared before attack)
trigger: when you make a melee attack
cost: 1 superiority_die
effect: +5ft reach for this attack + superiority_die bonus damage on hit
NOTE: "reach_extension" primitive
```

**Maneuvering Attack**
```
pattern: on_hit_rider
trigger: on_confirmed_hit
damage_bonus: +superiority_die
effect: choose a friendly creature who can see/hear you → 
    that creature can use reaction to move up to half speed without provoking opportunity attacks
NOTE: "grant_ally_movement" primitive
```

**Menacing Attack**
```
pattern: on_hit_rider
trigger: on_confirmed_hit
damage_bonus: +superiority_die
condition_applied: frightened (WIS save vs maneuver DC, until end of your next turn)
```

**Parry**
```
trigger: reaction | reaction_trigger: "when you are hit by a melee attack"
cost: 1 superiority_die
effect: reduce damage by superiority_die + DEX modifier
NOTE: "damage_reduction_reaction" primitive
```

**Precision Attack**
```
trigger: on_attack_roll (before or after rolling, before knowing if hit)
cost: 1 superiority_die
effect: add superiority_die to attack roll
NOTE: different decision point than on_hit — this is "on_attack_roll_rider"
```

**Pushing Attack**
```
pattern: on_hit_rider
trigger: on_confirmed_hit
damage_bonus: +superiority_die
forced_movement: push 15ft (STR save to resist push, but still take bonus damage)
target_restriction: "Large or smaller"
```

**Rally**
```
trigger: on_your_turn (bonus action)
cost: 1 superiority_die
target: friendly creature within 60ft who can see/hear you
effect: target gains temp HP = superiority_die + CHA modifier
NOTE: "grant_temp_hp" is essentially a heal_type: temp_hp with a target
```

**Riposte**
```
trigger: reaction | reaction_trigger: "creature misses you with melee attack"
cost: 1 superiority_die
effect: make one melee weapon attack against the creature + superiority_die bonus damage
NOTE: "counter_attack_on_miss" — reaction attack triggered by enemy missing
```

**Sweeping Attack**
```
pattern: on_hit_rider
trigger: on_confirmed_hit
cost: 1 superiority_die
target: different creature within 5ft of original target AND within your reach
effect: deal superiority_die damage to the second creature (if original attack roll would hit)
NOTE: "cleave" or "splash_to_adjacent" primitive
```

**Trip Attack**
```
pattern: on_hit_rider
trigger: on_confirmed_hit
damage_bonus: +superiority_die
condition_applied: prone (STR save to resist)
target_restriction: "Large or smaller"
```

### Champion Features

**Improved Critical**
```
activation: passive
effect:
  crit_range: 19-20 (18-20 at 15th level with Superior Critical)
NOTE: same "crit_range" primitive from Blade of Disaster
```

**Remarkable Athlete**
```
activation: passive
effect:
  stat_target: STR/DEX/CON ability checks (not proficient)
  stat_modification_type: flat_bonus | value: half_proficiency_bonus (round up)
  also: +running_long_jump distance (noncombat, probably skip)
```

### Eldritch Knight Features

**War Magic (7th)**
```
trigger: after_casting_cantrip
effect: can make one weapon attack as bonus action
NOTE: "bonus_action_attack_after_cantrip" — specific combo enabler
```

**Eldritch Strike (10th)**
```
trigger: on_confirmed_hit (weapon attack)
effect: target has disadvantage on next save vs your spell (before end of your next turn)
NOTE: "weaken_saves_on_hit" — on_hit_rider that debuffs saves instead of dealing damage
```

---

## ROGUE

### Sneak Attack
```
pattern: on_hit_rider
trigger: on_confirmed_hit (finesse or ranged weapon)
decision_point: after_hit (player chooses, but almost always yes)
cost: none
frequency: once_per_turn
condition_required: advantage on attack OR ally within 5ft of target
damage_bonus: scales by level (1d6 at 1st, 2d6 at 3rd, ... 10d6 at 19th)
damage_type: same as weapon
NOTE: the "condition_required" field is important — Sneak Attack has prerequisites
      beyond just hitting. "prerequisite_condition" primitive.
```

### Cunning Action
```
activation: bonus_action
cost: none
effect_choice: Dash, Disengage, or Hide as bonus action
NOTE: "action_economy_upgrade" — things that normally cost an action now cost bonus action
```

### Uncanny Dodge
```
trigger: reaction | reaction_trigger: "attacker you can see hits you with an attack"
cost: none (uses reaction)
effect: halve the attack's damage
NOTE: "damage_halving_reaction" — similar to Parry but flat half, no roll
```

### Evasion
```
activation: passive
trigger: DEX saving throw for half damage
effect:
  save_success: take no damage instead of half
  save_fail: take half damage instead of full
NOTE: "improved_save_outcome" — upgrades save results by one step.
      Also used by Monk's Evasion (identical).
```

### Reliable Talent
```
activation: passive
trigger: ability check where you add proficiency
effect: treat any d20 roll of 9 or lower as 10
NOTE: "minimum_roll" primitive — floor on the d20 result
```

### Assassinate (Assassin 3rd)
```
activation: passive
trigger: first round of combat
effects:
  advantage on attacks against creatures that haven't acted yet
  auto_crit: if you hit a surprised creature, the hit is a critical
NOTE: "surprise_round_bonus" and "auto_crit_condition"
```

### Arcane Trickster — Magical Ambush (9th)
```
trigger: when you cast a spell while hidden
effect: target has disadvantage on save against the spell
NOTE: "stealth_casting_debuff" — conditional save debuff
```

---

## PALADIN

### Divine Smite
```
pattern: on_hit_rider
trigger: on_confirmed_hit (melee weapon attack)
decision_point: after_hit_confirmed
cost: spell_slot (1st level minimum)
damage_bonus: 2d8 radiant (base for 1st level slot)
upcast: +1d8 per slot level above 1st (max 5d8)
creature_type_bonus: +1d8 vs undead and fiends
NOTE: THIS is your existing Smite system. Everything else that uses the
      on_hit_rider pattern can reuse this infrastructure.
```

### Smite Spells (all follow a pattern)

These are "concentration buff on self that triggers on next weapon hit":

```
shared_pattern: {
  action_type: bonus_action
  range: self
  duration: concentration, 1 minute
  trigger: on_next_weapon_hit (consumes spell, ends concentration)
}
```

**Thunderous Smite (1st)**
```
shared_pattern + {
  damage_bonus: 2d6 thunder
  forced_movement: push 10ft (STR save or also prone)
  audible: 300ft
}
```

**Wrathful Smite (1st)**
```
shared_pattern + {
  damage_bonus: 1d6 psychic
  condition: frightened (WIS save to end, uses action)
}
```

**Branding Smite (2nd)**
```
shared_pattern + {
  damage_bonus: 2d6 radiant
  effect: target sheds dim light 5ft, can't be invisible
  upcast: +1d6 per slot above 2nd
}
```

**Blinding Smite (3rd)**
```
shared_pattern + {
  damage_bonus: 3d8 radiant
  condition: blinded (CON save at end of each turn to end)
}
```

**Staggering Smite (4th)**
```
shared_pattern + {
  damage_bonus: 4d6 psychic
  condition: WIS save or disadvantage on attacks/ability checks,
    can't take reactions, until end of its next turn
}
```

**Banishing Smite (5th)**
```
shared_pattern + {
  damage_bonus: 5d10 force
  hp_threshold_branch: if target reduced to 50 HP or less by this,
    target is banished (as Banishment) for remainder of duration
}
```

### Lay on Hands
```
activation: action
cost: class_resource (HP pool = paladin level × 5)
range: touch
target: willing creature
effect_choice:
  - Heal: spend points from pool to restore that many HP
  - Cure Disease: spend 5 points to cure one disease
  - Neutralize Poison: spend 5 points to neutralize one poison
NOTE: "resource_pool_spending" — spend variable amounts from a pool.
      Different from spell slots.
```

### Aura of Protection
```
activation: passive
aoe_shape: aura | aoe_size_primary: 10 (30 at 18th)
aoe_anchor: caster_centered | aoe_moves_with_caster: true
effect:
  target: you + friendly creatures in aura
  stat_target: saving_throws (all) | stat_modification_type: flat_bonus
  stat_modification_value: CHA modifier (minimum +1)
requirement: "paladin is conscious"
NOTE: "passive_aura_buff" — always-on aura. Key pattern for Paladins.
```

### Aura of Courage (10th)
```
activation: passive
aoe_shape: aura | aoe_size_primary: 10 (30 at 18th)
aoe_anchor: caster_centered | aoe_moves_with_caster: true
effect:
  target: you + friendly creatures in aura
  condition_immunity: frightened (while in aura)
requirement: "paladin is conscious"
```

### Improved Divine Smite (11th)
```
activation: passive
trigger: on_confirmed_hit (melee weapon attack)
decision_point: automatic (always applies, no choice)
damage_bonus: 1d8 radiant (stacks with Divine Smite if used)
cost: none
NOTE: this is the "automatic on_hit_rider" — no resource cost, no decision.
      The passive version of your Smite popup.
```

### Cleansing Touch (14th)
```
activation: action
cost: class_resource (CHA modifier per long rest)
range: touch
target: willing creature
effect: end one spell on the target
NOTE: like a targeted Dispel Magic with no check — "targeted_dispel"
```

### Oath of Vengeance

**Vow of Enmity**
```
activation: bonus_action
cost: channel_divinity
range: 10ft | target: single creature
duration: 1 minute (or until target drops to 0 / unconscious)
effect:
  stat_target: attack_rolls (against target only)
  stat_modification_type: advantage
NOTE: single-target buff like Hunter's Mark but grants advantage instead of damage
```

**Relentless Avenger (7th)**
```
trigger: on_confirmed_hit (opportunity attack)
effect: can move up to half speed immediately after, no opportunity attacks provoked
NOTE: "bonus_movement_on_hit" — reactive movement
```

### Oath of the Ancients

**Aura of Warding (7th)**
```
aoe_shape: aura | aoe_size_primary: 10 (30 at 18th)
aoe_anchor: caster_centered | aoe_moves_with_caster: true
effect: creatures in aura have resistance to spell damage
NOTE: "damage_resistance: spell_damage" — resistance specifically to damage from spells.
      Broader than a single damage type.
```

---

## MONK

### Martial Arts
```
activation: passive
effects:
  weapon_enhancement: monk weapons and unarmed use DEX instead of STR (choice)
  martial_arts_die: 1d4 (scales: d6 at 5th, d8 at 11th, d10 at 17th)
  bonus_action_attack: when you take Attack action with monk weapon/unarmed,
    make one unarmed strike as bonus action
NOTE: the scaling martial arts die is a "scaling_die" primitive
```

### Ki (resource system)
```
resource: ki_points (= monk level)
recovery: short_rest (all points)
```

### Flurry of Blows
```
activation: bonus_action (immediately after Attack action)
cost: 1 ki
effect: make two unarmed strikes as bonus action (instead of one from Martial Arts)
NOTE: "upgraded_bonus_action_attack" — replaces the standard bonus action unarmed
```

### Patient Defense
```
activation: bonus_action
cost: 1 ki
effect: take Dodge action as bonus action
NOTE: "action_economy_upgrade" — same pattern as Cunning Action
```

### Step of the Wind
```
activation: bonus_action
cost: 1 ki
effect: Disengage or Dash as bonus action + jump distance doubled this turn
```

### Stunning Strike
```
pattern: on_hit_rider
trigger: on_confirmed_hit (melee weapon attack)
decision_point: after_hit_confirmed
cost: 1 ki
condition_applied: stunned (CON save vs ki DC, until end of your next turn)
NOTE: EXACTLY the same pattern as Divine Smite but with a condition instead of damage.
      Your Smite popup system handles this perfectly.
```

### Deflect Missiles
```
trigger: reaction | reaction_trigger: "hit by ranged weapon attack"
cost: none (reaction only; 1 ki to throw back)
effect: reduce damage by 1d10 + DEX mod + monk level
  if reduced to 0: can spend 1 ki to make ranged attack (20/60) with the caught missile
    damage: martial_arts_die + DEX mod (counts as monk weapon)
NOTE: "damage_reduction_reaction" (like Parry) + optional "counter_attack" for 1 ki
```

### Slow Fall
```
trigger: reaction | reaction_trigger: "you are falling"
cost: none
effect: reduce fall damage by monk_level × 5
NOTE: "fall_damage_reduction" — niche but might matter in combat
```

### Evasion
```
(identical to Rogue Evasion — see above)
improved_save_outcome: DEX saves, no damage on success, half on fail
```

### Stillness of Mind
```
activation: action
cost: none
effect: end one effect causing charmed or frightened on yourself
NOTE: "self_condition_removal" primitive
```

### Diamond Soul (14th)
```
activation: passive + active
passive: proficiency in all saving throws
active: when you fail a save, spend 1 ki to reroll
NOTE: "forced_reroll" again (same as Indomitable)
```

### Empty Body (18th)
```
activation: action
cost: 4 ki
duration: 1 minute
effects:
  condition: invisible
  damage_resistance: all except force
```

### Open Hand Techniques (Way of the Open Hand)
```
trigger: when you hit with Flurry of Blows attack
effect_choice (per hit):
  - Prone: target must DEX save or be knocked prone
  - Push: target must STR save or be pushed 15ft
  - No Reactions: target can't take reactions until end of your next turn
NOTE: on_hit_rider with effect_choice menu, triggered by specific attack type (Flurry)
```

### Quivering Palm (Way of the Open Hand, 17th)
```
activation: part of unarmed strike hit
cost: 3 ki
effect: imperceptible vibrations in target's body
  at any later point, you can use action: target makes CON save
    fail: reduced to 0 HP
    success: 10d10 necrotic damage
NOTE: "delayed_trigger_effect" — set up now, trigger later.
      Like a single-target Contingency. Very rare but very cool.
```

### Shadow Step (Way of Shadow, 6th)
```
activation: bonus_action
cost: none
requirement: "in dim light or darkness"
effect: teleport 60ft to unoccupied space in dim light/darkness
  + advantage on first melee attack before end of turn
NOTE: conditional teleport + attack advantage combo
```

---

## RANGER

### Favored Enemy
```
activation: passive
effect: advantage on WIS (Survival) to track + INT checks to recall info
    about chosen creature type(s)
NOTE: mostly noncombat, but the "creature type tracking" could be relevant
```

### Hunter's Prey (Hunter subclass, 3rd — pick one)

**Colossus Slayer**
```
pattern: on_hit_rider
trigger: on_confirmed_hit (weapon attack)
decision_point: automatic
cost: none
frequency: once_per_turn
prerequisite_condition: target is below max HP
damage_bonus: 1d8 (same type as weapon)
```

**Giant Killer**
```
trigger: reaction | reaction_trigger: "Large or larger creature within 5ft attacks you"
cost: none (uses reaction)
effect: make one weapon attack against that creature
```

**Horde Breaker**
```
trigger: on_confirmed_hit (weapon attack against one creature)
cost: none
frequency: once_per_turn
effect: make one additional weapon attack against a different creature within 5ft of original
    AND within range of your weapon
NOTE: "bonus_attack_vs_adjacent" — attack a second target near your first
```

### Defensive Tactics (Hunter, 7th — pick one)

**Escape the Horde**
```
activation: passive
effect: opportunity attacks against you have disadvantage
```

**Multiattack Defense**
```
activation: passive
trigger: "creature hits you with an attack"
effect: +4 AC against subsequent attacks from same creature this turn
NOTE: "escalating_defense" — AC improves against repeated attacks
```

**Steel Will**
```
activation: passive
effect: advantage on saves vs frightened
```

### Multiattack (Hunter, 11th — pick one)

**Volley**
```
activation: replaces Attack action
cost: none (uses ammunition)
target: all creatures within 10ft of a point you can see within range
resolution: make one attack roll against each creature in area
NOTE: "attack_action_aoe" — turns single-target attack into AoE
```

**Whirlwind Attack**
```
activation: replaces Attack action
cost: none
target: all creatures within your melee reach
resolution: make one melee attack against each creature
NOTE: same "attack_action_aoe" pattern but melee
```

### Gloom Stalker Features

**Dread Ambusher (3rd)**
```
trigger: first turn of combat
effects:
  speed_modification: +10ft for first turn
  bonus_attack: one additional weapon attack as part of Attack action
    damage_bonus: +1d8 (same type as weapon) on the extra attack
NOTE: "first_round_bonus" — extra capabilities on the first turn of combat.
      Similar concept to Assassinate.
```

**Stalker's Flurry (11th)**
```
trigger: when you miss with a weapon attack
cost: none
frequency: once_per_turn
effect: make one additional weapon attack
NOTE: "attack_on_miss" — consolation attack when you whiff
```

---

## WARLOCK

### Eldritch Invocations (Combat-Relevant)

**Agonizing Blast**
```
modifies: Eldritch Blast
effect: add CHA modifier to each beam's damage
NOTE: "cantrip_modifier" — adds ability mod to cantrip damage
```

**Repelling Blast**
```
modifies: Eldritch Blast
pattern: on_hit_rider (automatic)
effect: push target 10ft straight away per beam hit
NOTE: on_hit_rider with automatic trigger, applied to specific cantrip
```

**Grasp of Hadar**
```
modifies: Eldritch Blast
pattern: on_hit_rider (automatic, once per turn)
effect: pull target 10ft toward you (once per turn)
```

**Lance of Lethargy**
```
modifies: Eldritch Blast
pattern: on_hit_rider (once per turn)
effect: reduce target's speed by 10ft until end of your next turn
```

**Eldritch Smite**
```
pattern: on_hit_rider
trigger: on_confirmed_hit (pact weapon)
decision_point: after_hit_confirmed
cost: warlock_spell_slot
damage_bonus: 1d8 force + 1d8 per slot level above 1st
forced_movement: prone (if Huge or smaller, knocked prone — no save!)
NOTE: exactly your Smite system — spend slot, bonus damage + effect on hit
```

**Devil's Sight**
```
activation: passive
grants_sense: darkvision 120ft (sees through magical darkness)
NOTE: the "sees through magical darkness" part is unique — "enhanced_darkvision"
```

**Tomb of Levistus**
```
trigger: reaction | reaction_trigger: "you take damage"
cost: none (1/rest)
effect: gain 10 × warlock_level temp HP
    BUT: incapacitated, speed 0, vulnerable to fire until end of next turn
NOTE: "emergency_temp_hp" with severe drawback. Trade-off pattern.
```

### Hexblade Features

**Hexblade's Curse (1st)**
```
activation: bonus_action
cost: class_resource (1/rest)
range: 30ft | target: single creature
duration: 1 minute (or target dies, you die, or incapacitated)
effects:
  damage_bonus: +proficiency_bonus to damage rolls against target
  crit_range: 19-20 against target
  heal_on_kill: regain HP = warlock_level + CHA mod if cursed target dies
NOTE: "target_mark" with multiple stacking benefits.
      Combines crit_range, damage_bonus, and heal_on_kill.
```

**Armor of Hexes (10th)**
```
trigger: "cursed target hits you with attack"
effect: roll d6, on 4+ the attack misses regardless of roll
NOTE: "chance_to_negate_hit" — probabilistic damage avoidance
```

---

## CLERIC

### Channel Divinity: Turn Undead
```
activation: action
cost: channel_divinity
aoe_shape: sphere | aoe_size_primary: 30
aoe_anchor: caster_centered
target_restriction: undead that can see/hear you
resolution_type: saving_throw | save_ability: WIS
save_success_effect: no_effect
condition: frightened + must Dash away (can't move closer)
duration: 1 minute or until it takes damage
scaling: Destroy Undead at higher levels (instant kill if CR below threshold)
  5th: CR 1/2, 8th: CR 1, 11th: CR 2, 14th: CR 3, 17th: CR 4
NOTE: "destroy_below_cr" — instant kill based on CR threshold
```

### Domain Features (selected combat-relevant ones)

**Life Domain: Disciple of Life (1st)**
```
trigger: when you cast a healing spell of 1st level+
effect: target regains additional 2 + spell_level HP
NOTE: "healing_bonus_on_spell" — flat bonus added to healing spells.
      Modifies other spells' output.
```

**Life Domain: Blessed Healer (6th)**
```
trigger: when you cast a healing spell of 1st level+ on another creature
effect: you regain 2 + spell_level HP
NOTE: "self_heal_on_heal" — healer gets a kickback
```

**War Domain: War Priest (1st)**
```
trigger: when you take Attack action
cost: class_resource (WIS mod per long rest)
effect: make one weapon attack as bonus action
```

**War Domain: Guided Strike (Channel Divinity)**
```
trigger: when you make an attack roll
cost: channel_divinity
effect: +10 to the attack roll (declared after rolling, before knowing result)
NOTE: "massive_attack_bonus" — one-time large flat bonus.
      Decision point: after_roll_before_result (same timing as some Battlemaster maneuvers)
```

**Tempest Domain: Wrath of the Storm (1st)**
```
trigger: reaction | reaction_trigger: "creature within 5ft hits you with attack"
cost: class_resource (WIS mod per long rest)
effect: attacker takes 2d8 lightning or thunder damage (DEX save half)
NOTE: "retaliatory_damage" — reactive damage when hit
```

**Tempest Domain: Destructive Wrath (Channel Divinity)**
```
trigger: when you roll lightning or thunder damage
cost: channel_divinity
effect: deal maximum damage instead of rolling
NOTE: "maximize_damage" — replace dice rolls with maximum values.
      Very powerful primitive.
```

**Forge Domain: Blessing of the Forge (1st)**
```
activation: long rest ritual
target: one nonmagical weapon or armor
effect: weapon: +1 to attack and damage OR armor: +1 AC
duration: until next long rest
NOTE: "equipment_enchantment" — temporary magic item creation
```

**Twilight Domain: Twilight Sanctuary (Channel Divinity)**
```
activation: action
cost: channel_divinity
aoe_shape: sphere | aoe_size_primary: 30
aoe_anchor: caster_centered | aoe_moves_with_caster: true
duration: 1 minute
trigger_timing: end_of_turn (any creature of your choice that ends turn in aura)
effect_choice (per creature per turn):
  - Temp HP: 1d6 + cleric level
  - End Effect: end charmed or frightened
NOTE: powerful "ally_buff_aura" with per-turn healing. Considered very strong.
```

---

## DRUID

### Wild Shape
```
activation: bonus_action (for most druids; action to revert)
cost: class_resource (2/rest)
duration: floor(druid_level / 2) hours
effect: transform into beast (CR limit by level, see table)
  CR: 1/4 at 2nd (no flying/swimming), 1/2 at 4th (no flying), 1 at 8th
summon_stat_block: linked character sheet (YOUR SYSTEM!)
excess_damage_carryover: true (extra damage carries to real form HP)
retain_stats: some (can't cast spells, but keep mental stats for game features)
revert_condition: "0 HP in beast form, duration expires, or bonus action"
Moon Druid: can use as bonus action at level 2, higher CR beasts,
  can spend spell slots to heal in Wild Shape (1d8 per slot level)
NOTE: your stat block swap solution is perfect for this.
```

### Circle Features

**Moon: Combat Wild Shape**
```
modifies: Wild Shape
improvements:
  - bonus action to Wild Shape (standard for Moon, others get this at 2nd anyway)
  - CR limit: 1 at 2nd, increases by 1 per 3 druid levels (roughly)
  - can spend spell slots as bonus action while in Wild Shape to heal self (1d8 per slot level)
NOTE: "in_form_healing" — spend spell slots to heal while transformed
```

**Spores: Halo of Spores (2nd)**
```
trigger: reaction | reaction_trigger: "creature you can see moves to within 10ft
    or starts turn within 10ft"
cost: none (uses reaction)
damage: 1d4 necrotic (CON save negates) — scales: 1d6 at 6th, 1d8 at 10th, 1d10 at 14th
NOTE: "proximity_reaction_damage" — automatic reactive damage to nearby creatures
```

**Spores: Symbiotic Entity (2nd)**
```
activation: action (uses Wild Shape charge)
cost: 1 Wild Shape use
duration: 10 minutes (or until temp HP gone)
effects:
  gain temp HP: 4 × druid level
  Halo of Spores: double the damage dice
  melee_weapon_attacks: +1d6 poison damage
NOTE: uses Wild Shape resource for a buff instead of transformation.
      "alternate_resource_use" pattern.
```

---

## SORCERER

### Metamagic

Metamagic options modify how spells work. They're "spell modifiers" applied at cast time.

```
shared_pattern: {
  activation: declared at time of casting
  cost: sorcery_points (varies)
  target: the spell being cast
  frequency: one metamagic per spell (unless Twinned + another at higher levels)
}
```

**Careful Spell**
```
cost: 1 sorcery_point
effect: choose up to CHA mod creatures in spell's AoE — they auto-succeed on save
NOTE: "selective_targeting" — we already have this primitive!
```

**Distant Spell**
```
cost: 1 sorcery_point
effect: double the spell's range (or touch → 30ft)
NOTE: "range_modification" — modifies another spell's range primitive
```

**Empowered Spell**
```
cost: 1 sorcery_point
effect: reroll up to CHA mod damage dice, must use new rolls
NOTE: "damage_reroll" — selective reroll of damage dice
```

**Extended Spell**
```
cost: 1 sorcery_point
effect: double the spell's duration (max 24 hours)
NOTE: "duration_modification" — modifies another spell's duration primitive
```

**Heightened Spell**
```
cost: 3 sorcery_points
target: one target of the spell
effect: target has disadvantage on first save against the spell
NOTE: "impose_save_disadvantage" — debuff target's save
```

**Quickened Spell**
```
cost: 2 sorcery_points
effect: change casting time from 1 action to 1 bonus action
NOTE: "action_economy_modification" — modifies the spell's action_type
```

**Subtle Spell**
```
cost: 1 sorcery_point
effect: cast without verbal or somatic components
NOTE: mostly noncombat/anti-Counterspell, but relevant because
      a spell cast with Subtle can't be Counterspelled (no perceivable casting)
```

**Twinned Spell**
```
cost: sorcery_points = spell level (1 for cantrips)
requirement: spell targets only one creature and doesn't have range self
effect: spell targets a second creature in range
NOTE: "duplicate_targeting" — add an additional target to a single-target spell
```

---

## WIZARD (Subclass Features)

### Evocation: Sculpt Spells (2nd)
```
trigger: when you cast an evocation spell
effect: choose up to 1 + spell_level creatures in AoE — they auto-succeed
    and take no damage (even if they'd normally take half)
NOTE: enhanced "selective_targeting" — not just auto-succeed, but auto-no-damage
```

### Evocation: Potent Cantrip (6th)
```
trigger: when creature saves against your cantrip
effect: creature takes half damage instead of no damage
NOTE: "improved_cantrip_save" — upgrades cantrip save from no_effect to half_damage
```

### Evocation: Empowered Evocation (10th)
```
trigger: when you deal damage with wizard evocation spell
effect: +INT modifier to one damage roll
NOTE: "ability_mod_to_spell_damage" — flat damage bonus to spells
```

### War Magic: Arcane Deflection (2nd)
```
trigger: reaction | reaction_trigger: "hit by attack OR fail a save"
cost: none (uses reaction)
effect: +2 AC against triggering attack OR +4 to triggering save
restriction: until end of next turn, can only cast cantrips
NOTE: "defensive_reaction_with_restriction" — powerful reaction but limits next turn
```

### War Magic: Tactical Wit (2nd)
```
activation: passive
effect: +INT modifier to initiative rolls
NOTE: "initiative_bonus" — flat bonus to initiative
```

### War Magic: Durable Magic (10th)
```
activation: passive
trigger: while concentrating on a spell
effect: +2 AC and +2 to all saves
NOTE: "concentration_bonus" — buff while maintaining concentration
```

### Bladesinger: Bladesong (2nd)
```
activation: bonus_action
cost: class_resource (proficiency bonus per long rest)
duration: 1 minute (ends if incapacitated, don medium/heavy armor, shield, or two-hand weapon)
effects:
  stat_target: AC | stat_modification_type: flat_bonus | value: INT modifier
  stat_target: walking_speed | stat_modification_type: bonus_feet | value: 10
  stat_target: concentration_checks | stat_modification_type: flat_bonus | value: INT modifier
  stat_target: Acrobatics | stat_modification_type: flat_bonus | value: INT modifier
```

### Bladesinger: Extra Attack (6th)
```
special: one of the attacks can be replaced with casting a cantrip
NOTE: "cantrip_as_attack_replacement" — unique to Bladesinger
```

---

## BARD

### Bardic Inspiration
```
activation: bonus_action
cost: class_resource (CHA mod per rest; short rest at 5th+)
range: 60ft
target: one creature (not yourself) that can hear you
duration: 10 minutes (one use)
effect: target gains Bardic Inspiration die
  target can add die to one ability check, attack roll, or save
  decision_point: after_roll_before_result
  die_size: d6 (d8 at 5th, d10 at 10th, d12 at 15th)
NOTE: "bonus_die_grant" — give another creature a die to add to a future roll.
      Different from flat bonus because it's a die, and the recipient chooses when.
```

### Cutting Words (Lore Bard, 3rd)
```
trigger: reaction | reaction_trigger: "creature within 60ft makes attack, ability check, or damage roll"
cost: 1 Bardic Inspiration use
effect: subtract Bardic Inspiration die from the creature's roll
decision_point: after_roll_before_result
NOTE: "penalty_die_reaction" — subtract a die from enemy roll as reaction
```

### Combat Inspiration (Valor Bard, 3rd)
```
modifies: Bardic Inspiration
additional_use: recipient can add die to weapon damage roll
    OR add die to AC against one attack (after seeing roll, before knowing if hit)
```

### Countercharm (6th)
```
activation: action
cost: none
duration: until start of your next turn
aoe_shape: aura | aoe_size_primary: 30
aoe_anchor: caster_centered
effect: you and friendly creatures have advantage on saves vs frightened and charmed
```

### Magical Secrets (10th/14th/18th)
```
effect: learn 2 spells from any class's spell list
NOTE: purely a character building feature, not a combat mechanic.
      Your spell system already handles this since spells are class-agnostic.
```

---

## FEATS (Combat-Relevant)

### Great Weapon Master
```
feature_1:
  trigger: on_confirmed_crit OR when you reduce creature to 0 HP
  effect: make one melee weapon attack as bonus action

feature_2:
  pattern: on_hit_rider (declared before attack)
  decision_point: before_attack_roll
  effect: take -5 to attack roll, gain +10 damage on hit
NOTE: the -5/+10 trade-off is declared before rolling — "pre_attack_trade_off"
```

### Sharpshooter
```
feature_1:
  effect: ranged attacks ignore half and three-quarters cover
  NOTE: "cover_interaction: ignore_cover"

feature_2:
  effect: no disadvantage at long range

feature_3:
  pattern: same as GWM feature 2 (-5 attack/+10 damage, declared before attack)
```

### Polearm Master
```
feature_1:
  trigger: when you take Attack action with glaive/halberd/quarterstaff/spear
  effect: bonus action attack with opposite end (1d4 bludgeoning + STR)

feature_2:
  trigger: reaction | reaction_trigger: "creature enters your reach"
  effect: make opportunity attack
NOTE: "expanded_opportunity_attack_trigger" — OA triggers on entering reach, not just leaving
```

### Sentinel
```
feature_1:
  trigger: on_confirmed_hit (opportunity attack)
  effect: target's speed becomes 0 for rest of turn

feature_2:
  effect: creatures within your reach provoke OA even if they Disengage

feature_3:
  trigger: reaction | reaction_trigger: "creature within 5ft attacks someone other than you"
  requirement: attacker doesn't have this feat
  effect: make melee weapon attack against that creature
NOTE: "defensive_reaction_attack" — protect allies by attacking threats
```

### War Caster
```
feature_1:
  effect: advantage on CON saves for concentration

feature_2:
  effect: can perform somatic components with hands full

feature_3:
  trigger: when you would make opportunity attack
  effect: can cast a spell (1 action, single target only) instead of melee attack
NOTE: "spell_as_opportunity_attack" — replace OA with a spell
```

### Lucky
```
cost: 3 luck points per long rest
trigger: when you make an attack, ability check, or save
    OR when attack is made against you
effect: roll additional d20, choose which d20 to use
decision_point: after_roll_before_result
NOTE: "extra_d20_choice" — different from advantage (pick from 3 dice possible,
      or impose disadvantage on enemy by rolling your d20 into their roll)
```

### Resilient
```
effect: +1 to chosen ability score + proficiency in that ability's saves
NOTE: purely passive stat modification — character builder feature
```

### Tough
```
effect: +2 HP per level (retroactive)
NOTE: purely passive — max HP increase
```

### Alert
```
effect: +5 initiative, can't be surprised, hidden creatures don't gain advantage on attacks
NOTE: "initiative_bonus" + "surprise_immunity" + "hidden_attack_immunity"
```

### Crossbow Expert
```
feature_1: ignore loading property
feature_2: no disadvantage on ranged attack within 5ft
feature_3: bonus action hand crossbow attack after Attack action with one-handed weapon
```

---

## CONSOLIDATED: NEW PRIMITIVES FROM CLASS FEATURES

| Primitive | Description | Example |
|---|---|---|
| `on_hit_rider` (GENERALIZED) | After confirmed hit, choose to add effect for a resource cost | Divine Smite, Stunning Strike, Eldritch Smite, Battlemaster Maneuvers |
| `automatic_on_hit_rider` | Like above but always applies, no choice/cost | Improved Divine Smite, Colossus Slayer, Sneak Attack |
| `pre_attack_trade_off` | Declared before attack roll: penalty for bonus | GWM, Sharpshooter (-5/+10) |
| `after_roll_before_result` | Decision made after rolling but before knowing outcome | Bardic Inspiration, Precision Attack, Guided Strike |
| `maintenance_condition` | Active ability ends if condition not met each turn | Rage (must attack or take damage) |
| `self_debuff_as_cost` | Gain a benefit but enemies also gain a benefit | Reckless Attack |
| `passive_conditional_buff` | Always-on bonus with a prerequisite | Danger Sense, Reliable Talent |
| `crit_bonus_dice` | Extra dice on critical hits beyond doubling | Brutal Critical |
| `death_prevention` | Avoid dropping to 0 HP (with escalating DC or cost) | Relentless Rage |
| `ally_buff_aura` | Passive always-on aura buffing nearby allies | Aura of Protection, Wolf Totem |
| `condition_immunity_while_active` | Immune to condition while ability is active | Mindless Rage (charm/frighten) |
| `forced_reroll` | Reroll a failed save/check/attack | Indomitable, Diamond Soul, Lucky |
| `extra_attack` | Additional attacks per Attack action | Extra Attack (scales) |
| `grant_ally_reaction_attack` | Give an ally an attack using their reaction | Commander's Strike |
| `damage_reduction_reaction` | Reaction to reduce incoming damage by a value | Parry, Deflect Missiles, Uncanny Dodge |
| `counter_attack_on_miss` | Reaction attack when enemy misses you | Riposte |
| `cleave_splash` | Hit spreads to adjacent creature | Sweeping Attack |
| `reach_extension` | Temporarily extend weapon reach | Lunging Attack |
| `taunt_forced_focus` | Force enemy to attack you or suffer penalty | Goading Attack |
| `grant_ally_movement` | Allow ally to move using their reaction | Maneuvering Attack |
| `improved_save_outcome` | Upgrade save results by one step | Evasion |
| `minimum_roll` | Floor on d20 result for certain rolls | Reliable Talent |
| `action_economy_upgrade` | Use bonus action for normally action-costing things | Cunning Action, Patient Defense |
| `prerequisite_condition` | Ability only works if a condition is met | Sneak Attack (advantage or ally adjacent) |
| `healing_bonus_on_spell` | Flat bonus added when casting healing spells | Disciple of Life |
| `retaliatory_damage` | Reaction damage when you're hit | Wrath of the Storm, Halo of Spores |
| `maximize_damage` | Replace damage dice with maximum values | Destructive Wrath |
| `bonus_die_grant` | Give a creature a die to add to a future roll | Bardic Inspiration |
| `penalty_die_reaction` | Subtract a die from enemy roll as reaction | Cutting Words |
| `delayed_trigger_effect` | Set up effect now, trigger it later at will | Quivering Palm |
| `spell_modifier` | Metamagic-style modifications to spell properties | Twinned, Quickened, Heightened, etc. |
| `duplicate_targeting` | Add additional target to single-target spell | Twinned Spell |
| `cantrip_as_attack_replacement` | Replace one attack with a cantrip | Bladesinger Extra Attack |
| `expanded_opportunity_attack_trigger` | OA triggers on additional conditions | Polearm Master, Sentinel |
| `spell_as_opportunity_attack` | Cast spell instead of melee OA | War Caster |
| `chance_to_negate_hit` | Percentage chance to avoid being hit entirely | Armor of Hexes |
| `equipment_enchantment` | Temporarily make equipment magical | Blessing of the Forge |
| `heal_on_kill` | Regain HP when marked target dies | Hexblade's Curse |
| `target_mark` | Mark a creature for multiple stacking benefits | Hexblade's Curse, Hunter's Mark, Hex |
| `first_round_bonus` | Extra capabilities on first turn of combat | Dread Ambusher, Assassinate |
| `attack_on_miss` | Bonus attack when you miss | Stalker's Flurry |
| `attack_action_aoe` | Turn Attack action into area attack | Volley, Whirlwind Attack |
| `concentration_bonus` | Buff specifically while concentrating | Durable Magic |
| `destroy_below_cr` | Instant kill creatures below CR threshold | Destroy Undead |
| `in_form_healing` | Spend resources to heal while transformed | Combat Wild Shape (Moon) |
| `alternate_resource_use` | Use one resource for a completely different effect | Symbiotic Entity (Wild Shape → buff) |

---

## GRAND TOTAL: ALL PRIMITIVES

Combining spells (57 primitives) + class features (41 new primitives) = **~98 total primitives**

However, there's significant overlap. Many class feature primitives are special cases
of spell primitives. Here's how they collapse:

### Truly New Concepts from Class Features (~25 genuinely new)
1. `on_hit_rider` (generalized Smite system) — THE most important one
2. `automatic_on_hit_rider` (passive version)
3. `after_roll_before_result` decision timing
4. `pre_attack_trade_off` decision timing
5. `maintenance_condition` (Rage-style upkeep)
6. `self_debuff_as_cost` (Reckless Attack pattern)
7. `passive_conditional_buff` (always-on with prereqs)
8. `crit_bonus_dice` (Brutal Critical)
9. `death_prevention` (don't drop to 0)
10. `forced_reroll` (Indomitable/Lucky)
11. `extra_attack` scaling
12. `damage_reduction_reaction` (Parry/Uncanny Dodge)
13. `improved_save_outcome` (Evasion)
14. `minimum_roll` floor (Reliable Talent)
15. `action_economy_upgrade` (bonus action substitutions)
16. `prerequisite_condition` (Sneak Attack requirements)
17. `maximize_damage` (Destructive Wrath)
18. `bonus_die_grant` / `penalty_die_reaction` (Bardic Inspiration/Cutting Words)
19. `spell_modifier` system (Metamagic)
20. `target_mark` (stacking mark with multiple benefits)
21. `first_round_bonus` (surprise round extras)
22. `attack_action_aoe` (Volley/Whirlwind)
23. `retaliatory_damage` (reactive damage when hit)
24. `chance_to_negate_hit` (percentage miss chance)
25. `delayed_trigger_effect` (set up now, detonate later)

### Primitives That Collapse Into Existing Spell Primitives
- `ally_buff_aura` → already have aoe_anchor: caster_centered + stat_modification
- `condition_immunity_while_active` → already have condition primitives
- `grant_ally_reaction_attack` → variant of bonus_action_followup
- `counter_attack_on_miss` → variant of reaction_trigger
- `cleave_splash` → variant of chain_effect
- `healing_bonus_on_spell` → modifier on existing heal primitive
- `heal_on_kill` → variant of death_effect (but for caster)
- `equipment_enchantment` → variant of stat_modification on object
- `concentration_bonus` → conditional stat_modification
- `destroy_below_cr` → variant of hp_threshold
- `in_form_healing` → resource spending with heal_type

---

## THE SMITE SYSTEM REUSE MAP

Here's exactly which abilities your existing Smite popup can handle
with minimal modification:

### Direct Reuse (identical trigger pattern: hit → popup → spend resource → effect)
| Ability | Resource | Effect |
|---|---|---|
| Divine Smite | Spell slot | 2d8+ radiant |
| Eldritch Smite | Warlock slot | 1d8+ force + prone |
| Stunning Strike | 1 Ki | CON save or stunned |
| All Smite spells* | (pre-cast) | Varies |
| Battlemaster: Menacing Attack | 1 sup die | +die damage + frightened |
| Battlemaster: Trip Attack | 1 sup die | +die damage + prone |
| Battlemaster: Pushing Attack | 1 sup die | +die damage + push 15ft |
| Battlemaster: Disarming Attack | 1 sup die | +die damage + disarm |
| Battlemaster: Distracting Strike | 1 sup die | +die damage + ally advantage |
| Battlemaster: Goading Attack | 1 sup die | +die damage + taunt |
| Battlemaster: Maneuvering Attack | 1 sup die | +die damage + ally move |
| Open Hand: Flurry options | (free) | prone/push/no reactions |

*Smite spells trigger slightly differently (pre-cast concentration, then trigger on next hit)
but the popup moment is the same.

### Needs "Automatic" Mode (no popup, always applies)
| Ability | Condition | Effect |
|---|---|---|
| Improved Divine Smite | Every melee hit | +1d8 radiant |
| Colossus Slayer | Target below max HP | +1d8 (1/turn) |
| Sneak Attack | Advantage or ally adj. | +NdX (1/turn) |
| Repelling Blast | Every EB hit | Push 10ft |
| Agonizing Blast | Every EB hit | +CHA damage |

### Needs "Before Attack" Mode (declared before rolling)
| Ability | Trade-off |
|---|---|
| Great Weapon Master | -5 attack / +10 damage |
| Sharpshooter | -5 attack / +10 damage |
| Reckless Attack | Advantage on attacks / enemies get advantage on you |

### Needs "After Roll, Before Result" Mode
| Ability | Effect |
|---|---|
| Bardic Inspiration | +die to roll |
| Precision Attack | +sup die to attack roll |
| Guided Strike | +10 to attack roll |
| Cutting Words | -die from enemy roll |
| Lucky | Additional d20, choose which |

---

## IMPLEMENTATION RECOMMENDATION: THE UNIFIED RIDER SYSTEM

Instead of "the Smite system," you could build a **Unified Rider System** with 4 trigger modes:

```
Mode 1: PRE_ATTACK
  When: Before the attack roll
  Examples: GWM, Sharpshooter, Reckless Attack
  UI: Checkbox/toggle before rolling

Mode 2: POST_ROLL_PRE_RESULT
  When: After rolling, before confirming hit/miss
  Examples: Bardic Inspiration, Precision Attack, Lucky
  UI: Popup showing the roll, "Add bonus?" option

Mode 3: POST_HIT
  When: After confirming a hit, before damage
  Examples: Divine Smite, Stunning Strike, all Battlemaster maneuvers
  UI: Your existing Smite popup!

Mode 4: AUTOMATIC
  When: Always applies (passive, no decision needed)
  Examples: Improved Divine Smite, Sneak Attack, Colossus Slayer
  UI: Auto-calculated, shown in damage breakdown
```

Each rider has:
- Trigger mode (1-4)
- Cost (resource type + amount, or none)
- Frequency (per hit, once per turn, per rest, unlimited)
- Prerequisites (if any)
- Effects (damage bonus, condition, forced movement, etc.)
- Target (creature you hit, self, ally, etc.)

This single system replaces your Smite popup AND covers ~40% of all class features.

---

## AUDIT RESULTS (v0.13.1)

Audit performed against dnd_combat_sim v0.13.1. This document introduces the most architecturally significant gap: the **on-hit rider pattern** that affects ~40 class features. This audit covers the rider system, per-class feature buildability, and the 41 new primitives.

### Current Smite System Architecture

Before assessing class features, it's important to understand where the Smite system stands today:

| Component | Generic? | Details |
|---|---|---|
| `resolve_attack_damage(bonus_damage)` | **YES** | Accepts `list[DamageRoll]` — any damage type, any dice. Fully generic. |
| `CombatManager.complete_attack(hit_result, bonus_damage)` | **YES** | Passes bonus_damage straight through. Generic. |
| `AttackHitResult` dataclass | **YES** | Stores hit/crit/roll/context. No Smite-specific fields. |
| `SmitePopup` UI | **NO** | Hardcoded title "Divine Smite?", hardcoded `min(1+slot_level, 5)` d8 formula, hardcoded RADIANT type. |
| GUI eligibility check (`_can_smite`) | **NO** | Checks `f.name.lower() == "divine smite"` — literal string match. |
| Resource deduction (`_resolve_smite`) | **NO** | Hardcoded `spell_slot_{level}` pattern, hardcoded dice formula. |
| Feature/Feat model fields | **NO** | Only passive bonuses (bonus_ac, bonus_speed, etc.). No `on_hit_riders` field. |
| AI planning | **NO** | No AI logic for choosing when to Smite. |

**Key insight**: The combat engine is already 90% generic. The bottleneck is (1) the GUI layer's hardcoded Divine Smite wiring and (2) no data model for defining riders on Features/Feats.

### The On-Hit Rider Pattern — Audit

The document identifies **4 trigger modes** for the Unified Rider System. Current support:

| Mode | Status | Implementation Notes |
|---|---|---|
| **Mode 1: PRE_ATTACK** (before rolling) | **NOT SUPPORTED** | GWM/Sharpshooter -5/+10 trade-off. No pre-attack decision point in the attack flow. |
| **Mode 2: POST_ROLL_PRE_RESULT** (after roll, before hit/miss) | **NOT SUPPORTED** | Bardic Inspiration, Precision Attack, Guided Strike. No decision point between roll and result. |
| **Mode 3: POST_HIT** (after hit, before damage) | **HARDCODED** | Divine Smite only. The two-phase attack system (`resolve_attack_hit` → `SmitePopup` → `resolve_attack_damage`) works perfectly for this mode but is wired exclusively to Divine Smite via string matching. |
| **Mode 4: AUTOMATIC** (passive, always applies) | **NOT SUPPORTED** | Improved Divine Smite, Sneak Attack, Colossus Slayer. No passive on-hit rider fields on Feature/Feat models. |

**Abilities affected by Mode 3 (POST_HIT) — could reuse existing Smite architecture if generalized:**
- Divine Smite (currently works)
- Eldritch Smite
- Stunning Strike
- All Battlemaster on-hit maneuvers (Menacing, Trip, Pushing, Disarming, Distracting, Goading, Maneuvering, Sweeping Attack)
- Open Hand Techniques (Flurry options)

**Abilities affected by Mode 4 (AUTOMATIC) — need new data model field:**
- Improved Divine Smite (+1d8 radiant every melee hit)
- Colossus Slayer (+1d8 when target below max HP)
- Sneak Attack (+NdX once per turn with prerequisites)
- Repelling Blast (push 10ft per beam)
- Agonizing Blast (+CHA to each beam)

### Per-Class Feature Buildability

#### Barbarian

| Feature | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Rage | **NOT BUILDABLE** | Bonus action activation, resource cost via class_resources. | Buff system needed: +2 melee damage, advantage on STR checks/saves, bludg/pierc/slash resistance. Maintenance condition ("must attack or take damage"). Restriction ("can't cast spells"). |
| Reckless Attack | **NOT BUILDABLE** | None. | Pre-attack trade-off pattern, self-debuff-as-cost (enemies get advantage). |
| Danger Sense | **PARTIAL** | Feature model has no conditional advantage field. But the Feature model does have `grants_saving_throw_proficiencies`. | Conditional advantage on DEX saves (not when blinded/deafened/incapacitated) is distinct from proficiency. No conditional advantage. |
| Brutal Critical | **NOT SUPPORTED** | No crit_bonus_dice field. |
| Relentless Rage | **NOT SUPPORTED** | No death_prevention mechanic. |
| Bear Totem | **NOT BUILDABLE** | `grants_damage_resistances` on Feature model covers listing resistance types, but only as permanent passive — not while-raging conditional. | Needs "resistance while Rage is active" — conditional buff. |
| Wolf Totem | **NOT BUILDABLE** | None. | Ally buff aura (grant advantage to nearby allies' melee attacks). |

#### Fighter

| Feature | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Second Wind | **SUPPORTED** | `Action(action_type=BONUS_ACTION, target_type=SELF, healing="1d10+X", resource_cost={"second_wind": 1}, uses_per_rest=1, rest_type="short")`. All fields exist. | Healing bonus should scale with fighter level (user must update manually). |
| Action Surge | **NOT SUPPORTED** | No grants_extra_action mechanic. |
| Indomitable | **NOT SUPPORTED** | No forced_reroll mechanic. |
| Extra Attack | **NOT SUPPORTED** | Multiattack is modeled as multiple separate Attack actions on creatures, not as an "attacks per Attack action" system. No extra_attack primitive. |
| Battlemaster Maneuvers | **NOT BUILDABLE** | The forced_movement and conditions_applied fields on Action cover the *effects* of some maneuvers (Trip → prone, Pushing → push 15ft, Menacing → frightened). | But the *trigger* (on-hit rider), *resource* (superiority die scaling d8→d10→d12), and *decision point* (after hit confirmed) are all missing. Need generalized rider system. |
| Champion: Improved Critical | **NOT SUPPORTED** | No crit_range field. Hardcoded natural 20 only. |
| Eldritch Knight: War Magic | **NOT SUPPORTED** | No combo enabler (cantrip → bonus action attack). |

#### Rogue

| Feature | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Sneak Attack | **NOT BUILDABLE** | Damage dice and type could be expressed. | On-hit rider (automatic, once per turn), prerequisite condition (advantage OR ally within 5ft), weapon restriction (finesse/ranged). All missing. |
| Cunning Action | **NOT BUILDABLE** | None. | Action economy upgrade (Dash/Disengage/Hide as bonus action). |
| Uncanny Dodge | **NOT SUPPORTED** | No damage_halving_reaction. |
| Evasion | **NOT SUPPORTED** | No improved_save_outcome. DEX saves yield no damage on success, half on fail — not modellable. |
| Reliable Talent | **NOT SUPPORTED** | No minimum_roll floor. |
| Assassinate | **NOT SUPPORTED** | No first_round_bonus, no auto_crit_condition. |

#### Paladin

| Feature | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Divine Smite | **SUPPORTED** (hardcoded) | SmitePopup + two-phase attack + bonus_damage. Works end-to-end for this specific ability. | Not generalizable to other riders without refactoring. |
| Smite Spells | **NOT BUILDABLE** | Bonus action casting and concentration work. | "On next weapon hit" trigger doesn't exist. Smite spells are concentration buffs that consume on hit — a trigger mode not supported. |
| Lay on Hands | **NOT BUILDABLE** | Healing field works. | Distributable resource pool spending (spend variable HP from pool). Different from fixed resource_cost. |
| Aura of Protection | **NOT BUILDABLE** | None. | Passive aura buff (+CHA to all saves for nearby allies). Needs aura + buff system. |
| Aura of Courage | **PARTIAL** | `Feature.grants_condition_immunities: ["frightened"]` exists as passive field. | But this is permanent, not aura-based. Allies in range don't benefit. |
| Improved Divine Smite | **NOT BUILDABLE** | None. | Automatic on-hit rider (+1d8 radiant, no cost, every melee hit). No passive on-hit field. |
| Vow of Enmity | **NOT BUILDABLE** | Bonus action + resource cost work. | Single-target advantage buff (advantage on attacks against one creature). Needs buff system. |

#### Monk

| Feature | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Ki system | **SUPPORTED** | `class_resources: {"ki_points": N}` + `resource_cost: {"ki_points": 1}` on actions. Fully working. |
| Stunning Strike | **NOT BUILDABLE** | The effect (CON save → stunned) could be expressed. | On-hit rider trigger + ki cost at decision point is missing. Would need generalized Smite system. |
| Flurry of Blows | **PARTIAL** | Could model as bonus action attack with ki cost. | But it's an *upgraded* bonus action (two attacks instead of one), and is only valid after Attack action. |
| Patient Defense / Step of the Wind | **PARTIAL** | Bonus action + ki cost works. | The underlying Dodge/Disengage/Dash actions aren't formally modeled as bonus-action-eligible. |
| Deflect Missiles | **NOT SUPPORTED** | No damage_reduction_reaction. |
| Evasion | **NOT SUPPORTED** | Same as Rogue. |
| Open Hand Techniques | **NOT BUILDABLE** | Prone and push effects exist as Action fields. | On-hit effect choice menu triggered by Flurry of Blows hits specifically. |

#### Ranger

| Feature | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Colossus Slayer | **NOT BUILDABLE** | None. | Automatic on-hit rider with prerequisite (target below max HP), once per turn. |
| Giant Killer | **NOT SUPPORTED** | No reaction-attack-on-being-attacked trigger. |
| Horde Breaker | **NOT SUPPORTED** | No bonus-attack-vs-adjacent mechanic. |
| Dread Ambusher | **NOT SUPPORTED** | No first_round_bonus. Speed buff + extra attack on first turn. |

#### Warlock

| Feature | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Agonizing Blast | **NOT BUILDABLE** | None. | Cantrip modifier (add CHA to EB damage). Automatic on-hit rider on a specific cantrip. |
| Repelling Blast | **NOT BUILDABLE** | Push forced_movement exists, but only on the Action, not as an on-hit rider modifier. | Cantrip modifier that adds push effect per beam hit. |
| Eldritch Smite | **NOT BUILDABLE** | Would work identically to Divine Smite if the rider system were generalized. | Currently hardcoded to Divine Smite only. |
| Hexblade's Curse | **NOT BUILDABLE** | Bonus action + resource cost works. | Target mark with: +prof damage, crit range 19-20, heal on kill. All missing. |

#### Cleric

| Feature | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Turn Undead | **PARTIAL** | AoE sphere + WIS save + frightened condition. Buildable as a standard save action. | Creature type restriction (undead only), Destroy Undead (instant kill below CR threshold). |
| Disciple of Life | **NOT SUPPORTED** | No healing_bonus_on_spell modifier. |
| Guided Strike | **NOT SUPPORTED** | No after-roll-before-result decision point. |
| Wrath of the Storm | **NOT SUPPORTED** | No retaliatory_damage reaction. |
| Destructive Wrath | **NOT SUPPORTED** | No maximize_damage mechanic. |
| Twilight Sanctuary | **NOT BUILDABLE** | Zone-like aura concept exists. | End-of-turn temp HP grant per ally + effect choice. Needs aura buff system. |

#### Druid

| Feature | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Wild Shape | **SUPPORTED** | `Action(summon_creature="beasts/wolf.json", is_wild_shape=True)`. Full creature swap with HP overflow on revert. Working system. |
| Moon: Combat Wild Shape | **PARTIAL** | Wild Shape works. | In-form healing (spend spell slots as bonus action while transformed) missing. |
| Spores: Halo of Spores | **NOT SUPPORTED** | No proximity_reaction_damage. |
| Spores: Symbiotic Entity | **NOT BUILDABLE** | Temp HP field exists (`grants_temporary_hp`). | Alternate resource use (Wild Shape charge → buff), melee damage rider (+1d6 poison). |

#### Sorcerer — Metamagic

| Feature | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Careful Spell | **NOT SUPPORTED** | No selective_targeting in AoE. |
| Distant Spell | **NOT SUPPORTED** | No range_modification on cast. |
| Empowered Spell | **NOT SUPPORTED** | No damage_reroll. |
| Extended Spell | **NOT SUPPORTED** | No duration_modification. |
| Heightened Spell | **NOT SUPPORTED** | No impose_save_disadvantage. |
| Quickened Spell | **NOT SUPPORTED** | No action_economy_modification. |
| Subtle Spell | **NOT SUPPORTED** | No component system to bypass. |
| Twinned Spell | **NOT SUPPORTED** | No duplicate_targeting. |

**Metamagic is 0/8 supported.** The entire spell_modifier system is new architecture.

#### Wizard

| Feature | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Sculpt Spells | **NOT SUPPORTED** | No selective_targeting (auto-succeed for chosen allies). |
| Potent Cantrip | **NOT SUPPORTED** | No improved_cantrip_save (half on success instead of none). |
| Bladesong | **NOT BUILDABLE** | None. | Buff system: +INT to AC, +10 speed, +INT to concentration checks. |
| War Magic: Arcane Deflection | **NOT SUPPORTED** | No defensive_reaction with restriction. |

#### Bard

| Feature | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Bardic Inspiration | **NOT BUILDABLE** | Resource cost (CHA mod per rest) works. | bonus_die_grant: give ally a die for a future roll. Entirely new system — grant a deferred bonus die, recipient chooses when to use it, after_roll_before_result timing. |
| Cutting Words | **NOT SUPPORTED** | No penalty_die_reaction (subtract die from enemy roll). |

#### Feats

| Feat | Buildability | What Works | What Doesn't |
|---|---|---|---|
| Great Weapon Master | **NOT BUILDABLE** | None. | Pre-attack trade-off (-5/+10), bonus action attack on crit/kill. |
| Sharpshooter | **NOT BUILDABLE** | None. | Same -5/+10 pattern, cover_interaction: ignore_cover. |
| Polearm Master | **NOT BUILDABLE** | None. | Bonus action butt-end attack after Attack action, expanded OA trigger (enter reach). |
| Sentinel | **NOT BUILDABLE** | None. | Speed=0 on OA hit, OA despite Disengage, reaction attack when ally is targeted. |
| War Caster | **NOT BUILDABLE** | Advantage on concentration saves could maybe be modeled. | Spell-as-OA, somatic-with-hands-full (needs component system). |
| Lucky | **NOT SUPPORTED** | No extra_d20_choice. |
| Alert | **PARTIAL** | `Feat.bonus_initiative: 5` works for the +5 initiative. | Surprise immunity and hidden attack immunity not modellable. |
| Resilient | **SUPPORTED** | `Feat.bonus_ability_scores` + `grants_saving_throw_proficiencies` cover both effects. |
| Tough | **PARTIAL** | No "+2 HP per level" field. User can manually increase max HP. |

### New Primitives from Class Features — Audit

| Primitive | Status | Implementation Notes |
|---|---|---|
| `on_hit_rider` (generalized) | **HARDCODED** | Divine Smite only. Two-phase attack + bonus_damage is generic. GUI/model is not. Affects ~15 abilities directly. |
| `automatic_on_hit_rider` | **NOT SUPPORTED** | No passive on-hit damage/effect field on Feature/Feat. Affects ~8 abilities. |
| `pre_attack_trade_off` | **NOT SUPPORTED** | No pre-attack decision point. GWM, Sharpshooter. |
| `after_roll_before_result` | **NOT SUPPORTED** | No post-roll decision point. Bardic Inspiration, Precision Attack, Lucky. |
| `maintenance_condition` | **NOT SUPPORTED** | Rage-style "must attack each turn or ability ends." |
| `self_debuff_as_cost` | **NOT SUPPORTED** | Reckless Attack pattern. |
| `passive_conditional_buff` | **NOT SUPPORTED** | Always-on bonus with prerequisite. Danger Sense, Reliable Talent. |
| `crit_bonus_dice` | **NOT SUPPORTED** | Brutal Critical, Half-Orc Savage Attacks. |
| `death_prevention` | **NOT SUPPORTED** | Relentless Rage (CON save to stay at 1 HP). |
| `ally_buff_aura` | **NOT SUPPORTED** | Aura of Protection, Wolf Totem. Needs aura + buff system combined. |
| `condition_immunity_while_active` | **PARTIAL** | `Feature.grants_condition_immunities` works for permanent immunity. But "immune only while raging" is conditional — not modellable. |
| `forced_reroll` | **NOT SUPPORTED** | Indomitable, Diamond Soul, Lucky. No reroll mechanic. |
| `extra_attack` | **NOT SUPPORTED** | No "attacks per Attack action" system. |
| `grant_ally_reaction_attack` | **NOT SUPPORTED** | Commander's Strike. |
| `damage_reduction_reaction` | **NOT SUPPORTED** | Parry, Deflect Missiles, Uncanny Dodge. |
| `counter_attack_on_miss` | **NOT SUPPORTED** | Riposte. |
| `cleave_splash` | **NOT SUPPORTED** | Sweeping Attack. |
| `reach_extension` | **NOT SUPPORTED** | Lunging Attack. |
| `taunt_forced_focus` | **NOT SUPPORTED** | Goading Attack. |
| `grant_ally_movement` | **NOT SUPPORTED** | Maneuvering Attack. |
| `improved_save_outcome` | **NOT SUPPORTED** | Evasion (both Rogue and Monk). |
| `minimum_roll` | **NOT SUPPORTED** | Reliable Talent. |
| `action_economy_upgrade` | **NOT SUPPORTED** | Cunning Action, Patient Defense. |
| `prerequisite_condition` | **NOT SUPPORTED** | Sneak Attack requirements. |
| `healing_bonus_on_spell` | **NOT SUPPORTED** | Disciple of Life. |
| `retaliatory_damage` | **NOT SUPPORTED** | Wrath of the Storm, Halo of Spores. |
| `maximize_damage` | **NOT SUPPORTED** | Destructive Wrath. |
| `bonus_die_grant` | **NOT SUPPORTED** | Bardic Inspiration. |
| `penalty_die_reaction` | **NOT SUPPORTED** | Cutting Words. |
| `delayed_trigger_effect` | **NOT SUPPORTED** | Quivering Palm. |
| `spell_modifier` | **NOT SUPPORTED** | All 8 Metamagic options. Entirely new system. |
| `duplicate_targeting` | **NOT SUPPORTED** | Twinned Spell. |
| `cantrip_as_attack_replacement` | **NOT SUPPORTED** | Bladesinger Extra Attack. |
| `expanded_opportunity_attack_trigger` | **NOT SUPPORTED** | Polearm Master, Sentinel. |
| `spell_as_opportunity_attack` | **NOT SUPPORTED** | War Caster. |
| `chance_to_negate_hit` | **NOT SUPPORTED** | Armor of Hexes. |
| `equipment_enchantment` | **NOT SUPPORTED** | Blessing of the Forge. |
| `heal_on_kill` | **NOT SUPPORTED** | Hexblade's Curse. |
| `target_mark` | **NOT SUPPORTED** | Hexblade's Curse, Hunter's Mark pattern. |
| `first_round_bonus` | **NOT SUPPORTED** | Dread Ambusher, Assassinate. |
| `attack_on_miss` | **NOT SUPPORTED** | Stalker's Flurry. |
| `attack_action_aoe` | **NOT SUPPORTED** | Volley, Whirlwind Attack. |
| `concentration_bonus` | **NOT SUPPORTED** | Durable Magic. |
| `destroy_below_cr` | **NOT SUPPORTED** | Destroy Undead. |
| `in_form_healing` | **NOT SUPPORTED** | Moon Druid Combat Wild Shape. |
| `alternate_resource_use` | **NOT SUPPORTED** | Symbiotic Entity. |

### Features That ARE Buildable Today

Despite the large gap list, several features work right now:

| Feature | How It's Built |
|---|---|
| **Divine Smite** | Hardcoded SmitePopup system. Works end-to-end. |
| **Wild Shape** | `Action(summon_creature="...", is_wild_shape=True)`. Full creature swap with HP overflow. |
| **Second Wind** | `Action(action_type=BONUS_ACTION, target_type=SELF, healing="1d10+5", resource_cost={"second_wind": 1})` |
| **Ki/Superiority/Channel Divinity costs** | `class_resources` + `resource_cost` dict on Actions. All named resource pools work. |
| **Patient Defense** (partial) | `Action(action_type=BONUS_ACTION, conditions_applied=["dodging"], resource_cost={"ki_points": 1})` |
| **Resilient feat** | `Feat(bonus_ability_scores={"constitution": 1}, grants_saving_throw_proficiencies=["constitution"])` |
| **Alert feat** (partial) | `Feat(bonus_initiative=5)` |
| **Passive resistances/immunities** | `Feature(grants_damage_resistances=["fire"], grants_condition_immunities=["poisoned"])` |
| **Turn Undead** (partial) | AoE sphere + WIS save + frightened condition. Works as standard save action. |
| **Stillness of Mind** | `Action(action_type=ACTION, target_type=SELF, conditions_removed=["charmed", "frightened"])` |
| **Temp HP granting** (Rally) | `Action(target_type=ONE_ALLY, grants_temporary_hp="1d8+3", resource_cost={"superiority_die": 1})` |

### Buildability Summary

| Rating | Count | Examples |
|---|---|---|
| **SUPPORTED** | ~11 | Divine Smite, Wild Shape, Second Wind, Ki system, resource costs, passive resistances/immunities, Alert initiative, Resilient, Stillness of Mind, Rally temp HP, Patient Defense (partial) |
| **PARTIAL** | ~5 | Danger Sense (passive field exists but not conditional), Turn Undead (AoE+save works but not creature-type-restricted), Moon Wild Shape (base works, in-form healing doesn't), Flurry (bonus action + ki cost works, double attack doesn't) |
| **NOT BUILDABLE** | ~80+ | Everything requiring: on-hit riders, buff/debuff system, reaction triggers, pre/post-attack decisions, aura buffs, metamagic, passive advantages, damage reduction, rerolls, Extra Attack |

### The Document's Key Recommendation — Assessed

The Unified Rider System (4 trigger modes) is the single highest-leverage feature the project could build. Here's why:

**Current architecture advantage**: `resolve_attack_damage(bonus_damage: list[DamageRoll])` is already completely generic. The two-phase attack split (`resolve_attack_hit` → popup → `resolve_attack_damage`) is the right architecture. The only work needed is:

1. **Data model**: Add `on_hit_riders: list[OnHitRider]` to Feature/Feat/Action model
2. **UI generalization**: Parameterize SmitePopup → `OnHitRiderPopup(title, resource_options, dice_formula, damage_type, effects)`
3. **Eligibility lookup**: Replace `_can_smite()` string check with generic rider lookup across features/feats
4. **Automatic riders**: Add passive on-hit processing in `resolve_attack_damage` for Mode 4 (no popup needed)

This single system would unlock: Divine Smite (already works), Eldritch Smite, Stunning Strike, all 16 Battlemaster Maneuvers, Sneak Attack, Colossus Slayer, Improved Divine Smite, Agonizing/Repelling Blast, Open Hand Techniques — roughly **30-40 class features**.

### TOP 5 HIGHEST-IMPACT GAPS (Class Features)

1. **Generalized On-Hit Rider System** — ~40 class features across 6+ classes. The infrastructure is 90% there (two-phase attack + generic bonus_damage). Needs: data model fields, parameterized popup, automatic rider processing. **Highest leverage single feature.**

2. **Buff/Debuff System** (repeat from spell audit) — Rage (+damage, advantage, resistance), Bladesong (+INT to AC/speed), Aura of Protection (+CHA to saves), Hexblade's Curse, Reckless Attack, and many more. This gap blocks nearly every "activate ability for duration" class feature.

3. **Reaction Trigger System** — Uncanny Dodge, Parry, Deflect Missiles, Riposte, Wrath of the Storm, Shield, Counterspell, Cutting Words. Reactions exist as an action type but have no configurable trigger conditions or specialized resolution (damage halving, counter-attack, bonus die subtraction).

4. **Extra Attack / Multi-Attack Scaling** — Extra Attack (Fighter/Paladin/Ranger/Monk), Flurry of Blows, Action Surge, Haste extra action. The "attacks per Attack action" concept doesn't exist — multiattack is modeled as separate Actions on a creature.

5. **Metamagic / Spell Modifier System** — All 8 Sorcerer Metamagic options (0/8 supported). Entirely new architecture: modifiers applied at cast time that change spell properties (range, duration, action economy, targeting). Also needed for Eldritch Invocations that modify Eldritch Blast.

---

## PHASE 2: UI EXPOSURE AUDIT (v0.13.1)

> **Audit date**: 2026-02-25
> **Scope**: Can users configure class features through the Character Builder?
> **Reference**: See Document 1 Phase 2 for full Actions Tab widget inventory.

### How Class Features Map to Builder Tabs

Class features span TWO builder tabs:

| Feature Type | Builder Location | Examples |
|-------------|-----------------|----------|
| **Passive bonuses** | Features Tab → Feature editor | Unarmored Defense, Improved Critical, Aura of Protection |
| **Active abilities** | Actions Tab → Action editor | Second Wind, Action Surge, Lay on Hands, Wild Shape |
| **Resource pools** | Features Tab → Class Resources | Ki Points, Sorcery Points, Bardic Inspiration dice |
| **On-hit riders** | ❌ No dedicated location | Divine Smite (hardcoded), Sneak Attack, Maneuvers |
| **Passive toggles** | ❌ No dedicated location | Rage, Bladesong, Reckless Attack |
| **Reactions** | Actions Tab → Reactions category | Exists as category, but no trigger config |

### Features Tab — Passive Bonus Widgets

The Feature editor exposes these fields per feature:

| Widget | Type | Range | Maps To |
|--------|------|-------|---------|
| Name | Text input | — | Feature.name |
| Description | Text input | 120 chars | Feature.description |
| Source | Text input | — | Feature.source |
| Bonus AC | Spinner | -5 to +10 | Feature.bonus_ac |
| Bonus Speed | Spinner | -30 to +60, step 5 | Feature.bonus_speed |
| Bonus Initiative | Spinner | -5 to +10 | Feature.bonus_initiative |
| Ability Score Bonuses | 6 spinners | -4 to +4 each | Feature.bonus_ability_scores |
| Unarmored Defense | Dropdown | none/monk/barbarian | Feature.unarmored_defense |
| Damage Resistances | ListEditor | 13 damage types | Feature.grants_damage_resistances |
| Damage Immunities | ListEditor | 13 damage types | Feature.grants_damage_immunities |
| Condition Immunities | ListEditor | 15 conditions | Feature.grants_condition_immunities |
| Save Proficiencies | ListEditor | 6 abilities | Feature.grants_saving_throw_proficiencies |

**Plus**: Class Resources (name + value pairs), Spell Slots (1-9 level spinners), Spellcasting Ability, Feats (42 PHB feats with auto-populated data).

### Per-Class Feature Buildability Through UI

#### Barbarian
| Feature | UI Buildable? | How | Missing |
|---------|--------------|-----|---------|
| Rage | ❌ No | — | No buff/debuff toggle system. Would need: activate action → apply temp stat changes + damage resistance |
| Unarmored Defense | ✅ Yes | Features Tab → Unarmored Defense = "barbarian" | — |
| Reckless Attack | ❌ No | — | No "grant advantage on attacks this turn + enemies get advantage on you" toggle |
| Danger Sense | ❌ No | — | No advantage-on-specific-saves mechanic |
| Extra Attack | ❌ No | — | No attacks-per-action concept |
| Brutal Critical | ❌ No | — | No extra crit dice mechanic |
| Relentless Rage | ❌ No | — | No death-prevention mechanic |

#### Fighter
| Feature | UI Buildable? | How | Missing |
|---------|--------------|-----|---------|
| Second Wind | ✅ Yes | Actions Tab → bonus action + healing dice + uses_per_rest | — |
| Action Surge | ❌ No | — | No "gain extra action" mechanic |
| Extra Attack (1-3) | ❌ No | — | No attacks-per-action concept |
| Indomitable | ❌ No | — | No save-reroll mechanic |
| **Battlemaster Maneuvers** | ❌ No | — | No on-hit rider system. Would need: trigger on hit → spend superiority die → roll + apply effect |
| Champion Improved Critical | ❌ No | — | No crit_range field. Feature.bonus fields don't include crit modification |

#### Rogue
| Feature | UI Buildable? | How | Missing |
|---------|--------------|-----|---------|
| Sneak Attack | ❌ No | — | No automatic on-hit rider (advantage or ally-adjacent trigger + extra dice) |
| Cunning Action | ⚠️ Partial | Can create Dash/Disengage as bonus actions | No Hide action integration |
| Uncanny Dodge | ❌ No | — | No reaction trigger + damage halving |
| Evasion | ❌ No | — | No "DEX save: success=0 damage, fail=half" passive |

#### Paladin
| Feature | UI Buildable? | How | Missing |
|---------|--------------|-----|---------|
| Divine Smite | ⚠️ Hardcoded | Works in combat via SmitePopup, but user can't create NEW smite-like abilities | Generalized rider system needed |
| Lay on Hands | ✅ Yes | Actions Tab → action + healing + resource_cost (lay_on_hands pool) | — |
| Aura of Protection | ❌ No | — | No aura/buff system (CHA mod to all saves within 10ft) |
| Divine Sense | ❌ No | — | No detection/reveal mechanic |
| Extra Attack | ❌ No | — | No attacks-per-action concept |

#### Monk
| Feature | UI Buildable? | How | Missing |
|---------|--------------|-----|---------|
| Martial Arts (bonus unarmed) | ⚠️ Partial | Can create bonus action attack, but no conditional trigger | No "if you took Attack action" condition |
| Ki system | ✅ Yes | Class Resources → ki_points + action resource_cost | — |
| Flurry of Blows | ⚠️ Partial | Bonus action + 2 unarmed attacks as one action, costs 1 ki | No "2 attacks in one action" |
| Stunning Strike | ❌ No | — | No on-hit rider (spend ki → target makes CON save or stunned) |
| Unarmored Defense | ✅ Yes | Features Tab → Unarmored Defense = "monk" | — |
| Unarmored Movement | ✅ Yes | Features Tab → bonus_speed = +10 (scaling per level not supported) | Level-scaling missing |

#### Cleric/Druid/Wizard/Sorcerer/Warlock/Bard/Ranger
| Feature | UI Buildable? | How | Missing |
|---------|--------------|-----|---------|
| Spellcasting | ✅ Yes | Features Tab → spell ability + slots. Actions Tab → individual spells | Each spell still needs manual creation |
| Wild Shape | ✅ Yes | Actions Tab → summon_creature + is_wild_shape + uses_per_rest | — |
| Channel Divinity | ⚠️ Partial | Can create as action with uses_per_rest | Specific channel options need individual actions |
| Metamagic (Sorcerer) | ❌ No | — | No spell-modifier system |
| Eldritch Invocations | ❌ No | — | Most are passive spell modifications |
| Bardic Inspiration | ❌ No | — | No "grant ally a die to add to future roll" mechanic |

### Phase 2 Scorecard (Class Features)

| Category | Count | Status |
|----------|-------|--------|
| **Fully buildable via UI** | ~8 | Second Wind, Lay on Hands, Ki system, Wild Shape, Unarmored Defense (monk/barb), basic Channel Divinity, Spellcasting setup |
| **Partially buildable** | ~6 | Divine Smite (hardcoded only), Cunning Action, Martial Arts, Flurry of Blows, Unarmored Movement (no level scaling), Channel Divinity variants |
| **NOT buildable** | ~80+ | Everything requiring: riders, buffs, reactions, extra attacks, metamagic, save rerolls, auras, death prevention, crit modification |

### Key Phase 2 Findings for Class Features

**1. The Features Tab passive bonuses are comprehensive for what they cover.**
AC, speed, initiative, ability scores, resistances, immunities, condition immunities, save proficiencies, and unarmored defense are all exposed. For purely passive features (e.g., "your base AC is 13 + DEX"), the UI works well.

**2. Active abilities map cleanly to the Actions Tab when the engine supports them.**
Second Wind (bonus action + healing + resource cost), Lay on Hands (action + healing + resource cost), Wild Shape (action + summon + is_wild_shape) — these are all fully buildable because they use engine primitives that are exposed in the UI.

**3. The on-hit rider gap is the single biggest UI blocker for class features.**
There is literally nowhere in the UI to configure: "when you hit with a weapon attack, spend X resource to add Y damage dice of Z type." The SmitePopup is hardcoded to Divine Smite only. A generalized rider editor (in Features Tab or a new sub-panel of Actions Tab) would unlock ~40 class features.

**4. No UI for "toggle on/off" abilities.**
Rage, Bladesong, Reckless Attack, Patient Defense — features that the player activates and that modify their stats or behavior for a duration. These need both engine support (buff/debuff system) AND a UI for configuring what the toggle does.

**5. Reaction triggers have a category but no configuration.**
The Actions Tab has a "Reactions" category, so users CAN create a reaction-type action. But there's no way to specify WHEN it triggers (on being hit, on ally being hit, on enemy casting spell, etc.) or what special resolution it uses (halve damage, counter-spell, etc.).

### Combined Phase 2 Easy Wins (Class Features)

1. **On-Hit Rider Editor** (HIGH PRIORITY, needs engine work too): Add rider configuration to Feature model with: trigger_mode (automatic/post_hit/pre_attack), resource_cost, damage_dice, damage_type, save_ability, save_dc, condition_on_hit. Add UI panel in Features Tab or Actions Tab. This unlocks 30-40 features.

2. **Condition Duration Params** (HIGH PRIORITY, UI-only): Same finding as Document 1 — conditions applied by class features (Stunning Strike's Stunned, Battlemaster's Frightened) need configurable duration. Currently all conditions default to indefinite.

3. **Crit Range Field on Feature** (LOW PRIORITY, engine + UI): Add `bonus_crit_range: int = 0` to Feature model and a spinner in Features Tab. Handles Champion's Improved Critical (19-20) and Superior Critical (18-20).

### COMBINED PHASE 1+2 SUMMARY: What Can Users Actually Build Today?

**Spells they CAN build (end-to-end, no workarounds needed):**
- Simple attack cantrips (Fire Bolt, Eldritch Blast without invocations, Ray of Frost)
- Basic AoE save spells (Fireball, Thunderwave, Shatter, Cone of Cold)
- Single-target save spells (Inflict Wounds via save, Sacred Flame)
- Healing spells (Cure Wounds, Healing Word, Heal)
- Temp HP grants (Heroism's temp HP, False Life)
- Concentration AoE zones (Spirit Guardians, Moonbeam, Cloud of Kill)
- Teleportation (Misty Step, Thunder Step, Dimension Door)
- Forced movement effects (Thunderwave push, Eldritch Blast + Repelling Blast)
- Terrain modification (Wall of Stone, Spike Growth, Plant Growth)
- Summons and Wild Shape (Conjure Animals, Wild Shape)
- Condition-applying attacks/saves (basic — no duration config)
- Condition removal (Lesser/Greater Restoration)

**Spells they CANNOT build:**
- Anything with buff/debuff (Shield, Bless, Bane, Haste, Slow, Hex, Hunter's Mark)
- Anything with upcast scaling (all leveled spells scale incorrectly)
- Multi-target spells (Magic Missile, Scorching Ray, Eldritch Blast 2+ beams)
- On-hit rider spells (Hex extra damage, Booming Blade, Green-Flame Blade) — NOTE: the rider engine exists (v0.14.0) but these spells need the buff/debuff system to apply riders via concentration spells
- Recurring action spells (Spiritual Weapon, Heat Metal, Call Lightning)
- Reaction spells with triggers (Shield, Counterspell, Absorb Elements)
- Power Word spells (HP threshold checks)
- Spells with complex condition durations (Hold Person needs "save at end of each turn")

**Class features they CAN build:**
- Unarmored Defense (monk, barbarian)
- Second Wind, Lay on Hands, basic healing abilities
- Ki/Sorcery Point/resource-gated abilities (resource system works)
- Wild Shape
- Any passive stat bonus feature
- Divine Smite (now via generalized on-hit rider system, v0.14.0)
- **On-hit riders (v0.14.0)**: Sneak Attack, Stunning Strike, Eldritch Smite, Divine Smite, and similar features via `Feature.on_hit_rider` with builder UI

**Class features they CANNOT build:**
- ~~On-hit riders (Sneak Attack, Maneuvers, Stunning Strike, new smites)~~ — **RESOLVED (v0.14.0)**: core on-hit riders now buildable. Sub-gaps: Battlemaster Maneuvers need superiority die *roll* for variable damage; Smite *spells* need buff/debuff system to apply rider via spell
- Toggle abilities (Rage, Bladesong, Reckless Attack)
- Reaction features (Uncanny Dodge, Parry, Deflect Missiles)
- Extra Attack / multi-attack scaling
- Metamagic
- Aura effects
- Save rerolls (Indomitable, Lucky)
