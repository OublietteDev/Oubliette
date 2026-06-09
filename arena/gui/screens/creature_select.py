"""Creature selection screen — file picker for loading creatures into the builder."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from arena.gui.screens.base import Screen
from arena.gui.renderer import draw_text_centered, get_font
from arena.gui.button_images import draw_image_button
from arena.util.constants import COLORS, parse_color
from arena.util.loader import load_json

if TYPE_CHECKING:
    from arena.gui.app import App


class _CreatureEntry:
    """Cached metadata about a discovered creature file."""

    __slots__ = ("path", "name", "subtitle", "category")

    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = path.stem.replace("_", " ").title()
        self.subtitle = ""
        self.category = "character"  # "character" or "monster"

        try:
            data = load_json(path)
            self.name = data.get("name", self.name)

            if "character_class" in data:
                self.category = "character"
                cls = data.get("character_class", "")
                lvl = data.get("level", "")
                race = data.get("race", "")
                parts = [p for p in [race, cls, f"Lv.{lvl}" if lvl else ""] if p]
                self.subtitle = " | ".join(parts)
            else:
                is_pc = data.get("is_player_controlled", False)
                self.category = "npc" if is_pc else "monster"
                cr = data.get("challenge_rating", "")
                ctype = data.get("creature_type", "")
                parts = [ctype.title() if ctype else ""]
                if cr != "":
                    parts.append(f"CR {cr}")
                self.subtitle = " | ".join(p for p in parts if p)
        except Exception:
            pass


class CreatureSelectScreen(Screen):
    """Lists available creature files and opens the builder on selection."""

    def __init__(self, screen_width: int, screen_height: int) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.app: App | None = None

        self.entries: list[_CreatureEntry] = []
        self.hover_index: int | None = None
        self.back_hovered = False
        self.new_hovered = False
        self.scroll_y = 0

        self._scan_creatures()
        self._build_ui()

    def _scan_creatures(self) -> None:
        """Find all .json files in data/characters/ and data/monsters/."""
        for subdir in ("characters", "monsters"):
            directory = Path("data") / subdir
            if directory.exists():
                for p in sorted(directory.glob("*.json")):
                    self.entries.append(_CreatureEntry(p))

        # Sort: characters first, then monsters, alphabetical within each
        category_order = {"character": 0, "npc": 1, "monster": 2}
        self.entries.sort(key=lambda e: (category_order.get(e.category, 9), e.name))

    def _build_ui(self) -> None:
        self.btn_width = 500
        self.btn_height = 52
        self.btn_gap = 10
        self.list_start_y = 160
        self.center_x = self.screen_width // 2

        # Back button at bottom-left
        back_w, back_h = 160, 44
        self.back_button = pygame.Rect(
            self.center_x - back_w - 10,
            self.screen_height - 90,
            back_w,
            back_h,
        )

        # New Creature button at bottom-right
        self.new_button = pygame.Rect(
            self.center_x + 10,
            self.screen_height - 90,
            back_w,
            back_h,
        )

    def _get_entry_rect(self, index: int) -> pygame.Rect:
        x = self.center_x - self.btn_width // 2
        y = self.list_start_y + index * (self.btn_height + self.btn_gap) - self.scroll_y
        return pygame.Rect(x, y, self.btn_width, self.btn_height)

    def _get_list_content_height(self) -> int:
        return len(self.entries) * (self.btn_height + self.btn_gap)

    def _get_visible_area_height(self) -> int:
        return self.screen_height - self.list_start_y - 110

    def on_enter(self, app: App) -> None:
        self.app = app

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.go_to_main_menu()
            return

        if event.type == pygame.MOUSEWHEEL:
            max_scroll = max(
                0, self._get_list_content_height() - self._get_visible_area_height(),
            )
            self.scroll_y = max(0, min(max_scroll, self.scroll_y - event.y * 40))
            return

        if event.type == pygame.MOUSEMOTION:
            pos = event.pos
            self.back_hovered = self.back_button.collidepoint(pos)
            self.new_hovered = self.new_button.collidepoint(pos)
            self.hover_index = None
            for i in range(len(self.entries)):
                rect = self._get_entry_rect(i)
                if rect.collidepoint(pos) and rect.bottom > self.list_start_y:
                    self.hover_index = i
                    break

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            pos = event.pos
            if self.back_button.collidepoint(pos):
                from arena.audio.manager import get_sound_manager
                get_sound_manager().play_sfx("button_click")
                self.app.go_to_main_menu()
                return
            if self.new_button.collidepoint(pos):
                from arena.audio.manager import get_sound_manager
                get_sound_manager().play_sfx("button_click")
                self.app.go_to_creature_builder()
                return
            for i, entry in enumerate(self.entries):
                rect = self._get_entry_rect(i)
                if rect.collidepoint(pos) and rect.bottom > self.list_start_y:
                    from arena.audio.manager import get_sound_manager
                    get_sound_manager().play_sfx("button_click")
                    self.app.go_to_creature_builder(entry.path)
                    return

    def update(self) -> None:
        pass

    def render(self, surface: pygame.Surface) -> None:
        self.app.render_background(surface)

        # Title
        draw_text_centered(
            surface,
            "Load Creature",
            (self.screen_width // 2, 60),
            parse_color(COLORS["text_gold"]),
            font_size=36,
        )

        # Subtitle
        draw_text_centered(
            surface,
            "Select a creature to edit in the Character Builder",
            (self.screen_width // 2, 105),
            parse_color(COLORS["text_secondary"]),
            font_size=16,
        )

        # Decorative separator
        sep_y = 130
        sep_w = 200
        cx = self.screen_width // 2
        border_col = parse_color(COLORS["border_accent"])
        pygame.draw.line(surface, border_col, (cx - sep_w, sep_y), (cx + sep_w, sep_y), 1)

        # Clip the list area
        list_clip = pygame.Rect(
            0, self.list_start_y,
            self.screen_width, self._get_visible_area_height(),
        )
        old_clip = surface.get_clip()
        surface.set_clip(list_clip)

        font = get_font(18)
        small_font = get_font(13)
        label_color = parse_color(COLORS["text_secondary"])
        current_category = None

        for i, entry in enumerate(self.entries):
            rect = self._get_entry_rect(i)

            # Skip if fully outside visible area
            if rect.bottom < self.list_start_y or rect.top > list_clip.bottom:
                continue

            # Category separator header
            if entry.category != current_category:
                current_category = entry.category
                cat_labels = {
                    "character": "Characters",
                    "npc": "NPCs",
                    "monster": "Monsters",
                }
                cat_text = cat_labels.get(current_category, "Other")
                cat_y = rect.y - 22
                if cat_y >= self.list_start_y - 10:
                    cat_surf = small_font.render(cat_text, True, parse_color(COLORS["text_gold"]))
                    surface.blit(cat_surf, (rect.x + 4, cat_y))

            # Button background
            hovered = i == self.hover_index
            if hovered:
                bg_color = parse_color(COLORS["button_hover"])
            else:
                bg_color = parse_color(COLORS["button_normal"])

            pygame.draw.rect(surface, bg_color, rect, border_radius=6)
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                rect, 1, border_radius=6,
            )

            # Name
            name_surf = font.render(entry.name, True, parse_color(COLORS["text_primary"]))
            surface.blit(name_surf, (rect.x + 16, rect.y + 6))

            # Subtitle (class/race or CR/type)
            if entry.subtitle:
                sub_surf = small_font.render(
                    entry.subtitle, True, label_color,
                )
                surface.blit(sub_surf, (rect.x + 16, rect.y + 30))

            # Category badge on the right
            badge_labels = {
                "character": "PC",
                "npc": "NPC",
                "monster": "MON",
            }
            badge = badge_labels.get(entry.category, "?")
            badge_surf = small_font.render(badge, True, parse_color(COLORS["text_gold"]))
            surface.blit(
                badge_surf,
                (rect.right - badge_surf.get_width() - 16, rect.y + 16),
            )

        # Empty state
        if not self.entries:
            draw_text_centered(
                surface,
                "No creature files found in data/characters/ or data/monsters/",
                (self.screen_width // 2, self.list_start_y + 40),
                label_color,
                font_size=18,
            )

        surface.set_clip(old_clip)

        # Bottom buttons
        draw_image_button(
            surface, self.back_button, "Back",
            is_hovered=self.back_hovered, is_quit=True, font_size=20,
        )
        draw_image_button(
            surface, self.new_button, "New Creature",
            is_hovered=self.new_hovered, font_size=20,
        )
