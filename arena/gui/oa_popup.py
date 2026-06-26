"""Opportunity-attack prompt — shown when a player-controlled creature can make
an opportunity attack against an enemy leaving its reach. The player chooses to
spend their reaction (Attack) or not (Skip). AI reactors auto-fire and never
reach this popup.
"""

from __future__ import annotations

import pygame

from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color


class OpportunityAttackPopup:
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
        screen_width: int = 1280,
        screen_height: int = 720,
    ) -> None:
        self.reactor_name = reactor_name
        self.mover_name = mover_name
        self._screen_width = screen_width
        self._screen_height = screen_height
        self._hover_attack = False
        self._hover_skip = False
        total_h = (self.TITLE_HEIGHT + self.INFO_HEIGHT + self.BTN_HEIGHT
                   + self.PADDING * 3)
        self.rect = pygame.Rect(0, 0, self.WIDTH, total_h)

    def reposition(self, center: tuple[int, int]) -> None:
        self.rect.center = center
        self.rect.left = max(4, self.rect.left)
        self.rect.top = max(4, self.rect.top)
        self.rect.right = min(self._screen_width - 4, self.rect.right)
        self.rect.bottom = min(self._screen_height - 4, self.rect.bottom)

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
        bg = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        bg.fill((30, 24, 18, 240))
        surface.blit(bg, self.rect.topleft)
        pygame.draw.rect(surface, parse_color(COLORS["border_accent"]), self.rect, 2)

        font = get_font(13)
        small = get_font(11)
        gold = parse_color(COLORS["text_gold"])
        white = parse_color(COLORS["text_primary"])
        gray = parse_color(COLORS["text_secondary"])

        title = font.render("Opportunity Attack?", True, gold)
        surface.blit(title, (self.rect.x + (self.WIDTH - title.get_width()) // 2,
                             self.rect.y + 8))
        info = small.render(f"{self.reactor_name} vs fleeing {self.mover_name}",
                            True, gray)
        surface.blit(info, (self.rect.x + (self.WIDTH - info.get_width()) // 2,
                            self.rect.y + self.TITLE_HEIGHT + 4))

        for rect, label, hover in (
            (self._attack_rect(), "Attack", self._hover_attack),
            (self._skip_rect(), "Skip", self._hover_skip),
        ):
            if hover:
                hl = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
                hl.fill((80, 70, 50, 90))
                surface.blit(hl, rect.topleft)
            pygame.draw.rect(surface, parse_color(COLORS["border_accent"]), rect, 1)
            txt = font.render(label, True, white)
            surface.blit(txt, (rect.x + (rect.width - txt.get_width()) // 2,
                               rect.y + 8))
