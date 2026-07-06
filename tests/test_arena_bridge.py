"""Combat Stage 2 — the Arena bridge (`oubliette.combat.arena_bridge`).

Pure data-mapping, both directions:
  * Oubliette `Character` / `StatBlock` → Arena creatures,
    with the basic attack reproducing Oubliette's flat `attack_bonus` EXACTLY
    (asserted through the Arena's own `get_attack_modifier`) and real ability
    scores carried across.
  * a synthetic Arena handoff result dict → an Oubliette `CombatResult`, with
    absolute HP write-back for persistent entities only, fallen-enemy XP + loot.
"""

from __future__ import annotations

import pytest

from arena.combat.actions import get_attack_modifier
from arena.models.character import PlayerCharacter
from arena.models.encounter import Encounter
from arena.models.monster import Monster

from oubliette.combat.arena_bridge import (
    EnemyInstance,
    build_encounter,
    character_to_player,
    consumable_actions,
    enemy_from_character,
    enemy_from_statblock,
    result_to_combat_result,
    statblock_to_monster,
    weapon_kit_actions,
)
from oubliette.combat.schemas import ConsumedItem, TerrainSpec
from oubliette.content.ruleset import load_ruleset
from oubliette.content.schemas import Action as ContentAction
from oubliette.content.schemas import LootEntry, StatBlock
from oubliette.content.srd_schemas import ConsumableMechanics, SrdEquipment
from oubliette.enums import Ability
from oubliette.state.models import Character, CharacterSheet, ItemStack

RS = load_ruleset()


# --- fixtures ------------------------------------------------------------

def _goblin_statblock() -> StatBlock:
    return StatBlock(
        id="goblin", name="Goblin", size="Small", type="humanoid (goblinoid)",
        alignment="neutral evil", cr=0.25,
        abilities={"str": 8, "dex": 14, "con": 10, "int": 10, "wis": 8, "cha": 8},
        hp=7, armor_class=15, attack_bonus=4, damage="1d6+2", xp=50,
        damage_immunities=["poison"],
        actions=[ContentAction(name="Scimitar", damage="1d6+2", damage_type="slashing", attack_bonus=4)],
        loot=[LootEntry(gold=5)],
    )


def _pc(attack_bonus: int = 5, **over) -> Character:
    base = dict(
        id="hero", name="Elara", kind="pc", level=3,
        abilities={"str": 12, "dex": 16, "con": 14, "int": 10, "wis": 12, "cha": 8},
        hp=24, max_hp=27, armor_class=15, attack_bonus=attack_bonus, damage="1d8+3",
        sheet=CharacterSheet(race="Elf", char_class="Ranger", background="Outlander", size="Medium"),
    )
    base.update(over)
    return Character(**base)


def _carrier_attack(creature) -> int:
    """The Arena's actual to-hit for the mapped basic attack."""
    action = creature.actions[0]
    return get_attack_modifier(creature, action.attack, action)


# --- OUT: creature mappers (to-hit exactness is the contract) ------------

def test_statblock_to_monster_carries_identity_and_exact_to_hit():
    mon = statblock_to_monster(_goblin_statblock())
    assert isinstance(mon, Monster)
    assert mon.ability_scores.dexterity == 14 and mon.ability_scores.strength == 8
    assert mon.armor_class == 15 and mon.max_hit_points == 7
    assert mon.challenge_rating == 0.25 and mon.experience_points == 50
    assert mon.creature_type.value == "humanoid" and mon.size.value == "small"
    assert "poison" in mon.damage_immunities
    # to-hit lands on exactly +4, via the natural DEX decomposition
    assert _carrier_attack(mon) == 4
    assert mon.actions[0].attack.ability == "dexterity"
    # damage is the literal dice + flat bonus, no ability modifier mixed in
    dmg = mon.actions[0].attack.damage[0]
    assert dmg.dice == "1d6" and dmg.bonus == 2 and dmg.ability_modifier is None
    assert dmg.damage_type.value == "slashing"


def test_character_to_player_carries_sheet_and_exact_to_hit():
    pc = character_to_player(_pc(attack_bonus=6))
    assert isinstance(pc, PlayerCharacter)
    assert pc.character_class == "Ranger" and pc.race == "Elf" and pc.level == 3
    assert pc.ability_scores.dexterity == 16
    assert pc.max_hit_points == 27 and pc.current_hit_points == 24
    assert pc.is_player_controlled is True
    assert _carrier_attack(pc) == 6


@pytest.mark.parametrize("attack_bonus", [2, 5, 7, 11])
def test_to_hit_is_exact_across_the_reachable_range(attack_bonus):
    """Even when the flat bonus does not decompose into the highest stat's mod +
    a real proficiency, the solver still lands the to-hit exactly as long as the
    target is reachable (mod + prof, prof in [2, 9]) for these scores."""
    pc = character_to_player(_pc(attack_bonus=attack_bonus))
    assert _carrier_attack(pc) == attack_bonus


@pytest.mark.parametrize("attack_bonus,expected", [(0, 1), (14, 12)])
def test_to_hit_falls_back_to_closest_when_unreachable(attack_bonus, expected):
    """Targets outside [min_mod+2, max_mod+9] for the creature's real scores
    cannot be hit exactly (here str12/dex16: reachable is [1, 12]); the mapper
    lands on the closest achievable to-hit rather than corrupting the scores."""
    pc = character_to_player(_pc(attack_bonus=attack_bonus))
    assert _carrier_attack(pc) == expected


