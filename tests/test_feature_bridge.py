"""C1 — the feature bridge: sheet class features become engine machinery.

Three layers, mirroring the flow:
  1. the staging map (`features_for` / `feature_actions`) — names from the
     SRD ruleset data become engine Features and curated Actions, scaled to
     the character's level,
  2. resource-key normalization — story pools ("Ki") stage under the engine
     keys its presets hard-code ("ki_points"), and the result back-map
     reverses through the same function so CS5 ops keep display names,
  3. real-engine slices: Rage's +2 melee damage flows through the Arena's own
     attack resolution; Second Wind heals and spends the new fighter pool.
"""

from __future__ import annotations

from pathlib import Path

from arena.combat.stat_modifiers import get_extra_attack_count

from oubliette.combat.arena_bridge import (
    StagedResources,
    _spent_resources,
    build_encounter,
    character_to_player,
    enemy_from_template,
    result_to_combat_result,
)
from oubliette.combat.feature_bridge import (
    engine_resource_key,
    feature_actions,
    features_for,
)
from oubliette.combat.schemas import TerrainSpec
from oubliette.combat.templates import ENEMY_TEMPLATES
from oubliette.content.ruleset import load_ruleset
from oubliette.enums import Ability
from oubliette.rules import derive
from oubliette.state.models import Character, CharacterSheet, FeatureRef

RS = load_ruleset()


def _refs(*names_levels) -> list[FeatureRef]:
    return [FeatureRef(name=n, level=lv) for n, lv in names_levels]


def _fighter(level=5) -> Character:
    return Character(
        id="brom", name="Brom", kind="pc", level=level, hp=44, max_hp=44,
        abilities={Ability.STR: 16, Ability.DEX: 12, Ability.CON: 14},
        armor_class=18, attack_bonus=6, damage="1d8+3",
        sheet=CharacterSheet(
            race="human", char_class="fighter", background="acolyte",
            features=_refs(("Fighting Style", 1), ("Second Wind", 1),
                           ("Action Surge", 2), ("Extra Attack", 5))))


def _rogue(level=5) -> Character:
    return Character(
        id="scree", name="Scree", kind="pc", level=level, hp=33, max_hp=33,
        abilities={Ability.DEX: 16, Ability.CON: 12},
        armor_class=15, attack_bonus=6, damage="1d8+3",
        sheet=CharacterSheet(
            race="human", char_class="rogue", background="acolyte",
            features=_refs(("Sneak Attack", 1), ("Cunning Action", 2),
                           ("Uncanny Dodge", 5))))


def _monk(level=5) -> Character:
    return Character(
        id="li", name="Li", kind="pc", level=level, hp=38, max_hp=38,
        abilities={Ability.DEX: 16, Ability.WIS: 16, Ability.CON: 12},
        armor_class=16, attack_bonus=6, damage="1d6+3",
        sheet=CharacterSheet(
            race="human", char_class="monk", background="acolyte",
            features=_refs(("Martial Arts", 1), ("Ki", 2),
                           ("Unarmored Movement", 2), ("Extra Attack", 5),
                           ("Stunning Strike", 5))))


def _paladin(level=6) -> Character:
    return Character(
        id="sera", name="Sera", kind="pc", level=level, hp=52, max_hp=52,
        abilities={Ability.STR: 16, Ability.CHA: 16, Ability.CON: 14},
        armor_class=18, attack_bonus=6, damage="1d8+3",
        sheet=CharacterSheet(
            race="human", char_class="paladin", background="acolyte",
            spellcasting_ability=Ability.CHA,
            features=_refs(("Lay on Hands", 1), ("Divine Smite", 2),
                           ("Extra Attack", 5), ("Aura of Protection", 6))))


def _druid(level=2) -> Character:
    return Character(
        id="thorn", name="Thorn", kind="pc", level=level, hp=30, max_hp=30,
        abilities={Ability.WIS: 16, Ability.DEX: 12, Ability.CON: 14},
        armor_class=14, attack_bonus=4, damage="1d8+1",
        sheet=CharacterSheet(
            race="human", char_class="druid", background="acolyte",
            spellcasting_ability=Ability.WIS,
            features=_refs(("Druidic", 1), ("Spellcasting", 1),
                           ("Wild Shape", 2))))


def _barbarian(level=3) -> Character:
    return Character(
        id="grog", name="Grog", kind="pc", level=level, hp=40, max_hp=40,
        abilities={Ability.STR: 16, Ability.DEX: 14, Ability.CON: 16},
        armor_class=14, attack_bonus=5, damage="1d1",   # deterministic die
        sheet=CharacterSheet(
            race="human", char_class="barbarian", background="acolyte",
            features=_refs(("Rage", 1), ("Unarmored Defense", 1),
                           ("Reckless Attack", 2))))


# --- 1. the staging map -----------------------------------------------------

def test_extra_attack_stages_and_scales_with_fighter_level():
    assert get_extra_attack_count(character_to_player(_fighter(5), None, RS)) == 2
    assert get_extra_attack_count(character_to_player(_fighter(11), None, RS)) == 3
    assert get_extra_attack_count(character_to_player(_fighter(20), None, RS)) == 4


