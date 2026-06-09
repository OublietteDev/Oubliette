"""Ability Scores tab — 2x3 grid of score cards with +/- and modifier display."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from arena.gui.renderer import draw_text_centered, get_font
from arena.gui.widgets import NumberSpinner
from arena.util.constants import COLORS, parse_color

if TYPE_CHECKING:
    from arena.gui.screens.character_builder import CreatureBuilderScreen

ABILITIES = [
    ("strength", "STR"),
    ("dexterity", "DEX"),
    ("constitution", "CON"),
    ("intelligence", "INT"),
    ("wisdom", "WIS"),
    ("charisma", "CHA"),
]

STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]


class AbilitiesTab:
    """Renders and handles the Ability Scores tab."""

    def __init__(self, screen: CreatureBuilderScreen) -> None:
        self.screen = screen
        ox, oy = screen.get_content_origin()

        # Card layout: 2 columns x 3 rows
        card_w = 200
        card_h = 100
        col_gap = 40
        row_gap = 20

        self.spinners: dict[str, NumberSpinner] = {}
        self.card_rects: dict[str, pygame.Rect] = {}

        for i, (ability, _label) in enumerate(ABILITIES):
            col = i % 2
            row = i // 2
            cx = ox + col * (card_w + col_gap)
            cy = oy + 30 + row * (card_h + row_gap)

            self.card_rects[ability] = pygame.Rect(cx, cy, card_w, card_h)
            self.spinners[ability] = NumberSpinner(
                pygame.Rect(cx + 30, cy + 35, 140, 28),
                value=screen.form_data[ability],
                min_val=1, max_val=30,
            )

        # Standard Array button
        btn_y = oy + 30 + 3 * (card_h + row_gap) + 10
        self.std_array_btn = pygame.Rect(ox, btn_y, 200, 32)
        self.std_array_hovered = False

    def has_open_dropdown(self) -> bool:
        return False

    def handle_escape(self) -> bool:
        return False

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEMOTION:
            self.std_array_hovered = self.std_array_btn.collidepoint(event.pos)

        for ability, spinner in self.spinners.items():
            if spinner.handle_event(event):
                self.screen.form_data[ability] = spinner.value
                return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.std_array_btn.collidepoint(event.pos):
                self._apply_standard_array()
                return True

        return False

    def _apply_standard_array(self) -> None:
        """Fill abilities with the standard array values."""
        for i, (ability, _) in enumerate(ABILITIES):
            self.screen.form_data[ability] = STANDARD_ARRAY[i]
            self.spinners[ability].value = STANDARD_ARRAY[i]
        self.screen.status_message = "Applied standard array (15, 14, 13, 12, 10, 8)"
        self.screen.status_timer = 150

    def render(self, surface: pygame.Surface) -> None:
        ox, oy = self.screen.get_content_origin()
        label_color = parse_color(COLORS["text_secondary"])
        font = get_font(14)

        # Section header
        header = get_font(18)
        header_surf = header.render(
            "Ability Scores", True,
            parse_color(COLORS["text_gold"]),
        )
        surface.blit(header_surf, (ox, oy + 2))

        for ability, short_label in ABILITIES:
            card_rect = self.card_rects[ability]
            spinner = self.spinners[ability]

            # Card background
            pygame.draw.rect(
                surface, parse_color(COLORS["bg_dark"]),
                card_rect, border_radius=6,
            )
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                card_rect, 1, border_radius=6,
            )

            # Ability name
            draw_text_centered(
                surface, short_label,
                (card_rect.centerx, card_rect.y + 16),
                parse_color(COLORS["text_primary"]), font_size=16,
            )

            # Spinner
            spinner.render(surface)

            # Modifier
            score = spinner.value
            mod = (score - 10) // 2
            mod_str = f"+{mod}" if mod >= 0 else str(mod)
            mod_color = (
                parse_color(COLORS["hp_full"]) if mod > 0
                else parse_color(COLORS["hp_critical"]) if mod < 0
                else parse_color(COLORS["text_secondary"])
            )
            draw_text_centered(
                surface, f"({mod_str})",
                (card_rect.centerx, card_rect.bottom - 16),
                mod_color, font_size=16,
            )

        # Standard Array button
        btn_color = (
            parse_color(COLORS["button_hover"]) if self.std_array_hovered
            else parse_color(COLORS["button_normal"])
        )
        pygame.draw.rect(surface, btn_color, self.std_array_btn, border_radius=4)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            self.std_array_btn, 1, border_radius=4,
        )
        draw_text_centered(
            surface, "Standard Array",
            self.std_array_btn.center,
            parse_color(COLORS["text_primary"]), font_size=14,
        )

    def render_overlays(self, surface: pygame.Surface) -> None:
        pass
