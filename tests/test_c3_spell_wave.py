"""C3 — the spell curation wave: 72 control/buff/zone/recurring/teleport
spells added to the Arena library as curated overlays (tools/gen_spells.py
_CURATED), riding existing engine primitives.

Three layers again: emitted data shapes, the bridge bake (new: damage
ability_modifier + temp-HP MOD), and real-engine slices for the load-bearing
semantics — save-or-paralyzed with re-saves (Hold Person), the beneficial-AoE
gate (Bless must not buff enemies), and save-gated debuffs (Bane applies only
on a failed save).
"""

from __future__ import annotations

from pathlib import Path

from oubliette.combat.arena_bridge import (
    arena_spell_action,
    build_encounter,
    character_to_player,
    enemy_from_template,
    spell_actions,
)
from oubliette.combat.schemas import TerrainSpec
from oubliette.combat.templates import ENEMY_TEMPLATES
from oubliette.content.ruleset import load_ruleset
from oubliette.enums import Ability
from oubliette.state.models import Character, CharacterSheet

RS = load_ruleset()


def _caster(spells: list[str], char_class="cleric",
            ability=Ability.WIS, level=5) -> Character:
    return Character(
        id="mira", name="Mira", kind="pc", level=level, hp=30, max_hp=30,
        abilities={ability: 16, Ability.CON: 14, Ability.DEX: 12},
        armor_class=16, attack_bonus=4, damage="1d8+1",
        sheet=CharacterSheet(
            race="human", char_class=char_class, background="acolyte",
            spellcasting_ability=ability, spells_prepared=spells))


# --- 1. emitted data shapes --------------------------------------------------

def test_hold_person_is_save_or_paralyzed_with_upcast_targets():
    a = arena_spell_action("hold_person")
    assert a.saving_throw.ability == "wisdom" and a.saving_throw.dc is None
    assert a.saving_throw.conditions_on_fail == ["paralyzed"]
    assert a.requires_concentration is True
    assert a.upcast_target_count == 1
    assert a.resource_cost == {"spell_slot_2": 1}


def test_bless_rolls_a_real_d4_and_is_concentration():
    a = arena_spell_action("bless")
    mods = {(b.stat, b.value) for b in a.buff_effects}
    assert ("attack_rolls", "1d4") in mods
    assert ("saving_throws", "1d4") in mods
    assert a.requires_concentration is True
    assert a.saving_throw is None                  # beneficial — no save


def test_haste_and_slow_are_mirrored_buff_packages():
    haste = arena_spell_action("haste")
    assert {(b.stat, b.modifier_type) for b in haste.buff_effects} == {
        ("speed", "multiply"), ("ac", "flat_bonus"),
        ("saving_throws", "advantage")}
    slow = arena_spell_action("slow")
    assert slow.saving_throw.ability == "wisdom"   # save-gated debuff
    assert any(b.stat == "speed" and b.value == 0.5 for b in slow.buff_effects)


def test_web_restrains_and_lays_difficult_terrain():
    a = arena_spell_action("web")
    assert a.saving_throw.conditions_on_fail == ["restrained"]
    assert a.terrain_modification == "difficult"
    assert a.target_type.value == "area_cube" and a.area_size == 20


def test_spirit_guardians_is_a_moving_zone():
    a = arena_spell_action("spirit_guardians")
    assert a.zone_follows_caster is True
    assert a.requires_concentration is True
    assert a.saving_throw.damage_on_fail[0].dice == "3d8"
    assert a.upcast_damage_dice == "1d8"


def test_misty_step_and_dimension_door_teleport():
    ms = arena_spell_action("misty_step")
    assert ms.teleport_range == 30 and ms.action_type.value == "bonus_action"
    dd = arena_spell_action("dimension_door")
    assert dd.teleport_range == 500 and dd.teleport_passenger is True


def test_counterspell_is_a_reaction_interrupt():
    a = arena_spell_action("counterspell")
    assert a.is_counterspell is True and a.counterspell_auto_level == 3
    assert a.action_type.value == "reaction"


