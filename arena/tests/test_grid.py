"""Tests for hex grid system."""

import pytest
from math import sqrt
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid, HexCell
from arena.grid.pathfinding import find_path, get_reachable_hexes
from arena.models.encounter import TerrainType


class TestHexCoord:
    """Tests for hex coordinate math."""

    def test_creation(self):
        """Basic coordinate creation."""
        coord = HexCoord(3, 4)
        assert coord.q == 3
        assert coord.r == 4

    def test_cube_coordinate_s(self):
        """Cube s coordinate derived via offset-to-cube conversion."""
        # Even column (q=0): cube_x=0, cube_z=r-(0-0)//2=r, cube_y=-0-r=-r
        coord = HexCoord(0, 3)
        cx, cy, cz = coord._to_cube()
        assert cx == 0
        assert cz == 3
        assert cy == -3
        assert cx + cy + cz == 0
        # Odd column (q=3): cube_x=3, cube_z=r-(3-1)//2=r-1
        coord2 = HexCoord(3, 1)
        cx2, cy2, cz2 = coord2._to_cube()
        assert cx2 == 3
        assert cz2 == 1 - 1  # 0
        assert cx2 + cy2 + cz2 == 0

    def test_distance_same_hex(self):
        """Distance to self should be 0."""
        coord = HexCoord(5, 5)
        assert coord.distance_to(coord) == 0

    def test_distance_adjacent(self):
        """Distance to adjacent hex should be 1."""
        coord = HexCoord(0, 0)
        for neighbor in coord.neighbors():
            assert coord.distance_to(neighbor) == 1

    def test_distance_calculation(self):
        """Distance calculation should be correct for offset coords."""
        a = HexCoord(0, 0)
        b = HexCoord(3, 2)
        # cube(0,0,0) to cube(3,-4,1) => (3+4+1)//2 = 4
        assert a.distance_to(b) == 4

    def test_neighbors_count(self):
        """Should have exactly 6 neighbors."""
        coord = HexCoord(0, 0)
        neighbors = coord.neighbors()
        assert len(neighbors) == 6

    def test_neighbors_are_adjacent(self):
        """All neighbors should be at distance 1."""
        coord = HexCoord(5, 5)
        for neighbor in coord.neighbors():
            assert coord.distance_to(neighbor) == 1

    def test_to_pixel_origin(self):
        """Origin hex should be at pixel (0, 0)."""
        coord = HexCoord(0, 0)
        x, y = coord.to_pixel(40)
        assert x == 0
        assert y == 0

    def test_to_pixel_positive(self):
        """Pixel conversion for positive coordinates (even-q offset)."""
        coord = HexCoord(1, 0)
        x, y = coord.to_pixel(40)
        assert x == 60  # 40 * 3/2 * 1
        # Odd column shifts down by half: y = 40 * sqrt(3) * (0 + 0.5 * 1)
        assert abs(y - 40 * sqrt(3) * 0.5) < 0.001

    def test_from_pixel_roundtrip(self):
        """Converting to pixel and back should give same coordinate."""
        original = HexCoord(5, 3)
        size = 40
        x, y = original.to_pixel(size)
        recovered = HexCoord.from_pixel(x, y, size)
        assert recovered == original

    def test_addition(self):
        """Coordinate addition."""
        a = HexCoord(1, 2)
        b = HexCoord(3, 4)
        result = a + b
        assert result.q == 4
        assert result.r == 6

    def test_subtraction(self):
        """Coordinate subtraction."""
        a = HexCoord(5, 7)
        b = HexCoord(2, 3)
        result = a - b
        assert result.q == 3
        assert result.r == 4

    def test_frozen(self):
        """HexCoord should be immutable (frozen)."""
        coord = HexCoord(1, 2)
        with pytest.raises(AttributeError):
            coord.q = 5


