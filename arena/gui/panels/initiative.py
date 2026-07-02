"""Initiative order panel displaying turn order with click-to-select."""

import pygame

from arena.combat.manager import CombatManager, CombatState, TurnPhase
from arena.gui.renderer import draw_panel, get_font
from arena.gui.tray_backgrounds import draw_tray_background
from arena.util.constants import COLORS, FONT_SIZES, LAYOUT, parse_color


class InitiativePanel:
    """Displays the initiative turn order as a vertical list.

    Shows creature names, initiative rolls, HP indicators,
    and highlights the current turn. Entries are clickable to
    select a creature. Supports hover highlighting.
    """

    def __init__(self, rect: pygame.Rect) -> None:
        self.rect = rect
        self.combat: CombatManager | None = None
        self._hovered_entry_id: str | None = None
        self._entry_rects: list[tuple[pygame.Rect, str]] = []

    def set_combat(self, combat: CombatManager) -> None:
        """Connect to a CombatManager."""
        self.combat = combat

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Handle mouse events on initiative entries.

        Returns:
            creature_id of clicked entry, or None.
        """
        if event.type == pygame.MOUSEMOTION:
            if self.rect.collidepoint(event.pos):
                self._hovered_entry_id = None
                for entry_rect, creature_id in self._entry_rects:
                    if entry_rect.collidepoint(event.pos):
                        self._hovered_entry_id = creature_id
                        break
            else:
                self._hovered_entry_id = None

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for entry_rect, creature_id in self._entry_rects:
                if entry_rect.collidepoint(event.pos):
                    return creature_id

        return None

    def update(self) -> None:
        """Per-frame update."""
        pass

    def render(self, surface: pygame.Surface) -> None:
        """Render the initiative panel."""
        if self.combat is None:
            return

        # Background — tray image with draw_panel fallback
        if not draw_tray_background(surface, self.rect, variant="standard"):
            draw_panel(surface, self.rect)

        # Title
        title_font = get_font(FONT_SIZES["title"], "heading")
        round_num = self.combat.initiative.round_number
        title = title_font.render(
            f"Initiative - Round {round_num}",
            True,
            parse_color(COLORS["text_gold"]),
        )
        surface.blit(title, (self.rect.x + 8, self.rect.y + 6))

        # Turn info line (below title, above entries)
        y = self.rect.y + 30
        active = self.combat.active_combatant
        if active and self.combat.state == CombatState.IN_COMBAT:
            info_font = get_font(FONT_SIZES["small"])
            info_parts: list[str] = [active.creature.name]

            if self.combat.turn_phase == TurnPhase.SELECTING_TARGET:
                action_name = (
                    self.combat.selected_action.name
                    if self.combat.selected_action
                    else "?"
                )
                info_parts.append(f"Target: {action_name}")
            else:
                resources: list[str] = []
                if self.combat.has_used_action:
                    resources.append("Act\u2713")
                if self.combat.turn_resources.has_used_bonus_action:
                    resources.append("Bon\u2713")
                if resources:
                    info_parts.append(" ".join(resources))

            info_parts.append(
                f"Move: {self.combat.movement.remaining_movement} ft"
            )

            info_text = " | ".join(info_parts)
            info_surf = info_font.render(
                info_text,
                True,
                parse_color(COLORS["text_secondary"]),
            )
            surface.blit(info_surf, (self.rect.x + 8, y))
            y += 16

        # Entries
        font = get_font(FONT_SIZES["list"])
        line_height = LAYOUT["initiative_line_height"]
        current_entry = self.combat.initiative.current_entry

        self._entry_rects.clear()

        for entry in self.combat.initiative.entries:
            if y + line_height > self.rect.bottom - 4:
                break

            # Special rendering for lair pseudo-entry
            if entry.is_lair:
                is_current = (
                    current_entry is not None
                    and entry.creature_id == current_entry.creature_id
                )
                entry_rect = pygame.Rect(
                    self.rect.x + 2, y, self.rect.width - 4, line_height
                )
                self._entry_rects.append((entry_rect, entry.creature_id))

                if is_current:
                    pygame.draw.rect(
                        surface,
                        parse_color(COLORS["hex_selected"]),
                        entry_rect,
                    )

                gold = parse_color(COLORS["text_gold"])
                # Gold diamond icon
                cx, cy = self.rect.x + 16, y + line_height // 2
                diamond_pts = [
                    (cx, cy - 4), (cx + 4, cy), (cx, cy + 4), (cx - 4, cy),
                ]
                pygame.draw.polygon(surface, gold, diamond_pts)

                prefix = "> " if is_current else "  "
                text = f"{prefix}Lair (20)"
                text_surf = font.render(text, True, gold)
                surface.blit(text_surf, (self.rect.x + 24, y + 2))
                y += line_height
                continue

            combatant = self.combat.get_creature(entry.creature_id)
            if combatant is None:
                continue

            is_current = (
                current_entry is not None
                and entry.creature_id == current_entry.creature_id
            )
            is_hovered = entry.creature_id == self._hovered_entry_id
            is_conscious = combatant.creature.is_conscious

            # Build entry rect and record for hit testing
            entry_rect = pygame.Rect(
                self.rect.x + 2, y, self.rect.width - 4, line_height
            )
            self._entry_rects.append((entry_rect, entry.creature_id))

            # Highlight current turn
            if is_current:
                pygame.draw.rect(
                    surface,
                    parse_color(COLORS["hex_selected"]),
                    entry_rect,
                )
            elif is_hovered:
                pygame.draw.rect(
                    surface,
                    parse_color(COLORS["hex_hover"]),
                    entry_rect,
                )

            # Team color for text
            team_key = f"team_{combatant.team}"
            team_color = parse_color(
                COLORS.get(team_key, COLORS["text_secondary"])
            )
            if not is_conscious:
                team_color = (100, 100, 100)

            # HP indicator dot
            if is_conscious:
                hp_pct = combatant.creature.hp_percent
                if hp_pct > 0.5:
                    hp_color = parse_color(COLORS["hp_full"])
                elif hp_pct > 0.25:
                    hp_color = parse_color(COLORS["hp_bloodied"])
                else:
                    hp_color = parse_color(COLORS["hp_critical"])
                pygame.draw.circle(
                    surface, hp_color, (self.rect.x + 16, y + line_height // 2), 4
                )
            else:
                # Dead/unconscious: X marker
                cx, cy = self.rect.x + 16, y + line_height // 2
                pygame.draw.line(surface, (100, 100, 100), (cx - 3, cy - 3), (cx + 3, cy + 3), 2)
                pygame.draw.line(surface, (100, 100, 100), (cx + 3, cy - 3), (cx - 3, cy + 3), 2)

            # Turn arrow prefix
            prefix = "> " if is_current else "  "

            # Name and initiative roll
            text = f"{prefix}{entry.name} ({entry.initiative_roll})"
            text_surf = font.render(text, True, team_color)
            surface.blit(text_surf, (self.rect.x + 24, y + 2))

            # Legendary action points badge
            legendary_count = getattr(combatant.creature, "legendary_action_count", 0)
            if legendary_count > 0:
                remaining = self.combat.legendary_points.get(entry.creature_id, 0)
                badge_font = get_font(FONT_SIZES["tiny"])
                badge_text = f"L:{remaining}"
                badge_color = (180, 120, 255)  # Purple for legendary
                badge_surf = badge_font.render(badge_text, True, badge_color)
                badge_x = self.rect.right - badge_surf.get_width() - 8
                surface.blit(badge_surf, (badge_x, y + 5))

            y += line_height
