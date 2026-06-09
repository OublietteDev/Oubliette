"""Main menu screen."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from arena.gui.screens.base import Screen
from arena.gui.renderer import draw_text_centered
from arena.gui.button_images import draw_image_button
from arena.util.constants import COLORS, parse_color

if TYPE_CHECKING:
    from arena.gui.app import App

# Action IDs that should use the quit/back (red) button image
_QUIT_ACTIONS = {"quit"}


class MenuButton:
    """A main menu button styled with fantasy button artwork."""

    def __init__(self, rect: pygame.Rect, label: str, action_id: str) -> None:
        self.rect = rect
        self.label = label
        self.action_id = action_id
        self.is_hovered = False

    def render(self, surface: pygame.Surface) -> None:
        draw_image_button(
            surface,
            self.rect,
            self.label,
            is_hovered=self.is_hovered,
            is_quit=self.action_id in _QUIT_ACTIONS,
            font_size=22,
        )


class MainMenuScreen(Screen):
    """Main menu with navigation buttons."""

    MENU_ITEMS = [
        ("New Encounter", "new_encounter"),
        ("Load Encounter", "load_encounter"),
        ("Load Save", "load_save"),
        ("New Creature", "new_creature"),
        ("Load Creature", "load_creature"),
        ("Settings", "settings"),
        ("Quit", "quit"),
    ]

    def __init__(self, screen_width: int, screen_height: int) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.app: App | None = None
        self.buttons: list[MenuButton] = []
        self._build_buttons()

    def _build_buttons(self) -> None:
        btn_width = 280
        btn_height = 48
        gap = 16
        total_height = len(self.MENU_ITEMS) * btn_height + (len(self.MENU_ITEMS) - 1) * gap
        # Offset downward to leave room for title
        start_y = (self.screen_height - total_height) // 2 + 60
        center_x = self.screen_width // 2

        for i, (label, action_id) in enumerate(self.MENU_ITEMS):
            x = center_x - btn_width // 2
            y = start_y + i * (btn_height + gap)
            rect = pygame.Rect(x, y, btn_width, btn_height)
            self.buttons.append(MenuButton(rect, label, action_id))

    def on_enter(self, app: App) -> None:
        self.app = app

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.quit()
            return

        if event.type == pygame.MOUSEMOTION:
            for btn in self.buttons:
                btn.is_hovered = btn.rect.collidepoint(event.pos)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for btn in self.buttons:
                if btn.rect.collidepoint(event.pos):
                    self._on_button_click(btn.action_id)
                    return

    def _on_button_click(self, action_id: str) -> None:
        from arena.audio.manager import get_sound_manager
        get_sound_manager().play_sfx("button_click")

        if action_id == "new_encounter":
            self.app.go_to_encounter_setup()
        elif action_id == "load_encounter":
            self.app.go_to_encounter_select()
        elif action_id == "load_save":
            self.app.go_to_save_select()
        elif action_id == "new_creature":
            self.app.go_to_creature_builder()
        elif action_id == "load_creature":
            self.app.go_to_creature_select()
        elif action_id == "settings":
            self.app.go_to_settings()
        elif action_id == "quit":
            self.app.quit()

    def update(self) -> None:
        pass

    def render(self, surface: pygame.Surface) -> None:
        # Shared background slideshow (kept alive in App)
        self.app.render_background(surface)

        cx = self.screen_width // 2

        # Title — gold fantasy text
        draw_text_centered(
            surface,
            "The Arena",
            (cx, 110),
            parse_color(COLORS["text_gold"]),
            font_size=48,
        )
        # Subtitle
        draw_text_centered(
            surface,
            "Tactical Combat Engine",
            (cx, 158),
            parse_color(COLORS["text_secondary"]),
            font_size=22,
        )

        # Decorative separator line
        sep_y = 180
        sep_w = 240
        border_col = parse_color(COLORS["border_accent"])
        pygame.draw.line(surface, border_col, (cx - sep_w, sep_y), (cx + sep_w, sep_y), 1)
        # Small diamond in the center
        d = 4
        diamond = [(cx, sep_y - d), (cx + d, sep_y), (cx, sep_y + d), (cx - d, sep_y)]
        pygame.draw.polygon(surface, parse_color(COLORS["text_gold"]), diamond)

        # Buttons
        for btn in self.buttons:
            btn.render(surface)