# --- encounter assembly --------------------------------------------------

def test_build_encounter_assembles_valid_teams_positions_and_backmap():
    party = [_pc(), _pc(id="thorin", name="Thorin")]
    npc_foe = Character(id="thom", name="Thom", kind="npc", hp=9, max_hp=9,
                        armor_class=12, attack_bonus=2, damage="1d6")
    enemies = [
        enemy_from_statblock(_goblin_statblock()),
        enemy_from_statblock(_goblin_statblock()),  # duplicate → numbered name
        enemy_from_character(npc_foe),
    ]
    plan = build_encounter(party, enemies, TerrainSpec(kind="open"), name="Roadside")

    enc = plan.encounter
    assert isinstance(enc, Encounter)
    assert len(enc.combatants) == 5
    teams = [c.team for c in enc.combatants]
    assert teams.count("player") == 2 and teams.count("enemy") == 3

    # duplicate goblins get unique display names
    names = [c.name_override for c in enc.combatants]
    assert "Goblin" in names and "Goblin 2" in names

    # positions are all distinct and inside the grid
    coords = [tuple(c.starting_position) for c in enc.combatants]
    assert len(set(coords)) == len(coords)
    assert all(0 <= q < enc.grid_width and 0 <= r < enc.grid_height for q, r in coords)

    # persistent back-map: both PCs + the NPC foe; ephemeral goblins excluded
    assert plan.persistent_ids["Elara"] == "hero"
    assert plan.persistent_ids["Thorin"] == "thorin"
    assert plan.persistent_ids["Thom"] == "thom"
    assert "Goblin" not in plan.persistent_ids
    assert plan.loot_by_name["Goblin"] == plan.loot_by_name["Goblin 2"]  # 5g each

    # the produced encounter round-trips through the Arena's own validator
    Encounter.model_validate(enc.model_dump())


def test_terrain_kind_keys_a_default_layout():
    party = [_pc()]
    enemies = [enemy_from_statblock(RS.bestiary["bandit"])]
    open_plan = build_encounter(party, enemies, TerrainSpec(kind="open"))
    choke_plan = build_encounter(party, enemies, TerrainSpec(kind="chokepoint"))
    assert open_plan.encounter.terrain == []
    assert len(choke_plan.encounter.terrain) > 0
    assert all(t.terrain_type.value == "wall" for t in choke_plan.encounter.terrain)


# --- OUT: inventory consumables → drink actions (B1) ---------------------

def _potion_catalog() -> dict[str, SrdEquipment]:
    return {
        "potion_of_healing": SrdEquipment(
            id="potion_of_healing", name="Potion of Healing", category="consumable",
            item_type="potion", rarity="common", mechanics="structured",
            consumable=ConsumableMechanics(healing="2d4+2", action="action")),
        # mechanics "none": grantable flavor, NOT drinkable in the Arena
        "oil_of_slipperiness": SrdEquipment(
            id="oil_of_slipperiness", name="Oil of Slipperiness", category="consumable",
            item_type="potion", rarity="uncommon", mechanics="none"),
        # structured ability-SET potion — drinkable since B5 (engine "set" buff)
        "potion_of_giant_strength": SrdEquipment(
            id="potion_of_giant_strength", name="Potion of Hill Giant Strength",
            category="consumable", item_type="potion", mechanics="structured",
            consumable=ConsumableMechanics(ability_set={"str": 21}, duration="1 hour")),
        # Belts park ability_set in the same mechanics slot but are WORN gear —
        # they must never become drink actions.
        "belt_of_giant_strength": SrdEquipment(
            id="belt_of_giant_strength", name="Belt of Hill Giant Strength",
            category="gear", item_type="wondrous", mechanics="structured",
            consumable=ConsumableMechanics(ability_set={"str": 21})),
    }


def test_healing_potions_in_inventory_become_one_drink_action():
    pc = _pc(inventory=[
        ItemStack(item_id="potion_of_healing", qty=2),
        ItemStack(item_id="oil_of_slipperiness"),
        ItemStack(item_id="some_pack_trinket"),          # not in the SRD catalog
    ])
    creature = character_to_player(pc, _potion_catalog())

    drinks = [a for a in creature.actions if a.source_item]
    assert len(drinks) == 1                              # mechanics:none stays out
    drink = drinks[0]
    assert drink.name == "Potion of Healing"
    assert drink.healing == "2d4+2"
    assert drink.target_type.value == "self" and drink.action_type.value == "action"
    # the handoff-v2 entry invariant: uses enter equal to the stack quantity
    assert drink.uses_per_rest == 2 and drink.current_uses == 2
    assert drink.source_item == "Potion of Healing"
    assert drink.source_item_id == "potion_of_healing"
    # the basic attack is untouched alongside
    assert creature.actions[0].attack is not None


def test_no_catalog_or_empty_inventory_means_no_drink_actions():
    assert consumable_actions(_pc(), _potion_catalog()) == []
    pc = _pc(inventory=[ItemStack(item_id="potion_of_healing")])
    assert consumable_actions(pc, None) == []
    assert len(character_to_player(pc).actions) == 1     # default: basic attack only


