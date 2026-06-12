# Phase C — Arena Completeness ("any action a player can take") — v0.1

Date: 2026-06-12. Successor to `oubliette-content-first-plan-v0.1.md` (Phase A/B, both shipped —
`main` @ 8b8ea54, 2321 green). OublietteDev's directive: every combat-relevant action a player could
take should be possible in the Arena — all expressible spells, class abilities, item use, and
tactics — with truly freeform spells (Wish, Prestidigitation, Mage Hand) formally **washed**:
we wash our hands of actions whose effect is unbounded narrative improvisation.

This document is the C0 triage output: a 7-agent ground-truth pass over all 261 deferred SRD
spells, 131 class/subclass features, and the monster special-ability pipeline (2026-06-12).

---

## 0. Headline ground truth (things the roadmap previously got wrong)

1. **Breath weapons already work.** The bridge does NOT feed monsters through the flat StatBlock
   path — `enemy_from_statblock` prefers `arena/data/monsters/srd/<id>.json` (a parallel
   full-fidelity set for all 334 monsters, `tools/gen_arena_monsters.py`). 80 save-based AoE
   actions are staged, including all 40 recharge abilities, approximated as `uses_per_rest=2`
   per fight; the AI knows to lead with them (`arena/ai/resources.py:52`). A dragon breathes
   exactly twice per encounter today.
2. **The engine already has most "class feature" mechanics as declarative `Feature` fields,
   all dormant**: `extra_attack_count`, on-hit rider presets (`divine_smite`, `sneak_attack`,
   `stunning_strike`, `hex`), auras (`aura_save_bonus_ability`, `aura_condition_immunity`),
   `has_evasion`, damage-reduction reactions (Uncanny Dodge / Deflect Missiles), death
   prevention (Relentless Rage), forced rerolls (Indomitable / Diamond Soul), crit-range and
   bonus-crit-dice mods. The bridge constructs `PlayerCharacter` with **no `features=` kwarg
   at all** (`oubliette/combat/arena_bridge.py:457-482`). **A level-5 Fighter gets ONE attack
   in the Arena today** purely because of this. The single biggest Phase C unlock is a
   sheet-feature-name → engine-Feature staging map in the bridge.
