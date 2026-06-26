"""Tactics popup for the radial menu's 'Tactics' group slot.

Displays Dash, Disengage, Dodge, and Hide as a small rectangular panel
adjacent to the radial ring.
"""

from __future__ import annotations

import pygame

from arena.gui.icons import get_icon
from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color


# Entry definitions
_TACTICS = [
    ("Dash", "Double your movement this turn"),
    ("Disengage", "Move without provoking opportunity attacks"),
    ("Dodge", "Attacks against you have disadvantage"),
    ("Help", "Give an adjacent ally advantage on their next attack"),
    ("Hide", "Attempt to become hidden from enemies"),
    ("Shove", "Push a creature 5ft or knock it prone"),
]

# Shown only while grappled (C5): the escape check is its own action.
_ESCAPE_ENTRY = ("Escape", "Athletics/Acrobatics check to escape the grapple")

# Shown only while prone (C5): standing up is movement, not an action, so it
# stays available even after the creature has spent its action this turn.
_STAND_ENTRY = ("Stand Up", "Spend half your speed to rise from prone")

# Shown only when an adjacent ally is dying (C6): a DC 10 Medicine check to
# stabilize them (your action).
_STABILIZE_ENTRY = ("Stabilize", "DC 10 Medicine check to stabilize a dying ally")

# Entries that cost only movement (never the action slot) — clickable even
# when the action has already been used.
_MOVEMENT_ENTRIES = {"stand up"}


class TacticsPopup:
    """Rectangular popup listing the standard tactical actions."""

    ENTRY_HEIGHT = 28
    WIDTH = 210
    TITLE_HEIGHT = 26
    PADDING = 4

    def __init__(
        self,
        action_used: bool,
        screen_width: int = 1280,
        screen_height: int = 720,
        grappled: bool = False,
        prone: bool = False,
        can_stabilize: bool = False,
    ) -> None:
        self.action_used = action_used
        self._screen_width = screen_width
        self._screen_height = screen_height
        self._entries = list(_TACTICS)
        if grappled:
            self._entries.append(_ESCAPE_ENTRY)
        if prone:
            self._entries.append(_STAND_ENTRY)
        if can_stabilize:
            self._entries.append(_STABILIZE_ENTRY)

        self.hovered_index: int | None = None
        self._hovered_tooltip_lines: list[str] | None = None

        total_h = (self.TITLE_HEIGHT + len(self._entries) * self.ENTRY_HEIGHT
                   + self.PADDING * 2)
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

        # Flip left if off right edge
        if x + self.rect.width > self._screen_width - 4:
            x = menu_center[0] - ring_offset - 12 - self.rect.width

        # Clamp vertical
        y = max(4, min(self._screen_height - self.rect.height - 4, y))

        self.rect.topleft = (x, y)

    # ── Event Handling ───────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Handle events for the popup.

        Returns:
            ``"standard:<name>"`` when a tactic is clicked.
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
                name = self._entries[idx][0].lower()
                if not self._entry_enabled(name):
                    return None
                from arena.audio.manager import get_sound_manager
                get_sound_manager().play_sfx("button_click")
                # Shove needs target selection, not immediate execution
                if name == "shove":
                    return "shove"
                return f"standard:{name.replace(' ', '_')}"

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
        title_surf = font.render("Tactics", True, parse_color(COLORS["text_primary"]))
        surface.blit(
            title_surf,
            (self.rect.x + self.PADDING + 2, self.rect.y + self.PADDING),
        )

        # Entries
        entry_font = get_font(13)
        y = self.rect.y + self.TITLE_HEIGHT
        for i, (name, _desc) in enumerate(self._entries):
            enabled = self._entry_enabled(name.lower())
            entry_rect = pygame.Rect(
                self.rect.x + 2,
                y,
                self.rect.width - 4,
                self.ENTRY_HEIGHT,
            )

            # Hover highlight
            if i == self.hovered_index and enabled:
                pygame.draw.rect(
                    surface,
                    parse_color(COLORS["hex_hover"]),
                    entry_rect,
                )

            # Icon + Text
            text_x = entry_rect.x + 8
            icon_surf = get_icon(name, 18)
            if icon_surf is not None:
                icon_y = entry_rect.y + (self.ENTRY_HEIGHT - 18) // 2
                surface.blit(icon_surf, (entry_rect.x + 6, icon_y))
                text_x = entry_rect.x + 28

            if enabled:
                text_color = parse_color(COLORS["text_primary"])
            else:
                text_color = (100, 100, 100)
            text_surf = entry_font.render(name, True, text_color)
            surface.blit(text_surf, (text_x, entry_rect.y + 5))

            y += self.ENTRY_HEIGHT

    def render_tooltip(self, surface: pygame.Surface) -> None:
        """Render tooltip for the hovered entry."""
        if self.hovered_index is None or self._hovered_tooltip_lines is None:
            return
        hovered_name = self._entries[self.hovered_index][0].lower()
        if not self._entry_enabled(hovered_name):
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
        gray = parse_color(COLORS["text_secondary"])
        for line in lines:
            text_surf = font.render(line, True, gray)
            surface.blit(text_surf, (tx + padding, y))
            y += line_height

    # ── Helpers ──────────────────────────────────────────────────────

    def _entry_enabled(self, name: str) -> bool:
        """Whether the entry (lower-cased name) can be clicked right now.

        Movement-only tactics (Stand Up) stay enabled after the action is
        spent; everything else greys out once the action has been used.
        """
        return (not self.action_used) or (name in _MOVEMENT_ENTRIES)

    def _update_hover(self, pos: tuple[int, int]) -> None:
        """Update hover state."""
        idx = self._entry_at(pos)
        self.hovered_index = idx
        if idx is not None:
            self._hovered_tooltip_lines = [self._entries[idx][1]]
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
        if 0 <= idx < len(self._entries):
            return idx
        return None