class TestHexGrid:
    """Tests for the HexGrid data structure."""

    def test_creation(self):
        """Grid creation with specified dimensions."""
        grid = HexGrid(10, 8)
        assert grid.width == 10
        assert grid.height == 8

    def test_cells_initialized(self):
        """All cells should be initialized."""
        grid = HexGrid(5, 5)
        assert len(grid.cells) == 25

    def test_get_cell_valid(self):
        """Get cell for valid coordinate."""
        grid = HexGrid(10, 10)
        cell = grid.get_cell(HexCoord(5, 5))
        assert cell is not None
        assert cell.coord == HexCoord(5, 5)

    def test_get_cell_invalid(self):
        """Get cell for invalid coordinate returns None."""
        grid = HexGrid(10, 10)
        cell = grid.get_cell(HexCoord(15, 15))
        assert cell is None

    def test_is_valid(self):
        """Coordinate validity checking."""
        grid = HexGrid(10, 10)
        assert grid.is_valid(HexCoord(0, 0))
        assert grid.is_valid(HexCoord(9, 9))
        assert not grid.is_valid(HexCoord(-1, 0))
        assert not grid.is_valid(HexCoord(10, 5))

    def test_default_terrain(self):
        """Default terrain should be normal."""
        grid = HexGrid(5, 5)
        cell = grid.get_cell(HexCoord(2, 2))
        assert cell.terrain == TerrainType.NORMAL

    def test_set_terrain(self):
        """Setting terrain type."""
        grid = HexGrid(5, 5)
        grid.set_terrain(HexCoord(2, 2), TerrainType.DIFFICULT)
        cell = grid.get_cell(HexCoord(2, 2))
        assert cell.terrain == TerrainType.DIFFICULT

    def test_is_passable_normal(self):
        """Normal terrain is passable."""
        grid = HexGrid(5, 5)
        assert grid.is_passable(HexCoord(2, 2))

    def test_is_passable_wall(self):
        """Walls are not passable."""
        grid = HexGrid(5, 5)
        grid.set_terrain(HexCoord(2, 2), TerrainType.WALL)
        assert not grid.is_passable(HexCoord(2, 2))

    def test_is_passable_pit(self):
        """Pits are not passable."""
        grid = HexGrid(5, 5)
        grid.set_terrain(HexCoord(2, 2), TerrainType.PIT)
        assert not grid.is_passable(HexCoord(2, 2))

    def test_movement_cost_normal(self):
        """Normal terrain costs 5 feet."""
        grid = HexGrid(5, 5)
        assert grid.get_movement_cost(HexCoord(2, 2)) == 5

    def test_movement_cost_difficult(self):
        """Difficult terrain costs 10 feet."""
        grid = HexGrid(5, 5)
        grid.set_terrain(HexCoord(2, 2), TerrainType.DIFFICULT)
        assert grid.get_movement_cost(HexCoord(2, 2)) == 10

    def test_place_creature(self):
        """Placing a creature on the grid."""
        grid = HexGrid(5, 5)
        result = grid.place_creature(HexCoord(2, 2), "goblin_1")
        assert result is True
        assert grid.is_occupied(HexCoord(2, 2))

    def test_place_creature_occupied(self):
        """Cannot place creature on occupied hex."""
        grid = HexGrid(5, 5)
        grid.place_creature(HexCoord(2, 2), "goblin_1")
        result = grid.place_creature(HexCoord(2, 2), "goblin_2")
        assert result is False

    def test_remove_creature(self):
        """Removing a creature from the grid."""
        grid = HexGrid(5, 5)
        grid.place_creature(HexCoord(2, 2), "goblin_1")
        removed = grid.remove_creature(HexCoord(2, 2))
        assert removed == "goblin_1"
        assert not grid.is_occupied(HexCoord(2, 2))

    def test_find_creature(self):
        """Finding a creature on the grid."""
        grid = HexGrid(5, 5)
        grid.place_creature(HexCoord(3, 4), "fighter_1")
        pos = grid.find_creature("fighter_1")
        assert pos == HexCoord(3, 4)

    def test_find_creature_not_found(self):
        """Finding nonexistent creature returns None."""
        grid = HexGrid(5, 5)
        pos = grid.find_creature("nobody")
        assert pos is None


class TestPathfinding:
    """Tests for A* pathfinding."""

    def test_find_path_simple(self):
        """Simple path between two points."""
        grid = HexGrid(10, 10)
        path = find_path(HexCoord(0, 0), HexCoord(3, 0), grid)
        assert path is not None
        assert path[0] == HexCoord(0, 0)
        assert path[-1] == HexCoord(3, 0)

    def test_find_path_length(self):
        """Path length should be optimal."""
        grid = HexGrid(10, 10)
        start = HexCoord(0, 0)
        goal = HexCoord(5, 0)
        path = find_path(start, goal, grid)
        # Path includes start and goal
        assert len(path) == start.distance_to(goal) + 1

    def test_find_path_around_wall(self):
        """Path should go around walls."""
        grid = HexGrid(10, 10)
        # Create a wall
        grid.set_terrain(HexCoord(2, 0), TerrainType.WALL)
        grid.set_terrain(HexCoord(2, 1), TerrainType.WALL)
        path = find_path(HexCoord(0, 0), HexCoord(4, 0), grid)
        assert path is not None
        # Path should not include wall hexes
        for coord in path:
            assert coord != HexCoord(2, 0)
            assert coord != HexCoord(2, 1)

    def test_find_path_no_path(self):
        """Should return None if no path exists."""
        grid = HexGrid(5, 5)
        # Completely surround the goal
        goal = HexCoord(2, 2)
        for neighbor in goal.neighbors():
            if grid.is_valid(neighbor):
                grid.set_terrain(neighbor, TerrainType.WALL)
        path = find_path(HexCoord(0, 0), goal, grid)
        # Goal itself is blocked by walls around it
        assert path is None

    def test_find_path_to_invalid(self):
        """Path to invalid coordinate returns None."""
        grid = HexGrid(5, 5)
        path = find_path(HexCoord(0, 0), HexCoord(10, 10), grid)
        assert path is None

    def test_get_reachable_hexes(self):
        """Get all hexes within movement range."""
        grid = HexGrid(10, 10)
        reachable = get_reachable_hexes(HexCoord(5, 5), grid, 15)  # 3 hexes at 5ft each
        assert (5, 5) in reachable  # Starting hex
        assert reachable[(5, 5)] == 0  # No cost to stay

    def test_reachable_respects_terrain(self):
        """Difficult terrain should cost more movement."""
        grid = HexGrid(10, 10)
        # Set adjacent hex to difficult
        grid.set_terrain(HexCoord(5, 4), TerrainType.DIFFICULT)
        reachable = get_reachable_hexes(HexCoord(5, 5), grid, 10)
        # Difficult terrain should cost 10 to enter
        if (5, 4) in reachable:
            assert reachable[(5, 4)] == 10
