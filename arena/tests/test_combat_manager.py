"""Tests for the CombatManager — integration tests for the combat loop."""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.encounter import Encounter, CombatantEntry, TerrainHex
from arena.grid.coordinates import HexCoord


def _make_creature(name, hp, ac=10, strength=10, dexterity=10, is_player=True):
    """Create a simple creature for testing."""
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


def _make_simple_encounter():
    """Create a simple encounter with 1 player vs 1 enemy."""
    return Encounter(
        name="Test",
        grid_width=10,
        grid_height=10,
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


class TestCombatManagerSetup:
    def test_initial_state(self):
        cm = CombatManager()
        assert cm.state == CombatState.NOT_STARTED
        assert cm.grid is None
        assert len(cm.combatants) == 0

    def test_load_encounter(self):
        cm = CombatManager()
        encounter = _make_simple_encounter()
        cm.load_encounter(encounter, Path("."))
        assert cm.grid is not None
        assert cm.grid.width == 10
        assert cm.grid.height == 10
        assert len(cm.combatants) == 2

    def test_creatures_placed_on_grid(self):
        cm = CombatManager()
        encounter = _make_simple_encounter()
        cm.load_encounter(encounter, Path("."))
        # Both creatures should be on the grid
        for cid, combatant in cm.combatants.items():
            assert combatant.position is not None
            found = cm.grid.find_creature(cid)
            assert found is not None

    def test_unique_ids(self):
        cm = CombatManager()
        encounter = _make_simple_encounter()
        cm.load_encounter(encounter, Path("."))
        ids = list(cm.combatants.keys())
        assert len(ids) == len(set(ids))  # All unique


class TestCombatManagerInitiative:
    def test_roll_initiative(self):
        cm = CombatManager()
        cm.load_encounter(_make_simple_encounter(), Path("."))
        cm.roll_initiative()
        assert cm.state == CombatState.ROLLING_INITIATIVE
        assert len(cm.initiative.entries) == 2

    def test_begin_combat(self):
        cm = CombatManager()
        cm.load_encounter(_make_simple_encounter(), Path("."))
        cm.roll_initiative()
        cm.begin_combat()
        assert cm.state == CombatState.IN_COMBAT
        assert cm.turn_phase == TurnPhase.AWAITING_ACTION
        assert cm.active_combatant is not None

    def test_initiative_logs_events(self):
        cm = CombatManager()
        cm.load_encounter(_make_simple_encounter(), Path("."))
        cm.roll_initiative()
        event_types = [e.event_type for e in cm.log.events]
        assert CombatEventType.COMBAT_START in event_types


class TestCombatManagerTurns:
    def _start_combat(self):
        cm = CombatManager()
        cm.load_encounter(_make_simple_encounter(), Path("."))
        cm.roll_initiative()
        cm.begin_combat()
        return cm

    def test_active_combatant_set(self):
        cm = self._start_combat()
        active = cm.active_combatant
        assert active is not None
        assert active.creature.name in ("Fighter", "Goblin")

    def test_movement_reset_for_turn(self):
        cm = self._start_combat()
        active = cm.active_combatant
        speed = active.creature.speed.get("walk", 30)
        assert cm.movement.remaining_movement == speed
        assert cm.movement.creature_id == active.creature_id

    def test_end_turn_advances(self):
        cm = self._start_combat()
        first_active = cm.active_combatant.creature_id
        cm.end_turn()
        second_active = cm.active_combatant.creature_id
        assert first_active != second_active

    def test_end_turn_logs(self):
        cm = self._start_combat()
        initial_count = len(cm.log.events)
        cm.end_turn()
        assert len(cm.log.events) > initial_count
        event_types = [e.event_type for e in cm.log.events]
        assert CombatEventType.TURN_END in event_types

    def test_round_advances_after_all_turns(self):
        cm = self._start_combat()
        assert cm.initiative.round_number == 1
        cm.end_turn()  # Second creature's turn
        cm.end_turn()  # Back to first, round 2
        assert cm.initiative.round_number == 2


class TestCombatManagerActions:
    def _start_adjacent_combat(self):
        """Start combat with creatures adjacent to each other."""
        cm = CombatManager()
        cm.load_encounter(_make_simple_encounter(), Path("."))
        cm.roll_initiative()
        cm.begin_combat()
        return cm

    def test_select_action(self):
        cm = self._start_adjacent_combat()
        active = cm.active_combatant
        action = active.creature.actions[0]
        cm.select_action(action)
        assert cm.turn_phase == TurnPhase.SELECTING_TARGET
        assert cm.selected_action == action

    def test_cancel_action(self):
        cm = self._start_adjacent_combat()
        active = cm.active_combatant
        cm.select_action(active.creature.actions[0])
        cm.cancel_action()
        assert cm.turn_phase == TurnPhase.AWAITING_ACTION
        assert cm.selected_action is None

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_execute_attack(self, mock_damage, mock_d20):
        mock_d20.return_value = 18
        mock_damage.return_value = (5, [5])
        cm = self._start_adjacent_combat()
        active = cm.active_combatant

        # Find the other combatant
        target_id = None
        for cid in cm.combatants:
            if cid != active.creature_id:
                target_id = cid
                break

        cm.select_action(active.creature.actions[0])
        result = cm.execute_attack(target_id)
        assert result is not None
        assert cm.has_used_action is True
        assert cm.turn_phase == TurnPhase.AWAITING_ACTION

    @patch("arena.combat.actions.roll_die")
    def test_try_move(self, mock_d20):
        # Mock roll to 1 so any opportunity attack misses
        mock_d20.return_value = 1
        cm = self._start_adjacent_combat()
        active = cm.active_combatant
        # Find an empty adjacent hex
        if active.position:
            neighbors = active.position.neighbors()
            for n in neighbors:
                if cm.grid.is_valid(n) and not cm.grid.is_occupied(n):
                    success = cm.try_move(n)
                    assert success is True
                    assert active.position == n
                    break


class TestCombatManagerVictory:
    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_victory_when_all_enemies_defeated(self, mock_damage, mock_d20):
        mock_d20.return_value = 18
        mock_damage.return_value = (100, [100])  # Massive damage to one-shot

        cm = CombatManager()
        cm.load_encounter(_make_simple_encounter(), Path("."))
        cm.roll_initiative()
        cm.begin_combat()

        # Find player and enemy
        player_id = None
        enemy_id = None
        for cid, c in cm.combatants.items():
            if c.team == "player":
                player_id = cid
            else:
                enemy_id = cid

        # If enemy goes first, end their turn
        active = cm.active_combatant
        if active.team == "enemy":
            cm.end_turn()

        # Player attacks enemy
        active = cm.active_combatant
        cm.select_action(active.creature.actions[0])
        cm.execute_attack(enemy_id)

        assert cm.state == CombatState.COMBAT_ENDED
        assert cm.winner == "player"

    def test_unconscious_creatures_skipped(self):
        cm = CombatManager()
        cm.load_encounter(_make_simple_encounter(), Path("."))
        cm.roll_initiative()
        cm.begin_combat()

        # Make one creature unconscious
        for cid, c in cm.combatants.items():
            if c.team == "enemy":
                c.creature.current_hit_points = 0
                break

        # Victory should be detected on next end_turn
        cm.end_turn()
        assert cm.state == CombatState.COMBAT_ENDED

    def test_reset(self):
        cm = CombatManager()
        cm.load_encounter(_make_simple_encounter(), Path("."))
        cm.roll_initiative()
        cm.begin_combat()
        cm.reset()
        assert cm.state == CombatState.NOT_STARTED
        assert len(cm.combatants) == 0
        assert cm.grid is None
        assert cm.winner is None
