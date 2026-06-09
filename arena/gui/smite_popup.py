"""Divine Smite popup — shown after a successful melee hit to offer smiting."""

from __future__ import annotations

import pygame

from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color


class SmitePopup:
    """Modal popup asking the player whether to use Divine Smite.

    Displays available spell slot levels with remaining counts.
    Exhausted slots are shown grayed out. Player can pick a level
    or skip. Returns the chosen spell slot level (int) or None.
    """

    WIDTH = 220
    ROW_HEIGHT = 28
    TITLE_HEIGHT = 30
    SKIP_HEIGHT = 32
    PADDING = 6

    def __init__(
        self,
        spell_slots: dict[int, int],
        screen_width: int = 1280,
        screen_height: int = 720,
    ) -> None:
        """
        Args:
            spell_slots: Mapping of spell slot level -> remaining count.
                Only levels present in the dict are shown (up to 9).
        """
        # Sort by level, filter to levels 1-9
        self.slots: list[tuple[int, int]] = sorted(
            (lvl, count) for lvl, count in spell_slots.items()
            if 1 <= lvl <= 9
        )
        self._screen_width = screen_width
        self._screen_height = screen_height
        self.hovered_index: int | None = None  # Index into self.slots
        self._hovered_skip: bool = False

        total_h = (
            self.TITLE_HEIGHT
            + max(len(self.slots), 1) * self.ROW_HEIGHT
            + self.SKIP_HEIGHT
            + self.PADDING * 2
        )
        self.rect = pygame.Rect(0, 0, self.WIDTH, total_h)

    def reposition(self, center: tuple[int, int]) -> None:
        """Center the popup at the given screen position."""
        self.rect.center = center
        # Clamp to screen
        if self.rect.left < 4:
            self.rect.left = 4
        if self.rect.right > self._screen_width - 4:
            self.rect.right = self._screen_width - 4
        if self.rect.top < 4:
            self.rect.top = 4
        if self.rect.bottom > self._screen_height - 4:
            self.rect.bottom = self._screen_height - 4

    def _get_slot_rect(self, index: int) -> pygame.Rect:
        """Get the clickable rect for a spell slot row."""
        y = self.rect.y + self.TITLE_HEIGHT + self.PADDING + index * self.ROW_HEIGHT
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.ROW_HEIGHT,
        )

    def _get_skip_rect(self) -> pygame.Rect:
        """Get the clickable rect for the Skip button."""
        y = (
            self.rect.y + self.TITLE_HEIGHT + self.PADDING
            + len(self.slots) * self.ROW_HEIGHT
        )
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.SKIP_HEIGHT,
        )

    def _smite_dice_count(self, slot_level: int) -> int:
        """Number of d8 radiant dice for a given slot level.

        Per 5e: 2d8 for 1st level, +1d8 per level above 1st, max 5d8.
        """
        return min(1 + slot_level, 5)

    def handle_event(self, event: pygame.event.Event) -> int | None | str:
        """Process input. Returns:

        - int: chosen spell slot level (1-9)
        - "__skip__": player declined to smite
        - None: no decision yet (keep popup open)
        """
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            self.hovered_index = None
            self._hovered_skip = False
            for i in range(len(self.slots)):
                if self._get_slot_rect(i).collidepoint(mx, my):
                    self.hovered_index = i
                    break
            if self._get_skip_rect().collidepoint(mx, my):
                self._hovered_skip = True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            # Check slot clicks
            for i, (level, count) in enumerate(self.slots):
                if self._get_slot_rect(i).collidepoint(mx, my) and count > 0:
                    return level
            # Check skip
            if self._get_skip_rect().collidepoint(mx, my):
                return "__skip__"
            # Click outside popup = skip
            if not self.rect.collidepoint(mx, my):
                return "__skip__"

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "__skip__"

        return None

    def render(self, surface: pygame.Surface) -> None:
        """Render the smite popup."""
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
        title = font.render("Divine Smite?", True, gold)
        tx = self.rect.x + (self.WIDTH - title.get_width()) // 2
        surface.blit(title, (tx, self.rect.y + 8))

        # Slot rows
        for i, (level, count) in enumerate(self.slots):
            rect = self._get_slot_rect(i)
            available = count > 0
            is_hovered = (self.hovered_index == i) and available

            # Hover highlight
            if is_hovered:
                hl = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
                hl.fill((80, 70, 50, 80))
                surface.blit(hl, rect.topleft)

            dice_count = self._smite_dice_count(level)
            label = f"Level {level}  ({dice_count}d8 radiant)"
            count_text = f"{count} left"

            text_color = white if available else dim
            label_surf = font.render(label, True, text_color)
            count_surf = font_small.render(count_text, True, gray if available else dim)

            surface.blit(label_surf, (rect.x + 6, rect.y + 4))
            surface.blit(count_surf, (rect.right - count_surf.get_width() - 6, rect.y + 7))

        # Skip button
        skip_rect = self._get_skip_rect()
        if self._hovered_skip:
            hl = pygame.Surface((skip_rect.width, skip_rect.height), pygame.SRCALPHA)
            hl.fill((80, 70, 50, 80))
            surface.blit(hl, skip_rect.topleft)

        skip_text = font.render("Skip", True, gray)
        sx = skip_rect.x + (skip_rect.width - skip_text.get_width()) // 2
        surface.blit(skip_text, (sx, skip_rect.y + 8))
