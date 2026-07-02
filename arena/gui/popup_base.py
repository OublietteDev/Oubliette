"""Shared base class for the Arena's modal popups.

Every popup in the GUI follows the same skeleton — a fixed-width rect
positioned near a point and clamped to the screen, an alpha-blended dark
background with a 2px accent border, a centered gold title, and a column of
hover-highlighted choice rows. Before this base existed, fifteen popup files
each re-implemented that skeleton with small accidental drifts; the class
below owns the recipe once. Subclasses keep their content rendering and
``handle_event`` contracts (return types deliberately vary per popup).

Metrics default from the shared ``LAYOUT`` scale; palette defaults from
``COLORS``. A popup with its own personality (the legendary popup's purple,
the passenger popup's naval blue) overrides the class attributes rather than
hand-rolling its frame.
"""

from __future__ import annotations

import pygame

from arena.gui.renderer import get_font
from arena.util.constants import (
    COLORS, FONT_SIZES, LAYOUT, POPUP_BG_RGBA, parse_color,
)


class Popup:
    """Base class: geometry, clamping, and the shared frame/button recipes."""

    # Geometry — subclasses override to taste. These defaults mirror the most
    # common values across the existing popups.
    WIDTH: int = 260
    PADDING: int = LAYOUT["popup_padding"]
    TITLE_HEIGHT: int = LAYOUT["popup_title_height"]
    ROW_HEIGHT: int = LAYOUT["popup_row_height"]
    BTN_HEIGHT: int = LAYOUT["popup_button_height"]

    # Palette — RGBA background; None border/title fall back to the house
    # accent and gold. Override for popups with their own identity.
    BG_RGBA: tuple[int, int, int, int] = POPUP_BG_RGBA
    BORDER_RGB: tuple[int, int, int] | None = None
    TITLE_RGB: tuple[int, int, int] | None = None

    def __init__(
        self,
        screen_width: int = LAYOUT["screen_width"],
        screen_height: int = LAYOUT["screen_height"],
    ) -> None:
        self._screen_width = screen_width
        self._screen_height = screen_height
        # Subclasses size the height once their content is known.
        self.rect = pygame.Rect(0, 0, self.WIDTH, 0)

    # ── Positioning ──────────────────────────────────────────────────

    def reposition(self, center: tuple[int, int]) -> None:
        """Center the popup at *center*, clamped to the screen."""
        self.rect.center = center
        self.clamp_to_screen()

    def clamp_to_screen(self) -> None:
        """Keep the popup inside the screen with the standard margin."""
        margin = LAYOUT["popup_margin"]
        if self.rect.left < margin:
            self.rect.left = margin
        if self.rect.right > self._screen_width - margin:
            self.rect.right = self._screen_width - margin
        if self.rect.top < margin:
            self.rect.top = margin
        if self.rect.bottom > self._screen_height - margin:
            self.rect.bottom = self._screen_height - margin

    # ── Frame ────────────────────────────────────────────────────────

    def border_color(self) -> tuple[int, int, int]:
        if self.BORDER_RGB is not None:
            return self.BORDER_RGB
        return parse_color(COLORS["border_accent"])

    def title_color(self) -> tuple[int, int, int]:
        if self.TITLE_RGB is not None:
            return self.TITLE_RGB
        return parse_color(COLORS["text_gold"])

    def render_frame(self, surface: pygame.Surface, title: str | None = None) -> None:
        """Draw the popup's background, border, and (optionally) its title.

        The title is centered near the top edge in the heading face. Content
        rendering stays with the subclass.
        """
        bg = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        bg.fill(self.BG_RGBA)
        surface.blit(bg, self.rect.topleft)
        pygame.draw.rect(
            surface, self.border_color(), self.rect,
            LAYOUT["popup_border_width"],
        )
        if title:
            font = get_font(FONT_SIZES["content"], "heading")
            surf = font.render(title, True, self.title_color())
            surface.blit(
                surf,
                (self.rect.x + (self.rect.width - surf.get_width()) // 2,
                 self.rect.y + 7),
            )

    # ── Shared widgets ───────────────────────────────────────────────

    def draw_hover_highlight(
        self, surface: pygame.Surface, rect: pygame.Rect,
        rgba: tuple[int, int, int, int] = (80, 70, 50, 80),
    ) -> None:
        """The standard warm row-hover wash."""
        hl = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        hl.fill(rgba)
        surface.blit(hl, rect.topleft)

    def draw_button(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        label: str,
        *,
        hovered: bool = False,
        enabled: bool = True,
        font: pygame.font.Font | None = None,
    ) -> None:
        """The standard popup button: filled rect, border, centered label."""
        if not enabled:
            fill = parse_color(COLORS["button_normal"])
            text_rgb = parse_color(COLORS["text_disabled"])
        elif hovered:
            fill = parse_color(COLORS["button_hover"])
            text_rgb = parse_color(COLORS["text_primary"])
        else:
            fill = parse_color(COLORS["button_normal"])
            text_rgb = parse_color(COLORS["text_primary"])
        pygame.draw.rect(surface, fill, rect, border_radius=4)
        pygame.draw.rect(
            surface, self.border_color(), rect, 1, border_radius=4,
        )
        if font is None:
            font = get_font(FONT_SIZES["content"])
        surf = font.render(label, True, text_rgb)
        surface.blit(surf, surf.get_rect(center=rect.center))


def draw_modal_dim(
    surface: pygame.Surface,
    alpha: int = 100,
) -> None:
    """Dim the whole frame under a modal popup.

    Input is already blocked while a popup is open; this makes that state
    VISIBLE, so the grid behind a popup no longer looks interactive.
    """
    dim = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    dim.fill((12, 9, 6, alpha))
    surface.blit(dim, (0, 0))
