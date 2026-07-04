"""The battlefield editor — the Forge's window onto a location's battle map.

A direct descendant of the original sim's 1512-line encounter-setup screen,
cut down to what a LOCATION owns: terrain painting, grid sizing, and fitting
the background image to the grid. Creature placement, teams, and lair actions
are gone — fights are story-driven, spawns are the bridge's job, and the
Forge picks the assets (this screen previews them, it never chooses them).

Launched as a subprocess (``python -m arena.battlefield_editor <spec> <out>``)
by the Forge server. The spec carries the place name, the ``battle`` block
(the pack's BattleMap dump), and ABSOLUTE paths to the chosen background and
music. Save writes ``{"battle": {...}}`` — same block, updated grid size,
terrain, and background transform — and exits; Back/ESC exits without
writing, which the Forge reads as cancel.

Controls: click hexes to paint the selected terrain (Normal doubles as an
eraser), right-drag to move the background, scroll while right-dragging to
resize it, left-drag/wheel to pan/zoom the view, G for hex labels, Home to
recenter.
"""

from __future__ import annotations

import json
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.gui.button_images import draw_image_button
from arena.gui.grid_view import GridView
from arena.gui.renderer import draw_text_centered, get_font
from arena.gui.screens.base import Screen
from arena.gui.tray_backgrounds import draw_tray_background
from arena.models.encounter import TerrainType
from arena.util.constants import COLORS, TERRAIN_COLORS, TERRAIN_NAMES, parse_color

if TYPE_CHECKING:
    from arena.gui.app import App

# Layout constants (the old editor's, unchanged)
TOP_BAR_HEIGHT = 40
LEFT_PANEL_WIDTH = 300
STATUS_BAR_HEIGHT = 40

MIN_GRID_SIZE = 5
MAX_GRID_SIZE = 40

# The hazard brush: what a painted hazard hex deals on ENTRY (walked into or
# shoved into — the engine's process_terrain_hazard_entry reads this spec).
HAZARD_DICE = ["1d4", "1d6", "1d8", "1d10", "2d4", "2d6", "2d8", "3d6", "4d6"]
HAZARD_TYPES = ["fire", "cold", "lightning", "acid", "poison", "necrotic",
                "radiant", "thunder", "force", "bludgeoning", "piercing",
                "slashing"]


class ToolMode(Enum):
    TERRAIN = auto()
    ERASE = auto()


