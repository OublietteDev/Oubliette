"""Reusable 'Coming Soon' placeholder screen."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from arena.gui.screens.base import Screen
from arena.gui.renderer import draw_text_centered
from arena.gui.button_images import draw_image_button
from arena.util.constants import COLORS, parse_color

if TYPE_CHECKING:
    from arena.gui.app import App


class StubScreen(Screen):
    """Placeholder screen showing 'Coming Soon' with a back button."""

    def __init__(self, screen_width: int, screen_height: int, title: str) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.title = title
        self.app: App | None = None

        back_w, back_h = 160, 44
        center_x = screen_width // 2
        self.back_button = pygame.Rect(
            center_x - back_w // 2,
            screen_height // 2 + 60,
            back_w,
            back_h,
        )
        self.back_hovered = False

    def on_enter(self, app: App) -> None:
        self.app = app

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.go_to_main_menu()
            return

        if event.type == pygame.MOUSEMOTION:
            self.back_hovered = self.back_button.collidepoint(event.pos)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.back_button.collidepoint(event.pos):
                self.app.go_to_main_menu()

    def update(self) -> None:
        pass

    def render(self, surface: pygame.Surface) -> None:
        # Title
        draw_text_centered(
            surface,
            self.title,
            (self.screen_width // 2, self.screen_height // 2 - 60),
            parse_color(COLORS["text_gold"]),
            font_size=36,
        )
        # Subtitle
        draw_text_centered(
            surface,
            "Coming Soon",
            (self.screen_width // 2, self.screen_height // 2),
            parse_color(COLORS["text_secondary"]),
            font_size=24,
        )
        # Back button
        draw_image_button(
            surface, self.back_button, "Back",
            is_hovered=self.back_hovered, is_quit=True, font_size=20,
        )
