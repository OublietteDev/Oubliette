"""Action bar for selecting combat actions during a turn."""

import pygame

from arena.combat.manager import CombatManager, TurnPhase
from arena.combat.actions import check_resource_cost
from arena.combat.stat_modifiers import get_weapon_attack_bonus
from arena.models.actions import Action
from arena.gui.renderer import get_font
from arena.util.constants import COLORS, FONT_SIZES, LAYOUT, parse_color

# Tooltip descriptions for standard actions
STANDARD_TOOLTIPS: dict[str, list[str]] = {
    "Dash": ["Double your movement this turn"],
    "Disengage": ["Move without provoking opportunity attacks"],
    "Dodge": ["Attacks against you have disadvantage"],
    "Hide": ["Attempt to become hidden from enemies"],
}


class ActionButton:
    """A clickable button in the action bar."""

    def __init__(
        self, rect: pygame.Rect, label: str, action: Action | None = None,
        btn_type: str = "action",
    ) -> None:
        """Initialize a button.

        Args:
            rect: Button rectangle.
            label: Display text.
            action: The Action model this button triggers, or None for special buttons.
            btn_type: "action", "bonus", "standard", or "end_turn".
        """
        self.rect = rect
        self.label = label
        self.action = action
        self.btn_type = btn_type
        self.is_hovered = False
        self.is_disabled = False
        self.tooltip_lines: list[str] = []

    def render(self, surface: pygame.Surface) -> None:
        """Render the button."""
        if self.is_disabled:
            color = parse_color(COLORS["button_disabled"])
        elif self.is_hovered:
            color = parse_color(COLORS["button_hover"])
        elif self.btn_type == "bonus":
            color = parse_color(COLORS["button_bonus"])
        elif self.btn_type == "standard":
            color = parse_color(COLORS["button_standard"])
        else:
            color = parse_color(COLORS["button_normal"])

        pygame.draw.rect(surface, color, self.rect, border_radius=4)
        pygame.draw.rect(
            surface,
            parse_color(COLORS["hex_border"]),
            self.rect,
            1,
            border_radius=4,
        )

        font = get_font(FONT_SIZES["body"])
        text_color = parse_color(COLORS["text_primary"])
        if self.is_disabled:
            text_color = parse_color(COLORS["text_disabled"])
        text_surf = font.render(self.label, True, text_color)
        text_rect = text_surf.get_rect(center=self.rect.center)
        surface.blit(text_surf, text_rect)


