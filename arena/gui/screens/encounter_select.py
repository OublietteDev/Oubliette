"""Encounter selection screen — file picker for loading encounters."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from arena.gui.screens.base import Screen
from arena.gui.renderer import draw_text_centered
from arena.gui.button_images import draw_image_button
from arena.util.constants import COLORS, parse_color

if TYPE_CHECKING:
    from arena.gui.app import App


class EncounterSelectScreen(Screen):
    """Lists available encounter files and launches combat on selection."""

    def __init__(self, screen_width: int, screen_height: int) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.app: App | None = None

        self.encounters: list[Path] = []
        self.hover_index: int | None = None
        self.back_hovered = False
        self.scroll_offset: int = 0

        self._scan_encounters()
        self._build_ui()

    def _scan_encounters(self) -> None:
        """Find all .json files in data/encounters/."""
        encounters_dir = Path("data") / "encounters"
        if encounters_dir.exists():
            self.encounters = sorted(encounters_dir.glob("*.json"))

    def _build_ui(self) -> None:
        """Build layout rects for encounter entries and back button."""
        self.btn_width = 400
        self.btn_height = 44
        self.btn_gap = 12
        self.list_start_y = 160
        self.center_x = self.screen_width // 2

        # Back button at bottom
        back_w, back_h = 160, 44
        self.back_button = pygame.Rect(
            self.center_x - back_w // 2,
            self.screen_height - 100,
            back_w,
            back_h,
        )

        # Scrollable area: from list_start_y down to just above the back button
        self.list_bottom_y = self.screen_height - 120
        self.list_clip_rect = pygame.Rect(
            0, self.list_start_y,
            self.screen_width, self.list_bottom_y - self.list_start_y,
        )

    def _get_entry_rect(self, index: int) -> pygame.Rect:
        """Get the rect for the encounter entry at the given index."""
        x = self.center_x - self.btn_width // 2
        y = self.list_start_y + index * (self.btn_height + self.btn_gap) - self.scroll_offset
        return pygame.Rect(x, y, self.btn_width, self.btn_height)

    def _get_max_scroll(self) -> int:
        """Calculate the maximum scroll offset."""
        if not self.encounters:
            return 0
        total_content_height = len(self.encounters) * (self.btn_height + self.btn_gap) - self.btn_gap
        visible_height = self.list_bottom_y - self.list_start_y
        return max(0, total_content_height - visible_height)

    def _clamp_scroll(self) -> None:
        """Clamp scroll_offset to valid range."""
        self.scroll_offset = max(0, min(self.scroll_offset, self._get_max_scroll()))

    def on_enter(self, app: App) -> None:
        self.app = app

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.go_to_main_menu()
            return

        # Mousewheel scrolling
        if event.type == pygame.MOUSEWHEEL:
            self.scroll_offset -= event.y * 40
            self._clamp_scroll()
            # Update hover after scroll
            mouse_pos = pygame.mouse.get_pos()
            self._update_hover(mouse_pos)
            return

        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            pos = event.pos
            if self.back_button.collidepoint(pos):
                self.app.go_to_main_menu()
                return
            # Only register clicks within the scrollable list area
            if self.list_clip_rect.collidepoint(pos):
                for i, path in enumerate(self.encounters):
                    rect = self._get_entry_rect(i)
                    if rect.collidepoint(pos) and self.list_clip_rect.colliderect(rect):
                        self.app.go_to_combat(path)
                        return

    def _update_hover(self, pos: tuple[int, int]) -> None:
        """Update hover state for back button and encounter entries."""
        self.back_hovered = self.back_button.collidepoint(pos)
        self.hover_index = None
        if self.list_clip_rect.collidepoint(pos):
            for i in range(len(self.encounters)):
                rect = self._get_entry_rect(i)
                if rect.collidepoint(pos) and self.list_clip_rect.colliderect(rect):
                    self.hover_index = i
                    break

    def update(self) -> None:
        pass

    def render(self, surface: pygame.Surface) -> None:
        # Shared background slideshow (kept alive in App)
        self.app.render_background(surface)

        # Title
        draw_text_centered(
            surface,
            "Select Encounter",
            (self.screen_width // 2, 80),
            parse_color(COLORS["text_gold"]),
            font_size=36,
        )

        # Clip to scrollable area for encounter entries
        old_clip = surface.get_clip()
        surface.set_clip(self.list_clip_rect)

        # Encounter entries
        for i, path in enumerate(self.encounters):
            rect = self._get_entry_rect(i)
            # Skip entries that are completely outside the clip area
            if rect.bottom < self.list_clip_rect.top or rect.top > self.list_clip_rect.bottom:
                continue
            hovered = i == self.hover_index
            display_name = path.stem.replace("_", " ").title()
            draw_image_button(
                surface, rect, display_name,
                is_hovered=hovered, font_size=20,
            )

        # Restore clip
        surface.set_clip(old_clip)

        # Empty state
        if not self.encounters:
            draw_text_centered(
                surface,
                "No encounter files found in data/encounters/",
                (self.screen_width // 2, 200),
                parse_color(COLORS["text_secondary"]),
                font_size=18,
            )

        # Scroll indicators (arrows at top/bottom when content is clipped)
        max_scroll = self._get_max_scroll()
        if max_scroll > 0:
            indicator_color = parse_color(COLORS["text_secondary"])
            if self.scroll_offset > 0:
                # Up arrow indicator
                draw_text_centered(
                    surface, "▲",
                    (self.center_x, self.list_start_y - 12),
                    indicator_color, font_size=16,
                )
            if self.scroll_offset < max_scroll:
                # Down arrow indicator
                draw_text_centered(
                    surface, "▼",
                    (self.center_x, self.list_bottom_y + 8),
                    indicator_color, font_size=16,
                )

        # Back button
        draw_image_button(
            surface, self.back_button, "Back",
            is_hovered=self.back_hovered, is_quit=True, font_size=20,
        )
