"""Lair Action popup — shown when the lair turn arrives in initiative.

Lets the DM choose a lair action to use or pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from arena.gui.popup_base import Popup
from arena.gui.renderer import get_font
from arena.util.constants import COLORS, FONT_SIZES, LAYOUT, parse_color

if TYPE_CHECKING:
    from arena.models.actions import Action


class LairActionPopup(Popup):
    """Modal popup for choosing a lair action during combat.

    Displays available lair actions (those not used last round).
    DM picks an action or passes.

    Returns:
    - Action: the chosen lair action
    - "__pass__": DM declined
    - None: no decision yet
    """

    WIDTH = 320
    ROW_HEIGHT = 36
    TITLE_HEIGHT = 50
    PASS_HEIGHT = 32
    PADDING = 6

    # Lair identity — dark gold tint with a gold border; title keeps the
    # default gold.
    BG_RGBA = (35, 28, 15, 240)
    BORDER_RGB = (200, 170, 50)

    def __init__(
        self,
        available_actions: list[Action],
        screen_width: int = LAYOUT["screen_width"],
        screen_height: int = LAYOUT["screen_height"],
    ) -> None:
        super().__init__(screen_width, screen_height)
        self.actions = available_actions
        self.hovered_index: int | None = None
        self._hovered_pass: bool = False

        total_h = (
            self.TITLE_HEIGHT
            + max(len(self.actions), 1) * self.ROW_HEIGHT
            + self.PASS_HEIGHT
            + self.PADDING * 2
        )
        self.rect = pygame.Rect(0, 0, self.WIDTH, total_h)

    def _get_action_rect(self, index: int) -> pygame.Rect:
        """Get the clickable rect for an action row."""
        y = self.rect.y + self.TITLE_HEIGHT + self.PADDING + index * self.ROW_HEIGHT
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.ROW_HEIGHT,
        )

    def _get_pass_rect(self) -> pygame.Rect:
        """Get the clickable rect for the Pass button."""
        y = (
            self.rect.y + self.TITLE_HEIGHT + self.PADDING
            + len(self.actions) * self.ROW_HEIGHT
        )
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.PASS_HEIGHT,
        )

    def handle_event(self, event: pygame.event.Event) -> Action | str | None:
        """Process input.

        Returns:
        - Action: chosen lair action
        - "__pass__": DM declined
        - None: no decision yet
        """
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            self.hovered_index = None
            self._hovered_pass = False
            for i in range(len(self.actions)):
                if self._get_action_rect(i).collidepoint(mx, my):
                    self.hovered_index = i
                    break
            if self._get_pass_rect().collidepoint(mx, my):
                self._hovered_pass = True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            for i, action in enumerate(self.actions):
                if self._get_action_rect(i).collidepoint(mx, my):
                    return action
            if self._get_pass_rect().collidepoint(mx, my):
                return "__pass__"
            # Click outside popup = pass
            if not self.rect.collidepoint(mx, my):
                return "__pass__"

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "__pass__"

        return None

    def render(self, surface: pygame.Surface) -> None:
        """Render the lair action popup."""
        self.render_frame(surface, "Lair Action")

        font = get_font(FONT_SIZES["content"])
        font_small = get_font(FONT_SIZES["small"])
        white = parse_color(COLORS["text_primary"])
        gray = parse_color(COLORS["text_secondary"])

        # Subtitle
        sub = font_small.render(
            "Choose an action for the lair", True, gray,
        )
        sx = self.rect.x + (self.WIDTH - sub.get_width()) // 2
        surface.blit(sub, (sx, self.rect.y + 26))

        # Action rows
        for i, action in enumerate(self.actions):
            rect = self._get_action_rect(i)
            if self.hovered_index == i:
                self.draw_hover_highlight(surface, rect, (100, 80, 30, 80))

            label_surf = font.render(action.name, True, white)
            surface.blit(label_surf, (rect.x + 6, rect.y + 4))

            # Brief description on second line
            if action.description:
                desc = action.description[:45]
                if len(action.description) > 45:
                    desc += "..."
                desc_surf = font_small.render(desc, True, gray)
                surface.blit(desc_surf, (rect.x + 6, rect.y + 20))

        # Pass button
        pass_rect = self._get_pass_rect()
        if self._hovered_pass:
            self.draw_hover_highlight(surface, pass_rect, (100, 80, 30, 80))

        pass_text = font.render("Pass", True, gray)
        px = pass_rect.x + (pass_rect.width - pass_text.get_width()) // 2
        surface.blit(pass_text, (px, pass_rect.y + 8))