class ActionBar:
    """Horizontal action bar displayed during combat turns.

    Shows three sections:
    - Attack actions (from creature's action list)
    - Standard actions (Dash, Disengage, Dodge, Hide)
    - Bonus action attacks (TWF) if available
    - End Turn button on the right

    Displays turn info text showing resource state.
    """

    STANDARD_ACTIONS = ["Dash", "Disengage", "Dodge", "Hide"]

    def __init__(self, rect: pygame.Rect) -> None:
        self.rect = rect
        self.combat: CombatManager | None = None
        self.buttons: list[ActionButton] = []
        self._needs_rebuild = True
        self._last_creature_id: str | None = None
        self._last_action_state: bool = False

    def set_combat(self, combat: CombatManager) -> None:
        """Connect to a CombatManager."""
        self.combat = combat
        self._needs_rebuild = True

    def rebuild_buttons(self) -> None:
        """Rebuild buttons based on the current active combatant's actions."""
        self.buttons.clear()
        if self.combat is None:
            return

        combatant = self.combat.active_combatant
        if combatant is None:
            return

        self._last_creature_id = combatant.creature_id
        self._last_action_state = self.combat.has_used_action

        creature = combatant.creature
        btn_width = LAYOUT["action_button_width"]
        btn_height = LAYOUT["action_button_height"]
        small_btn_width = LAYOUT["action_small_button_width"]
        padding = LAYOUT["action_bar_padding"]
        x = self.rect.x + padding
        y = self.rect.y + (self.rect.height - btn_height) // 2 + 6

        # --- Attack actions (from creature's action list) ---
        actions = [a for a in creature.actions if a.attack is not None]
        for action in actions:
            btn_rect = pygame.Rect(x, y, btn_width, btn_height)
            btn = ActionButton(btn_rect, action.name, action=action, btn_type="action")
            res_ok, _ = check_resource_cost(creature, action)
            btn.is_disabled = self.combat.has_used_action or not res_ok
            btn.tooltip_lines = self._build_attack_tooltip(action, creature)
            self.buttons.append(btn)
            x += btn_width + padding

        # --- Separator ---
        x += padding

        # --- Standard actions ---
        for std_name in self.STANDARD_ACTIONS:
            btn_rect = pygame.Rect(x, y, small_btn_width, btn_height)
            btn = ActionButton(btn_rect, std_name, action=None, btn_type="standard")
            btn.is_disabled = self.combat.has_used_action
            btn.tooltip_lines = STANDARD_TOOLTIPS.get(std_name, [])
            self.buttons.append(btn)
            x += small_btn_width + padding

        # --- Bonus action: TWF ---
        if self.combat.can_two_weapon_fight():
            x += padding
            btn_rect = pygame.Rect(x, y, btn_width, btn_height)
            btn = ActionButton(btn_rect, "Off-Hand", action=None, btn_type="bonus")
            btn.tooltip_lines = ["Off-hand attack (bonus action)"]
            self.buttons.append(btn)
            x += btn_width + padding

        # --- End Turn button on the right ---
        end_rect = pygame.Rect(
            self.rect.right - btn_width - padding, y, btn_width, btn_height
        )
        end_btn = ActionButton(end_rect, "End Turn", action=None, btn_type="end_turn")
        end_btn.tooltip_lines = ["End your turn (Space)"]
        self.buttons.append(end_btn)

        self._needs_rebuild = False

    def _build_attack_tooltip(self, action: Action, creature) -> list[str]:
        """Build tooltip lines for an attack action."""
        lines: list[str] = []
        atk = action.attack
        if atk is None:
            return lines

        # Attack bonus
        ability_mod = creature.ability_scores.get_modifier(atk.ability)
        attack_bonus = ability_mod + creature.proficiency_bonus
        attack_bonus += get_weapon_attack_bonus(creature, action.source_item)
        sign = "+" if attack_bonus >= 0 else ""
        lines.append(f"{sign}{attack_bonus} to hit")

        # Damage rolls
        for dr in atk.damage:
            dmg_str = dr.dice
            total_bonus = dr.bonus
            if dr.ability_modifier:
                ab_mod = creature.ability_scores.get_modifier(dr.ability_modifier)
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

        return lines

    def get_hovered_tooltip(self) -> tuple[list[str], pygame.Rect] | None:
        """Get tooltip data for the currently hovered button.

        Returns:
            Tuple of (lines, button_rect) for the hovered button, or None.
        """
        for btn in self.buttons:
            if btn.is_hovered and btn.tooltip_lines:
                return (btn.tooltip_lines, btn.rect)
        return None

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Handle mouse events.

        Returns:
            "end_turn" if End Turn clicked.
            "action:<name>" if an action button clicked.
            "standard:<name>" if a standard action button clicked.
            "bonus:offhand" if off-hand attack clicked.
            None otherwise.
        """
        if not self.rect.collidepoint(pygame.mouse.get_pos()):
            return None

        if event.type == pygame.MOUSEMOTION:
            for btn in self.buttons:
                btn.is_hovered = btn.rect.collidepoint(event.pos)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for btn in self.buttons:
                if btn.rect.collidepoint(event.pos) and not btn.is_disabled:
                    from arena.audio.manager import get_sound_manager
                    get_sound_manager().play_sfx("button_click")

                    if btn.btn_type == "end_turn":
                        return "end_turn"
                    elif btn.btn_type == "action" and btn.action:
                        return f"action:{btn.action.name}"
                    elif btn.btn_type == "standard":
                        return f"standard:{btn.label.lower()}"
                    elif btn.btn_type == "bonus":
                        return "bonus:offhand"

        return None

    def update(self) -> None:
        """Per-frame update. Detects when the active creature or action state changes."""
        if self.combat is None:
            return

        combatant = self.combat.active_combatant
        current_id = combatant.creature_id if combatant else None

        if current_id != self._last_creature_id:
            self._needs_rebuild = True

        # Rebuild if action state changed (to update disabled states and TWF)
        if self.combat.has_used_action != self._last_action_state:
            self._needs_rebuild = True

        if self._needs_rebuild:
            self.rebuild_buttons()

    def render(self, surface: pygame.Surface) -> None:
        """Render the action bar."""
        if self.combat is None:
            return

        # Background
        pygame.draw.rect(surface, parse_color(COLORS["bg_medium"]), self.rect)
        pygame.draw.rect(surface, parse_color(COLORS["hex_border"]), self.rect, 1)

        combatant = self.combat.active_combatant
        if combatant is None:
            return

        if self._needs_rebuild:
            self.rebuild_buttons()

        # Info text at top of bar
        font = get_font(FONT_SIZES["body"])
        info_parts = [f"{combatant.creature.name}'s turn"]

        if self.combat.turn_phase == TurnPhase.SELECTING_TARGET:
            action_name = (
                self.combat.selected_action.name
                if self.combat.selected_action
                else "?"
            )
            info_parts.append(f"Select target for {action_name}")
        else:
            # Show resource state
            resources = []
            if self.combat.has_used_action:
                resources.append("Action used")
            if self.combat.turn_resources.has_used_bonus_action:
                resources.append("Bonus used")
            if self.combat.turn_resources.is_disengaging:
                resources.append("Disengaging")
            if resources:
                info_parts.append(" | ".join(resources))

        info_parts.append(f"Move: {self.combat.movement.remaining_movement} ft")
        info = " | ".join(info_parts)

        info_surf = font.render(info, True, parse_color(COLORS["text_secondary"]))
        surface.blit(info_surf, (self.rect.x + 8, self.rect.y + 4))

        for btn in self.buttons:
            btn.render(surface)
