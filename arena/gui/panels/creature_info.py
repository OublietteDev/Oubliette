"""Creature info panel — displays a full character sheet for the selected creature."""

import pygame

from arena.combat.manager import CombatManager
from arena.combat.stat_modifiers import (
    get_effective_armor_class,
    get_effective_speed,
    get_effective_ability_modifier,
    get_effective_damage_resistances,
    get_effective_damage_immunities,
    get_effective_condition_immunities,
    get_effective_saving_throw_proficiencies,
    get_ac_breakdown,
    get_speed_breakdown,
    get_ability_score_breakdown,
)
from arena.gui.renderer import draw_panel, draw_scrollbar, get_font
from arena.gui.tray_backgrounds import draw_tray_background
from arena.util.constants import COLORS, CONDITION_DISPLAY, FONT_SIZES, parse_color

# Ability abbreviations in display order
ABILITY_NAMES = [
    ("STR", "strength"),
    ("DEX", "dexterity"),
    ("CON", "constitution"),
    ("INT", "intelligence"),
    ("WIS", "wisdom"),
    ("CHA", "charisma"),
]


class CreatureInfoPanel:
    """Displays detailed creature info in the side panel.

    Shows name, HP, AC, speed, ability scores with modifiers,
    saving throws, resistances/immunities, conditions, and actions.
    Supports scrolling when content exceeds panel height.
    Hovering over AC, Speed, or ability scores shows a breakdown tooltip.
    """

    def __init__(self, rect: pygame.Rect) -> None:
        self.rect = rect
        self.combat: CombatManager | None = None
        self.creature_id: str | None = None
        self.scroll_offset: int = 0
        self._content_height: int = 0  # Total rendered height for scroll limits

        # Hitbox tracking for stat tooltips
        self._ac_rect: pygame.Rect | None = None
        self._speed_rect: pygame.Rect | None = None
        self._ability_rects: dict[str, pygame.Rect] = {}
        self._mouse_pos: tuple[int, int] = (0, 0)
        self._hovered_stat: str | None = None  # "ac", "speed", or ability name

    def set_combat(self, combat: CombatManager) -> None:
        """Connect to a CombatManager."""
        self.combat = combat

    def set_creature_id(self, creature_id: str | None) -> None:
        """Set the creature to display."""
        if creature_id != self.creature_id:
            self.creature_id = creature_id
            self.scroll_offset = 0

    def handle_event(self, event: pygame.event.Event) -> None:
        """Handle scroll and hover events within the panel."""
        if event.type == pygame.MOUSEWHEEL:
            mouse_pos = pygame.mouse.get_pos()
            if self.rect.collidepoint(mouse_pos):
                self.scroll_offset = max(
                    0, self.scroll_offset - event.y * 20
                )
                # Clamp to content
                max_scroll = max(0, self._content_height - self.rect.height + 8)
                self.scroll_offset = min(self.scroll_offset, max_scroll)

        if event.type == pygame.MOUSEMOTION:
            self._mouse_pos = event.pos
            self._update_hovered_stat()

    def _update_hovered_stat(self) -> None:
        """Determine which stat (if any) the mouse is hovering over."""
        mx, my = self._mouse_pos
        if not self.rect.collidepoint(mx, my):
            self._hovered_stat = None
            return

        if self._ac_rect and self._ac_rect.collidepoint(mx, my):
            self._hovered_stat = "ac"
            return
        if self._speed_rect and self._speed_rect.collidepoint(mx, my):
            self._hovered_stat = "speed"
            return
        for ability_name, rect in self._ability_rects.items():
            if rect.collidepoint(mx, my):
                self._hovered_stat = ability_name
                return
        self._hovered_stat = None

    def update(self) -> None:
        """Per-frame update."""
        pass

    def render(self, surface: pygame.Surface) -> None:
        """Render the creature info panel."""
        # Background — tray image with draw_panel fallback
        if not draw_tray_background(surface, self.rect, variant="standard"):
            draw_panel(surface, self.rect)

        if self.combat is None:
            return

        # Resolve creature to display
        cid = self.creature_id
        if cid is None:
            active = self.combat.active_combatant
            if active:
                cid = active.creature_id
        if cid is None:
            return

        combatant = self.combat.get_creature(cid)
        if combatant is None:
            return

        c = combatant.creature
        panel_x = self.rect.x
        panel_w = self.rect.width

        # Clip to panel
        old_clip = surface.get_clip()
        surface.set_clip(self.rect)

        x = panel_x + 10
        y = self.rect.y + 8 - self.scroll_offset

        white = parse_color(COLORS["text_primary"])
        gray = parse_color(COLORS["text_secondary"])
        gold = parse_color(COLORS["text_gold"])
        font_title = get_font(FONT_SIZES["title"], "heading")
        font_body = get_font(FONT_SIZES["label"])
        font_small = get_font(FONT_SIZES["body"])

        # --- Team color indicator + Name ---
        team_key = f"team_{combatant.team}"
        team_color = parse_color(COLORS.get(team_key, COLORS["text_secondary"]))
        pygame.draw.rect(surface, team_color, (x, y, 4, 18))
        surf = font_title.render(c.name, True, gold)
        surface.blit(surf, (x + 10, y))
        y += 26

        # --- HP bar ---
        bar_width = panel_w - 24
        bar_height = 8
        pygame.draw.rect(surface, (40, 40, 40), (x, y, bar_width, bar_height))
        hp_pct = c.hp_percent
        fill_w = int(bar_width * hp_pct)
        if hp_pct > 0.5:
            hp_color = parse_color(COLORS["hp_full"])
        elif hp_pct > 0.25:
            hp_color = parse_color(COLORS["hp_bloodied"])
        else:
            hp_color = parse_color(COLORS["hp_critical"])
        if fill_w > 0:
            pygame.draw.rect(surface, hp_color, (x, y, fill_w, bar_height))
        # Temp HP overlay (cyan segment after the real HP fill)
        temp_hp = getattr(c, "temporary_hit_points", 0) or 0
        if temp_hp > 0 and c.max_hit_points > 0:
            temp_pct = temp_hp / c.max_hit_points
            temp_w = min(int(bar_width * temp_pct), bar_width - fill_w)
            if temp_w > 0:
                temp_color = parse_color(COLORS["hp_temp"])
                pygame.draw.rect(
                    surface, temp_color,
                    (x + fill_w, y, temp_w, bar_height),
                )
        y += 14

        # --- HP text ---
        hp_text = f"HP: {c.current_hit_points}/{c.max_hit_points}"
        if temp_hp > 0:
            hp_text += f" (+{temp_hp} temp)"
        surf = font_body.render(hp_text, True, white)
        surface.blit(surf, (x, y))
        y += 18

        # --- Death saves (if applicable) ---
        if c.current_hit_points == 0 and not c.is_conscious:
            ds_label = font_body.render("Death Saves: ", True, gray)
            surface.blit(ds_label, (x, y))
            pip_x = x + ds_label.get_width()
            pip_r = 4
            green = parse_color(COLORS["hp_full"])
            red = parse_color(COLORS["hp_critical"])
            dark = (40, 40, 40)
            ds_successes = getattr(c, "death_save_successes", 0)
            ds_failures = getattr(c, "death_save_failures", 0)
            for i in range(3):
                color = green if i < ds_successes else dark
                pygame.draw.circle(
                    surface, color, (pip_x + i * 12 + pip_r, y + 8), pip_r
                )
            pip_x += 42
            for i in range(3):
                color = red if i < ds_failures else dark
                pygame.draw.circle(
                    surface, color, (pip_x + i * 12 + pip_r, y + 8), pip_r
                )
            y += 18

        # --- AC and Speed ---
        ac_text = f"AC: {get_effective_armor_class(c)}"
        ac_surf = font_body.render(ac_text, True, gray)
        surface.blit(ac_surf, (x, y))
        self._ac_rect = pygame.Rect(x, y, ac_surf.get_width(), ac_surf.get_height())

        speed_val = get_effective_speed(c)
        speed_text = f"Speed: {speed_val} ft"
        speed_surf = font_body.render(speed_text, True, gray)
        surface.blit(speed_surf, (x + 100, y))
        self._speed_rect = pygame.Rect(x + 100, y, speed_surf.get_width(), speed_surf.get_height())
        y += 20

        # --- Class Resources (PlayerCharacter only) ---
        class_resources = getattr(c, "class_resources", None)
        if class_resources and combatant.max_resources:
            for res_name, current_val in class_resources.items():
                max_val = combatant.max_resources.get(res_name, current_val)
                # Render compact resource line
                display_name = res_name.replace("_", " ").title()
                res_text = f"{display_name}: {current_val}/{max_val}"
                res_surf = font_small.render(res_text, True, gray)
                surface.blit(res_surf, (x, y))

                # Small resource bar
                bar_w = panel_w - 24
                bar_h = 4
                y += 14
                pygame.draw.rect(surface, (40, 40, 40), (x, y, bar_w, bar_h))
                if max_val > 0:
                    fill = int(bar_w * current_val / max_val)
                    if fill > 0:
                        bar_color = parse_color(COLORS["text_gold"])
                        pygame.draw.rect(surface, bar_color, (x, y, fill, bar_h))
                y += 8
            y += 2

        # --- Active conditions ---
        if c.active_conditions:
            cond_x = x
            for ac in c.active_conditions:
                cond_name = ac.condition.value
                abbrev, color_key = CONDITION_DISPLAY.get(
                    cond_name, (cond_name[:2].upper(), "condition_neutral")
                )
                cond_color = parse_color(COLORS[color_key])
                text_surf = font_small.render(abbrev, True, (0, 0, 0))
                badge_w = text_surf.get_width() + 6
                badge_h = text_surf.get_height() + 2
                if cond_x + badge_w > panel_x + panel_w - 10:
                    cond_x = x
                    y += badge_h + 2
                pygame.draw.rect(
                    surface, cond_color,
                    (cond_x, y, badge_w, badge_h), border_radius=3,
                )
                surface.blit(text_surf, (cond_x + 3, y + 1))
                cond_x += badge_w + 3
            y += badge_h + 6
        else:
            y += 2

        # --- Section separator ---
        y += 2
        pygame.draw.line(
            surface, parse_color(COLORS["border_accent"]),
            (x, y), (panel_x + panel_w - 10, y),
        )
        y += 6

        # --- Ability Scores (3x2 grid) ---
        section_label = font_small.render("Ability Scores", True, gold)
        surface.blit(section_label, (x, y))
        y += 16

        col_width = (panel_w - 24) // 3
        self._ability_rects.clear()
        for row in range(2):
            for col in range(3):
                idx = row * 3 + col
                abbrev, full_name = ABILITY_NAMES[idx]
                score = c.ability_scores.get_score(full_name)
                mod = get_effective_ability_modifier(c, full_name)

                cx = x + col * col_width
                # Abbreviation
                ab_surf = font_small.render(abbrev, True, gray)
                surface.blit(ab_surf, (cx, y))

                # Score
                score_surf = font_small.render(str(score), True, white)
                surface.blit(score_surf, (cx + 30, y))

                # Modifier (color-coded)
                if mod >= 0:
                    mod_text = f"(+{mod})"
                    mod_color = parse_color(COLORS["hp_full"]) if mod > 0 else gray
                else:
                    mod_text = f"({mod})"
                    mod_color = parse_color(COLORS["hp_critical"])
                mod_surf = font_small.render(mod_text, True, mod_color)
                surface.blit(mod_surf, (cx + 50, y))

                # Track hitbox for this ability cell
                self._ability_rects[full_name] = pygame.Rect(cx, y, col_width, 16)

            y += 16
        y += 4

        # --- Saving Throws ---
        section_label = font_small.render("Saving Throws", True, gold)
        surface.blit(section_label, (x, y))
        y += 16

        eff_profs = get_effective_saving_throw_proficiencies(c)
        for row in range(2):
            for col in range(3):
                idx = row * 3 + col
                abbrev, full_name = ABILITY_NAMES[idx]
                # Use effective ability modifier + proficiency if applicable
                mod = get_effective_ability_modifier(c, full_name)
                is_prof = full_name.lower() in eff_profs
                if is_prof:
                    mod += c.proficiency_bonus

                cx = x + col * col_width
                ab_surf = font_small.render(abbrev, True, gray)
                surface.blit(ab_surf, (cx, y))

                sign = "+" if mod >= 0 else ""
                save_text = f"{sign}{mod}"
                if is_prof:
                    save_text += "*"
                save_color = white if is_prof else gray
                save_surf = font_small.render(save_text, True, save_color)
                surface.blit(save_surf, (cx + 30, y))
            y += 16
        y += 4

        # --- Resistances / Immunities / Vulnerabilities ---
        y = self._render_defense_list(
            surface, x, y, "Resistances",
            get_effective_damage_resistances(c),
            parse_color(COLORS["condition_neutral"]), font_small, gold,
            panel_x + panel_w - 10,
        )
        y = self._render_defense_list(
            surface, x, y, "Immunities",
            get_effective_damage_immunities(c),
            parse_color(COLORS["hp_full"]), font_small, gold,
            panel_x + panel_w - 10,
        )
        y = self._render_defense_list(
            surface, x, y, "Vulnerabilities", c.damage_vulnerabilities,
            parse_color(COLORS["hp_critical"]), font_small, gold,
            panel_x + panel_w - 10,
        )
        eff_ci = get_effective_condition_immunities(c)
        if eff_ci:
            y = self._render_defense_list(
                surface, x, y, "Cond. Immunities", eff_ci,
                parse_color(COLORS["hp_full"]), font_small, gold,
                panel_x + panel_w - 10,
            )

        # --- Separator before actions ---
        if c.actions or c.bonus_actions or c.reactions:
            pygame.draw.line(
                surface, parse_color(COLORS["border_accent"]),
                (x, y), (panel_x + panel_w - 10, y),
            )
            y += 6

        # --- Actions ---
        if c.actions:
            header = font_small.render("Actions", True, gold)
            surface.blit(header, (x, y))
            y += 16
            for action in c.actions:
                label = f"  {action.name}"
                if action.attack:
                    label += f" ({action.attack.attack_type.replace('_', ' ')})"
                surf = font_small.render(label, True, white)
                surface.blit(surf, (x, y))
                y += 15

        # --- Bonus Actions ---
        if c.bonus_actions:
            y += 2
            header = font_small.render("Bonus Actions", True, gold)
            surface.blit(header, (x, y))
            y += 16
            for action in c.bonus_actions:
                surf = font_small.render(f"  {action.name}", True, white)
                surface.blit(surf, (x, y))
                y += 15

        # --- Reactions ---
        if c.reactions:
            y += 2
            header = font_small.render("Reactions", True, gold)
            surface.blit(header, (x, y))
            y += 16
            for action in c.reactions:
                surf = font_small.render(f"  {action.name}", True, white)
                surface.blit(surf, (x, y))
                y += 15

        # --- Other speeds ---
        other_speeds = {
            k: v for k, v in c.speed.items() if k != "walk" and v > 0
        }
        if other_speeds:
            y += 4
            parts = [f"{k}: {v} ft" for k, v in other_speeds.items()]
            speed_line = "Other speeds: " + ", ".join(parts)
            surf = font_small.render(speed_line, True, gray)
            surface.blit(surf, (x, y))
            y += 16

        # --- Senses ---
        if c.senses:
            parts = [f"{k} {v} ft" for k, v in c.senses.items()]
            senses_line = "Senses: " + ", ".join(parts)
            surf = font_small.render(senses_line, True, gray)
            surface.blit(surf, (x, y))
            y += 16

        # Record total content height for scroll clamping
        self._content_height = (y + self.scroll_offset) - self.rect.y

        # Scrollbar
        draw_scrollbar(
            surface, self.rect, self._content_height, self.scroll_offset,
        )

        # Restore clip before rendering tooltip (tooltip may extend outside panel)
        surface.set_clip(old_clip)

        # --- Stat tooltip (rendered on top, outside clip) ---
        if self._hovered_stat is not None:
            self._render_stat_tooltip(surface, c)

    def _render_stat_tooltip(
        self, surface: pygame.Surface, creature,
    ) -> None:
        """Render a stat breakdown tooltip near the mouse cursor."""
        if self._hovered_stat == "ac":
            breakdown = get_ac_breakdown(creature)
            title = "Armor Class"
        elif self._hovered_stat == "speed":
            breakdown = get_speed_breakdown(creature)
            title = "Speed"
        else:
            breakdown = get_ability_score_breakdown(creature, self._hovered_stat)
            title = self._hovered_stat.title()

        if not breakdown:
            return

        font = get_font(FONT_SIZES["body"])
        padding = 6
        line_height = 17
        separator_height = 4

        # Measure tooltip dimensions
        max_label_w = 0
        max_value_w = 0
        for label, value in breakdown:
            max_label_w = max(max_label_w, font.size(label)[0])
            max_value_w = max(max_value_w, font.size(value)[0])

        title_w = font.size(title)[0]
        content_w = max(title_w, max_label_w + 12 + max_value_w)
        tooltip_w = content_w + padding * 2
        tooltip_h = padding * 2 + line_height * (len(breakdown) + 1) + separator_height

        # Position near mouse
        mx, my = self._mouse_pos
        tx = mx + 16
        ty = my + 16

        # Clamp to screen
        screen_w = surface.get_width()
        screen_h = surface.get_height()
        if tx + tooltip_w > screen_w:
            tx = mx - tooltip_w - 4
        if ty + tooltip_h > screen_h:
            ty = my - tooltip_h - 4

        # Draw background
        bg_rect = pygame.Rect(tx, ty, tooltip_w, tooltip_h)
        bg_surface = pygame.Surface((tooltip_w, tooltip_h), pygame.SRCALPHA)
        bg_surface.fill((30, 24, 18, 235))
        surface.blit(bg_surface, (tx, ty))
        border_color = parse_color(COLORS["border_accent"])
        pygame.draw.rect(surface, border_color, bg_rect, 1)

        # Draw title
        white = parse_color(COLORS["text_primary"])
        gold = parse_color(COLORS["text_gold"])
        gray = parse_color(COLORS["text_secondary"])

        title_surf = font.render(title, True, gold)
        surface.blit(title_surf, (tx + padding, ty + padding))
        cy = ty + padding + line_height

        # Draw breakdown lines
        for i, (label, value) in enumerate(breakdown):
            is_total = (i == len(breakdown) - 1)

            # Separator line before total
            if is_total:
                pygame.draw.line(
                    surface, gray,
                    (tx + padding, cy + 1),
                    (tx + tooltip_w - padding, cy + 1),
                )
                cy += separator_height

            text_color = white if is_total else gray
            label_surf = font.render(label, True, text_color)
            value_surf = font.render(value, True, text_color)
            surface.blit(label_surf, (tx + padding, cy))
            surface.blit(value_surf, (tx + tooltip_w - padding - value_surf.get_width(), cy))
            cy += line_height

    def _render_defense_list(
        self,
        surface: pygame.Surface,
        x: int,
        y: int,
        label: str,
        items: list[str],
        color: tuple,
        font: pygame.font.Font,
        label_color: tuple,
        max_x: int,
    ) -> int:
        """Render a defense list (resistances, immunities, etc.).

        Returns the updated y position.
        """
        if not items:
            return y

        header = font.render(f"{label}: ", True, label_color)
        surface.blit(header, (x, y))

        text = ", ".join(items)
        # Wrap if text is too long
        text_surf = font.render(text, True, color)
        if x + header.get_width() + text_surf.get_width() <= max_x:
            surface.blit(text_surf, (x + header.get_width(), y))
            y += 16
        else:
            y += 16
            text_surf = font.render(f"  {text}", True, color)
            surface.blit(text_surf, (x, y))
            y += 16

        return y