def test_scroll_variant_stacks_stay_story_side():
    """A stack carrying a spell rider (an inscribed scroll) is never mapped to a
    drink action, even if its catalog item had structured healing (F3 deferral)."""
    pc = _pc(inventory=[ItemStack(item_id="potion_of_healing", spell="cure_wounds")])
    assert consumable_actions(pc, _potion_catalog()) == []


def test_same_item_split_across_stacks_aggregates_uses():
    pc = _pc(inventory=[
        ItemStack(item_id="potion_of_healing", qty=1),
        ItemStack(item_id="potion_of_healing", qty=2),
    ])
    (drink,) = consumable_actions(pc, _potion_catalog())
    assert drink.uses_per_rest == 3 and drink.current_uses == 3


# --- B3: +X gear bakes into the numbers; resistance potions ---------------

def test_equipped_plus_one_weapon_boosts_to_hit_and_damage_and_is_magical():
    pc = _pc(equipped=["weapon_1"])                       # generic "Weapon, +1"
    creature = character_to_player(pc, RS.equipment)
    attack_action = creature.actions[0]
    assert _carrier_attack(creature) == 5 + 1             # story +5, exact via solver
    assert attack_action.attack.damage[0].bonus == 3 + 1  # "1d8+3" flat + magic
    assert attack_action.attack.magical is True


def test_best_equipped_weapon_counts_not_the_sum():
    pc = _pc(equipped=["weapon_1", "weapon_3"])
    assert _carrier_attack(character_to_player(pc, RS.equipment)) == 5 + 3


def test_defensive_magic_items_stack_into_ac():
    pc = _pc(equipped=["armor_1", "ring_of_protection"])  # +1 armor, +1 ring
    creature = character_to_player(pc, RS.equipment)
    assert creature.armor_class == 15 + 2                 # story AC 15
    assert creature.actions[0].attack.magical is False    # weapon untouched


def test_ammunition_is_skipped_for_the_melee_basic_attack():
    pc = _pc(equipped=["ammunition_1"])
    creature = character_to_player(pc, RS.equipment)
    assert _carrier_attack(creature) == 5
    assert creature.armor_class == 15


def test_resistance_potion_becomes_a_buff_drink_action():
    pc = _pc(inventory=[ItemStack(item_id="potion_of_resistance_fire")])
    (drink,) = consumable_actions(pc, RS.equipment)
    assert drink.healing is None
    (buff,) = drink.buff_effects
    assert buff.stat == "damage_resistance" and buff.modifier_type == "resistance"
    assert buff.value == "fire"
    assert drink.uses_per_rest == 1 and drink.current_uses == 1
    assert drink.source_item_id == "potion_of_resistance_fire"


def test_drinking_a_resistance_potion_grants_resistance_in_the_real_engine():
    from pathlib import Path

    from arena.combat.actions import resolve_effect
    from arena.combat.manager import CombatManager
    from arena.combat.stat_modifiers import get_effective_damage_resistances

    pc = _pc(inventory=[ItemStack(item_id="potion_of_resistance_fire")])
    plan = build_encounter([pc], [enemy_from_statblock(RS.bestiary["bandit"])],
                           TerrainSpec(), catalog=RS.equipment)
    cm = CombatManager()
    cm.load_encounter(plan.encounter, Path("."))
    pc_cid, combatant = next((cid, c) for cid, c in cm.combatants.items()
                             if c.team == "player")
    creature = combatant.creature
    drink = next(a for a in creature.actions if a.source_item)

    res = resolve_effect(creature, pc_cid, creature, pc_cid, drink, cm.grid)
    assert res.success
    assert "fire" in [r.lower() for r in get_effective_damage_resistances(creature)]
    assert drink.current_uses == 0                        # reported by handoff v2


# --- B5: ability-SET potions (Giant Strength) ------------------------------

def test_giant_strength_potion_becomes_a_set_buff_drink_action():
    pc = _pc(inventory=[ItemStack(item_id="potion_of_giant_strength")])
    (drink,) = consumable_actions(pc, _potion_catalog())
    assert drink.healing is None
    (buff,) = drink.buff_effects
    assert buff.stat == "strength" and buff.modifier_type == "set"
    assert buff.value == 21
    assert "Strength becomes 21" in drink.description
    assert drink.source_item_id == "potion_of_giant_strength"


def test_belts_with_ability_set_are_never_drinkable():
    pc = _pc(inventory=[ItemStack(item_id="belt_of_giant_strength")])
    assert consumable_actions(pc, _potion_catalog()) == []


def test_drinking_giant_strength_sets_str_in_the_real_engine():
    from pathlib import Path

    from arena.combat.actions import resolve_effect
    from arena.combat.manager import CombatManager
    from arena.combat.stat_modifiers import get_effective_ability_score

    pc = _pc(inventory=[ItemStack(item_id="potion_of_giant_strength_hill")])
    plan = build_encounter([pc], [enemy_from_statblock(RS.bestiary["bandit"])],
                           TerrainSpec(), catalog=RS.equipment)
    cm = CombatManager()
    cm.load_encounter(plan.encounter, Path("."))
    pc_cid, combatant = next((cid, c) for cid, c in cm.combatants.items()
                             if c.team == "player")
    creature = combatant.creature
    assert get_effective_ability_score(creature, "strength") < 21
    drink = next(a for a in creature.actions if a.source_item)

    res = resolve_effect(creature, pc_cid, creature, pc_cid, drink, cm.grid)
    assert res.success
    assert get_effective_ability_score(creature, "strength") == 21
    assert drink.current_uses == 0


