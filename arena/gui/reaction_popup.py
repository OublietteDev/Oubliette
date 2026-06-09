"""Damage reduction reaction popup -- shown when a player-controlled creature
is hit and has a reaction feature that can reduce incoming damage.

Supports Parry, Uncanny Dodge, Deflect Missiles, and similar features.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color


@dataclass
class ReactionChoice:
    """Result from the reaction popup."""

    feature_name: str | None  # None means the player skipped
    used: bool


class ReactionPopup:
    """Modal popup offering a damage reduction reaction.

    Shows the feature name, reduction preview, and Use/Skip buttons.
    Styled to match RiderPopup (same colours, fonts, sizing pattern).
    """

    WIDTH = 260
    ROW_HEIGHT = 32
    TITLE_HEIGHT = 36
    INFO_HEIGHT = 22
    SKIP_HEIGHT = 32
    PADDING = 6

    def __init__(
        self,
        target_name: str,
        options: list[tuple],
        screen_width: int = 1280,
        screen_height: int = 720,
    ) -> None:
        """
        Args:
            target_name: Display name of the creature being hit.
            options: List of (Feature, reduction_amount) tuples from
                ``check_damage_reduction_reaction``.  reduction_amount is
                -1 for Uncanny Dodge (halving).
            screen_width: Viewport width for clamping.
            screen_height: Viewport height for clamping.
        """
        self.target_name = target_name
        self.options = options
        self._screen_width = screen_width
        self._screen_height = screen_height
        self.hovered_index: int | None = None
        self._hovered_skip: bool = False

        row_count = max(len(options), 1)
        total_h = (
            self.TITLE_HEIGHT
            + self.INFO_HEIGHT
            + row_count * self.ROW_HEIGHT
            + self.SKIP_HEIGHT
            + self.PADDING * 2
        )
        self.rect = pygame.Rect(0, 0, self.WIDTH, total_h)

    def reposition(self, center: tuple[int, int]) -> None:
        """Centre the popup at the given screen position."""
        self.rect.center = center
        if self.rect.left < 4:
            self.rect.left = 4
        if self.rect.right > self._screen_width - 4:
            self.rect.right = self._screen_width - 4
        if self.rect.top < 4:
            self.rect.top = 4
        if self.rect.bottom > self._screen_height - 4:
            self.rect.bottom = self._screen_height - 4

    # ── geometry helpers ─────────────────────────────────────────────

    def _get_row_rect(self, index: int) -> pygame.Rect:
        y = (
            self.rect.y
            + self.TITLE_HEIGHT
            + self.INFO_HEIGHT
            + self.PADDING
            + index * self.ROW_HEIGHT
        )
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.ROW_HEIGHT,
        )

    def _get_skip_rect(self) -> pygame.Rect:
        row_count = max(len(self.options), 1)
        y = (
            self.rect.y
            + self.TITLE_HEIGHT
            + self.INFO_HEIGHT
            + self.PADDING
            + row_count * self.ROW_HEIGHT
        )
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.SKIP_HEIGHT,
        )

    # ── event handling ───────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> ReactionChoice | None:
        """Process input.  Returns ``ReactionChoice`` when decided."""
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            self.hovered_index = None
            self._hovered_skip = False

            for i in range(len(self.options)):
                if self._get_row_rect(i).collidepoint(mx, my):
                    self.hovered_index = i
                    break

            if self._get_skip_rect().collidepoint(mx, my):
                self._hovered_skip = True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            for i, (feature, _reduction) in enumerate(self.options):
                if self._get_row_rect(i).collidepoint(mx, my):
                    return ReactionChoice(
                        feature_name=feature.name, used=True,
                    )

            if self._get_skip_rect().collidepoint(mx, my):
                return ReactionChoice(feature_name=None, used=False)

            # Click outside => skip
            if not self.rect.collidepoint(mx, my):
                return ReactionChoice(feature_name=None, used=False)

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return ReactionChoice(feature_name=None, used=False)

        return None

    # ── rendering ────────────────────────────────────────────────────

    def render(self, surface: pygame.Surface) -> None:
        """Render the reaction popup."""
        # Background
        bg = pygame.Surface(
            (self.rect.width, self.rect.height), pygame.SRCALPHA,
        )
        bg.fill((30, 24, 18, 240))
        surface.blit(bg, self.rect.topleft)
        border_color = parse_color(COLORS["border_accent"])
        pygame.draw.rect(surface, border_color, self.rect, 2)

        font = get_font(13)
        font_small = get_font(11)
        gold = parse_color(COLORS["text_gold"])
        white = parse_color(COLORS["text_primary"])
        gray = parse_color(COLORS["text_secondary"])

        # Title
        title = font.render("Use Reaction?", True, gold)
        tx = self.rect.x + (self.WIDTH - title.get_width()) // 2
        surface.blit(title, (tx, self.rect.y + 8))

        # Info line
        info = font_small.render(
            f"{self.target_name} was hit!", True, gray,
        )
        ix = self.rect.x + (self.WIDTH - info.get_width()) // 2
        surface.blit(info, (ix, self.rect.y + self.TITLE_HEIGHT + 2))

        # Option rows
        for i, (feature, reduction) in enumerate(self.options):
            rect = self._get_row_rect(i)
            is_hovered = self.hovered_index == i

            if is_hovered:
                hl = pygame.Surface(
                    (rect.width, rect.height), pygame.SRCALPHA,
                )
                hl.fill((80, 70, 50, 80))
                surface.blit(hl, rect.topleft)

            if reduction == -1:
                desc = "halve damage"
            else:
                desc = f"reduce by {reduction}"

            label = f"{feature.name}  ({desc})"
            label_surf = font.render(label, True, white)
            surface.blit(label_surf, (rect.x + 6, rect.y + 7))

        # Skip button
        skip_rect = self._get_skip_rect()
        if self._hovered_skip:
            hl = pygame.Surface(
                (skip_rect.width, skip_rect.height), pygame.SRCALPHA,
            )
            hl.fill((80, 70, 50, 80))
            surface.blit(hl, skip_rect.topleft)

        skip_text = font.render("Skip", True, gray)
        sx = skip_rect.x + (skip_rect.width - skip_text.get_width()) // 2
        surface.blit(skip_text, (sx, skip_rect.y + 8))
