"""Encounter setup screen for creating and editing encounters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.grid.footprint import get_occupied_hexes, is_valid_placement, get_footprint_center_pixel
from arena.models.character import CreatureSize
from arena.gui.grid_view import GridView
from arena.gui.renderer import draw_scrollbar, draw_text_centered, get_font
from arena.gui.button_images import draw_image_button
from arena.gui.tray_backgrounds import draw_tray_background
from arena.gui.widgets.dropdown import Dropdown
from arena.gui.screens.base import Screen
from arena.gui.lair_action_editor import LairActionEditor
from arena.models.encounter import (
    CombatantEntry,
    Encounter,
    TerrainHex,
    TerrainType,
)
from arena.util.constants import (
    COLORS,
    TERRAIN_COLORS,
    TERRAIN_NAMES,
    parse_color,
)
from arena.util.settings import get_settings
from arena.util.loader import load_encounter, load_json, save_encounter

if TYPE_CHECKING:
    from arena.gui.app import App


# Layout constants
TOP_BAR_HEIGHT = 40
LEFT_PANEL_WIDTH = 300
STATUS_BAR_HEIGHT = 40

# Grid size limits
MIN_GRID_SIZE = 5
MAX_GRID_SIZE = 40

# Team definitions
TEAMS = ["player", "ally", "enemy", "neutral"]
TEAM_COLORS_MAP = {
    "player": "team_player",
    "ally": "team_ally",
    "enemy": "team_enemy",
    "neutral": "team_neutral",
}


def _parse_size(raw: str) -> CreatureSize:
    """Convert a size string from JSON to CreatureSize enum."""
    try:
        return CreatureSize(raw.lower())
    except (ValueError, AttributeError):
        return CreatureSize.MEDIUM


class ToolMode(Enum):
    PLACE = auto()
    TERRAIN = auto()
    ERASE = auto()


@dataclass
class CreatureFileInfo:
    """Info about an available creature file."""

    file_path: str  # Relative, e.g. "characters/thorin.json"
    display_name: str
    category: str  # "Character" or "Monster"
    token_color: str
    detail: str  # "Level 5 Fighter" or "CR 0.25"
    size: CreatureSize = CreatureSize.MEDIUM


@dataclass
class PlacedCombatant:
    """A creature placed on the setup grid."""

    creature_id: str  # File path, e.g. "characters/thorin.json"
    display_name: str
    team: str
    position: HexCoord
    name_override: str | None = None
    token_color: str = "#808080"
    grid_uid: str = ""  # Unique ID for grid occupancy tracking
    size: CreatureSize = CreatureSize.MEDIUM


class EncounterSetupScreen(Screen):
    """Screen for creating and editing encounter configurations."""

    def __init__(
        self,
        screen_width: int,
        screen_height: int,
        encounter_path: Path | None = None,
    ) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.app: App | None = None

        # Encounter state
        self.encounter_name = "New Encounter"
        self.grid_width = 20
        self.grid_height = 15
        self.placed_combatants: list[PlacedCombatant] = []
        self._uid_counter = 0

        # Tool state
        self.tool_mode = ToolMode.PLACE
        self.selected_creature_index: int | None = None
        self.selected_team = "enemy"
        self.selected_terrain = TerrainType.DIFFICULT

        # UI state
        self.name_input_active = False
        self.status_message = ""
        self.status_timer = 0
        self._grid_owns_mouse = False
        self.creature_scroll_offset = 0

        # Hover states for buttons
        self.back_hovered = False
        self.save_hovered = False
        self.fight_hovered = False

        # Background edit state (right-click drag)
        self._bg_edit_mode = False
        self._bg_drag_start: tuple[int, int] | None = None
        self._bg_drag_start_offset: tuple[float, float] = (0.0, 0.0)

        # Discover available creatures
        self.available_creatures = self._scan_creature_files()

        # Music selection
        self._music_files = self._scan_music_files()
        self._music_options = ["None (Menu Music)"] + [
            f.replace("_", " ").replace(".mp3", "").title()
            for f in self._music_files
        ]
        self.selected_music_track: str | None = None

        # Background selection
        self._bg_files = self._scan_background_files()
        self._bg_options = ["None"] + [
            Path(f).stem.replace("_", " ").title()
            for f in self._bg_files
        ]
        self.selected_background: str | None = None

        # Lair action state
        self.has_lair: bool = False
        self.lair_actions: list = []  # list[Action]
        self._lair_editor: LairActionEditor | None = None

        # Build layout
        self._build_ui_rects()

        # Create grid and grid view
        self._create_grid()

        # Load existing encounter if provided
        if encounter_path is not None:
            self._load_existing_encounter(encounter_path)

    def on_enter(self, app: App) -> None:
        self.app = app

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    def _scan_creature_files(self) -> list[CreatureFileInfo]:
        """Scan data/ for character and monster JSON files."""
        creatures: list[CreatureFileInfo] = []
        data_dir = Path("data")

        # Characters
        char_dir = data_dir / "characters"
        if char_dir.exists():
            for path in sorted(char_dir.glob("*.json")):
                try:
                    data = load_json(path)
                    name = data.get("name", path.stem)
                    level = data.get("level", "?")
                    cls = data.get("character_class", "")
                    color = data.get("token_color", "#808080")
                    size = _parse_size(data.get("size", "medium"))
                    creatures.append(CreatureFileInfo(
                        file_path=f"characters/{path.name}",
                        display_name=name,
                        category="Character",
                        token_color=color,
                        detail=f"Level {level} {cls}",
                        size=size,
                    ))
                except Exception:
                    continue

        # Monsters
        mon_dir = data_dir / "monsters"
        if mon_dir.exists():
            for path in sorted(mon_dir.glob("*.json")):
                try:
                    data = load_json(path)
                    name = data.get("name", path.stem)
                    cr = data.get("challenge_rating", "?")
                    color = data.get("token_color", "#808080")
                    size = _parse_size(data.get("size", "medium"))
                    creatures.append(CreatureFileInfo(
                        file_path=f"monsters/{path.name}",
                        display_name=name,
                        category="Monster",
                        token_color=color,
                        detail=f"CR {cr}",
                        size=size,
                    ))
                except Exception:
                    continue

        return creatures

    def _scan_music_files(self) -> list[str]:
        """Scan assets/music/ for available .mp3 files (excluding menu music)."""
        music_dir = Path("assets") / "music"
        if not music_dir.exists():
            return []
        return sorted(
            f.name for f in music_dir.glob("*.mp3")
            if f.name != "menu_music.mp3"
        )

    def _scan_background_files(self) -> list[str]:
        """Scan assets/ui/encounter backgrounds/ for image files."""
        bg_dir = Path("assets") / "ui" / "encounter backgrounds"
        if not bg_dir.exists():
            return []
        extensions = ("*.png", "*.jpg", "*.jpeg")
        files: list[str] = []
        for ext in extensions:
            files.extend(f.name for f in bg_dir.glob(ext))
        return sorted(files)

    def _build_ui_rects(self) -> None:
        """Compute all layout rectangles."""
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
        self.save_btn = pygame.Rect(sw - 190, 6, 80, 28)
        self.fight_btn = pygame.Rect(sw - 100, 6, 90, 28)

        # Name input
        self.name_input_rect = pygame.Rect(20, TOP_BAR_HEIGHT + 30, 260, 28)

        # Grid size controls
        gs_y = TOP_BAR_HEIGHT + 75
        self.width_minus_btn = pygame.Rect(80, gs_y, 24, 24)
        self.width_plus_btn = pygame.Rect(160, gs_y, 24, 24)
        self.height_minus_btn = pygame.Rect(80, gs_y + 30, 24, 24)
        self.height_plus_btn = pygame.Rect(160, gs_y + 30, 24, 24)

        # Music selector dropdown
        music_y = TOP_BAR_HEIGHT + 132
        self.music_dropdown = Dropdown(
            pygame.Rect(80, music_y, 200, 24),
            options=self._music_options,
            selected_index=0,
            max_visible=5,
        )

        # Background selector dropdown
        bg_y = TOP_BAR_HEIGHT + 162
        self.bg_dropdown = Dropdown(
            pygame.Rect(80, bg_y, 200, 24),
            options=self._bg_options,
            selected_index=0,
            max_visible=5,
        )

        # Lair action controls
        lair_y = TOP_BAR_HEIGHT + 196
        self.lair_toggle_rect = pygame.Rect(75, lair_y, 18, 18)
        self.lair_edit_btn = pygame.Rect(140, lair_y - 2, 140, 22)

        # Tool mode buttons (shifted down for lair controls)
        tool_y = TOP_BAR_HEIGHT + 236
        tool_w = 84
        tool_h = 28
        tool_gap = 6
        tool_x = 20
        self.tool_buttons = {
            ToolMode.PLACE: pygame.Rect(tool_x, tool_y, tool_w, tool_h),
            ToolMode.TERRAIN: pygame.Rect(
                tool_x + tool_w + tool_gap, tool_y, tool_w, tool_h,
            ),
            ToolMode.ERASE: pygame.Rect(
                tool_x + 2 * (tool_w + tool_gap), tool_y, tool_w, tool_h,
            ),
        }

        # Team selector buttons (shown in PLACE mode)
        team_y = TOP_BAR_HEIGHT + 281
        team_size = 50
        team_gap = 8
        team_x = 20
        self.team_buttons: dict[str, pygame.Rect] = {}
        for i, team in enumerate(TEAMS):
            self.team_buttons[team] = pygame.Rect(
                team_x + i * (team_size + team_gap), team_y, team_size, team_size,
            )

        # Creature list / terrain palette start Y
        self.context_start_y = TOP_BAR_HEIGHT + 346

    def _create_grid(self) -> None:
        """Create the hex grid and grid view."""
        self.grid = HexGrid(self.grid_width, self.grid_height)
        self.grid_view = GridView(
            self.grid,
            self.grid_area_rect.width,
            self.grid_area_rect.height,
            origin=(self.grid_area_rect.x, self.grid_area_rect.y),
        )

    def _next_uid(self) -> str:
        """Generate a unique ID for grid occupancy."""
        self._uid_counter += 1
        return f"setup_{self._uid_counter}"

    def _load_existing_encounter(self, path: Path) -> None:
        """Populate setup state from an existing encounter file."""
        try:
            encounter = load_encounter(path)
        except Exception:
            self.status_message = "Failed to load encounter"
            self.status_timer = 150
            return

        self.encounter_name = encounter.name
        self.grid_width = encounter.grid_width
        self.grid_height = encounter.grid_height

        # Restore music selection
        self.selected_music_track = encounter.music_track
        if encounter.music_track and encounter.music_track in self._music_files:
            self.music_dropdown.selected_index = (
                self._music_files.index(encounter.music_track) + 1
            )
        else:
            self.music_dropdown.selected_index = 0

        # Restore background selection
        self.selected_background = encounter.background_image
        if encounter.background_image and encounter.background_image in self._bg_files:
            self.bg_dropdown.selected_index = (
                self._bg_files.index(encounter.background_image) + 1
            )
        else:
            self.bg_dropdown.selected_index = 0

        # Recreate grid with correct size
        self._create_grid()

        # Apply background preview and transform
        self._apply_background_preview()
        if encounter.background_image:
            self.grid_view.set_background_transform(
                encounter.background_offset, encounter.background_scale,
            )

        # Apply terrain
        for th in encounter.terrain:
            coord = HexCoord(th.position[0], th.position[1])
            if self.grid.is_valid(coord):
                self.grid.set_terrain(coord, th.terrain_type)

        # Place combatants
        for entry in encounter.combatants:
            info = next(
                (c for c in self.available_creatures
                 if c.file_path == entry.creature_id),
                None,
            )
            if info is None:
                continue

            for i in range(entry.count):
                display = entry.name_override or info.display_name
                if entry.count > 1 and not entry.name_override:
                    display = f"{info.display_name} {i + 1}"

                uid = self._next_uid()
                pos = None
                if entry.starting_position:
                    pos = HexCoord(
                        entry.starting_position[0],
                        entry.starting_position[1],
                    )
                    if is_valid_placement(pos, info.size, self.grid):
                        self.grid.place_creature(pos, uid, info.size)
                    else:
                        pos = None

                if pos is not None:
                    self.placed_combatants.append(PlacedCombatant(
                        creature_id=entry.creature_id,
                        display_name=display,
                        team=entry.team,
                        position=pos,
                        name_override=entry.name_override,
                        token_color=info.token_color,
                        grid_uid=uid,
                        size=info.size,
                    ))

        # Restore lair action data
        self.has_lair = encounter.has_lair
        self.lair_actions = list(encounter.lair_actions)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> None:
        # Lair action editor intercepts all input when open
        if self._lair_editor is not None:
            result = self._lair_editor.handle_event(event)
            if result == "__done__":
                self.lair_actions = self._lair_editor.get_actions()
                self._lair_editor = None
            return

        # Give open dropdown priority so it captures clicks/keys
        if self.music_dropdown.is_open:
            if self.music_dropdown.handle_event(event):
                self._sync_music_selection()
                return

        if self.bg_dropdown.is_open:
            if self.bg_dropdown.handle_event(event):
                self._sync_background_selection()
                return

        # ESC handling
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.name_input_active:
                self.name_input_active = False
            else:
                self.app.go_to_main_menu()
            return

        # Text input when name field is active
        if self.name_input_active and event.type == pygame.KEYDOWN:
            self._handle_name_input(event)
            return

        # Mouse motion — update hover states and background drag
        if event.type == pygame.MOUSEMOTION:
            pos = event.pos
            self.back_hovered = self.back_btn.collidepoint(pos)
            self.save_hovered = self.save_btn.collidepoint(pos)
            self.fight_hovered = self.fight_btn.collidepoint(pos)

            # Background drag (world-space)
            if self._bg_edit_mode and self._bg_drag_start is not None:
                dx_screen = pos[0] - self._bg_drag_start[0]
                dy_screen = pos[1] - self._bg_drag_start[1]
                dx_world = dx_screen / self.grid_view.camera.zoom
                dy_world = dy_screen / self.grid_view.camera.zoom
                new_offset = (
                    self._bg_drag_start_offset[0] + dx_world,
                    self._bg_drag_start_offset[1] + dy_world,
                )
                _, scale = self.grid_view.get_background_transform()
                self.grid_view.set_background_transform(new_offset, scale)

            # Forward to grid view for hex hover
            if self.grid_area_rect.collidepoint(pos):
                self.grid_view.handle_event(event)
            return

        # Mouse wheel — scale background, scroll creature list, or zoom grid
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if (self._bg_edit_mode
                    and self.grid_area_rect.collidepoint(pos)):
                # Background scaling while right-click held
                offset, scale = self.grid_view.get_background_transform()
                new_scale = scale + event.y * 0.1
                self.grid_view.set_background_transform(offset, new_scale)
            elif self.grid_area_rect.collidepoint(pos):
                self.grid_view.handle_event(event)
            elif self.left_panel_rect.collidepoint(pos):
                self.creature_scroll_offset = max(
                    0, self.creature_scroll_offset - event.y * 30,
                )
                # Clamp upper bound based on actual content height
                self._clamp_creature_scroll()
            return

        # Mouse button down — track grid ownership, name input, bg edit
        if event.type == pygame.MOUSEBUTTONDOWN:
            pos = event.pos
            if event.button == 1:
                if self.grid_area_rect.collidepoint(pos):
                    self._grid_owns_mouse = True
                    self.grid_view.handle_event(event)
                else:
                    self._grid_owns_mouse = False
                    # Toggle name input focus
                    self.name_input_active = self.name_input_rect.collidepoint(pos)
            elif event.button == 3 and self.selected_background:
                # Right-click: start background drag
                if self.grid_area_rect.collidepoint(pos):
                    self._bg_edit_mode = True
                    self._bg_drag_start = pos
                    offset, _ = self.grid_view.get_background_transform()
                    self._bg_drag_start_offset = offset
            return

        # Mouse button up — handle clicks
        if event.type == pygame.MOUSEBUTTONUP:
            pos = event.pos

            # Right-click release: end background drag
            if event.button == 3:
                self._bg_edit_mode = False
                self._bg_drag_start = None
                return

            if event.button != 1:
                return

            # Dropdowns (closed state — check before left panel dispatch)
            if self.music_dropdown.handle_event(event):
                self._sync_music_selection()
                return
            if self.bg_dropdown.handle_event(event):
                self._sync_background_selection()
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
                    clicked_hex = self.grid_view._screen_to_hex(pos[0], pos[1])
                    if clicked_hex is not None and self.grid.is_valid(clicked_hex):
                        self._handle_grid_click(clicked_hex)
            else:
                self._grid_owns_mouse = False
            return

        # Forward keyboard events to grid view (G for coords, HOME)
        if event.type == pygame.KEYDOWN:
            self.grid_view.handle_event(event)

    def _handle_name_input(self, event: pygame.event.Event) -> None:
        """Handle keyboard input for the encounter name field."""
        if event.key == pygame.K_RETURN:
            self.name_input_active = False
        elif event.key == pygame.K_BACKSPACE:
            self.encounter_name = self.encounter_name[:-1]
        else:
            ch = event.unicode
            if ch and ch.isprintable() and len(self.encounter_name) < 40:
                self.encounter_name += ch

    def _sync_music_selection(self) -> None:
        """Update selected_music_track from dropdown state."""
        idx = self.music_dropdown.selected_index
        if idx == 0:
            self.selected_music_track = None
        else:
            self.selected_music_track = self._music_files[idx - 1]

    def _sync_background_selection(self) -> None:
        """Update selected_background from dropdown state and apply preview."""
        idx = self.bg_dropdown.selected_index
        if idx == 0:
            self.selected_background = None
        else:
            self.selected_background = self._bg_files[idx - 1]
        self._apply_background_preview()

    def _apply_background_preview(self) -> None:
        """Set or clear the background image on the grid view."""
        if self.selected_background:
            bg_path = (
                Path("assets") / "ui" / "encounter backgrounds"
                / self.selected_background
            )
            self.grid_view.set_background(bg_path)
        else:
            self.grid_view.set_background(None)
            self.grid_view.set_background_transform((0.0, 0.0), 1.0)

    def _handle_top_bar_click(self, pos: tuple[int, int]) -> None:
        """Handle clicks on top bar buttons."""
        if self.back_btn.collidepoint(pos):
            self.app.go_to_main_menu()
        elif self.save_btn.collidepoint(pos):
            self._save_encounter()
        elif self.fight_btn.collidepoint(pos):
            self._launch_combat()

    def _handle_left_panel_click(self, pos: tuple[int, int]) -> None:
        """Handle clicks on left panel controls."""
        # Lair toggle checkbox
        if self.lair_toggle_rect.collidepoint(pos):
            self.has_lair = not self.has_lair
            return

        # Lair edit button
        if self.has_lair and self.lair_edit_btn.collidepoint(pos):
            self._lair_editor = LairActionEditor(
                self.lair_actions,
                self.screen_width,
                self.screen_height,
            )
            return

        # Tool mode buttons
        for mode, rect in self.tool_buttons.items():
            if rect.collidepoint(pos):
                self.tool_mode = mode
                return

        # Grid size controls
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

        # Context-dependent clicks
        if self.tool_mode == ToolMode.PLACE:
            # Team selector
            for team, rect in self.team_buttons.items():
                if rect.collidepoint(pos):
                    self.selected_team = team
                    return
            # Creature list
            self._handle_creature_list_click(pos)

        elif self.tool_mode == ToolMode.TERRAIN:
            self._handle_terrain_palette_click(pos)

        elif self.tool_mode == ToolMode.ERASE:
            self._handle_placed_list_click(pos)

    def _handle_creature_list_click(self, pos: tuple[int, int]) -> None:
        """Handle a click in the creature list area."""
        item_h = 44
        gap = 4
        x = 20
        w = 260

        for i in range(len(self.available_creatures)):
            y = self.context_start_y + i * (item_h + gap) - self.creature_scroll_offset
            rect = pygame.Rect(x, y, w, item_h)
            if rect.collidepoint(pos):
                self.selected_creature_index = i
                return

    def _handle_terrain_palette_click(self, pos: tuple[int, int]) -> None:
        """Handle a click in the terrain palette."""
        item_h = 30
        gap = 4
        x = 20
        w = 260

        for i, terrain_type in enumerate(TerrainType):
            y = self.context_start_y + i * (item_h + gap)
            rect = pygame.Rect(x, y, w, item_h)
            if rect.collidepoint(pos):
                self.selected_terrain = terrain_type
                return

    def _handle_placed_list_click(self, pos: tuple[int, int]) -> None:
        """Handle a click in the placed creatures list (erase mode)."""
        item_h = 30
        gap = 4
        x = 20
        w = 260

        for i, pc in enumerate(self.placed_combatants):
            y = self.context_start_y + i * (item_h + gap)
            rect = pygame.Rect(x, y, w, item_h)
            if rect.collidepoint(pos):
                self.grid.remove_creature(pc.position, pc.size)
                self.placed_combatants.pop(i)
                self.status_message = f"Removed {pc.display_name}"
                self.status_timer = 120
                return

    def _handle_grid_click(self, hex_coord: HexCoord) -> None:
        """Handle a click on the hex grid, dispatched by tool mode."""
        if self.tool_mode == ToolMode.PLACE:
            self._place_creature(hex_coord)
        elif self.tool_mode == ToolMode.TERRAIN:
            self._paint_terrain(hex_coord)
        elif self.tool_mode == ToolMode.ERASE:
            self._erase_hex(hex_coord)

    # ------------------------------------------------------------------
    # Tool actions
    # ------------------------------------------------------------------

    def _place_creature(self, hex_coord: HexCoord) -> None:
        """Place the selected creature at the given hex."""
        if self.selected_creature_index is None:
            self.status_message = "Select a creature first"
            self.status_timer = 120
            return

        info = self.available_creatures[self.selected_creature_index]

        # Footprint-aware placement check
        if not is_valid_placement(hex_coord, info.size, self.grid):
            self.status_message = "Not enough space to place creature here"
            self.status_timer = 120
            return

        # Auto-number duplicates
        count = sum(
            1 for pc in self.placed_combatants
            if pc.creature_id == info.file_path
        )
        display = info.display_name
        override = None
        if count > 0:
            override = f"{info.display_name} {count + 1}"
            display = override

        uid = self._next_uid()
        self.grid.place_creature(hex_coord, uid, info.size)

        self.placed_combatants.append(PlacedCombatant(
            creature_id=info.file_path,
            display_name=display,
            team=self.selected_team,
            position=hex_coord,
            name_override=override,
            token_color=info.token_color,
            grid_uid=uid,
            size=info.size,
        ))

        self.status_message = f"Placed {display} ({self.selected_team})"
        self.status_timer = 120

    def _paint_terrain(self, hex_coord: HexCoord) -> None:
        """Paint terrain on the given hex."""
        self.grid.set_terrain(hex_coord, self.selected_terrain)
        name = TERRAIN_NAMES.get(self.selected_terrain, str(self.selected_terrain))
        self.status_message = f"Painted {name} at ({hex_coord.q}, {hex_coord.r})"
        self.status_timer = 90

    def _erase_hex(self, hex_coord: HexCoord) -> None:
        """Remove creature or reset terrain at the given hex."""
        cell = self.grid.get_cell(hex_coord)
        if cell is None:
            return

        if cell.occupant_id:
            for i, pc in enumerate(self.placed_combatants):
                if pc.grid_uid == cell.occupant_id:
                    self.grid.remove_creature(pc.position, pc.size)
                    self.placed_combatants.pop(i)
                    self.status_message = f"Removed {pc.display_name}"
                    self.status_timer = 120
                    return
            # Fallback: remove from grid even if not in our list
            self.grid.remove_creature(hex_coord)
        elif cell.terrain != TerrainType.NORMAL:
            self.grid.set_terrain(hex_coord, TerrainType.NORMAL)
            self.status_message = (
                f"Cleared terrain at ({hex_coord.q}, {hex_coord.r})"
            )
            self.status_timer = 90

    # ------------------------------------------------------------------
    # Scroll clamping
    # ------------------------------------------------------------------

    def _clamp_creature_scroll(self) -> None:
        """Ensure the creature list scroll offset stays in valid bounds."""
        if self.tool_mode == ToolMode.PLACE:
            item_h = 44
            gap = 4
            total_items = len(self.available_creatures)
        elif self.tool_mode == ToolMode.ERASE:
            item_h = 30
            gap = 4
            total_items = len(self.placed_combatants)
        else:
            self.creature_scroll_offset = 0
            return

        total_content = total_items * (item_h + gap)
        visible = self.left_panel_rect.bottom - 10 - self.context_start_y
        max_scroll = max(0, total_content - visible)
        self.creature_scroll_offset = min(self.creature_scroll_offset, max_scroll)

    # ------------------------------------------------------------------
    # Grid size
    # ------------------------------------------------------------------

    def _adjust_grid_size(self, dw: int, dh: int) -> None:
        """Adjust grid dimensions and recreate the grid.

        Preserves the current camera position and zoom level so the
        view does not jump when the user tweaks the grid size.
        """
        new_w = max(MIN_GRID_SIZE, min(MAX_GRID_SIZE, self.grid_width + dw))
        new_h = max(MIN_GRID_SIZE, min(MAX_GRID_SIZE, self.grid_height + dh))

        if new_w == self.grid_width and new_h == self.grid_height:
            return

        # Preserve camera state across grid recreation
        old_cam_x = self.grid_view.camera.x
        old_cam_y = self.grid_view.camera.y
        old_cam_zoom = self.grid_view.camera.zoom

        self.grid_width = new_w
        self.grid_height = new_h
        self.placed_combatants.clear()
        self._create_grid()

        # Restore camera
        self.grid_view.camera.x = old_cam_x
        self.grid_view.camera.y = old_cam_y
        self.grid_view.camera.zoom = old_cam_zoom

        # Restore background preview
        self._apply_background_preview()

        self.status_message = (
            f"Grid resized to {new_w}x{new_h} (placements cleared)"
        )
        self.status_timer = 150

    # ------------------------------------------------------------------
    # Save / Fight
    # ------------------------------------------------------------------

    def _build_encounter(self) -> Encounter:
        """Convert current state into an Encounter model."""
        terrain_list = []
        for (q, r), cell in self.grid.cells.items():
            if cell.terrain != TerrainType.NORMAL:
                terrain_list.append(TerrainHex(
                    position=(q, r),
                    terrain_type=cell.terrain,
                ))

        combatant_entries = []
        for pc in self.placed_combatants:
            combatant_entries.append(CombatantEntry(
                creature_id=pc.creature_id,
                team=pc.team,
                starting_position=(pc.position.q, pc.position.r),
                name_override=pc.name_override,
            ))

        # Get background transform (if a background is set)
        bg_offset = (0.0, 0.0)
        bg_scale = 1.0
        if self.selected_background:
            bg_offset, bg_scale = self.grid_view.get_background_transform()

        return Encounter(
            name=self.encounter_name,
            grid_width=self.grid_width,
            grid_height=self.grid_height,
            terrain=terrain_list,
            combatants=combatant_entries,
            has_lair=self.has_lair,
            lair_actions=self.lair_actions,
            music_track=self.selected_music_track,
            background_image=self.selected_background,
            background_offset=bg_offset,
            background_scale=bg_scale,
        )

    def _slugify(self, name: str) -> str:
        """Convert a name to a filename-safe slug."""
        slug = name.lower().strip()
        slug = re.sub(r"[^a-z0-9\s_-]", "", slug)
        slug = re.sub(r"[\s-]+", "_", slug)
        return slug or "encounter"

    def _save_encounter(self) -> Path | None:
        """Save the encounter to a JSON file."""
        if not self.placed_combatants:
            self.status_message = "Add at least one creature before saving"
            self.status_timer = 150
            return None

        encounter = self._build_encounter()
        slug = self._slugify(self.encounter_name)
        path = Path("data") / "encounters" / f"{slug}.json"
        try:
            save_encounter(encounter, path)
            self.status_message = f"Saved to {path}"
            self.status_timer = 180
            return path
        except Exception as e:
            self.status_message = f"Save failed: {e}"
            self.status_timer = 180
            return None

    def _launch_combat(self) -> None:
        """Save the encounter and launch combat."""
        if not self.placed_combatants:
            self.status_message = "Add at least one creature before fighting"
            self.status_timer = 150
            return

        path = self._save_encounter()
        if path is not None:
            self.app.go_to_combat(path)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self) -> None:
        if self.status_timer > 0:
            self.status_timer -= 1
            if self.status_timer <= 0:
                self.status_message = ""

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        self._render_top_bar(surface)
        self._render_left_panel(surface)
        self._render_grid_area(surface)
        self._render_status_bar(surface)
        # Dropdown overlays must be last for correct z-order
        self.music_dropdown.render_dropdown(surface)
        self.bg_dropdown.render_dropdown(surface)

        # Lair action editor overlay (must be on top)
        if self._lair_editor is not None:
            self._lair_editor.render(surface)

    def _render_top_bar(self, surface: pygame.Surface) -> None:
        """Render the top bar with Back, title, Save, Fight! buttons."""
        pygame.draw.rect(
            surface, parse_color(COLORS["bg_medium"]), self.top_bar_rect,
        )

        # Back button (quit/back style)
        draw_image_button(
            surface, self.back_btn, "Back",
            is_hovered=self.back_hovered, is_quit=True, font_size=14,
        )

        # Title
        draw_text_centered(
            surface, "ENCOUNTER SETUP",
            (self.screen_width // 2, TOP_BAR_HEIGHT // 2),
            parse_color(COLORS["text_gold"]), font_size=22,
        )

        # Save button (standard style)
        draw_image_button(
            surface, self.save_btn, "Save",
            is_hovered=self.save_hovered, font_size=14,
        )

        # Fight! button (standard style)
        draw_image_button(
            surface, self.fight_btn, "Fight!",
            is_hovered=self.fight_hovered, font_size=16,
        )

    def _render_left_panel(self, surface: pygame.Surface) -> None:
        """Render the left sidebar with controls."""
        if not draw_tray_background(surface, self.left_panel_rect, variant="standard"):
            pygame.draw.rect(
                surface, parse_color(COLORS["bg_medium"]), self.left_panel_rect,
            )

        label_color = parse_color(COLORS["text_secondary"])
        font = get_font(14)

        # -- Name input --
        lbl = font.render("Name:", True, label_color)
        surface.blit(lbl, (20, TOP_BAR_HEIGHT + 14))

        border_color = (
            parse_color(COLORS["button_active"]) if self.name_input_active
            else parse_color(COLORS["hex_border"])
        )
        pygame.draw.rect(
            surface, parse_color(COLORS["bg_dark"]),
            self.name_input_rect, border_radius=3,
        )
        pygame.draw.rect(
            surface, border_color, self.name_input_rect, 1, border_radius=3,
        )
        name_font = get_font(16)
        name_surf = name_font.render(
            self.encounter_name, True,
            parse_color(COLORS["text_primary"]),
        )
        clip_rect = pygame.Rect(0, 0, self.name_input_rect.width - 8, 24)
        surface.blit(
            name_surf,
            (self.name_input_rect.x + 4, self.name_input_rect.y + 4),
            clip_rect,
        )
        if self.name_input_active and (pygame.time.get_ticks() // 500) % 2 == 0:
            cursor_x = min(
                self.name_input_rect.x + 4 + name_surf.get_width(),
                self.name_input_rect.right - 4,
            )
            pygame.draw.line(
                surface, parse_color(COLORS["text_primary"]),
                (cursor_x, self.name_input_rect.y + 4),
                (cursor_x, self.name_input_rect.bottom - 4),
            )

        # -- Grid size --
        gs_label_y = TOP_BAR_HEIGHT + 68
        lbl2 = font.render("Grid Size:", True, label_color)
        surface.blit(lbl2, (20, gs_label_y))

        gs_y = TOP_BAR_HEIGHT + 75
        # Width row
        self._draw_small_btn(surface, self.width_minus_btn, "-")
        draw_text_centered(
            surface, str(self.grid_width),
            (self.width_minus_btn.right + 28, gs_y + 12),
            parse_color(COLORS["text_primary"]), font_size=16,
        )
        self._draw_small_btn(surface, self.width_plus_btn, "+")
        w_label = font.render("W", True, label_color)
        surface.blit(w_label, (self.width_plus_btn.right + 8, gs_y + 4))

        # Height row
        self._draw_small_btn(surface, self.height_minus_btn, "-")
        draw_text_centered(
            surface, str(self.grid_height),
            (self.height_minus_btn.right + 28, gs_y + 42),
            parse_color(COLORS["text_primary"]), font_size=16,
        )
        self._draw_small_btn(surface, self.height_plus_btn, "+")
        h_label = font.render("H", True, label_color)
        surface.blit(h_label, (self.height_plus_btn.right + 8, gs_y + 34))

        # -- Music selector --
        music_lbl = font.render("Music:", True, label_color)
        surface.blit(music_lbl, (20, TOP_BAR_HEIGHT + 134))
        self.music_dropdown.render(surface)

        # -- Background selector --
        bg_lbl = font.render("Background:", True, label_color)
        surface.blit(bg_lbl, (20, TOP_BAR_HEIGHT + 164))
        self.bg_dropdown.render(surface)

        # -- Lair toggle --
        lair_lbl = font.render("Lair:", True, label_color)
        surface.blit(lair_lbl, (20, self.lair_toggle_rect.y + 1))

        cb_color = (
            parse_color(COLORS["button_active"]) if self.has_lair
            else parse_color(COLORS["hex_border"])
        )
        pygame.draw.rect(surface, cb_color, self.lair_toggle_rect, border_radius=2)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            self.lair_toggle_rect, 1, border_radius=2,
        )
        if self.has_lair:
            # Checkmark
            white = parse_color(COLORS["text_primary"])
            pts = [
                (self.lair_toggle_rect.x + 3, self.lair_toggle_rect.centery),
                (self.lair_toggle_rect.centerx - 1, self.lair_toggle_rect.bottom - 4),
                (self.lair_toggle_rect.right - 3, self.lair_toggle_rect.y + 3),
            ]
            pygame.draw.lines(surface, white, False, pts, 2)

        if self.has_lair:
            btn_label = f"Edit ({len(self.lair_actions)})"
            draw_image_button(
                surface, self.lair_edit_btn, btn_label, font_size=12,
            )

        # -- Separator --
        sep_y = TOP_BAR_HEIGHT + 226
        pygame.draw.line(
            surface, parse_color(COLORS["hex_border"]),
            (10, sep_y), (LEFT_PANEL_WIDTH - 10, sep_y),
        )

        # -- Tool mode buttons --
        for mode, rect in self.tool_buttons.items():
            active = mode == self.tool_mode
            color = (
                parse_color(COLORS["button_active"]) if active
                else parse_color(COLORS["button_normal"])
            )
            pygame.draw.rect(surface, color, rect, border_radius=4)
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                rect, 1, border_radius=4,
            )
            draw_text_centered(
                surface, mode.name.title(), rect.center,
                parse_color(COLORS["text_primary"]), font_size=14,
            )

        # -- Separator --
        sep_y2 = TOP_BAR_HEIGHT + 243
        pygame.draw.line(
            surface, parse_color(COLORS["hex_border"]),
            (10, sep_y2), (LEFT_PANEL_WIDTH - 10, sep_y2),
        )

        # -- Context section --
        if self.tool_mode == ToolMode.PLACE:
            self._render_place_context(surface)
        elif self.tool_mode == ToolMode.TERRAIN:
            self._render_terrain_palette(surface)
        elif self.tool_mode == ToolMode.ERASE:
            self._render_placed_list(surface)

    def _render_place_context(self, surface: pygame.Surface) -> None:
        """Render team selector and creature list for PLACE mode."""
        # Team selector buttons
        for team, rect in self.team_buttons.items():
            team_c = parse_color(COLORS[TEAM_COLORS_MAP[team]])
            selected = team == self.selected_team
            if selected:
                pygame.draw.rect(surface, team_c, rect, border_radius=4)
            else:
                dim = tuple(c // 3 for c in team_c)
                pygame.draw.rect(surface, dim, rect, border_radius=4)
            bw = 2 if selected else 1
            pygame.draw.rect(surface, team_c, rect, bw, border_radius=4)
            draw_text_centered(
                surface, team.title()[:3],
                rect.center,
                parse_color(COLORS["text_primary"]), font_size=12,
            )

        # Creature list
        item_h = 44
        gap = 4
        x = 20
        w = 260
        clip_bottom = self.left_panel_rect.bottom - 10

        for i, info in enumerate(self.available_creatures):
            y = (
                self.context_start_y
                + i * (item_h + gap)
                - self.creature_scroll_offset
            )
            if y + item_h < self.context_start_y:
                continue
            if y > clip_bottom:
                break

            rect = pygame.Rect(x, y, w, item_h)
            selected = i == self.selected_creature_index
            color = (
                parse_color(COLORS["button_active"]) if selected
                else parse_color(COLORS["button_normal"])
            )
            pygame.draw.rect(surface, color, rect, border_radius=4)
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                rect, 1, border_radius=4,
            )

            # Color dot
            dot_color = parse_color(info.token_color)
            pygame.draw.circle(surface, dot_color, (x + 16, y + item_h // 2), 8)

            # Name and detail
            name_font = get_font(15)
            detail_font = get_font(12)
            name_surf = name_font.render(
                info.display_name, True,
                parse_color(COLORS["text_primary"]),
            )
            detail_surf = detail_font.render(
                f"{info.category} - {info.detail}", True,
                parse_color(COLORS["text_secondary"]),
            )
            surface.blit(name_surf, (x + 30, y + 4))
            surface.blit(detail_surf, (x + 30, y + 24))

        # Scrollbar for creature list
        total_content = len(self.available_creatures) * (item_h + gap)
        visible_h = clip_bottom - self.context_start_y
        if total_content > visible_h:
            scroll_area = pygame.Rect(
                x, self.context_start_y, w, visible_h,
            )
            draw_scrollbar(
                surface, scroll_area, total_content,
                self.creature_scroll_offset,
            )

    def _render_terrain_palette(self, surface: pygame.Surface) -> None:
        """Render terrain type buttons for TERRAIN mode."""
        item_h = 30
        gap = 4
        x = 20
        w = 260

        for i, terrain_type in enumerate(TerrainType):
            y = self.context_start_y + i * (item_h + gap)
            if y + item_h > self.left_panel_rect.bottom:
                break

            rect = pygame.Rect(x, y, w, item_h)
            selected = terrain_type == self.selected_terrain
            bg = (
                parse_color(COLORS["button_active"]) if selected
                else parse_color(COLORS["button_normal"])
            )
            pygame.draw.rect(surface, bg, rect, border_radius=4)
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                rect, 1, border_radius=4,
            )

            # Color swatch
            color_key = TERRAIN_COLORS.get(terrain_type.value, "hex_fill")
            swatch_color = parse_color(COLORS[color_key])
            swatch_rect = pygame.Rect(x + 6, y + 5, 20, 20)
            pygame.draw.rect(surface, swatch_color, swatch_rect, border_radius=2)

            # Label
            name = TERRAIN_NAMES.get(terrain_type, terrain_type.value)
            draw_text_centered(
                surface, name,
                (x + 30 + (w - 36) // 2, y + item_h // 2),
                parse_color(COLORS["text_primary"]), font_size=14,
            )

    def _render_placed_list(self, surface: pygame.Surface) -> None:
        """Render list of placed creatures for ERASE mode."""
        label_font = get_font(14)
        header = label_font.render(
            "Placed Creatures (click to remove):", True,
            parse_color(COLORS["text_secondary"]),
        )
        surface.blit(header, (20, self.context_start_y - 18))

        item_h = 30
        gap = 4
        x = 20
        w = 260

        if not self.placed_combatants:
            empty_font = get_font(13)
            empty = empty_font.render(
                "No creatures placed", True,
                parse_color(COLORS["text_secondary"]),
            )
            surface.blit(empty, (x, self.context_start_y + 4))
            return

        for i, pc in enumerate(self.placed_combatants):
            y = self.context_start_y + i * (item_h + gap)
            if y + item_h > self.left_panel_rect.bottom:
                break

            rect = pygame.Rect(x, y, w, item_h)
            pygame.draw.rect(
                surface, parse_color(COLORS["button_normal"]),
                rect, border_radius=4,
            )
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                rect, 1, border_radius=4,
            )

            # Team dot
            team_c = parse_color(COLORS[TEAM_COLORS_MAP[pc.team]])
            pygame.draw.circle(surface, team_c, (x + 14, y + item_h // 2), 6)

            # Name
            item_font = get_font(14)
            n = item_font.render(
                pc.display_name, True,
                parse_color(COLORS["text_primary"]),
            )
            surface.blit(n, (x + 26, y + 6))

            # Position
            pos_font = get_font(11)
            pos_text = pos_font.render(
                f"({pc.position.q},{pc.position.r})", True,
                parse_color(COLORS["text_secondary"]),
            )
            surface.blit(pos_text, (x + w - 60, y + 8))

    def _render_grid_area(self, surface: pygame.Surface) -> None:
        """Render the grid view and tokens on top, clipped to the grid area."""
        old_clip = surface.get_clip()
        surface.set_clip(self.grid_area_rect)
        self.grid_view.render(surface)
        self._render_grid_tokens(surface)
        surface.set_clip(old_clip)

    def _render_grid_tokens(self, surface: pygame.Surface) -> None:
        """Draw simplified tokens for placed creatures."""
        cam = self.grid_view.camera
        ox, oy = self.grid_view.origin

        for pc in self.placed_combatants:
            s = get_settings()
            # Use footprint centroid for multi-hex creatures
            wx, wy = get_footprint_center_pixel(
                pc.position, pc.size, s.display.default_hex_size,
            )
            sx, sy = cam.world_to_screen(wx, wy)
            center = (int(sx) + ox, int(sy) + oy)
            radius = max(3, int(s.display.token_radius * cam.zoom))

            # Skip if offscreen
            if (center[0] < self.grid_area_rect.left - radius
                    or center[0] > self.grid_area_rect.right + radius
                    or center[1] < self.grid_area_rect.top - radius
                    or center[1] > self.grid_area_rect.bottom + radius):
                continue

            self._render_setup_token(
                surface, center, radius,
                pc.display_name, pc.team, pc.token_color,
            )

    def _render_setup_token(
        self,
        surface: pygame.Surface,
        center: tuple[int, int],
        radius: int,
        display_name: str,
        team: str,
        token_color: str,
    ) -> None:
        """Draw a simplified creature token."""
        body_color = parse_color(token_color)
        team_key = TEAM_COLORS_MAP.get(team, "team_neutral")
        team_color = parse_color(COLORS[team_key])

        # Body circle
        pygame.draw.circle(surface, body_color, center, radius)

        # Initials
        if radius >= 8:
            parts = display_name.split()
            if len(parts) >= 2:
                initials = (parts[0][0] + parts[-1][0]).upper()
            else:
                initials = display_name[0].upper() if display_name else "?"
            font_size = max(10, int(14 * self.grid_view.camera.zoom))
            txt_font = get_font(font_size)
            text_surf = txt_font.render(
                initials, True, parse_color(COLORS["text_primary"]),
            )
            text_rect = text_surf.get_rect(center=center)
            surface.blit(text_surf, text_rect)

        # Team ring
        pygame.draw.circle(surface, team_color, center, radius, 2)

    def _render_status_bar(self, surface: pygame.Surface) -> None:
        """Render the bottom status bar."""
        pygame.draw.rect(
            surface, parse_color(COLORS["bg_medium"]), self.status_bar_rect,
        )

        # Status message or context hint
        font = get_font(14)
        if self._bg_edit_mode:
            text = "BG EDIT: Drag to move \u00b7 Scroll to resize"
            text_color = parse_color(COLORS["text_gold"])
        else:
            text = self.status_message or self._get_default_status()
            text_color = parse_color(COLORS["text_secondary"])

        txt = font.render(text, True, text_color)
        surface.blit(txt, (12, self.status_bar_rect.y + 12))

        # Hovered hex coordinate
        hovered = self.grid_view.hovered_hex
        if hovered is not None:
            coord_text = f"Hex: ({hovered.q}, {hovered.r})"
            coord_surf = font.render(
                coord_text, True, parse_color(COLORS["text_secondary"]),
            )
            surface.blit(
                coord_surf,
                (self.screen_width - coord_surf.get_width() - 12,
                 self.status_bar_rect.y + 12),
            )

    def _get_default_status(self) -> str:
        """Get context-appropriate status text."""
        if self.tool_mode == ToolMode.PLACE:
            if self.selected_creature_index is not None:
                info = self.available_creatures[self.selected_creature_index]
                return (
                    f"Click hex to place {info.display_name} "
                    f"({self.selected_team})"
                )
            return "Select a creature from the list, then click a hex"
        elif self.tool_mode == ToolMode.TERRAIN:
            name = TERRAIN_NAMES.get(
                self.selected_terrain, str(self.selected_terrain),
            )
            return f"Click hexes to paint {name} terrain"
        elif self.tool_mode == ToolMode.ERASE:
            return "Click hex to erase creature or terrain"
        return ""

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_button(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        label: str,
        hovered: bool,
    ) -> None:
        """Draw a standard button."""
        color = (
            parse_color(COLORS["button_hover"]) if hovered
            else parse_color(COLORS["button_normal"])
        )
        pygame.draw.rect(surface, color, rect, border_radius=4)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            rect, 1, border_radius=4,
        )
        draw_text_centered(
            surface, label, rect.center,
            parse_color(COLORS["text_primary"]), font_size=14,
        )

    def _draw_small_btn(
        self, surface: pygame.Surface, rect: pygame.Rect, label: str,
    ) -> None:
        """Draw a small +/- button."""
        pygame.draw.rect(
            surface, parse_color(COLORS["button_normal"]),
            rect, border_radius=3,
        )
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            rect, 1, border_radius=3,
        )
        draw_text_centered(
            surface, label, rect.center,
            parse_color(COLORS["text_primary"]), font_size=16,
        )