# --- B2: slot/resource state IN, spent state OUT --------------------------

def _warlock(slots_used=None) -> Character:
    """L3 warlock: pact magic pool {2: 2}."""
    return Character(
        id="vex", name="Vex", kind="pc", level=3, hp=20, max_hp=24,
        abilities={Ability.CHA: 16, Ability.DEX: 14, Ability.CON: 14, Ability.WIS: 10},
        armor_class=13, attack_bonus=5, damage="1d10",
        spell_slots_used=slots_used or {},
        sheet=CharacterSheet(race="human", char_class="warlock", background="acolyte",
                             spellcasting_ability=Ability.CHA))


def _barbarian(rage_used=0) -> Character:
    """L3 barbarian: Rage pool of 3, no spell slots."""
    return Character(
        id="grog", name="Grog", kind="pc", level=3, hp=30, max_hp=30,
        abilities={Ability.STR: 16, Ability.DEX: 14, Ability.CON: 16},
        armor_class=14, attack_bonus=5, damage="1d12+3",
        resources_used={"Rage": rage_used},
        sheet=CharacterSheet(race="human", char_class="barbarian", background="acolyte"))


def test_caster_arrives_with_current_slots_not_recharged():
    creature = character_to_player(_warlock(slots_used={2: 1}), None, RS)
    assert creature.spell_slots == {2: 2}                      # maxima
    assert creature.class_resources["spell_slot_2"] == 1       # 1 of 2 already spent


def test_class_resources_arrive_with_remaining_pool():
    creature = character_to_player(_barbarian(rage_used=1), None, RS)
    # C1: pools stage under ENGINE keys ("rage", "ki_points"), the names the
    # engine's presets and standard actions hard-code; story side keeps "Rage".
    assert creature.class_resources["rage"] == 2               # 3-pool, 1 spent
    assert creature.spell_slots == {}


def test_without_ruleset_or_sheet_nothing_is_staged():
    assert character_to_player(_warlock(slots_used={2: 1})).class_resources == {}
    sheetless = Character(id="x", name="Nix", kind="pc", hp=9, max_hp=9,
                          armor_class=11, attack_bonus=2, damage="1d6")
    assert character_to_player(sheetless, None, RS).class_resources == {}


def _plan_with(pc: Character):
    enemies = [enemy_from_statblock(RS.bestiary["bandit"])]
    return build_encounter([pc], enemies, TerrainSpec(), ruleset=RS)


def _v2_pc_entry(name: str, resources: dict) -> dict:
    return {"name": name, "team": "player", "is_pc": True, "hp": 20, "max_hp": 24,
            "conditions": [], "is_conscious": True, "xp": 0, "resources": resources}


def test_spent_slots_map_back_as_absolute_used():
    plan = _plan_with(_warlock(slots_used={2: 1}))
    handoff = {"schema": 2, "winner": None, "outcome": "unresolved", "combatants": [
        _v2_pc_entry("Vex", {"spell_slots": {"2": {"remaining": 0, "max": 2}},
                             "class_resources": {}})]}
    result = result_to_combat_result(handoff, plan)
    assert result.slots_used_final == {"vex": {2: 2}}          # both gone now
    assert result.resources_used_final == {}                   # warlock has no pools


def test_spent_class_resources_map_back_preserving_untracked_entries():
    pc = _barbarian(rage_used=1)
    pc.resources_used["Lucky"] = 2          # an un-carried tracker must survive
    plan = _plan_with(pc)
    handoff = {"schema": 2, "winner": "player", "outcome": "victory", "combatants": [
        _v2_pc_entry("Grog", {"spell_slots": {}, "class_resources": {"Rage": 0}})]}
    result = result_to_combat_result(handoff, plan)
    assert result.resources_used_final == {"grog": {"Rage": 3, "Lucky": 2}}
    assert result.slots_used_final == {}                       # no slots staged


def test_unreported_resources_keep_their_staged_state():
    plan = _plan_with(_warlock(slots_used={2: 1}))
    handoff = {"schema": 2, "winner": "player", "outcome": "victory", "combatants": [
        _v2_pc_entry("Vex", {"spell_slots": {}, "class_resources": {}})]}
    result = result_to_combat_result(handoff, plan)
    assert result.slots_used_final == {"vex": {2: 1}}          # unchanged, not reset


def test_overdrawn_remaining_clamps_into_the_pool():
    plan = _plan_with(_warlock())
    handoff = {"schema": 2, "winner": "player", "outcome": "victory", "combatants": [
        _v2_pc_entry("Vex", {"spell_slots": {"2": {"remaining": 9, "max": 2}},
                             "class_resources": {}})]}
    result = result_to_combat_result(handoff, plan)
    assert result.slots_used_final == {"vex": {2: 0}}          # never negative used


def test_v1_results_touch_no_resource_state():
    plan = _plan_with(_warlock(slots_used={2: 1}))
    handoff = {"schema": 1, "winner": "player", "outcome": "victory", "combatants": [
        {"name": "Vex", "team": "player", "hp": 20, "conditions": [],
         "is_conscious": True, "xp": 0}]}
    result = result_to_combat_result(handoff, plan)
    assert result.slots_used_final == {} and result.resources_used_final == {}


