"""Spell list popup for the radial menu's 'Spells' group slot.

Displays leveled spells organized by spell level in a rectangular panel
adjacent to the radial ring. Supports mousewheel scrolling.
"""

from __future__ import annotations

import pygame

from arena.models.actions import Action
from arena.gui.icons import get_icon
from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color


# Ordinal level labels
_LEVEL_LABELS = {
    1: "1st Level",
    2: "2nd Level",
    3: "3rd Level",
    4: "4th Level",
    5: "5th Level",
    6: "6th Level",
    7: "7th Level",
    8: "8th Level",
    9: "9th Level",
}


def _spell_level(action: Action) -> int:
    """Extract the spell slot level from an action's resource_cost.

    Returns the lowest ``spell_slot_N`` key found, or 0 if none.
    """
    for key in action.resource_cost:
        if key.startswith("spell_slot_"):
            try:
                return int(key.split("_")[-1])
            except ValueError:
                pass
    return 0


class _SpellEntry:
    """One row in the spell popup (either a level header or a spell name)."""

    __slots__ = ("is_header", "label", "action", "level")

    def __init__(
        self,
        *,
        is_header: bool = False,
        label: str = "",
        action: Action | None = None,
        level: int = 0,
    ) -> None:
        self.is_header = is_header
        self.label = label
        self.action = action
        self.level = level


