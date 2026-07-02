"""Combat log panel displaying event history with filtering."""

from enum import Enum, auto

import pygame

from arena.combat.events import CombatLog, CombatEventType
from arena.gui.renderer import draw_panel, draw_scrollbar, get_font
from arena.gui.tray_backgrounds import draw_tray_background
from arena.util.constants import COLORS, FONT_SIZES, LAYOUT, parse_color


# Dark color palette for combat log text (readable on light parchment tray).
# Same hue relationships as the main COLORS palette, but much darker.
_LOG_COLORS: dict[str, tuple[int, int, int]] = {
    "text_primary":     (40, 32, 24),       # dark brown (was #f0e6d2)
    "text_secondary":   (90, 78, 62),       # muted brown (was #a89880)
    "text_gold":        (120, 88, 20),      # dark gold (was #d4a847)
    "team_player":      (24, 100, 28),      # dark green (was #4CAF50)
    "team_enemy":       (140, 28, 20),      # dark red (was #c43030)
    "hp_full":          (24, 100, 28),      # dark green
    "hp_critical":      (140, 28, 20),      # dark red
    "condition_neutral": (30, 70, 130),     # dark blue (was #5090d0)
    "condition_debuff": (140, 28, 20),      # dark red
    "condition_buff":   (24, 100, 28),      # dark green
    "ai_thinking":      (80, 50, 110),      # dark purple (was #9070b0)
}

# Color mapping for different event types (keys into _LOG_COLORS)
EVENT_COLORS: dict[CombatEventType, str] = {
    CombatEventType.COMBAT_START: "text_primary",
    CombatEventType.ROUND_START: "text_primary",
    CombatEventType.TURN_START: "team_player",
    CombatEventType.TURN_END: "text_secondary",
    CombatEventType.MOVEMENT: "text_secondary",
    CombatEventType.ATTACK_ROLL: "text_primary",
    CombatEventType.DAMAGE: "hp_critical",
    CombatEventType.CREATURE_DOWNED: "hp_critical",
    CombatEventType.COMBAT_END: "text_primary",
    CombatEventType.INFO: "text_secondary",
    CombatEventType.SAVING_THROW: "condition_neutral",
    CombatEventType.CONDITION_APPLIED: "condition_debuff",
    CombatEventType.CONDITION_REMOVED: "condition_buff",
    CombatEventType.DEATH_SAVE: "hp_critical",
    CombatEventType.HEALING: "hp_full",
    CombatEventType.REACTION: "team_enemy",
    CombatEventType.AI_THINKING: "ai_thinking",
    CombatEventType.TELEPORT: "condition_neutral",
    CombatEventType.FORCED_MOVEMENT: "condition_neutral",
    CombatEventType.TERRAIN_MODIFICATION: "condition_neutral",
}


class LogFilter(Enum):
    """Filter categories for the combat log."""

    ALL = auto()
    COMBAT = auto()
    MOVEMENT = auto()
    CONDITIONS = auto()
    SYSTEM = auto()


# Which event types belong to each filter
FILTER_TYPES: dict[LogFilter, set[CombatEventType]] = {
    LogFilter.COMBAT: {
        CombatEventType.ATTACK_ROLL,
        CombatEventType.DAMAGE,
        CombatEventType.SAVING_THROW,
        CombatEventType.CREATURE_DOWNED,
        CombatEventType.DEATH_SAVE,
        CombatEventType.HEALING,
        CombatEventType.REACTION,
    },
    LogFilter.MOVEMENT: {
        CombatEventType.MOVEMENT,
    },
    LogFilter.CONDITIONS: {
        CombatEventType.CONDITION_APPLIED,
        CombatEventType.CONDITION_REMOVED,
    },
    LogFilter.SYSTEM: {
        CombatEventType.COMBAT_START,
        CombatEventType.ROUND_START,
        CombatEventType.TURN_START,
        CombatEventType.TURN_END,
        CombatEventType.COMBAT_END,
        CombatEventType.INFO,
        CombatEventType.AI_THINKING,
    },
}

# Display labels for filter tabs
FILTER_LABELS: dict[LogFilter, str] = {
    LogFilter.ALL: "All",
    LogFilter.COMBAT: "Combat",
    LogFilter.MOVEMENT: "Move",
    LogFilter.CONDITIONS: "Cond",
    LogFilter.SYSTEM: "Sys",
}