def test_resource_ops_round_trip_through_a_real_combat_manager():
    """The headless B2 slice: a warlock with one slot already spent is staged into
    a REAL CombatManager; the engine's spend ledger drops the other slot; the
    GENUINE build_result + bridge + ops write `spell_slots_used` = fully spent."""
    from pathlib import Path

    from arena.combat.manager import CombatManager
    from arena.handoff import build_result

    from oubliette.combat.boundary import result_to_ops
    from oubliette.record.events import apply_ops
    from oubliette.state.repository import InMemoryRepository

    pc = _warlock(slots_used={2: 1})
    plan = _plan_with(pc)
    cm = CombatManager()
    cm.load_encounter(plan.encounter, Path("."))

    creature = next(c.creature for c in cm.combatants.values() if c.team == "player")
    assert creature.class_resources["spell_slot_2"] == 1       # staged, not recharged
    creature.class_resources["spell_slot_2"] -= 1              # the engine's spend path

    # break off the fight unresolved: a slot burned before fleeing is still spent
    result = result_to_combat_result(build_result(cm), plan)
    assert result.outcome == "flee"
    repo = InMemoryRepository(characters=[pc], items=[], pc_id="vex")
    apply_ops(result_to_ops(result), repo)
    assert repo.pc().spell_slots_used == {2: 2}                # both slots now spent


# --- BACK: result dict → CombatResult ------------------------------------

def _plan_for_backmap() -> "tuple":
    party = [_pc()]
    npc_foe = Character(id="thom", name="Thom", kind="npc", hp=9, max_hp=9,
                        armor_class=12, attack_bonus=2, damage="1d6")
    enemies = [enemy_from_statblock(_goblin_statblock()), enemy_from_character(npc_foe)]
    return build_encounter(party, enemies, TerrainSpec())


def test_victory_writes_back_persistent_hp_and_awards_fallen_xp_and_loot():
    plan = _plan_for_backmap()
    handoff = {
        "schema": 1, "winner": "player", "outcome": "victory", "rounds": 3,
        "combatants": [
            {"name": "Elara", "team": "player", "is_pc": True, "hp": 18,
             "max_hp": 27, "conditions": ["prone"], "is_conscious": True, "xp": 0},
            {"name": "Goblin", "team": "enemy", "is_pc": False, "hp": 0,
             "max_hp": 7, "conditions": [], "is_conscious": False, "xp": 50},
            {"name": "Thom", "team": "enemy", "is_pc": False, "hp": 0,
             "max_hp": 9, "conditions": [], "is_conscious": False, "xp": 0},
        ],
    }
    result = result_to_combat_result(handoff, plan)

    assert result.outcome == "victory"
    # PC + persistent NPC foe written back (absolute); ephemeral goblin is not
    assert result.hp_final == {"hero": 18, "thom": 0}
    assert result.conditions_final["hero"] == ["prone"]
    assert "goblin" not in result.hp_final and "Goblin" not in result.hp_final
    # XP only from the fallen ephemeral goblin (the NPC carries 0)
    assert result.xp_award == 50
    # loot dropped for the fallen goblin (5g)
    assert any(e.gold == 5 for e in result.loot)


def test_defeat_writes_partial_hp_but_no_xp():
    plan = _plan_for_backmap()
    handoff = {
        "winner": "enemy", "outcome": "defeat",
        "combatants": [
            {"name": "Elara", "team": "player", "hp": 0, "conditions": ["unconscious"],
             "is_conscious": False, "xp": 0},
            {"name": "Goblin", "team": "enemy", "hp": 4, "conditions": [],
             "is_conscious": True, "xp": 50},
        ],
    }
    result = result_to_combat_result(handoff, plan)
    assert result.outcome == "defeat"
    assert result.hp_final["hero"] == 0
    assert result.xp_award == 0 and result.loot == []
    # surviving ephemeral enemy surfaced as a promotion candidate
    assert "Goblin" in result.ephemeral_survivors


def test_consumables_used_map_to_inventory_debits():
    """v2 results: per-PC consumption becomes `items_consumed` keyed by entity id.
    Entries without a catalog id (native Arena content) are unmappable → skipped;
    consumption applies on EVERY outcome (drunk before fleeing = still gone)."""
    plan = _plan_for_backmap()
    handoff = {
        "schema": 2, "winner": None, "outcome": "unresolved",
        "combatants": [
            {"name": "Elara", "team": "player", "is_pc": True, "hp": 12,
             "conditions": [], "is_conscious": True, "xp": 0,
             "consumables_used": [
                 {"item_id": "potion_of_healing", "name": "Potion of Healing", "used": 2},
                 {"item_id": None, "name": "Mystery Elixir", "used": 1},
             ]},
            {"name": "Goblin", "team": "enemy", "is_pc": False, "hp": 7,
             "conditions": [], "is_conscious": True, "xp": 50},
        ],
    }
    result = result_to_combat_result(handoff, plan)
    assert result.outcome == "flee"
    assert result.items_consumed == [
        ConsumedItem(char="hero", item_id="potion_of_healing", qty=2)
    ]


def test_v1_results_yield_no_items_consumed():
    plan = _plan_for_backmap()
    handoff = {"schema": 1, "winner": "player", "outcome": "victory",
               "combatants": [{"name": "Elara", "team": "player", "hp": 20,
                               "conditions": [], "is_conscious": True, "xp": 0}]}
    assert result_to_combat_result(handoff, plan).items_consumed == []


