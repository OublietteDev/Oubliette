"""On-hit rider popup — shown after a successful hit to offer rider abilities.

Replaces the hardcoded SmitePopup with a generic popup that handles:
- Spell-slot riders (Divine Smite, Eldritch Smite): level selection
- Flat-cost riders (Stunning Strike): simple Use/Skip
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color
from arena.models.character import Feature, OnHitRider
from arena.combat.riders import get_rider_dice_preview, get_available_spell_slots


@dataclass
class RiderChoice:
    """Result from the rider popup for one rider."""

    feature_name: str
    used: bool  # Player chose to activate
    slot_level: int | None = None  # For spell-slot riders


class RiderPopup:
    """Modal popup for a single on-hit rider.

    For spell-slot riders: shows available slot levels with dice previews.
    For flat-cost riders: shows Use/Skip buttons with cost info.
    """

    WIDTH = 240
    ROW_HEIGHT = 28
    TITLE_HEIGHT = 30
    SKIP_HEIGHT = 32
    PADDING = 6

    def __init__(
        self,
        feature: Feature,
        rider: OnHitRider,
        creature,
        screen_width: int = 1280,
        screen_height: int = 720,
    ) -> None:
        self.feature = feature
        self.rider = rider
        self.creature = creature
        self._screen_width = screen_width
        self._screen_height = screen_height
        self.hovered_index: int | None = None
        self._hovered_skip: bool = False
        self._hovered_use: bool = False

        self.is_spell_slot = rider.resource_type == "spell_slot"

        if self.is_spell_slot:
            # Build slot list like SmitePopup
            all_slots = get_available_spell_slots(creature)
            self.slots: list[tuple[int, int]] = sorted(all_slots.items())
            row_count = max(len(self.slots), 1)
        else:
            self.slots = []
            row_count = 1  # Single "Use" row

        total_h = (
            self.TITLE_HEIGHT
            + row_count * self.ROW_HEIGHT
            + self.SKIP_HEIGHT
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

    def _get_row_rect(self, index: int) -> pygame.Rect:
        y = self.rect.y + self.TITLE_HEIGHT + self.PADDING + index * self.ROW_HEIGHT
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.ROW_HEIGHT,
        )

    def _get_skip_rect(self) -> pygame.Rect:
        row_count = max(len(self.slots), 1) if self.is_spell_slot else 1
        y = (
            self.rect.y + self.TITLE_HEIGHT + self.PADDING
            + row_count * self.ROW_HEIGHT
        )
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.SKIP_HEIGHT,
        )

    def handle_event(self, event: pygame.event.Event) -> RiderChoice | None:
        """Process input. Returns RiderChoice when decided, None to keep open."""
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            self.hovered_index = None
            self._hovered_skip = False
            self._hovered_use = False

            if self.is_spell_slot:
                for i in range(len(self.slots)):
                    if self._get_row_rect(i).collidepoint(mx, my):
                        self.hovered_index = i
                        break
            else:
                if self._get_row_rect(0).collidepoint(mx, my):
                    self._hovered_use = True

            if self._get_skip_rect().collidepoint(mx, my):
                self._hovered_skip = True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            if self.is_spell_slot:
                for i, (level, count) in enumerate(self.slots):
                    if self._get_row_rect(i).collidepoint(mx, my) and count > 0:
                        return RiderChoice(
                            feature_name=self.feature.name,
                            used=True,
                            slot_level=level,
                        )
            else:
                if self._get_row_rect(0).collidepoint(mx, my):
                    return RiderChoice(
                        feature_name=self.feature.name,
                        used=True,
                    )

            if self._get_skip_rect().collidepoint(mx, my):
                return RiderChoice(feature_name=self.feature.name, used=False)

            if not self.rect.collidepoint(mx, my):
                return RiderChoice(feature_name=self.feature.name, used=False)

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return RiderChoice(feature_name=self.feature.name, used=False)

        return None

    def render(self, surface: pygame.Surface) -> None:
        """Render the rider popup."""
        # Background
        bg = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        bg.fill((30, 24, 18, 240))
        surface.blit(bg, self.rect.topleft)
        border_color = parse_color(COLORS["border_accent"])
        pygame.draw.rect(surface, border_color, self.rect, 2)

        font = get_font(13)
        font_small = get_font(11)
        gold = parse_color(COLORS["text_gold"])
        white = parse_color(COLORS["text_primary"])
        gray = parse_color(COLORS["text_secondary"])
        dim = (80, 70, 60)

        # Title
        title = font.render(f"{self.feature.name}?", True, gold)
        tx = self.rect.x + (self.WIDTH - title.get_width()) // 2
        surface.blit(title, (tx, self.rect.y + 8))

        if self.is_spell_slot:
            self._render_spell_slot_rows(surface, font, font_small, white, gray, dim)
        else:
            self._render_flat_cost_row(surface, font, font_small, white, gray)

        # Skip button
        skip_rect = self._get_skip_rect()
        if self._hovered_skip:
            hl = pygame.Surface((skip_rect.width, skip_rect.height), pygame.SRCALPHA)
            hl.fill((80, 70, 50, 80))
            surface.blit(hl, skip_rect.topleft)

        skip_text = font.render("Skip", True, gray)
        sx = skip_rect.x + (skip_rect.width - skip_text.get_width()) // 2
        surface.blit(skip_text, (sx, skip_rect.y + 8))

    def _render_spell_slot_rows(
        self, surface, font, font_small, white, gray, dim,
    ) -> None:
        """Render spell-slot level selection rows."""
        for i, (level, count) in enumerate(self.slots):
            rect = self._get_row_rect(i)
            available = count > 0
            is_hovered = (self.hovered_index == i) and available

            if is_hovered:
                hl = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
                hl.fill((80, 70, 50, 80))
                surface.blit(hl, rect.topleft)

            preview = get_rider_dice_preview(self.rider, level)
            label = f"Level {level}  ({preview})"
            count_text = f"{count} left"

            text_color = white if available else dim
            label_surf = font.render(label, True, text_color)
            count_surf = font_small.render(
                count_text, True, gray if available else dim,
            )

            surface.blit(label_surf, (rect.x + 6, rect.y + 4))
            surface.blit(
                count_surf,
                (rect.right - count_surf.get_width() - 6, rect.y + 7),
            )

    def _render_flat_cost_row(
        self, surface, font, font_small, white, gray,
    ) -> None:
        """Render a single Use button for flat-cost riders."""
        rect = self._get_row_rect(0)

        if self._hovered_use:
            hl = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            hl.fill((80, 70, 50, 80))
            surface.blit(hl, rect.topleft)

        # Build cost description
        rider = self.rider
        cost_parts: list[str] = []
        if rider.resource_type and rider.resource_cost > 0:
            resources = getattr(self.creature, "class_resources", {})
            remaining = resources.get(rider.resource_type, 0)
            res_name = rider.resource_type.replace("_", " ")
            cost_parts.append(f"{rider.resource_cost} {res_name}")
            count_text = f"{remaining} left"
        else:
            count_text = ""

        # Damage preview
        if rider.damage_dice:
            dtype = rider.damage_type
            cost_parts.append(f"{rider.damage_dice} {dtype}")

        label = "Use" + (f"  ({', '.join(cost_parts)})" if cost_parts else "")

        label_surf = font.render(label, True, white)
        surface.blit(label_surf, (rect.x + 6, rect.y + 4))

        if count_text:
            count_surf = font_small.render(count_text, True, gray)
            surface.blit(
                count_surf,
                (rect.right - count_surf.get_width() - 6, rect.y + 7),
            )