class CombatLogPanel:
    """Displays a scrollable combat event log with filtering.

    Shows events color-coded by type. Auto-scrolls to the bottom
    when new events arrive. Supports manual scrolling with the mouse wheel.
    Filter tabs allow viewing specific event categories.
    """

    def __init__(self, rect: pygame.Rect) -> None:
        self.rect = rect
        self.combat_log: CombatLog | None = None
        self.scroll_offset: int = 0
        self._last_event_count: int = 0

        # Filter state
        self.active_filter = LogFilter.ALL
        self._filter_rects: list[tuple[pygame.Rect, LogFilter]] = []
        self._hovered_filter: LogFilter | None = None

    def set_log(self, combat_log: CombatLog) -> None:
        """Connect to a CombatLog."""
        self.combat_log = combat_log
        self._last_event_count = len(combat_log.events)

    def _get_filtered_events(self) -> list:
        """Get events matching the active filter."""
        if self.combat_log is None:
            return []
        if self.active_filter == LogFilter.ALL:
            return self.combat_log.events
        allowed = FILTER_TYPES.get(self.active_filter, set())
        return [e for e in self.combat_log.events if e.event_type in allowed]

    def handle_event(self, event: pygame.event.Event) -> None:
        """Handle scroll and filter click events."""
        if event.type == pygame.MOUSEWHEEL:
            mouse_pos = pygame.mouse.get_pos()
            if self.rect.collidepoint(mouse_pos):
                # scroll_offset is anchored to the BOTTOM (0 = newest event, larger =
                # further back in history), unlike the top-anchored creature-info panel.
                # So wheel-up (event.y > 0) must INCREASE the offset to scroll back.
                self.scroll_offset = max(0, self.scroll_offset + event.y * 2)
                # Clamp upper bound so we can't scroll past the first event
                self._clamp_scroll()

        elif event.type == pygame.MOUSEMOTION:
            if self.rect.collidepoint(event.pos):
                self._hovered_filter = None
                for frect, filt in self._filter_rects:
                    if frect.collidepoint(event.pos):
                        self._hovered_filter = filt
                        break
            else:
                self._hovered_filter = None

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for frect, filt in self._filter_rects:
                if frect.collidepoint(event.pos):
                    if filt != self.active_filter:
                        self.active_filter = filt
                        self.scroll_offset = 0  # Reset scroll on filter change
                    return

    def _clamp_scroll(self) -> None:
        """Ensure scroll_offset stays within valid bounds."""
        line_height = LAYOUT["log_line_height"]
        content_rect_height = self.rect.height - 24  # title bar area
        max_lines = content_rect_height // line_height
        filtered_events = self._get_filtered_events()
        total = len(filtered_events)
        # Max offset = number of lines we can scroll back (total - visible)
        max_offset = max(0, total - max_lines)
        self.scroll_offset = min(self.scroll_offset, max_offset)

    def update(self) -> None:
        """Auto-scroll to bottom when new events arrive (if enabled).

        Also triggers sound effects for newly arrived events.
        """
        from arena.util.settings import get_settings

        if self.combat_log and len(self.combat_log.events) != self._last_event_count:
            # Play sounds for new events
            from arena.audio.events import play_event_sound
            for event in self.combat_log.events[self._last_event_count:]:
                play_event_sound(event.event_type, event.details)

            self._last_event_count = len(self.combat_log.events)
            if get_settings().system.auto_scroll_combat_log:
                self.scroll_offset = 0  # Snap to bottom on new event

    def render(self, surface: pygame.Surface) -> None:
        """Render the combat log panel with filter tabs."""
        if self.combat_log is None:
            return

        # Background — dark leather tray with draw_panel fallback
        if not draw_tray_background(surface, self.rect, variant="combatlog"):
            draw_panel(surface, self.rect, bg_color="bg_dark")

        # Title
        title_font = get_font(FONT_SIZES["label"], "heading")
        title = title_font.render(
            "Combat Log", True, _LOG_COLORS["text_gold"]
        )
        surface.blit(title, (self.rect.x + 8, self.rect.y + 4))

        # Filter tabs (right of title)
        self._render_filter_tabs(surface)

        # Content area below title
        content_rect = pygame.Rect(
            self.rect.x + 4,
            self.rect.y + 20,
            self.rect.width - 8,
            self.rect.height - 24,
        )

        font = get_font(FONT_SIZES["content"])
        line_height = LAYOUT["log_line_height"]
        max_lines = content_rect.height // line_height

        filtered_events = self._get_filtered_events()
        total = len(filtered_events)

        # Calculate visible range (most recent at bottom)
        end_idx = max(0, total - self.scroll_offset)
        start_idx = max(0, end_idx - max_lines)

        y = content_rect.y
        for i in range(start_idx, end_idx):
            event = filtered_events[i]
            color_key = EVENT_COLORS.get(event.event_type, "text_secondary")
            color = _LOG_COLORS.get(color_key, _LOG_COLORS["text_primary"])

            text = f"> {event.message}"
            text_surf = font.render(text, True, color)

            # Clip to content area width
            surface.blit(
                text_surf,
                (content_rect.x, y),
                area=pygame.Rect(0, 0, content_rect.width - 10, line_height),
            )
            y += line_height

        # Scrollbar (only when content exceeds visible area)
        total_content_h = total * line_height
        if total_content_h > content_rect.height:
            # Invert scroll ratio: offset 0 = bottom, max = top
            max_offset = max(0, total - max_lines)
            inverted_offset = max_offset - self.scroll_offset
            draw_scrollbar(
                surface,
                content_rect,
                total_content_h,
                inverted_offset,
            )

    def _render_filter_tabs(self, surface: pygame.Surface) -> None:
        """Render the filter tab buttons in the title bar area."""
        font = get_font(FONT_SIZES["small"])
        tab_height = 16
        tab_y = self.rect.y + 2
        tab_gap = 2
        tab_padding = 6

        # Start tabs from the right side to avoid collision with title
        tab_x = self.rect.x + 100

        self._filter_rects.clear()

        for filt in LogFilter:
            label = FILTER_LABELS[filt]
            tab_w = font.size(label)[0] + tab_padding * 2

            tab_rect = pygame.Rect(tab_x, tab_y, tab_w, tab_height)
            self._filter_rects.append((tab_rect, filt))

            # Color based on state
            is_active = filt == self.active_filter
            is_hovered = filt == self._hovered_filter

            if is_active:
                bg_color = parse_color(COLORS["button_active"])
                text_color = parse_color(COLORS["text_primary"])
            elif is_hovered:
                bg_color = parse_color(COLORS["button_hover"])
                text_color = parse_color(COLORS["text_primary"])
            else:
                bg_color = parse_color(COLORS["button_normal"])
                text_color = parse_color(COLORS["text_secondary"])

            pygame.draw.rect(surface, bg_color, tab_rect, border_radius=3)
            label_surf = font.render(label, True, text_color)
            label_rect = label_surf.get_rect(center=tab_rect.center)
            surface.blit(label_surf, label_rect)

            tab_x += tab_w + tab_gap
