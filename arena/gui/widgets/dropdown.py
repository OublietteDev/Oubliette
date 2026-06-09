"""Dropdown selector widget."""

from __future__ import annotations

import pygame

from arena.gui.renderer import draw_text_centered, get_font
from arena.util.constants import COLORS, parse_color


class Dropdown:
    """A dropdown that opens a list of options when clicked."""

    def __init__(
        self,
        rect: pygame.Rect,
        options: list[str],
        selected_index: int = 0,
        max_visible: int = 8,
        disabled: bool = False,
        disabled_text: str = "",
    ) -> None:
        self.rect = rect
        self.options = options
        self.selected_index = selected_index
        self.max_visible = max_visible
        self.disabled = disabled
        self.disabled_text = disabled_text
        self.is_open = False
        self.hovered_index: int | None = None
        self.scroll_offset = 0

    @property
    def value(self) -> str:
        """Get the currently selected option string."""
        if 0 <= self.selected_index < len(self.options):
            return self.options[self.selected_index]
        return ""

    @value.setter
    def value(self, val: str) -> None:
        """Set the selected option by string value."""
        try:
            self.selected_index = self.options.index(val)
        except ValueError:
            pass

    def _get_dropdown_rect(self) -> pygame.Rect:
        """Get the rect for the open dropdown list."""
        item_h = self.rect.height
        visible = min(len(self.options), self.max_visible)
        return pygame.Rect(
            self.rect.x, self.rect.bottom,
            self.rect.width, item_h * visible,
        )

    def _get_item_rect(self, index: int) -> pygame.Rect:
        """Get the rect for a dropdown item (relative to dropdown opening)."""
        item_h = self.rect.height
        visual_index = index - self.scroll_offset
        return pygame.Rect(
            self.rect.x,
            self.rect.bottom + visual_index * item_h,
            self.rect.width,
            item_h,
        )

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Handle an event. Returns True if consumed."""
        if self.disabled:
            return False

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            pos = event.pos
            if self.is_open:
                dd_rect = self._get_dropdown_rect()
                if dd_rect.collidepoint(pos):
                    for i in range(self.scroll_offset,
                                   min(len(self.options),
                                       self.scroll_offset + self.max_visible)):
                        if self._get_item_rect(i).collidepoint(pos):
                            self.selected_index = i
                            self.is_open = False
                            return True
                # Clicked outside dropdown — close it
                self.is_open = False
                return True
            elif self.rect.collidepoint(pos):
                self.is_open = True
                self.scroll_offset = max(
                    0, min(self.selected_index,
                           len(self.options) - self.max_visible),
                )
                return True

        if self.is_open and event.type == pygame.MOUSEMOTION:
            dd_rect = self._get_dropdown_rect()
            if dd_rect.collidepoint(event.pos):
                for i in range(self.scroll_offset,
                               min(len(self.options),
                                   self.scroll_offset + self.max_visible)):
                    if self._get_item_rect(i).collidepoint(event.pos):
                        self.hovered_index = i
                        return True
            self.hovered_index = None
            return True

        if self.is_open and event.type == pygame.MOUSEWHEEL:
            max_offset = max(0, len(self.options) - self.max_visible)
            self.scroll_offset = max(
                0, min(max_offset, self.scroll_offset - event.y),
            )
            return True

        if self.is_open and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.is_open = False
                return True

        return False

    def render(self, surface: pygame.Surface) -> None:
        """Draw the closed dropdown button."""
        if self.disabled:
            # Greyed-out appearance
            pygame.draw.rect(
                surface, parse_color(COLORS["bg_dark"]),
                self.rect, border_radius=3,
            )
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                self.rect, 1, border_radius=3,
            )
            font = get_font(14)
            display = self.disabled_text or self.value or ""
            text_surf = font.render(
                display, True, parse_color(COLORS["text_secondary"]),
            )
            surface.blit(
                text_surf,
                (self.rect.x + 6,
                 self.rect.y + (self.rect.height - text_surf.get_height()) // 2),
            )
            return

        color = (
            parse_color(COLORS["button_active"]) if self.is_open
            else parse_color(COLORS["button_normal"])
        )
        pygame.draw.rect(surface, color, self.rect, border_radius=3)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            self.rect, 1, border_radius=3,
        )

        # Selected value text
        font = get_font(14)
        display = self.value
        # Truncate if too wide
        max_w = self.rect.width - 20
        if font.size(display)[0] > max_w:
            while display and font.size(display + "...")[0] > max_w:
                display = display[:-1]
            display += "..."
        text_surf = font.render(
            display, True, parse_color(COLORS["text_primary"]),
        )
        surface.blit(
            text_surf,
            (self.rect.x + 6,
             self.rect.y + (self.rect.height - text_surf.get_height()) // 2),
        )

        # Arrow indicator
        arrow = get_font(12)
        arrow_surf = arrow.render(
            "v" if not self.is_open else "^", True,
            parse_color(COLORS["text_secondary"]),
        )
        surface.blit(
            arrow_surf,
            (self.rect.right - 14,
             self.rect.y + (self.rect.height - arrow_surf.get_height()) // 2),
        )

    def render_dropdown(self, surface: pygame.Surface) -> None:
        """Draw the open dropdown overlay. Call this LAST in the render pass."""
        if not self.is_open:
            return

        dd_rect = self._get_dropdown_rect()

        # Background
        pygame.draw.rect(
            surface, parse_color(COLORS["bg_dark"]), dd_rect,
        )
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]), dd_rect, 1,
        )

        # Left-side scrollbar (only when content exceeds visible area)
        total = len(self.options)
        has_scrollbar = total > self.max_visible
        bar_w = 5
        bar_margin = 2
        text_indent = (bar_w + bar_margin * 2 + 2) if has_scrollbar else 6

        if has_scrollbar:
            track_x = dd_rect.x + bar_margin
            track_y = dd_rect.y + bar_margin
            track_h = dd_rect.height - bar_margin * 2

            # Track
            pygame.draw.rect(
                surface, parse_color(COLORS.get("bg_medium", "#2a2018")),
                (track_x, track_y, bar_w, track_h),
                border_radius=bar_w // 2,
            )

            # Thumb
            visible = min(total, self.max_visible)
            thumb_ratio = visible / total
            thumb_h = max(12, int(track_h * thumb_ratio))
            max_scroll = total - self.max_visible
            if max_scroll > 0:
                scroll_ratio = self.scroll_offset / max_scroll
            else:
                scroll_ratio = 0.0
            thumb_y = track_y + int((track_h - thumb_h) * scroll_ratio)

            pygame.draw.rect(
                surface, parse_color(COLORS.get("border_accent", "#6b5530")),
                (track_x, thumb_y, bar_w, thumb_h),
                border_radius=bar_w // 2,
            )

        font = get_font(14)
        visible_end = min(len(self.options),
                          self.scroll_offset + self.max_visible)
        for i in range(self.scroll_offset, visible_end):
            item_rect = self._get_item_rect(i)
            # Highlight
            if i == self.hovered_index:
                pygame.draw.rect(
                    surface, parse_color(COLORS["button_hover"]), item_rect,
                )
            elif i == self.selected_index:
                pygame.draw.rect(
                    surface, parse_color(COLORS["button_active"]), item_rect,
                )

            text_surf = font.render(
                self.options[i], True,
                parse_color(COLORS["text_primary"]),
            )
            surface.blit(
                text_surf,
                (item_rect.x + text_indent,
                 item_rect.y + (item_rect.height - text_surf.get_height()) // 2),
            )
