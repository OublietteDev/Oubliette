"""Save file selection screen for loading saved combat states."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from arena.gui.screens.base import Screen
from arena.gui.renderer import draw_text_centered, get_font
from arena.gui.button_images import draw_image_button
from arena.util.constants import COLORS, parse_color

if TYPE_CHECKING:
    from arena.gui.app import App


class _SaveInfo:
    """Cached metadata about a save file."""

    __slots__ = ("path", "name", "round_number", "timestamp")

    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = path.stem.replace("_", " ").title()
        self.round_number: int | None = None
        self.timestamp: str | None = None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            init = data.get("initiative", {})
            self.round_number = init.get("round_number")
            self.timestamp = data.get("timestamp", "")[:16]  # "2026-01-29T12:00"
        except Exception:
            pass

    @property
    def display_line(self) -> str:
        parts = [self.name]
        if self.round_number is not None:
            parts.append(f"Round {self.round_number}")
        if self.timestamp:
            parts.append(self.timestamp.replace("T", " "))
        return "  |  ".join(parts)


class SaveSelectScreen(Screen):
    """Lists saved combat files and allows loading or deleting them."""

    def __init__(self, screen_width: int, screen_height: int) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.app: App | None = None

        self.saves: list[_SaveInfo] = []
        self.hover_index: int | None = None
        self.back_hovered = False
        self.delete_hover_index: int | None = None
        self._confirm_delete_index: int | None = None

        self._scan_saves()
        self._build_ui()

    def _scan_saves(self) -> None:
        """Find all .json files in data/saves/."""
        saves_dir = Path("data") / "saves"
        if saves_dir.exists():
            paths = sorted(saves_dir.glob("*.json"), reverse=True)
            self.saves = [_SaveInfo(p) for p in paths]

    def _build_ui(self) -> None:
        self.btn_width = 500
        self.btn_height = 44
        self.btn_gap = 12
        self.list_start_y = 160
        self.center_x = self.screen_width // 2
        self.delete_btn_size = 28

        back_w, back_h = 160, 44
        self.back_button = pygame.Rect(
            self.center_x - back_w // 2,
            self.screen_height - 100,
            back_w,
            back_h,
        )

    def _get_entry_rect(self, index: int) -> pygame.Rect:
        x = self.center_x - self.btn_width // 2
        y = self.list_start_y + index * (self.btn_height + self.btn_gap)
        return pygame.Rect(x, y, self.btn_width, self.btn_height)

    def _get_delete_rect(self, index: int) -> pygame.Rect:
        entry = self._get_entry_rect(index)
        return pygame.Rect(
            entry.right + 8,
            entry.y + (self.btn_height - self.delete_btn_size) // 2,
            self.delete_btn_size,
            self.delete_btn_size,
        )

    def on_enter(self, app: App) -> None:
        self.app = app

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.go_to_main_menu()
            return

        if event.type == pygame.MOUSEMOTION:
            pos = event.pos
            self.back_hovered = self.back_button.collidepoint(pos)
            self.hover_index = None
            self.delete_hover_index = None
            for i in range(len(self.saves)):
                if self._get_entry_rect(i).collidepoint(pos):
                    self.hover_index = i
                if self._get_delete_rect(i).collidepoint(pos):
                    self.delete_hover_index = i

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            pos = event.pos

            if self.back_button.collidepoint(pos):
                self.app.go_to_main_menu()
                return

            # Handle delete confirmation
            if self._confirm_delete_index is not None:
                idx = self._confirm_delete_index
                if self._get_delete_rect(idx).collidepoint(pos):
                    # Confirmed delete
                    self._delete_save(idx)
                    self._confirm_delete_index = None
                    return
                else:
                    # Cancel delete
                    self._confirm_delete_index = None

            # Check delete buttons
            for i in range(len(self.saves)):
                if self._get_delete_rect(i).collidepoint(pos):
                    self._confirm_delete_index = i
                    return

            # Check load buttons
            for i, save in enumerate(self.saves):
                if self._get_entry_rect(i).collidepoint(pos):
                    self.app.go_to_combat_from_save(save.path)
                    return

    def _delete_save(self, index: int) -> None:
        """Delete a save file and remove it from the list."""
        if 0 <= index < len(self.saves):
            save = self.saves[index]
            try:
                save.path.unlink()
            except OSError:
                pass
            self.saves.pop(index)

    def update(self) -> None:
        pass

    def render(self, surface: pygame.Surface) -> None:
        # Shared background slideshow (kept alive in App)
        self.app.render_background(surface)

        # Title
        draw_text_centered(
            surface,
            "Load Saved Combat",
            (self.screen_width // 2, 80),
            parse_color(COLORS["text_gold"]),
            font_size=36,
        )

        # Save entries
        for i, save in enumerate(self.saves):
            rect = self._get_entry_rect(i)
            hovered = i == self.hover_index

            # Draw image button background (no centered label — we draw
            # left-aligned text manually for the multi-part display line)
            draw_image_button(
                surface, rect, "",
                is_hovered=hovered, font_size=16,
            )

            # Display text (left-aligned within the button)
            text_color = (
                parse_color(COLORS["text_gold"])
                if hovered
                else parse_color(COLORS["text_primary"])
            )
            font = get_font(16)
            text_surf = font.render(save.display_line, True, text_color)
            surface.blit(
                text_surf,
                (rect.x + 12, rect.y + (self.btn_height - text_surf.get_height()) // 2),
            )

            # Delete button
            del_rect = self._get_delete_rect(i)
            is_confirm = self._confirm_delete_index == i
            del_hovered = i == self.delete_hover_index

            if is_confirm:
                del_color = parse_color(COLORS["hp_critical"])
            elif del_hovered:
                del_color = parse_color(COLORS["button_hover"])
            else:
                del_color = parse_color(COLORS["button_normal"])

            pygame.draw.rect(surface, del_color, del_rect, border_radius=4)
            pygame.draw.rect(
                surface,
                parse_color(COLORS["hex_border"]),
                del_rect,
                1,
                border_radius=4,
            )

            del_label = "!" if is_confirm else "X"
            draw_text_centered(
                surface,
                del_label,
                del_rect.center,
                parse_color(COLORS["text_primary"]),
                font_size=14,
            )

        # Empty state
        if not self.saves:
            draw_text_centered(
                surface,
                "No saved games found in data/saves/",
                (self.screen_width // 2, 200),
                parse_color(COLORS["text_secondary"]),
                font_size=18,
            )
            draw_text_centered(
                surface,
                "Press Ctrl+S during combat to save",
                (self.screen_width // 2, 230),
                parse_color(COLORS["text_secondary"]),
                font_size=16,
            )

        # Delete confirmation hint
        if self._confirm_delete_index is not None:
            draw_text_centered(
                surface,
                "Click ! again to confirm deletion",
                (self.screen_width // 2, self.screen_height - 140),
                parse_color(COLORS["hp_critical"]),
                font_size=14,
            )

        # Back button
        draw_image_button(
            surface, self.back_button, "Back",
            is_hovered=self.back_hovered, is_quit=True, font_size=20,
        )