def test_future_result_schema_is_refused():
    """A result newer than the bridge understands must fail loudly, not silently
    misread — the subprocess boundary is where version drift would bite."""
    plan = _plan_for_backmap()
    handoff = {"schema": 3, "winner": "player", "outcome": "victory", "combatants": []}
    try:
        result_to_combat_result(handoff, plan)
    except ValueError as e:
        assert "schema 3" in str(e)
    else:
        raise AssertionError("schema 3 should have been refused")


def test_unresolved_window_close_maps_to_flee_with_partial_writeback():
    plan = _plan_for_backmap()
    handoff = {
        "winner": None, "outcome": "unresolved",
        "combatants": [
            {"name": "Elara", "team": "player", "hp": 12, "conditions": [],
             "is_conscious": True, "xp": 0},
            {"name": "Goblin", "team": "enemy", "hp": 2, "conditions": [],
             "is_conscious": True, "xp": 50},
        ],
    }
    result = result_to_combat_result(handoff, plan)
    assert result.outcome == "flee"
    assert result.hp_final["hero"] == 12      # you took your hits before breaking off
    assert result.xp_award == 0 and result.loot == []


# --- C5: the weapon kit ----------------------------------------------------

def _give(char, item_id, qty=1):
    char.inventory.append(ItemStack(item_id=item_id, qty=qty))
    return char


def test_every_carried_weapon_is_its_own_attack():
    pc = _give(_give(_pc(), "longsword"), "longbow")
    actions = {a.name: a for a in weapon_kit_actions(pc, RS.equipment)}
    sword = actions["Longsword"]
    assert sword.attack.attack_type == "melee_weapon"
    assert sword.attack.ability == "strength"
    assert sword.attack.damage[0].dice == "1d8"
    assert sword.attack.damage[0].damage_type.value == "slashing"
    assert sword.attack.damage[0].ability_modifier == "strength"
    bow = actions["Longbow"]
    assert bow.attack.attack_type == "ranged_weapon"
    assert bow.attack.ability == "dexterity"
    assert bow.attack.range_normal == 150 and bow.attack.range_long == 600
    assert bow.uses_per_rest is None          # ammunition deliberately untracked


def test_finesse_picks_the_better_mod():
    pc = _give(_pc(), "dagger")               # DEX 16 beats STR 12
    dagger = next(a for a in weapon_kit_actions(pc, RS.equipment)
                  if a.name == "Dagger")
    assert dagger.attack.ability == "dexterity"


def test_thrown_melee_weapon_gets_a_consuming_ranged_twin():
    pc = _give(_pc(), "javelin", qty=3)
    acts = {a.name: a for a in weapon_kit_actions(pc, RS.equipment)}
    melee, thrown = acts["Javelin"], acts["Javelin (thrown)"]
    assert melee.uses_per_rest is None        # stabbing keeps the javelin
    assert thrown.attack.attack_type == "ranged_weapon"
    assert thrown.attack.ability == "strength"  # thrown keeps the melee ability
    assert thrown.attack.range_normal == 30 and thrown.attack.range_long == 120
    assert thrown.uses_per_rest == 3 and thrown.current_uses == 3
    assert thrown.source_item_id == "javelin"   # B1 round-trip debits the stack


def test_non_weapons_and_unknown_items_are_skipped():
    pc = _give(_give(_pc(), "rope_hempen"), "no_such_item_xyz")
    assert weapon_kit_actions(pc, RS.equipment) == []


def test_equipped_but_unstacked_weapon_still_stages():
    # The equipped handaxe is the basic-attack source, so its melee swing is
    # the sheet's "Attack" (module-kit S1.5: no double-listing) — but the kit
    # still stages its thrown variant, which the melee-shaped Attack can't cover.
    pc = _pc()
    pc.equipped.append("handaxe")
    names = [a.name for a in weapon_kit_actions(pc, RS.equipment)]
    assert "Handaxe" not in names and "Handaxe (thrown)" in names


def test_kit_rides_into_the_staged_player_after_the_basic_attack():
    pc = _give(_pc(), "handaxe")
    creature = character_to_player(pc, RS.equipment, RS)
    names = [a.name for a in creature.actions]
    assert names[0] == "Attack"               # the solved sheet attack stays first
    assert "Handaxe" in names and "Handaxe (thrown)" in names


# --- AI profile flow (Forge Phase 2a) -----------------------------------
# A pack StatBlock's `ai_profile` (the creature's personality) must ride the
# bridge into the Arena Monster, through both the flat mapping and the rich
# SRD-file path.

def _sb_with_profile(profile, sid="synthetic_brute"):
    return StatBlock(
        id=sid, name="Brute", hp=20, armor_class=13, attack_bonus=4, damage="1d8+2",
        abilities={"str": 16, "dex": 10, "con": 14, "int": 6, "wis": 8, "cha": 6},
        ai_profile=profile,
    )


def test_statblock_ai_profile_flows_to_monster():
    # An exotic id with no rich Arena file -> the flat mapping path.
    mon = statblock_to_monster(_sb_with_profile("berserker"))
    assert mon.ai_profile == "berserker"


def test_statblock_default_ai_profile_when_unset():
    mon = statblock_to_monster(_sb_with_profile(None))
    assert mon.ai_profile == "default_monster"


