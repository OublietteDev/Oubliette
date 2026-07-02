"""Forced save reroll popup -- shown when a player creature fails a save
and has Indomitable, Lucky, or Diamond Soul available.

Displays:
- The failed save info (ability, roll, DC)
- Available reroll features with resource cost
- Use / Skip buttons
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from arena.gui.popup_base import Popup
from arena.gui.renderer import get_font
from arena.util.constants import COLORS, FONT_SIZES, LAYOUT, parse_color
from arena.models.character import Feature


@dataclass
class RerollChoice:
    """Result from the reroll popup."""

    feature_name: str | None  # None = skip reroll
    used: bool  # True if player chose to reroll


class RerollPopup(Popup):
    """Modal popup offering a forced save reroll.

    For single-feature creatures: shows Use/Skip.
    For multi-feature creatures: shows one button per feature + Skip.
    """

    WIDTH = 280
    ROW_HEIGHT = 30
    TITLE_HEIGHT = 44
    SKIP_HEIGHT = 32
    PADDING = 8

    def __init__(
        self,
        creature_name: str,
        save_ability: str,
        original_roll: int,
        save_dc: int,
        features: list[Feature],
        creature,
        screen_width: int = LAYOUT["screen_width"],
        screen_height: int = LAYOUT["screen_height"],
    ) -> None:
        super().__init__(screen_width, screen_height)
        self.creature_name = creature_name
        self.save_ability = save_ability
        self.original_roll = original_roll
        self.save_dc = save_dc
        self.features = features
        self.creature = creature
        self.hovered_index: int | None = None
        self._hovered_skip: bool = False

        row_count = max(len(features), 1)
        total_h = (
            self.TITLE_HEIGHT
            + row_count * self.ROW_HEIGHT
            + self.SKIP_HEIGHT
            + self.PADDING * 2
        )
        self.rect = pygame.Rect(0, 0, self.WIDTH, total_h)

    def _get_row_rect(self, index: int) -> pygame.Rect:
        y = (
            self.rect.y + self.TITLE_HEIGHT + self.PADDING
            + index * self.ROW_HEIGHT
        )
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.ROW_HEIGHT,
        )

    def _get_skip_rect(self) -> pygame.Rect:
        row_count = max(len(self.features), 1)
        y = (
            self.rect.y + self.TITLE_HEIGHT + self.PADDING
            + row_count * self.ROW_HEIGHT
        )
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.SKIP_HEIGHT,
        )

    def handle_event(self, event: pygame.event.Event) -> RerollChoice | None:
        """Process input. Returns RerollChoice when decided, None to keep open."""
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            self.hovered_index = None
            self._hovered_skip = False

            for i in range(len(self.features)):
                if self._get_row_rect(i).collidepoint(mx, my):
                    self.hovered_index = i
                    break

            if self._get_skip_rect().collidepoint(mx, my):
                self._hovered_skip = True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            for i, feat in enumerate(self.features):
                if self._get_row_rect(i).collidepoint(mx, my):
                    return RerollChoice(
                        feature_name=feat.name,
                        used=True,
                    )

            if self._get_skip_rect().collidepoint(mx, my):
                return RerollChoice(feature_name=None, used=False)

            # Click outside popup = skip
            if not self.rect.collidepoint(mx, my):
                return RerollChoice(feature_name=None, used=False)

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return RerollChoice(feature_name=None, used=False)

        return None

    def render(self, surface: pygame.Surface) -> None:
        """Render the reroll popup."""
        # Title: "Reroll WIS save?"
        self.render_frame(
            surface, f"Reroll {self.save_ability[:3].upper()} save?",
        )

        font = get_font(FONT_SIZES["content"])
        font_small = get_font(FONT_SIZES["small"])
        white = parse_color(COLORS["text_primary"])
        gray = parse_color(COLORS["text_secondary"])
        red = (200, 80, 80)

        # Subtitle: "Rolled 8, need 15"
        subtitle = font_small.render(
            f"Rolled {self.original_roll}, need {self.save_dc}",
            True, red,
        )
        sx = self.rect.x + (self.WIDTH - subtitle.get_width()) // 2
        surface.blit(subtitle, (sx, self.rect.y + 24))

        # Feature rows
        for i, feat in enumerate(self.features):
            rect = self._get_row_rect(i)
            is_hovered = self.hovered_index == i

            if is_hovered:
                self.draw_hover_highlight(surface, rect)

            # Label: feature name
            label = font.render(f"Use {feat.name}", True, white)
            surface.blit(label, (rect.x + 6, rect.y + 5))

            # Cost info on right side
            cost_text = self._get_cost_text(feat)
            if cost_text:
                cost_surf = font_small.render(cost_text, True, gray)
                surface.blit(
                    cost_surf,
                    (rect.right - cost_surf.get_width() - 6, rect.y + 7),
                )

        # Skip button
        skip_rect = self._get_skip_rect()
        if self._hovered_skip:
            self.draw_hover_highlight(surface, skip_rect)

        skip_text = font.render("Skip", True, gray)
        sx = skip_rect.x + (skip_rect.width - skip_text.get_width()) // 2
        surface.blit(skip_text, (sx, skip_rect.y + 8))

    def _get_cost_text(self, feature: Feature) -> str:
        """Build cost description for a reroll feature."""
        if feature.forced_reroll_resource is None:
            return ""
        resources = getattr(self.creature, "class_resources", {})
        remaining = resources.get(feature.forced_reroll_resource, 0)
        res_name = feature.forced_reroll_resource.replace("_", " ")
        return f"{feature.forced_reroll_resource_cost} {res_name} ({remaining} left)"