class BattlefieldEditorScreen(Screen):
    """Edit one location's battle map and write the block back."""

    OWNS_MUSIC = True   # the App must not restart menu music over this screen

    def __init__(
        self,
        screen_width: int,
        screen_height: int,
        spec: dict,
        out_path: Path,
    ) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.app: App | None = None
        self.out_path = Path(out_path)

        # The spec: place name for the title, the battle block to edit, and
        # absolute asset paths (already resolved by the Forge server).
        self.place_name: str = spec.get("place_name") or "Battlefield"
        self._battle: dict = dict(spec.get("battle") or {})
        self._background_path: str | None = spec.get("background_path")
        self._music_path: str | None = spec.get("music_path")

        self.grid_width = int(self._battle.get("grid_width", 20))
        self.grid_height = int(self._battle.get("grid_height", 15))

        # Tool state
        self.tool_mode = ToolMode.TERRAIN
        self.selected_terrain = TerrainType.COVER_HALF
        self.hazard_dice_i = HAZARD_DICE.index("1d6")
        self.hazard_type_i = HAZARD_TYPES.index("fire")

        # UI state
        self.status_message = ""
        self.status_timer = 0
        self._grid_owns_mouse = False
        self.back_hovered = False
        self.save_hovered = False
        self.preview_hovered = False
        self._previewing = False

        # Background edit state (right-click drag)
        self._bg_edit_mode = False
        self._bg_drag_start: tuple[int, int] | None = None
        self._bg_drag_start_offset: tuple[float, float] = (0.0, 0.0)

        # Authored extra_data survives the editor untouched UNLESS the hex is
        # repainted/erased (the grid's cells don't carry it): {(q, r): dict}.
        self._extra_data: dict[tuple[int, int], dict] = {}

        self._build_ui_rects()
        self._create_grid()
        self._load_battle()

    def on_enter(self, app: App) -> None:
        self.app = app
        # The author's headspace: silence until they hit Preview.
        from arena.audio.manager import get_sound_manager
        get_sound_manager().stop_music()

    def on_exit(self) -> None:
        from arena.audio.manager import get_sound_manager
        get_sound_manager().stop_music()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _build_ui_rects(self) -> None:
        sw, sh = self.screen_width, self.screen_height

        self.top_bar_rect = pygame.Rect(0, 0, sw, TOP_BAR_HEIGHT)
        self.left_panel_rect = pygame.Rect(
            0, TOP_BAR_HEIGHT, LEFT_PANEL_WIDTH,
            sh - TOP_BAR_HEIGHT - STATUS_BAR_HEIGHT,
        )
        self.grid_area_rect = pygame.Rect(
            LEFT_PANEL_WIDTH, TOP_BAR_HEIGHT,
            sw - LEFT_PANEL_WIDTH,
            sh - TOP_BAR_HEIGHT - STATUS_BAR_HEIGHT,
        )
        self.status_bar_rect = pygame.Rect(
            0, sh - STATUS_BAR_HEIGHT, sw, STATUS_BAR_HEIGHT,
        )

        # Top bar buttons
        self.back_btn = pygame.Rect(10, 6, 80, 28)
        self.save_btn = pygame.Rect(sw - 100, 6, 90, 28)

        # Grid size controls
        gs_y = TOP_BAR_HEIGHT + 40
        self.width_minus_btn = pygame.Rect(80, gs_y, 24, 24)
        self.width_plus_btn = pygame.Rect(160, gs_y, 24, 24)
        self.height_minus_btn = pygame.Rect(80, gs_y + 30, 24, 24)
        self.height_plus_btn = pygame.Rect(160, gs_y + 30, 24, 24)

        # Music preview button (shown only when the place has a track)
        self.preview_btn = pygame.Rect(80, TOP_BAR_HEIGHT + 108, 110, 24)

        # Tool mode buttons
        tool_y = TOP_BAR_HEIGHT + 150
        self.tool_buttons = {
            ToolMode.TERRAIN: pygame.Rect(20, tool_y, 84, 28),
            ToolMode.ERASE: pygame.Rect(110, tool_y, 84, 28),
        }

        # Terrain palette start Y
        self.context_start_y = tool_y + 44

    def _create_grid(self) -> None:
        self.grid = HexGrid(self.grid_width, self.grid_height)
        self.grid_view = GridView(
            self.grid,
            self.grid_area_rect.width,
            self.grid_area_rect.height,
            origin=(self.grid_area_rect.x, self.grid_area_rect.y),
        )

    def _load_battle(self) -> None:
        """Populate the grid from the battle block."""
        for th in self._battle.get("terrain") or []:
            q, r = th["position"]
            coord = HexCoord(int(q), int(r))
            if not self.grid.is_valid(coord):
                continue
            try:
                kind = TerrainType(th["terrain_type"])
            except ValueError:
                continue   # newer pack than engine — keep it out of the grid
            self.grid.set_terrain(coord, kind)
            extra = th.get("extra_data") or {}
            if extra:
                self._extra_data[(coord.q, coord.r)] = dict(extra)

        if self._background_path:
            self.grid_view.set_background(Path(self._background_path))
            self.grid_view.set_background_transform(
                tuple(self._battle.get("background_offset") or (0.0, 0.0)),
                float(self._battle.get("background_scale", 1.0)),
            )

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> None:
        # ESC cancels — exit without writing (the Forge reads that as cancel)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.quit()
            return

        if event.type == pygame.MOUSEMOTION:
            pos = event.pos
            self.back_hovered = self.back_btn.collidepoint(pos)
            self.save_hovered = self.save_btn.collidepoint(pos)
            self.preview_hovered = (
                self._music_path is not None
                and self.preview_btn.collidepoint(pos)
            )

            # Background drag (world-space)
            if self._bg_edit_mode and self._bg_drag_start is not None:
                dx_world = (pos[0] - self._bg_drag_start[0]) / self.grid_view.camera.zoom
                dy_world = (pos[1] - self._bg_drag_start[1]) / self.grid_view.camera.zoom
                new_offset = (
                    self._bg_drag_start_offset[0] + dx_world,
                    self._bg_drag_start_offset[1] + dy_world,
                )
                _, scale = self.grid_view.get_background_transform()
                self.grid_view.set_background_transform(new_offset, scale)

            if self.grid_area_rect.collidepoint(pos):
                self.grid_view.handle_event(event)
            return

        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if self._bg_edit_mode and self.grid_area_rect.collidepoint(pos):
                offset, scale = self.grid_view.get_background_transform()
                self.grid_view.set_background_transform(offset, scale + event.y * 0.1)
            elif self.grid_area_rect.collidepoint(pos):
                self.grid_view.handle_event(event)
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            pos = event.pos
            if event.button == 1:
                self._grid_owns_mouse = self.grid_area_rect.collidepoint(pos)
                if self._grid_owns_mouse:
                    self.grid_view.handle_event(event)
            elif event.button == 3 and self._background_path:
                if self.grid_area_rect.collidepoint(pos):
                    self._bg_edit_mode = True
                    self._bg_drag_start = pos
                    offset, _ = self.grid_view.get_background_transform()
                    self._bg_drag_start_offset = offset
            return

        if event.type == pygame.MOUSEBUTTONUP:
            pos = event.pos
            if event.button == 3:
                self._bg_edit_mode = False
                self._bg_drag_start = None
                return
            if event.button != 1:
                return

            if self.top_bar_rect.collidepoint(pos):
                self._handle_top_bar_click(pos)
            elif self.left_panel_rect.collidepoint(pos):
                self._handle_left_panel_click(pos)
            elif self.grid_area_rect.collidepoint(pos) and self._grid_owns_mouse:
                was_dragging = self.grid_view._is_dragging
                self.grid_view.handle_event(event)
                self._grid_owns_mouse = False
                if not was_dragging:
                    clicked = self.grid_view._screen_to_hex(pos[0], pos[1])
                    if clicked is not None and self.grid.is_valid(clicked):
                        self._handle_grid_click(clicked)
            else:
                self._grid_owns_mouse = False
            return

        # Forward remaining keys to the grid view (G for coords, Home)
        if event.type == pygame.KEYDOWN:
            self.grid_view.handle_event(event)

    def _handle_top_bar_click(self, pos: tuple[int, int]) -> None:
        if self.back_btn.collidepoint(pos):
            self.app.quit()                    # cancel: no out-file
        elif self.save_btn.collidepoint(pos):
            self._save_and_close()

    def _handle_left_panel_click(self, pos: tuple[int, int]) -> None:
        if self.width_minus_btn.collidepoint(pos):
            self._adjust_grid_size(-1, 0)
            return
        if self.width_plus_btn.collidepoint(pos):
            self._adjust_grid_size(1, 0)
            return
        if self.height_minus_btn.collidepoint(pos):
            self._adjust_grid_size(0, -1)
            return
        if self.height_plus_btn.collidepoint(pos):
            self._adjust_grid_size(0, 1)
            return

        if self._music_path and self.preview_btn.collidepoint(pos):
            self._toggle_preview()
            return

        for mode, rect in self.tool_buttons.items():
            if rect.collidepoint(pos):
                self.tool_mode = mode
                return

        if self.tool_mode == ToolMode.TERRAIN:
            self._handle_terrain_palette_click(pos)

    @property
    def hazard_spec(self) -> str:
        """The brush's damage spec, e.g. "1d6 fire"."""
        return f"{HAZARD_DICE[self.hazard_dice_i]} {HAZARD_TYPES[self.hazard_type_i]}"

    def _hazard_cfg_rects(self) -> dict[str, pygame.Rect]:
        """The ◄/► cycler buttons shown below the palette while the Hazard
        brush is selected."""
        y0 = self.context_start_y + len(TerrainType) * 34 + 14
        return {
            "dice_prev": pygame.Rect(20, y0 + 22, 22, 22),
            "dice_next": pygame.Rect(160, y0 + 22, 22, 22),
            "type_prev": pygame.Rect(20, y0 + 50, 22, 22),
            "type_next": pygame.Rect(160, y0 + 50, 22, 22),
        }

    def _handle_terrain_palette_click(self, pos: tuple[int, int]) -> None:
        item_h, gap, x, w = 30, 4, 20, 260
        for i, terrain_type in enumerate(TerrainType):
            rect = pygame.Rect(x, self.context_start_y + i * (item_h + gap), w, item_h)
            if rect.collidepoint(pos):
                self.selected_terrain = terrain_type
                return
        if self.selected_terrain == TerrainType.HAZARD:
            r = self._hazard_cfg_rects()
            if r["dice_prev"].collidepoint(pos):
                self.hazard_dice_i = (self.hazard_dice_i - 1) % len(HAZARD_DICE)
            elif r["dice_next"].collidepoint(pos):
                self.hazard_dice_i = (self.hazard_dice_i + 1) % len(HAZARD_DICE)
            elif r["type_prev"].collidepoint(pos):
                self.hazard_type_i = (self.hazard_type_i - 1) % len(HAZARD_TYPES)
            elif r["type_next"].collidepoint(pos):
                self.hazard_type_i = (self.hazard_type_i + 1) % len(HAZARD_TYPES)

    def _handle_grid_click(self, hex_coord: HexCoord) -> None:
        if self.tool_mode == ToolMode.TERRAIN:
            self._paint_terrain(hex_coord)
        else:
            self._erase_hex(hex_coord)

    # ------------------------------------------------------------------
    # Tool actions
    # ------------------------------------------------------------------

    def _paint_terrain(self, hex_coord: HexCoord) -> None:
        self.grid.set_terrain(hex_coord, self.selected_terrain)
        key = (hex_coord.q, hex_coord.r)
        if self.selected_terrain == TerrainType.HAZARD:
            # The hazard brush stamps its damage spec; repainting restamps.
            self._extra_data[key] = {"damage": self.hazard_spec}
            name = f"Hazard ({self.hazard_spec} on entry)"
        else:
            # Repainting a hex discards any authored extra_data it carried.
            self._extra_data.pop(key, None)
            name = TERRAIN_NAMES.get(self.selected_terrain, self.selected_terrain.value)
        self.status_message = f"Painted {name} at ({hex_coord.q}, {hex_coord.r})"
        self.status_timer = 90

    def _erase_hex(self, hex_coord: HexCoord) -> None:
        cell = self.grid.get_cell(hex_coord)
        if cell is None or cell.terrain == TerrainType.NORMAL:
            return
        self.grid.set_terrain(hex_coord, TerrainType.NORMAL)
        self._extra_data.pop((hex_coord.q, hex_coord.r), None)
        self.status_message = f"Cleared terrain at ({hex_coord.q}, {hex_coord.r})"
        self.status_timer = 90

    def _toggle_preview(self) -> None:
        from arena.audio.manager import get_sound_manager
        sm = get_sound_manager()
        if self._previewing:
            sm.stop_music()
            self._previewing = False
        else:
            sm.play_music(self._music_path)
            self._previewing = True

    # ------------------------------------------------------------------
    # Grid size
    # ------------------------------------------------------------------

    def _adjust_grid_size(self, dw: int, dh: int) -> None:
        """Resize the grid, PRESERVING painted terrain that still fits (the
        old editor threw the whole layout away here) and the camera."""
        new_w = max(MIN_GRID_SIZE, min(MAX_GRID_SIZE, self.grid_width + dw))
        new_h = max(MIN_GRID_SIZE, min(MAX_GRID_SIZE, self.grid_height + dh))
        if new_w == self.grid_width and new_h == self.grid_height:
            return

        kept = {
            (q, r): cell.terrain
            for (q, r), cell in self.grid.cells.items()
            if cell.terrain != TerrainType.NORMAL and q < new_w and r < new_h
        }
        cam = self.grid_view.camera
        old_cam = (cam.x, cam.y, cam.zoom)
        bg_transform = self.grid_view.get_background_transform()

        self.grid_width, self.grid_height = new_w, new_h
        self._create_grid()
        for (q, r), terrain in kept.items():
            self.grid.set_terrain(HexCoord(q, r), terrain)
        self._extra_data = {
            pos: extra for pos, extra in self._extra_data.items() if pos in kept
        }

        cam = self.grid_view.camera
        cam.x, cam.y, cam.zoom = old_cam
        if self._background_path:
            self.grid_view.set_background(Path(self._background_path))
            self.grid_view.set_background_transform(*bg_transform)

        self.status_message = f"Grid resized to {new_w}x{new_h}"
        self.status_timer = 120

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def build_battle(self) -> dict:
        """The updated battle block: geometry from the editor, asset
        FILENAMES exactly as they came in (choosing files is the Forge's
        job, so the editor cannot corrupt them)."""
        terrain = []
        for (q, r), cell in sorted(self.grid.cells.items()):
            if cell.terrain == TerrainType.NORMAL:
                continue
            entry: dict = {"position": [q, r], "terrain_type": cell.terrain.value}
            extra = self._extra_data.get((q, r))
            if extra:
                entry["extra_data"] = extra
            terrain.append(entry)

        offset, scale = self.grid_view.get_background_transform()
        out = dict(self._battle)
        out.update(
            grid_width=self.grid_width,
            grid_height=self.grid_height,
            terrain=terrain,
            background_offset=[offset[0], offset[1]],
            background_scale=scale,
        )
        return out

    def _save_and_close(self) -> None:
        try:
            self.out_path.write_text(
                json.dumps({"battle": self.build_battle()}, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            self.status_message = f"Save failed: {e}"
            self.status_timer = 180
            return
        self.app.quit()

    # ------------------------------------------------------------------
    # Update / render
    # ------------------------------------------------------------------

    def update(self) -> None:
        if self.status_timer > 0:
            self.status_timer -= 1
            if self.status_timer <= 0:
                self.status_message = ""

    def render(self, surface: pygame.Surface) -> None:
        self._render_grid_area(surface)
        self._render_top_bar(surface)
        self._render_left_panel(surface)
        self._render_status_bar(surface)

    def _render_top_bar(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(surface, parse_color(COLORS["bg_medium"]), self.top_bar_rect)
        draw_image_button(surface, self.back_btn, "Back",
                          is_hovered=self.back_hovered, is_quit=True, font_size=14)
        draw_text_centered(
            surface, self.place_name.upper(),
            (self.screen_width // 2, TOP_BAR_HEIGHT // 2),
            parse_color(COLORS["text_gold"]), font_size=22,
        )
        draw_image_button(surface, self.save_btn, "Save",
                          is_hovered=self.save_hovered, font_size=16)

    def _render_left_panel(self, surface: pygame.Surface) -> None:
        if not draw_tray_background(surface, self.left_panel_rect, variant="standard"):
            pygame.draw.rect(
                surface, parse_color(COLORS["bg_medium"]), self.left_panel_rect,
            )

        label_color = parse_color(COLORS["text_secondary"])
        font = get_font(14)

        # -- Grid size --
        gs_y = self.width_minus_btn.y
        surface.blit(font.render("Grid Size:", True, label_color), (20, gs_y - 22))
        self._draw_small_btn(surface, self.width_minus_btn, "-")
        draw_text_centered(
            surface, str(self.grid_width),
            (self.width_minus_btn.right + 28, gs_y + 12),
            parse_color(COLORS["text_primary"]), font_size=16,
        )
        self._draw_small_btn(surface, self.width_plus_btn, "+")
        surface.blit(font.render("W", True, label_color),
                     (self.width_plus_btn.right + 8, gs_y + 4))

        self._draw_small_btn(surface, self.height_minus_btn, "-")
        draw_text_centered(
            surface, str(self.grid_height),
            (self.height_minus_btn.right + 28, gs_y + 42),
            parse_color(COLORS["text_primary"]), font_size=16,
        )
        self._draw_small_btn(surface, self.height_plus_btn, "+")
        surface.blit(font.render("H", True, label_color),
                     (self.height_plus_btn.right + 8, gs_y + 34))

        # -- Music preview --
        if self._music_path:
            surface.blit(font.render("Music:", True, label_color),
                         (20, self.preview_btn.y + 4))
            label = "Stop" if self._previewing else "Preview"
            draw_image_button(surface, self.preview_btn, label,
                              is_hovered=self.preview_hovered, font_size=13)

        # -- Tool mode buttons --
        for mode, rect in self.tool_buttons.items():
            active = mode == self.tool_mode
            color = (parse_color(COLORS["button_active"]) if active
                     else parse_color(COLORS["button_normal"]))
            pygame.draw.rect(surface, color, rect, border_radius=4)
            pygame.draw.rect(surface, parse_color(COLORS["hex_border"]),
                             rect, 1, border_radius=4)
            draw_text_centered(
                surface, mode.name.title(), rect.center,
                parse_color(COLORS["text_primary"]), font_size=14,
            )

        # -- Context section --
        if self.tool_mode == ToolMode.TERRAIN:
            self._render_terrain_palette(surface)
        else:
            hint = font.render("Click hexes to clear terrain", True, label_color)
            surface.blit(hint, (20, self.context_start_y + 4))

    def _render_terrain_palette(self, surface: pygame.Surface) -> None:
        item_h, gap, x, w = 30, 4, 20, 260
        for i, terrain_type in enumerate(TerrainType):
            y = self.context_start_y + i * (item_h + gap)
            if y + item_h > self.left_panel_rect.bottom:
                break
            rect = pygame.Rect(x, y, w, item_h)
            selected = terrain_type == self.selected_terrain
            bg = (parse_color(COLORS["button_active"]) if selected
                  else parse_color(COLORS["button_normal"]))
            pygame.draw.rect(surface, bg, rect, border_radius=4)
            pygame.draw.rect(surface, parse_color(COLORS["hex_border"]),
                             rect, 1, border_radius=4)

            color_key = TERRAIN_COLORS.get(terrain_type.value, "hex_fill")
            swatch = pygame.Rect(x + 6, y + 5, 20, 20)
            pygame.draw.rect(surface, parse_color(COLORS[color_key]),
                             swatch, border_radius=2)

            name = TERRAIN_NAMES.get(terrain_type, terrain_type.value)
            draw_text_centered(
                surface, name,
                (x + 30 + (w - 36) // 2, y + item_h // 2),
                parse_color(COLORS["text_primary"]), font_size=14,
            )

        if self.selected_terrain == TerrainType.HAZARD:
            self._render_hazard_config(surface)

    def _render_hazard_config(self, surface: pygame.Surface) -> None:
        """The hazard brush's damage pickers (◄ value ►), under the palette."""
        r = self._hazard_cfg_rects()
        font = get_font(14)
        label = font.render("Hazard damage (on entry):", True,
                            parse_color(COLORS["text_gold"]))
        surface.blit(label, (20, r["dice_prev"].y - 22))
        rows = (
            (r["dice_prev"], r["dice_next"], HAZARD_DICE[self.hazard_dice_i]),
            (r["type_prev"], r["type_next"], HAZARD_TYPES[self.hazard_type_i]),
        )
        for prev, nxt, value in rows:
            self._draw_small_btn(surface, prev, "<")
            self._draw_small_btn(surface, nxt, ">")
            draw_text_centered(
                surface, value,
                ((prev.right + nxt.left) // 2, prev.centery),
                parse_color(COLORS["text_primary"]), font_size=15,
            )

    def _render_grid_area(self, surface: pygame.Surface) -> None:
        old_clip = surface.get_clip()
        surface.set_clip(self.grid_area_rect)
        self.grid_view.render(surface)
        surface.set_clip(old_clip)

    def _render_status_bar(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(
            surface, parse_color(COLORS["bg_medium"]), self.status_bar_rect,
        )
        font = get_font(14)
        if self._bg_edit_mode:
            text = "BG EDIT: Drag to move · Scroll to resize"
            text_color = parse_color(COLORS["text_gold"])
        else:
            text = self.status_message or self._get_default_status()
            text_color = parse_color(COLORS["text_secondary"])
        surface.blit(font.render(text, True, text_color),
                     (12, self.status_bar_rect.y + 12))

        hovered = self.grid_view.hovered_hex
        if hovered is not None:
            coord_surf = font.render(
                f"Hex: ({hovered.q}, {hovered.r})", True,
                parse_color(COLORS["text_secondary"]),
            )
            surface.blit(
                coord_surf,
                (self.screen_width - coord_surf.get_width() - 12,
                 self.status_bar_rect.y + 12),
            )

    def _get_default_status(self) -> str:
        if self.tool_mode == ToolMode.TERRAIN:
            name = TERRAIN_NAMES.get(self.selected_terrain, self.selected_terrain.value)
            if self.selected_terrain == TerrainType.HAZARD:
                name = f"Hazard ({self.hazard_spec} on entry)"
            base = f"Click hexes to paint {name}"
        else:
            base = "Click hexes to clear terrain"
        if self._background_path:
            base += " · Right-drag: move image · Right-drag+scroll: resize"
        return base + " · ESC cancels without saving"

    def _draw_small_btn(
        self, surface: pygame.Surface, rect: pygame.Rect, label: str,
    ) -> None:
        pygame.draw.rect(surface, parse_color(COLORS["button_normal"]),
                         rect, border_radius=3)
        pygame.draw.rect(surface, parse_color(COLORS["hex_border"]),
                         rect, 1, border_radius=3)
        draw_text_centered(
            surface, label, rect.center,
            parse_color(COLORS["text_primary"]), font_size=16,
        )
