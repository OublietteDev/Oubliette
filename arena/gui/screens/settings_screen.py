"""Settings screen for configuring application preferences."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from arena.gui.screens.base import Screen
from arena.gui.renderer import draw_text_centered, get_font
from arena.gui.button_images import draw_image_button
from arena.gui.widgets.number_spinner import NumberSpinner
from arena.gui.widgets.checkbox import Checkbox
from arena.gui.widgets.dropdown import Dropdown
from arena.util.constants import COLORS, parse_color
from arena.util.settings import get_settings, save_settings, reset_settings
from arena.gui.custom_cursor import CustomCursorManager

if TYPE_CHECKING:
    from arena.gui.app import App


# Layout constants
TOP_BAR_HEIGHT = 50
STATUS_BAR_HEIGHT = 36
SECTION_HEADER_HEIGHT = 32
ROW_HEIGHT = 36
ROW_GAP = 6
LABEL_WIDTH = 220
WIDGET_WIDTH = 150
COLUMN_GAP = 60

# Resolution options
RESOLUTION_OPTIONS = [
    "1280x720",
    "1440x900",
    "1600x900",
    "1920x1080",
]


class SettingsScreen(Screen):
    """Settings screen with categorised options.

    Two-column layout with Gameplay/Audio on the left and
    Display/System on the right.  Changes take effect immediately;
    the Save button persists them to disk.
    """

    def __init__(self, screen_width: int, screen_height: int) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.app: App | None = None

        # Status message (timed feedback)
        self.status_message = ""
        self.status_timer = 0

        # Top-bar button hover states
        self.save_hovered = False
        self.reset_hovered = False
        self.back_hovered = False

        # Top-bar button rects (built in _build_layout)
        self.save_btn = pygame.Rect(0, 0, 0, 0)
        self.reset_btn = pygame.Rect(0, 0, 0, 0)
        self.back_btn = pygame.Rect(0, 0, 0, 0)

        # Build widgets and layout
        self._build_layout()
        self._sync_widgets_from_settings()

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        """Create all widget instances and compute positions."""
        # Top bar buttons (right-aligned)
        btn_h = 32
        btn_y = (TOP_BAR_HEIGHT - btn_h) // 2
        self.back_btn = pygame.Rect(self.screen_width - 90, btn_y, 80, btn_h)
        self.reset_btn = pygame.Rect(self.screen_width - 220, btn_y, 120, btn_h)
        self.save_btn = pygame.Rect(self.screen_width - 310, btn_y, 80, btn_h)

        # Content area
        content_top = TOP_BAR_HEIGHT + 10
        left_x = 40
        right_x = self.screen_width // 2 + COLUMN_GAP // 2

        # ---- LEFT COLUMN: Gameplay + Audio ----
        y = content_top
        self._gameplay_header_y = y
        y += SECTION_HEADER_HEIGHT

        self._ai_step_label_y = y
        self.ai_step_spinner = NumberSpinner(
            pygame.Rect(left_x + LABEL_WIDTH, y, WIDGET_WIDTH, 28),
            value=500, min_val=100, max_val=2000, step=50,
        )
        y += ROW_HEIGHT + ROW_GAP

        self._ai_think_label_y = y
        self.ai_think_spinner = NumberSpinner(
            pygame.Rect(left_x + LABEL_WIDTH, y, WIDGET_WIDTH, 28),
            value=300, min_val=100, max_val=2000, step=50,
        )
        y += ROW_HEIGHT + ROW_GAP

        self._ai_random_label_y = y
        self.ai_random_spinner = NumberSpinner(
            pygame.Rect(left_x + LABEL_WIDTH, y, WIDGET_WIDTH, 28),
            value=10, min_val=0, max_val=100, step=5,
        )
        y += ROW_HEIGHT + ROW_GAP

        self._ai_thinking_label_y = y
        self.show_ai_thinking_cb = Checkbox(
            pygame.Rect(left_x + LABEL_WIDTH, y, WIDGET_WIDTH + 60, 28),
            label="",
            checked=True,
        )
        y += ROW_HEIGHT + ROW_GAP + 12

        # Audio section
        self._audio_header_y = y
        y += SECTION_HEADER_HEIGHT

        self._master_vol_label_y = y
        self.master_vol_spinner = NumberSpinner(
            pygame.Rect(left_x + LABEL_WIDTH, y, WIDGET_WIDTH, 28),
            value=80, min_val=0, max_val=100, step=5,
        )
        y += ROW_HEIGHT + ROW_GAP

        self._sfx_vol_label_y = y
        self.sfx_vol_spinner = NumberSpinner(
            pygame.Rect(left_x + LABEL_WIDTH, y, WIDGET_WIDTH, 28),
            value=80, min_val=0, max_val=100, step=5,
        )
        y += ROW_HEIGHT + ROW_GAP

        self._music_vol_label_y = y
        self.music_vol_spinner = NumberSpinner(
            pygame.Rect(left_x + LABEL_WIDTH, y, WIDGET_WIDTH, 28),
            value=50, min_val=0, max_val=100, step=5,
        )

        # ---- RIGHT COLUMN: Display + System ----
        y = content_top
        self._display_header_y = y
        y += SECTION_HEADER_HEIGHT

        self._hex_coords_label_y = y
        self.show_hex_coords_cb = Checkbox(
            pygame.Rect(right_x + LABEL_WIDTH, y, WIDGET_WIDTH + 60, 28),
            label="",
            checked=False,
        )
        y += ROW_HEIGHT + ROW_GAP

        self._hex_size_label_y = y
        self.hex_size_spinner = NumberSpinner(
            pygame.Rect(right_x + LABEL_WIDTH, y, WIDGET_WIDTH, 28),
            value=40, min_val=20, max_val=80, step=2,
        )
        y += ROW_HEIGHT + ROW_GAP

        self._zoom_label_y = y
        self.zoom_spinner = NumberSpinner(
            pygame.Rect(right_x + LABEL_WIDTH, y, WIDGET_WIDTH, 28),
            value=110, min_val=101, max_val=150, step=1,
        )
        y += ROW_HEIGHT + ROW_GAP

        self._token_label_y = y
        self.token_spinner = NumberSpinner(
            pygame.Rect(right_x + LABEL_WIDTH, y, WIDGET_WIDTH, 28),
            value=18, min_val=8, max_val=40, step=1,
        )
        y += ROW_HEIGHT + ROW_GAP

        self._cursor_label_y = y
        # Build cursor options: "Random" + each discovered cursor name (title-case)
        self._cursor_options = self._build_cursor_options()
        self.cursor_dropdown = Dropdown(
            pygame.Rect(right_x + LABEL_WIDTH, y, WIDGET_WIDTH + 20, 28),
            options=self._cursor_options,
            selected_index=0,
            max_visible=4,
        )
        y += ROW_HEIGHT + ROW_GAP

        self._cursor_anim_label_y = y
        self.cursor_anim_cb = Checkbox(
            pygame.Rect(right_x + LABEL_WIDTH, y, WIDGET_WIDTH + 60, 28),
            label="",
            checked=True,
        )
        y += ROW_HEIGHT + ROW_GAP + 12

        # System section
        self._system_header_y = y
        y += SECTION_HEADER_HEIGHT

        self._resolution_label_y = y
        self.resolution_dropdown = Dropdown(
            pygame.Rect(right_x + LABEL_WIDTH, y, WIDGET_WIDTH + 20, 28),
            options=RESOLUTION_OPTIONS,
            selected_index=0,
            max_visible=4,
        )
        y += ROW_HEIGHT + ROW_GAP
        self._resolution_note_y = y
        y += ROW_HEIGHT + ROW_GAP

        self._auto_scroll_label_y = y
        self.auto_scroll_cb = Checkbox(
            pygame.Rect(right_x + LABEL_WIDTH, y, WIDGET_WIDTH + 60, 28),
            label="",
            checked=True,
        )

        # Column x positions stored for rendering labels
        self._left_x = left_x
        self._right_x = right_x

        # Collect all widgets for event routing
        self._spinners = [
            self.ai_step_spinner,
            self.ai_think_spinner,
            self.ai_random_spinner,
            self.master_vol_spinner,
            self.sfx_vol_spinner,
            self.music_vol_spinner,
            self.hex_size_spinner,
            self.zoom_spinner,
            self.token_spinner,
        ]
        self._checkboxes = [
            self.show_ai_thinking_cb,
            self.show_hex_coords_cb,
            self.cursor_anim_cb,
            self.auto_scroll_cb,
        ]

    @staticmethod
    def _build_cursor_options() -> list[str]:
        """Return the list of cursor options for the dropdown.

        Always starts with "Random", followed by title-cased stem names
        of every cursor image found in the assets folder.
        """
        # Use a temporary manager just to discover available cursors
        from pathlib import Path
        cursor_dir = Path("assets") / "ui" / "cursor"
        exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
        names: list[str] = []
        if cursor_dir.is_dir():
            for f in sorted(cursor_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in exts:
                    names.append(f.stem.capitalize())
        return ["Random"] + names

    # ------------------------------------------------------------------
    # Settings <-> widget sync
    # ------------------------------------------------------------------

    def _sync_widgets_from_settings(self) -> None:
        """Populate widget values from the current settings singleton."""
        s = get_settings()

        # Gameplay
        self.ai_step_spinner.value = s.gameplay.ai_step_delay
        self.ai_think_spinner.value = s.gameplay.ai_thinking_delay
        self.ai_random_spinner.value = int(s.gameplay.ai_randomness * 100)
        self.show_ai_thinking_cb.checked = s.gameplay.show_ai_thinking

        # Display
        self.show_hex_coords_cb.checked = s.display.show_hex_coordinates
        self.hex_size_spinner.value = s.display.default_hex_size
        self.zoom_spinner.value = int(s.display.zoom_speed * 100)
        self.token_spinner.value = s.display.token_radius
        # Cursor setting: stored as "Random" or lowercase stem, display as title-case
        cursor_display = s.display.cursor.capitalize()
        if cursor_display in self._cursor_options:
            self.cursor_dropdown.value = cursor_display
        else:
            self.cursor_dropdown.value = "Random"
        self.cursor_anim_cb.checked = s.display.cursor_animations

        # Audio
        self.master_vol_spinner.value = s.audio.master_volume
        self.sfx_vol_spinner.value = s.audio.sfx_volume
        self.music_vol_spinner.value = s.audio.music_volume

        # System
        self.resolution_dropdown.value = s.system.resolution
        self.auto_scroll_cb.checked = s.system.auto_scroll_combat_log

    def _sync_settings_from_widgets(self) -> None:
        """Write widget values back into the settings singleton."""
        s = get_settings()

        # Gameplay
        s.gameplay.ai_step_delay = self.ai_step_spinner.value
        s.gameplay.ai_thinking_delay = self.ai_think_spinner.value
        s.gameplay.ai_randomness = self.ai_random_spinner.value / 100.0
        s.gameplay.show_ai_thinking = self.show_ai_thinking_cb.checked

        # Display
        s.display.show_hex_coordinates = self.show_hex_coords_cb.checked
        s.display.default_hex_size = self.hex_size_spinner.value
        s.display.zoom_speed = self.zoom_spinner.value / 100.0
        s.display.token_radius = self.token_spinner.value

        # Cursor — apply change live when the dropdown value changes
        new_cursor = self.cursor_dropdown.value  # title-case display
        old_cursor = s.display.cursor
        # Normalise for comparison (settings stores e.g. "Random" or "sword")
        new_cursor_setting = new_cursor if new_cursor == "Random" else new_cursor.lower()
        if new_cursor_setting != old_cursor and self.app is not None:
            s.display.cursor = new_cursor_setting
            self.app.cursor_manager.change_cursor(new_cursor_setting)
        else:
            s.display.cursor = new_cursor_setting

        # Cursor animations — apply live
        s.display.cursor_animations = self.cursor_anim_cb.checked
        if self.app is not None:
            self.app.cursor_manager.animations_enabled = self.cursor_anim_cb.checked

        # Audio
        s.audio.master_volume = self.master_vol_spinner.value
        s.audio.sfx_volume = self.sfx_vol_spinner.value
        s.audio.music_volume = self.music_vol_spinner.value

        # System
        s.system.resolution = self.resolution_dropdown.value
        s.system.auto_scroll_combat_log = self.auto_scroll_cb.checked

    # ------------------------------------------------------------------
    # Screen lifecycle
    # ------------------------------------------------------------------

    def on_enter(self, app: App) -> None:
        self.app = app

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.go_to_main_menu()
            return

        # Dropdowns get first crack when open (z-order)
        if self.cursor_dropdown.is_open:
            if self.cursor_dropdown.handle_event(event):
                return
        if self.resolution_dropdown.is_open:
            if self.resolution_dropdown.handle_event(event):
                return

        # Mouse hover for top bar buttons
        if event.type == pygame.MOUSEMOTION:
            pos = event.pos
            self.save_hovered = self.save_btn.collidepoint(pos)
            self.reset_hovered = self.reset_btn.collidepoint(pos)
            self.back_hovered = self.back_btn.collidepoint(pos)

        # Mouse clicks
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            pos = event.pos
            if self.save_btn.collidepoint(pos):
                self._on_save()
                return
            if self.reset_btn.collidepoint(pos):
                self._on_reset()
                return
            if self.back_btn.collidepoint(pos):
                self.app.go_to_main_menu()
                return

        # Delegate to dropdowns (closed-state click-to-open)
        if self.resolution_dropdown.handle_event(event):
            return
        if self.cursor_dropdown.handle_event(event):
            return

        # Delegate to spinners
        for spinner in self._spinners:
            if spinner.handle_event(event):
                return

        # Delegate to checkboxes
        for cb in self._checkboxes:
            if cb.handle_event(event):
                return

    def update(self) -> None:
        # Decrement status timer
        if self.status_timer > 0:
            self.status_timer -= 1
            if self.status_timer <= 0:
                self.status_message = ""

        # Sync settings from widgets every frame (immediate effect)
        self._sync_settings_from_widgets()

    def render(self, surface: pygame.Surface) -> None:
        # Shared background slideshow (kept alive in App)
        self.app.render_background(surface)

        self._render_top_bar(surface)
        self._render_left_column(surface)
        self._render_right_column(surface)
        self._render_status_bar(surface)

        # Dropdown overlays (must be last)
        self.cursor_dropdown.render_dropdown(surface)
        self.resolution_dropdown.render_dropdown(surface)

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------

    def _on_save(self) -> None:
        self._sync_settings_from_widgets()
        save_settings()
        self.status_message = "Settings saved."
        self.status_timer = 150  # ~2.5 seconds at 60 FPS

    def _on_reset(self) -> None:
        reset_settings()
        self._sync_widgets_from_settings()
        self.status_message = "Reset to defaults."
        self.status_timer = 150

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _draw_button(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        text: str,
        hovered: bool,
    ) -> None:
        """Draw a styled button (matches existing project button style)."""
        color = (
            parse_color(COLORS["button_hover"])
            if hovered
            else parse_color(COLORS["button_normal"])
        )
        pygame.draw.rect(surface, color, rect, border_radius=6)
        pygame.draw.rect(
            surface,
            parse_color(COLORS["hex_border"]),
            rect, 1, border_radius=6,
        )
        draw_text_centered(
            surface, text, rect.center,
            parse_color(COLORS["text_primary"]),
            font_size=16,
        )

    def _render_top_bar(self, surface: pygame.Surface) -> None:
        # Background strip
        bar_rect = pygame.Rect(0, 0, self.screen_width, TOP_BAR_HEIGHT)
        pygame.draw.rect(surface, parse_color(COLORS["bg_medium"]), bar_rect)
        pygame.draw.line(
            surface, parse_color(COLORS["hex_border"]),
            (0, TOP_BAR_HEIGHT - 1), (self.screen_width, TOP_BAR_HEIGHT - 1),
        )

        # Title
        font = get_font(26)
        title_surf = font.render("Settings", True, parse_color(COLORS["text_gold"]))
        surface.blit(title_surf, (20, (TOP_BAR_HEIGHT - title_surf.get_height()) // 2))

        # Buttons
        draw_image_button(
            surface, self.save_btn, "Save",
            is_hovered=self.save_hovered, font_size=16,
        )
        draw_image_button(
            surface, self.reset_btn, "Reset Defaults",
            is_hovered=self.reset_hovered, font_size=16,
        )
        draw_image_button(
            surface, self.back_btn, "Back",
            is_hovered=self.back_hovered, is_quit=True, font_size=16,
        )

    def _draw_section_header(
        self, surface: pygame.Surface, x: int, y: int, text: str,
    ) -> None:
        font = get_font(18)
        header_surf = font.render(text, True, parse_color(COLORS["text_gold"]))
        surface.blit(header_surf, (x, y + 4))
        # Underline
        line_y = y + SECTION_HEADER_HEIGHT - 4
        line_w = LABEL_WIDTH + WIDGET_WIDTH
        pygame.draw.line(
            surface, parse_color(COLORS["border_accent"]),
            (x, line_y), (x + line_w, line_y),
        )

    def _draw_label(
        self, surface: pygame.Surface, x: int, y: int, text: str,
    ) -> None:
        font = get_font(15)
        label_surf = font.render(text, True, parse_color(COLORS["text_secondary"]))
        # Vertically centre label with the 28px-tall widget
        surface.blit(label_surf, (x, y + (28 - label_surf.get_height()) // 2))

    def _render_left_column(self, surface: pygame.Surface) -> None:
        x = self._left_x

        # Gameplay
        self._draw_section_header(surface, x, self._gameplay_header_y, "GAMEPLAY")
        self._draw_label(surface, x, self._ai_step_label_y, "AI Step Delay (ms)")
        self.ai_step_spinner.render(surface)
        self._draw_label(surface, x, self._ai_think_label_y, "AI Thinking Delay (ms)")
        self.ai_think_spinner.render(surface)
        self._draw_label(surface, x, self._ai_random_label_y, "AI Randomness (%)")
        self.ai_random_spinner.render(surface)
        self._draw_label(surface, x, self._ai_thinking_label_y, "Show AI Thinking")
        self.show_ai_thinking_cb.render(surface)

        # Audio
        self._draw_section_header(surface, x, self._audio_header_y, "AUDIO")
        self._draw_label(surface, x, self._master_vol_label_y, "Master Volume")
        self.master_vol_spinner.render(surface)
        self._draw_label(surface, x, self._sfx_vol_label_y, "SFX Volume")
        self.sfx_vol_spinner.render(surface)
        self._draw_label(surface, x, self._music_vol_label_y, "Music Volume")
        self.music_vol_spinner.render(surface)

    def _render_right_column(self, surface: pygame.Surface) -> None:
        x = self._right_x

        # Display
        self._draw_section_header(surface, x, self._display_header_y, "DISPLAY")
        self._draw_label(surface, x, self._hex_coords_label_y, "Show Hex Coordinates")
        self.show_hex_coords_cb.render(surface)
        self._draw_label(surface, x, self._hex_size_label_y, "Default Hex Size (px)")
        self.hex_size_spinner.render(surface)
        self._draw_label(surface, x, self._zoom_label_y, "Zoom Speed (%)")
        self.zoom_spinner.render(surface)
        self._draw_label(surface, x, self._token_label_y, "Token Radius (px)")
        self.token_spinner.render(surface)
        self._draw_label(surface, x, self._cursor_label_y, "Cursor")
        self.cursor_dropdown.render(surface)
        self._draw_label(surface, x, self._cursor_anim_label_y, "Cursor Animations")
        self.cursor_anim_cb.render(surface)

        # System
        self._draw_section_header(surface, x, self._system_header_y, "SYSTEM")
        self._draw_label(surface, x, self._resolution_label_y, "Window Resolution")
        self.resolution_dropdown.render(surface)

        # Resolution note
        note_font = get_font(12)
        note_surf = note_font.render(
            "Changes apply on next launch",
            True,
            parse_color(COLORS["text_secondary"]),
        )
        surface.blit(note_surf, (x + LABEL_WIDTH, self._resolution_note_y + 4))

        self._draw_label(surface, x, self._auto_scroll_label_y, "Auto-scroll Combat Log")
        self.auto_scroll_cb.render(surface)

    def _render_status_bar(self, surface: pygame.Surface) -> None:
        if not self.status_message:
            return
        bar_y = self.screen_height - STATUS_BAR_HEIGHT
        draw_text_centered(
            surface,
            self.status_message,
            (self.screen_width // 2, bar_y + STATUS_BAR_HEIGHT // 2),
            parse_color(COLORS["text_secondary"]),
            font_size=16,
        )
