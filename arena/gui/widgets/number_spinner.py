"""Number spinner widget with +/- buttons."""

from __future__ import annotations

import pygame

from arena.gui.renderer import draw_text_centered, get_font
from arena.util.constants import COLORS, parse_color


class NumberSpinner:
    """A numeric value with [-] and [+] buttons."""

    def __init__(
        self,
        rect: pygame.Rect,
        value: int = 10,
        min_val: int = 0,
        max_val: int = 30,
        step: int = 1,
    ) -> None:
        self.rect = rect
        self.value = value
        self.min_val = min_val
        self.max_val = max_val
        self.step = step

        # Sub-rects: [-] [value] [+]
        btn_size = min(rect.height, 24)
        self.minus_btn = pygame.Rect(
            rect.x, rect.y + (rect.height - btn_size) // 2,
            btn_size, btn_size,
        )
        self.plus_btn = pygame.Rect(
            rect.right - btn_size, rect.y + (rect.height - btn_size) // 2,
            btn_size, btn_size,
        )
        self.minus_hovered = False
        self.plus_hovered = False

    def update_subrects(self) -> None:
        """Recompute minus/plus button rects from current self.rect."""
        btn_size = min(self.rect.height, 24)
        self.minus_btn = pygame.Rect(
            self.rect.x, self.rect.y + (self.rect.height - btn_size) // 2,
            btn_size, btn_size,
        )
        self.plus_btn = pygame.Rect(
            self.rect.right - btn_size,
            self.rect.y + (self.rect.height - btn_size) // 2,
            btn_size, btn_size,
        )

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Handle an event. Returns True if consumed."""
        if event.type == pygame.MOUSEMOTION:
            self.minus_hovered = self.minus_btn.collidepoint(event.pos)
            self.plus_hovered = self.plus_btn.collidepoint(event.pos)
            return False

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.minus_btn.collidepoint(event.pos):
                self.value = max(self.min_val, self.value - self.step)
                return True
            if self.plus_btn.collidepoint(event.pos):
                self.value = min(self.max_val, self.value + self.step)
                return True

        return False

    def render(self, surface: pygame.Surface) -> None:
        """Draw the spinner."""
        # Minus button
        minus_color = (
            parse_color(COLORS["button_hover"]) if self.minus_hovered
            else parse_color(COLORS["button_normal"])
        )
        pygame.draw.rect(surface, minus_color, self.minus_btn, border_radius=3)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            self.minus_btn, 1, border_radius=3,
        )
        draw_text_centered(
            surface, "-", self.minus_btn.center,
            parse_color(COLORS["text_primary"]), font_size=16,
        )

        # Plus button
        plus_color = (
            parse_color(COLORS["button_hover"]) if self.plus_hovered
            else parse_color(COLORS["button_normal"])
        )
        pygame.draw.rect(surface, plus_color, self.plus_btn, border_radius=3)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            self.plus_btn, 1, border_radius=3,
        )
        draw_text_centered(
            surface, "+", self.plus_btn.center,
            parse_color(COLORS["text_primary"]), font_size=16,
        )

        # Value text between buttons
        value_x = (self.minus_btn.right + self.plus_btn.left) // 2
        value_y = self.rect.centery
        draw_text_centered(
            surface, str(self.value), (value_x, value_y),
            parse_color(COLORS["text_primary"]), font_size=16,
        )
