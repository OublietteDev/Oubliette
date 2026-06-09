"""Counterspell reaction popup — shown when an enemy casts a spell.

Offers player-controlled creatures the option to use their reaction
to cast Counterspell at various spell slot levels, or skip.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color


@dataclass
class CounterspellChoice:
    """Result from the counterspell popup."""

    counterspeller_id: str | None  # None = skip
    cast_level: int | None = None  # Spell slot level used


class CounterspellPopup:
    """Modal popup for counterspell reaction.

    Shows the spell being cast and available counterspell slot levels.
    If the counterspeller has multiple slot levels, shows each as a row.
    Always includes a Skip button.
    """

    WIDTH = 260
    ROW_HEIGHT = 28
    TITLE_HEIGHT = 40
    SKIP_HEIGHT = 32
    PADDING = 6

    def __init__(
        self,
        spell_name: str,
        spell_level: int,
        counterspeller_name: str,
        counterspeller_id: str,
        available_slots: dict[int, int],  # level -> count
        screen_width: int = 1280,
        screen_height: int = 720,
    ) -> None:
        self.spell_name = spell_name
        self.spell_level = spell_level
        self.counterspeller_name = counterspeller_name
        self.counterspeller_id = counterspeller_id
        self.available_slots = available_slots
        self._screen_width = screen_width
        self._screen_height = screen_height
        self.hovered_index: int | None = None
        self._hovered_skip: bool = False

        # Build slot rows: (level, count, label)
        self.slot_rows: list[tuple[int, int, str]] = []
        for lvl in sorted(available_slots.keys()):
            count = available_slots[lvl]
            if count <= 0:
                continue
            auto = "auto" if lvl >= spell_level else "check"
            label = f"Lvl {lvl} ({count} left) [{auto}]"
            self.slot_rows.append((lvl, count, label))

        row_count = max(len(self.slot_rows), 1)
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

    def _get_slot_rect(self, index: int) -> pygame.Rect:
        y = self.rect.y + self.TITLE_HEIGHT + self.PADDING + index * self.ROW_HEIGHT
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.ROW_HEIGHT,
        )

    def _get_skip_rect(self) -> pygame.Rect:
        y = (
            self.rect.y + self.TITLE_HEIGHT + self.PADDING
            + len(self.slot_rows) * self.ROW_HEIGHT
        )
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.SKIP_HEIGHT,
        )

    def handle_event(self, event: pygame.event.Event) -> CounterspellChoice | None:
        """Process input.

        Returns:
            CounterspellChoice when a decision is made, None otherwise.
        """
        if event.type == pygame.MOUSEMOTION:
            self.hovered_index = None
            self._hovered_skip = False
            for i in range(len(self.slot_rows)):
                if self._get_slot_rect(i).collidepoint(event.pos):
                    self.hovered_index = i
                    break
            if self._get_skip_rect().collidepoint(event.pos):
                self._hovered_skip = True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, (lvl, _count, _label) in enumerate(self.slot_rows):
                if self._get_slot_rect(i).collidepoint(event.pos):
                    from arena.audio.manager import get_sound_manager
                    get_sound_manager().play_sfx("button_click")
                    return CounterspellChoice(
                        counterspeller_id=self.counterspeller_id,
                        cast_level=lvl,
                    )
            if self._get_skip_rect().collidepoint(event.pos):
                from arena.audio.manager import get_sound_manager
                get_sound_manager().play_sfx("button_click")
                return CounterspellChoice(counterspeller_id=None)

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return CounterspellChoice(counterspeller_id=None)

        return None

    def render(self, surface: pygame.Surface) -> None:
        """Render the counterspell popup."""
        # Background
        bg = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        bg.fill((20, 18, 40, 240))
        surface.blit(bg, self.rect.topleft)
        border_color = (120, 80, 200)  # Purple for counterspell
        pygame.draw.rect(surface, border_color, self.rect, 2)

        font = get_font(12)
        title_font = get_font(13)
        gold = parse_color(COLORS["text_gold"])
        white = parse_color(COLORS["text_primary"])
        dim = (160, 160, 160)

        # Title: "Counterspell [Fireball] (Lvl 3)?"
        title_text = f"Counter {self.spell_name} (Lvl {self.spell_level})?"
        title_surf = title_font.render(title_text, True, gold)
        tx = self.rect.x + (self.WIDTH - title_surf.get_width()) // 2
        surface.blit(title_surf, (tx, self.rect.y + 6))

        # Subtitle: counterspeller name
        sub_text = f"{self.counterspeller_name}'s reaction"
        sub_surf = font.render(sub_text, True, dim)
        sx = self.rect.x + (self.WIDTH - sub_surf.get_width()) // 2
        surface.blit(sub_surf, (sx, self.rect.y + 24))

        # Slot rows
        for i, (lvl, _count, label) in enumerate(self.slot_rows):
            rect = self._get_slot_rect(i)
            is_hovered = self.hovered_index == i

            if is_hovered:
                hl = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
                hl.fill((80, 60, 120, 80))
                surface.blit(hl, rect.topleft)

            label_surf = font.render(label, True, white)
            lx = rect.x + (rect.width - label_surf.get_width()) // 2
            surface.blit(label_surf, (lx, rect.y + 7))

        # Skip button
        skip_rect = self._get_skip_rect()
        if self._hovered_skip:
            hl = pygame.Surface((skip_rect.width, skip_rect.height), pygame.SRCALPHA)
            hl.fill((60, 40, 40, 80))
            surface.blit(hl, skip_rect.topleft)

        skip_surf = font.render("Skip", True, dim)
        sx = skip_rect.x + (skip_rect.width - skip_surf.get_width()) // 2
        surface.blit(skip_surf, (sx, skip_rect.y + 9))
