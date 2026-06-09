"""Click-to-focus text input field with blinking cursor."""

from __future__ import annotations

import pygame

from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color


class TextInput:
    """A single-line text input field."""

    def __init__(
        self,
        rect: pygame.Rect,
        value: str = "",
        max_length: int = 40,
        placeholder: str = "",
        font_size: int = 16,
    ) -> None:
        self.rect = rect
        self.value = value
        self.max_length = max_length
        self.placeholder = placeholder
        self.font_size = font_size
        self.active = False

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Handle an event. Returns True if the event was consumed."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            was_active = self.active
            self.active = self.rect.collidepoint(event.pos)
            return self.active or was_active

        if self.active and event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_TAB):
                self.active = False
            elif event.key == pygame.K_ESCAPE:
                self.active = False
            elif event.key == pygame.K_BACKSPACE:
                self.value = self.value[:-1]
            else:
                ch = event.unicode
                if ch and ch.isprintable() and len(self.value) < self.max_length:
                    self.value += ch
            return True

        return False

    def render(self, surface: pygame.Surface) -> None:
        """Draw the text input field."""
        # Background
        pygame.draw.rect(
            surface, parse_color(COLORS["bg_dark"]),
            self.rect, border_radius=3,
        )

        # Border
        border_color = (
            parse_color(COLORS["button_active"]) if self.active
            else parse_color(COLORS["hex_border"])
        )
        pygame.draw.rect(surface, border_color, self.rect, 1, border_radius=3)

        # Text
        font = get_font(self.font_size)
        if self.value:
            text_surf = font.render(
                self.value, True, parse_color(COLORS["text_primary"]),
            )
        elif self.placeholder and not self.active:
            text_surf = font.render(
                self.placeholder, True, parse_color(COLORS["text_secondary"]),
            )
        else:
            text_surf = None

        if text_surf is not None:
            clip = pygame.Rect(0, 0, self.rect.width - 8, self.rect.height - 4)
            surface.blit(
                text_surf,
                (self.rect.x + 4, self.rect.y + (self.rect.height - text_surf.get_height()) // 2),
                clip,
            )

        # Blinking cursor
        if self.active and (pygame.time.get_ticks() // 500) % 2 == 0:
            text_w = font.size(self.value)[0] if self.value else 0
            cursor_x = min(self.rect.x + 4 + text_w, self.rect.right - 4)
            pad = 4
            pygame.draw.line(
                surface, parse_color(COLORS["text_primary"]),
                (cursor_x, self.rect.y + pad),
                (cursor_x, self.rect.bottom - pad),
            )
