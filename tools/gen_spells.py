"""Generate the Arena spell-action library (arena/data/spells/srd/) from the
machine-readable 5e-database 2014 dataset — a DETERMINISTIC parse, never an LLM
transcription (the CS4 lesson), the playbook's fifth use.

Source: https://github.com/5e-bits/5e-database  (CC-BY-4.0 / OGL SRD 5.1 content)
        src/2014/en/5e-SRD-Spells.json

Re-run:
    curl -sL https://raw.githubusercontent.com/5e-bits/5e-database/main/src/2014/en/5e-SRD-Spells.json -o srd-spells-raw.json
    python tools/gen_spells.py srd-spells-raw.json arena/data/spells/srd

Each emitted file is ONE Arena `Action` (validated against the model on write),
keyed by the Oubliette spell id (index with underscores) so the bridge can map a
character sheet's spell lists straight onto files. Only the pattern-extractable
combat families are emitted (D-COMBAT-2 — the cap is the design, not a failure):

  - spell-attack damage  (attack_type + damage)          e.g. Fire Bolt, Guiding Bolt
  - save-based damage    (dc + damage [+ area_of_effect]) e.g. Fireball, Sacred Flame
  - healing              (heal_at_slot_level)             e.g. Cure Wounds
  - curated rescues      (_CURATED overlays, B5)          Magic Missile, Scorching Ray, Mage Armor

Everything else is skipped with a reason into `_manifest.json` (control/buff
spells carry no structured mechanics in the source; rituals/long casts have no
combat shape; auto-hit and zone/duration spells need primitives the engine
doesn't route from data yet — Magic Missile is the famous one).

BRIDGE-BAKED FIELDS (the library is consumed by oubliette's arena_bridge, which
knows the caster's sheet — same philosophy as the +X gear bake in B3):
  - `Attack.ability` is emitted as a placeholder; the bridge rewrites it to the
    caster's spellcasting ability.
  - `SavingThrowEffect.dc` is emitted as null; the bridge stamps the caster's
    spell save DC (the engine's data-side fallback is a flat 10).
  - healing strings may contain the literal token `MOD` ("1d8+MOD"); the bridge
    substitutes the caster's spellcasting modifier.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.models.actions import Action  # noqa: E402  (validation gate)

_OK_TIMES = {"1 action": "action", "1 bonus action": "bonus_action",
             "1 reaction": "reaction"}
_ABILITY_LONG = {"str": "strength", "dex": "dexterity", "con": "constitution",
                 "int": "intelligence", "wis": "wisdom", "cha": "charisma"}
_AOE_TARGET = {"sphere": "area_sphere", "cube": "area_cube", "cone": "area_cone",
               "line": "area_line", "cylinder": "area_sphere"}
# Attack.ability placeholder — the bridge rewrites it to the caster's real
# spellcasting ability before the action ever reaches the engine.
_PLACEHOLDER_ABILITY = "intelligence"

_DICE_RE = re.compile(r"^\s*(\d+)d(\d+)\s*(?:\+\s*(\d+|MOD))?\s*$")

# Spells the pattern rules can't read but the engine CAN run — curated
# overlays applied on top of the normal base fields (the base supplies name,
# description, action economy, range, concentration, spell level + slot cost,
# and any source-declared area; the overlay supplies the mechanics the source
# encodes only as prose). B5 began this with three rescues (magic_missile,
# scorching_ray, mage_armor); C3 is the full curation wave: the control/buff/
# zone/recurring/teleport families the triage marked expressible.
#
# CONVENTIONS (engine semantics these entries rely on, all verified):
#   - saving_throw.conditions_on_fail: applied with a built-in re-save at the
#     END of the target's turn; persists while saves keep failing. dc: None is
#     stamped with the caster's spell DC by the bridge.
#   - buff_effects + saving_throw = save-gated debuff (Bane/Slow apply only on
#     a failed save, with save-to-end riding the buff). buff_effects without a
#     save = beneficial; AoE resolves allies-only (_is_beneficial_aoe).
#   - dice-valued buffs roll per use (Bless's real +1d4); int penalties work.
#   - concentration + area + save-damage = implicit persistent ZONE
#     (enemies-only, damage at start of turn inside; zone_follows_caster for
#     auras, zone_move_cost for movable spheres).
#   - recurring_action_type re-offers the action on later turns (Witch Bolt
#     machinery); recurring_move_distance moves the effect first.
#   - DamageRoll.ability_modifier set to the placeholder = the bridge bakes
#     the caster's spellcasting mod into damage (Spiritual Weapon).
#   - grants_temporary_hp may carry the MOD token (Heroism); bridge bakes it.
#
# DELIBERATE APPROXIMATIONS (the tactical essence is kept; noted per entry):
# fixed condition lists for tiered/progressive effects, single damage type
# for ray-roulette spells, "ends on attack" not enforced for invisibility,
# choice-of-type resistances pinned to the common pick. Walls stay OUT of
# this wave: the wall engine exists but no GUI placement mode is wired yet
# (wall_of_stone/wall_of_force/forcecage/prismatic_wall wait on it).
_CURATED: dict[str, dict] = {
    "magic_missile": {
        "target_type": "one_creature",
        "target_count": 3,
        "upcast_target_count": 1,
        "attack": {
            "name": "Magic Missile",
            "attack_type": "ranged_spell",
            "ability": _PLACEHOLDER_ABILITY,       # bridge rewrites
            "reach": 5,
            "range_normal": 120,
            "auto_hit": True,
            "damage": [{"dice": "1d4", "damage_type": "force", "bonus": 1}],
        },
    },
    "scorching_ray": {
        "target_type": "one_creature",
        "target_count": 3,
        "upcast_target_count": 1,
        "attack": {
            "name": "Scorching Ray",
            "attack_type": "ranged_spell",
            "ability": _PLACEHOLDER_ABILITY,       # bridge rewrites
            "reach": 5,
            "range_normal": 120,
            "damage": [{"dice": "2d6", "damage_type": "fire", "bonus": 0}],
        },
    },
    "mage_armor": {
        "target_type": "self",
        "buff_effects": [
            {"stat": "ac", "modifier_type": "set", "value": "13+DEX"},
        ],
    },

    # ── C3: control — save or condition (re-save each turn built in) ──────
    "hold_person": {
        "target_type": "one_creature", "upcast_target_count": 1,
        "saving_throw": {"ability": "wisdom", "dc": None,
                         "conditions_on_fail": ["paralyzed"]},
    },
    "hold_monster": {
        "target_type": "one_creature", "upcast_target_count": 1,
        "saving_throw": {"ability": "wisdom", "dc": None,
                         "conditions_on_fail": ["paralyzed"]},
    },
    "charm_person": {   # approx: ends-on-harm not modeled
        "target_type": "one_creature", "upcast_target_count": 1,
        "saving_throw": {"ability": "wisdom", "dc": None,
                         "conditions_on_fail": ["charmed"]},
    },
    "blindness_deafness": {
        "target_type": "one_creature", "upcast_target_count": 1,
        "saving_throw": {"ability": "constitution", "dc": None,
                         "conditions_on_fail": ["blinded"]},
    },
    "fear": {           # approx: drop-held-item + forced flight omitted
        "target_type": "area_cone", "area_size": 30,
        "saving_throw": {"ability": "wisdom", "dc": None,
                         "conditions_on_fail": ["frightened"]},
    },
    "hideous_laughter": {
        "target_type": "one_creature",
        "saving_throw": {"ability": "wisdom", "dc": None,
                         "conditions_on_fail": ["prone", "incapacitated"]},
    },
    "hypnotic_pattern": {  # approx: damage-breaks-it omitted
        "target_type": "area_cube", "area_size": 30,
        "saving_throw": {"ability": "wisdom", "dc": None,
                         "conditions_on_fail": ["charmed", "incapacitated"]},
    },
    "confusion": {      # approx: behaviour table collapsed to incapacitated
        "target_type": "area_sphere", "area_size": 10,
        "saving_throw": {"ability": "wisdom", "dc": None,
                         "conditions_on_fail": ["incapacitated"]},
    },
    "color_spray": {    # approx: HP-pool mechanic becomes a DEX save
        "target_type": "area_cone", "area_size": 15,
        "saving_throw": {"ability": "dexterity", "dc": None,
                         "conditions_on_fail": ["blinded"]},
    },
    "eyebite": {        # approx: sicken/sleep modes dropped, fear kept
        "target_type": "one_creature",
        "saving_throw": {"ability": "wisdom", "dc": None,
                         "conditions_on_fail": ["frightened"]},
    },
    "flesh_to_stone": { # approx: first stage only; 3-fail petrify escalation dropped
        "target_type": "one_creature",
        "saving_throw": {"ability": "constitution", "dc": None,
                         "conditions_on_fail": ["restrained"]},
    },
    "irresistible_dance": {  # approx: dance package as restrained
        "target_type": "one_creature",
        "saving_throw": {"ability": "wisdom", "dc": None,
                         "conditions_on_fail": ["restrained"]},
    },
    "levitate": {       # approx: hoisted 20 ft = melee-locked restrained
        "target_type": "one_creature",
        "saving_throw": {"ability": "constitution", "dc": None,
                         "conditions_on_fail": ["restrained"]},
    },
    "command": {        # approx: "grovel" reading — one-word commands vary
        "target_type": "one_creature", "upcast_target_count": 1,
        "saving_throw": {"ability": "wisdom", "dc": None,
                         "conditions_on_fail": ["prone"]},
    },
    "contagion": {      # approx: 3-fail disease onset skipped; poisoned on hit
        "target_type": "one_creature",
        "attack": {"name": "Contagion", "attack_type": "melee_spell",
                   "ability": _PLACEHOLDER_ABILITY, "reach": 5, "damage": []},
        "conditions_applied": ["poisoned"],
        "condition_save_to_end": "constitution",
    },
    "bestow_curse": {   # approx: curse menu collapsed to attack disadvantage
        "target_type": "one_creature",
        "saving_throw": {"ability": "wisdom", "dc": None},
        "buff_effects": [
            {"stat": "attack_rolls", "modifier_type": "disadvantage"},
        ],
    },
    "web": {
        "target_type": "area_cube", "area_size": 20,
        "saving_throw": {"ability": "dexterity", "dc": None,
                         "conditions_on_fail": ["restrained"]},
        "terrain_modification": "difficult",
    },
    "entangle": {
        "target_type": "area_cube", "area_size": 20,
        "saving_throw": {"ability": "strength", "dc": None,
                         "conditions_on_fail": ["restrained"]},
        "terrain_modification": "difficult",
    },
    "grease": {         # approx: re-save on later entry dropped
        "target_type": "area_cube", "area_size": 10,
        "saving_throw": {"ability": "dexterity", "dc": None,
                         "conditions_on_fail": ["prone"]},
        "terrain_modification": "difficult",
    },
    "faerie_fire": {    # save-gated debuff: attackers gain advantage
        "target_type": "area_cube", "area_size": 20,
        "saving_throw": {"ability": "dexterity", "dc": None},
        "buff_effects": [
            {"stat": "attack_rolls", "modifier_type": "advantage",
             "target_grants_to_attacker": True},
        ],
    },
    "ray_of_enfeeblement": {  # approx: attack reshaped as save (engine buffs ride saves)
        "target_type": "one_creature",
        "saving_throw": {"ability": "constitution", "dc": None},
        "buff_effects": [
            {"stat": "damage_rolls", "modifier_type": "flat_bonus", "value": -3,
             "scope": "melee"},
        ],
    },
    "calm_emotions": {
        "target_type": "area_sphere", "area_size": 20,
        "conditions_removed": ["charmed", "frightened"],
    },
    "lesser_restoration": {
        "target_type": "one_ally",
        "conditions_removed": ["blinded", "deafened", "paralyzed", "poisoned"],
    },

    # ── C3: HP-threshold effects ──────────────────────────────────────────
    "sleep": {          # approx: 5d8 HP pool flattened to a 22-HP threshold
        "target_type": "area_sphere", "area_size": 20,
        "hp_threshold": 22, "hp_threshold_effect": "condition",
        "hp_threshold_condition": "unconscious",
    },
    "power_word_kill": {
        "target_type": "one_creature",
        "hp_threshold": 100, "hp_threshold_effect": "kill",
    },
    "power_word_stun": {
        "target_type": "one_creature",
        "hp_threshold": 150, "hp_threshold_effect": "condition",
        "hp_threshold_condition": "stunned",
        "condition_save_to_end": "constitution",
    },
    "divine_word": {    # approx: HP tiers collapsed to kill<=20 + stunned
        "target_type": "area_sphere", "area_size": 30,
        "hp_threshold": 20, "hp_threshold_effect": "kill",
        "saving_throw": {"ability": "charisma", "dc": None,
                         "conditions_on_fail": ["stunned"]},
    },

    # ── C3: buffs (dice values roll per use; debuffs gate on their save) ──
    "bless": {
        "target_type": "area_sphere", "area_size": 30,
        "buff_effects": [
            {"stat": "attack_rolls", "modifier_type": "flat_bonus", "value": "1d4"},
            {"stat": "saving_throws", "modifier_type": "flat_bonus", "value": "1d4"},
        ],
    },
    "bane": {           # approx: -1d4 as flat -2 (penalty dice unsupported)
        "target_type": "area_sphere", "area_size": 30,
        "saving_throw": {"ability": "charisma", "dc": None},
        "buff_effects": [
            {"stat": "attack_rolls", "modifier_type": "flat_bonus", "value": -2},
            {"stat": "saving_throws", "modifier_type": "flat_bonus", "value": -2},
        ],
    },
    "shield_of_faith": {
        "target_type": "one_ally",
        "buff_effects": [{"stat": "ac", "modifier_type": "flat_bonus", "value": 2}],
    },
    "barkskin": {
        "target_type": "one_ally",
        "buff_effects": [{"stat": "ac", "modifier_type": "set", "value": 16}],
    },
    "haste": {          # approx: the extra action + lethargy crash omitted
        "target_type": "one_ally",
        "buff_effects": [
            {"stat": "speed", "modifier_type": "multiply", "value": 2.0},
            {"stat": "ac", "modifier_type": "flat_bonus", "value": 2},
            {"stat": "saving_throws", "modifier_type": "advantage",
             "scope": "dexterity"},
        ],
    },
    "slow": {           # approx: action-economy denial dropped
        "target_type": "area_cube", "area_size": 40,
        "saving_throw": {"ability": "wisdom", "dc": None},
        "buff_effects": [
            {"stat": "speed", "modifier_type": "multiply", "value": 0.5},
            {"stat": "ac", "modifier_type": "flat_bonus", "value": -2},
            {"stat": "saving_throws", "modifier_type": "flat_bonus", "value": -2,
             "scope": "dexterity"},
        ],
    },
    "expeditious_retreat": {
        "target_type": "self",
        "buff_effects": [{"stat": "speed", "modifier_type": "multiply", "value": 2.0}],
    },
    "longstrider": {
        "target_type": "one_ally",
        "buff_effects": [{"stat": "speed", "modifier_type": "flat_bonus", "value": 10}],
    },
    "blur": {
        "target_type": "self",
        "buff_effects": [
            {"stat": "attack_rolls", "modifier_type": "disadvantage",
             "target_grants_to_attacker": True},
        ],
    },
    "true_strike": {    # approx: one-round self advantage
        "target_type": "self",
        "buff_effects": [{"stat": "attack_rolls", "modifier_type": "advantage"}],
        "buff_duration_rounds": 2,
    },
    "heroism": {        # temp HP = casting mod (bridge bakes); per-turn regrant dropped
        "target_type": "one_ally",
        "grants_temporary_hp": "MOD",
    },
    "protection_from_energy": {  # approx: type choice pinned to fire
        "target_type": "one_ally",
        "buff_effects": [
            {"stat": "damage_resistance", "modifier_type": "resistance",
             "value": "fire"},
        ],
    },
    "protection_from_poison": {
        "target_type": "one_ally",
        "buff_effects": [
            {"stat": "damage_resistance", "modifier_type": "resistance",
             "value": "poison"},
        ],
    },
    "stoneskin": {      # approx: blanket b/p/s resistance (nonmagical filter is monster-side)
        "target_type": "one_ally",
        "buff_effects": [
            {"stat": "damage_resistance", "modifier_type": "resistance",
             "value": "bludgeoning"},
            {"stat": "damage_resistance", "modifier_type": "resistance",
             "value": "piercing"},
            {"stat": "damage_resistance", "modifier_type": "resistance",
             "value": "slashing"},
        ],
    },
    "warding_bond": {   # approx: caster damage-mirror dropped
        "target_type": "one_ally",
        "buff_effects": [
            {"stat": "ac", "modifier_type": "flat_bonus", "value": 1},
            {"stat": "saving_throws", "modifier_type": "flat_bonus", "value": 1},
        ] + [
            {"stat": "damage_resistance", "modifier_type": "resistance", "value": t}
            for t in ("acid", "bludgeoning", "cold", "fire", "force", "lightning",
                      "necrotic", "piercing", "poison", "psychic", "radiant",
                      "slashing", "thunder")
        ],
    },
    "beacon_of_hope": { # approx: maximised-healing rider dropped
        "target_type": "area_sphere", "area_size": 30,
        "buff_effects": [
            {"stat": "saving_throws", "modifier_type": "advantage",
             "scope": "wisdom"},
        ],
    },
    "holy_aura": {      # approx: fiend/undead blind-flash rider dropped
        "target_type": "area_sphere", "area_size": 30,
        "buff_effects": [
            {"stat": "saving_throws", "modifier_type": "advantage"},
            {"stat": "attack_rolls", "modifier_type": "disadvantage",
             "target_grants_to_attacker": True},
        ],
    },
    "resistance": {
        "target_type": "one_ally",
        "buff_effects": [
            {"stat": "saving_throws", "modifier_type": "flat_bonus", "value": "1d4"},
        ],
    },
    "magic_weapon": {   # approx: base +1 only (no upcast route for buffs)
        "target_type": "one_ally",
        "buff_effects": [
            {"stat": "attack_rolls", "modifier_type": "flat_bonus", "value": 1},
            {"stat": "damage_rolls", "modifier_type": "flat_bonus", "value": 1},
        ],
    },
    "invisibility": {   # approx: ends-on-attack not enforced
        "target_type": "one_ally", "upcast_target_count": 1,
        "conditions_applied": ["invisible"],
    },
    "greater_invisibility": {
        "target_type": "one_ally",
        "conditions_applied": ["invisible"],
    },
    "protection_from_evil_and_good": {  # approx: creature-type filter dropped
        "target_type": "one_ally",
        "buff_effects": [
            {"stat": "attack_rolls", "modifier_type": "disadvantage",
             "target_grants_to_attacker": True},
        ],
    },
    "dispel_evil_and_good": {  # approx: type filter + banish rider dropped
        "target_type": "self",
        "buff_effects": [
            {"stat": "attack_rolls", "modifier_type": "disadvantage",
             "target_grants_to_attacker": True},
        ],
    },

    # ── C3: save-damage the parser couldn't read (dual-type, prone riders) ─
    "flame_strike": {
        "target_type": "area_sphere", "area_size": 10,
        "saving_throw": {"ability": "dexterity", "dc": None,
                         "damage_on_fail": [
                             {"dice": "4d6", "damage_type": "fire", "bonus": 0},
                             {"dice": "4d6", "damage_type": "radiant", "bonus": 0}],
                         "damage_on_success": "half"},
        "upcast_damage_dice": "1d6",
    },
    "ice_storm": {
        "target_type": "area_sphere", "area_size": 20,
        "saving_throw": {"ability": "dexterity", "dc": None,
                         "damage_on_fail": [
                             {"dice": "2d8", "damage_type": "bludgeoning", "bonus": 0},
                             {"dice": "4d6", "damage_type": "cold", "bonus": 0}],
                         "damage_on_success": "half"},
        "terrain_modification": "difficult",
        "upcast_damage_dice": "1d8",
    },
    "meteor_swarm": {   # approx: four impact points collapsed to one
        "target_type": "area_sphere", "area_size": 40,
        "saving_throw": {"ability": "dexterity", "dc": None,
                         "damage_on_fail": [
                             {"dice": "20d6", "damage_type": "fire", "bonus": 0},
                             {"dice": "20d6", "damage_type": "bludgeoning", "bonus": 0}],
                         "damage_on_success": "half"},
    },
    "prismatic_spray": {  # approx: ray roulette flattened to 10d6 radiant
        "target_type": "area_cone", "area_size": 60,
        "saving_throw": {"ability": "dexterity", "dc": None,
                         "damage_on_fail": [
                             {"dice": "10d6", "damage_type": "radiant", "bonus": 0}],
                         "damage_on_success": "half"},
    },
    "earthquake": {     # approx: fissures/structures dropped; shake = prone + rubble
        "target_type": "area_sphere", "area_size": 100,
        "saving_throw": {"ability": "dexterity", "dc": None,
                         "damage_on_fail": [
                             {"dice": "5d6", "damage_type": "bludgeoning", "bonus": 0}],
                         "damage_on_success": "half",
                         "conditions_on_fail": ["prone"]},
        "terrain_modification": "difficult",
    },
    "reverse_gravity": {  # approx: verticality as fall damage + suspension
        "target_type": "area_sphere", "area_size": 50,
        "saving_throw": {"ability": "dexterity", "dc": None,
                         "damage_on_fail": [
                             {"dice": "6d6", "damage_type": "bludgeoning", "bonus": 0}],
                         "damage_on_success": "none",
                         "conditions_on_fail": ["restrained"]},
    },
    "gust_of_wind": {   # approx: sustained re-aim dropped; one-shot push
        "target_type": "area_line", "area_size": 60,
        "saving_throw": {"ability": "strength", "dc": None},
        "forced_movement_type": "push", "forced_movement_distance": 15,
    },
    "telekinesis": {    # approx: contest as STR save; hoist = restrained + slide
        "target_type": "one_creature",
        "saving_throw": {"ability": "strength", "dc": None,
                         "conditions_on_fail": ["restrained"]},
        "forced_movement_type": "slide", "forced_movement_distance": 30,
    },

    # ── C3: persistent zones (concentration + area + save-damage) ─────────
    "spirit_guardians": {
        "target_type": "area_sphere", "area_size": 15,
        "zone_follows_caster": True,
        "saving_throw": {"ability": "wisdom", "dc": None,
                         "damage_on_fail": [
                             {"dice": "3d8", "damage_type": "radiant", "bonus": 0}],
                         "damage_on_success": "half"},
        "upcast_damage_dice": "1d8",
    },
    "spike_growth": {   # approx: per-5ft scaling as a save-for-half zone
        "target_type": "area_sphere", "area_size": 20,
        "saving_throw": {"ability": "dexterity", "dc": None,
                         "damage_on_fail": [
                             {"dice": "2d4", "damage_type": "piercing", "bonus": 0}],
                         "damage_on_success": "half"},
        "terrain_modification": "difficult",
    },
    "guardian_of_faith": {  # approx: 8-hour sentinel runs on concentration; 60-dmg cap dropped
        "target_type": "area_sphere", "area_size": 10,
        "requires_concentration": True,
        "saving_throw": {"ability": "dexterity", "dc": None,
                         "damage_on_fail": [
                             {"dice": "20", "damage_type": "radiant", "bonus": 0}],
                         "damage_on_success": "half"},
    },
    "weird": {          # zone reading: recurring nightmare damage; per-creature re-saves dropped
        "target_type": "area_sphere", "area_size": 30,
        "saving_throw": {"ability": "wisdom", "dc": None,
                         "damage_on_fail": [
                             {"dice": "4d10", "damage_type": "psychic", "bonus": 0}],
                         "damage_on_success": "none",
                         "conditions_on_fail": ["frightened"]},
    },
    "flaming_sphere": { # movable zone: ram/park it with the bonus action
        "target_type": "area_sphere", "area_size": 5,
        "zone_move_cost": "bonus_action",
        "saving_throw": {"ability": "dexterity", "dc": None,
                         "damage_on_fail": [
                             {"dice": "2d6", "damage_type": "fire", "bonus": 0}],
                         "damage_on_success": "half"},
        "upcast_damage_dice": "1d6",
    },

    # ── C3: recurring actions (cast once, re-use on later turns) ──────────
    "call_lightning": { # approx: bolt strikes one target, repeatable each turn
        "target_type": "one_creature",
        "saving_throw": {"ability": "dexterity", "dc": None,
                         "damage_on_fail": [
                             {"dice": "3d10", "damage_type": "lightning", "bonus": 0}],
                         "damage_on_success": "half"},
        "recurring_action_type": "action",
        "recurring_damage_dice": "3d10", "recurring_damage_type": "lightning",
        "upcast_damage_dice": "1d10",
    },
    "spiritual_weapon": {
        "target_type": "one_creature",
        "attack": {"name": "Spiritual Weapon", "attack_type": "melee_spell",
                   "ability": _PLACEHOLDER_ABILITY, "reach": 5,
                   "damage": [{"dice": "1d8", "damage_type": "force", "bonus": 0,
                               "ability_modifier": _PLACEHOLDER_ABILITY}]},
        "recurring_action_type": "bonus_action",
        "recurring_move_distance": 20,
        "upcast_damage_dice": "1d8", "upcast_damage_per_levels": 2,
    },
    "heat_metal": {     # approx: drop-weapon rider omitted
        "target_type": "one_creature",
        "attack": {"name": "Heat Metal", "attack_type": "ranged_spell",
                   "ability": _PLACEHOLDER_ABILITY, "reach": 5,
                   "range_normal": 60, "auto_hit": True,
                   "damage": [{"dice": "2d8", "damage_type": "fire", "bonus": 0}]},
        "recurring_action_type": "bonus_action",
        "recurring_damage_dice": "2d8", "recurring_damage_type": "fire",
        "recurring_auto_hit": True,
        "upcast_damage_dice": "1d8",
    },
    "flame_blade": {    # approx: the cast also swings (RAW: cast, then attack later)
        "target_type": "one_creature",
        "attack": {"name": "Flame Blade", "attack_type": "melee_spell",
                   "ability": _PLACEHOLDER_ABILITY, "reach": 5,
                   "damage": [{"dice": "3d6", "damage_type": "fire", "bonus": 0}]},
        "recurring_action_type": "action",
        "upcast_damage_dice": "1d6", "upcast_damage_per_levels": 2,
    },
    "arcane_hand": {    # approx: clenched fist mode only; grapple/shove modes dropped
        "target_type": "one_creature",
        "attack": {"name": "Arcane Hand", "attack_type": "melee_spell",
                   "ability": _PLACEHOLDER_ABILITY, "reach": 5,
                   "damage": [{"dice": "4d8", "damage_type": "force", "bonus": 0}]},
        "recurring_action_type": "action",
        "recurring_move_distance": 30,
        "upcast_damage_dice": "2d8",
    },

    # ── C3: teleports, summon, counterspell ───────────────────────────────
    "misty_step": {
        "target_type": "self",
        "teleport_range": 30,
    },
    "dimension_door": {
        "target_type": "self",
        "teleport_range": 500, "teleport_passenger": True,
    },
    "conjure_woodland_beings": {  # approx: option menu collapsed to one fey ally
        "target_type": "self",
        "summon_creature": "monsters/srd/dryad.json",
    },
    "counterspell": {
        "target_type": "one_creature",
        "is_counterspell": True, "counterspell_auto_level": 3,
    },
    # --- C4: reaction spells (engine hit-reaction popup, not the radial) ----
    "shield": {   # cast via the popup when hit; +5 AC persists until the
        "target_type": "self",        # start of the caster's next turn.
        "buff_effects": [             # approx: the Magic Missile auto-block
            {"stat": "ac", "modifier_type": "flat_bonus", "value": 5},
        ],                            # rider is dropped (auto-hit volleys
        "buff_duration_rounds": 1,    # never offer reactions).
    },
    # --- C4: decoys (engine hooks in resolve_attack_hit) ---------------------
    "mirror_image": {  # the buff's trigger charges ARE the duplicates;
        "target_type": "self",        # redirect d20 + image AC 10+DEX live
        "buff_effects": [             # engine-side. approx: a nat 20 only
            {"stat": "decoy_images", "modifier_type": "flat_bonus",
             "value": 3},             # pops an image; blindsight not modeled
        ],
        "buff_charges": 3,
        "buff_duration_rounds": 10,   # 1 minute, no concentration
    },
    "sanctuary": {     # attacker WIS save vs the ward DC or the attack is
        "target_type": "one_ally",    # lost (approx of choose-new-target);
        "buff_effects": [             # ward breaks when the warded creature
            {"stat": "sanctuary_ward", "modifier_type": "flat_bonus",
             "value": "DC"},          # attacks. "DC" baked by the bridge.
        ],
        "buff_duration_rounds": 10,
    },
    # --- C4: spell-granted on-hit riders (stat="on_hit_damage" buffs) -------
    # The rider rides the buff system: concentration cleanup, duration, and
    # save-to-end all come free. damage_type omitted = inherit the weapon's;
    # target_grants_to_attacker=True = the buff lives ON the marked target
    # and fires only for the buff's caster (Hunter's Mark pattern).
    "hunters_mark": {   # approx: bonus-action re-mark on kill dropped
        "target_type": "one_creature",
        "buff_effects": [
            {"stat": "on_hit_damage", "modifier_type": "flat_bonus",
             "value": "1d6", "scope": "weapon",
             "target_grants_to_attacker": True},
        ],
    },
    "divine_favor": {
        "target_type": "self",
        "buff_effects": [
            {"stat": "on_hit_damage", "modifier_type": "flat_bonus",
             "value": "1d4", "damage_type": "radiant", "scope": "weapon"},
        ],
    },
    "branding_smite": {  # next-hit only (buff_charges=1); approx: the
        "target_type": "self",       # invisibility-reveal rider is dropped
        "buff_effects": [            # and upcast (+1d6/level) not modeled
            {"stat": "on_hit_damage", "modifier_type": "flat_bonus",
             "value": "2d6", "damage_type": "radiant", "scope": "weapon"},
        ],
        "buff_charges": 1,
    },
}


def _parse_dice(expr: str) -> tuple[int, int, str | None] | None:
    """ "8d6" / "3d4 + 3" / "1d8 + MOD" → (count, size, flat|"MOD"|None)."""
    m = _DICE_RE.match(expr or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), m.group(3)


def _dice_str(count: int, size: int, flat: str | None) -> str:
    out = f"{count}d{size}"
    if flat:
        out += f"+{flat}"
    return out


def _range_feet(text: str) -> int:
    """SRD range text → feet. Touch fights at reach; Self anchors AoE on the caster."""
    t = (text or "").strip().lower()
    if t == "touch":
        return 5
    if t == "self":
        return 0
    m = re.match(r"^(\d+)\s*(?:feet|foot|ft)", t)
    return int(m.group(1)) if m else 30


def _upcast_delta(rows: dict[str, str], base_level: int) -> str | None:
    """Per-slot-step bonus dice from the slot-level table ("8d6"→"9d6" = "1d6").
    None when rows are missing, unparseable, or don't step uniformly."""
    base = _parse_dice(rows.get(str(base_level), ""))
    nxt = _parse_dice(rows.get(str(base_level + 1), ""))
    if base is None or nxt is None or base[1] != nxt[1]:
        return None
    step = nxt[0] - base[0]
    if step <= 0:
        return None
    # verify uniformity across the table (non-uniform scalers get no upcast)
    for lvl in range(base_level, 10):
        row = _parse_dice(rows.get(str(lvl), ""))
        if row is None:
            continue
        if row[0] != base[0] + step * (lvl - base_level) or row[1] != base[1]:
            return None
    return f"{step}d{base[1]}"


