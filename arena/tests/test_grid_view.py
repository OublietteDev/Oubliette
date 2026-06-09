"""Tests for the GridView component."""

import pygame
import pytest

from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.gui.grid_view import GridView
from arena.models.encounter import TerrainType
from arena.util.constants import COLORS, TERRAIN_COLORS, parse_color


@pytest.fixture(autouse=True)
def init_pygame():
    """Initialize and teardown pygame for tests."""
    pygame.init()
    yield
    pygame.quit()


@pytest.fixture
def grid():
    """Create a standard test grid."""
    return HexGrid(10, 10)


@pytest.fixture
def grid_view(grid):
    """Create a GridView with a standard grid."""
    return GridView(grid, 800, 600)


class TestGridViewInit:
    """Tests for GridView initialization."""

    def test_creation(self, grid_view):
        """GridView creates successfully with grid and dimensions."""
        assert grid_view.grid is not None
        assert grid_view.camera is not None
        assert grid_view.screen_width == 800
        assert grid_view.screen_height == 600

    def test_initial_state_no_hover_no_selection(self, grid_view):
        """Initially, hovered_hex and selected_hex are None."""
        assert grid_view.hovered_hex is None
        assert grid_view.selected_hex is None

    def test_coordinates_off_by_default(self, grid_view):
        """Coordinate display should be off by default."""
        assert grid_view.show_coordinates is False

    def test_camera_exists(self, grid_view):
        """Camera should be created and accessible."""
        assert grid_view.camera is not None
        assert grid_view.camera.zoom == 1.0


class TestGridViewTerrainColors:
    """Tests for terrain-to-color mapping."""

    def test_normal_terrain_uses_hex_fill(self, grid_view, grid):
        """NORMAL terrain should use the hex_fill color."""
        cell = grid.get_cell(HexCoord(0, 0))
        color = grid_view._get_hex_fill_color(cell)
        assert color == parse_color(COLORS["hex_fill"])

    def test_difficult_terrain_color(self, grid_view, grid):
        """DIFFICULT terrain should use terrain_difficult color."""
        grid.set_terrain(HexCoord(1, 1), TerrainType.DIFFICULT)
        cell = grid.get_cell(HexCoord(1, 1))
        color = grid_view._get_hex_fill_color(cell)
        assert color == parse_color(COLORS["terrain_difficult"])

    def test_water_terrain_color(self, grid_view, grid):
        """WATER terrain should use terrain_water color."""
        grid.set_terrain(HexCoord(2, 2), TerrainType.WATER)
        cell = grid.get_cell(HexCoord(2, 2))
        color = grid_view._get_hex_fill_color(cell)
        assert color == parse_color(COLORS["terrain_water"])

    def test_all_terrain_types_have_color(self, grid_view, grid):
        """Every TerrainType value should map to a valid color."""
        for terrain_type in TerrainType:
            color_key = TERRAIN_COLORS.get(terrain_type.value)
            assert color_key is not None, f"No TERRAIN_COLORS entry for {terrain_type}"
            assert color_key in COLORS, f"COLORS missing key '{color_key}'"


class TestGridViewMouseInteraction:
    """Tests for mouse-based grid interaction."""

    def test_click_sets_selected_hex(self, grid_view):
        """Mouse down + up without drag should select a hex."""
        # Find a screen position that maps to a valid hex
        coord = HexCoord(5, 5)
        world_x, world_y = coord.to_pixel(40)  # HEX_SIZE = 40
        screen_x, screen_y = grid_view.camera.world_to_screen(world_x, world_y)

        # Simulate mouse down
        down_event = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=(screen_x, screen_y)
        )
        grid_view.handle_event(down_event)

        # Simulate mouse up at same position (no drag)
        up_event = pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=(screen_x, screen_y)
        )
        grid_view.handle_event(up_event)

        assert grid_view.selected_hex == coord

    def test_click_same_hex_deselects(self, grid_view):
        """Clicking the already-selected hex should deselect it."""
        coord = HexCoord(5, 5)
        world_x, world_y = coord.to_pixel(40)
        screen_x, screen_y = grid_view.camera.world_to_screen(world_x, world_y)

        # First click: select
        down = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=(screen_x, screen_y)
        )
        up = pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=(screen_x, screen_y)
        )
        grid_view.handle_event(down)
        grid_view.handle_event(up)
        assert grid_view.selected_hex == coord

        # Second click: deselect
        down2 = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=(screen_x, screen_y)
        )
        up2 = pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=(screen_x, screen_y)
        )
        grid_view.handle_event(down2)
        grid_view.handle_event(up2)
        assert grid_view.selected_hex is None

    def test_drag_does_not_select(self, grid_view):
        """Dragging beyond the threshold should NOT trigger selection."""
        coord = HexCoord(5, 5)
        world_x, world_y = coord.to_pixel(40)
        screen_x, screen_y = grid_view.camera.world_to_screen(world_x, world_y)

        # Mouse down
        down = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=(screen_x, screen_y)
        )
        grid_view.handle_event(down)

        # Mouse motion far from start (exceeds DRAG_THRESHOLD)
        far_x = screen_x + 50
        far_y = screen_y + 50
        motion = pygame.event.Event(
            pygame.MOUSEMOTION,
            pos=(far_x, far_y),
            rel=(50, 50),
            buttons=(1, 0, 0),
        )
        grid_view.handle_event(motion)

        # Mouse up at the far position
        up = pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=(far_x, far_y)
        )
        grid_view.handle_event(up)

        # Should NOT have selected anything
        assert grid_view.selected_hex is None

    def test_hover_off_grid_returns_none(self, grid_view):
        """Mouse position far outside the grid should yield None hovered_hex."""
        # Move mouse to a very far position that's definitely off the grid
        motion = pygame.event.Event(
            pygame.MOUSEMOTION,
            pos=(-9999, -9999),
            rel=(0, 0),
            buttons=(0, 0, 0),
        )
        grid_view.handle_event(motion)
        # The screen_to_world of (-9999, -9999) will map to a negative world coord
        # which should be off the 10x10 grid
        # hovered_hex should be None (off grid)
        assert grid_view.hovered_hex is None


class TestGridViewKeyboard:
    """Tests for keyboard controls."""

    def test_g_toggles_coordinates(self, grid_view):
        """Pressing G should toggle coordinate display."""
        assert grid_view.show_coordinates is False

        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g)
        grid_view.handle_event(event)
        assert grid_view.show_coordinates is True

        grid_view.handle_event(event)
        assert grid_view.show_coordinates is False


class TestVisibleHexRange:
    """Tests for visible hex range calculation."""

    def test_clamps_to_grid_bounds(self, grid_view, grid):
        """Visible range should never exceed grid dimensions."""
        q_min, q_max, r_min, r_max = grid_view._get_visible_hex_range()
        assert q_min >= 0
        assert r_min >= 0
        assert q_max <= grid.width - 1
        assert r_max <= grid.height - 1

    def test_range_values_are_ordered(self, grid_view):
        """q_min should be <= q_max, same for r."""
        q_min, q_max, r_min, r_max = grid_view._get_visible_hex_range()
        assert q_min <= q_max
        assert r_min <= r_max