def test_sneak_attack_rider_scales_and_uncanny_dodge_stages():
    features = {f.name: f for f in features_for(_rogue(5))}
    rider = features["Sneak Attack"].on_hit_rider
    assert rider.damage_dice == "3d6" and rider.once_per_turn is True
    assert rider.trigger.value == "automatic"
    assert features["Uncanny Dodge"].damage_reduction_flat_half is True
    # Cunning Action is deliberately NOT staged yet (needs the engine hook)
    assert "Cunning Action" not in features


def test_divine_smite_auto_upgrades_and_aura_stages():
    features = {f.name: f for f in features_for(_paladin(6))}
    rider = features["Divine Smite"].on_hit_rider
    assert rider is not None                       # the engine validator filled it
    assert rider.damage_dice == "2d8" and rider.resource_type == "spell_slot"
    aura = features["Aura of Protection"]
    assert aura.aura_range == 10 and aura.aura_save_bonus_ability == "charisma"


def test_monk_kit_stages_flurry_stunning_strike_and_speed():
    pc = _monk(5)
    features = {f.name: f for f in features_for(pc)}
    assert features["Stunning Strike"].on_hit_rider.resource_type == "ki_points"
    assert features["Unarmored Movement"].bonus_speed == 10
    _, bonus = feature_actions(pc, "dexterity")
    by_name = {a.name: a for a in bonus}
    flurry = by_name["Flurry of Blows"]
    assert flurry.resource_cost == {"ki_points": 1}
    assert flurry.target_count == 2
    assert flurry.attack.damage[0].dice == "1d6"   # martial die at L5
    assert by_name["Patient Defense"].conditions_applied == ["dodging"]


def test_unarmored_defense_and_fighting_style_are_not_staged():
    # Story-side AC already includes Unarmored Defense; staging it would
    # double-count. Fighting Style has no stored choice to bake.
    assert features_for(_barbarian()) == [
        f for f in features_for(_barbarian()) if f.name not in
        ("Unarmored Defense", "Fighting Style")
    ]


# --- 2. resource-key normalization ------------------------------------------

def test_engine_resource_keys():
    assert engine_resource_key("Ki") == "ki_points"
    assert engine_resource_key("Lay on Hands") == "lay_on_hands"
    assert engine_resource_key("Action Surge") == "action_surge"
    assert engine_resource_key("Channel Divinity") == "channel_divinity"
    assert engine_resource_key("Rage") == "rage"


def test_fighter_pools_stage_under_engine_keys():
    creature = character_to_player(_fighter(5), None, RS)
    assert creature.class_resources["second_wind"] == 1
    assert creature.class_resources["action_surge"] == 1
    assert "Second Wind" not in creature.class_resources


def test_fighter_resources_exist_story_side():
    pools = derive.class_resources(_fighter(17), RS)
    assert pools["Second Wind"]["max"] == 1
    assert pools["Action Surge"]["max"] == 2       # 2 uses at L17
    assert pools["Indomitable"]["max"] == 3


def test_spent_resources_reverse_maps_engine_keys_to_story_names():
    staged = StagedResources(resources_max={"Ki": 5},
                             resources_used_full={"Ki": 1})
    slots, used = _spent_resources(staged, {"class_resources": {"ki_points": 2}})
    assert used == {"Ki": 3}                       # 5 max, 2 remaining → 3 used


# --- 3. real-engine slices ---------------------------------------------------

def _manager_for(pc: Character):
    from arena.combat.manager import CombatManager

    plan = build_encounter([pc], [enemy_from_template(ENEMY_TEMPLATES["bandit"])],
                           TerrainSpec(), ruleset=RS)
    cm = CombatManager()
    cm.load_encounter(plan.encounter, Path("."))
    pc_cid, combatant = next((cid, c) for cid, c in cm.combatants.items()
                             if c.team == "player")
    en_cid, enemy = next((cid, c) for cid, c in cm.combatants.items()
                         if c.team == "enemy")
    return plan, cm, pc_cid, combatant.creature, en_cid, enemy.creature


def test_rage_buffs_apply_and_boost_melee_damage_through_the_engine():
    from arena.combat.actions import resolve_attack, resolve_effect

    plan, cm, pc_cid, grog, en_cid, bandit = _manager_for(_barbarian(3))
    rage = next(a for a in grog.bonus_actions if a.name == "Rage")
    result = resolve_effect(grog, pc_cid, grog, pc_cid, rage, cm.grid)
    assert result.success
    assert grog.class_resources["rage"] == 2       # pool of 3, one spent
    resistances = {m.value for b in grog.active_buffs for m in []} or {
        m.value for b in grog.active_buffs for m in b.modifiers
        if m.stat == "damage_resistance"}
    assert {"bludgeoning", "piercing", "slashing"} <= resistances

    # The attack die is 1d1: without Rage damage is 1 (2 on a crit); with the
    # +2 buff every hit deals at least 3. Move the bandit adjacent first —
    # spawns are on opposite sides of the grid and the attack has 5 ft reach.
    from arena.grid.coordinates import HexCoord

    grog_pos = cm.grid.find_creature(pc_cid)
    bandit_pos = cm.grid.find_creature(en_cid)
    cm.grid.remove_creature(bandit_pos)
    cm.grid.place_creature(HexCoord(grog_pos.q + 1, grog_pos.r), en_cid)

    bandit.armor_class = 1
    hp_before = bandit.current_hit_points
    for _ in range(20):                            # until a non-miss lands
        res = resolve_attack(grog, pc_cid, bandit, en_cid,
                             grog.actions[0], cm.grid)
        if any("HIT" in (e.message or "") for e in res.events) \
                or bandit.current_hit_points < hp_before:
            break
    dealt = hp_before - bandit.current_hit_points
    assert dealt >= 3                              # 1d1 + rage 2