def test_power_words_use_hp_thresholds():
    kill = arena_spell_action("power_word_kill")
    assert kill.hp_threshold == 100 and kill.hp_threshold_effect == "kill"
    stun = arena_spell_action("power_word_stun")
    assert stun.hp_threshold == 150
    assert stun.hp_threshold_condition == "stunned"


# --- 2. the bridge bake ------------------------------------------------------

def test_spiritual_weapon_damage_rides_the_casting_modifier():
    actions = {a.name: a for a in spell_actions(_caster(["spiritual_weapon"]))}
    sw = actions["Spiritual Weapon"]
    assert sw.attack.ability == "wisdom"
    assert sw.attack.damage[0].ability_modifier == "wisdom"   # 1d8 + WIS
    assert sw.recurring_action_type == "bonus_action"


def test_heroism_temp_hp_bakes_the_casting_modifier():
    actions = {a.name: a for a in spell_actions(
        _caster(["heroism"], char_class="paladin", ability=Ability.CHA))}
    assert actions["Heroism"].grants_temporary_hp == "3"      # CHA 16 → +3


# --- 3. real-engine slices ---------------------------------------------------

def _combat_with(pc, spell_name):
    from arena.combat.manager import CombatManager

    plan = build_encounter([pc], [enemy_from_template(ENEMY_TEMPLATES["bandit"])],
                           TerrainSpec(), ruleset=RS)
    cm = CombatManager()
    cm.load_encounter(plan.encounter, Path("."))
    pc_cid, pc_comb = next((cid, c) for cid, c in cm.combatants.items()
                           if c.team == "player")
    en_cid, en_comb = next((cid, c) for cid, c in cm.combatants.items()
                           if c.team == "enemy")
    spell = next(a for a in pc_comb.creature.actions if a.name == spell_name)
    return cm, pc_cid, pc_comb.creature, en_cid, en_comb.creature, spell


def test_hold_person_paralyzes_until_the_save_lands():
    from arena.combat.actions import resolve_effect
    from arena.grid.coordinates import HexCoord

    cm, pc_cid, mira, en_cid, bandit, hold = _combat_with(
        _caster(["hold_person"]), "Hold Person")
    # Spawns sit on opposite grid edges — bring the bandit into the 60-ft range
    pos = cm.grid.find_creature(en_cid)
    cm.grid.remove_creature(pos)
    mira_pos = cm.grid.find_creature(pc_cid)
    cm.grid.place_creature(HexCoord(mira_pos.q + 2, mira_pos.r), en_cid)
    hold.saving_throw.dc = 30                      # force the failure
    result = resolve_effect(mira, pc_cid, bandit, en_cid, hold, cm.grid)
    assert result.success
    conds = {c.condition.value: c for c in bandit.active_conditions}
    assert "paralyzed" in conds
    assert conds["paralyzed"].save_to_end == "wisdom"   # re-save each turn
    assert mira.class_resources["spell_slot_2"] == 2    # L5 cleric: 3 - 1 cast


def test_bless_buffs_allies_only_through_the_aoe_gate():
    cm, pc_cid, mira, en_cid, bandit, bless = _combat_with(
        _caster(["bless"]), "Bless")
    cm.selected_action = bless
    targets = cm._resolve_effect_targets(bless, cm.combatants[pc_cid], en_cid)
    assert en_cid not in targets                   # the enemy is never blessed


def test_bane_applies_only_on_a_failed_save():
    from arena.combat.actions import resolve_effect

    cm, pc_cid, mira, en_cid, bandit, bane = _combat_with(
        _caster(["bane"]), "Bane")
    bane.saving_throw.dc = -10                     # guaranteed save
    resolve_effect(mira, pc_cid, bandit, en_cid, bane, cm.grid)
    assert not bandit.active_buffs                 # saved → no debuff

    bane.saving_throw.dc = 30                      # guaranteed failure
    resolve_effect(mira, pc_cid, bandit, en_cid, bane, cm.grid)
    assert any(b.name == "Bane" for b in bandit.active_buffs)
    debuff = next(b for b in bandit.active_buffs if b.name == "Bane")
    assert debuff.save_to_end == "charisma"        # re-save rides the buff
