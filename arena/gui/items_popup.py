"""Items list popup for the radial menu's 'Items' group slot.

Displays available consumable/utility actions (potions, scrolls, etc.)
in a rectangular panel adjacent to the radial ring. Follows the same
pattern as CantripPopup and TacticsPopup.
"""

from __future__ import annotations

import pygame

from arena.models.actions import Action, ActionType
from arena.gui.icons import get_icon
from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color


class ItemsPopup:
    """Rectangular popup listing consumable and utility actions."""

    ENTRY_HEIGHT = 28
    WIDTH = 240
    TITLE_HEIGHT = 26
    PADDING = 4

    def __init__(
        self,
        items: list[Action],
        action_used: bool,
        bonus_used: bool,
        screen_width: int = 1280,
        screen_height: int = 720,
    ) -> None:
        self.items = list(items)
        self.action_used = action_used
        self.bonus_used = bonus_used
        self._screen_width = screen_width
        self._screen_height = screen_height

        self.hovered_index: int | None = None
        self._hovered_tooltip_lines: list[str] | None = None

        total_h = (
            self.TITLE_HEIGHT
            + max(len(self.items), 1) * self.ENTRY_HEIGHT
            + self.PADDING * 2
        )
        self.rect = pygame.Rect(0, 0, self.WIDTH, total_h)

    # ── Positioning ──────────────────────────────────────────────────

    def reposition(
        self,
        menu_center: tuple[int, int],
        ring_offset: int,
    ) -> None:
        """Place the popup adjacent to the radial ring."""
        x = menu_center[0] + ring_offset + 12
        y = menu_center[1] - self.rect.height // 2

        if x + self.rect.width > self._screen_width - 4:
            x = menu_center[0] - ring_offset - 12 - self.rect.width

        y = max(4, min(self._screen_height - self.rect.height - 4, y))
        self.rect.topleft = (x, y)

    # ── Event Handling ───────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Handle events for the popup.

        Returns:
            ``"action:<name>"`` or ``"bonus_action:<name>"`` when clicked.
            ``"__close__"`` when the popup should close.
            ``None`` otherwise.
        """
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if not self.rect.collidepoint(event.pos):
                return "__close__"
            idx = self._entry_at(event.pos)
            if idx is not None:
                item = self.items[idx]
                if not self._is_disabled(item):
                    from arena.audio.manager import get_sound_manager
                    get_sound_manager().play_sfx("button_click")
                    if item.action_type == ActionType.BONUS_ACTION:
                        return f"bonus_action:{item.name}"
                    return f"action:{item.name}"

        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "__close__"

        return None

    # ── Rendering ────────────────────────────────────────────────────

    def render(self, surface: pygame.Surface) -> None:
        """Render the popup panel."""
        # Background
        bg = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        bg.fill((35, 28, 20, 235))
        surface.blit(bg, self.rect.topleft)
        pygame.draw.rect(
            surface,
            parse_color(COLORS["border_accent"]),
            self.rect,
            1,
        )

        # Title
        font = get_font(14)
        title_surf = font.render("Items", True, parse_color(COLORS["text_primary"]))
        surface.blit(
            title_surf,
            (self.rect.x + self.PADDING + 2, self.rect.y + self.PADDING),
        )

        # Entries
        entry_font = get_font(13)
        y = self.rect.y + self.TITLE_HEIGHT
        for i, item in enumerate(self.items):
            entry_rect = pygame.Rect(
                self.rect.x + 2,
                y,
                self.rect.width - 4,
                self.ENTRY_HEIGHT,
            )
            disabled = self._is_disabled(item)

            # Hover highlight
            if i == self.hovered_index and not disabled:
                pygame.draw.rect(
                    surface,
                    parse_color(COLORS["hex_hover"]),
                    entry_rect,
                )

            # Icon + Text
            text_x = entry_rect.x + 8
            icon_surf = get_icon(item.name, 18)
            if icon_surf is not None:
                icon_y = entry_rect.y + (self.ENTRY_HEIGHT - 18) // 2
                surface.blit(icon_surf, (entry_rect.x + 6, icon_y))
                text_x = entry_rect.x + 28

            text_color = (
                (100, 100, 100)
                if disabled
                else parse_color(COLORS["text_primary"])
            )
            text_surf = entry_font.render(item.name, True, text_color)
            surface.blit(text_surf, (text_x, entry_rect.y + 5))

            # Uses remaining indicator
            if item.uses_per_rest is not None:
                uses = item.current_uses if item.current_uses is not None else item.uses_per_rest
                uses_text = f"{uses}/{item.uses_per_rest}"
                uses_color = (
                    (100, 100, 100) if disabled
                    else parse_color(COLORS["text_secondary"])
                )
                uses_surf = entry_font.render(uses_text, True, uses_color)
                surface.blit(
                    uses_surf,
                    (entry_rect.right - uses_surf.get_width() - 6, entry_rect.y + 5),
                )

            y += self.ENTRY_HEIGHT

    def render_tooltip(self, surface: pygame.Surface) -> None:
        """Render tooltip for the hovered item entry."""
        if self.hovered_index is None or self._hovered_tooltip_lines is None:
            return

        lines = self._hovered_tooltip_lines
        font = get_font(13)
        padding = 6
        line_height = 17

        max_w = max(font.size(line)[0] for line in lines)
        tw = max_w + padding * 2
        th = len(lines) * line_height + padding * 2

        # Position to the right of the popup
        tx = self.rect.right + 6
        ty = (
            self.rect.y
            + self.TITLE_HEIGHT
            + self.hovered_index * self.ENTRY_HEIGHT
        )

        if tx + tw > self._screen_width - 4:
            tx = self.rect.left - tw - 6

        ty = max(4, min(self._screen_height - th - 4, ty))

        bg = pygame.Surface((tw, th), pygame.SRCALPHA)
        bg.fill((30, 24, 18, 235))
        surface.blit(bg, (tx, ty))
        pygame.draw.rect(
            surface,
            parse_color(COLORS["border_accent"]),
            (tx, ty, tw, th),
            1,
        )

        y = ty + padding
        white = parse_color(COLORS["text_primary"])
        gray = parse_color(COLORS["text_secondary"])
        for i, line in enumerate(lines):
            color = white if i == 0 else gray
            text_surf = font.render(line, True, color)
            surface.blit(text_surf, (tx + padding, y))
            y += line_height

    # ── Helpers ──────────────────────────────────────────────────────

    def _is_disabled(self, item: Action) -> bool:
        """Check if an item action should be grayed out."""
        # Check action economy
        if item.action_type == ActionType.BONUS_ACTION:
            if self.bonus_used:
                return True
        else:
            if self.action_used:
                return True
        # Check uses remaining
        if item.uses_per_rest is not None:
            uses = item.current_uses if item.current_uses is not None else item.uses_per_rest
            if uses <= 0:
                return True
        return False

    def _update_hover(self, pos: tuple[int, int]) -> None:
        """Update hover state."""
        idx = self._entry_at(pos)
        self.hovered_index = idx
        if idx is not None:
            self._hovered_tooltip_lines = self._build_item_tooltip(
                self.items[idx]
            )
        else:
            self._hovered_tooltip_lines = None

    def _entry_at(self, pos: tuple[int, int]) -> int | None:
        """Get the entry index at the given screen position."""
        if not self.rect.collidepoint(pos):
            return None
        rel_y = pos[1] - (self.rect.y + self.TITLE_HEIGHT)
        if rel_y < 0:
            return None
        idx = int(rel_y // self.ENTRY_HEIGHT)
        if 0 <= idx < len(self.items):
            return idx
        return None

    def _build_item_tooltip(self, action: Action) -> list[str]:
        """Build tooltip lines for a consumable/utility action."""
        lines: list[str] = []

        # Action economy tag
        economy = {
            "action": "Action",
            "bonus_action": "Bonus Action",
            "reaction": "Reaction",
        }.get(action.action_type.value, "Action")
        if action.source_item:
            lines.append(f"Item \u2022 {economy}")
        else:
            lines.append(economy)

        # Description
        if action.description:
            desc = action.description
            if len(desc) > 60:
                desc = desc[:57] + "..."
            lines.append(desc)

        # Healing
        if action.healing:
            lines.append(f"Heals {action.healing}")

        # Saving throw
        if action.saving_throw:
            st = action.saving_throw
            dc = st.dc or "?"
            lines.append(f"DC {dc} {st.ability.capitalize()} save")
            if st.damage_on_fail:
                for dr in st.damage_on_fail:
                    lines.append(f"{dr.dice} {dr.damage_type.value} (on fail)")
            if st.damage_on_success and st.damage_on_success != "none":
                lines.append(f"On success: {st.damage_on_success} damage")

        # Conditions
        if action.conditions_applied:
            lines.append(f"Applies: {', '.join(action.conditions_applied)}")
        if action.conditions_removed:
            lines.append(f"Removes: {', '.join(action.conditions_removed)}")

        # Uses
        if action.uses_per_rest is not None:
            uses = action.current_uses if action.current_uses is not None else action.uses_per_rest
            lines.append(f"Uses: {uses}/{action.uses_per_rest}")

        # Target / range
        if action.target_type and action.target_type != "self":
            lines.append(f"Target: {action.target_type}")
        if action.range and action.range > 0:
            lines.append(f"Range: {action.range} ft")

        return lines if lines else [action.name]