def test_pack_profile_overrides_rich_srd_file():
    from oubliette.combat.arena_bridge import arena_monster_file
    assert arena_monster_file("goblin") is not None      # this id HAS a rich file
    sb = StatBlock(
        id="goblin", name="Goblin", hp=7, armor_class=15, attack_bonus=4,
        damage="1d6+2", abilities={"str": 8, "dex": 14, "con": 10},
        ai_profile="berserker",
    )
    inst = enemy_from_statblock(sb)
    assert inst.creature.ai_profile == "berserker"        # author's choice wins


def test_rich_file_profile_kept_when_pack_leaves_it_unset():
    from oubliette.combat.arena_bridge import arena_monster_file
    own = arena_monster_file("goblin").ai_profile
    sb = StatBlock(
        id="goblin", name="Goblin", hp=7, armor_class=15, attack_bonus=4,
        damage="1d6+2", abilities={"str": 8, "dex": 14, "con": 10},
        ai_profile=None,
    )
    inst = enemy_from_statblock(sb)
    assert inst.creature.ai_profile == own                # untouched


def test_carried_profile_resolves_to_a_real_aiprofile():
    # End-to-end: the carried name is one the Arena AI actually resolves.
    from arena.ai.behavior import DEFAULT_PROFILES
    mon = statblock_to_monster(_sb_with_profile("coward"))
    assert mon.ai_profile in DEFAULT_PROFILES
    assert DEFAULT_PROFILES[mon.ai_profile].will_flee is True


# --- custom (Forge-authored) personalities (Phase 2b bridge resolution) ---

def _pack_profile(**kw):
    from oubliette.content.schemas import AiProfile as PackProfile
    base = dict(id="cowardly_goblin", name="Cowardly Goblin",
                aggression=0.5, self_preservation=1.5, will_flee=True,
                retreat_threshold=0.5)
    base.update(kw)
    return PackProfile(**base)


class _Comb:
    """Duck-typed combatant for AIController._get_profile."""
    def __init__(self, creature):
        self.creature = creature


def test_custom_profile_is_baked_inline_and_resolved():
    from arena.ai.controller import AIController
    prof = _pack_profile()
    sb = StatBlock(
        id="goblin", name="Goblin", hp=7, armor_class=15, attack_bonus=4,
        damage="1d6+2", abilities={"str": 8, "dex": 14, "con": 10},
        ai_profile="cowardly_goblin",
    )
    inst = enemy_from_statblock(sb, ai_profiles={"cowardly_goblin": prof})
    inline = inst.creature.ai_profile_inline
    assert inline is not None and inline["will_flee"] is True
    assert "id" not in inline                      # the runtime AIProfile has no id

    # The Arena controller prefers the inline profile over the named one.
    resolved = AIController(randomness=0.0)._get_profile(_Comb(inst.creature))
    assert resolved.name == "Cowardly Goblin"
    assert resolved.will_flee is True and resolved.aggression == 0.5


def test_preset_name_does_not_bake_inline():
    sb = StatBlock(
        id="goblin", name="Goblin", hp=7, armor_class=15, attack_bonus=4,
        damage="1d6+2", abilities={"str": 8, "dex": 14, "con": 10},
        ai_profile="berserker",                    # a built-in preset, not a custom id
    )
    inst = enemy_from_statblock(sb, ai_profiles={"cowardly_goblin": _pack_profile()})
    assert inst.creature.ai_profile_inline is None  # rides as the string instead
    assert inst.creature.ai_profile == "berserker"


def test_unknown_custom_id_falls_back_to_default():
    from arena.ai.controller import AIController
    sb = StatBlock(
        id="goblin", name="Goblin", hp=7, armor_class=15, attack_bonus=4,
        damage="1d6+2", abilities={"str": 8, "dex": 14, "con": 10},
        ai_profile="typo_profile",                 # neither preset nor a known custom id
    )
    inst = enemy_from_statblock(sb, ai_profiles={"cowardly_goblin": _pack_profile()})
    assert inst.creature.ai_profile_inline is None
    resolved = AIController(randomness=0.0)._get_profile(_Comb(inst.creature))
    assert resolved.name == "Default Monster"      # safe fallback


# --- Phase 3b-1: pack-carried combat file preferred over the flat mapping -----
import shutil
from pathlib import Path

from arena.paths import DATA_DIR


def _homebrew_statblock() -> StatBlock:
    """A custom creature whose id matches NO SRD file, so the only rich source is
    a pack-authored combat file — isolating pack-vs-flat in the assertions."""
    return StatBlock(
        id="brightvale_gloom_beast", name="Gloom Beast", hp=40, armor_class=14,
        attack_bonus=5, damage="2d6+3", cr=3.0, xp=700,
        abilities={"str": 17, "dex": 12, "con": 15, "int": 3, "wis": 12, "cha": 6},
    )


def test_pack_combat_file_is_preferred_over_flat_mapping(tmp_path):
    sb = _homebrew_statblock()
    mdir = tmp_path / "monsters"
    mdir.mkdir()
    # a real, valid combat file (the Owlbear's: two distinct attacks) under the
    # homebrew id — the bridge should fight THIS, not the flat one-swing mapping
    shutil.copy(DATA_DIR / "monsters" / "srd" / "owlbear.json", mdir / f"{sb.id}.json")
    inst = enemy_from_statblock(sb, pack_monster_dir=mdir)
    assert inst.creature.name == "Owlbear"          # came from the file, not sb.name
    assert len(inst.creature.actions) == 2          # Beak + Claws; flat gives exactly 1
    assert inst.xp == sb.xp                          # reward still from the bestiary


