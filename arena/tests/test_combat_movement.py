"""Tests for combat movement system."""

import pytest
from arena.combat.movement import MovementTracker
from arena.combat.events import CombatEventType
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.encounter import TerrainType


class TestMovementTracker:
    """Tests for MovementTracker."""

    def _make_grid(self, width=10, height=10):
        return HexGrid(width, height)

    def test_reset(self):
        mt = MovementTracker(creature_id="", max_movement=0, remaining_movement=0)
        mt.reset("fighter", 30)
        assert mt.creature_id == "fighter"
        assert mt.max_movement == 30
        assert mt.remaining_movement == 30
        assert mt.has_moved is False

    def test_get_reachable_creature_not_on_grid(self):
        mt = MovementTracker(creature_id="missing", max_movement=30, remaining_movement=30)
        grid = self._make_grid()
        result = mt.get_reachable(grid)
        assert result == {}

    def test_get_reachable_returns_hexes(self):
        grid = self._make_grid()
        start = HexCoord(5, 5)
        grid.place_creature(start, "fighter")
        mt = MovementTracker(creature_id="fighter", max_movement=30, remaining_movement=30)
        reachable = mt.get_reachable(grid)
        assert len(reachable) > 0
        assert (5, 5) in reachable  # Starting hex always included

    def test_try_move_success(self):
        grid = self._make_grid()
        start = HexCoord(5, 5)
        grid.place_creature(start, "fighter")
        mt = MovementTracker(creature_id="fighter", max_movement=30, remaining_movement=30)
        target = HexCoord(5, 6)  # Adjacent hex
        success, event = mt.try_move(target, grid)
        assert success is True
        assert event is not None
        assert event.event_type == CombatEventType.MOVEMENT
        assert mt.remaining_movement < 30
        assert mt.has_moved is True
        # Creature should be at target
        assert grid.find_creature("fighter") == target

    def test_try_move_deducts_cost(self):
        grid = self._make_grid()
        start = HexCoord(5, 5)
        grid.place_creature(start, "fighter")
        mt = MovementTracker(creature_id="fighter", max_movement=30, remaining_movement=30)
        # Normal terrain costs 5 ft per hex
        target = HexCoord(5, 6)
        mt.try_move(target, grid)
        assert mt.remaining_movement == 25

    def test_try_move_to_occupied_fails(self):
        grid = self._make_grid()
        grid.place_creature(HexCoord(5, 5), "fighter")
        grid.place_creature(HexCoord(5, 6), "goblin")
        mt = MovementTracker(creature_id="fighter", max_movement=30, remaining_movement=30)
        success, event = mt.try_move(HexCoord(5, 6), grid)
        assert success is False
        assert event is None

    def test_try_move_out_of_range_fails(self):
        grid = self._make_grid()
        grid.place_creature(HexCoord(0, 0), "fighter")
        mt = MovementTracker(creature_id="fighter", max_movement=5, remaining_movement=5)
        # Try to move 2 hexes away (costs 10 ft)
        success, event = mt.try_move(HexCoord(0, 2), grid)
        assert success is False

    def test_try_move_creature_not_on_grid(self):
        grid = self._make_grid()
        mt = MovementTracker(creature_id="missing", max_movement=30, remaining_movement=30)
        success, event = mt.try_move(HexCoord(5, 5), grid)
        assert success is False
        assert event is None

    def test_try_move_difficult_terrain_costs_more(self):
        grid = self._make_grid()
        grid.place_creature(HexCoord(5, 5), "fighter")
        grid.set_terrain(HexCoord(5, 6), TerrainType.DIFFICULT)
        mt = MovementTracker(creature_id="fighter", max_movement=30, remaining_movement=30)
        mt.try_move(HexCoord(5, 6), grid)
        # Difficult terrain costs 10 ft
        assert mt.remaining_movement == 20

    def test_multiple_moves_in_turn(self):
        grid = self._make_grid()
        grid.place_creature(HexCoord(5, 5), "fighter")
        mt = MovementTracker(creature_id="fighter", max_movement=30, remaining_movement=30)
        mt.try_move(HexCoord(5, 6), grid)
        assert mt.remaining_movement == 25
        mt.try_move(HexCoord(5, 7), grid)
        assert mt.remaining_movement == 20