class SpellPopup:
    """Rectangular popup listing leveled spells organized by level."""

    ENTRY_HEIGHT = 24
    HEADER_HEIGHT = 22
    WIDTH = 230
    TITLE_HEIGHT = 26
    PADDING = 4
    MAX_VISIBLE_ENTRIES = 12  # scroll beyond this

    def __init__(
        self,
        spells: list[Action],
        creature,
        action_used: bool,
        screen_width: int = 1280,
        screen_height: int = 720,
        max_resources: dict[str, int] | None = None,
    ) -> None:
        self.creature = creature
        self.action_used = action_used
        self._screen_width = screen_width
        self._screen_height = screen_height
        self._max_resources = max_resources

        self.hovered_index: int | None = None  # index into _entries
        self._hovered_tooltip_lines: list[str] | None = None
        self.scroll_offset: int = 0

        # Build entries grouped by level
        self._entries: list[_SpellEntry] = self._build_entries(
            spells, creature, max_resources,
        )

        # Compute rect height
        content_h = 0
        for entry in self._entries:
            content_h += self.HEADER_HEIGHT if entry.is_header else self.ENTRY_HEIGHT
        visible_h = min(
            content_h,
            self.MAX_VISIBLE_ENTRIES * self.ENTRY_HEIGHT,
        )
        total_h = self.TITLE_HEIGHT + visible_h + self.PADDING * 2
        self.rect = pygame.Rect(0, 0, self.WIDTH, total_h)
        self._content_height = content_h
        self._visible_height = visible_h

    # ── Entry Building ───────────────────────────────────────────────

    @staticmethod
    def _build_entries(
        spells: list[Action],
        creature,
        max_resources: dict[str, int] | None = None,
    ) -> list[_SpellEntry]:
        """Build the entry list grouped by spell level.

        Current slot counts are read from ``creature.class_resources``
        (decremented during combat by ``deduct_resource_cost``).  Max
        slot counts come from the combatant's ``max_resources`` snapshot
        taken at initiative roll, falling back to ``creature.spell_slots``
        for display outside of combat.
        """
        # Group by level
        by_level: dict[int, list[Action]] = {}
        for spell in spells:
            lvl = _spell_level(spell)
            by_level.setdefault(lvl, []).append(spell)

        # Current slot counts from class_resources (live, decremented)
        class_res = getattr(creature, "class_resources", {}) or {}

        # Max slot counts from combatant snapshot, then spell_slots fallback
        spell_slots = dict(creature.spell_slots) if getattr(creature, "spell_slots", None) else {}

        entries: list[_SpellEntry] = []
        for lvl in sorted(by_level.keys()):
            if lvl == 0:
                continue  # Skip cantrips (shouldn't be here)
            label = _LEVEL_LABELS.get(lvl, f"Level {lvl}")
            key = f"spell_slot_{lvl}"
            # Current: read from class_resources (decremented in combat)
            remaining = class_res.get(key, spell_slots.get(lvl, "?"))
            # Max: read from max_resources snapshot, then spell_slots
            if max_resources and key in max_resources:
                total = max_resources[key]
            else:
                total = spell_slots.get(lvl, "?")
            header_text = f"{label}  ({remaining}/{total} slots)"
            entries.append(_SpellEntry(is_header=True, label=header_text, level=lvl))
            for spell in by_level[lvl]:
                entries.append(_SpellEntry(label=spell.name, action=spell, level=lvl))

        return entries

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
            ``"action:<name>"`` when a spell is clicked.
            ``"__close__"`` when the popup should close.
            ``None`` otherwise.
        """
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)

        elif event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                self.scroll_offset = max(
                    0,
                    min(
                        self._content_height - self._visible_height,
                        self.scroll_offset - event.y * self.ENTRY_HEIGHT,
                    ),
                )

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if not self.rect.collidepoint(event.pos):
                return "__close__"
            entry = self._entry_at(event.pos)
            if (
                entry is not None
                and not entry.is_header
                and entry.action is not None
                and not self.action_used
            ):
                from arena.audio.manager import get_sound_manager
                get_sound_manager().play_sfx("button_click")
                return f"action:{entry.action.name}"

        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "__close__"

        return None

    # ── Rendering ────────────────────────────────────────────────────

    def render(self, surface: pygame.Surface) -> None:
        """Render the spell popup."""
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
        title_surf = font.render("Spells", True, parse_color(COLORS["text_primary"]))
        surface.blit(
            title_surf,
            (self.rect.x + self.PADDING + 2, self.rect.y + self.PADDING),
        )

        # Clip content area
        content_rect = pygame.Rect(
            self.rect.x,
            self.rect.y + self.TITLE_HEIGHT,
            self.rect.width,
            self._visible_height,
        )
        surface.set_clip(content_rect)

        # Entries
        header_font = get_font(11)
        entry_font = get_font(13)
        y = content_rect.y - self.scroll_offset
        visible_idx = 0

        for i, entry in enumerate(self._entries):
            h = self.HEADER_HEIGHT if entry.is_header else self.ENTRY_HEIGHT
            entry_bottom = y + h
            entry_top = y

            if entry_bottom > content_rect.y and entry_top < content_rect.bottom:
                if entry.is_header:
                    # Level header
                    header_color = parse_color(COLORS["text_secondary"])
                    text_surf = header_font.render(entry.label, True, header_color)
                    surface.blit(text_surf, (content_rect.x + 6, y + 4))
                else:
                    # Spell entry
                    entry_rect = pygame.Rect(
                        content_rect.x + 2,
                        y,
                        content_rect.width - 4,
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
                    text_x = entry_rect.x + 14
                    icon_surf = get_icon(entry.label, 16)
                    if icon_surf is not None:
                        icon_y = y + (self.ENTRY_HEIGHT - 16) // 2
                        surface.blit(icon_surf, (entry_rect.x + 8, icon_y))
                        text_x = entry_rect.x + 28

                    text_color = (
                        (100, 100, 100)
                        if self.action_used
                        else parse_color(COLORS["text_primary"])
                    )
                    text_surf = entry_font.render(entry.label, True, text_color)
                    surface.blit(text_surf, (text_x, y + 3))

            y += h
            visible_idx += 1

        surface.set_clip(None)

        # Scroll indicators
        if self.scroll_offset > 0:
            indicator_color = parse_color(COLORS["text_secondary"])
            pygame.draw.polygon(
                surface,
                indicator_color,
                [
                    (content_rect.centerx - 6, content_rect.y + 4),
                    (content_rect.centerx + 6, content_rect.y + 4),
                    (content_rect.centerx, content_rect.y),
                ],
            )
        if self.scroll_offset < self._content_height - self._visible_height:
            indicator_color = parse_color(COLORS["text_secondary"])
            pygame.draw.polygon(
                surface,
                indicator_color,
                [
                    (content_rect.centerx - 6, content_rect.bottom - 4),
                    (content_rect.centerx + 6, content_rect.bottom - 4),
                    (content_rect.centerx, content_rect.bottom),
                ],
            )

    def render_tooltip(self, surface: pygame.Surface) -> None:
        """Render tooltip for the hovered spell entry."""
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

        # Position to the right of the popup
        tx = self.rect.right + 6
        entry = self._entries[self.hovered_index]
        entry_y = self._entry_y(self.hovered_index)
        ty = entry_y if entry_y is not None else self.rect.y

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

    def _update_hover(self, pos: tuple[int, int]) -> None:
        """Update hover state."""
        entry = self._entry_at(pos)
        if entry is not None and not entry.is_header:
            idx = self._entries.index(entry)
            self.hovered_index = idx
            self._hovered_tooltip_lines = self._build_spell_tooltip(entry.action)
        else:
            self.hovered_index = None
            self._hovered_tooltip_lines = None

    def _entry_at(self, pos: tuple[int, int]) -> _SpellEntry | None:
        """Get the entry at the given screen position."""
        if not self.rect.collidepoint(pos):
            return None

        content_top = self.rect.y + self.TITLE_HEIGHT
        rel_y = pos[1] - content_top + self.scroll_offset

        if rel_y < 0:
            return None

        y = 0
        for entry in self._entries:
            h = self.HEADER_HEIGHT if entry.is_header else self.ENTRY_HEIGHT
            if y <= rel_y < y + h:
                return entry
            y += h
        return None

    def _entry_y(self, index: int) -> int | None:
        """Get the screen Y position for an entry by index."""
        y = self.rect.y + self.TITLE_HEIGHT - self.scroll_offset
        for i, entry in enumerate(self._entries):
            if i == index:
                return y
            h = self.HEADER_HEIGHT if entry.is_header else self.ENTRY_HEIGHT
            y += h
        return None

    def _build_spell_tooltip(self, action: Action | None) -> list[str]:
        """Build tooltip lines for a spell."""
        if action is None:
            return []
        lines: list[str] = []

        # Type + action economy tag
        level = _spell_level(action)
        if level > 0:
            ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(level, f"{level}th")
            type_label = f"Spell ({ordinal})"
        else:
            type_label = "Spell"
        economy = {
            "action": "Action",
            "bonus_action": "Bonus Action",
            "reaction": "Reaction",
        }.get(action.action_type.value, "Action")
        lines.append(f"{type_label} \u2022 {economy}")

        # Spell description
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
                    ab_mod = self.creature.ability_scores.get_modifier(dr.ability_modifier)
                    total_bonus += ab_mod
                if total_bonus > 0:
                    dmg_str += f"+{total_bonus}"
                elif total_bonus < 0:
                    dmg_str += str(total_bonus)
                dmg_str += f" {dr.damage_type.value}"
                lines.append(dmg_str)

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

        # Range
        if action.range and action.range > 5:
            lines.append(f"Range: {action.range} ft")

        # Concentration
        if action.requires_concentration:
            lines.append("Concentration")

        return lines if lines else [action.name]
