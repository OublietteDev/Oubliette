"""Error screen — displays a user-friendly error message with a back button."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from arena.gui.screens.base import Screen
from arena.gui.renderer import draw_text_centered, get_font
from arena.gui.button_images import draw_image_button
from arena.util.constants import COLORS, parse_color

if TYPE_CHECKING:
    from arena.gui.app import App


class ErrorScreen(Screen):
    """Displays an error title and detail message with a Back button."""

    def __init__(
        self,
        screen_width: int,
        screen_height: int,
        title: str = "Error",
        message: str = "",
    ) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.title = title
        self.message = message
        self.app: App | None = None

        back_w, back_h = 160, 44
        center_x = screen_width // 2
        self.back_button = pygame.Rect(
            center_x - back_w // 2,
            screen_height // 2 + 80,
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
        # Shared background
        self.app.render_background(surface)

        # Title
        draw_text_centered(
            surface,
            self.title,
            (self.screen_width // 2, self.screen_height // 2 - 60),
            parse_color(COLORS["hp_critical"]),
            font_size=32,
        )

        # Detail message — wrap long lines
        if self.message:
            self._render_wrapped(
                surface,
                self.message,
                self.screen_width // 2,
                self.screen_height // 2,
                max_width=int(self.screen_width * 0.7),
                font_size=18,
            )

        # Back button
        draw_image_button(
            surface, self.back_button, "Back",
            is_hovered=self.back_hovered, is_quit=True, font_size=20,
        )

    @staticmethod
    def _render_wrapped(
        surface: pygame.Surface,
        text: str,
        cx: int,
        start_y: int,
        max_width: int,
        font_size: int = 18,
    ) -> None:
        """Render text centered, wrapping at max_width."""
        font = get_font(font_size)
        color = parse_color(COLORS["text_secondary"])
        line_height = font_size + 6
        words = text.split()
        lines: list[str] = []
        current_line = ""

        for word in words:
            test = f"{current_line} {word}".strip()
            if font.size(test)[0] <= max_width:
                current_line = test
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        y = start_y
        for line in lines:
            text_surf = font.render(line, True, color)
            rect = text_surf.get_rect(center=(cx, y))
            surface.blit(text_surf, rect)
            y += line_height
