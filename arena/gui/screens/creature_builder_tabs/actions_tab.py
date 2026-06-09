"""Actions tab — master-detail action editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from arena.gui.renderer import draw_text_centered, get_font
from arena.gui.widgets import TextInput, NumberSpinner, Dropdown, Checkbox, ListEditor
from arena.util.constants import COLORS, parse_color

if TYPE_CHECKING:
    from arena.gui.screens.character_builder import CreatureBuilderScreen

# Action categories
BASE_CATEGORIES = ["actions", "bonus_actions", "reactions"]
MONSTER_CATEGORIES = ["actions", "bonus_actions", "reactions",
                      "legendary_actions", "lair_actions"]

CATEGORY_LABELS = {
    "actions": "Actions",
    "bonus_actions": "Bonus Actions",
    "reactions": "Reactions",
    "legendary_actions": "Legendary Actions",
    "lair_actions": "Lair Actions",
}

TARGET_TYPES = [
    "self", "one_creature", "one_ally", "one_enemy",
    "area_sphere", "area_cone", "area_line", "area_cube", "area_cylinder",
]

ATTACK_TYPES = [
    "melee_weapon", "ranged_weapon", "melee_spell", "ranged_spell",
]

ABILITY_OPTIONS = [
    "strength", "dexterity", "constitution",
    "intelligence", "wisdom", "charisma",
]

DAMAGE_TYPES = [
    "acid", "bludgeoning", "cold", "fire", "force", "lightning",
    "necrotic", "piercing", "poison", "psychic", "radiant",
    "slashing", "thunder",
]

SAVE_ON_SUCCESS = ["none", "half", "full"]

CONDITION_VALUES = [
    "blinded", "charmed", "deafened", "exhaustion", "frightened",
    "grappled", "incapacitated", "invisible", "paralyzed", "petrified",
    "poisoned", "prone", "restrained", "stunned", "unconscious",
    "concentrating", "dodging", "helped", "hidden",
]

SPELL_LEVEL_OPTIONS = [
    "(not a spell)", "cantrip",
    "1st level", "2nd level", "3rd level", "4th level", "5th level",
    "6th level", "7th level", "8th level", "9th level",
]

# Collapsible section identifiers
SECTION_SPELL_SCALING = "spell_scaling"
SECTION_MULTI_TARGET = "multi_target"
SECTION_CONDITION_OPTIONS = "condition_options"
SECTION_CREATURE_TYPE_BONUS = "creature_type_bonus"
SECTION_HP_THRESHOLD = "hp_threshold"
SECTION_REACTION_TRIGGER = "reaction_trigger"
SECTION_CHAIN_EFFECT = "chain_effect"
SECTION_COUNTERSPELL = "counterspell"
SECTION_WALL_SPELL = "wall_spell"
SECTION_RECURRING_ACTION = "recurring_action"

SECTION_TITLES = {
    SECTION_SPELL_SCALING: "Spell Scaling",
    SECTION_MULTI_TARGET: "Multi-Target",
    SECTION_CONDITION_OPTIONS: "Condition Options",
    SECTION_CREATURE_TYPE_BONUS: "Creature Type Bonus",
    SECTION_HP_THRESHOLD: "HP Threshold",
    SECTION_REACTION_TRIGGER: "Reaction Trigger",
    SECTION_CHAIN_EFFECT: "Chain Effect",
    SECTION_COUNTERSPELL: "Counterspell",
    SECTION_WALL_SPELL: "Wall Spell",
    SECTION_RECURRING_ACTION: "Recurring Action",
}

HP_THRESHOLD_EFFECTS = ["(none)", "kill", "condition", "bonus_damage_die"]
CONDITION_DURATION_TYPES = ["indefinite", "rounds", "end_of_turn", "start_of_turn"]

CREATURE_TYPES = [
    "aberration", "beast", "celestial", "construct", "dragon",
    "elemental", "fey", "fiend", "giant", "humanoid",
    "monstrosity", "ooze", "plant", "undead",
]

# Detail panel origin offset from content area
LIST_PANEL_WIDTH = 340
DETAIL_PANEL_X_OFFSET = LIST_PANEL_WIDTH + 20


def _get_animation_options() -> list[str]:
    """Return available animation folder names for the dropdown.

    Uses a lazy import to avoid importing pygame-dependent code at module
    load time (the builder tab modules are imported before pygame.init).
    """
    try:
        from arena.gui.animation_cache import get_available_animations
        return get_available_animations()
    except Exception:
        return []


class ActionsTab:
    """Renders and handles the Actions tab with master-detail layout."""

    def __init__(self, screen: CreatureBuilderScreen) -> None:
        self.screen = screen

        self.selected_category: str | None = None
        self.selected_action_index: int | None = None
        self.detail_scroll_y = 0
        self._prev_scroll_y = 0  # for computing scroll delta

        # List panel scroll
        self.list_scroll_y = 0

        # Hover state for add buttons
        self.add_hover_cat: str | None = None

        # Detail widgets (created/refreshed when an action is selected)
        self._detail_widgets: dict | None = None
        self._detail_dropdowns: list[Dropdown] = []
        self._detail_list_editors: list[ListEditor] = []
        self._detail_content_height: int = 0

        # Equipment-sourced action flag
        self._is_equipment_sourced: bool = False

        # Collapsible section state
        self._section_expanded: dict[str, bool] = {
            SECTION_SPELL_SCALING: False,
            SECTION_MULTI_TARGET: False,
            SECTION_CONDITION_OPTIONS: False,
            SECTION_CREATURE_TYPE_BONUS: False,
            SECTION_HP_THRESHOLD: False,
            SECTION_REACTION_TRIGGER: False,
            SECTION_CHAIN_EFFECT: False,
            SECTION_COUNTERSPELL: False,
            SECTION_WALL_SPELL: False,
            SECTION_RECURRING_ACTION: False,
        }
        self._section_header_rects: dict[str, pygame.Rect] = {}

    def _get_categories(self) -> list[str]:
        from arena.gui.screens.character_builder import CreatureMode
        if self.screen.creature_mode == CreatureMode.CHARACTER:
            return BASE_CATEGORIES
        return MONSTER_CATEGORIES

    def _get_list_content_height(self) -> int:
        """Compute total pixel height of the list panel content."""
        item_h = 28
        gap = 4
        total = 0
        for cat in self._get_categories():
            total += 28  # header
            actions = self.screen.actions_data.get(cat, [])
            if actions:
                total += len(actions) * (item_h + gap)
            else:
                total += 20
            total += 10  # gap between categories
        return total

    def _get_list_panel_rect(self) -> pygame.Rect:
        """Return the clipping rect for the list panel area."""
        return pygame.Rect(
            self.screen.content_rect.x,
            self.screen.content_rect.y,
            LIST_PANEL_WIDTH,
            self.screen.content_rect.height,
        )

    def _get_selected_action(self) -> dict | None:
        if (self.selected_category and self.selected_action_index is not None):
            actions = self.screen.actions_data.get(self.selected_category, [])
            if 0 <= self.selected_action_index < len(actions):
                return actions[self.selected_action_index]
        return None

    # ------------------------------------------------------------------
    # Scroll offset management
    # ------------------------------------------------------------------

    def _shift_widget_rects(self, dy: int) -> None:
        """Shift all detail-panel widget rects by *dy* pixels vertically.

        This keeps hit-testing rects in sync with where widgets are rendered
        after scrolling.  Each widget type stores geometry in ``rect`` (and
        sometimes derived sub-rects), so we patch them all.
        """
        if dy == 0:
            return

        # Shift section header rects
        for rect in self._section_header_rects.values():
            rect.y += dy

        if not self._detail_widgets:
            return

        for widget in self._detail_widgets.values():
            if hasattr(widget, "rect"):
                widget.rect.y += dy
            # NumberSpinner stores sub-rects
            if isinstance(widget, NumberSpinner):
                widget.minus_btn.y += dy
                widget.plus_btn.y += dy
            # Checkbox stores sub-rect
            if isinstance(widget, Checkbox):
                widget.box_rect.y += dy
            # ListEditor stores layout rects
            if isinstance(widget, ListEditor):
                widget.content_y += dy
                widget.add_btn.y += dy

    def _apply_scroll(self, new_scroll: int) -> None:
        """Set scroll position and shift widget rects by the delta."""
        delta = self._prev_scroll_y - new_scroll
        self.detail_scroll_y = new_scroll
        self._prev_scroll_y = new_scroll
        self._shift_widget_rects(delta)

    # ------------------------------------------------------------------
    # Collapsible section helpers
    # ------------------------------------------------------------------

    def _is_section_active(self, section_id: str, action: dict) -> bool:
        """Return True if any field in the section has a non-default value."""
        if section_id == SECTION_SPELL_SCALING:
            return (
                action.get("cantrip_scaling", False)
                or action.get("cantrip_extra_targets", False)
                or bool(action.get("upcast_damage_dice"))
                or bool(action.get("upcast_healing_dice"))
                or (action.get("upcast_damage_per_levels", 1) or 1) != 1
                or (action.get("upcast_target_count", 0) or 0) > 0
            )
        if section_id == SECTION_MULTI_TARGET:
            return (
                (action.get("target_count", 1) or 1) > 1
                or bool(action.get("damage_type_choices"))
            )
        if section_id == SECTION_CONDITION_OPTIONS:
            return (
                bool(action.get("condition_save_to_end"))
                or (action.get("condition_save_to_end_dc", 0) or 0) > 0
                or (action.get("condition_duration_type", "indefinite") or "indefinite") != "indefinite"
                or (action.get("condition_duration_rounds", 0) or 0) > 0
            )
        if section_id == SECTION_CREATURE_TYPE_BONUS:
            return (
                bool(action.get("creature_type_bonus_damage"))
                or bool(action.get("creature_type_bonus_types"))
            )
        if section_id == SECTION_HP_THRESHOLD:
            return (
                (action.get("hp_threshold", 0) or 0) > 0
                or bool(action.get("hp_threshold_effect"))
            )
        if section_id == SECTION_REACTION_TRIGGER:
            return bool(action.get("reaction_trigger"))
        if section_id == SECTION_CHAIN_EFFECT:
            return (action.get("chain_target_count", 0) or 0) > 0
        if section_id == SECTION_COUNTERSPELL:
            return bool(action.get("is_counterspell"))
        if section_id == SECTION_WALL_SPELL:
            return bool(action.get("is_wall"))
        if section_id == SECTION_RECURRING_ACTION:
            return bool(action.get("recurring_action_type"))
        return False

    def _build_section_header(
        self, section_id: str, ox: int, cy: int, w: int,
    ) -> int:
        """Store a header rect for the section. Returns new cy after header."""
        self._section_header_rects[section_id] = pygame.Rect(
            ox, cy, w, 26,
        )
        return cy + 30

    def _render_section_header(
        self, surface: pygame.Surface, section_id: str,
        action: dict,
    ) -> None:
        """Draw a collapsible section header bar with triangle + title + dot."""
        rect = self._section_header_rects.get(section_id)
        if rect is None:
            return

        font = get_font(13)
        expanded = self._section_expanded.get(section_id, False)
        active = self._is_section_active(section_id, action)
        title = SECTION_TITLES.get(section_id, section_id)

        # Background bar
        bar_color = parse_color(COLORS.get("bg_medium", "#2a2018"))
        pygame.draw.rect(surface, bar_color, rect, border_radius=3)
        border_color = parse_color(COLORS.get("border_accent", "#6b5530"))
        pygame.draw.rect(surface, border_color, rect, 1, border_radius=3)

        # Triangle indicator
        tri_x = rect.x + 10
        tri_cy = rect.centery
        tri_color = parse_color(COLORS.get("text_gold", "#d4a843"))
        if expanded:
            # Downward triangle ▼
            pts = [(tri_x, tri_cy - 4), (tri_x + 8, tri_cy - 4), (tri_x + 4, tri_cy + 4)]
        else:
            # Right triangle ▶
            pts = [(tri_x, tri_cy - 5), (tri_x, tri_cy + 5), (tri_x + 7, tri_cy)]
        pygame.draw.polygon(surface, tri_color, pts)

        # Title text
        text_color = parse_color(COLORS["text_primary"])
        title_surf = font.render(title, True, text_color)
        surface.blit(title_surf, (rect.x + 24, rect.y + 4))

        # Active indicator dot (gold circle)
        if active:
            dot_x = rect.right - 16
            dot_y = rect.centery
            pygame.draw.circle(surface, tri_color, (dot_x, dot_y), 5)

    # ------------------------------------------------------------------
    # Detail panel — widget building helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_damage_row(
        widgets: dict, prefix: str, dmg: dict,
        ox: int, y: int, w: int,
    ) -> None:
        """Create one row of damage widgets (dice / type / modifier / bonus)."""
        widgets[f"{prefix}_dice"] = TextInput(
            pygame.Rect(ox, y, 65, 26),
            value=dmg.get("dice", ""),
            placeholder="e.g. 1d8",
            max_length=10,
        )
        dmg_type = dmg.get("damage_type", "slashing")
        widgets[f"{prefix}_type"] = Dropdown(
            pygame.Rect(ox + 70, y, 110, 26),
            DAMAGE_TYPES,
        )
        try:
            widgets[f"{prefix}_type"].selected_index = DAMAGE_TYPES.index(dmg_type)
        except ValueError:
            pass

        mod = dmg.get("ability_modifier", "")
        mod_opts = ["(none)"] + ABILITY_OPTIONS
        widgets[f"{prefix}_mod"] = Dropdown(
            pygame.Rect(ox + 185, y, 130, 26),
            mod_opts,
        )
        try:
            if mod:
                widgets[f"{prefix}_mod"].selected_index = mod_opts.index(mod)
        except ValueError:
            pass

        widgets[f"{prefix}_bonus"] = NumberSpinner(
            pygame.Rect(ox + 320, y, 90, 26),
            value=dmg.get("bonus", 0),
            min_val=-10, max_val=30,
        )

    @staticmethod
    def _read_damage_row(widgets: dict, prefix: str) -> dict | None:
        """Read one row of damage widgets into a dict (or None if empty)."""
        dice_w = widgets.get(f"{prefix}_dice")
        if not dice_w or not dice_w.value:
            return None
        mod_val = widgets[f"{prefix}_mod"].value
        bonus = widgets[f"{prefix}_bonus"].value
        entry: dict = {
            "dice": dice_w.value,
            "damage_type": widgets[f"{prefix}_type"].value,
        }
        if mod_val and mod_val != "(none)":
            entry["ability_modifier"] = mod_val
        if bonus != 0:
            entry["bonus"] = bonus
        return entry

    # ------------------------------------------------------------------
    # Spell level detection helper
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_spell_level(action: dict) -> int:
        """Return the SPELL_LEVEL_OPTIONS index for an action's current data.

        Detection logic mirrors the radial menu classification:
        - resource_cost has ``spell_slot_N`` key → "Nth level"
        - spell attack type or save-only cantrip pattern → "cantrip"
        - otherwise → "(not a spell)"
        """
        resource_cost = action.get("resource_cost") or {}
        for key in resource_cost:
            if key.startswith("spell_slot_"):
                try:
                    lvl = int(key.split("_")[-1])
                    if 1 <= lvl <= 9:
                        return lvl + 1  # index 2 = "1st level", etc.
                except (ValueError, IndexError):
                    pass
            elif key.startswith("spell_slot"):
                # Generic "spell_slot" without level number — treat as 1st
                return 2

        # Check for cantrip pattern: spell attack type or save-only spell
        attack = action.get("attack")
        if attack:
            atk_type = attack.get("attack_type", "")
            if atk_type in ("melee_spell", "ranged_spell"):
                return 1  # "cantrip"
        elif action.get("saving_throw") is not None:
            # Save-only with no attack and no spell slot → cantrip
            return 1  # "cantrip"

        return 0  # "(not a spell)"

    # ------------------------------------------------------------------
    # Detail panel — build all widgets
    # ------------------------------------------------------------------

    def _build_detail_widgets(self) -> None:
        """Create/refresh widgets for the currently selected action."""
        action = self._get_selected_action()
        if action is None:
            self._detail_widgets = None
            self._detail_dropdowns = []
            self._detail_list_editors = []
            self._detail_content_height = 0
            self._is_equipment_sourced = False
            return

        # Equipment-sourced actions are read-only
        self._is_equipment_sourced = action.get("source_item") is not None
        if self._is_equipment_sourced:
            self._detail_widgets = {"_readonly": True}
            self._detail_dropdowns = []
            self._detail_list_editors = []
            self._detail_content_height = 60
            return

        # Reset scroll on new selection
        self.detail_scroll_y = 0
        self._prev_scroll_y = 0

        ox = self.screen.content_rect.x + DETAIL_PANEL_X_OFFSET
        oy = self.screen.content_rect.y + 10
        w = self.screen.content_rect.width - DETAIL_PANEL_X_OFFSET - 20

        widgets: dict = {}
        cy = oy  # dynamic y cursor

        # ============================================================
        # HEADER: Name, Description, Target / Range / Area
        # ============================================================
        widgets["name"] = TextInput(
            pygame.Rect(ox, cy + 18, w, 26),
            value=action.get("name", ""),
            placeholder="Action name...",
        )
        cy += 44

        widgets["description"] = TextInput(
            pygame.Rect(ox, cy + 18, w, 26),
            value=action.get("description", ""),
            max_length=120,
            placeholder="Description...",
        )
        cy += 48

        target = action.get("target_type", "one_creature")
        widgets["target_type"] = Dropdown(
            pygame.Rect(ox, cy + 16, 180, 26),
            TARGET_TYPES,
        )
        try:
            widgets["target_type"].selected_index = TARGET_TYPES.index(target)
        except ValueError:
            pass

        widgets["range"] = NumberSpinner(
            pygame.Rect(ox + 200, cy + 16, 140, 26),
            value=action.get("range", 5),
            min_val=0, max_val=300, step=5,
        )
        widgets["area_size"] = NumberSpinner(
            pygame.Rect(ox + 360, cy + 16, 120, 26),
            value=action.get("area_size", 0) or 0,
            min_val=0, max_val=120, step=5,
        )
        cy += 48

        # ============================================================
        # SPELL LEVEL (classification for radial menu grouping)
        # ============================================================
        spell_level_idx = self._detect_spell_level(action)
        widgets["spell_level"] = Dropdown(
            pygame.Rect(ox, cy + 16, 180, 26),
            SPELL_LEVEL_OPTIONS,
        )
        widgets["spell_level"].selected_index = spell_level_idx
        cy += 48

        # ============================================================
        # ANIMATION (visual effect played during combat)
        # ============================================================
        anim_options = ["(none)"] + _get_animation_options()
        widgets["animation"] = Dropdown(
            pygame.Rect(ox + 200, cy + 16, 200, 26),
            anim_options,
        )
        current_anim = action.get("animation") or "(none)"
        try:
            widgets["animation"].selected_index = anim_options.index(current_anim)
        except ValueError:
            widgets["animation"].selected_index = 0
        cy += 48

        # ============================================================
        # ATTACK SECTION (collapsible)
        # ============================================================
        has_attack = action.get("attack") is not None
        widgets["has_attack"] = Checkbox(
            pygame.Rect(ox, cy, 200, 24),
            "Has Attack",
            checked=has_attack,
        )
        cy += 28

        attack = action.get("attack", {}) or {}

        if has_attack:
            atk_type = attack.get("attack_type", "melee_weapon")
            widgets["attack_type"] = Dropdown(
                pygame.Rect(ox, cy + 2, 180, 26),
                ATTACK_TYPES,
            )
            try:
                widgets["attack_type"].selected_index = ATTACK_TYPES.index(atk_type)
            except ValueError:
                pass

            atk_ability = attack.get("ability", "strength")
            widgets["attack_ability"] = Dropdown(
                pygame.Rect(ox + 200, cy + 2, 160, 26),
                ABILITY_OPTIONS,
            )
            try:
                widgets["attack_ability"].selected_index = ABILITY_OPTIONS.index(atk_ability)
            except ValueError:
                pass
            cy += 32

            widgets["reach"] = NumberSpinner(
                pygame.Rect(ox, cy + 2, 120, 26),
                value=attack.get("reach", 5),
                min_val=0, max_val=30, step=5,
            )
            widgets["range_normal"] = NumberSpinner(
                pygame.Rect(ox + 140, cy + 2, 120, 26),
                value=attack.get("range_normal", 0) or 0,
                min_val=0, max_val=600, step=5,
            )
            widgets["range_long"] = NumberSpinner(
                pygame.Rect(ox + 280, cy + 2, 120, 26),
                value=attack.get("range_long", 0) or 0,
                min_val=0, max_val=600, step=5,
            )
            cy += 32

            # Damage rolls header
            cy += 4  # small gap
            damage_list = attack.get("damage", [])
            for di in range(3):
                dmg = damage_list[di] if di < len(damage_list) else {}
                self._build_damage_row(widgets, f"dmg_{di}", dmg, ox, cy, w)
                cy += 30
            cy += 4

        # ============================================================
        # SAVING THROW SECTION (collapsible)
        # ============================================================
        has_save = action.get("saving_throw") is not None
        widgets["has_save"] = Checkbox(
            pygame.Rect(ox, cy, 200, 24),
            "Has Saving Throw",
            checked=has_save,
        )
        cy += 28

        if has_save:
            save = action.get("saving_throw", {}) or {}

            # Row 1: Save Ability | DC | DC Ability | On Success
            save_ability = save.get("ability", "dexterity")
            widgets["save_ability"] = Dropdown(
                pygame.Rect(ox, cy, 120, 26),
                ABILITY_OPTIONS,
            )
            try:
                widgets["save_ability"].selected_index = ABILITY_OPTIONS.index(save_ability)
            except ValueError:
                pass

            widgets["save_dc"] = NumberSpinner(
                pygame.Rect(ox + 130, cy, 90, 26),
                value=save.get("dc", 10) or 10,
                min_val=1, max_val=30,
            )

            dc_ability_opts = ["(none)"] + ABILITY_OPTIONS
            dc_ability = save.get("dc_ability", "") or ""
            widgets["save_dc_ability"] = Dropdown(
                pygame.Rect(ox + 230, cy, 130, 26),
                dc_ability_opts,
            )
            try:
                if dc_ability:
                    widgets["save_dc_ability"].selected_index = dc_ability_opts.index(dc_ability)
            except ValueError:
                pass

            on_success = save.get("damage_on_success", "none")
            widgets["save_on_success"] = Dropdown(
                pygame.Rect(ox + 370, cy, 100, 26),
                SAVE_ON_SUCCESS,
            )
            try:
                widgets["save_on_success"].selected_index = SAVE_ON_SUCCESS.index(on_success)
            except ValueError:
                pass
            cy += 34

            # Damage on Fail (2 rows)
            cy += 2
            fail_dmg_list = save.get("damage_on_fail", [])
            for fi in range(2):
                fdmg = fail_dmg_list[fi] if fi < len(fail_dmg_list) else {}
                self._build_damage_row(widgets, f"fail_dmg_{fi}", fdmg, ox, cy, w)
                cy += 30

            # Conditions on Fail / on Success (side-by-side ListEditors)
            cy += 6
            half_w = (w - 10) // 2
            cond_fail = save.get("conditions_on_fail", [])
            cond_success = save.get("conditions_on_success", [])

            widgets["save_cond_fail"] = ListEditor(
                pygame.Rect(ox, cy + 16, half_w, 76),
                items=list(cond_fail),
                allowed_values=CONDITION_VALUES,
            )
            widgets["save_cond_success"] = ListEditor(
                pygame.Rect(ox + half_w + 10, cy + 16, half_w, 76),
                items=list(cond_success),
                allowed_values=CONDITION_VALUES,
            )
            cy += 96

        # ============================================================
        # COLLAPSIBLE SECTIONS (new primitive fields)
        # ============================================================
        self._section_header_rects = {}

        # --- Spell Scaling ---
        cy += 6
        cy = self._build_section_header(SECTION_SPELL_SCALING, ox, cy, w)
        if self._section_expanded[SECTION_SPELL_SCALING]:
            widgets["cantrip_scaling"] = Checkbox(
                pygame.Rect(ox + 10, cy, 160, 24),
                "Cantrip Scaling",
                checked=action.get("cantrip_scaling", False),
            )
            widgets["cantrip_extra_targets"] = Checkbox(
                pygame.Rect(ox + 180, cy, 220, 24),
                "Extra Targets (Eldritch Blast)",
                checked=action.get("cantrip_extra_targets", False),
            )
            cy += 30

            widgets["upcast_damage_dice"] = TextInput(
                pygame.Rect(ox + 10, cy + 16, 120, 26),
                value=action.get("upcast_damage_dice", "") or "",
                placeholder="e.g. 1d6",
                max_length=10,
            )
            widgets["upcast_healing_dice"] = TextInput(
                pygame.Rect(ox + 200, cy + 16, 120, 26),
                value=action.get("upcast_healing_dice", "") or "",
                placeholder="e.g. 1d8",
                max_length=10,
            )
            cy += 46

            widgets["upcast_per_levels"] = NumberSpinner(
                pygame.Rect(ox + 10, cy + 16, 120, 26),
                value=action.get("upcast_damage_per_levels", 1) or 1,
                min_val=1, max_val=4,
            )
            widgets["upcast_target_count"] = NumberSpinner(
                pygame.Rect(ox + 200, cy + 16, 120, 26),
                value=action.get("upcast_target_count", 0) or 0,
                min_val=0, max_val=5,
            )
            cy += 46

        # --- Multi-Target ---
        cy += 4
        cy = self._build_section_header(SECTION_MULTI_TARGET, ox, cy, w)
        if self._section_expanded[SECTION_MULTI_TARGET]:
            widgets["target_count"] = NumberSpinner(
                pygame.Rect(ox + 10, cy + 16, 120, 26),
                value=action.get("target_count", 1) or 1,
                min_val=1, max_val=10,
            )
            dmg_choices = action.get("damage_type_choices", []) or []
            widgets["damage_type_choices"] = TextInput(
                pygame.Rect(ox + 200, cy + 16, w - 210, 26),
                value=", ".join(dmg_choices) if dmg_choices else "",
                placeholder="e.g. fire, cold, lightning",
                max_length=80,
            )
            cy += 46

        # --- Condition Options ---
        cy += 4
        cy = self._build_section_header(SECTION_CONDITION_OPTIONS, ox, cy, w)
        if self._section_expanded[SECTION_CONDITION_OPTIONS]:
            save_end_opts = ["(none)"] + ABILITY_OPTIONS
            save_end_val = action.get("condition_save_to_end") or "(none)"
            widgets["cond_save_to_end"] = Dropdown(
                pygame.Rect(ox + 10, cy + 16, 140, 26),
                save_end_opts,
            )
            try:
                widgets["cond_save_to_end"].selected_index = save_end_opts.index(save_end_val)
            except ValueError:
                pass

            widgets["cond_save_to_end_dc"] = NumberSpinner(
                pygame.Rect(ox + 200, cy + 16, 100, 26),
                value=action.get("condition_save_to_end_dc", 0) or 0,
                min_val=0, max_val=30,
            )
            cy += 46

            dur_type = action.get("condition_duration_type", "indefinite") or "indefinite"
            widgets["cond_duration_type"] = Dropdown(
                pygame.Rect(ox + 10, cy + 16, 140, 26),
                CONDITION_DURATION_TYPES,
            )
            try:
                widgets["cond_duration_type"].selected_index = CONDITION_DURATION_TYPES.index(dur_type)
            except ValueError:
                pass

            widgets["cond_duration_rounds"] = NumberSpinner(
                pygame.Rect(ox + 200, cy + 16, 100, 26),
                value=action.get("condition_duration_rounds", 0) or 0,
                min_val=0, max_val=100,
            )
            cy += 46

        # --- Creature Type Bonus ---
        cy += 4
        cy = self._build_section_header(SECTION_CREATURE_TYPE_BONUS, ox, cy, w)
        if self._section_expanded[SECTION_CREATURE_TYPE_BONUS]:
            widgets["ct_bonus_damage"] = TextInput(
                pygame.Rect(ox + 10, cy + 16, 120, 26),
                value=action.get("creature_type_bonus_damage", "") or "",
                placeholder="e.g. 2d6",
                max_length=10,
            )
            ct_types = action.get("creature_type_bonus_types", []) or []
            widgets["ct_bonus_types"] = TextInput(
                pygame.Rect(ox + 200, cy + 16, w - 210, 26),
                value=", ".join(ct_types) if ct_types else "",
                placeholder="e.g. undead, fiend",
                max_length=80,
            )
            cy += 46

        # --- HP Threshold ---
        cy += 4
        cy = self._build_section_header(SECTION_HP_THRESHOLD, ox, cy, w)
        if self._section_expanded[SECTION_HP_THRESHOLD]:
            widgets["hp_threshold"] = NumberSpinner(
                pygame.Rect(ox + 10, cy + 16, 120, 26),
                value=action.get("hp_threshold", 0) or 0,
                min_val=0, max_val=200, step=10,
            )
            hp_effect_val = action.get("hp_threshold_effect") or "(none)"
            widgets["hp_threshold_effect"] = Dropdown(
                pygame.Rect(ox + 200, cy + 16, 160, 26),
                HP_THRESHOLD_EFFECTS,
            )
            try:
                widgets["hp_threshold_effect"].selected_index = HP_THRESHOLD_EFFECTS.index(hp_effect_val)
            except ValueError:
                pass
            cy += 46

            cond_opts = ["(none)"] + CONDITION_VALUES
            hp_cond = action.get("hp_threshold_condition") or "(none)"
            widgets["hp_threshold_condition"] = Dropdown(
                pygame.Rect(ox + 10, cy + 16, 160, 26),
                cond_opts,
            )
            try:
                widgets["hp_threshold_condition"].selected_index = cond_opts.index(hp_cond)
            except ValueError:
                pass

            widgets["hp_threshold_alt_dice"] = TextInput(
                pygame.Rect(ox + 200, cy + 16, 120, 26),
                value=action.get("hp_threshold_alt_dice", "") or "",
                placeholder="e.g. 1d12",
                max_length=10,
            )
            cy += 46

        # --- Reaction Trigger ---
        cy += 4
        cy = self._build_section_header(SECTION_REACTION_TRIGGER, ox, cy, w)
        if self._section_expanded[SECTION_REACTION_TRIGGER]:
            widgets["reaction_trigger"] = TextInput(
                pygame.Rect(ox + 10, cy + 16, w - 20, 26),
                value=action.get("reaction_trigger", "") or "",
                placeholder="e.g. when hit by melee attack",
                max_length=80,
            )
            cy += 46

        # --- Chain Effect ---
        cy += 4
        cy = self._build_section_header(SECTION_CHAIN_EFFECT, ox, cy, w)
        if self._section_expanded[SECTION_CHAIN_EFFECT]:
            widgets["chain_target_count"] = NumberSpinner(
                pygame.Rect(ox + 10, cy + 16, 120, 26),
                value=action.get("chain_target_count", 0) or 0,
                min_val=0, max_val=10,
            )
            widgets["chain_range"] = NumberSpinner(
                pygame.Rect(ox + 200, cy + 16, 120, 26),
                value=action.get("chain_range", 30) or 30,
                min_val=0, max_val=120, step=5,
            )
            cy += 46

            widgets["chain_same_damage"] = Checkbox(
                pygame.Rect(ox + 10, cy, 200, 24),
                "Same Damage",
                checked=action.get("chain_same_damage", True),
            )
            cy += 30

        # --- Counterspell ---
        cy += 4
        cy = self._build_section_header(SECTION_COUNTERSPELL, ox, cy, w)
        if self._section_expanded[SECTION_COUNTERSPELL]:
            widgets["is_counterspell"] = Checkbox(
                pygame.Rect(ox + 10, cy, 200, 24),
                "Is Counterspell",
                checked=action.get("is_counterspell", False),
            )
            cy += 30

            widgets["counterspell_auto_level"] = NumberSpinner(
                pygame.Rect(ox + 10, cy + 16, 120, 26),
                value=action.get("counterspell_auto_level", 0) or 0,
                min_val=0, max_val=9,
            )
            widgets["counterspell_check_dc_base"] = NumberSpinner(
                pygame.Rect(ox + 200, cy + 16, 120, 26),
                value=action.get("counterspell_check_dc_base", 10) or 10,
                min_val=1, max_val=20,
            )
            cy += 46

        # --- Wall Spell ---
        cy += 4
        cy = self._build_section_header(SECTION_WALL_SPELL, ox, cy, w)
        if self._section_expanded[SECTION_WALL_SPELL]:
            # Row 1: Creates Wall checkbox
            widgets["is_wall"] = Checkbox(
                pygame.Rect(ox + 10, cy, 200, 24),
                "Creates Wall",
                checked=action.get("is_wall", False),
            )
            cy += 30

            # Row 2: Dimensions (length, height, thickness)
            widgets["wall_length"] = NumberSpinner(
                pygame.Rect(ox + 10, cy + 16, 120, 26),
                value=action.get("wall_length", 0) or 0,
                min_val=0, max_val=120, step=5,
            )
            widgets["wall_height"] = NumberSpinner(
                pygame.Rect(ox + 140, cy + 16, 120, 26),
                value=action.get("wall_height", 0) or 0,
                min_val=0, max_val=60, step=5,
            )
            widgets["wall_thickness"] = NumberSpinner(
                pygame.Rect(ox + 270, cy + 16, 120, 26),
                value=action.get("wall_thickness", 1) or 1,
                min_val=0, max_val=10, step=1,
            )
            cy += 46

            # Row 3: HP per panel + blocking checkboxes
            widgets["wall_hp_per_panel"] = NumberSpinner(
                pygame.Rect(ox + 10, cy + 16, 120, 26),
                value=action.get("wall_hp_per_panel", 0) or 0,
                min_val=0, max_val=200, step=10,
            )
            widgets["wall_blocks_movement"] = Checkbox(
                pygame.Rect(ox + 140, cy + 18, 160, 24),
                "Blocks Movement",
                checked=action.get("wall_blocks_movement", True),
            )
            widgets["wall_blocks_los"] = Checkbox(
                pygame.Rect(ox + 310, cy + 18, 140, 24),
                "Blocks LoS",
                checked=action.get("wall_blocks_los", False),
            )
            cy += 46

            # Row 4: Damage fields (side, dice, type)
            wall_side_opts = ["(none)", "one_side"]
            wall_side_val = action.get("wall_damage_side") or "(none)"
            widgets["wall_damage_side"] = Dropdown(
                pygame.Rect(ox + 10, cy + 16, 120, 26),
                wall_side_opts,
            )
            try:
                widgets["wall_damage_side"].selected_index = wall_side_opts.index(wall_side_val)
            except ValueError:
                pass

            widgets["wall_damage_on_enter"] = TextInput(
                pygame.Rect(ox + 140, cy + 16, 120, 26),
                value=action.get("wall_damage_on_enter", "") or "",
                placeholder="e.g. 5d8",
                max_length=10,
            )

            wall_dmg_type_opts = ["(none)"] + DAMAGE_TYPES
            wall_dmg_type_val = action.get("wall_damage_type") or "(none)"
            widgets["wall_damage_type"] = Dropdown(
                pygame.Rect(ox + 270, cy + 16, 140, 26),
                wall_dmg_type_opts,
            )
            try:
                widgets["wall_damage_type"].selected_index = wall_dmg_type_opts.index(wall_dmg_type_val)
            except ValueError:
                pass
            cy += 46

        # --- Recurring Action ---
        cy += 4
        cy = self._build_section_header(SECTION_RECURRING_ACTION, ox, cy, w)
        if self._section_expanded[SECTION_RECURRING_ACTION]:
            rec_type_opts = ["(none)", "action", "bonus_action"]
            rec_type_val = action.get("recurring_action_type") or "(none)"
            widgets["recurring_action_type"] = Dropdown(
                pygame.Rect(ox + 10, cy + 16, 140, 26),
                rec_type_opts,
            )
            try:
                widgets["recurring_action_type"].selected_index = rec_type_opts.index(rec_type_val)
            except ValueError:
                pass

            widgets["recurring_damage_dice"] = TextInput(
                pygame.Rect(ox + 200, cy + 16, 120, 26),
                value=action.get("recurring_damage_dice", "") or "",
                placeholder="e.g. 1d12",
                max_length=10,
            )
            cy += 46

            rec_dmg_type_opts = ["(none)"] + DAMAGE_TYPES
            rec_dmg_type_val = action.get("recurring_damage_type") or "(none)"
            widgets["recurring_damage_type"] = Dropdown(
                pygame.Rect(ox + 10, cy + 16, 140, 26),
                rec_dmg_type_opts,
            )
            try:
                widgets["recurring_damage_type"].selected_index = rec_dmg_type_opts.index(rec_dmg_type_val)
            except ValueError:
                pass

            widgets["recurring_auto_hit"] = Checkbox(
                pygame.Rect(ox + 200, cy + 16, 140, 24),
                "Auto-Hit",
                checked=action.get("recurring_auto_hit", False),
            )
            cy += 46

            widgets["recurring_move_distance"] = NumberSpinner(
                pygame.Rect(ox + 10, cy + 16, 120, 26),
                value=action.get("recurring_move_distance", 0) or 0,
                min_val=0, max_val=60, step=5,
            )
            cy += 46

        # ============================================================
        # OTHER FIELDS: Healing, Temp HP, Uses/Rest, Concentration, etc.
        # ============================================================
        cy += 4

        widgets["healing"] = TextInput(
            pygame.Rect(ox, cy + 18, 140, 26),
            value=action.get("healing", "") or "",
            placeholder="e.g. 2d8+3",
        )

        widgets["temp_hp"] = TextInput(
            pygame.Rect(ox + 200, cy + 18, 140, 26),
            value=action.get("grants_temporary_hp", "") or "",
            placeholder="e.g. 1d4+4",
        )
        cy += 48

        widgets["uses_per_rest"] = NumberSpinner(
            pygame.Rect(ox, cy + 18, 120, 26),
            value=action.get("uses_per_rest", 0) or 0,
            min_val=0, max_val=20,
        )

        rest_type = action.get("rest_type", "") or "(none)"
        rest_opts = ["(none)", "short", "long"]
        widgets["rest_type"] = Dropdown(
            pygame.Rect(ox + 140, cy + 18, 100, 26),
            rest_opts,
        )
        try:
            widgets["rest_type"].selected_index = rest_opts.index(rest_type)
        except ValueError:
            pass
        cy += 48

        widgets["concentration"] = Checkbox(
            pygame.Rect(ox, cy, 200, 24),
            "Requires Concentration",
            checked=action.get("requires_concentration", False),
        )

        widgets["zone_follows_caster"] = Checkbox(
            pygame.Rect(ox + 220, cy, 200, 24),
            "Zone Follows Caster",
            checked=action.get("zone_follows_caster", False),
        )
        cy += 30

        # Zone move cost (for movable zones like Moonbeam/Flaming Sphere)
        zone_cost = action.get("zone_move_cost", "") or "(none)"
        zone_cost_opts = ["(none)", "action", "bonus_action"]
        widgets["zone_move_cost"] = Dropdown(
            pygame.Rect(ox + 220, cy, 140, 26),
            zone_cost_opts,
        )
        try:
            widgets["zone_move_cost"].selected_index = zone_cost_opts.index(zone_cost)
        except ValueError:
            pass
        cy += 30

        # Legendary action cost (only for legendary_actions category)
        if self.selected_category == "legendary_actions":
            widgets["legendary_cost"] = NumberSpinner(
                pygame.Rect(ox, cy, 120, 26),
                value=action.get("legendary_action_cost", 1),
                min_val=1, max_val=3,
            )
            cy += 30

        # ============================================================
        # TELEPORTATION
        # ============================================================
        cy += 4

        widgets["teleport_range"] = NumberSpinner(
            pygame.Rect(ox, cy + 18, 120, 26),
            value=action.get("teleport_range", 0) or 0,
            min_val=0, max_val=500, step=5,
        )
        widgets["teleport_self"] = Checkbox(
            pygame.Rect(ox + 140, cy + 18, 140, 24),
            "Teleports Self",
            checked=action.get("teleport_self", True),
        )
        widgets["teleport_passenger"] = Checkbox(
            pygame.Rect(ox + 300, cy + 18, 160, 24),
            "Bring Passenger",
            checked=action.get("teleport_passenger", False),
        )
        cy += 48

        widgets["teleport_origin_effect"] = TextInput(
            pygame.Rect(ox, cy + 18, 120, 26),
            value=action.get("teleport_origin_effect", "") or "",
            placeholder="e.g. 3d10",
            max_length=20,
        )
        dmg_types_with_none = ["(none)"] + DAMAGE_TYPES
        widgets["teleport_origin_damage_type"] = Dropdown(
            pygame.Rect(ox + 140, cy + 18, 140, 26),
            dmg_types_with_none,
        )
        origin_dt = action.get("teleport_origin_damage_type") or "(none)"
        try:
            widgets["teleport_origin_damage_type"].selected_index = (
                dmg_types_with_none.index(origin_dt)
            )
        except ValueError:
            pass
        cy += 48

        # ============================================================
        # FORCED MOVEMENT (push/pull/slide on hit or failed save)
        # ============================================================
        cy += 4

        fm_type_opts = ["(none)", "push", "pull", "slide"]
        fm_type = action.get("forced_movement_type") or "(none)"
        widgets["fm_type"] = Dropdown(
            pygame.Rect(ox, cy + 18, 120, 26),
            fm_type_opts,
        )
        try:
            widgets["fm_type"].selected_index = fm_type_opts.index(fm_type)
        except ValueError:
            pass

        widgets["fm_distance"] = NumberSpinner(
            pygame.Rect(ox + 140, cy + 18, 120, 26),
            value=action.get("forced_movement_distance", 0) or 0,
            min_val=0, max_val=60, step=5,
        )

        widgets["fm_prone"] = Checkbox(
            pygame.Rect(ox + 280, cy + 18, 160, 24),
            "Also Knock Prone",
            checked=action.get("forced_movement_prone", False),
        )
        cy += 48

        # ============================================================
        # TERRAIN MODIFICATION (terrain-altering spells)
        # ============================================================
        cy += 4

        terrain_mod_opts = [
            "(none)", "normal", "difficult", "hazard", "water",
            "pit", "wall", "cover_half", "cover_three_quarters", "cover_full",
        ]
        terrain_mod_val = action.get("terrain_modification") or "(none)"
        widgets["terrain_modification"] = Dropdown(
            pygame.Rect(ox, cy + 18, 200, 26),
            terrain_mod_opts,
        )
        try:
            widgets["terrain_modification"].selected_index = (
                terrain_mod_opts.index(terrain_mod_val)
            )
        except ValueError:
            pass
        cy += 48

        # ============================================================
        # SUMMONING (creature path + Wild Shape flag)
        # ============================================================
        cy += 4

        widgets["summon_creature"] = TextInput(
            pygame.Rect(ox, cy + 18, 280, 26),
            value=action.get("summon_creature", "") or "",
            placeholder="e.g. monsters/wolf.json",
            max_length=100,
        )
        widgets["is_wild_shape"] = Checkbox(
            pygame.Rect(ox + 300, cy + 18, 160, 24),
            "Wild Shape",
            checked=action.get("is_wild_shape", False),
        )
        cy += 48

        # ============================================================
        # CONDITIONS APPLIED / REMOVED
        # ============================================================
        cy += 4
        half_w = (w - 10) // 2
        cond_app = action.get("conditions_applied", [])
        cond_rem = action.get("conditions_removed", [])

        widgets["cond_applied"] = ListEditor(
            pygame.Rect(ox, cy + 16, half_w, 80),
            items=list(cond_app),
            allowed_values=CONDITION_VALUES,
        )
        widgets["cond_removed"] = ListEditor(
            pygame.Rect(ox + half_w + 10, cy + 16, half_w, 80),
            items=list(cond_rem),
            allowed_values=CONDITION_VALUES,
        )
        # Cross-exclusion: same condition shouldn't be in both lists
        widgets["cond_applied"].excluded_values = set(cond_rem)
        widgets["cond_removed"].excluded_values = set(cond_app)
        cy += 100

        # ============================================================
        # RESOURCE COST (key-value rows)
        # ============================================================
        cy += 2
        resource_cost = action.get("resource_cost", {}) or {}
        cost_items = list(resource_cost.items())
        for ri in range(3):
            key = cost_items[ri][0] if ri < len(cost_items) else ""
            val = cost_items[ri][1] if ri < len(cost_items) else 0
            widgets[f"res_key_{ri}"] = TextInput(
                pygame.Rect(ox, cy, 200, 26),
                value=key,
                placeholder="resource name...",
                max_length=30,
            )
            widgets[f"res_val_{ri}"] = NumberSpinner(
                pygame.Rect(ox + 210, cy, 100, 26),
                value=val,
                min_val=0, max_val=20,
            )
            cy += 30

        # ============================================================
        # AI FIELDS
        # ============================================================
        cy += 4
        widgets["ai_priority"] = NumberSpinner(
            pygame.Rect(ox, cy + 16, 120, 26),
            value=action.get("ai_priority", 5),
            min_val=1, max_val=10,
        )
        widgets["ai_condition"] = TextInput(
            pygame.Rect(ox + 200, cy + 16, w - 200, 26),
            value=action.get("ai_use_condition", "") or "",
            placeholder="AI condition...",
            max_length=60,
        )
        cy += 48

        # ============================================================
        # Finalize
        # ============================================================
        self._detail_widgets = widgets
        self._detail_content_height = cy - oy

        # Collect all dropdowns for overlay rendering
        self._detail_dropdowns = [
            v for v in widgets.values() if isinstance(v, Dropdown)
        ]
        # Collect all ListEditors for overlay rendering
        self._detail_list_editors = [
            v for v in widgets.values() if isinstance(v, ListEditor)
        ]

    # ------------------------------------------------------------------
    # Sync detail widgets → action dict
    # ------------------------------------------------------------------

    def _sync_detail_to_action(self) -> None:
        """Write detail widget values back to the selected action dict.

        After syncing, if a collapsible checkbox changed state we rebuild
        widgets so the conditional sections appear/disappear.
        """
        if self._is_equipment_sourced:
            return

        action = self._get_selected_action()
        if action is None or self._detail_widgets is None:
            return

        w = self._detail_widgets
        action["name"] = w["name"].value
        action["description"] = w["description"].value
        action["target_type"] = w["target_type"].value
        action["range"] = w["range"].value
        area = w["area_size"].value
        action["area_size"] = area if area > 0 else None

        # --- Animation ---
        if "animation" in w:
            anim_val = w["animation"].value
            action["animation"] = anim_val if anim_val != "(none)" else None

        # --- Attack ---
        if w["has_attack"].checked and "attack_type" in w:
            damage = []
            for di in range(3):
                entry = self._read_damage_row(w, f"dmg_{di}")
                if entry:
                    damage.append(entry)

            action["attack"] = {
                "name": w["name"].value,
                "attack_type": w["attack_type"].value,
                "ability": w["attack_ability"].value,
                "reach": w["reach"].value,
                "damage": damage,
            }
            rn = w["range_normal"].value
            rl = w["range_long"].value
            if rn > 0:
                action["attack"]["range_normal"] = rn
            if rl > 0:
                action["attack"]["range_long"] = rl
        elif w["has_attack"].checked:
            # Checkbox just toggled ON but attack widgets don't exist yet.
            # Write a default attack dict so rebuild picks it up.
            action["attack"] = {
                "name": action.get("name", ""),
                "attack_type": "melee_weapon",
                "ability": "strength",
                "reach": 5,
                "damage": [],
            }
        else:
            action["attack"] = None

        # --- Saving throw ---
        if w["has_save"].checked and "save_ability" in w:
            save_data: dict = {
                "ability": w["save_ability"].value,
                "dc": w["save_dc"].value,
                "damage_on_success": w["save_on_success"].value,
            }

            # DC ability (auto-calc)
            dc_ability_w = w.get("save_dc_ability")
            if dc_ability_w and dc_ability_w.value != "(none)":
                save_data["dc_ability"] = dc_ability_w.value

            # Damage on fail
            fail_damage = []
            for fi in range(2):
                entry = self._read_damage_row(w, f"fail_dmg_{fi}")
                if entry:
                    fail_damage.append(entry)
            if fail_damage:
                save_data["damage_on_fail"] = fail_damage

            # Conditions on fail/success
            cond_fail_le = w.get("save_cond_fail")
            if cond_fail_le and cond_fail_le.items:
                save_data["conditions_on_fail"] = list(cond_fail_le.items)

            cond_success_le = w.get("save_cond_success")
            if cond_success_le and cond_success_le.items:
                save_data["conditions_on_success"] = list(cond_success_le.items)

            action["saving_throw"] = save_data
        elif w["has_save"].checked:
            # Checkbox just toggled ON but save widgets don't exist yet.
            action["saving_throw"] = {
                "ability": "dexterity",
                "dc": 10,
                "damage_on_success": "none",
            }
        else:
            action["saving_throw"] = None

        # --- Other fields ---
        healing = w["healing"].value
        action["healing"] = healing if healing else None

        temp_hp = w["temp_hp"].value
        action["grants_temporary_hp"] = temp_hp if temp_hp else None

        uses = w["uses_per_rest"].value
        action["uses_per_rest"] = uses if uses > 0 else None

        rest = w["rest_type"].value
        action["rest_type"] = None if rest == "(none)" else rest

        action["requires_concentration"] = w["concentration"].checked
        action["zone_follows_caster"] = w["zone_follows_caster"].checked

        zone_cost = w["zone_move_cost"].value
        action["zone_move_cost"] = None if zone_cost == "(none)" else zone_cost

        # Legendary action cost
        if "legendary_cost" in w:
            action["legendary_action_cost"] = w["legendary_cost"].value

        # --- Teleportation ---
        tp_range = w["teleport_range"].value
        action["teleport_range"] = tp_range if tp_range > 0 else None
        action["teleport_self"] = w["teleport_self"].checked
        action["teleport_passenger"] = w["teleport_passenger"].checked
        origin_eff = w["teleport_origin_effect"].value
        action["teleport_origin_effect"] = origin_eff if origin_eff else None
        origin_dt = w["teleport_origin_damage_type"].value
        action["teleport_origin_damage_type"] = (
            None if origin_dt == "(none)" else origin_dt
        )

        # --- Forced movement ---
        fm_type_val = w["fm_type"].value
        action["forced_movement_type"] = None if fm_type_val == "(none)" else fm_type_val
        action["forced_movement_distance"] = w["fm_distance"].value
        action["forced_movement_prone"] = w["fm_prone"].checked

        # --- Terrain modification ---
        terrain_mod_val = w["terrain_modification"].value
        action["terrain_modification"] = (
            None if terrain_mod_val == "(none)" else terrain_mod_val
        )

        # --- Summoning ---
        summon_path = w["summon_creature"].value
        action["summon_creature"] = summon_path if summon_path else None
        action["is_wild_shape"] = w["is_wild_shape"].checked

        # --- Conditions applied / removed ---
        cond_app = w.get("cond_applied")
        action["conditions_applied"] = list(cond_app.items) if cond_app else []

        cond_rem = w.get("cond_removed")
        action["conditions_removed"] = list(cond_rem.items) if cond_rem else []

        # Keep cross-exclusion in sync
        if cond_app and cond_rem:
            cond_app.excluded_values = set(cond_rem.items)
            cond_rem.excluded_values = set(cond_app.items)

        # --- Resource cost ---
        resource_cost: dict = {}
        for ri in range(3):
            key_w = w.get(f"res_key_{ri}")
            val_w = w.get(f"res_val_{ri}")
            if key_w and val_w and key_w.value.strip():
                resource_cost[key_w.value.strip()] = val_w.value

        # Apply spell level: remove any manual spell_slot_* keys, then add
        # the correct one based on the dropdown.
        resource_cost = {
            k: v for k, v in resource_cost.items()
            if not k.startswith("spell_slot")
        }
        spell_level_dd = w.get("spell_level")
        if spell_level_dd:
            sel_idx = spell_level_dd.selected_index
            if sel_idx >= 2:
                # Index 2 = "1st level" → spell_slot_1, etc.
                slot_level = sel_idx - 1
                resource_cost[f"spell_slot_{slot_level}"] = 1

        action["resource_cost"] = resource_cost if resource_cost else {}

        # --- AI ---
        action["ai_priority"] = w["ai_priority"].value
        ai_cond = w["ai_condition"].value
        action["ai_use_condition"] = ai_cond if ai_cond else None

        # --- Spell Scaling (collapsible) ---
        if "cantrip_scaling" in w:
            action["cantrip_scaling"] = w["cantrip_scaling"].checked
        if "cantrip_extra_targets" in w:
            action["cantrip_extra_targets"] = w["cantrip_extra_targets"].checked
        if "upcast_damage_dice" in w:
            val = w["upcast_damage_dice"].value
            action["upcast_damage_dice"] = val if val else None
        if "upcast_healing_dice" in w:
            val = w["upcast_healing_dice"].value
            action["upcast_healing_dice"] = val if val else None
        if "upcast_per_levels" in w:
            action["upcast_damage_per_levels"] = w["upcast_per_levels"].value
        if "upcast_target_count" in w:
            action["upcast_target_count"] = w["upcast_target_count"].value

        # --- Multi-Target (collapsible) ---
        if "target_count" in w:
            action["target_count"] = w["target_count"].value
        if "damage_type_choices" in w:
            raw = w["damage_type_choices"].value.strip()
            action["damage_type_choices"] = (
                [s.strip() for s in raw.split(",") if s.strip()]
                if raw else []
            )

        # --- Condition Options (collapsible) ---
        if "cond_save_to_end" in w:
            val = w["cond_save_to_end"].value
            action["condition_save_to_end"] = None if val == "(none)" else val
        if "cond_save_to_end_dc" in w:
            dc = w["cond_save_to_end_dc"].value
            action["condition_save_to_end_dc"] = dc if dc > 0 else None
        if "cond_duration_type" in w:
            action["condition_duration_type"] = w["cond_duration_type"].value
        if "cond_duration_rounds" in w:
            rounds = w["cond_duration_rounds"].value
            action["condition_duration_rounds"] = rounds if rounds > 0 else None

        # --- Creature Type Bonus (collapsible) ---
        if "ct_bonus_damage" in w:
            val = w["ct_bonus_damage"].value
            action["creature_type_bonus_damage"] = val if val else None
        if "ct_bonus_types" in w:
            raw = w["ct_bonus_types"].value.strip()
            action["creature_type_bonus_types"] = (
                [s.strip() for s in raw.split(",") if s.strip()]
                if raw else []
            )

        # --- HP Threshold (collapsible) ---
        if "hp_threshold" in w:
            val = w["hp_threshold"].value
            action["hp_threshold"] = val if val > 0 else None
        if "hp_threshold_effect" in w:
            val = w["hp_threshold_effect"].value
            action["hp_threshold_effect"] = None if val == "(none)" else val
        if "hp_threshold_condition" in w:
            val = w["hp_threshold_condition"].value
            action["hp_threshold_condition"] = None if val == "(none)" else val
        if "hp_threshold_alt_dice" in w:
            val = w["hp_threshold_alt_dice"].value
            action["hp_threshold_alt_dice"] = val if val else None

        # --- Reaction Trigger (collapsible) ---
        if "reaction_trigger" in w:
            val = w["reaction_trigger"].value
            action["reaction_trigger"] = val if val else None

        # --- Chain Effect (collapsible) ---
        if "chain_target_count" in w:
            val = w["chain_target_count"].value
            action["chain_target_count"] = val if val > 0 else None
        if "chain_range" in w:
            action["chain_range"] = w["chain_range"].value
        if "chain_same_damage" in w:
            action["chain_same_damage"] = w["chain_same_damage"].checked

        # --- Counterspell (collapsible) ---
        if "is_counterspell" in w:
            action["is_counterspell"] = w["is_counterspell"].checked
        if "counterspell_auto_level" in w:
            val = w["counterspell_auto_level"].value
            action["counterspell_auto_level"] = val if val > 0 else None
        if "counterspell_check_dc_base" in w:
            action["counterspell_check_dc_base"] = w["counterspell_check_dc_base"].value

        # --- Wall Spell (collapsible) ---
        if "is_wall" in w:
            action["is_wall"] = w["is_wall"].checked
        if "wall_length" in w:
            action["wall_length"] = w["wall_length"].value
        if "wall_height" in w:
            action["wall_height"] = w["wall_height"].value
        if "wall_thickness" in w:
            action["wall_thickness"] = w["wall_thickness"].value
        if "wall_hp_per_panel" in w:
            val = w["wall_hp_per_panel"].value
            action["wall_hp_per_panel"] = val if val > 0 else None
        if "wall_blocks_movement" in w:
            action["wall_blocks_movement"] = w["wall_blocks_movement"].checked
        if "wall_blocks_los" in w:
            action["wall_blocks_los"] = w["wall_blocks_los"].checked
        if "wall_damage_side" in w:
            val = w["wall_damage_side"].value
            action["wall_damage_side"] = None if val == "(none)" else val
        if "wall_damage_on_enter" in w:
            val = w["wall_damage_on_enter"].value
            action["wall_damage_on_enter"] = val if val else None
        if "wall_damage_type" in w:
            val = w["wall_damage_type"].value
            action["wall_damage_type"] = None if val == "(none)" else val

        # --- Recurring Action (collapsible) ---
        if "recurring_action_type" in w:
            val = w["recurring_action_type"].value
            action["recurring_action_type"] = None if val == "(none)" else val
        if "recurring_damage_dice" in w:
            val = w["recurring_damage_dice"].value
            action["recurring_damage_dice"] = val if val else None
        if "recurring_damage_type" in w:
            val = w["recurring_damage_type"].value
            action["recurring_damage_type"] = None if val == "(none)" else val
        if "recurring_auto_hit" in w:
            action["recurring_auto_hit"] = w["recurring_auto_hit"].checked
        if "recurring_move_distance" in w:
            val = w["recurring_move_distance"].value
            action["recurring_move_distance"] = val if val > 0 else None

        # --- Rebuild if collapsible section toggled ---
        # The checkbox state determines whether attack/save widgets exist.
        # If the state no longer matches, rebuild so widgets appear/disappear.
        attack_widgets_exist = "attack_type" in w
        save_widgets_exist = "save_ability" in w
        if (w["has_attack"].checked != attack_widgets_exist
                or w["has_save"].checked != save_widgets_exist):
            self._build_detail_widgets()

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def has_open_dropdown(self) -> bool:
        if any(dd.is_open for dd in self._detail_dropdowns):
            return True
        if any(le.is_picker_open for le in self._detail_list_editors):
            return True
        return False

    def handle_escape(self) -> bool:
        if self._detail_widgets:
            for v in self._detail_widgets.values():
                if isinstance(v, TextInput) and v.active:
                    v.active = False
                    return True
                if isinstance(v, Dropdown) and v.is_open:
                    v.is_open = False
                    return True
                if isinstance(v, ListEditor) and v.is_picker_open:
                    v._picker_open = False
                    return True
        return False

    def handle_event(self, event: pygame.event.Event) -> bool:
        # Open dropdowns get priority
        for dd in self._detail_dropdowns:
            if dd.is_open and dd.handle_event(event):
                self._sync_detail_to_action()
                return True

        # Open ListEditor pickers get priority
        for le in self._detail_list_editors:
            if le.is_picker_open and le.handle_event(event):
                self._sync_detail_to_action()
                return True

        # Scrolling (mousewheel)
        if event.type == pygame.MOUSEWHEEL:
            mouse_pos = pygame.mouse.get_pos()

            # List panel scroll
            list_rect = self._get_list_panel_rect()
            if list_rect.collidepoint(mouse_pos):
                list_h = self._get_list_content_height()
                max_scroll = max(0, list_h - list_rect.height + 20)
                self.list_scroll_y = max(
                    0, min(max_scroll, self.list_scroll_y - event.y * 30),
                )
                return True

            # Detail panel scroll
            detail_rect = pygame.Rect(
                self.screen.content_rect.x + DETAIL_PANEL_X_OFFSET,
                self.screen.content_rect.y,
                self.screen.content_rect.width - DETAIL_PANEL_X_OFFSET,
                self.screen.content_rect.height,
            )
            if detail_rect.collidepoint(mouse_pos):
                max_scroll = max(
                    0, self._detail_content_height - detail_rect.height + 20,
                )
                new_scroll = max(
                    0, min(max_scroll, self.detail_scroll_y - event.y * 30),
                )
                self._apply_scroll(new_scroll)
                return True

        # Collapsible section header clicks
        if (event.type == pygame.MOUSEBUTTONUP and event.button == 1
                and self._section_header_rects):
            for section_id, rect in self._section_header_rects.items():
                if rect.collidepoint(event.pos):
                    self._section_expanded[section_id] = (
                        not self._section_expanded[section_id]
                    )
                    self._build_detail_widgets()
                    return True

        # Detail panel widgets
        if self._detail_widgets:
            for v in self._detail_widgets.values():
                if hasattr(v, "handle_event") and v.handle_event(event):
                    self._sync_detail_to_action()
                    return True

        # List panel clicks
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            return self._handle_list_click(event.pos)

        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)

        return False

    # ------------------------------------------------------------------
    # List panel — click handling
    # ------------------------------------------------------------------

    def _handle_list_click(self, pos: tuple[int, int]) -> bool:
        # Only handle clicks inside the list panel area
        list_rect = self._get_list_panel_rect()
        if not list_rect.collidepoint(pos):
            return False

        ox = self.screen.content_rect.x + 10
        oy = self.screen.content_rect.y + 10 - self.list_scroll_y
        item_h = 28
        gap = 4

        current_y = oy
        categories = self._get_categories()

        for cat in categories:
            # Category header with add button
            add_rect = pygame.Rect(
                ox + LIST_PANEL_WIDTH - 75, current_y, 56, 22,
            )

            if add_rect.collidepoint(pos):
                # Add new action to this category
                action_type_map = {
                    "actions": "action",
                    "bonus_actions": "bonus_action",
                    "reactions": "reaction",
                    "legendary_actions": "legendary",
                    "lair_actions": "lair",
                }
                new_action = {
                    "name": "New Action",
                    "description": "",
                    "action_type": action_type_map.get(cat, "action"),
                    "target_type": "one_creature",
                    "range": 5,
                }
                self.screen.actions_data[cat].append(new_action)
                self.selected_category = cat
                self.selected_action_index = len(self.screen.actions_data[cat]) - 1
                self._build_detail_widgets()
                return True

            current_y += 28

            # Action items in this category
            actions = self.screen.actions_data.get(cat, [])
            for i, action in enumerate(actions):
                item_rect = pygame.Rect(ox, current_y, LIST_PANEL_WIDTH - 50, item_h)
                rm_rect = pygame.Rect(
                    ox + LIST_PANEL_WIDTH - 45, current_y + 4, 20, 20,
                )

                if rm_rect.collidepoint(pos):
                    # Cannot delete equipment-sourced actions
                    if action.get("source_item") is not None:
                        return True
                    actions.pop(i)
                    if (self.selected_category == cat
                            and self.selected_action_index == i):
                        self.selected_action_index = None
                        self._detail_widgets = None
                        self._detail_dropdowns = []
                        self._detail_list_editors = []
                    elif (self.selected_category == cat
                          and self.selected_action_index is not None
                          and self.selected_action_index > i):
                        self.selected_action_index -= 1
                        self._build_detail_widgets()
                    return True

                if item_rect.collidepoint(pos):
                    self.selected_category = cat
                    self.selected_action_index = i
                    self._build_detail_widgets()
                    return True

                current_y += item_h + gap

            if not actions:
                current_y += 20  # "(none)" text height

            current_y += 10  # Gap between categories

        return False

    def _update_hover(self, pos: tuple[int, int]) -> None:
        ox = self.screen.content_rect.x + 10
        oy = self.screen.content_rect.y + 10 - self.list_scroll_y
        current_y = oy
        self.add_hover_cat = None

        for cat in self._get_categories():
            add_rect = pygame.Rect(
                ox + LIST_PANEL_WIDTH - 75, current_y, 56, 22,
            )
            if add_rect.collidepoint(pos):
                self.add_hover_cat = cat

            current_y += 28
            actions = self.screen.actions_data.get(cat, [])
            if actions:
                current_y += len(actions) * 32  # item_h + gap
            else:
                current_y += 20  # "(none)" text height
            current_y += 10

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        self._render_list_panel(surface)
        self._render_detail_panel(surface)

    def _render_list_panel(self, surface: pygame.Surface) -> None:
        list_clip = self._get_list_panel_rect()
        old_clip = surface.get_clip()
        surface.set_clip(list_clip)

        ox = self.screen.content_rect.x + 10
        oy = self.screen.content_rect.y + 10 - self.list_scroll_y
        font = get_font(14)
        small_font = get_font(12)
        label_color = parse_color(COLORS["text_secondary"])
        item_h = 28
        gap = 4

        current_y = oy
        categories = self._get_categories()

        for cat in categories:
            # Category header
            header_text = CATEGORY_LABELS.get(cat, cat)
            header_surf = font.render(
                header_text, True, parse_color(COLORS["text_primary"]),
            )
            surface.blit(header_surf, (ox, current_y + 2))

            # Add button
            add_rect = pygame.Rect(
                ox + LIST_PANEL_WIDTH - 75, current_y, 56, 22,
            )
            add_color = (
                parse_color(COLORS["button_hover"])
                if self.add_hover_cat == cat
                else parse_color(COLORS["button_normal"])
            )
            pygame.draw.rect(surface, add_color, add_rect, border_radius=3)
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                add_rect, 1, border_radius=3,
            )
            draw_text_centered(
                surface, "+ Add", add_rect.center,
                parse_color(COLORS["text_primary"]), font_size=12,
            )

            current_y += 28

            # Action items
            actions = self.screen.actions_data.get(cat, [])
            for i, action in enumerate(actions):
                item_rect = pygame.Rect(
                    ox, current_y, LIST_PANEL_WIDTH - 50, item_h,
                )
                selected = (
                    cat == self.selected_category
                    and i == self.selected_action_index
                )
                bg = (
                    parse_color(COLORS["button_active"]) if selected
                    else parse_color(COLORS["button_normal"])
                )
                pygame.draw.rect(surface, bg, item_rect, border_radius=3)
                pygame.draw.rect(
                    surface, parse_color(COLORS["hex_border"]),
                    item_rect, 1, border_radius=3,
                )

                name = action.get("name", "(unnamed)")
                is_equip_src = action.get("source_item") is not None
                if is_equip_src:
                    name = f"[E] {name}"
                name_color = (
                    parse_color(COLORS["text_gold"]) if is_equip_src
                    else parse_color(COLORS["text_primary"])
                )
                name_surf = small_font.render(name, True, name_color)
                surface.blit(name_surf, (item_rect.x + 6, current_y + 6))

                # Remove [x] — hidden for equipment-sourced actions
                if not is_equip_src:
                    draw_text_centered(
                        surface, "x",
                        (ox + LIST_PANEL_WIDTH - 35, current_y + item_h // 2),
                        parse_color(COLORS["text_secondary"]), font_size=12,
                    )

                current_y += item_h + gap

            if not actions:
                empty = small_font.render("(none)", True, label_color)
                surface.blit(empty, (ox + 6, current_y + 2))
                current_y += 20

            current_y += 10

        surface.set_clip(old_clip)

        # Left-side scrollbar
        list_content_h = self._get_list_content_height()
        visible_h = list_clip.height
        if list_content_h > visible_h:
            bar_w = 5
            bar_margin = 2
            track_x = list_clip.x + bar_margin
            track_y = list_clip.y + bar_margin
            track_h = visible_h - bar_margin * 2

            # Track
            track_color = parse_color(COLORS.get("bg_medium", "#2a2018"))
            pygame.draw.rect(
                surface, track_color,
                (track_x, track_y, bar_w, track_h),
                border_radius=bar_w // 2,
            )

            # Thumb
            thumb_ratio = visible_h / list_content_h
            thumb_h = max(16, int(track_h * thumb_ratio))
            max_scroll = list_content_h - visible_h + 20
            if max_scroll > 0:
                scroll_ratio = self.list_scroll_y / max_scroll
            else:
                scroll_ratio = 0.0
            thumb_y = track_y + int((track_h - thumb_h) * scroll_ratio)

            thumb_color = parse_color(COLORS.get("border_accent", "#6b5530"))
            pygame.draw.rect(
                surface, thumb_color,
                (track_x, thumb_y, bar_w, thumb_h),
                border_radius=bar_w // 2,
            )

        # Separator between list and detail
        sep_x = self.screen.content_rect.x + LIST_PANEL_WIDTH + 5
        pygame.draw.line(
            surface, parse_color(COLORS["hex_border"]),
            (sep_x, self.screen.content_rect.y + 5),
            (sep_x, self.screen.content_rect.bottom - 5),
        )

    def _render_detail_panel(self, surface: pygame.Surface) -> None:
        ox = self.screen.content_rect.x + DETAIL_PANEL_X_OFFSET
        oy_base = self.screen.content_rect.y + 10
        font = get_font(14)
        small_font = get_font(12)
        label_color = parse_color(COLORS["text_secondary"])

        action = self._get_selected_action()
        if action is None or self._detail_widgets is None:
            msg = font.render(
                "Select an action to edit", True, label_color,
            )
            surface.blit(msg, (ox, oy_base + 40))
            return

        # Equipment-sourced actions — read-only summary
        if self._is_equipment_sourced:
            lines = [
                (action.get("name", ""), parse_color(COLORS["text_gold"])),
                ("", label_color),
                ("This action is generated from equipment.", label_color),
                ("Edit it in the Equipment tab.", label_color),
            ]
            # Show attack stats summary if present
            atk = action.get("attack")
            if atk:
                lines.append(("", label_color))
                atk_type = atk.get("attack_type", "")
                ability = atk.get("ability", "")
                reach = atk.get("reach", 5)
                dmg_list = atk.get("damage", [])
                dmg_str = ", ".join(
                    f"{d.get('dice', '')} {d.get('damage_type', '')}"
                    for d in dmg_list
                ) or "none"
                lines.append(
                    (f"Type: {atk_type}  |  Ability: {ability}  |  Reach: {reach} ft",
                     label_color),
                )
                lines.append((f"Damage: {dmg_str}", label_color))
            # Show consumable info if present
            if action.get("action_type") in ("action", "bonus_action"):
                uses = action.get("uses_per_rest")
                if uses is not None:
                    lines.append(("", label_color))
                    lines.append(
                        (f"Uses: {uses}  |  Type: {action.get('action_type', '')}",
                         label_color),
                    )
            # Show healing if present
            healing = action.get("healing")
            if healing:
                lines.append((f"Healing: {healing}", label_color))
            # Show saving throw if present
            save = action.get("saving_throw")
            if save:
                dc = save.get("dc", "?")
                ability = save.get("ability", "?")
                on_succ = save.get("damage_on_success", "none")
                save_line = f"Save: DC {dc} {ability}"
                if on_succ != "none":
                    save_line += f"  |  On Success: {on_succ}"
                lines.append((save_line, label_color))
                fail_dmg = save.get("damage_on_fail", [])
                if fail_dmg:
                    dmg_str = ", ".join(
                        f"{d.get('dice', '')} {d.get('damage_type', '')}"
                        for d in fail_dmg
                    )
                    lines.append((f"Damage on Fail: {dmg_str}", label_color))
            # Show conditions applied
            cond_app = action.get("conditions_applied", [])
            if cond_app:
                lines.append(
                    (f"Applies: {', '.join(cond_app)}", label_color),
                )
            # Show conditions removed
            cond_rem = action.get("conditions_removed", [])
            if cond_rem:
                lines.append(
                    (f"Removes: {', '.join(cond_rem)}", label_color),
                )

            for i, (text, color) in enumerate(lines):
                if text:
                    txt = font.render(text, True, color)
                    surface.blit(txt, (ox, oy_base + 20 + i * 22))
            return

        w = self._detail_widgets

        # --- Set up clipping for scroll ---
        detail_clip = pygame.Rect(
            ox - 5,
            self.screen.content_rect.y,
            self.screen.content_rect.width - DETAIL_PANEL_X_OFFSET + 10,
            self.screen.content_rect.height,
        )
        old_clip = surface.get_clip()
        surface.set_clip(detail_clip)

        # Render labels relative to widget positions so they stay in sync
        # with scrolling.  Each label is placed just above its widget.

        def _lbl(text: str, widget_key: str, x_off: int = 0) -> None:
            """Draw *text* label above (or beside) a widget."""
            wgt = w.get(widget_key)
            if wgt is None:
                return
            surface.blit(
                font.render(text, True, label_color),
                (wgt.rect.x + x_off, wgt.rect.y - 18),
            )

        def _slbl(text: str, x: int, y: int) -> None:
            """Draw a small-font label at absolute position."""
            surface.blit(small_font.render(text, True, label_color), (x, y))

        # ============================================================
        # HEADER: Name, Description, Target / Range / Area
        # ============================================================
        _lbl("Name:", "name")
        w["name"].render(surface)

        _lbl("Description:", "description")
        w["description"].render(surface)

        _lbl("Target:", "target_type")
        w["target_type"].render(surface)

        _lbl("Range:", "range")
        w["range"].render(surface)

        target_val = w["target_type"].value
        if target_val.startswith("area_"):
            _lbl("Area:", "area_size")
            w["area_size"].render(surface)

        # ============================================================
        # SPELL LEVEL
        # ============================================================
        _lbl("Spell Level:", "spell_level")
        w["spell_level"].render(surface)

        # ============================================================
        # ANIMATION
        # ============================================================
        if "animation" in w:
            _lbl("Animation:", "animation")
            w["animation"].render(surface)

        # ============================================================
        # ATTACK SECTION
        # ============================================================
        w["has_attack"].render(surface)

        if w["has_attack"].checked and "attack_type" in w:
            _lbl("Attack Type:", "attack_type")
            w["attack_type"].render(surface)

            _lbl("Ability:", "attack_ability")
            w["attack_ability"].render(surface)

            _lbl("Reach:", "reach")
            w["reach"].render(surface)

            _lbl("Range:", "range_normal")
            w["range_normal"].render(surface)

            _lbl("Long:", "range_long")
            w["range_long"].render(surface)

            # Damage rolls — header + column labels above first row
            first_dmg = w.get("dmg_0_dice")
            if first_dmg:
                hdr_y = first_dmg.rect.y - 22
                surface.blit(
                    font.render("Damage Rolls:", True, label_color),
                    (ox, hdr_y),
                )
                _slbl("Dice", ox, first_dmg.rect.y - 10)
                _slbl("Type", ox + 70, first_dmg.rect.y - 10)
                _slbl("Modifier", ox + 185, first_dmg.rect.y - 10)
                _slbl("Bonus", ox + 320, first_dmg.rect.y - 10)

            for di in range(3):
                for suffix in ("_dice", "_type", "_mod", "_bonus"):
                    wgt = w.get(f"dmg_{di}{suffix}")
                    if wgt:
                        wgt.render(surface)

        # ============================================================
        # SAVING THROW SECTION
        # ============================================================
        w["has_save"].render(surface)

        if w["has_save"].checked and "save_ability" in w:
            _lbl("Ability:", "save_ability")
            w["save_ability"].render(surface)

            _lbl("DC:", "save_dc")
            w["save_dc"].render(surface)

            _lbl("DC Ability:", "save_dc_ability")
            w["save_dc_ability"].render(surface)

            _lbl("On Succ:", "save_on_success")
            w["save_on_success"].render(surface)

            # Damage on fail — header + column labels
            first_fail = w.get("fail_dmg_0_dice")
            if first_fail:
                hdr_y = first_fail.rect.y - 22
                surface.blit(
                    font.render("Damage on Fail:", True, label_color),
                    (ox, hdr_y),
                )
                _slbl("Dice", ox, first_fail.rect.y - 10)
                _slbl("Type", ox + 70, first_fail.rect.y - 10)
                _slbl("Modifier", ox + 185, first_fail.rect.y - 10)
                _slbl("Bonus", ox + 320, first_fail.rect.y - 10)

            for fi in range(2):
                for suffix in ("_dice", "_type", "_mod", "_bonus"):
                    wgt = w.get(f"fail_dmg_{fi}{suffix}")
                    if wgt:
                        wgt.render(surface)

            # Conditions on fail / success
            cond_fail = w.get("save_cond_fail")
            cond_succ = w.get("save_cond_success")
            if cond_fail:
                surface.blit(
                    font.render("Conds on Fail:", True, label_color),
                    (cond_fail.rect.x, cond_fail.rect.y - 16),
                )
                cond_fail.render(surface)
            if cond_succ:
                surface.blit(
                    font.render("Conds on Succ:", True, label_color),
                    (cond_succ.rect.x, cond_succ.rect.y - 16),
                )
                cond_succ.render(surface)

        # ============================================================
        # COLLAPSIBLE SECTIONS
        # ============================================================

        # --- Spell Scaling ---
        self._render_section_header(surface, SECTION_SPELL_SCALING, action)
        if self._section_expanded[SECTION_SPELL_SCALING]:
            if "cantrip_scaling" in w:
                w["cantrip_scaling"].render(surface)
            if "cantrip_extra_targets" in w:
                w["cantrip_extra_targets"].render(surface)
            if "upcast_damage_dice" in w:
                _lbl("Upcast Damage:", "upcast_damage_dice")
                w["upcast_damage_dice"].render(surface)
            if "upcast_healing_dice" in w:
                _lbl("Upcast Healing:", "upcast_healing_dice")
                w["upcast_healing_dice"].render(surface)
            if "upcast_per_levels" in w:
                _lbl("Per Levels:", "upcast_per_levels")
                w["upcast_per_levels"].render(surface)
            if "upcast_target_count" in w:
                _lbl("Extra Targets/Lvl:", "upcast_target_count")
                w["upcast_target_count"].render(surface)

        # --- Multi-Target ---
        self._render_section_header(surface, SECTION_MULTI_TARGET, action)
        if self._section_expanded[SECTION_MULTI_TARGET]:
            if "target_count" in w:
                _lbl("Targets:", "target_count")
                w["target_count"].render(surface)
            if "damage_type_choices" in w:
                _lbl("Damage Type Choices:", "damage_type_choices")
                w["damage_type_choices"].render(surface)

        # --- Condition Options ---
        self._render_section_header(surface, SECTION_CONDITION_OPTIONS, action)
        if self._section_expanded[SECTION_CONDITION_OPTIONS]:
            if "cond_save_to_end" in w:
                _lbl("Save to End:", "cond_save_to_end")
                w["cond_save_to_end"].render(surface)
            if "cond_save_to_end_dc" in w:
                _lbl("DC:", "cond_save_to_end_dc")
                w["cond_save_to_end_dc"].render(surface)
            if "cond_duration_type" in w:
                _lbl("Duration:", "cond_duration_type")
                w["cond_duration_type"].render(surface)
            if "cond_duration_rounds" in w:
                _lbl("Rounds:", "cond_duration_rounds")
                w["cond_duration_rounds"].render(surface)

        # --- Creature Type Bonus ---
        self._render_section_header(surface, SECTION_CREATURE_TYPE_BONUS, action)
        if self._section_expanded[SECTION_CREATURE_TYPE_BONUS]:
            if "ct_bonus_damage" in w:
                _lbl("Bonus Dice:", "ct_bonus_damage")
                w["ct_bonus_damage"].render(surface)
            if "ct_bonus_types" in w:
                _lbl("Creature Types:", "ct_bonus_types")
                w["ct_bonus_types"].render(surface)

        # --- HP Threshold ---
        self._render_section_header(surface, SECTION_HP_THRESHOLD, action)
        if self._section_expanded[SECTION_HP_THRESHOLD]:
            if "hp_threshold" in w:
                _lbl("Threshold HP:", "hp_threshold")
                w["hp_threshold"].render(surface)
            if "hp_threshold_effect" in w:
                _lbl("Effect:", "hp_threshold_effect")
                w["hp_threshold_effect"].render(surface)
            if "hp_threshold_condition" in w:
                _lbl("Condition:", "hp_threshold_condition")
                w["hp_threshold_condition"].render(surface)
            if "hp_threshold_alt_dice" in w:
                _lbl("Alt Dice:", "hp_threshold_alt_dice")
                w["hp_threshold_alt_dice"].render(surface)

        # --- Reaction Trigger ---
        self._render_section_header(surface, SECTION_REACTION_TRIGGER, action)
        if self._section_expanded[SECTION_REACTION_TRIGGER]:
            if "reaction_trigger" in w:
                _lbl("Trigger:", "reaction_trigger")
                w["reaction_trigger"].render(surface)

        # --- Chain Effect ---
        self._render_section_header(surface, SECTION_CHAIN_EFFECT, action)
        if self._section_expanded[SECTION_CHAIN_EFFECT]:
            if "chain_target_count" in w:
                _lbl("Chain Targets:", "chain_target_count")
                w["chain_target_count"].render(surface)
            if "chain_range" in w:
                _lbl("Chain Range:", "chain_range")
                w["chain_range"].render(surface)
            if "chain_same_damage" in w:
                w["chain_same_damage"].render(surface)

        # --- Counterspell ---
        self._render_section_header(surface, SECTION_COUNTERSPELL, action)
        if self._section_expanded[SECTION_COUNTERSPELL]:
            if "is_counterspell" in w:
                w["is_counterspell"].render(surface)
            if "counterspell_auto_level" in w:
                _lbl("Auto Level (0=none):", "counterspell_auto_level")
                w["counterspell_auto_level"].render(surface)
            if "counterspell_check_dc_base" in w:
                _lbl("Check DC Base:", "counterspell_check_dc_base")
                w["counterspell_check_dc_base"].render(surface)

        # --- Wall Spell ---
        self._render_section_header(surface, SECTION_WALL_SPELL, action)
        if self._section_expanded[SECTION_WALL_SPELL]:
            if "is_wall" in w:
                w["is_wall"].render(surface)
            if "wall_length" in w:
                _lbl("Length:", "wall_length")
                w["wall_length"].render(surface)
            if "wall_height" in w:
                _lbl("Height:", "wall_height")
                w["wall_height"].render(surface)
            if "wall_thickness" in w:
                _lbl("Thick:", "wall_thickness")
                w["wall_thickness"].render(surface)
            if "wall_hp_per_panel" in w:
                _lbl("HP/Panel (0=inv):", "wall_hp_per_panel")
                w["wall_hp_per_panel"].render(surface)
            if "wall_blocks_movement" in w:
                w["wall_blocks_movement"].render(surface)
            if "wall_blocks_los" in w:
                w["wall_blocks_los"].render(surface)
            if "wall_damage_side" in w:
                _lbl("Dmg Side:", "wall_damage_side")
                w["wall_damage_side"].render(surface)
            if "wall_damage_on_enter" in w:
                _lbl("Dmg on Enter:", "wall_damage_on_enter")
                w["wall_damage_on_enter"].render(surface)
            if "wall_damage_type" in w:
                _lbl("Dmg Type:", "wall_damage_type")
                w["wall_damage_type"].render(surface)

        # --- Recurring Action ---
        self._render_section_header(surface, SECTION_RECURRING_ACTION, action)
        if self._section_expanded[SECTION_RECURRING_ACTION]:
            if "recurring_action_type" in w:
                _lbl("Action Type:", "recurring_action_type")
                w["recurring_action_type"].render(surface)
            if "recurring_damage_dice" in w:
                _lbl("Damage Dice:", "recurring_damage_dice")
                w["recurring_damage_dice"].render(surface)
            if "recurring_damage_type" in w:
                _lbl("Damage Type:", "recurring_damage_type")
                w["recurring_damage_type"].render(surface)
            if "recurring_auto_hit" in w:
                w["recurring_auto_hit"].render(surface)
            if "recurring_move_distance" in w:
                _lbl("Move Dist (ft):", "recurring_move_distance")
                w["recurring_move_distance"].render(surface)

        # ============================================================
        # OTHER FIELDS
        # ============================================================
        _lbl("Healing:", "healing")
        w["healing"].render(surface)

        _lbl("Temp HP:", "temp_hp")
        w["temp_hp"].render(surface)

        _lbl("Uses/Rest:", "uses_per_rest")
        w["uses_per_rest"].render(surface)

        _lbl("Rest:", "rest_type")
        w["rest_type"].render(surface)

        w["concentration"].render(surface)
        w["zone_follows_caster"].render(surface)

        _lbl("Zone Move:", "zone_move_cost")
        w["zone_move_cost"].render(surface)

        if "legendary_cost" in w:
            _lbl("Legendary Cost:", "legendary_cost")
            w["legendary_cost"].render(surface)

        # ============================================================
        # TELEPORTATION
        # ============================================================
        _lbl("Teleport Range (ft):", "teleport_range")
        w["teleport_range"].render(surface)
        w["teleport_self"].render(surface)
        w["teleport_passenger"].render(surface)

        _lbl("Origin Damage:", "teleport_origin_effect")
        w["teleport_origin_effect"].render(surface)
        _lbl("Origin Dmg Type:", "teleport_origin_damage_type")
        w["teleport_origin_damage_type"].render(surface)

        # ============================================================
        # FORCED MOVEMENT
        # ============================================================
        _lbl("Forced Movement:", "fm_type")
        w["fm_type"].render(surface)
        _lbl("Distance (ft):", "fm_distance")
        w["fm_distance"].render(surface)
        w["fm_prone"].render(surface)

        # ============================================================
        # TERRAIN MODIFICATION
        # ============================================================
        _lbl("Terrain Mod:", "terrain_modification")
        w["terrain_modification"].render(surface)

        # ============================================================
        # SUMMONING
        # ============================================================
        _lbl("Summon Creature:", "summon_creature")
        w["summon_creature"].render(surface)
        w["is_wild_shape"].render(surface)

        # ============================================================
        # CONDITIONS APPLIED / REMOVED
        # ============================================================
        cond_app = w.get("cond_applied")
        cond_rem = w.get("cond_removed")
        if cond_app:
            surface.blit(
                font.render("Conditions Applied:", True, label_color),
                (cond_app.rect.x, cond_app.rect.y - 16),
            )
            cond_app.render(surface)
        if cond_rem:
            surface.blit(
                font.render("Conditions Removed:", True, label_color),
                (cond_rem.rect.x, cond_rem.rect.y - 16),
            )
            cond_rem.render(surface)

        # ============================================================
        # RESOURCE COST
        # ============================================================
        res_key_0 = w.get("res_key_0")
        if res_key_0:
            hdr_y = res_key_0.rect.y - 22
            surface.blit(
                font.render("Resource Cost:", True, label_color),
                (ox, hdr_y),
            )
            _slbl("Resource Name", ox, res_key_0.rect.y - 10)
            _slbl("Amount", ox + 210, res_key_0.rect.y - 10)
        for ri in range(3):
            rk = w.get(f"res_key_{ri}")
            rv = w.get(f"res_val_{ri}")
            if rk:
                rk.render(surface)
            if rv:
                rv.render(surface)

        # ============================================================
        # AI FIELDS
        # ============================================================
        _lbl("AI Priority:", "ai_priority")
        w["ai_priority"].render(surface)

        _lbl("AI Condition:", "ai_condition")
        w["ai_condition"].render(surface)

        # ============================================================
        # Restore clip and draw scrollbar
        # ============================================================
        surface.set_clip(old_clip)

        # Scrollbar (right edge of detail panel)
        visible_h = detail_clip.height
        if self._detail_content_height > visible_h:
            bar_w = 6
            track_x = detail_clip.right - bar_w - 2
            track_y = detail_clip.y + 2
            track_h = visible_h - 4

            # Track
            track_color = parse_color(COLORS.get("bg_medium", "#2a2018"))
            pygame.draw.rect(
                surface, track_color,
                (track_x, track_y, bar_w, track_h),
                border_radius=bar_w // 2,
            )

            # Thumb
            thumb_ratio = visible_h / self._detail_content_height
            thumb_h = max(16, int(track_h * thumb_ratio))
            max_scroll = self._detail_content_height - visible_h + 20
            if max_scroll > 0:
                scroll_ratio = self.detail_scroll_y / max_scroll
            else:
                scroll_ratio = 0.0
            thumb_y = track_y + int((track_h - thumb_h) * scroll_ratio)

            thumb_color = parse_color(COLORS.get("border_accent", "#6b5530"))
            pygame.draw.rect(
                surface, thumb_color,
                (track_x, thumb_y, bar_w, thumb_h),
                border_radius=bar_w // 2,
            )

    def render_overlays(self, surface: pygame.Surface) -> None:
        for dd in self._detail_dropdowns:
            dd.render_dropdown(surface)
        for le in self._detail_list_editors:
            le.render_overlay(surface)
