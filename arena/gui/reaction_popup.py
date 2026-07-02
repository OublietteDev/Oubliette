"""Damage reduction reaction popup -- shown when a player-controlled creature
is hit and has a reaction feature that can reduce incoming damage.

Supports Parry, Uncanny Dodge, Deflect Missiles, and similar features.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from arena.gui.popup_base import Popup
from arena.gui.renderer import get_font
from arena.util.constants import COLORS, FONT_SIZES, LAYOUT, parse_color


@dataclass
class ReactionChoice:
    """Result from the reaction popup."""

    feature_name: str | None  # None means the player skipped
    used: bool


class ReactionPopup(Popup):
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
        screen_width: int = LAYOUT["screen_width"],
        screen_height: int = LAYOUT["screen_height"],
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
        super().__init__(screen_width, screen_height)
        self.target_name = target_name
        self.options = options
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
        self.render_frame(surface, "Use Reaction?")

        font = get_font(FONT_SIZES["content"])
        font_small = get_font(FONT_SIZES["small"])
        white = parse_color(COLORS["text_primary"])
        gray = parse_color(COLORS["text_secondary"])

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
                self.draw_hover_highlight(surface, rect)

            if reduction == -1:
                desc = "halve damage"
            elif reduction == -2:
                # AC-reaction spell (Shield): show the AC bump instead
                bonus = next(
                    (m.value for m in getattr(feature, "buff_effects", [])
                     if getattr(m, "stat", "") == "ac"
                     and isinstance(m.value, int)),
                    5,
                )
                desc = f"+{bonus} AC vs this attack"
            else:
                desc = f"reduce by {reduction}"

            label = f"{feature.name}  ({desc})"
            label_surf = font.render(label, True, white)
            surface.blit(label_surf, (rect.x + 6, rect.y + 7))

        # Skip button
        skip_rect = self._get_skip_rect()
        if self._hovered_skip:
            self.draw_hover_highlight(surface, skip_rect)

        skip_text = font.render("Skip", True, gray)
        sx = skip_rect.x + (skip_rect.width - skip_text.get_width()) // 2
        surface.blit(skip_text, (sx, skip_rect.y + 8))
