"""Tests for summoning creatures mid-combat and Wild Shape."""

import copy
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant
from arena.combat.events import CombatEventType
from arena.combat.initiative import InitiativeEntry
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action,
    ActionType,
    Attack,
    DamageRoll,
    DamageType,
    TargetType,
)
from arena.models.character import Creature, PlayerCharacter
from arena.models.encounter import CombatantEntry, Encounter


# ── Helpers ──────────────────────────────────────────────────────────


def _make_druid(actions=None) -> PlayerCharacter:
    return PlayerCharacter(
        name="Druid",
        max_hit_points=40,
        armor_class=14,
        ability_scores=AbilityScores(wisdom=16, dexterity=12),
        proficiency_bonus=3,
        is_player_controlled=True,
        character_class="Druid",
        level=5,
        class_resources={"spell_slot_2": 3},
        actions=actions or [],
    )


def _make_wolf() -> Creature:
    """A simple wolf for summoning/Wild Shape tests."""
    return Creature(
        name="Wolf",
        max_hit_points=11,
        armor_class=13,
        ability_scores=AbilityScores(strength=12, dexterity=15),
        proficiency_bonus=2,
        is_player_controlled=False,
        ai_profile="default_monster",
        actions=[
            Action(
                name="Bite",
                description="Melee attack.",
                attack=Attack(
                    name="Bite",
                    attack_type="melee_weapon",
                    ability="dexterity",
                    reach=5,
                    damage=[DamageRoll(dice="2d4", damage_type=DamageType.PIERCING)],
                ),
            ),
        ],
    )


def _make_enemy(name="Goblin", hp=15) -> Creature:
    return Creature(
        name=name,
        max_hit_points=hp,
        armor_class=13,
        ability_scores=AbilityScores(dexterity=14),
        proficiency_bonus=2,
        is_player_controlled=False,
        ai_profile="default_monster",
    )


def _summon_action(creature_path="monsters/wolf.json", is_wild_shape=False) -> Action:
    return Action(
        name="Find Familiar" if not is_wild_shape else "Wild Shape",
        description="Summon a creature.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=30,
        summon_creature=creature_path,
        is_wild_shape=is_wild_shape,
        resource_cost={"spell_slot_2": 1} if not is_wild_shape else {},
    )