def map_spell(s: dict) -> tuple[dict | None, str | None]:
    """One source spell → (Action dict, None) or (None, skip_reason)."""
    action_type = _OK_TIMES.get(s.get("casting_time", ""))
    if action_type is None:
        return None, f"casting time {s.get('casting_time')!r} has no combat shape"

    level = int(s.get("level", 0))
    dmg = s.get("damage") or {}
    dmg_rows = dmg.get("damage_at_slot_level") or {}
    cantrip_rows = dmg.get("damage_at_character_level") or {}
    heal_rows = s.get("heal_at_slot_level") or {}
    dc = s.get("dc") or {}
    aoe = s.get("area_of_effect") or {}

    is_cantrip = level == 0
    base_dice = (cantrip_rows.get("1") if is_cantrip
                 else dmg_rows.get(str(level)))
    has_damage = bool(base_dice)
    dtype = ((dmg.get("damage_type") or {}).get("index") or "").lower()

    desc_list = s.get("desc") or []
    description = (desc_list[0] if desc_list else s["name"])[:300]

    base: dict = {
        "name": s["name"],
        "description": description,
        "action_type": action_type,
        "range": _range_feet(s.get("range", "")),
        "requires_concentration": bool(s.get("concentration")),
        "ai_priority": 6,
    }
    if not is_cantrip:
        base["spell_level"] = level
        base["resource_cost"] = {f"spell_slot_{level}": 1}
    else:
        base["spell_level"] = 0
        base["cantrip_scaling"] = True

    if aoe:
        target = _AOE_TARGET.get((aoe.get("type") or "").lower())
        if target is None:
            return None, f"area type {aoe.get('type')!r} not expressible"
        base["target_type"] = target
        base["area_size"] = int(aoe.get("size", 5))

    # --- curated rescues (B5) ------------------------------------------------
    curated = _CURATED.get(s["index"].replace("-", "_"))
    if curated is not None:
        base.update(curated)
        return base, None

    # --- healing -----------------------------------------------------------
    if heal_rows:
        row = heal_rows.get(str(max(level, 1)), "")
        parsed = _parse_dice(row)
        if parsed is not None:
            base["healing"] = _dice_str(*parsed)      # may carry literal +MOD
        elif row.strip().isdigit():
            base["healing"] = row.strip()             # flat heal (Heal = 70)
        else:
            return None, "healing row unparseable"
        base.setdefault("target_type", "one_ally")
        delta = _upcast_delta(
            {k: v.replace(" + MOD", "").replace("+MOD", "") for k, v in heal_rows.items()},
            max(level, 1))
        if delta:
            base["upcast_healing_dice"] = delta
        base["ai_priority"] = 7
        return base, None

    # --- spell-attack damage -------------------------------------------------
    if s.get("attack_type") and has_damage:
        parsed = _parse_dice(base_dice)
        if parsed is None or parsed[2] == "MOD":
            return None, "damage row unparseable"
        if not dtype:
            return None, "attack spell without a damage type"
        base.setdefault("target_type", "one_creature")
        base["attack"] = {
            "name": s["name"],
            "attack_type": f"{s['attack_type'].lower()}_spell",
            "ability": _PLACEHOLDER_ABILITY,           # bridge rewrites
            "reach": base["range"] if s["attack_type"].lower() == "melee" else 5,
            "range_normal": base["range"] if s["attack_type"].lower() == "ranged" else None,
            "damage": [{"dice": _dice_str(parsed[0], parsed[1], None),
                        "damage_type": dtype,
                        "bonus": int(parsed[2]) if parsed[2] and parsed[2] != "MOD" else 0}],
        }
        if not is_cantrip:
            delta = _upcast_delta(dmg_rows, level)
            if delta:
                base["upcast_damage_dice"] = delta
        return base, None

    # --- save-based damage ---------------------------------------------------
    if dc and has_damage:
        ability = ((dc.get("dc_type") or {}).get("index") or "").lower()
        success = (dc.get("dc_success") or "none").lower()
        if ability not in _ABILITY_LONG:
            return None, f"save ability {ability!r} unknown"
        if success not in ("half", "none"):
            return None, f"save success rule {success!r} not expressible"
        parsed = _parse_dice(base_dice)
        if parsed is None or parsed[2] == "MOD":
            return None, "damage row unparseable"
        if not dtype:
            return None, "save spell without a damage type"
        base.setdefault("target_type", "one_creature")
        base["saving_throw"] = {
            "ability": _ABILITY_LONG[ability],
            "dc": None,                                # bridge stamps caster DC
            "damage_on_fail": [{"dice": _dice_str(parsed[0], parsed[1], None),
                                "damage_type": dtype,
                                "bonus": int(parsed[2]) if parsed[2] and parsed[2] != "MOD" else 0}],
            "damage_on_success": success,
        }
        if not is_cantrip:
            delta = _upcast_delta(dmg_rows, level)
            if delta:
                base["upcast_damage_dice"] = delta
        return base, None

    if has_damage:
        return None, "auto-hit / zone / rider damage — no engine route from data yet"
    return None, "no structured combat mechanics in the source (control/buff/utility)"


def main(src: str, out_dir: str) -> int:
    spells = json.loads(Path(src).read_text(encoding="utf-8"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    generated: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for s in spells:
        spell_id = s["index"].replace("-", "_")
        mapped, reason = map_spell(s)
        if mapped is None:
            skipped[spell_id] = reason or "unknown"
            continue
        # Validation gate — every emitted file loads through the Arena's model.
        # (The literal MOD token in healing is bridge-substituted before play but
        # must already validate as a plain string here.)
        Action.model_validate(mapped)
        (out / f"{spell_id}.json").write_text(
            json.dumps(mapped, indent=2), encoding="utf-8")
        generated[spell_id] = s["name"]

    (out / "_manifest.json").write_text(
        json.dumps({"generated": generated, "skipped": skipped}, indent=2),
        encoding="utf-8")
    print(f"generated {len(generated)} spell actions, skipped {len(skipped)} "
          f"(see _manifest.json)")
    by_reason: dict[str, int] = {}
    for r in skipped.values():
        by_reason[r] = by_reason.get(r, 0) + 1
    for r, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        print(f"  skipped {n:3d}: {r}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python tools/gen_spells.py <srd-spells-raw.json> <out-dir>",
              file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
