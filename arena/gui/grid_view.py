"""Grid view component for rendering and interacting with the hex grid."""

from __future__ import annotations

from pathlib import Path

import pygame

from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid, HexCell
from arena.gui.camera import Camera
from arena.gui.renderer import (
    draw_hex,
    draw_hex_highlight,
    draw_text_centered,
    draw_terrain_indicator,
    hex_vertices,
)
from arena.models.encounter import TerrainType
from arena.util.constants import (
    COLORS,
    TERRAIN_COLORS,
    DRAG_THRESHOLD,
    parse_color,
)
from arena.util.settings import get_settings


class GridView:
    """Manages hex grid rendering, camera, and mouse interaction.

    Encapsulates the grid data, camera state, and user interaction
    (hover, selection, panning, zooming). Designed to be embedded
    in a screen or used directly by the App.
    """

    def __init__(
        self,
        grid: HexGrid,
        screen_width: int,
        screen_height: int,
        origin: tuple[int, int] = (0, 0),
    ) -> None:
        """Initialize the grid view.

        Args:
            grid: The hex grid to render.
            screen_width: Width of the grid view area in pixels.
            screen_height: Height of the grid view area in pixels.
            origin: (x, y) offset on the screen surface. Used to correctly
                    map screen-global mouse positions to grid coordinates
                    when the view is embedded in a larger screen layout.
        """
        self.grid = grid
        self.camera = Camera()
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.origin = origin

        # Interaction state
        self.hovered_hex: HexCoord | None = None
        self.selected_hex: HexCoord | None = None

        # Display options
        self.show_coordinates: bool = get_settings().display.show_hex_coordinates

        # Background image (loaded via set_background)
        self._background_surface: pygame.Surface | None = None
        self._background_raw: pygame.Surface | None = None  # Original unscaled
        self._bg_offset_x: float = 0.0  # World-space offset
        self._bg_offset_y: float = 0.0
        self._bg_scale: float = 1.0  # Scale multiplier (1.0 = fill grid bounds)

        # Drag state (private)
        self._is_dragging: bool = False
        self._mouse_button_held: bool = False
        self._drag_start: tuple[int, int] | None = None
        self._last_mouse_pos: tuple[int, int] = (0, 0)

        # Center camera on grid initially
        self._center_camera_on_grid()

    def _center_camera_on_grid(self) -> None:
        """Position the camera so the grid is centered in the viewport."""
        center_q = self.grid.width // 2
        center_r = self.grid.height // 2
        center_coord = HexCoord(center_q, center_r)
        cx, cy = center_coord.to_pixel(get_settings().display.default_hex_size)

        self.camera.x = cx - self.screen_width / (2 * self.camera.zoom)
        self.camera.y = cy - self.screen_height / (2 * self.camera.zoom)

    @property
    def has_background(self) -> bool:
        """Whether a background image is currently set."""
        return self._background_surface is not None

    def set_background(self, path: Path | None) -> None:
        """Load a background image to render behind the hex grid.

        Args:
            path: Full path to the image file, or None to clear.
        """
        if path is None or not path.exists():
            self._background_surface = None
            self._background_raw = None
            return
        try:
            raw = pygame.image.load(str(path)).convert()
            self._background_raw = raw
            # Scale to fill the viewport; will be repositioned by camera
            self._background_surface = pygame.transform.smoothscale(
                raw, (self.screen_width, self.screen_height),
            )
        except (pygame.error, FileNotFoundError, OSError):
            self._background_surface = None
            self._background_raw = None

    def set_background_transform(
        self, offset: tuple[float, float], scale: float,
    ) -> None:
        """Set the background image transform.

        Args:
            offset: World-space (x, y) offset from default position.
            scale: Scale multiplier (1.0 = fill grid bounds).
        """
        self._bg_offset_x, self._bg_offset_y = offset
        self._bg_scale = max(0.25, min(4.0, scale))

    def get_background_transform(
        self,
    ) -> tuple[tuple[float, float], float]:
        """Get current background transform for saving.

        Returns:
            Tuple of ((offset_x, offset_y), scale).
        """
        return ((self._bg_offset_x, self._bg_offset_y), self._bg_scale)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> None:
        """Process a single pygame event for grid interaction."""
        if event.type == pygame.MOUSEMOTION:
            self._handle_mouse_motion(event)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            self._handle_mouse_button_down(event)
        elif event.type == pygame.MOUSEBUTTONUP:
            self._handle_mouse_button_up(event)
        elif event.type == pygame.MOUSEWHEEL:
            self._handle_mouse_wheel(event)
        elif event.type == pygame.KEYDOWN:
            self._handle_key_down(event)

    def _handle_mouse_motion(self, event: pygame.event.Event) -> None:
        """Handle mouse movement: update hover and drag."""
        # Always update hovered hex
        self.hovered_hex = self._screen_to_hex(event.pos[0], event.pos[1])

        # Handle dragging
        if self._mouse_button_held and self._drag_start is not None:
            dx = event.pos[0] - self._last_mouse_pos[0]
            dy = event.pos[1] - self._last_mouse_pos[1]

            # Check if we've exceeded the drag threshold
            total_dx = event.pos[0] - self._drag_start[0]
            total_dy = event.pos[1] - self._drag_start[1]
            dist = (total_dx**2 + total_dy**2) ** 0.5

            if dist > DRAG_THRESHOLD:
                self._is_dragging = True
                self.camera.pan(dx, dy)

        self._last_mouse_pos = event.pos

    def _handle_mouse_button_down(self, event: pygame.event.Event) -> None:
        """Handle mouse button press: start potential drag or click."""
        if event.button == 1:  # Left click
            self._mouse_button_held = True
            self._drag_start = event.pos
            self._last_mouse_pos = event.pos
            self._is_dragging = False

    def _handle_mouse_button_up(self, event: pygame.event.Event) -> None:
        """Handle mouse button release: finalize click or drag."""
        if event.button == 1:
            self._mouse_button_held = False

            if not self._is_dragging:
                # This was a click, not a drag
                clicked_hex = self._screen_to_hex(event.pos[0], event.pos[1])
                if clicked_hex is not None and clicked_hex == self.selected_hex:
                    # Toggle off: clicking the selected hex deselects it
                    self.selected_hex = None
                else:
                    self.selected_hex = clicked_hex

            self._drag_start = None
            self._is_dragging = False

    def _handle_mouse_wheel(self, event: pygame.event.Event) -> None:
        """Handle mouse wheel: zoom in/out centered on cursor."""
        zoom_factor = get_settings().display.zoom_speed
        mouse_x, mouse_y = pygame.mouse.get_pos()
        # Adjust for origin offset so zoom centers correctly
        local_x = mouse_x - self.origin[0]
        local_y = mouse_y - self.origin[1]
        if event.y > 0:
            self.camera.zoom_at(local_x, local_y, zoom_factor)
        elif event.y < 0:
            self.camera.zoom_at(local_x, local_y, 1.0 / zoom_factor)

    def _handle_key_down(self, event: pygame.event.Event) -> None:
        """Handle key presses for grid-specific controls."""
        if event.key == pygame.K_g:
            self.show_coordinates = not self.show_coordinates
        elif event.key == pygame.K_HOME:
            self._center_camera_on_grid()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def update(self) -> None:
        """Per-frame update — advance smooth camera panning."""
        self.camera.update()

    def render(self, surface: pygame.Surface) -> None:
        """Render the hex grid to the given surface.

        Uses a multi-pass approach:
        0. (Optional) Draw background image behind hexes.
        1. Draw all hex fills and borders (with terrain colors).
        2. Draw hover and selection highlights on top.
        """
        q_min, q_max, r_min, r_max = self._get_visible_hex_range()
        scaled_size = get_settings().display.default_hex_size * self.camera.zoom
        border_color = parse_color(COLORS["hex_border"])

        # Pass 0: Background image (pans/zooms with camera). At 0% opacity the
        # image is skipped entirely and hexes render opaque — the plain field.
        bg_opacity = get_settings().display.battle_background_opacity
        bg_visible = self._background_surface is not None and bg_opacity > 0
        if bg_visible:
            self._render_background(surface, bg_opacity)

        # Pass 1: Draw all visible hexes
        use_alpha = bg_visible
        for q in range(q_min, q_max + 1):
            for r in range(r_min, r_max + 1):
                coord = HexCoord(q, r)
                cell = self.grid.get_cell(coord)
                if cell is None:
                    continue

                # Convert world position to screen position
                world_x, world_y = coord.to_pixel(get_settings().display.default_hex_size)
                local_x, local_y = self.camera.world_to_screen(world_x, world_y)
                center = (local_x + self.origin[0], local_y + self.origin[1])

                fill_color = self._get_hex_fill_color(cell)

                if use_alpha:
                    # Semi-transparent hex so background shows through
                    self._draw_hex_alpha(
                        surface, center, scaled_size,
                        fill_color, border_color, alpha=100,
                    )
                else:
                    draw_hex(surface, center, scaled_size, fill_color, border_color)

                # Draw terrain indicator for special terrain
                if cell.terrain not in (
                    TerrainType.NORMAL,
                    TerrainType.DIFFICULT,
                    TerrainType.WATER,
                    TerrainType.HAZARD,
                ):
                    draw_terrain_indicator(
                        surface, center, scaled_size, cell.terrain
                    )

        # Pass 2: Draw highlights on top
        ox, oy = self.origin
        if self.hovered_hex is not None and self.grid.is_valid(self.hovered_hex):
            wx, wy = self.hovered_hex.to_pixel(get_settings().display.default_hex_size)
            lx, ly = self.camera.world_to_screen(wx, wy)
            draw_hex_highlight(
                surface,
                (lx + ox, ly + oy),
                scaled_size,
                parse_color(COLORS["hex_hover"]),
                alpha=128,
            )

        if self.selected_hex is not None and self.grid.is_valid(self.selected_hex):
            wx, wy = self.selected_hex.to_pixel(get_settings().display.default_hex_size)
            lx, ly = self.camera.world_to_screen(wx, wy)
            draw_hex_highlight(
                surface,
                (lx + ox, ly + oy),
                scaled_size,
                parse_color(COLORS["hex_selected"]),
                alpha=160,
            )

        # Pass 3: Coordinate labels (optional)
        if self.show_coordinates and scaled_size > 20:
            label_color = parse_color(COLORS["text_secondary"])
            font_size = max(10, int(12 * self.camera.zoom))
            for q in range(q_min, q_max + 1):
                for r in range(r_min, r_max + 1):
                    coord = HexCoord(q, r)
                    if not self.grid.is_valid(coord):
                        continue
                    wx, wy = coord.to_pixel(get_settings().display.default_hex_size)
                    lx, ly = self.camera.world_to_screen(wx, wy)
                    draw_text_centered(
                        surface,
                        f"{q},{r}",
                        (lx + ox, ly + oy),
                        label_color,
                        font_size=font_size,
                    )

    # ------------------------------------------------------------------
    # Background rendering
    # ------------------------------------------------------------------

    def _render_background(self, surface: pygame.Surface, opacity: int = 100) -> None:
        """Draw the background image with offset/scale transform applied.
        `opacity` (0–100) fades the art toward the plain field — the in-fight
        slider for when the image makes terrain hard to read."""
        if self._background_raw is None:
            return

        # Compute base world-space bounding box of the full grid
        hex_size = get_settings().display.default_hex_size
        tl = HexCoord(0, 0).to_pixel(hex_size)
        br = HexCoord(self.grid.width - 1, self.grid.height - 1).to_pixel(hex_size)
        base_x0 = tl[0] - hex_size
        base_y0 = tl[1] - hex_size
        base_x1 = br[0] + hex_size
        base_y1 = br[1] + hex_size

        # Apply centered scaling
        base_w = base_x1 - base_x0
        base_h = base_y1 - base_y0
        center_x = (base_x0 + base_x1) / 2
        center_y = (base_y0 + base_y1) / 2
        scaled_w = base_w * self._bg_scale
        scaled_h = base_h * self._bg_scale

        # Apply offset
        world_x0 = center_x - scaled_w / 2 + self._bg_offset_x
        world_y0 = center_y - scaled_h / 2 + self._bg_offset_y
        world_x1 = center_x + scaled_w / 2 + self._bg_offset_x
        world_y1 = center_y + scaled_h / 2 + self._bg_offset_y

        # Convert world corners to screen space
        sx0, sy0 = self.camera.world_to_screen(world_x0, world_y0)
        sx1, sy1 = self.camera.world_to_screen(world_x1, world_y1)

        dest_w = int(sx1 - sx0)
        dest_h = int(sy1 - sy0)
        if dest_w <= 0 or dest_h <= 0:
            return

        # Scale the raw image to fill the transformed footprint
        scaled = pygame.transform.smoothscale(self._background_raw, (dest_w, dest_h))
        if opacity < 100:
            scaled.set_alpha(int(opacity * 255 / 100))
        ox, oy = self.origin
        surface.blit(scaled, (int(sx0) + ox, int(sy0) + oy))

    @staticmethod
    def _draw_hex_alpha(
        surface: pygame.Surface,
        center: tuple[float, float],
        size: float,
        fill_color: tuple[int, int, int],
        border_color: tuple[int, int, int],
        alpha: int = 100,
    ) -> None:
        """Draw a hex with a semi-transparent fill and opaque border."""
        verts = hex_vertices(center[0], center[1], size)
        min_x = int(min(v[0] for v in verts)) - 1
        min_y = int(min(v[1] for v in verts)) - 1
        max_x = int(max(v[0] for v in verts)) + 2
        max_y = int(max(v[1] for v in verts)) + 2
        w = max_x - min_x
        h = max_y - min_y
        if w <= 0 or h <= 0:
            return

        # Offset vertices to local coords
        local_verts = [(v[0] - min_x, v[1] - min_y) for v in verts]

        tmp = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.polygon(tmp, (*fill_color, alpha), local_verts)
        pygame.draw.polygon(tmp, (*border_color, 255), local_verts, 1)
        surface.blit(tmp, (min_x, min_y))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_visible_hex_range(self) -> tuple[int, int, int, int]:
        """Calculate the range of hex coordinates visible on screen.

        Returns:
            Tuple of (q_min, q_max, r_min, r_max) clamped to grid bounds.
        """
        # Get world-space bounding box of the screen
        top_left_world = self.camera.screen_to_world(0, 0)
        bottom_right_world = self.camera.screen_to_world(
            self.screen_width, self.screen_height
        )

        # Convert corners to hex coordinates
        margin = 2  # Extra hexes for partially visible edges
        tl_hex = HexCoord.from_pixel(top_left_world[0], top_left_world[1], get_settings().display.default_hex_size)
        br_hex = HexCoord.from_pixel(
            bottom_right_world[0], bottom_right_world[1], get_settings().display.default_hex_size
        )

        q_min = max(0, tl_hex.q - margin)
        q_max = min(self.grid.width - 1, br_hex.q + margin)
        r_min = max(0, tl_hex.r - margin)
        r_max = min(self.grid.height - 1, br_hex.r + margin)

        return (q_min, q_max, r_min, r_max)

    def _get_hex_fill_color(self, cell: HexCell) -> tuple[int, int, int]:
        """Get the fill color for a hex cell based on its terrain type.

        Args:
            cell: The hex cell to get the color for.

        Returns:
            RGB tuple for the fill color.
        """
        terrain_value = cell.terrain.value
        color_key = TERRAIN_COLORS.get(terrain_value, "hex_fill")
        return parse_color(COLORS[color_key])

    def _screen_to_hex(
        self, screen_x: int, screen_y: int
    ) -> HexCoord | None:
        """Convert screen coordinates to a hex coordinate.

        Adjusts for the origin offset so that screen-global mouse
        positions are correctly mapped when the grid view is embedded.

        Args:
            screen_x: X position in screen pixels (global).
            screen_y: Y position in screen pixels (global).

        Returns:
            The HexCoord under the cursor, or None if off-grid.
        """
        local_x = screen_x - self.origin[0]
        local_y = screen_y - self.origin[1]
        world_x, world_y = self.camera.screen_to_world(local_x, local_y)
        coord = HexCoord.from_pixel(world_x, world_y, get_settings().display.default_hex_size)
        if self.grid.is_valid(coord):
            return coord
        return None