def _setup_combat(player_actions=None, enemy_pos=(7, 5)):
    """Create combat with druid + enemy, druid's turn active."""
    enc = Encounter(
        name="Summon Test",
        grid_width=20,
        grid_height=15,
        combatants=[
            CombatantEntry(
                creature_id="druid_inline",
                creature_data=_make_druid(player_actions),
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="goblin_inline",
                creature_data=_make_enemy(),
                team="enemy",
                starting_position=enemy_pos,
            ),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    cm.roll_initiative()
    cm.begin_combat()

    druid_id = None
    for cid, c in cm.combatants.items():
        if c.team == "player":
            druid_id = cid
            break

    while cm.active_combatant and cm.active_combatant.creature_id != druid_id:
        cm.end_turn()

    return cm, druid_id


# ── Tests ────────────────────────────────────────────────────────────


def _mock_load_for_summon(original_method):
    """Create a side_effect that returns the original result for inline data
    but returns a wolf for file-based loading (summons)."""
    def _side_effect(entry, data_dir):
        if entry.creature_data:
            return original_method(entry, data_dir)
        return _make_wolf()
    return _side_effect


class TestExecuteSummon:
    def test_summon_places_creature_on_grid(self):
        """Summoning should create a new combatant at the target hex."""
        cm, druid_id = _setup_combat(player_actions=[_summon_action()])
        original = CombatManager._load_creature

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda entry, data_dir: (
                              entry.creature_data.model_copy(deep=True) if entry.creature_data
                              else _make_wolf())):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            target_hex = HexCoord(4, 4)
            result = cm.execute_summon(target_hex)

        assert result is not None
        assert result.success

        wolf_ids = [
            cid for cid, c in cm.combatants.items()
            if "wolf" in cid.lower()
        ]
        assert len(wolf_ids) == 1
        wolf_id = wolf_ids[0]
        assert cm.combatants[wolf_id].position == target_hex
        assert cm.combatants[wolf_id].team == "player"

    def test_summon_initiative_after_summoner(self):
        """Summoned creature should appear right after the summoner in initiative."""
        cm, druid_id = _setup_combat(player_actions=[_summon_action()])

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            cm.execute_summon(HexCoord(4, 4))

        entries = cm.initiative.entries
        druid_idx = next(i for i, e in enumerate(entries) if e.creature_id == druid_id)
        wolf_ids = [cid for cid in cm.combatants if "wolf" in cid.lower()]
        wolf_idx = next(i for i, e in enumerate(entries) if e.creature_id == wolf_ids[0])

        assert wolf_idx == druid_idx + 1

    def test_summon_same_team_as_summoner(self):
        """Summoned creature should be on the same team as the summoner."""
        cm, druid_id = _setup_combat(player_actions=[_summon_action()])

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            cm.execute_summon(HexCoord(4, 4))

        wolf_ids = [cid for cid in cm.combatants if "wolf" in cid.lower()]
        assert cm.combatants[wolf_ids[0]].team == "player"

    def test_summon_on_occupied_hex_fails(self):
        """Cannot summon on an occupied hex."""
        cm, druid_id = _setup_combat(player_actions=[_summon_action()])

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            druid_pos = cm.combatants[druid_id].position
            result = cm.execute_summon(druid_pos)

        assert result is not None
        assert result.success is False

    def test_summon_out_of_range_fails(self):
        """Cannot summon beyond the action's range."""
        cm, druid_id = _setup_combat(player_actions=[_summon_action()])

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            result = cm.execute_summon(HexCoord(17, 2))

        assert result is not None
        assert result.success is False

    def test_summon_deducts_resource_cost(self):
        """Summoning should deduct the resource cost."""
        cm, druid_id = _setup_combat(player_actions=[_summon_action()])

        slots_before = cm.combatants[druid_id].creature.class_resources["spell_slot_2"]

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            cm.execute_summon(HexCoord(4, 4))

        slots_after = cm.combatants[druid_id].creature.class_resources["spell_slot_2"]
        assert slots_after == slots_before - 1

    def test_summon_unique_ids(self):
        """Multiple summons should get unique IDs."""
        action = _summon_action()
        action.resource_cost = {}
        cm, druid_id = _setup_combat(player_actions=[action])

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            cm.execute_summon(HexCoord(4, 4))

            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            cm.execute_summon(HexCoord(5, 4))

        wolf_ids = [cid for cid in cm.combatants if "wolf" in cid.lower()]
        assert len(wolf_ids) == 2
        assert wolf_ids[0] != wolf_ids[1]

    def test_summon_tracks_link(self):
        """Summon should be tracked in summon_links."""
        cm, druid_id = _setup_combat(player_actions=[_summon_action()])

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            cm.execute_summon(HexCoord(4, 4))

        wolf_ids = [cid for cid in cm.combatants if "wolf" in cid.lower()]
        assert wolf_ids[0] in cm.summon_links
        assert cm.summon_links[wolf_ids[0]] == druid_id


class TestSummonDeath:
    def test_summon_death_removes_creature(self):
        """When a summoned creature drops to 0 HP, it's removed from combat."""
        cm, druid_id = _setup_combat(player_actions=[_summon_action()])

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            cm.execute_summon(HexCoord(4, 4))

        wolf_ids = [cid for cid in cm.combatants if "wolf" in cid.lower()]
        wolf_id = wolf_ids[0]

        cm.combatants[wolf_id].creature.current_hit_points = 0
        cm._check_summon_death(wolf_id)

        assert wolf_id not in cm.combatants
        assert wolf_id not in cm.summon_links


class TestWildShape:
    def test_wild_shape_stores_original(self):
        """Wild Shape should store the original creature for reversion."""
        action = _summon_action(is_wild_shape=True)
        cm, druid_id = _setup_combat(player_actions=[action])

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            cm.execute_summon(HexCoord(4, 4))

        assert druid_id in cm.stored_creatures

    def test_wild_shape_revert_on_death(self):
        """When Wild Shape form hits 0 HP, original creature is restored."""
        action = _summon_action(is_wild_shape=True)
        cm, druid_id = _setup_combat(player_actions=[action])

        original_name = cm.combatants[druid_id].creature.name
        original_hp = cm.combatants[druid_id].creature.max_hit_points

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            cm.execute_summon(HexCoord(4, 4))

        wolf_ids = [cid for cid in cm.combatants if "wolf" in cid.lower()]
        wolf_id = wolf_ids[0]

        cm.combatants[wolf_id].creature.current_hit_points = 0
        cm._check_summon_death(wolf_id)

        assert wolf_id not in cm.combatants
        assert cm.combatants[druid_id].creature.name == original_name
        assert cm.combatants[druid_id].creature.max_hit_points == original_hp

    def test_wild_shape_places_at_summoner_position(self):
        """Wild Shape bear should appear at the summoner's position, not clicked hex."""
        action = _summon_action(is_wild_shape=True)
        cm, druid_id = _setup_combat(player_actions=[action])
        druid_pos = cm.combatants[druid_id].position

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            # Pass a different hex — but Wild Shape should use summoner's position
            cm.execute_summon(druid_pos)

        wolf_ids = [cid for cid in cm.combatants if "wolf" in cid.lower()]
        assert len(wolf_ids) == 1
        assert cm.combatants[wolf_ids[0]].position == druid_pos

    def test_wild_shape_removes_summoner_from_grid(self):
        """When Wild Shaping, the original creature should be removed from the grid."""
        action = _summon_action(is_wild_shape=True)
        cm, druid_id = _setup_combat(player_actions=[action])
        druid_pos = cm.combatants[druid_id].position

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            cm.execute_summon(druid_pos)

        # Summoner should have no grid position (they transformed)
        assert cm.combatants[druid_id].position is None

    def test_wild_shape_revert_places_original_on_grid(self):
        """After Wild Shape revert, the original creature should be back on the grid."""
        action = _summon_action(is_wild_shape=True)
        cm, druid_id = _setup_combat(player_actions=[action])
        druid_pos = cm.combatants[druid_id].position

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            cm.execute_summon(druid_pos)

        wolf_ids = [cid for cid in cm.combatants if "wolf" in cid.lower()]
        wolf_id = wolf_ids[0]
        wolf_pos = cm.combatants[wolf_id].position

        # Kill the wolf form
        cm.combatants[wolf_id].creature.current_hit_points = 0
        cm._check_summon_death(wolf_id)

        # Original creature should be placed at the wolf's position
        assert cm.combatants[druid_id].position == wolf_pos


class TestNonConcentrationSummon:
    def test_non_concentration_summon_persists(self):
        """A non-concentration summon (Find Familiar) should NOT be removed
        when _cleanup_concentration_summons runs."""
        action = _summon_action(is_wild_shape=False)
        action.requires_concentration = False  # Find Familiar is not concentration
        cm, druid_id = _setup_combat(player_actions=[action])

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            cm.execute_summon(HexCoord(4, 4))

        wolf_ids = [cid for cid in cm.combatants if "wolf" in cid.lower()]
        assert len(wolf_ids) == 1

        # Run cleanup — this should NOT remove the familiar
        cm._cleanup_concentration_summons()

        # Wolf should still be there
        assert wolf_ids[0] in cm.combatants

    def test_non_concentration_summon_survives_combat_actions(self):
        """A non-concentration familiar should survive after attacks and
        other actions that trigger _cleanup_orphaned_zones."""
        action = _summon_action(is_wild_shape=False)
        action.requires_concentration = False
        cm, druid_id = _setup_combat(player_actions=[action])

        with patch.object(CombatManager, "_load_creature",
                          side_effect=lambda e, d: e.creature_data.model_copy(deep=True) if e.creature_data else _make_wolf()):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            cm.execute_summon(HexCoord(4, 4))

        wolf_ids = [cid for cid in cm.combatants if "wolf" in cid.lower()]
        wolf_id = wolf_ids[0]

        # Trigger the same cleanup path that runs after attacks
        cm._cleanup_orphaned_zones()

        # Wolf should still be present
        assert wolf_id in cm.combatants
        assert cm.combatants[wolf_id].position == HexCoord(4, 4)
