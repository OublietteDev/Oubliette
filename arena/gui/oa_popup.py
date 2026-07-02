"""Opportunity-attack prompt — shown when a player-controlled creature can make
an opportunity attack against an enemy leaving its reach. The player chooses to
spend their reaction (Attack) or not (Skip). AI reactors auto-fire and never
reach this popup.
"""

from __future__ import annotations

import pygame

from arena.gui.popup_base import Popup
from arena.gui.renderer import get_font
from arena.util.constants import COLORS, FONT_SIZES, LAYOUT, parse_color


class OpportunityAttackPopup(Popup):
    """Modal Attack/Skip prompt for a single opportunity attack."""

    WIDTH = 300
    TITLE_HEIGHT = 34
    INFO_HEIGHT = 24
    BTN_HEIGHT = 34
    PADDING = 8

    def __init__(
        self,
        reactor_name: str,
        mover_name: str,
        screen_width: int = LAYOUT["screen_width"],
        screen_height: int = LAYOUT["screen_height"],
    ) -> None:
        super().__init__(screen_width, screen_height)
        self.reactor_name = reactor_name
        self.mover_name = mover_name
        self._hover_attack = False
        self._hover_skip = False
        total_h = (self.TITLE_HEIGHT + self.INFO_HEIGHT + self.BTN_HEIGHT
                   + self.PADDING * 3)
        self.rect = pygame.Rect(0, 0, self.WIDTH, total_h)

    # ── geometry ─────────────────────────────────────────────────────
    def _attack_rect(self) -> pygame.Rect:
        y = self.rect.y + self.TITLE_HEIGHT + self.INFO_HEIGHT + self.PADDING
        w = (self.WIDTH - self.PADDING * 3) // 2
        return pygame.Rect(self.rect.x + self.PADDING, y, w, self.BTN_HEIGHT)

    def _skip_rect(self) -> pygame.Rect:
        a = self._attack_rect()
        return pygame.Rect(a.right + self.PADDING, a.y, a.width, self.BTN_HEIGHT)

    # ── input ────────────────────────────────────────────────────────
    def handle_event(self, event: pygame.event.Event) -> bool | None:
        """Returns True (attack), False (skip), or None (no decision yet)."""
        if event.type == pygame.MOUSEMOTION:
            self._hover_attack = self._attack_rect().collidepoint(event.pos)
            self._hover_skip = self._skip_rect().collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._attack_rect().collidepoint(event.pos):
                return True
            if self._skip_rect().collidepoint(event.pos):
                return False
        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_y):
                return True
            if event.key in (pygame.K_ESCAPE, pygame.K_n):
                return False
        return None

    # ── render ───────────────────────────────────────────────────────
    def render(self, surface: pygame.Surface) -> None:
        self.render_frame(surface, "Opportunity Attack?")

        small = get_font(FONT_SIZES["small"])
        gray = parse_color(COLORS["text_secondary"])
        info = small.render(f"{self.reactor_name} vs fleeing {self.mover_name}",
                            True, gray)
        surface.blit(info, (self.rect.x + (self.WIDTH - info.get_width()) // 2,
                            self.rect.y + self.TITLE_HEIGHT + 4))

        for rect, label, hover in (
            (self._attack_rect(), "Attack", self._hover_attack),
            (self._skip_rect(), "Skip", self._hover_skip),
        ):
            self.draw_button(surface, rect, label, hovered=hover)