3. **More spell primitives exist than the B4 generator uses**: `condition_save_to_end`
   (re-save each turn), `terrain_modification: "difficult"`, `summon_creature` (wired in
   manager.py, used by Wild Shape's `is_wild_shape` revert path), `conditions_removed`
   (cleanses), speed buffs (flat/multiply/set), `hp_threshold_effect="condition"`, dual-type
   damage lists, `AREA_CYLINDER`. Several spells the triage tagged PRIMITIVE will downgrade to
   CURATION on contact (noted below).
4. **Known approximations to keep on the radar** (not blockers): cone/line AoEs resolve as a
   radius burst around the caster (`manager.py:2847` `_resolve_effect_targets`); wall
   `damage_on_enter` is stored but never applied; Sneak Attack's engine preset fires on every
   hit (no advantage/ally-adjacency gate); saving-throw proficiencies ARE used by rider saves
   and the AI executor (not fully unused as previously believed).

## 1. Scope arithmetic (319 SRD spells)

| Bucket | Count | Outcome |
|---|---|---|
| Already in the Arena library | 58 | shipped (B4/B5) |
| CURATION — data/curated entry only, zero engine code | 78 | Phase C target |
| PRIMITIVE — needs a named new engine mechanic | 47 | tiered; some downgrade to curation |
| WASH — triage-judged: no bounded in-combat use | 77 | formally closed |
| WASH — casting time ≥ 1 minute (can't start mid-fight) | 59 | formally closed |

End state if all tiers land: **183 of 319 castable in combat (57%)**; the other 136 are
deliberately story-side, which IS the design (the DM narrates them; the Arena fights them).

---

## 2. Spell triage — CURATION tier (78)

Hand-curated rules entries via the `_CURATED` table / generator extensions in
`tools/gen_spells.py`. "(approx)" = a noted, deliberate simplification that keeps the
tactical essence. Grouped by the primitive they ride.

**Buffs / debuffs (buff-modifier, buff-set, advantage flags, resistance grants):**
- bless — 3 allies flat +2 attacks/saves (approx of +1d4), concentration
- bane — 3 targets CHA save, flat −2 attacks/saves (approx), concentration
- shield_of_faith — +2 AC, concentration
- barkskin — AC floor 16 (buff-set), concentration
- haste — speed ×2, +2 AC, advantage DEX saves (approx: extra action + lethargy dropped)
- slow — WIS save: speed ×0.5, −2 AC, −2 DEX saves, re-save each turn
- expeditious_retreat — speed multiplier ≈ bonus-action Dash, concentration
- longstrider — flat +10 speed, 1 hr, no concentration
- blur — attackers-have-disadvantage on self, concentration
- true_strike — self advantage on attacks 1 round
- heroism — temp HP grant (approx: per-turn regrant + fear immunity dropped)
- magic_weapon — wielder +1/+2/+3 attack & damage, counts as magical, concentration
- shillelagh — flat attack/damage bake + magical tag + d8 die
- protection_from_energy — resistance to chosen type (per-type variants), concentration
- protection_from_poison — poison resistance + save advantage, 1 hr
- stoneskin — resistance to nonmagical B/P/S (B3 magical-tag plumbing distinguishes)
- warding_bond — +1 AC/saves + resistance all types (approx: caster damage-mirror dropped)
- beacon_of_hope — allies advantage on WIS saves (approx: max-healing rider dropped)
- holy_aura — chosen allies: advantage all saves + attackers disadvantaged, concentration
- protection_from_evil_and_good / dispel_evil_and_good — attackers disadvantaged vs target (approx: type filter dropped)
- resistance — +1d4 to saves (dice bonus supported), concentration
- ray_of_enfeeblement — attack hit → damage-penalty debuff w/ CON re-save (approx flat −3)
- fire_shield — resistance (fire/cold) + 5-ft moves-with-caster retaliation aura (approx)

**Conditions on save (incl. re-save via `condition_save_to_end`):**
- hold_person / hold_monster — WIS save or paralyzed, re-save each turn, concentration
- blindness_deafness — CON save or blinded, CON re-save, upcast +1 target
- fear — 30-ft cone WIS save or frightened w/ re-save (approx: drop-item/forced-flee dropped)
- hideous_laughter — prone + incapacitated, WIS re-save
- hypnotic_pattern — cube, charmed + incapacitated fixed duration (approx: damage-breaks-it dropped)
- charm_person — WIS save or charmed fixed duration (approx: ends-on-harm dropped)
- confusion — AoE WIS save → incapacitated 2-3 turns (approx: behavior table dropped)
- color_spray — cone, blinded 1 round (approx: HP-pool → save)
- eyebite — frightened (or unconscious) single target, concentration (approx)
- flesh_to_stone — CON save or restrained, concentration (approx: 3-fail petrify escalation dropped)
- irresistible_dance — restrained-equivalent package, concentration (approx)
- levitate — CON save or restrained ≈ hoisted, melee-locked (approx)
- web — cube: DEX save or restrained + difficult terrain, concentration (approx)
- entangle — square: difficult terrain + STR save or restrained w/ re-save, concentration
- grease — cube: DEX save or prone + difficult terrain (approx: re-trip on entry dropped)
- sleep — AoE hp-threshold (~22 flat) → unconscious (approx: HP pool + wake-on-damage dropped)
- contagion — melee attack → blinded+poisoned w/ CON re-save (approx: 3-fail onset dropped)
- bestow_curse — WIS save → disadvantage attacks + one ability's saves, concentration (approx)
- command — WIS save or lose turn (prone/incapacitated 1 round); upcast adds targets
- faerie_fire — cube DEX save → attackers-have-advantage buff (approx: invis-negation dropped)
- greater_invisibility — invisible condition, concentration
- invisibility — invisible condition (approx: ends-on-attack not enforced — generous)
- calm_emotions — AoE `conditions_removed` cleanse of charmed/frightened on allies
- lesser_restoration — touch cleanse: blinded/deafened/paralyzed/poisoned (field exists verbatim)

**Save-damage / AoE (incl. dual-type and cylinder shapes):**
- flame_strike — cylinder DEX save 4d6 fire + 4d6 radiant
- ice_storm — cylinder DEX save 2d8 bludgeoning + 4d6 cold + difficult terrain
- meteor_swarm — 40-ft sphere 20d6 fire + 20d6 bludgeoning (approx: 4 impact points → 1)
- prismatic_spray — cone 10d6 mixed (approx: ray roulette + riders dropped)
- earthquake — huge AoE prone + difficult terrain + small bludgeoning (approx)
- divine_word — CHA save: hp-threshold kill ≤20 + conditions on fail (approx: planar eject dropped)
- weird — AoE frightened + concentration zone 4d10 psychic start-of-turn (approx)
- power_word_kill — hp_threshold=100, effect=kill (the primitive's namesake)
- power_word_stun — hp_threshold≤150 → stunned, CON re-save (all existing fields)
- reverse_gravity — 50-ft radius DEX save or 6d6 fall + suspended/restrained (approx: verticality flattened)
- gust_of_wind — line STR save or pushed 15 ft (forced-movement; approx: sustained re-aim dropped)
- telekinesis — STR save or slide 30 ft + restrained 1 turn, repeatable, concentration (approx)

**Zones, walls, recurring:**
- spirit_guardians — 15-ft moves-with-caster aura, WIS save 3d8 start-of-turn, enemies-only (approx: slow dropped)
- spike_growth — zone 2d4 piercing on enter + start-of-turn (approx: per-5-ft scaling dropped)
- guardian_of_faith — fixed enemies-only zone, 20 radiant on enter (approx: 60-dmg cap → duration)
- flaming_sphere — recurring movable sphere, DEX save 2d6 fire
- call_lightning — recurring repeat-cast 3d10 at chosen point each turn
- heat_metal — recurring auto-hit 2d8 fire each bonus action (approx: drop-weapon dropped)
- flame_blade — recurring sustained blade: melee spell attack 3d6 fire
- spiritual_weapon — recurring bonus-action movable attack 1d8+mod force
- arcane_hand — recurring movable 4d8 force + shove option (approx: grapple/cover dropped)
- wall_of_stone — wall: 10 panels AC 15 / 90 HP
- wall_of_force — wall: indestructible (`wall_hp_per_panel=None` documented for this spell)
- forcecage — wall panels arranged as enclosing box, ≈indestructible (approx)
- prismatic_wall — wall + pass-through damage (rides the known wall-damage bug fix; approx: 7 layers → 1)

**Teleports & misc:**
- misty_step — bonus-action self-teleport 30 ft (exact fit)
- dimension_door — self-teleport 500 ft + willing passenger (exact fit)
- counterspell — `is_counterspell` (primitive exists)
- conjure_woodland_beings — `summon_creature` one CR-2 fey ally (approx: multi-option dropped)

## 3. Spell triage — PRIMITIVE tier (47, grouped by mechanic)

Ordered by unlock count. ★ = engine partially covers it already; verify-then-downgrade likely.

| Primitive | Spells unlocked | Notes |
|---|---|---|
| **P-VISION-LIGHT** — light/darkness/invisibility/obscurement layer affecting LOS+targeting | darkness, fog_cloud, daylight, see_invisibility, true_seeing, mislead | The big one; also benefits monster blindsight later. Without it these six are dead. |
| **P-BANISH** — temporarily remove a creature from the field | banishment, maze, resilient_sphere, blink, plane_shift (offensive rider) | One mechanic, five spells. Untargetable + returns on condition. |
| **P-CONTROL** — caster dictates an enemy's actions | dominate_person, dominate_beast, dominate_monster, compulsion | Real AI/turn-loop work; re-save on damage. |
| **P-TRANSFORM** ★ — stat-block replacement | polymorph, true_polymorph, shapechange, animal_shapes | Wild Shape machinery (`summon_creature` + `is_wild_shape` revert at 0 HP) likely carries most of this. |
| **P-ONHIT-RIDER** ★ — rider on the caster's weapon hits | branding_smite, hunters_mark, divine_favor, enlarge_reduce | Engine `RIDER_PRESETS` already include `hex` (≈ Hunter's Mark) and `divine_smite` — mostly bridge/data work. |
| **P-SUMMON** ★ — spawn allied creatures | conjure_animals, giant_insect, animate_objects | `summon_creature` is wired; gap is multi-creature counts + player control UX. |
| **Condition-zones (P-TERRAIN)** — zones that apply conditions/terrain, not just damage | sleet_storm, stinking_cloud, plant_growth | `ActiveZone` is damage-only today; `terrain_modification` exists on actions but not zones. |
| **P-DEATHWARD** ★ — death-prevention / stabilize / revive | death_ward, revivify, spare_the_dying | Engine has `death_prevention.py` + `is_stabilized`; mostly wiring. |
| **P-DECOY** — decoy charges / attack redirection | mirror_image, sanctuary, (mislead) | d20 redirect roll, charges. |
| **P-DISPEL** — strip magical effects | dispel_magic, greater_restoration | Needs effect-origin tagging on buffs/zones. |
| **P-REACTION** — true spell interrupts | shield, feather_fall | Engine HAS damage-reduction reactions (Uncanny Dodge) — extend that hook to spells. |
| **P-MOVEMENT-MODE** — fly/water-walk | fly, water_walk | 2D grid makes this near-cosmetic; lowest priority / candidate re-wash. |
| **P-CASTBLOCK** — spellcasting suppression | silence, feeblemind | Zone flag + per-creature flag. |
| One-offs (stretch) | antilife_shell (barrier aura), globe_of_invulnerability (spell ward), antimagic_field (suppression), freedom_of_movement (condition immunity grant), time_stop (bonus turns) | Each is its own mechanic for one spell — do last or never. |

## 4. Spell triage — WASH (136, formally closed)

**Triage-judged (77):** alter_self, animal_friendship, animal_messenger, arcane_eye, arcane_lock,
arcanists_magic_aura, comprehend_languages, continual_flame, create_food_and_water,
create_or_destroy_water, dancing_lights, darkvision, demiplane, detect_evil_and_good,
detect_magic, detect_poison_and_disease, detect_thoughts, disguise_self, divination, druidcraft,
enhance_ability, enthrall, etherealness, find_traps, floating_disk, gaseous_form, gate,
gentle_repose, glibness, goodberry, guidance, jump, knock, light, locate_animals_or_plants,
locate_creature, locate_object, mage_hand, major_image, mass_suggestion, meld_into_stone,
message, mind_blank, minor_illusion, mislead*, modify_memory, move_earth, nondetection,
pass_without_trace, passwall, prestidigitation, programmed_illusion, project_image,
purify_food_and_drink, remove_curse, rope_trick, secret_chest, seeming, sending, sequester,
silent_image, speak_with_animals, speak_with_dead, speak_with_plants, spider_climb, stone_shape,
suggestion, telepathic_bond, teleport, thaumaturgy, tongues, transport_via_plants, tree_stride,
unseen_servant, water_breathing, word_of_recall, zone_of_truth, wish.
(*mislead sits in P-VISION-LIGHT above; washed if that primitive never lands.)

**Casting time ≥ 1 minute (59):** alarm, animate_dead, antipathy_sympathy, astral_projection,
augury, awaken, clairvoyance, clone, commune, commune_with_nature, conjure_celestial,
conjure_elemental, conjure_fey, conjure_minor_elementals, contact_other_plane, contingency,
control_weather, create_undead, creation, dream, fabricate, find_familiar, find_steed,
find_the_path, forbiddance, foresight, geas, glyph_of_warding, guards_and_wards, hallow,
hallucinatory_terrain, heroes_feast, identify, illusory_script, imprisonment, instant_summons,
legend_lore, magic_circle, magic_jar, magic_mouth, magnificent_mansion, mending, mirage_arcane,
phantom_steed, planar_ally, planar_binding, prayer_of_healing, private_sanctum, raise_dead,
regenerate, reincarnate, resurrection, scrying, simulacrum, symbol, teleportation_circle,
tiny_hut, true_resurrection, wind_walk.

All of these remain available story-side — the DM narrates them; that's the design, not a gap.

---

## 5. Class features (131 triaged: 14 ALREADY / 25 CURATION / 36 BRIDGE-PASSIVE / 22 PRIMITIVE / 34 WASH)

The central fact: **the bridge stages zero engine Features.** Tiers: ALREADY works today;
CURATION = stage extra Actions/buffs from existing primitives; BRIDGE-PASSIVE = stage an engine
`Feature` field or bake a number (the B3 pattern); PRIMITIVE = new engine mechanic.

**Universal / multi-class:**
- Extra Attack (fighter/barbarian/monk/paladin/ranger L5) — BRIDGE-PASSIVE: `Feature(extra_attack_count=2)`; engine fully wired (`stat_modifiers.py:468`, `manager.py:1232`)
- Fighting Styles — BRIDGE-PASSIVE: bake +2 archery to-hit / +1 AC defense / +2 dueling dmg; TWF engine-native. DATA GAP: chargen stores no style choice (prose-only)
- Unarmored Defense (barbarian/monk) — ALREADY (derive.armor_class includes it; flat AC rides in)

**Fighter:** Second Wind CURATION (bonus-action self-heal 1d10+level, uses_per_rest=1 short);
Action Surge CURATION (engine action EXISTS; bridge never stages the `action_surge` resource —
add a `resources` block to classes.json); Indomitable BRIDGE-PASSIVE (`forced_reroll_saves`);
Champion Improved Critical BRIDGE-PASSIVE (`crit_range_reduction=1`).

**Barbarian:** Rage PRIMITIVE-lite — pool already bridged; resistance + STR-save advantage are
buffs today; the +2 melee damage needs ONE new buff stat (flat damage-roll bonus) — small engine
add, fold into C1. Reckless Attack CURATION (toggle: self attack-advantage + attackers-advantage
via the Faerie Fire pattern). Danger Sense / Fast Movement / Brutal Critical / Relentless Rage
all BRIDGE-PASSIVE (fields exist incl. `death_prevention`). DATA GAP: no Berserker subclass in
subclasses.json.

**Rogue:** Sneak Attack BRIDGE-PASSIVE (`RIDER_PRESETS["sneak_attack"]` exists; fires every hit —
advantage/ally gate unmodeled, acceptable approx or small engine gate). Cunning Action CURATION
(bonus-action Dash/Disengage/Hide). Uncanny Dodge / Evasion BRIDGE-PASSIVE (fields exist).
Elusive / Stroke of Luck / Thief's Reflexes PRIMITIVE (niche, stretch).

**Monk:** Ki pool ALREADY staged — but as display name "Ki" while engine presets expect
`ki_points`: **a resource-name normalization map is required** (arena_bridge.py:392). Martial
Arts CURATION (DEX + scaling die bake + bonus-action strike). Flurry / Patient Defense / Step of
the Wind CURATION (ki-costed bonus actions). Stunning Strike BRIDGE-PASSIVE (preset exists).
Deflect Missiles / Evasion / Diamond Soul / Purity of Body BRIDGE-PASSIVE. Open Hand: Technique +
Wholeness of Body CURATION; Quivering Palm PRIMITIVE (stretch).

**Paladin:** Divine Smite BRIDGE-PASSIVE — the engine AUTO-UPGRADES any Feature named "Divine
Smite" (`arena/models/character.py:150-169`); just stage it. Improved Divine Smite
BRIDGE-PASSIVE (auto 1d8 rider). Lay on Hands CURATION (pool staged; heal action in 5-HP
increments). Auras of Protection/Courage/Devotion BRIDGE-PASSIVE (`auras.py` exists). Sacred
Weapon CURATION (+CHA attack buff costing Channel Divinity). Turn the Unholy PRIMITIVE (shared
with cleric Turn Undead).

**Cleric:** Channel Divinity pool ALREADY. Turn Undead PRIMITIVE (creature-type-filtered AoE
save + flee behavior; approx-able as WIS-save frightened). Life domain: Preserve Life ≈ CURATION
(single-target approx), Disciple of Life / Blessed Healer / Supreme Healing PRIMITIVE
(heal-amplification hooks; flat-bonus bake approx possible), Divine Strike BRIDGE-PASSIVE.

**Druid:** Wild Shape CURATION (!) — engine transform exists (`summon_creature` + `is_wild_shape`,
0-HP revert, manager.py:3569-3692); pool already bridged; SRD beast files on disk. Land circle:
Nature's Ward BRIDGE-PASSIVE; Land's Stride PRIMITIVE (terrain-cost exemption flag).

**Bard:** Bardic Inspiration PRIMITIVE (banked bonus die / reaction-modify-roll) + DATA GAP (no
resource block; CHA-scaled pools can't be expressed in by_level). Cutting Words PRIMITIVE (same
reaction-modify-roll mechanic). Jack of All Trades BRIDGE-PASSIVE (initiative slice).

**Sorcerer:** Font of Magic PRIMITIVE (resource conversion); Metamagic PRIMITIVE (spell-mod
layer; Quickened ≈ curation as bonus-action variant). DATA GAP: no Draconic Bloodline subclass.

**Warlock:** Pact Magic ALREADY (short-rest slots via CS5). Invocations CURATION but DATA GAP
(no invocation list in data; Agonizing Blast = damage bake, Repelling Blast = forced-movement
fields exist). Mystic Arcanum CURATION (uses_per_rest=1 long, no slot).

**Wizard:** Sculpt Spells PRIMITIVE — **AoE ally-exemption flag; high priority now that B5 real
friendly fire is on.** Arcane Recovery WASH for Arena (story-side rest feature; note: absent
from rest.py too — separate story-side gap, not Phase C).

**Ranger:** Hunter's Mark is a spell (P-ONHIT-RIDER ★, `hex` preset ≈ exact). Hunter subclass:
Colossus Slayer BRIDGE-PASSIVE approx; Volley/Whirlwind CURATION; Giant Killer / Stand Against
the Tide PRIMITIVE (triggered reaction attacks, stretch).

**Data gaps found:** subclasses.json lacks barbarian/sorcerer/warlock SRD subclasses; no
Eldritch Invocations list; classes.json features are prose-only (`text`), zero structured
mechanics beyond `resources` and spell progressions; no fighter resource blocks
(second_wind/action_surge/indomitable); no bard inspiration pool (CHA-scaled).

## 6. Monster side (verified, mostly healthy)

Working today: full-fidelity files for 334 monsters, multi-type attacks, live multiattack,
resistances/immunities, 80 save-AoE actions, 40 recharge abilities (2 uses/fight approx),
AI that leads with signature moves, legendary/lair engine support, exhausted-action greying.

Ordered fix list (value per effort):
1. **Emit `legendary_actions` in gen_arena_monsters.py** — data-only; engine support complete
   and idle (`manager.py:700-856`, AI planner `controller.py:738-838`). Dragons are the marquee
   fights; this is their missing tooth.
2. **Emit `conditions_on_fail` on save actions** — data-mostly; un-inerts Gorgon Petrifying
   Breath (currently staged with no payload → AI skips it) and Frightful Presence, adds poison
   breath riders.
3. **Attack-side condition riders** (ghoul paralysis, etc.) — small engine field; condition
   machinery exists.
4. True d6 recharge roll — small engine feature (`recharge_on` sketched in
   CombatEffectDesignDocument.md:195); upgrade from the 2-uses approx.
5. Regeneration + Pack Tactics — one small targeted hook each.
6. Monster spellcasting — the one genuinely large item (name-listed only today). Stretch.

## 7. Player kit & UX (the radial audit — mostly already wired)

Verified working: radial slots for attack / cantrips / spells / tactics (Dash, Disengage, Dodge,
Hide, Help, Shove) / items (potions) / bonus actions / end turn; Ready actions; opportunity
attacks; two-weapon fighting; exhausted actions greyed.

To add:
- **Weapon kit (design decided 2026-06-12):** NO switch action — 5e's free object interaction
  makes swapping free, so everything carried is simply available. Bridge stages one attack
  action per carried weapon (longsword AND javelin); thrown weapons decrement from inventory
  like potions (gone for the fight when thrown). Hand economy (shield + two-hander) deliberately
  not policed. Armor switching stays OUT (donning takes minutes; engine would clobber story AC).
- **Scrolls in the Arena:** the bridge currently skips spell-rider stacks deliberately
  (arena_bridge.py:343). Wire: scroll → cast that spell at the inscribed level without a slot,
  consume the scroll (rides B1's consumable round-trip + B4's spell staging). Min-level rule
  already enforced story-side.
- Grapple escape (no escape check exists) and prone movement penalty — two small engine gaps
  from the tactics audit.

## 8. Proposed stages

- **C1 — Feature bridge (the big unlock):** staging map from sheet feature names → engine
  Features + curated Actions (Extra Attack, smite, sneak attack, stunning strike, auras,
  evasion, uncanny dodge, deflect missiles, second wind, cunning action, flurry/ki actions,
  lay on hands, reckless attack, rage incl. the one new flat-damage buff stat, sacred weapon…).
  Includes: resource-name normalization (Ki→ki_points…), fighter resource blocks in
  classes.json, missing SRD subclasses (Berserker/Draconic/Fiend) as CS4-style content fill.
  This makes martials first-class citizens — biggest player-visible win in the whole phase.
- **C2 — Monster data wins:** fix list items 1–3 (legendary actions, condition riders on saves
  and attacks). Cheap, big fidelity.
- **C3 — Spell curation wave:** the 78 CURATION spells through gen_spells.py's curated table,
  verifying the ★-marked engine claims as we go (likely pulls summons/riders/deathward/
  transform spells down from PRIMITIVE too).
- **C4 — New primitives by unlock count:** Sculpt-Spells ally exemption (friendly-fire
  counterweight), P-VISION-LIGHT (6 spells), P-BANISH (5), P-CONTROL (4), condition-zones (3),
  P-DECOY (3), P-DISPEL (2), P-REACTION (Shield + the Bardic Inspiration/Cutting Words
  reaction-modify-roll mechanic), Turn Undead. Stretch tier: movement modes, metamagic,
  antimagic, time stop, one-offs.
- **C5 — Player kit:** weapon kit, scrolls in Arena, grapple escape, prone penalty.
- **C6 — Ship-readiness playtest:** absorbs the B7 ledger (B3 gear check, friendly-fire feel,
  Mage Armor/Magic Missile/Giant Strength, Scree portrait re-upload) + new-content shakedown.
  Exit question: "is the Arena shippable?"

Ordering rationale: C1 and C2 are wiring/data against engine machinery that already exists —
maximum fidelity per line of code. C3 is volume data work. C4 is real engine work, strictly
prioritized by spells-per-primitive. C5/C6 close the loop.
