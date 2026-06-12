"""B4 — the spell library and the caster kit.

Three layers, mirroring how the content flows:
  1. the generated library itself (structural gate + iconic spot checks),
  2. the bridge bake (`spell_actions` / `character_to_player`) — placeholder
     ability, save DC, and the MOD healing token all resolved to THIS caster,
  3. the real-engine slice: a cleric casts Cure Wounds through the Arena's own
     `resolve_effect` — the heal lands, the slot is spent from the B2-staged
     ledger, and the genuine handoff v2 result writes `spell_slots_used` back.
"""

from __future__ import annotations

import json
from pathlib import Path

from arena.models.actions import Action

from oubliette.combat.arena_bridge import (
    arena_spell_action,
    build_encounter,
    character_to_player,
    enemy_from_template,
    result_to_combat_result,
    spell_actions,
)
from oubliette.combat.schemas import TerrainSpec
from oubliette.combat.templates import ENEMY_TEMPLATES
from oubliette.content.ruleset import load_ruleset
from oubliette.enums import Ability
from oubliette.state.models import Character, CharacterSheet

RS = load_ruleset()
SPELL_DIR = Path(__file__).resolve().parents[1] / "arena" / "data" / "spells" / "srd"


def _cleric(level=3, slots_used=None) -> Character:
    """L3 cleric: WIS +3, prof +2 → spell DC 13; slots {1: 4, 2: 2}."""
    return Character(
        id="mira", name="Mira", kind="pc", level=level, hp=20, max_hp=24,
        abilities={Ability.WIS: 16, Ability.STR: 12, Ability.DEX: 12,
                   Ability.CON: 14},
        armor_class=16, attack_bonus=4, damage="1d8+1",
        spell_slots_used=slots_used or {},
        sheet=CharacterSheet(
            race="human", char_class="cleric", background="acolyte",
            spellcasting_ability=Ability.WIS,
            saving_throw_proficiencies={Ability.WIS, Ability.CHA},
            cantrips_known=["sacred_flame"],
            spells_prepared=["cure_wounds", "guiding_bolt", "bless"],
        ))


# --- 1. the generated library --------------------------------------------

def test_every_generated_spell_file_is_a_valid_arena_action():
    files = [f for f in SPELL_DIR.glob("*.json") if not f.name.startswith("_")]
    assert len(files) >= 50                       # the expressible combat core
    for f in files:
        Action.model_validate(json.loads(f.read_text(encoding="utf-8")))


