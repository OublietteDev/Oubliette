"""Radial action menu for selecting combat actions during a player's turn.

Appears centered on the active creature's token when the player right-clicks
it. Supports up to 8 slots per page with pagination arrows, plus sub-popups
for grouped spell and tactics options.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto

import pygame

from arena.combat.manager import CombatManager, TurnPhase
from arena.combat.actions import check_resource_cost
from arena.combat.conditions import has_condition
from arena.models.conditions import Condition
from arena.combat.stat_modifiers import get_weapon_attack_bonus
from arena.grid.footprint import get_footprint_center_pixel
from arena.models.actions import Action, ActionType
from arena.gui.icons import get_icon
from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color
from arena.util.settings import get_settings

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arena.gui.grid_view import GridView


# ── Constants ────────────────────────────────────────────────────────

MAX_SLOTS_PER_PAGE = 8

# Animation timing (ms)
_MENU_ANIM_DURATION_MS = 150

# Slot type → COLORS key mapping for fill colors
SLOT_COLORS: dict[str, str] = {
    "attack": "radial_slot_attack",
    "cantrip": "radial_slot_cantrip",
    "spells": "radial_slot_spells",
    "tactics": "radial_slot_tactics",
    "items": "radial_slot_items",
    "bonus": "radial_slot_bonus",
    "action_surge": "radial_slot_tactics",
    "drop_concentration": "radial_slot_spells",
    "move_zone": "radial_slot_spells",
    "end_turn": "radial_slot_end_turn",
}

# Tooltip descriptions for standard actions (reused from action_bar)
STANDARD_TOOLTIPS: dict[str, list[str]] = {
    "Dash": ["Double your movement this turn"],
    "Disengage": ["Move without provoking opportunity attacks"],
    "Dodge": ["Attacks against you have disadvantage"],
    "Hide": ["Attempt to become hidden from enemies"],
}


# ── State Machine ────────────────────────────────────────────────────

class RadialMenuState(Enum):
    CLOSED = auto()
    OPENING = auto()
    OPEN = auto()
    CLOSING = auto()
    SPELL_POPUP = auto()
    TACTICS_POPUP = auto()
    CANTRIP_POPUP = auto()
    ITEMS_POPUP = auto()


# ── Slot Data ────────────────────────────────────────────────────────

@dataclass
class RadialSlot:
    """A single slot in the radial menu ring."""

    label: str
    slot_type: str  # "attack", "cantrip", "spells", "tactics", "items", "bonus", "end_turn"
    action: Action | None = None
    icon_text: str = ""
    tooltip_lines: list[str] = field(default_factory=list)
    is_disabled: bool = False
    angle: float = 0.0
    screen_pos: tuple[int, int] = (0, 0)


# ── Main Radial Menu ────────────────────────────────────────────────

class RadialMenu:
    """Radial action menu rendered around a creature token.

    The menu is opened with a right-click on the active creature's token
    and emits command strings compatible with the combat screen's routing
    (e.g. ``"action:Longsword"``, ``"standard:dash"``, ``"end_turn"``).
    """

    def __init__(self) -> None:
        self.state: RadialMenuState = RadialMenuState.CLOSED
        self.combat: CombatManager | None = None
        self.creature_id: str | None = None

        # Slot data
        self.all_slots: list[RadialSlot] = []
        self.slots: list[RadialSlot] = []  # current page
        self.current_page: int = 0
        self.total_pages: int = 1

        # Hover / interaction
        self.hovered_slot: RadialSlot | None = None
        self._hovered_arrow: str | None = None  # "next" or "prev"

        # Geometry (updated every frame when open)
        self._center_screen: tuple[int, int] = (0, 0)
        self._inner_radius: int = 40
        self._outer_radius: int = 90
        self._slot_radius: int = 22
        self._screen_width: int = 1280
        self._screen_height: int = 720

        # Arrow button rects (built during position update)
        self._next_arrow_center: tuple[int, int] = (0, 0)
        self._prev_arrow_center: tuple[int, int] = (0, 0)
        self._arrow_radius: int = 12

        # Animation
        self._anim_start: int = 0  # pygame.time.get_ticks() when anim began

        # Sub-popups
        self.spell_popup: object | None = None
        self.tactics_popup: object | None = None
        self.cantrip_popup: object | None = None
        self.items_popup: object | None = None

    # ── Public API ───────────────────────────────────────────────────

    def set_combat(self, combat: CombatManager) -> None:
        """Connect to a CombatManager."""
        self.combat = combat

    def open(self, creature_id: str) -> None:
        """Open the radial menu for the given creature."""
        self.creature_id = creature_id
        self.current_page = 0
        self.hovered_slot = None
        self._hovered_arrow = None
        self.spell_popup = None
        self.tactics_popup = None
        self.cantrip_popup = None
        self.items_popup = None
        self._rebuild_slots()
        self._anim_start = pygame.time.get_ticks()
        self.state = RadialMenuState.OPENING

    def close(self) -> None:
        """Begin closing the radial menu (starts fade-out animation)."""
        if self.state == RadialMenuState.CLOSED or self.state == RadialMenuState.CLOSING:
            return
        self._anim_start = pygame.time.get_ticks()
        self.state = RadialMenuState.CLOSING
        self.hovered_slot = None
        self._hovered_arrow = None
        self.spell_popup = None
        self.tactics_popup = None
        self.cantrip_popup = None
        self.items_popup = None

    def _finish_close(self) -> None:
        """Finalize close after the animation completes."""
        self.state = RadialMenuState.CLOSED
        self.creature_id = None
        self.hovered_slot = None
        self._hovered_arrow = None
        self.all_slots.clear()
        self.slots.clear()

    def open_spell_popup(self) -> None:
        """Transition from OPEN to SPELL_POPUP."""
        from arena.gui.spell_popup import SpellPopup

        if self.combat is None or self.creature_id is None:
            return
        combatant = self.combat.get_creature(self.creature_id)
        if combatant is None:
            return

        leveled = self._get_leveled_spells(combatant.creature)
        action_used = self.combat.has_used_action

        self.spell_popup = SpellPopup(
            spells=leveled,
            creature=combatant.creature,
            action_used=action_used,
            screen_width=self._screen_width,
            screen_height=self._screen_height,
            max_resources=combatant.max_resources,
        )
        self.spell_popup.reposition(
            self._center_screen,
            self._outer_radius + self._slot_radius,
        )
        self.state = RadialMenuState.SPELL_POPUP

    def open_tactics_popup(self) -> None:
        """Transition from OPEN to TACTICS_POPUP."""
        from arena.gui.tactics_popup import TacticsPopup

        if self.combat is None:
            return

        action_used = self.combat.has_used_action

        self.tactics_popup = TacticsPopup(
            action_used=action_used,
            screen_width=self._screen_width,
            screen_height=self._screen_height,
        )
        self.tactics_popup.reposition(
            self._center_screen,
            self._outer_radius + self._slot_radius,
        )
        self.state = RadialMenuState.TACTICS_POPUP

    def open_cantrip_popup(self) -> None:
        """Transition from OPEN to CANTRIP_POPUP."""
        from arena.gui.cantrip_popup import CantripPopup

        if self.combat is None or self.creature_id is None:
            return
        combatant = self.combat.get_creature(self.creature_id)
        if combatant is None:
            return

        cantrips = self._get_cantrips(combatant.creature)
        action_used = self.combat.has_used_action

        self.cantrip_popup = CantripPopup(
            cantrips=cantrips,
            creature=combatant.creature,
            action_used=action_used,
            screen_width=self._screen_width,
            screen_height=self._screen_height,
        )
        self.cantrip_popup.reposition(
            self._center_screen,
            self._outer_radius + self._slot_radius,
        )
        self.state = RadialMenuState.CANTRIP_POPUP

    def open_items_popup(self) -> None:
        """Transition from OPEN to ITEMS_POPUP."""
        self._open_utility_popup(self._get_item_actions, "Items")

    def open_abilities_popup(self) -> None:
        """Transition from OPEN to the abilities list (same popup machinery as
        Items, fed with class-ability actions and titled accordingly)."""
        self._open_utility_popup(self._get_ability_actions, "Abilities")

    def _open_utility_popup(self, getter, title: str) -> None:
        from arena.gui.items_popup import ItemsPopup

        if self.combat is None or self.creature_id is None:
            return
        combatant = self.combat.get_creature(self.creature_id)
        if combatant is None:
            return

        items = getter(combatant.creature)
        action_used = self.combat.has_used_action
        bonus_used = self.combat.turn_resources.has_used_bonus_action

        self.items_popup = ItemsPopup(
            items=items,
            action_used=action_used,
            bonus_used=bonus_used,
            screen_width=self._screen_width,
            screen_height=self._screen_height,
            title=title,
        )
        self.items_popup.reposition(
            self._center_screen,
            self._outer_radius + self._slot_radius,
        )
        self.state = RadialMenuState.ITEMS_POPUP

    # ── Event Handling ───────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Handle mouse events on the radial menu.

        Returns:
            Command string if an action was selected, or None.
            Special returns: ``"open_spells"`` and ``"open_tactics"``
            are internal signals handled by the combat screen.
        """
        if self.state in (RadialMenuState.CLOSED, RadialMenuState.OPENING, RadialMenuState.CLOSING):
            return None

        # Delegate to sub-popup if one is open
        if self.state == RadialMenuState.SPELL_POPUP and self.spell_popup is not None:
            result = self.spell_popup.handle_event(event)
            if result == "__close__":
                self.spell_popup = None
                self.state = RadialMenuState.OPEN
                return None
            return result

        if self.state == RadialMenuState.TACTICS_POPUP and self.tactics_popup is not None:
            result = self.tactics_popup.handle_event(event)
            if result == "__close__":
                self.tactics_popup = None
                self.state = RadialMenuState.OPEN
                return None
            return result

        if self.state == RadialMenuState.CANTRIP_POPUP and self.cantrip_popup is not None:
            result = self.cantrip_popup.handle_event(event)
            if result == "__close__":
                self.cantrip_popup = None
                self.state = RadialMenuState.OPEN
                return None
            return result

        if self.state == RadialMenuState.ITEMS_POPUP and self.items_popup is not None:
            result = self.items_popup.handle_event(event)
            if result == "__close__":
                self.items_popup = None
                self.state = RadialMenuState.OPEN
                return None
            return result

        # Main ring interaction
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            # Check pagination arrows first
            if self.total_pages > 1:
                if self._point_in_arrow(event.pos, self._next_arrow_center):
                    self._play_click()
                    self.current_page = (self.current_page + 1) % self.total_pages
                    self._paginate()
                    self._compute_slot_positions()
                    return None
                if self._point_in_arrow(event.pos, self._prev_arrow_center):
                    self._play_click()
                    self.current_page = (self.current_page - 1) % self.total_pages
                    self._paginate()
                    self._compute_slot_positions()
                    return None

            # Check slot clicks
            slot = self._get_slot_at(event.pos)
            if slot is not None and not slot.is_disabled:
                self._play_click()
                return self._slot_command(slot)

        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close()
            return None

        return None

    def contains_point(self, pos: tuple[int, int]) -> bool:
        """Is *pos* inside the menu's clickable area?"""
        if self.state == RadialMenuState.CLOSED:
            return False

        # Check ring area
        dx = pos[0] - self._center_screen[0]
        dy = pos[1] - self._center_screen[1]
        dist = math.hypot(dx, dy)
        ring_outer = self._outer_radius + self._slot_radius + 16
        if dist <= ring_outer:
            return True

        # Check popup area
        if self.state == RadialMenuState.SPELL_POPUP and self.spell_popup is not None:
            if self.spell_popup.rect.collidepoint(pos):
                return True
        if self.state == RadialMenuState.TACTICS_POPUP and self.tactics_popup is not None:
            if self.tactics_popup.rect.collidepoint(pos):
                return True
        if self.state == RadialMenuState.CANTRIP_POPUP and self.cantrip_popup is not None:
            if self.cantrip_popup.rect.collidepoint(pos):
                return True
        if self.state == RadialMenuState.ITEMS_POPUP and self.items_popup is not None:
            if self.items_popup.rect.collidepoint(pos):
                return True

        return False

    # ── Position Update ──────────────────────────────────────────────

    def update_position(
        self,
        grid_view: GridView,
        combat: CombatManager,
        screen_width: int,
        screen_height: int,
    ) -> None:
        """Recompute screen-space center from current camera state.

        Called every frame by the combat screen when the menu is open.
        """
        self._screen_width = screen_width
        self._screen_height = screen_height

        if self.creature_id is None:
            return
        combatant = combat.get_creature(self.creature_id)
        if combatant is None or combatant.position is None:
            return

        settings = get_settings()
        # Use footprint centroid for multi-hex creatures
        wx, wy = get_footprint_center_pixel(
            combatant.position, combatant.creature.size,
            settings.display.default_hex_size,
        )
        lx, ly = grid_view.camera.world_to_screen(wx, wy)
        ox, oy = grid_view.origin

        self._center_screen = (int(lx) + ox, int(ly) + oy)

        # Scale radii with zoom (clamped)
        zoom = grid_view.camera.zoom
        self._inner_radius = max(30, min(60, int(40 * zoom)))
        self._outer_radius = max(60, min(120, int(90 * zoom)))
        self._slot_radius = max(16, min(28, int(22 * zoom)))
        self._arrow_radius = max(8, min(14, int(12 * zoom)))

        self._compute_slot_positions()

        # Reposition popup if open
        popup_offset = self._outer_radius + self._slot_radius
        if self.state == RadialMenuState.SPELL_POPUP and self.spell_popup is not None:
            self.spell_popup.reposition(self._center_screen, popup_offset)
        if self.state == RadialMenuState.TACTICS_POPUP and self.tactics_popup is not None:
            self.tactics_popup.reposition(self._center_screen, popup_offset)
        if self.state == RadialMenuState.CANTRIP_POPUP and self.cantrip_popup is not None:
            self.cantrip_popup.reposition(self._center_screen, popup_offset)
        if self.state == RadialMenuState.ITEMS_POPUP and self.items_popup is not None:
            self.items_popup.reposition(self._center_screen, popup_offset)

    # ── Rendering ────────────────────────────────────────────────────

    def render(self, surface: pygame.Surface) -> None:
        """Render the radial menu ring, slots, and pagination."""
        if self.state == RadialMenuState.CLOSED:
            return

        # --- Animation progress (opening / closing) ---
        anim_scale = 1.0
        anim_alpha = 255

        if self.state == RadialMenuState.OPENING:
            elapsed = pygame.time.get_ticks() - self._anim_start
            if elapsed >= _MENU_ANIM_DURATION_MS:
                self.state = RadialMenuState.OPEN
            else:
                t = elapsed / _MENU_ANIM_DURATION_MS
                # Ease-out quadratic
                t = 1.0 - (1.0 - t) ** 2
                anim_scale = 0.5 + 0.5 * t  # 0.5 → 1.0
                anim_alpha = int(255 * t)

        elif self.state == RadialMenuState.CLOSING:
            elapsed = pygame.time.get_ticks() - self._anim_start
            if elapsed >= _MENU_ANIM_DURATION_MS:
                self._finish_close()
                return
            else:
                t = elapsed / _MENU_ANIM_DURATION_MS
                # Ease-in quadratic
                t_inv = 1.0 - t * t
                anim_scale = 0.5 + 0.5 * t_inv  # 1.0 → 0.5
                anim_alpha = int(255 * t_inv)

        # --- Render menu content (possibly to a temp surface for animation) ---
        needs_anim = anim_scale < 0.99 or anim_alpha < 250
        if needs_anim:
            cx, cy = self._center_screen
            total_r = self._outer_radius + self._slot_radius + 30
            buf_size = total_r * 2 + 4
            buf = pygame.Surface((buf_size, buf_size), pygame.SRCALPHA)

            # Temporarily shift center so rendering targets the buffer center
            buf_center = (buf_size // 2, buf_size // 2)
            real_center = self._center_screen
            dx = buf_center[0] - cx
            dy = buf_center[1] - cy
            self._center_screen = buf_center
            # Shift slot screen positions too
            real_positions = []
            for slot in self.slots:
                real_positions.append(slot.screen_pos)
                slot.screen_pos = (slot.screen_pos[0] + dx, slot.screen_pos[1] + dy)
            real_next = self._next_arrow_center
            real_prev = self._prev_arrow_center
            self._next_arrow_center = (real_next[0] + dx, real_next[1] + dy)
            self._prev_arrow_center = (real_prev[0] + dx, real_prev[1] + dy)

            # Render into buffer
            self._render_backdrop(buf)
            for slot in self.slots:
                self._render_slot(buf, slot)
            if self.total_pages > 1:
                self._render_pagination(buf)

            # Restore real positions
            self._center_screen = real_center
            for i, slot in enumerate(self.slots):
                slot.screen_pos = real_positions[i]
            self._next_arrow_center = real_next
            self._prev_arrow_center = real_prev

            # Scale from center and apply alpha
            scaled_w = max(1, int(buf_size * anim_scale))
            scaled_h = max(1, int(buf_size * anim_scale))
            scaled = pygame.transform.smoothscale(buf, (scaled_w, scaled_h))
            scaled.set_alpha(anim_alpha)
            surface.blit(scaled, (cx - scaled_w // 2, cy - scaled_h // 2))
        else:
            # No animation needed — render directly
            self._render_backdrop(surface)
            for slot in self.slots:
                self._render_slot(surface, slot)
            if self.total_pages > 1:
                self._render_pagination(surface)

        # Sub-popup (always direct, no animation)
        if self.state == RadialMenuState.SPELL_POPUP and self.spell_popup is not None:
            self.spell_popup.render(surface)
        if self.state == RadialMenuState.TACTICS_POPUP and self.tactics_popup is not None:
            self.tactics_popup.render(surface)
        if self.state == RadialMenuState.CANTRIP_POPUP and self.cantrip_popup is not None:
            self.cantrip_popup.render(surface)
        if self.state == RadialMenuState.ITEMS_POPUP and self.items_popup is not None:
            self.items_popup.render(surface)

    def render_tooltip(self, surface: pygame.Surface) -> None:
        """Render tooltip for the hovered slot (call late in z-order)."""
        if self.state in (RadialMenuState.CLOSED, RadialMenuState.OPENING, RadialMenuState.CLOSING):
            return

        # Sub-popup tooltip
        if self.state == RadialMenuState.SPELL_POPUP and self.spell_popup is not None:
            self.spell_popup.render_tooltip(surface)
            return
        if self.state == RadialMenuState.TACTICS_POPUP and self.tactics_popup is not None:
            self.tactics_popup.render_tooltip(surface)
            return
        if self.state == RadialMenuState.CANTRIP_POPUP and self.cantrip_popup is not None:
            self.cantrip_popup.render_tooltip(surface)
            return
        if self.state == RadialMenuState.ITEMS_POPUP and self.items_popup is not None:
            self.items_popup.render_tooltip(surface)
            return

        if self.hovered_slot is None or not self.hovered_slot.tooltip_lines:
            return

        lines = self.hovered_slot.tooltip_lines
        font = get_font(13)
        padding = 6
        line_height = 17

        max_w = max(font.size(line)[0] for line in lines)
        tw = max_w + padding * 2
        th = len(lines) * line_height + padding * 2

        # Position above the slot
        sx, sy = self.hovered_slot.screen_pos
        tx = sx - tw // 2
        ty = sy - self._slot_radius - th - 6

        # Clamp to screen
        tx = max(4, min(self._screen_width - tw - 4, tx))
        if ty < 4:
            ty = sy + self._slot_radius + 6

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

    # ── Slot Building ────────────────────────────────────────────────

    def _rebuild_slots(self) -> None:
        """Build the full slot list from the active creature's actions."""
        self.all_slots = self._build_slots()
        self._paginate()

    def _build_slots(self) -> list[RadialSlot]:
        """Categorize creature abilities into radial menu slots."""
        if self.combat is None or self.creature_id is None:
            return []

        combatant = self.combat.get_creature(self.creature_id)
        if combatant is None:
            return []

        creature = combatant.creature
        action_used = self.combat.has_used_action
        bonus_used = self.combat.turn_resources.has_used_bonus_action
        slots: list[RadialSlot] = []

        # Track which actions we've already assigned to a category
        categorized_actions: set[str] = set()

        # 1. Weapon attacks (melee_weapon or ranged_weapon)
        for action in creature.actions:
            if (
                action.attack
                and action.attack.attack_type in ("melee_weapon", "ranged_weapon")
            ):
                categorized_actions.add(action.name)
                res_ok, _ = check_resource_cost(creature, action)
                slots.append(RadialSlot(
                    label=action.name,
                    slot_type="attack",
                    action=action,
                    icon_text=self._make_icon(action.name),
                    tooltip_lines=self._build_attack_tooltip(
                        action, creature, slot_type="attack"
                    ),
                    is_disabled=action_used or not res_ok,
                ))

        # 2. Cantrips → single "Cantrips" group slot
        cantrips = self._get_cantrips(creature)
        if cantrips:
            for c in cantrips:
                categorized_actions.add(c.name)
            count = len(cantrips)
            slots.append(RadialSlot(
                label="Cantrips",
                slot_type="cantrip",
                action=None,
                icon_text="CA",
                tooltip_lines=[f"{count} cantrip(s) available"],
                is_disabled=action_used,
            ))

        # 3. Leveled spells → single "Spells" group slot
        leveled = self._get_leveled_spells(creature)
        if leveled:
            count = len(leveled)
            slots.append(RadialSlot(
                label="Spells",
                slot_type="spells",
                action=None,
                icon_text="SP",
                tooltip_lines=[f"{count} spell(s) available"],
                is_disabled=action_used,
            ))

        # 4. Tactics — always present
        slots.append(RadialSlot(
            label="Tactics",
            slot_type="tactics",
            action=None,
            icon_text="TA",
            tooltip_lines=["Dash, Disengage, Dodge, Hide"],
            is_disabled=action_used,
        ))

        # 5. Item + ability actions — uncategorized actions from
        # creature.actions, split by origin: carried items ("Items") vs class
        # abilities like Lay on Hands ("Abilities").
        for group_label, icon, slot_type, group_actions in (
            ("Items", "IT", "items", self._get_item_actions(creature)),
            ("Abilities", "AB", "ability", self._get_ability_actions(creature)),
        ):
            if not group_actions:
                continue
            for a in group_actions:
                categorized_actions.add(a.name)
            if len(group_actions) == 1:
                # Single action: show directly
                a = group_actions[0]
                tip = [a.description] if a.description else [a.name]
                uses_disabled = (
                    a.uses_per_rest is not None
                    and a.current_uses is not None
                    and a.current_uses <= 0
                )
                res_ok, _ = check_resource_cost(creature, a)
                slots.append(RadialSlot(
                    label=a.name,
                    slot_type=slot_type,
                    action=a,
                    icon_text=self._make_icon(a.name),
                    tooltip_lines=tip,
                    is_disabled=action_used or uses_disabled or not res_ok,
                ))
            else:
                # Multiple: group slot
                slots.append(RadialSlot(
                    label=group_label,
                    slot_type=slot_type,
                    action=None,
                    icon_text=icon,
                    tooltip_lines=[f"{len(group_actions)} available"],
                    is_disabled=action_used,
                ))

        # 6. Creature's bonus_actions — individual slots
        for action in creature.bonus_actions:
            tag = self._tooltip_tag(action, "bonus")
            bonus_tip = [tag] if tag else []
            if action.description:
                bonus_tip.append(action.description)
            res_ok, _ = check_resource_cost(creature, action)
            slots.append(RadialSlot(
                label=action.name,
                slot_type="bonus",
                action=action,
                icon_text=self._make_icon(action.name),
                tooltip_lines=bonus_tip,
                is_disabled=bonus_used or not res_ok,
            ))

        # 7. TWF Off-Hand (conditional bonus)
        if self.combat.can_two_weapon_fight():
            slots.append(RadialSlot(
                label="Off-Hand",
                slot_type="bonus",
                action=None,
                icon_text="OH",
                tooltip_lines=["Bonus Action", "Off-hand attack"],
                is_disabled=bonus_used,
            ))

        # 8. Action Surge (Fighter — free, resets action slot)
        class_resources = getattr(creature, "class_resources", None)
        if class_resources and "action_surge" in class_resources:
            surge_remaining = class_resources.get("action_surge", 0)
            slots.append(RadialSlot(
                label="Action Surge",
                slot_type="action_surge",
                action=None,
                icon_text="AS",
                tooltip_lines=[
                    "Action Surge (Fighter)",
                    "Gain an additional action this turn",
                    f"Uses remaining: {surge_remaining}",
                ],
                is_disabled=(surge_remaining <= 0 or not action_used),
            ))

        # 9. Drop Concentration (only when concentrating — free action)
        if has_condition(creature, Condition.CONCENTRATING):
            # Find what spell is being concentrated on
            conc_source = ""
            for ac in creature.active_conditions:
                if ac.condition == Condition.CONCENTRATING:
                    conc_source = ac.extra_data.get("spell", ac.source)
                    break
            slots.append(RadialSlot(
                label="Drop Conc.",
                slot_type="drop_concentration",
                action=None,
                icon_text="DC",
                tooltip_lines=[
                    "Drop Concentration (free action)",
                    f"End concentration on {conc_source}" if conc_source else "End concentration",
                ],
                is_disabled=False,
            ))

        # 9.5. Move Zone (when caster has a movable zone)
        caster_zones = [z for z in self.combat.active_zones
                        if z.caster_id == self.creature_id]
        if caster_zones:
            zone = caster_zones[0]
            # Find the original action that created this zone
            zone_action = None
            for a in creature.actions:
                if a.zone_move_cost and a.name.lower().replace(" ", "_") in zone.zone_id:
                    zone_action = a
                    break
            if zone_action:
                cost_label = "Bonus" if zone_action.zone_move_cost == "bonus_action" else "Action"
                is_used = (
                    self.combat.turn_resources.has_used_bonus_action
                    if zone_action.zone_move_cost == "bonus_action"
                    else self.combat.turn_resources.has_used_action
                )
                slots.append(RadialSlot(
                    label="Move Zone",
                    slot_type="move_zone",
                    action=zone_action,
                    icon_text="MZ",
                    tooltip_lines=[
                        f"Move {zone.name} ({cost_label})",
                        "Click a hex to reposition",
                    ],
                    is_disabled=is_used,
                ))

        # 10. End Turn — always last
        slots.append(RadialSlot(
            label="End Turn",
            slot_type="end_turn",
            action=None,
            icon_text="ET",
            tooltip_lines=["End your turn (Space)"],
            is_disabled=False,
        ))

        return slots

    @staticmethod
    def _get_leveled_spells(creature) -> list[Action]:
        """Return actions that consume a spell slot."""
        result: list[Action] = []
        for action in creature.actions:
            if action.resource_cost:
                if any(k.startswith("spell_slot") for k in action.resource_cost):
                    result.append(action)
        return result

    @staticmethod
    def _get_cantrips(creature) -> list[Action]:
        """Return cantrip actions (spell attack or save, no resource cost)."""
        result: list[Action] = []
        for action in creature.actions:
            if action.resource_cost:
                continue
            is_spell_attack = (
                action.attack
                and action.attack.attack_type in ("melee_spell", "ranged_spell")
            )
            is_save_cantrip = (
                action.saving_throw is not None
                and not action.attack
                and action.action_type == ActionType.ACTION
            )
            if is_spell_attack or is_save_cantrip:
                result.append(action)
        return result

    @staticmethod
    def _get_utility_actions(creature) -> list[Action]:
        """Return non-attack, non-spell actions — consumable uses and class
        abilities. Split by `source_item` into the Items and Abilities slots."""
        result: list[Action] = []
        for action in creature.actions:
            # Skip weapon attacks
            if action.attack and action.attack.attack_type in (
                "melee_weapon", "ranged_weapon",
            ):
                continue
            # Skip cantrips (spell attacks with no resource cost)
            if action.attack and action.attack.attack_type in (
                "melee_spell", "ranged_spell",
            ) and not action.resource_cost:
                continue
            # Skip save-based cantrips
            if (
                action.saving_throw is not None
                and not action.attack
                and action.action_type == ActionType.ACTION
                and not action.resource_cost
                and not action.source_item
            ):
                continue
            # Skip leveled spells (have spell slot cost)
            if action.resource_cost and any(
                k.startswith("spell_slot") for k in action.resource_cost
            ):
                continue
            # What's left: consumable uses, class features, etc.
            result.append(action)
        return result

    @classmethod
    def _get_item_actions(cls, creature) -> list[Action]:
        """Utility actions that come from carried items (potions etc.)."""
        return [a for a in cls._get_utility_actions(creature) if a.source_item]

    @classmethod
    def _get_ability_actions(cls, creature) -> list[Action]:
        """Utility actions that are class abilities (Lay on Hands, Wild
        Shape, Stillness of Mind...) — not items, so they get their own slot."""
        return [a for a in cls._get_utility_actions(creature) if not a.source_item]

    @staticmethod
    def _make_icon(name: str) -> str:
        """Build 1-3 character icon text from an action name."""
        words = name.split()
        if len(words) >= 2:
            return (words[0][0] + words[1][0]).upper()
        return name[:3].capitalize()

    def _build_attack_tooltip(
        self, action: Action, creature, *, slot_type: str = "attack"
    ) -> list[str]:
        """Build tooltip lines for an attack action.

        The first line is a type/economy tag such as
        ``"Cantrip \u2022 Action"`` or ``"Weapon \u2022 Bonus Action"``.
        """
        lines: list[str] = []

        # Type + action economy tag
        tag = self._tooltip_tag(action, slot_type)
        if tag:
            lines.append(tag)

        atk = action.attack
        if atk is None:
            if action.description:
                lines.append(action.description)
            return lines

        ability_mod = creature.ability_scores.get_modifier(atk.ability)
        attack_bonus = ability_mod + creature.proficiency_bonus
        attack_bonus += get_weapon_attack_bonus(creature, action.source_item)
        sign = "+" if attack_bonus >= 0 else ""
        lines.append(f"{sign}{attack_bonus} to hit")

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

        if atk.attack_type.startswith("ranged"):
            range_str = f"Range: {atk.range_normal or atk.reach} ft"
            if atk.range_long:
                range_str += f" / {atk.range_long} ft"
            lines.append(range_str)
        else:
            lines.append(f"Reach: {atk.reach} ft")

        return lines

    @staticmethod
    def _tooltip_tag(action: Action, slot_type: str) -> str:
        """Build a short type + action economy tag for a tooltip.

        Examples: ``"Weapon \u2022 Action"``, ``"Cantrip \u2022 Action"``,
        ``"Spell (1st) \u2022 Action"``, ``"Bonus Action"``.
        """
        # Determine type label
        if slot_type == "cantrip":
            type_label = "Cantrip"
        elif slot_type == "attack":
            type_label = "Weapon"
        elif slot_type == "spells":
            # Extract spell level from resource_cost
            level = 0
            for key in action.resource_cost:
                if key.startswith("spell_slot_"):
                    try:
                        level = int(key.split("_")[-1])
                    except ValueError:
                        pass
            if level > 0:
                ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(level, f"{level}th")
                type_label = f"Spell ({ordinal})"
            else:
                type_label = "Spell"
        elif slot_type == "bonus":
            type_label = ""
        else:
            type_label = ""

        # Determine economy label
        economy = {
            ActionType.ACTION: "Action",
            ActionType.BONUS_ACTION: "Bonus Action",
            ActionType.REACTION: "Reaction",
            ActionType.FREE: "Free",
        }.get(action.action_type, "Action")

        if type_label and economy:
            return f"{type_label} \u2022 {economy}"
        elif economy:
            return economy
        return ""

    # ── Pagination ───────────────────────────────────────────────────

    def _paginate(self) -> None:
        """Split all_slots into pages."""
        total = len(self.all_slots)
        if total <= MAX_SLOTS_PER_PAGE:
            self.slots = list(self.all_slots)
            self.total_pages = 1
            self.current_page = 0
        else:
            self.total_pages = math.ceil(total / MAX_SLOTS_PER_PAGE)
            self.current_page = min(self.current_page, self.total_pages - 1)
            start = self.current_page * MAX_SLOTS_PER_PAGE
            end = min(start + MAX_SLOTS_PER_PAGE, total)
            self.slots = list(self.all_slots[start:end])

    # ── Geometry ─────────────────────────────────────────────────────

    def _compute_slot_positions(self) -> None:
        """Compute screen positions for each slot on the current page."""
        n = len(self.slots)
        if n == 0:
            return
        cx, cy = self._center_screen
        for i, slot in enumerate(self.slots):
            angle = -math.pi / 2 + (2 * math.pi * i / n)
            slot.angle = angle
            slot.screen_pos = (
                int(cx + self._outer_radius * math.cos(angle)),
                int(cy + self._outer_radius * math.sin(angle)),
            )

        # Arrow positions (3-o-clock and 9-o-clock, outside the ring)
        arrow_dist = self._outer_radius + self._slot_radius + 16
        self._next_arrow_center = (int(cx + arrow_dist), cy)
        self._prev_arrow_center = (int(cx - arrow_dist), cy)

    def _get_slot_at(self, pos: tuple[int, int]) -> RadialSlot | None:
        """Find the slot under the given screen position."""
        for slot in self.slots:
            dx = pos[0] - slot.screen_pos[0]
            dy = pos[1] - slot.screen_pos[1]
            if math.hypot(dx, dy) <= self._slot_radius:
                return slot
        return None

    def _point_in_arrow(
        self, pos: tuple[int, int], arrow_center: tuple[int, int]
    ) -> bool:
        """Check if pos is inside a pagination arrow circle."""
        dx = pos[0] - arrow_center[0]
        dy = pos[1] - arrow_center[1]
        return math.hypot(dx, dy) <= self._arrow_radius

    def _update_hover(self, pos: tuple[int, int]) -> None:
        """Update hover state for slots and arrows."""
        self.hovered_slot = self._get_slot_at(pos)

        self._hovered_arrow = None
        if self.total_pages > 1:
            if self._point_in_arrow(pos, self._next_arrow_center):
                self._hovered_arrow = "next"
            elif self._point_in_arrow(pos, self._prev_arrow_center):
                self._hovered_arrow = "prev"

    # ── Slot Command Mapping ─────────────────────────────────────────

    def _slot_command(self, slot: RadialSlot) -> str | None:
        """Map a slot click to a command string."""
        if slot.slot_type == "end_turn":
            return "end_turn"
        elif slot.slot_type == "spells":
            return "open_spells"
        elif slot.slot_type == "tactics":
            return "open_tactics"
        elif slot.slot_type == "cantrip":
            return "open_cantrips"
        elif slot.slot_type == "attack":
            if slot.action:
                return f"action:{slot.action.name}"
        elif slot.slot_type == "items":
            if slot.action:
                # Single item action — direct command
                return f"action:{slot.action.name}"
            else:
                # Group slot — open items popup
                return "open_items"
        elif slot.slot_type == "ability":
            if slot.action:
                return f"action:{slot.action.name}"
            else:
                return "open_abilities"
        elif slot.slot_type == "bonus":
            if slot.action:
                # Named bonus action (e.g., Second Wind)
                return f"bonus_action:{slot.action.name}"
            else:
                # TWF Off-Hand
                return "bonus:offhand"
        elif slot.slot_type == "action_surge":
            return "standard:action_surge"
        elif slot.slot_type == "drop_concentration":
            return "drop_concentration"
        elif slot.slot_type == "move_zone":
            return "move_zone"
        return None

    # ── Render Helpers ───────────────────────────────────────────────

    def _render_backdrop(self, surface: pygame.Surface) -> None:
        """Render semi-transparent annular backdrop."""
        cx, cy = self._center_screen
        total_r = self._outer_radius + self._slot_radius + 8

        # Create a temporary surface with alpha
        size = total_r * 2 + 4
        temp = pygame.Surface((size, size), pygame.SRCALPHA)
        center = (size // 2, size // 2)

        # Draw outer filled circle
        pygame.draw.circle(temp, (30, 24, 18, 120), center, total_r)
        # Cut out inner circle (draw transparent)
        pygame.draw.circle(temp, (0, 0, 0, 0), center, self._inner_radius - 2)

        surface.blit(temp, (cx - size // 2, cy - size // 2))

    def _render_slot(self, surface: pygame.Surface, slot: RadialSlot) -> None:
        """Render a single slot circle."""
        sx, sy = slot.screen_pos
        r = self._slot_radius

        # Fill color
        if slot.is_disabled:
            fill = parse_color(COLORS["radial_slot_disabled"])
        elif slot == self.hovered_slot:
            fill = parse_color(COLORS["radial_slot_hover"])
        else:
            color_key = SLOT_COLORS.get(slot.slot_type, "button_normal")
            fill = parse_color(COLORS[color_key])

        pygame.draw.circle(surface, fill, (sx, sy), r)
        pygame.draw.circle(
            surface,
            parse_color(COLORS["border_accent"]),
            (sx, sy),
            r,
            2,
        )

        # Icon image or fallback text inside the circle
        icon_size = max(16, int(r * 1.4))
        icon_surf = get_icon(slot.label, icon_size)
        if icon_surf is not None:
            if slot.is_disabled:
                # Dim the icon for disabled slots
                dimmed = icon_surf.copy()
                dark = pygame.Surface(dimmed.get_size(), pygame.SRCALPHA)
                dark.fill((0, 0, 0, 140))
                dimmed.blit(dark, (0, 0))
                icon_surf = dimmed
            icon_rect = icon_surf.get_rect(center=(sx, sy))
            surface.blit(icon_surf, icon_rect)
        else:
            font_size = max(10, min(16, int(14 * (r / 22))))
            font = get_font(font_size)
            text_color = (100, 100, 100) if slot.is_disabled else parse_color(COLORS["text_primary"])
            text_surf = font.render(slot.icon_text, True, text_color)
            text_rect = text_surf.get_rect(center=(sx, sy - 2))
            surface.blit(text_surf, text_rect)

        # Label below the circle
        if r >= 16:
            label_font_size = max(10, min(13, int(12 * (r / 22))))
            label_font = get_font(label_font_size)
            label_color = (100, 100, 100) if slot.is_disabled else parse_color(COLORS["text_secondary"])
            label_surf = label_font.render(slot.label, True, label_color)
            label_rect = label_surf.get_rect(center=(sx, sy + r + 10))
            surface.blit(label_surf, label_rect)

    def _render_pagination(self, surface: pygame.Surface) -> None:
        """Render pagination arrows and page indicator."""
        # Page indicator text
        cx, cy = self._center_screen
        font = get_font(10)
        page_text = f"{self.current_page + 1}/{self.total_pages}"
        page_surf = font.render(
            page_text,
            True,
            parse_color(COLORS["text_secondary"]),
        )
        page_rect = page_surf.get_rect(
            center=(cx, cy + self._outer_radius + self._slot_radius + 24)
        )
        surface.blit(page_surf, page_rect)

        # Next arrow (right side) — right-pointing triangle
        self._render_arrow(
            surface,
            self._next_arrow_center,
            direction=1,
            hovered=self._hovered_arrow == "next",
        )

        # Prev arrow (left side) — left-pointing triangle
        self._render_arrow(
            surface,
            self._prev_arrow_center,
            direction=-1,
            hovered=self._hovered_arrow == "prev",
        )

    def _render_arrow(
        self,
        surface: pygame.Surface,
        center: tuple[int, int],
        direction: int,
        hovered: bool,
    ) -> None:
        """Render a pagination arrow (triangle inside a circle)."""
        r = self._arrow_radius
        cx, cy = center

        # Circle backdrop
        fill = (
            parse_color(COLORS["button_hover"])
            if hovered
            else parse_color(COLORS["button_normal"])
        )
        pygame.draw.circle(surface, fill, (cx, cy), r)
        pygame.draw.circle(
            surface,
            parse_color(COLORS["border_accent"]),
            (cx, cy),
            r,
            1,
        )

        # Triangle
        half = r * 0.5
        if direction > 0:  # right-pointing
            points = [
                (cx - half * 0.6, cy - half),
                (cx + half * 0.8, cy),
                (cx - half * 0.6, cy + half),
            ]
        else:  # left-pointing
            points = [
                (cx + half * 0.6, cy - half),
                (cx - half * 0.8, cy),
                (cx + half * 0.6, cy + half),
            ]
        arrow_color = parse_color(COLORS["radial_arrow"])
        pygame.draw.polygon(surface, arrow_color, points)

    @staticmethod
    def _play_click() -> None:
        """Play a button click sound."""
        from arena.audio.manager import get_sound_manager
        get_sound_manager().play_sfx("button_click")