def _activate(cm, pc_cid):
    """Advance the loaded encounter until it's the PC's turn."""
    cm.roll_initiative()
    cm.begin_combat()
    for _ in range(10):
        active = cm.active_combatant
        if active is not None and active.creature_id == pc_cid:
            return
        cm.end_turn()
    raise AssertionError("PC never became active")


def test_cunning_action_dash_works_with_the_action_slot_already_spent():
    plan, cm, pc_cid, scree, _, _ = _manager_for(_rogue(5))
    _activate(cm, pc_cid)
    cm.turn_resources.has_used_action = True      # the whole point: action is gone
    before = cm.movement.remaining_movement
    dash = next(a for a in scree.bonus_actions if a.name == "Cunning Action: Dash")
    event = cm.execute_data_standard_action(dash)
    assert event is not None
    assert cm.movement.remaining_movement > before
    assert cm.turn_resources.has_used_bonus_action is True
    assert cm.turn_resources.has_used_action is True   # untouched by the dash


def test_step_of_the_wind_costs_a_ki_point():
    plan, cm, pc_cid, li, _, _ = _manager_for(_monk(5))
    _activate(cm, pc_cid)
    assert li.class_resources["ki_points"] == 5
    sotw = next(a for a in li.bonus_actions
                if a.name == "Step of the Wind: Disengage")
    event = cm.execute_data_standard_action(sotw)
    assert event is not None
    assert cm.turn_resources.is_disengaging is True
    assert li.class_resources["ki_points"] == 4
    # A second use the same turn is blocked — the bonus action is spent
    assert cm.execute_data_standard_action(sotw) is None
    assert li.class_resources["ki_points"] == 4    # and nothing was deducted


def test_wild_shape_forms_gate_by_druid_level():
    forms = lambda lv: [a.name for a in feature_actions(_druid(lv), "wisdom")[0]
                        if a.name.startswith("Wild Shape")]
    assert forms(2) == ["Wild Shape: Wolf"]
    assert forms(4) == ["Wild Shape: Wolf", "Wild Shape: Crocodile"]
    assert len(forms(8)) == 3


def test_wild_shape_transforms_and_reverts_through_the_engine():
    plan, cm, pc_cid, thorn, _, _ = _manager_for(_druid(2))
    _activate(cm, pc_cid)
    assert thorn.class_resources["wild_shape"] == 2

    ws = next(a for a in thorn.actions if a.name == "Wild Shape: Wolf")
    cm.select_action(ws)
    result = cm.execute_summon(cm.combatants[pc_cid].position)
    assert result.success
    assert thorn.class_resources["wild_shape"] == 1
    assert pc_cid in cm.stored_creatures                 # original safely stored
    wolf_id = next(sid for sid, summoner in cm.summon_links.items()
                   if summoner == pc_cid)
    wolf = cm.combatants[wolf_id]
    assert wolf.team == "player" and wolf.creature.name == "Wolf"
    assert cm.combatants[pc_cid].position is None        # druid is off the grid

    # The wolf drops to 0 HP — the druid reverts at the wolf's position.
    wolf_pos = wolf.position
    wolf.creature.current_hit_points = 0
    cm._check_summon_death(wolf_id)
    assert pc_cid not in cm.stored_creatures
    assert cm.combatants[pc_cid].creature.name == "Thorn"
    assert cm.combatants[pc_cid].position == wolf_pos
    assert wolf_id not in cm.combatants


def test_second_wind_heals_spends_pool_and_rounds_trip():
    from arena.combat.actions import resolve_effect
    from arena.handoff import build_result

    plan, cm, pc_cid, brom, _, _ = _manager_for(_fighter(5))
    brom.current_hit_points = 20
    sw = next(a for a in brom.bonus_actions if a.name == "Second Wind")
    result = resolve_effect(brom, pc_cid, brom, pc_cid, sw, cm.grid)
    assert result.success
    assert brom.current_hit_points >= 26           # 1d10+5 heals at least 6
    assert brom.class_resources["second_wind"] == 0

    # The genuine v2 result writes the spend back under the STORY name.
    combat_result = result_to_combat_result(build_result(cm), plan)
    assert combat_result.resources_used_final["brom"]["Second Wind"] == 1
    assert combat_result.resources_used_final["brom"]["Action Surge"] == 0