def test_manifest_accounts_for_every_srd_spell():
    manifest = json.loads((SPELL_DIR / "_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["generated"]) + len(manifest["skipped"]) == 319
    # the genuinely freeform spells are skipped deliberately, not silently
    assert "wish" in manifest["skipped"]
    assert "prestidigitation" in manifest["skipped"]
    # B5 curated rescues moved out of the skip list
    assert "magic_missile" in manifest["generated"]
    assert "scorching_ray" in manifest["generated"]
    assert "mage_armor" in manifest["generated"]
    # C3 curation wave: the control/buff/zone families are IN now
    for spell in ("hold_person", "bless", "haste", "spirit_guardians",
                  "misty_step", "counterspell", "web", "spiritual_weapon"):
        assert spell in manifest["generated"], spell
    # C4 primitives: on-hit riders, the Shield reaction, decoys
    for spell in ("hunters_mark", "divine_favor", "branding_smite", "shield",
                  "mirror_image", "sanctuary"):
        assert spell in manifest["generated"], spell


def test_fire_bolt_is_a_scaling_attack_cantrip():
    a = arena_spell_action("fire_bolt")
    assert a.spell_level == 0 and a.cantrip_scaling is True
    assert not a.resource_cost
    assert a.attack.attack_type == "ranged_spell"
    assert a.attack.damage[0].dice == "1d10"
    assert a.attack.damage[0].damage_type.value == "fire"


def test_fireball_is_a_save_for_half_sphere_with_upcast():
    a = arena_spell_action("fireball")
    assert a.spell_level == 3 and a.resource_cost == {"spell_slot_3": 1}
    assert a.target_type.value == "area_sphere" and a.area_size == 20
    assert a.range == 150
    st = a.saving_throw
    assert st.ability == "dexterity" and st.dc is None      # bridge stamps DC
    assert st.damage_on_fail[0].dice == "8d6"
    assert st.damage_on_success == "half"
    assert a.upcast_damage_dice == "1d6"


def test_cure_wounds_carries_the_mod_token_and_upcast():
    a = arena_spell_action("cure_wounds")
    assert a.healing == "1d8+MOD"                 # bridge substitutes
    assert a.upcast_healing_dice == "1d8"
    assert a.target_type.value == "one_ally"
    assert a.resource_cost == {"spell_slot_1": 1}


def test_unknown_or_skipped_spell_loads_as_none():
    assert arena_spell_action("mage_hand") is None   # freeform — washed
    assert arena_spell_action("no_such_spell_xyz") is None


# --- B5 curated rescues -----------------------------------------------------

def test_magic_missile_is_an_auto_hit_volley():
    a = arena_spell_action("magic_missile")
    assert a.attack.auto_hit is True
    assert a.target_count == 3 and a.upcast_target_count == 1   # +1 dart/level
    assert a.attack.damage[0].dice == "1d4" and a.attack.damage[0].bonus == 1
    assert a.attack.damage[0].damage_type.value == "force"
    assert a.resource_cost == {"spell_slot_1": 1}


def test_scorching_ray_is_a_three_ray_attack_spell():
    a = arena_spell_action("scorching_ray")
    assert a.attack.auto_hit is False             # each ray rolls to hit
    assert a.attack.attack_type == "ranged_spell"
    assert a.target_count == 3 and a.upcast_target_count == 1
    assert a.attack.damage[0].dice == "2d6"
    assert a.resource_cost == {"spell_slot_2": 1}


def test_mage_armor_is_an_ac_set_self_buff():
    a = arena_spell_action("mage_armor")
    (buff,) = a.buff_effects
    assert buff.stat == "ac" and buff.modifier_type == "set"
    assert buff.value == "13+DEX"                 # engine evaluates per-wearer
    assert a.target_type.value == "self"
    assert a.requires_concentration is False
    assert a.resource_cost == {"spell_slot_1": 1}


# --- 2. the bridge bake ----------------------------------------------------

def test_caster_kit_is_baked_with_this_casters_numbers():
    actions = {a.name: a for a in spell_actions(_cleric())}
    # C3: Bless joined the library — the whole prepared list is expressible now
    assert set(actions) == {"Sacred Flame", "Cure Wounds", "Guiding Bolt", "Bless"}
    assert actions["Sacred Flame"].saving_throw.dc == 13      # 8 + 2 + 3
    assert actions["Guiding Bolt"].attack.ability == "wisdom"
    assert actions["Cure Wounds"].healing == "1d8+3"


def test_non_casters_get_no_spell_actions():
    fighter = Character(
        id="f", name="Brom", kind="pc", level=3, hp=30, max_hp=30,
        armor_class=16, attack_bonus=5, damage="1d10+3",
        sheet=CharacterSheet(race="human", char_class="fighter",
                             background="acolyte"))
    assert spell_actions(fighter) == []


def test_player_mapping_carries_kit_saves_speed_and_casting_ability():
    creature = character_to_player(_cleric(), None, RS)
    names = [a.name for a in creature.actions]
    assert names[0] == "Attack"                   # basic attack stays first
    assert {"Sacred Flame", "Cure Wounds", "Guiding Bolt"} <= set(names)
    assert creature.spellcasting_ability == "wisdom"
    assert creature.saving_throw_proficiencies == ["charisma", "wisdom"]
    assert creature.speed == {"walk": 30}
    assert creature.spell_slots == {1: 4, 2: 2}   # B2 staging still intact


def test_sanctuary_ward_dc_bakes_to_the_caster():
    """C4: the "DC" token in buff values becomes this caster's spell DC
    (Sanctuary's ward is checked at attack time, long after the cast)."""
    cleric = _cleric()
    cleric.sheet.spells_prepared = ["sanctuary"]
    actions = {a.name: a for a in spell_actions(cleric)}
    ward = actions["Sanctuary"].buff_effects[0]
    assert ward.stat == "sanctuary_ward"
    assert ward.value == 13                       # 8 + 2 prof + 3 WIS


def test_shield_stages_as_a_reaction_not_an_action():
    """C4: reaction spells route to creature.reactions — the engine's
    hit-reaction popup casts them; the radial must never offer them."""
    wiz = Character(
        id="skid", name="Skid", kind="pc", level=1, hp=8, max_hp=8,
        abilities={Ability.INT: 16, Ability.DEX: 12, Ability.CON: 12},
        armor_class=12, attack_bonus=4, damage="1d4+1",
        sheet=CharacterSheet(
            race="gnome", char_class="wizard", background="acolyte",
            spellcasting_ability=Ability.INT,
            cantrips_known=["fire_bolt"],
            spells_known=["shield", "burning_hands"],
        ))
    creature = character_to_player(wiz, None, RS)
    action_names = [a.name for a in creature.actions]
    reaction_names = [a.name for a in creature.reactions]
    assert "Shield" in reaction_names
    assert "Shield" not in action_names
    assert "Burning Hands" in action_names        # turn spells stay put


# --- 3. the real-engine cast slice (B2 lights up) --------------------------

def test_cleric_casts_cure_wounds_slot_spends_and_rounds_trip():
    from arena.combat.actions import resolve_effect
    from arena.combat.manager import CombatManager
    from arena.handoff import build_result

    pc = _cleric(slots_used={1: 1})               # one slot already gone
    plan = build_encounter([pc], [enemy_from_template(ENEMY_TEMPLATES["bandit"])],
                           TerrainSpec(), ruleset=RS)
    cm = CombatManager()
    cm.load_encounter(plan.encounter, Path("."))
    pc_cid, combatant = next((cid, c) for cid, c in cm.combatants.items()
                             if c.team == "player")
    creature = combatant.creature
    assert creature.class_resources["spell_slot_1"] == 3      # staged, not full

    creature.current_hit_points = 10              # wounded
    cure = next(a for a in creature.actions if a.name == "Cure Wounds")
    result = resolve_effect(creature, pc_cid, creature, pc_cid, cure, cm.grid)
    assert result.success
    assert creature.current_hit_points >= 14      # 1d8+3 heals at least 4
    assert creature.class_resources["spell_slot_1"] == 2      # the cast spent it

    # the genuine v2 result maps the spend back onto the CS5 tracker shape
    combat_result = result_to_combat_result(build_result(cm), plan)
    assert combat_result.slots_used_final["mira"][1] == 2     # 1 staged + 1 cast
    assert combat_result.slots_used_final["mira"][2] == 0
