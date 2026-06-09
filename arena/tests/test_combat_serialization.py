"""Tests for combat state serialization (save/load mid-combat)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from arena.combat.manager import CombatManager, CombatState, TurnPhase, TurnResources
from arena.combat.serialization import serialize_combat, deserialize_combat
from arena.combat.events import CombatEvent, CombatEventType
from arena.combat.initiative import InitiativeEntry
from arena.combat.movement import MovementTracker
from arena.combat.ready_action import ReadiedAction, TriggerType
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.conditions import AppliedCondition, Condition
from arena.models.encounter import Encounter, CombatantEntry, TerrainType, TerrainHex


# ── Helpers ─────────────────────────────────────────────────────────


def _make_creature(name, hp, ac=10, strength=10, dexterity=10, is_player=True):
    return Creature(
        name=name,
        max_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(strength=strength, dexterity=dexterity),
        proficiency_bonus=2,
        is_player_controlled=is_player,
        actions=[
            Action(
                name="Sword",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Sword",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=5,
                    damage=[
                        DamageRoll(
                            dice="1d6",
                            damage_type=DamageType.SLASHING,
                            ability_modifier="strength",
                        )
                    ],
                ),
            )
        ],
    )


def _make_encounter_with_terrain():
    return Encounter(
        name="Test Save",
        grid_width=10,
        grid_height=10,
        terrain=[
            TerrainHex(position=(3, 4), terrain_type=TerrainType.DIFFICULT),
            TerrainHex(position=(5, 5), terrain_type=TerrainType.WALL),
        ],
        combatants=[
            CombatantEntry(
                creature_id="inline_player",
                creature_data=_make_creature("Fighter", hp=20, ac=15, strength=16, is_player=True),
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="inline_enemy",
                creature_data=_make_creature("Goblin", hp=7, ac=13, dexterity=14, is_player=False),
                team="enemy",
                starting_position=(3, 2),
            ),
        ],
    )


def _start_combat():
    """Create a CombatManager in IN_COMBAT state with enemy going first."""
    cm = CombatManager()
    cm.load_encounter(_make_encounter_with_terrain(), Path("."))

    with patch("arena.combat.manager.roll_die", return_value=10):
        cm.roll_initiative()

    # Force enemy to go first
    for e in cm.initiative.entries:
        if cm.combatants[e.creature_id].team == "enemy":
            e.initiative_roll = 20
        else:
            e.initiative_roll = 5
    cm.initiative.entries.sort(
        key=lambda x: (-x.initiative_roll, -x.dexterity)
    )

    cm.begin_combat()
    return cm


# ── Round-trip Tests ────────────────────────────────────────────────


class TestSerializationRoundTrip:
    """Verify serialize -> deserialize produces equivalent state."""

    def test_basic_round_trip(self):
        """A fresh combat survives a full round-trip."""
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert cm2.state == cm.state
        assert cm2.turn_phase == cm.turn_phase
        assert cm2.winner == cm.winner

    def test_json_serializable(self):
        """Serialized output is valid JSON."""
        cm = _start_combat()
        data = serialize_combat(cm)
        # Should not raise
        json_str = json.dumps(data)
        assert isinstance(json_str, str)
        # Should round-trip through JSON
        parsed = json.loads(json_str)
        cm2 = deserialize_combat(parsed)
        assert cm2.state == cm.state

    def test_version_field(self):
        """Serialized data includes a version field."""
        cm = _start_combat()
        data = serialize_combat(cm)
        assert data["version"] == 1

    def test_timestamp_field(self):
        """Serialized data includes a timestamp."""
        cm = _start_combat()
        data = serialize_combat(cm)
        assert "timestamp" in data
        assert isinstance(data["timestamp"], str)


class TestGridSerialization:
    """Verify grid state survives serialization."""

    def test_grid_dimensions(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert cm2.grid.width == cm.grid.width
        assert cm2.grid.height == cm.grid.height

    def test_terrain_preserved(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        # Check the difficult terrain cell
        cell_orig = cm.grid.get_cell(HexCoord(3, 4))
        cell_loaded = cm2.grid.get_cell(HexCoord(3, 4))
        assert cell_loaded.terrain == cell_orig.terrain
        assert cell_loaded.terrain == TerrainType.DIFFICULT

        # Check the wall cell
        cell_wall = cm2.grid.get_cell(HexCoord(5, 5))
        assert cell_wall.terrain == TerrainType.WALL

        # Check a normal cell
        cell_normal = cm2.grid.get_cell(HexCoord(0, 0))
        assert cell_normal.terrain == TerrainType.NORMAL

    def test_occupants_preserved(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        # Every combatant should be on the grid at the same position
        for cid, combatant in cm.combatants.items():
            if combatant.position:
                orig_pos = cm.grid.find_creature(cid)
                loaded_pos = cm2.grid.find_creature(cid)
                assert loaded_pos == orig_pos, f"{cid}: {loaded_pos} != {orig_pos}"


class TestCombatantSerialization:
    """Verify combatant data survives serialization."""

    def test_combatant_count(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert len(cm2.combatants) == len(cm.combatants)

    def test_creature_ids_match(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert set(cm2.combatants.keys()) == set(cm.combatants.keys())

    def test_creature_stats_preserved(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        for cid in cm.combatants:
            orig = cm.combatants[cid].creature
            loaded = cm2.combatants[cid].creature
            assert loaded.name == orig.name
            assert loaded.max_hit_points == orig.max_hit_points
            assert loaded.current_hit_points == orig.current_hit_points
            assert loaded.armor_class == orig.armor_class
            assert loaded.is_player_controlled == orig.is_player_controlled

    def test_team_preserved(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        for cid in cm.combatants:
            assert cm2.combatants[cid].team == cm.combatants[cid].team

    def test_position_preserved(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        for cid in cm.combatants:
            assert cm2.combatants[cid].position == cm.combatants[cid].position

    def test_mutated_hp_preserved(self):
        """HP changes survive serialization."""
        cm = _start_combat()

        # Damage the goblin
        for cid, c in cm.combatants.items():
            if c.team == "enemy":
                c.creature.current_hit_points = 3
                break

        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        for cid, c in cm2.combatants.items():
            if c.team == "enemy":
                assert c.creature.current_hit_points == 3

    def test_conditions_preserved(self):
        """Active conditions survive serialization."""
        cm = _start_combat()

        # Apply a condition to the fighter
        for cid, c in cm.combatants.items():
            if c.team == "player":
                c.creature.active_conditions.append(
                    AppliedCondition(
                        condition=Condition.POISONED,
                        source="Goblin",
                        duration_type="rounds",
                        duration_rounds=3,
                    )
                )
                break

        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        for cid, c in cm2.combatants.items():
            if c.team == "player":
                assert len(c.creature.active_conditions) == 1
                cond = c.creature.active_conditions[0]
                assert cond.condition == Condition.POISONED
                assert cond.source == "Goblin"
                assert cond.duration_rounds == 3

    def test_actions_preserved(self):
        """Creature actions survive serialization."""
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        for cid in cm.combatants:
            orig_actions = cm.combatants[cid].creature.actions
            loaded_actions = cm2.combatants[cid].creature.actions
            assert len(loaded_actions) == len(orig_actions)
            for orig_a, loaded_a in zip(orig_actions, loaded_actions):
                assert loaded_a.name == orig_a.name
                assert loaded_a.action_type == orig_a.action_type


class TestInitiativeSerialization:
    """Verify initiative state survives serialization."""

    def test_initiative_order(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        orig_order = [e.creature_id for e in cm.initiative.entries]
        loaded_order = [e.creature_id for e in cm2.initiative.entries]
        assert loaded_order == orig_order

    def test_current_index(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert cm2.initiative.current_index == cm.initiative.current_index

    def test_round_number(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert cm2.initiative.round_number == cm.initiative.round_number

    def test_initiative_rolls(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        for orig, loaded in zip(cm.initiative.entries, cm2.initiative.entries):
            assert loaded.initiative_roll == orig.initiative_roll
            assert loaded.dexterity == orig.dexterity
            assert loaded.is_player_controlled == orig.is_player_controlled


class TestTurnResourcesSerialization:
    """Verify turn resources survive serialization."""

    def test_default_resources(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert cm2.turn_resources.has_used_action == cm.turn_resources.has_used_action
        assert cm2.turn_resources.has_used_bonus_action == cm.turn_resources.has_used_bonus_action
        assert cm2.turn_resources.has_used_reaction == cm.turn_resources.has_used_reaction
        assert cm2.turn_resources.is_disengaging == cm.turn_resources.is_disengaging

    def test_mutated_resources(self):
        cm = _start_combat()
        cm.turn_resources.has_used_action = True
        cm.turn_resources.is_disengaging = True
        cm.turn_resources.free_actions_used = 1

        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert cm2.turn_resources.has_used_action is True
        assert cm2.turn_resources.is_disengaging is True
        assert cm2.turn_resources.free_actions_used == 1


class TestMovementSerialization:
    """Verify movement state survives serialization."""

    def test_movement_state(self):
        cm = _start_combat()
        # Simulate partial movement
        cm.movement.remaining_movement = 15
        cm.movement.has_moved = True

        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert cm2.movement.creature_id == cm.movement.creature_id
        assert cm2.movement.max_movement == cm.movement.max_movement
        assert cm2.movement.remaining_movement == 15
        assert cm2.movement.has_moved is True


class TestCombatLogSerialization:
    """Verify combat log survives serialization."""

    def test_log_events_preserved(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert len(cm2.log.events) == len(cm.log.events)

    def test_log_event_fields(self):
        cm = _start_combat()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        for orig, loaded in zip(cm.log.events, cm2.log.events):
            assert loaded.event_type == orig.event_type
            assert loaded.message == orig.message
            assert loaded.source_id == orig.source_id
            assert loaded.target_id == orig.target_id

    def test_custom_log_event(self):
        """Manually added log events survive."""
        cm = _start_combat()
        cm.log.add(CombatEvent(
            event_type=CombatEventType.INFO,
            message="Test event",
            source_id="fighter",
            target_id="goblin",
            details={"key": "value"},
        ))

        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        last_event = cm2.log.events[-1]
        assert last_event.message == "Test event"
        assert last_event.source_id == "fighter"
        assert last_event.target_id == "goblin"
        assert last_event.details == {"key": "value"}


class TestReactionAndReadiedSerialization:
    """Verify reaction tracking and readied actions survive."""

    def test_reaction_used_dict(self):
        cm = _start_combat()
        # Mark a reaction as used
        for cid in cm.combatants:
            cm.reaction_used[cid] = True
            break

        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert cm2.reaction_used == cm.reaction_used

    def test_readied_action_preserved(self):
        cm = _start_combat()

        # Set up a readied action
        player_id = None
        enemy_id = None
        for cid, c in cm.combatants.items():
            if c.team == "player":
                player_id = cid
            else:
                enemy_id = cid

        action = cm.combatants[player_id].creature.actions[0]
        cm.readied_actions[player_id] = ReadiedAction(
            creature_id=player_id,
            action=action,
            trigger_type=TriggerType.CREATURE_MOVES,
            trigger_target_id=enemy_id,
            description="Attack when goblin moves",
        )

        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert player_id in cm2.readied_actions
        ra = cm2.readied_actions[player_id]
        assert ra.creature_id == player_id
        assert ra.action.name == action.name
        assert ra.trigger_type == TriggerType.CREATURE_MOVES
        assert ra.trigger_target_id == enemy_id
        assert ra.description == "Attack when goblin moves"


class TestSelectedActionSerialization:
    """Verify selected_action survives serialization."""

    def test_null_selected_action(self):
        cm = _start_combat()
        cm.selected_action = None

        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert cm2.selected_action is None

    def test_selected_action_preserved(self):
        cm = _start_combat()
        # Select the first creature's first action
        active = cm.active_combatant
        if active and active.creature.actions:
            cm.selected_action = active.creature.actions[0]

        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert cm2.selected_action is not None
        assert cm2.selected_action.name == cm.selected_action.name


class TestEdgeCases:
    """Edge cases for serialization."""

    def test_no_grid(self):
        """CombatManager with no grid (pre-encounter load)."""
        cm = CombatManager()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert cm2.grid is None
        assert cm2.state == CombatState.NOT_STARTED

    def test_empty_combatants(self):
        cm = CombatManager()
        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert len(cm2.combatants) == 0

    def test_combatant_with_no_position(self):
        """A combatant with position=None survives."""
        cm = _start_combat()

        # Remove a combatant from the grid
        for cid, c in cm.combatants.items():
            if c.position:
                cm.grid.remove_creature(c.position)
                c.position = None
                break

        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert cm2.combatants[cid].position is None
