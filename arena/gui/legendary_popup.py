"""Legendary Action popup — shown at end of another creature's turn.

Lets the player choose a legendary action to use or pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color

if TYPE_CHECKING:
    from arena.models.actions import Action


class LegendaryActionPopup:
    """Modal popup for choosing a legendary action.

    Displays the creature name, remaining legendary action points,
    and available actions (those whose cost <= remaining points).
    Exhausted actions are not shown.  Player picks an action or passes.

    Returns:
    - Action: the chosen legendary action (caller must handle targeting)
    - "__pass__": player declined to use a legendary action
    - None: no decision yet
    """

    WIDTH = 300
    ROW_HEIGHT = 36
    TITLE_HEIGHT = 50
    PASS_HEIGHT = 32
    PADDING = 6

    def __init__(
        self,
        creature_name: str,
        remaining_points: int,
        available_actions: list[Action],
        screen_width: int = 1280,
        screen_height: int = 720,
    ) -> None:
        self.creature_name = creature_name
        self.remaining_points = remaining_points
        self.actions = available_actions
        self._screen_width = screen_width
        self._screen_height = screen_height
        self.hovered_index: int | None = None
        self._hovered_pass: bool = False

        total_h = (
            self.TITLE_HEIGHT
            + max(len(self.actions), 1) * self.ROW_HEIGHT
            + self.PASS_HEIGHT
            + self.PADDING * 2
        )
        self.rect = pygame.Rect(0, 0, self.WIDTH, total_h)

    def reposition(self, center: tuple[int, int]) -> None:
        """Center the popup at the given screen position."""
        self.rect.center = center
        if self.rect.left < 4:
            self.rect.left = 4
        if self.rect.right > self._screen_width - 4:
            self.rect.right = self._screen_width - 4
        if self.rect.top < 4:
            self.rect.top = 4
        if self.rect.bottom > self._screen_height - 4:
            self.rect.bottom = self._screen_height - 4

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
        - Action: chosen legendary action
        - "__pass__": player declined
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
        """Render the legendary action popup."""
        # Background
        bg = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        bg.fill((25, 18, 35, 240))  # Dark purple tint
        surface.blit(bg, self.rect.topleft)

        # Purple border for legendary
        border_color = (180, 120, 255)
        pygame.draw.rect(surface, border_color, self.rect, 2)

        font = get_font(13)
        font_small = get_font(11)
        purple = (200, 150, 255)
        white = parse_color(COLORS["text_primary"])
        gray = parse_color(COLORS["text_secondary"])
        gold = parse_color(COLORS["text_gold"])

        # Title: creature name
        title = font.render(f"Legendary Action", True, purple)
        tx = self.rect.x + (self.WIDTH - title.get_width()) // 2
        surface.blit(title, (tx, self.rect.y + 6))

        # Subtitle: remaining points
        sub = font_small.render(
            f"{self.creature_name} — {self.remaining_points} point"
            f"{'s' if self.remaining_points != 1 else ''} remaining",
            True, gray,
        )
        sx = self.rect.x + (self.WIDTH - sub.get_width()) // 2
        surface.blit(sub, (sx, self.rect.y + 26))

        # Action rows
        for i, action in enumerate(self.actions):
            rect = self._get_action_rect(i)
            is_hovered = self.hovered_index == i

            if is_hovered:
                hl = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
                hl.fill((80, 60, 100, 80))
                surface.blit(hl, rect.topleft)

            cost = action.legendary_action_cost
            label = f"{action.name}"
            cost_text = f"({cost} pt{'s' if cost != 1 else ''})"

            label_surf = font.render(label, True, white)
            cost_surf = font_small.render(cost_text, True, gold)

            surface.blit(label_surf, (rect.x + 6, rect.y + 4))
            surface.blit(cost_surf, (rect.x + 6 + label_surf.get_width() + 8, rect.y + 6))

            # Brief description on second line if space allows
            if action.description:
                desc = action.description[:40]
                if len(action.description) > 40:
                    desc += "..."
                desc_surf = font_small.render(desc, True, gray)
                surface.blit(desc_surf, (rect.x + 6, rect.y + 20))

        # Pass button
        pass_rect = self._get_pass_rect()
        if self._hovered_pass:
            hl = pygame.Surface((pass_rect.width, pass_rect.height), pygame.SRCALPHA)
            hl.fill((80, 60, 100, 80))
            surface.blit(hl, pass_rect.topleft)

        pass_text = font.render("Pass", True, gray)
        px = pass_rect.x + (pass_rect.width - pass_text.get_width()) // 2
        surface.blit(pass_text, (px, pass_rect.y + 8))
