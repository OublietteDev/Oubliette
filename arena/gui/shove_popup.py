"""Shove choice popup — shown after clicking an adjacent enemy via Shove.

Offers two choices: Push 5ft or Knock Prone.
"""

from __future__ import annotations

import pygame

from arena.gui.popup_base import Popup
from arena.gui.renderer import get_font
from arena.util.constants import COLORS, FONT_SIZES, LAYOUT, parse_color


class ShoveChoicePopup(Popup):
    """Modal popup for the Shove action: Push 5ft or Knock Prone."""

    WIDTH = 200
    ROW_HEIGHT = 32
    TITLE_HEIGHT = 30
    PADDING = 6

    _CHOICES = [
        ("push", "Push 5ft"),
        ("prone", "Knock Prone"),
    ]

    def __init__(
        self,
        target_name: str,
        screen_width: int = LAYOUT["screen_width"],
        screen_height: int = LAYOUT["screen_height"],
    ) -> None:
        super().__init__(screen_width, screen_height)
        self.target_name = target_name
        self.hovered_index: int | None = None

        total_h = (
            self.TITLE_HEIGHT
            + len(self._CHOICES) * self.ROW_HEIGHT
            + self.PADDING * 2
        )
        self.rect = pygame.Rect(0, 0, self.WIDTH, total_h)

    def _get_choice_rect(self, index: int) -> pygame.Rect:
        y = self.rect.y + self.TITLE_HEIGHT + self.PADDING + index * self.ROW_HEIGHT
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.ROW_HEIGHT,
        )

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Process input.

        Returns:
            "push" or "prone" when a choice is made.
            "__close__" to cancel.
            None if no decision yet.
        """
        if event.type == pygame.MOUSEMOTION:
            self.hovered_index = None
            for i in range(len(self._CHOICES)):
                if self._get_choice_rect(i).collidepoint(event.pos):
                    self.hovered_index = i
                    break

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, (key, _label) in enumerate(self._CHOICES):
                if self._get_choice_rect(i).collidepoint(event.pos):
                    from arena.audio.manager import get_sound_manager
                    get_sound_manager().play_sfx("button_click")
                    return key
            # Click outside = cancel
            if not self.rect.collidepoint(event.pos):
                return "__close__"

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "__close__"

        return None

    def render(self, surface: pygame.Surface) -> None:
        """Render the shove choice popup."""
        self.render_frame(surface, f"Shove {self.target_name}?")

        font = get_font(FONT_SIZES["content"])
        white = parse_color(COLORS["text_primary"])

        # Choice rows
        for i, (_key, label) in enumerate(self._CHOICES):
            rect = self._get_choice_rect(i)
            is_hovered = self.hovered_index == i

            if is_hovered:
                self.draw_hover_highlight(surface, rect)

            label_surf = font.render(label, True, white)
            lx = rect.x + (rect.width - label_surf.get_width()) // 2
            surface.blit(label_surf, (lx, rect.y + 8))
