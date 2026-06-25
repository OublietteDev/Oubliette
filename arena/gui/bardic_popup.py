"""Bardic Inspiration spend popup -- shown when a player-controlled attacker
misses but holds a banked Bardic Inspiration die that could flip the miss to a
hit. Offers Spend / Skip (so the limited die can be saved for a bigger moment).

Mirrors the reroll/reaction popup pattern: presentation-only, returns a choice;
the combat manager owns the pause/resume via ``_pending_bardic_choice``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color


@dataclass
class BardicChoice:
    """Result from the bardic popup."""

    use: bool  # True = spend the die, False = skip


class BardicInspirationPopup:
    """Modal popup offering to spend a Bardic Inspiration die on a missed attack."""

    WIDTH = 280
    ROW_HEIGHT = 30
    TITLE_HEIGHT = 44
    SKIP_HEIGHT = 32
    PADDING = 8

    def __init__(
        self,
        attacker_name: str,
        die_size: int,
        total_roll: int,
        target_ac: int,
        screen_width: int = 1280,
        screen_height: int = 720,
    ) -> None:
        self.attacker_name = attacker_name
        self.die_size = die_size
        self.total_roll = total_roll
        self.target_ac = target_ac
        self._screen_width = screen_width
        self._screen_height = screen_height
        self._hovered_use = False
        self._hovered_skip = False

        total_h = (
            self.TITLE_HEIGHT + self.ROW_HEIGHT + self.SKIP_HEIGHT + self.PADDING * 2
        )
        self.rect = pygame.Rect(0, 0, self.WIDTH, total_h)

    def reposition(self, center: tuple[int, int]) -> None:
        self.rect.center = center
        if self.rect.left < 4:
            self.rect.left = 4
        if self.rect.right > self._screen_width - 4:
            self.rect.right = self._screen_width - 4
        if self.rect.top < 4:
            self.rect.top = 4
        if self.rect.bottom > self._screen_height - 4:
            self.rect.bottom = self._screen_height - 4

    def _get_use_rect(self) -> pygame.Rect:
        y = self.rect.y + self.TITLE_HEIGHT + self.PADDING
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.ROW_HEIGHT,
        )

    def _get_skip_rect(self) -> pygame.Rect:
        y = self.rect.y + self.TITLE_HEIGHT + self.PADDING + self.ROW_HEIGHT
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.SKIP_HEIGHT,
        )

    def handle_event(self, event: pygame.event.Event) -> BardicChoice | None:
        """Process input. Returns BardicChoice when decided, None to keep open."""
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            self._hovered_use = self._get_use_rect().collidepoint(mx, my)
            self._hovered_skip = self._get_skip_rect().collidepoint(mx, my)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if self._get_use_rect().collidepoint(mx, my):
                return BardicChoice(use=True)
            if self._get_skip_rect().collidepoint(mx, my):
                return BardicChoice(use=False)
            if not self.rect.collidepoint(mx, my):
                return BardicChoice(use=False)  # click outside = skip

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return BardicChoice(use=False)

        return None

    def render(self, surface: pygame.Surface) -> None:
        bg = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        bg.fill((30, 24, 18, 240))
        surface.blit(bg, self.rect.topleft)
        pygame.draw.rect(surface, parse_color(COLORS["border_accent"]), self.rect, 2)

        font = get_font(13)
        font_small = get_font(11)
        gold = parse_color(COLORS["text_gold"])
        white = parse_color(COLORS["text_primary"])
        gray = parse_color(COLORS["text_secondary"])

        # Title
        title = font.render("Bardic Inspiration?", True, gold)
        surface.blit(title, (self.rect.x + (self.WIDTH - title.get_width()) // 2,
                             self.rect.y + 6))
        # Subtitle: "Rolled 14, need 16"
        sub = font_small.render(
            f"Rolled {self.total_roll}, need {self.target_ac}", True, gray)
        surface.blit(sub, (self.rect.x + (self.WIDTH - sub.get_width()) // 2,
                           self.rect.y + 24))

        # Use row
        use_rect = self._get_use_rect()
        if self._hovered_use:
            hl = pygame.Surface((use_rect.width, use_rect.height), pygame.SRCALPHA)
            hl.fill((80, 70, 50, 80))
            surface.blit(hl, use_rect.topleft)
        label = font.render(f"Spend d{self.die_size} die", True, white)
        surface.blit(label, (use_rect.x + 6, use_rect.y + 5))

        # Skip row
        skip_rect = self._get_skip_rect()
        if self._hovered_skip:
            hl = pygame.Surface((skip_rect.width, skip_rect.height), pygame.SRCALPHA)
            hl.fill((80, 70, 50, 80))
            surface.blit(hl, skip_rect.topleft)
        skip_text = font.render("Save it (Skip)", True, gray)
        surface.blit(skip_text,
                     (skip_rect.x + (skip_rect.width - skip_text.get_width()) // 2,
                      skip_rect.y + 8))
