"""Combat Stage 2 — the Arena bridge (`oubliette.combat.arena_bridge`).

Pure data-mapping, both directions:
  * Oubliette `Character` / `StatBlock` / `CombatantTemplate` → Arena creatures,
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
    enemy_from_character,
    enemy_from_statblock,
    enemy_from_template,
    result_to_combat_result,
    statblock_to_monster,
    template_to_monster,
)
from oubliette.combat.schemas import TerrainSpec
from oubliette.combat.templates import ENEMY_TEMPLATES
from oubliette.content.schemas import Action as ContentAction
from oubliette.content.schemas import LootEntry, StatBlock
from oubliette.state.models import Character, CharacterSheet


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


def test_template_to_monster_defaults_and_exact_to_hit():
    bandit = ENEMY_TEMPLATES["bandit"]
    mon = template_to_monster(bandit)
    assert mon.max_hit_points == bandit.hp and mon.armor_class == bandit.armor_class
    assert mon.experience_points == bandit.xp
    assert mon.is_player_controlled is False
    assert _carrier_attack(mon) == bandit.attack_bonus


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
    enemies = [enemy_from_template(ENEMY_TEMPLATES["bandit"])]
    open_plan = build_encounter(party, enemies, TerrainSpec(kind="open"))
    choke_plan = build_encounter(party, enemies, TerrainSpec(kind="chokepoint"))
    assert open_plan.encounter.terrain == []
    assert len(choke_plan.encounter.terrain) > 0
    assert all(t.terrain_type.value == "wall" for t in choke_plan.encounter.terrain)


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
