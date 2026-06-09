"""Scrollable list with Add/Remove buttons and optional predefined choices."""

from __future__ import annotations

import pygame

from arena.gui.renderer import draw_text_centered, get_font
from arena.util.constants import COLORS, parse_color


class ListEditor:
    """A list of string items with [+ Add] and [x] remove per item.

    When *allowed_values* is provided, the Add button opens a small
    dropdown picker showing only values that are not already present,
    preventing duplicates.  When *allowed_values* is ``None`` the
    widget falls back to the legacy behaviour of appending
    *default_value* on each click.
    """

    def __init__(
        self,
        rect: pygame.Rect,
        items: list[str] | None = None,
        item_height: int = 28,
        gap: int = 2,
        default_value: str = "",
        allowed_values: list[str] | None = None,
    ) -> None:
        self.rect = rect
        self.items: list[str] = items if items is not None else []
        self.item_height = item_height
        self.gap = gap
        self.default_value = default_value
        self.allowed_values = allowed_values
        self.selected_index: int | None = None
        self.scroll_offset = 0

        # Values excluded by sibling lists (cross-list exclusion).
        # When set, these values are removed from the picker options
        # in addition to the list's own items.
        self.excluded_values: set[str] = set()

        # Add button at the top of the list
        self.add_btn = pygame.Rect(
            rect.right - 60, rect.y, 56, 22,
        )
        self.add_hovered = False

        # Content starts below the add button
        self.content_y = rect.y + 26

        # --- Picker dropdown state (when allowed_values is set) ---
        self._picker_open = False
        self._picker_options: list[str] = []
        self._picker_rects: list[pygame.Rect] = []
        self._picker_hovered: int | None = None
        self._picker_scroll: int = 0
        self._picker_max_visible: int = 6

    def update_subrects(self) -> None:
        """Recompute add button and content_y from current self.rect."""
        self.add_btn = pygame.Rect(
            self.rect.right - 60, self.rect.y, 56, 22,
        )
        self.content_y = self.rect.y + 26

    @property
    def is_picker_open(self) -> bool:
        """Whether the add-value picker dropdown is currently open."""
        return self._picker_open

    # -----------------------------------------------------------------
    # Geometry helpers
    # -----------------------------------------------------------------

    def _get_item_rect(self, index: int) -> pygame.Rect:
        """Get the rect for an item at the given index."""
        y = self.content_y + index * (self.item_height + self.gap) - self.scroll_offset
        return pygame.Rect(self.rect.x, y, self.rect.width, self.item_height)

    def _get_remove_rect(self, item_rect: pygame.Rect) -> pygame.Rect:
        """Get the [x] remove button rect for an item."""
        size = min(20, self.item_height - 4)
        return pygame.Rect(
            item_rect.right - size - 4,
            item_rect.y + (self.item_height - size) // 2,
            size, size,
        )

    def _build_picker(self) -> None:
        """Compute available options and dropdown geometry."""
        if self.allowed_values is None:
            return
        current = set(self.items)
        unavailable = current | self.excluded_values
        self._picker_options = [v for v in self.allowed_values if v not in unavailable]
        self._picker_scroll = 0
        self._picker_hovered = None
        self._rebuild_picker_rects()

    def _rebuild_picker_rects(self) -> None:
        """Rebuild picker item rects from current scroll state."""
        item_h = 24
        visible = min(len(self._picker_options), self._picker_max_visible)
        self._picker_rects = []
        base_x = self.add_btn.x
        base_y = self.add_btn.bottom + 2
        for vi in range(visible):
            idx = self._picker_scroll + vi
            if idx >= len(self._picker_options):
                break
            self._picker_rects.append(
                pygame.Rect(base_x, base_y + vi * item_h, self.add_btn.width + 60, item_h)
            )

    def _get_picker_area(self) -> pygame.Rect:
        """Bounding rect of the entire picker dropdown."""
        if not self._picker_rects:
            return pygame.Rect(0, 0, 0, 0)
        first = self._picker_rects[0]
        last = self._picker_rects[-1]
        return pygame.Rect(first.x, first.y, first.width, last.bottom - first.y)

    # -----------------------------------------------------------------
    # Event handling
    # -----------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Handle an event. Returns True if consumed."""

        # --- Picker interactions (highest priority when open) ---
        if self._picker_open:
            if event.type == pygame.MOUSEMOTION:
                self._picker_hovered = None
                for vi, pr in enumerate(self._picker_rects):
                    if pr.collidepoint(event.pos):
                        self._picker_hovered = self._picker_scroll + vi
                        break
                return True

            if event.type == pygame.MOUSEWHEEL:
                picker_area = self._get_picker_area()
                if picker_area.collidepoint(pygame.mouse.get_pos()):
                    max_off = max(0, len(self._picker_options) - self._picker_max_visible)
                    self._picker_scroll = max(
                        0, min(max_off, self._picker_scroll - event.y),
                    )
                    self._rebuild_picker_rects()
                    return True

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                # Check if an option was clicked
                for vi, pr in enumerate(self._picker_rects):
                    if pr.collidepoint(event.pos):
                        idx = self._picker_scroll + vi
                        if 0 <= idx < len(self._picker_options):
                            chosen = self._picker_options[idx]
                            self.items.append(chosen)
                            self.selected_index = len(self.items) - 1
                        self._picker_open = False
                        return True
                # Clicked outside the picker — close it
                self._picker_open = False
                return True

            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._picker_open = False
                return True

            return False

        # --- Normal widget interactions ---
        if event.type == pygame.MOUSEMOTION:
            self.add_hovered = self.add_btn.collidepoint(event.pos)
            return False

        if event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                max_scroll = max(
                    0,
                    len(self.items) * (self.item_height + self.gap)
                    - (self.rect.height - 26),
                )
                self.scroll_offset = max(
                    0, min(max_scroll, self.scroll_offset - event.y * 20),
                )
                return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            pos = event.pos

            # Add button
            if self.add_btn.collidepoint(pos):
                if self.allowed_values is not None:
                    # Open picker with remaining options
                    self._build_picker()
                    if self._picker_options:
                        self._picker_open = True
                    # If no options left, silently ignore (all added)
                else:
                    # Legacy free-text behaviour
                    self.items.append(self.default_value)
                    self.selected_index = len(self.items) - 1
                return True

            # Item clicks
            for i in range(len(self.items)):
                item_rect = self._get_item_rect(i)
                if item_rect.collidepoint(pos):
                    # Check remove button
                    remove_rect = self._get_remove_rect(item_rect)
                    if remove_rect.collidepoint(pos):
                        self.items.pop(i)
                        if self.selected_index is not None:
                            if self.selected_index == i:
                                self.selected_index = None
                            elif self.selected_index > i:
                                self.selected_index -= 1
                        return True
                    # Select item
                    self.selected_index = i
                    return True

        return False

    # -----------------------------------------------------------------
    # Rendering
    # -----------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        """Draw the list editor."""
        font = get_font(13)

        # Add button — grey out when no options remain
        all_used = False
        if self.allowed_values is not None:
            unavailable = set(self.items) | self.excluded_values
            all_used = all(v in unavailable for v in self.allowed_values)
        if all_used:
            add_color = parse_color(COLORS["bg_dark"])
            add_text_color = parse_color(COLORS["text_secondary"])
        elif self.add_hovered:
            add_color = parse_color(COLORS["button_hover"])
            add_text_color = parse_color(COLORS["text_primary"])
        else:
            add_color = parse_color(COLORS["button_normal"])
            add_text_color = parse_color(COLORS["text_primary"])

        pygame.draw.rect(surface, add_color, self.add_btn, border_radius=3)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            self.add_btn, 1, border_radius=3,
        )
        draw_text_centered(
            surface, "+ Add", self.add_btn.center,
            add_text_color, font_size=12,
        )

        # Clip to list area
        list_area = pygame.Rect(
            self.rect.x, self.content_y,
            self.rect.width, self.rect.bottom - self.content_y,
        )
        old_clip = surface.get_clip()
        surface.set_clip(list_area)

        # Items
        for i, item_text in enumerate(self.items):
            item_rect = self._get_item_rect(i)

            # Skip if outside visible area
            if item_rect.bottom < self.content_y or item_rect.top > self.rect.bottom:
                continue

            # Background
            selected = i == self.selected_index
            bg = (
                parse_color(COLORS["button_active"]) if selected
                else parse_color(COLORS["button_normal"])
            )
            pygame.draw.rect(surface, bg, item_rect, border_radius=3)
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                item_rect, 1, border_radius=3,
            )

            # Item text
            display = item_text or "(empty)"
            text_surf = font.render(
                display, True, parse_color(COLORS["text_primary"]),
            )
            clip = pygame.Rect(0, 0, item_rect.width - 30, self.item_height)
            surface.blit(text_surf, (item_rect.x + 6, item_rect.y + 5), clip)

            # Remove button [x]
            remove_rect = self._get_remove_rect(item_rect)
            draw_text_centered(
                surface, "x", remove_rect.center,
                parse_color(COLORS["text_secondary"]), font_size=12,
            )

        # Empty state
        if not self.items:
            empty_surf = font.render(
                "(none)", True, parse_color(COLORS["text_secondary"]),
            )
            surface.blit(empty_surf, (self.rect.x + 6, self.content_y + 4))

        # Left-side scrollbar (only when content exceeds visible area)
        total_content_h = len(self.items) * (self.item_height + self.gap)
        visible_h = self.rect.bottom - self.content_y
        if total_content_h > visible_h:
            bar_w = 5
            bar_margin = 2
            track_x = list_area.x + bar_margin
            track_y = list_area.y + bar_margin
            track_h = visible_h - bar_margin * 2

            # Track
            track_color = parse_color(COLORS.get("bg_medium", "#2a2018"))
            pygame.draw.rect(
                surface, track_color,
                (track_x, track_y, bar_w, track_h),
                border_radius=bar_w // 2,
            )

            # Thumb
            thumb_ratio = visible_h / total_content_h
            thumb_h = max(12, int(track_h * thumb_ratio))
            max_scroll = total_content_h - visible_h
            if max_scroll > 0:
                scroll_ratio = self.scroll_offset / max_scroll
            else:
                scroll_ratio = 0.0
            thumb_y = track_y + int((track_h - thumb_h) * scroll_ratio)

            thumb_color = parse_color(COLORS.get("border_accent", "#6b5530"))
            pygame.draw.rect(
                surface, thumb_color,
                (track_x, thumb_y, bar_w, thumb_h),
                border_radius=bar_w // 2,
            )

        surface.set_clip(old_clip)

    def render_overlay(self, surface: pygame.Surface) -> None:
        """Draw the picker dropdown overlay. Call LAST in the render pass."""
        if not self._picker_open or not self._picker_rects:
            return

        font = get_font(13)
        area = self._get_picker_area()

        # Background
        pygame.draw.rect(surface, parse_color(COLORS["bg_dark"]), area)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]), area, 1,
        )

        # Left-side scrollbar (only when content exceeds visible slots)
        total = len(self._picker_options)
        has_scrollbar = total > self._picker_max_visible
        bar_w = 5
        bar_margin = 2
        text_indent = (bar_w + bar_margin * 2 + 2) if has_scrollbar else 6

        if has_scrollbar:
            track_x = area.x + bar_margin
            track_y = area.y + bar_margin
            track_h = area.height - bar_margin * 2

            # Track
            track_color = parse_color(COLORS.get("bg_medium", "#2a2018"))
            pygame.draw.rect(
                surface, track_color,
                (track_x, track_y, bar_w, track_h),
                border_radius=bar_w // 2,
            )

            # Thumb
            visible = min(total, self._picker_max_visible)
            thumb_ratio = visible / total
            thumb_h = max(12, int(track_h * thumb_ratio))
            max_scroll = total - self._picker_max_visible
            if max_scroll > 0:
                scroll_ratio = self._picker_scroll / max_scroll
            else:
                scroll_ratio = 0.0
            thumb_y = track_y + int((track_h - thumb_h) * scroll_ratio)

            thumb_color = parse_color(COLORS.get("border_accent", "#6b5530"))
            pygame.draw.rect(
                surface, thumb_color,
                (track_x, thumb_y, bar_w, thumb_h),
                border_radius=bar_w // 2,
            )

        for vi, pr in enumerate(self._picker_rects):
            idx = self._picker_scroll + vi
            if idx >= len(self._picker_options):
                break

            # Hover highlight
            if idx == self._picker_hovered:
                pygame.draw.rect(
                    surface, parse_color(COLORS["button_hover"]), pr,
                )

            text_surf = font.render(
                self._picker_options[idx], True,
                parse_color(COLORS["text_primary"]),
            )
            surface.blit(
                text_surf,
                (pr.x + text_indent, pr.y + (pr.height - text_surf.get_height()) // 2),
            )