def test_pack_combat_file_xp_and_profile_overridden_from_statblock(tmp_path):
    sb = _homebrew_statblock()
    sb.ai_profile = "berserker"
    mdir = tmp_path / "monsters"
    mdir.mkdir()
    shutil.copy(DATA_DIR / "monsters" / "srd" / "owlbear.json", mdir / f"{sb.id}.json")
    inst = enemy_from_statblock(sb, pack_monster_dir=mdir)
    assert inst.creature.experience_points == sb.xp
    assert inst.creature.ai_profile == "berserker"


def test_missing_pack_combat_file_falls_back_to_flat_mapping(tmp_path):
    sb = _homebrew_statblock()
    mdir = tmp_path / "monsters"
    mdir.mkdir()                                     # empty — no file for this id
    inst = enemy_from_statblock(sb, pack_monster_dir=mdir)
    assert inst.creature.name == sb.name            # flat mapping
    assert len(inst.creature.actions) == 1          # single basic attack


def test_malformed_pack_combat_file_degrades_to_flat_mapping(tmp_path):
    sb = _homebrew_statblock()
    mdir = tmp_path / "monsters"
    mdir.mkdir()
    (mdir / f"{sb.id}.json").write_text("{ not valid json", encoding="utf-8")
    inst = enemy_from_statblock(sb, pack_monster_dir=mdir)
    assert inst.creature.name == sb.name            # didn't crash; fell back
    assert len(inst.creature.actions) == 1


def test_pack_combat_file_overrides_an_srd_id(tmp_path):
    """A pack file wins even when the id matches an SRD monster (an author's
    custom take on a standard creature)."""
    sb = _goblin_statblock()                         # id "goblin" — has an SRD file
    mdir = tmp_path / "monsters"
    mdir.mkdir()
    shutil.copy(DATA_DIR / "monsters" / "srd" / "owlbear.json", mdir / "goblin.json")
    inst = enemy_from_statblock(sb, pack_monster_dir=mdir)
    assert inst.creature.name == "Owlbear"          # the pack file, not the SRD goblin


# --- Phase 3b-3a: the engine honors what the attacks editor writes ------------
def test_engine_honors_authored_attacks_and_multiattack():
    """Guard the REAL path: a combat file shaped like the Forge attacks editor
    produces (distinct attacks + a Multiattack special ability) is mechanically
    honored — the multiattack count and the derived to-hit both resolve."""
    from arena.combat.stat_modifiers import get_extra_attack_count
    # str 16 (+3), proficiency +2 → melee attacks resolve at +5
    monster = Monster.model_validate({
        "name": "Gloom Beast",
        "ability_scores": {"strength": 16, "dexterity": 12, "constitution": 14,
                           "intelligence": 3, "wisdom": 10, "charisma": 6},
        "armor_class": 14, "max_hit_points": 40, "proficiency_bonus": 2,
        "challenge_rating": 3,
        "actions": [
            {"name": "Bite", "description": "Melee Weapon Attack", "action_type": "action",
             "target_type": "one_creature", "range": 5,
             "attack": {"name": "Bite", "attack_type": "melee_weapon", "ability": "strength",
                        "reach": 5, "damage": [{"dice": "2d6", "damage_type": "piercing", "bonus": 3}]}},
            {"name": "Claw", "description": "Melee Weapon Attack", "action_type": "action",
             "target_type": "one_creature", "range": 5,
             "attack": {"name": "Claw", "attack_type": "melee_weapon", "ability": "strength",
                        "reach": 5, "damage": [{"dice": "1d8", "damage_type": "slashing", "bonus": 3}]}},
        ],
        "special_abilities": [
            {"name": "Multiattack", "description": "makes two attacks.", "extra_attack_count": 2},
        ],
    })
    assert get_extra_attack_count(monster) == 2          # multiattack count is live
    bite = monster.actions[0]
    assert get_attack_modifier(monster, bite.attack, bite) == 5   # +3 STR + 2 prof, as previewed


def test_engine_accepts_authored_breath_weapon():
    """Guard the real path for save-for-effect moves: a breath weapon shaped like
    the Forge special-move editor writes validates against the engine Action model,
    with its area + saving throw + recharge intact."""
    from arena.models.actions import Action, TargetType
    act = Action.model_validate({
        "name": "Frost Breath", "description": "15-ft cone.", "action_type": "action",
        "target_type": "area_cone", "area_size": 15, "range": 15,
        "saving_throw": {"ability": "constitution", "dc": 12,
                         "damage_on_fail": [{"dice": "3d8", "damage_type": "cold", "bonus": 0}],
                         "damage_on_success": "half", "conditions_on_fail": []},
        "recharge_min": 5, "ai_priority": 9,
    })
    assert act.target_type == TargetType.AREA_CONE
    assert act.saving_throw.ability == "constitution" and act.saving_throw.dc == 12
    assert act.saving_throw.damage_on_success == "half"
    assert act.recharge_min == 5 and act.ai_priority == 9   # signature: AI uses it freely
