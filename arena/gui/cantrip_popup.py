"""Cantrip list popup for the radial menu's 'Cantrips' group slot.

Displays available cantrips in a simple rectangular panel adjacent
to the radial ring.  Similar in structure to TacticsPopup but with
dynamic entries derived from the creature's action list.
"""

from __future__ import annotations

import pygame

from arena.models.actions import Action, ActionType
from arena.gui.icons import get_icon
from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color


class CantripPopup:
    """Rectangular popup listing the creature's cantrips."""

    ENTRY_HEIGHT = 28
    WIDTH = 220
    TITLE_HEIGHT = 26
    PADDING = 4

    def __init__(
        self,
        cantrips: list[Action],
        creature,
        action_used: bool,
        screen_width: int = 1280,
        screen_height: int = 720,
    ) -> None:
        self.creature = creature
        self.cantrips = list(cantrips)
        self.action_used = action_used
        self._screen_width = screen_width
        self._screen_height = screen_height

        self.hovered_index: int | None = None
        self._hovered_tooltip_lines: list[str] | None = None

        total_h = (
            self.TITLE_HEIGHT
            + max(len(self.cantrips), 1) * self.ENTRY_HEIGHT
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
            ``"action:<name>"`` when a cantrip is clicked.
            ``"__close__"`` when the popup should close.
            ``None`` otherwise.
        """
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if not self.rect.collidepoint(event.pos):
                return "__close__"
            idx = self._entry_at(event.pos)
            if idx is not None and not self.action_used:
                from arena.audio.manager import get_sound_manager
                get_sound_manager().play_sfx("button_click")
                return f"action:{self.cantrips[idx].name}"

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
        title_surf = font.render("Cantrips", True, parse_color(COLORS["text_primary"]))
        surface.blit(
            title_surf,
            (self.rect.x + self.PADDING + 2, self.rect.y + self.PADDING),
        )

        # Entries
        entry_font = get_font(13)
        y = self.rect.y + self.TITLE_HEIGHT
        for i, cantrip in enumerate(self.cantrips):
            entry_rect = pygame.Rect(
                self.rect.x + 2,
                y,
                self.rect.width - 4,
                self.ENTRY_HEIGHT,
            )

            # Hover highlight
            if i == self.hovered_index and not self.action_used:
                pygame.draw.rect(
                    surface,
                    parse_color(COLORS["hex_hover"]),
                    entry_rect,
                )

            # Icon + Text
            text_x = entry_rect.x + 8
            icon_surf = get_icon(cantrip.name, 18)
            if icon_surf is not None:
                icon_y = entry_rect.y + (self.ENTRY_HEIGHT - 18) // 2
                surface.blit(icon_surf, (entry_rect.x + 6, icon_y))
                text_x = entry_rect.x + 28

            text_color = (
                (100, 100, 100)
                if self.action_used
                else parse_color(COLORS["text_primary"])
            )
            text_surf = entry_font.render(cantrip.name, True, text_color)
            surface.blit(text_surf, (text_x, entry_rect.y + 5))

            y += self.ENTRY_HEIGHT

    def render_tooltip(self, surface: pygame.Surface) -> None:
        """Render tooltip for the hovered cantrip entry."""
        if self.hovered_index is None or self._hovered_tooltip_lines is None:
            return
        if self.action_used:
            return

        lines = self._hovered_tooltip_lines
        font = get_font(13)
        padding = 6
        line_height = 17

        max_w = max(font.size(line)[0] for line in lines)
        tw = max_w + padding * 2
        th = len(lines) * line_height + padding * 2

        # Position to the right of the popup, aligned with hovered entry
        tx = self.rect.right + 6
        ty = (
            self.rect.y
            + self.TITLE_HEIGHT
            + self.hovered_index * self.ENTRY_HEIGHT
        )

        # Flip left if off right edge
        if tx + tw > self._screen_width - 4:
            tx = self.rect.left - tw - 6

        # Clamp vertical
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

    def _update_hover(self, pos: tuple[int, int]) -> None:
        """Update hover state."""
        idx = self._entry_at(pos)
        self.hovered_index = idx
        if idx is not None:
            self._hovered_tooltip_lines = self._build_cantrip_tooltip(
                self.cantrips[idx]
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
        if 0 <= idx < len(self.cantrips):
            return idx
        return None

    def _build_cantrip_tooltip(self, action: Action) -> list[str]:
        """Build tooltip lines for a cantrip."""
        lines: list[str] = []

        # Type + action economy tag
        economy = {
            "action": "Action",
            "bonus_action": "Bonus Action",
            "reaction": "Reaction",
        }.get(action.action_type.value, "Action")
        lines.append(f"Cantrip \u2022 {economy}")

        # Description
        if action.description:
            desc = action.description
            if len(desc) > 60:
                desc = desc[:57] + "..."
            lines.append(desc)

        # Attack info
        if action.attack:
            atk = action.attack
            ability_mod = self.creature.ability_scores.get_modifier(atk.ability)
            attack_bonus = ability_mod + self.creature.proficiency_bonus
            sign = "+" if attack_bonus >= 0 else ""
            lines.append(f"{sign}{attack_bonus} to hit")

            for dr in atk.damage:
                dmg_str = dr.dice
                total_bonus = dr.bonus
                if dr.ability_modifier:
                    ab_mod = self.creature.ability_scores.get_modifier(
                        dr.ability_modifier
                    )
                    total_bonus += ab_mod
                if total_bonus > 0:
                    dmg_str += f"+{total_bonus}"
                elif total_bonus < 0:
                    dmg_str += str(total_bonus)
                dmg_str += f" {dr.damage_type.value}"
                lines.append(dmg_str)

            # Range/reach
            if atk.attack_type.startswith("ranged"):
                range_str = f"Range: {atk.range_normal or atk.reach} ft"
                if atk.range_long:
                    range_str += f" / {atk.range_long} ft"
                lines.append(range_str)
            else:
                lines.append(f"Reach: {atk.reach} ft")

        # Saving throw info
        if action.saving_throw:
            st = action.saving_throw
            dc = st.dc or "?"
            lines.append(f"DC {dc} {st.ability.capitalize()} save")
            if st.damage_on_fail:
                for dr in st.damage_on_fail:
                    lines.append(f"{dr.dice} {dr.damage_type.value} (on fail)")
            if st.damage_on_success != "none":
                lines.append(f"On success: {st.damage_on_success} damage")

        # Range (for non-attack cantrips)
        if not action.attack and action.range and action.range > 5:
            lines.append(f"Range: {action.range} ft")

        return lines if lines else [action.name]
