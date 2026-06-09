"""Toggle checkbox widget with label."""

from __future__ import annotations

import pygame

from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color


class Checkbox:
    """A checkbox with a text label."""

    BOX_SIZE = 20

    def __init__(
        self,
        rect: pygame.Rect,
        label: str,
        checked: bool = False,
    ) -> None:
        self.rect = rect
        self.label = label
        self.checked = checked
        self.hovered = False

        # The clickable box portion
        self.box_rect = pygame.Rect(
            rect.x, rect.y + (rect.height - self.BOX_SIZE) // 2,
            self.BOX_SIZE, self.BOX_SIZE,
        )

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Handle an event. Returns True if consumed."""
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
            return False

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.checked = not self.checked
                return True

        return False

    def render(self, surface: pygame.Surface) -> None:
        """Draw the checkbox and label."""
        # Box
        box_color = (
            parse_color(COLORS["button_active"]) if self.checked
            else parse_color(COLORS["bg_dark"])
        )
        pygame.draw.rect(surface, box_color, self.box_rect, border_radius=3)
        border_color = (
            parse_color(COLORS["button_hover"]) if self.hovered
            else parse_color(COLORS["hex_border"])
        )
        pygame.draw.rect(
            surface, border_color, self.box_rect, 1, border_radius=3,
        )

        # Checkmark
        if self.checked:
            cx, cy = self.box_rect.center
            points = [
                (cx - 5, cy),
                (cx - 1, cy + 4),
                (cx + 5, cy - 4),
            ]
            pygame.draw.lines(
                surface, parse_color(COLORS["text_primary"]),
                False, points, 2,
            )

        # Label
        font = get_font(14)
        label_surf = font.render(
            self.label, True, parse_color(COLORS["text_primary"]),
        )
        surface.blit(
            label_surf,
            (self.box_rect.right + 8,
             self.rect.y + (self.rect.height - label_surf.get_height()) // 2),
        )
