"""Equipment tab — master-detail item editor for all creature types."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from arena.gui.renderer import draw_text_centered, get_font
from arena.gui.widgets import TextInput, NumberSpinner, Dropdown, Checkbox, ListEditor
from arena.models.items import (
    ItemType,
    WeaponProperty,
    EquipmentSlot,
    Rarity,
)
from arena.gui.screens.creature_builder_tabs.equipment_actions import (
    sync_equipment_actions,
    find_linked_action,
)
from arena.util.constants import COLORS, parse_color

if TYPE_CHECKING:
    from arena.gui.screens.character_builder import CreatureBuilderScreen

# Layout constants
LIST_PANEL_WIDTH = 300
DETAIL_PANEL_X_OFFSET = LIST_PANEL_WIDTH + 20

# Dropdown option lists (derived from enums)
ITEM_TYPE_OPTIONS = [e.value for e in ItemType]
EQUIPMENT_SLOT_OPTIONS = [e.value for e in EquipmentSlot]
RARITY_OPTIONS = [e.value for e in Rarity]
WEAPON_PROPERTY_OPTIONS = [e.value for e in WeaponProperty]
ARMOR_TYPE_OPTIONS = ["light", "medium", "heavy"]

DAMAGE_TYPE_OPTIONS = [
    "acid", "bludgeoning", "cold", "fire", "force", "lightning",
    "necrotic", "piercing", "poison", "psychic", "radiant",
    "slashing", "thunder",
]

ABILITY_OPTIONS = [
    "strength", "dexterity", "constitution",
    "intelligence", "wisdom", "charisma",
]

SAVE_ON_SUCCESS_OPTIONS = ["none", "half", "full"]

TARGET_TYPE_OPTIONS = [
    "self", "one_creature", "one_ally", "one_enemy",
    "area_sphere", "area_cone", "area_line", "area_cube", "area_cylinder",
]

CONDITION_OPTIONS = [
    "blinded", "charmed", "deafened", "exhaustion", "frightened",
    "grappled", "incapacitated", "invisible", "paralyzed", "petrified",
    "poisoned", "prone", "restrained", "stunned", "unconscious",
    "concentrating", "dodging", "helped", "hidden",
]

SENSES_OPTIONS = ["darkvision", "blindsight", "tremorsense", "truesight"]
ABILITY_ABBREV = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]

# Auto-slot mapping: when item type changes, suggest a default slot
_TYPE_TO_DEFAULT_SLOT = {
    "weapon": "main_hand",
    "armor": "armor",
    "shield": "off_hand",
    "potion": "none",
    "scroll": "none",
    "wondrous": "none",
    "tool": "none",
    "gear": "none",
}


def _default_item() -> dict:
    """Return a default new-item dict."""
    return {
        "name": "New Item",
        "item_type": "weapon",
        "description": "",
        "equipment_slot": "main_hand",
        "rarity": "common",
        "magic_bonus": 0,
        "requires_attunement": False,
        "is_magical": False,
        "weight": 0.0,
        "weapon_properties": [],
        "damage_dice": "",
        "damage_type": "slashing",
        "versatile_dice": "",
        "armor_class": None,
        "armor_type": None,
        "max_dex_bonus": None,
        "stealth_disadvantage": False,
        "strength_requirement": None,
        "range_normal": None,
        "range_long": None,
        "charges": None,
        "current_charges": None,
        "potion_action_type": None,
        "effect_healing": None,
        "effect_damage_dice": None,
        "effect_damage_type": None,
        "effect_target_type": None,
        "effect_range": None,
        "effect_save_ability": None,
        "effect_save_dc": None,
        "effect_save_damage_on_success": None,
        "effect_conditions_applied": [],
        "effect_conditions_removed": [],
        # Passive effect fields
        "bonus_ability_scores": {},
        "bonus_speed": 0,
        "bonus_ac": 0,
        "grants_damage_resistances": [],
        "grants_damage_immunities": [],
        "grants_condition_immunities": [],
        "grants_senses": {},
    }


class EquipmentTab:
    """Renders and handles the Equipment tab with master-detail layout."""

    def __init__(self, screen: CreatureBuilderScreen) -> None:
        self.screen = screen

        self.selected_index: int | None = None
        self.detail_scroll_y = 0
        self._prev_scroll_y = 0
        self.list_scroll_y = 0

        # Hover state
        self.add_hovered = False

        # Detail widgets
        self._detail_widgets: dict | None = None
        self._detail_dropdowns: list[Dropdown] = []
        self._detail_list_editors: list[ListEditor] = []
        self._detail_content_height: int = 0

        # Track the item type so we can detect changes
        self._current_item_type: str | None = None

        # Track item name for rename detection
        self._last_synced_item_name: str | None = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_selected_item(self) -> dict | None:
        if self.selected_index is not None:
            items = self.screen.equipment_data
            if 0 <= self.selected_index < len(items):
                return items[self.selected_index]
        return None

    def _get_list_panel_rect(self) -> pygame.Rect:
        return pygame.Rect(
            self.screen.content_rect.x,
            self.screen.content_rect.y,
            LIST_PANEL_WIDTH,
            self.screen.content_rect.height,
        )

    def _get_list_content_height(self) -> int:
        item_h = 28
        gap = 4
        count = len(self.screen.equipment_data)
        return 32 + max(count, 1) * (item_h + gap) + 10

    # ------------------------------------------------------------------
    # Scroll management (mirrors ActionsTab pattern)
    # ------------------------------------------------------------------

    def _shift_widget_rects(self, dy: int) -> None:
        if not self._detail_widgets or dy == 0:
            return
        for widget in self._detail_widgets.values():
            if hasattr(widget, "rect"):
                widget.rect.y += dy
            if isinstance(widget, NumberSpinner):
                widget.minus_btn.y += dy
                widget.plus_btn.y += dy
            if isinstance(widget, Checkbox):
                widget.box_rect.y += dy
            if isinstance(widget, ListEditor):
                widget.content_y += dy
                widget.add_btn.y += dy

    def _apply_scroll(self, new_scroll: int) -> None:
        delta = self._prev_scroll_y - new_scroll
        self.detail_scroll_y = new_scroll
        self._prev_scroll_y = new_scroll
        self._shift_widget_rects(delta)

    # ------------------------------------------------------------------
    # Detail panel — build widgets
    # ------------------------------------------------------------------

    def _build_detail_widgets(self) -> None:
        item = self._get_selected_item()
        if item is None:
            self._detail_widgets = None
            self._detail_dropdowns = []
            self._detail_list_editors = []
            self._detail_content_height = 0
            self._current_item_type = None
            return

        self.detail_scroll_y = 0
        self._prev_scroll_y = 0

        ox = self.screen.content_rect.x + DETAIL_PANEL_X_OFFSET
        oy = self.screen.content_rect.y + 10
        w = self.screen.content_rect.width - DETAIL_PANEL_X_OFFSET - 20

        widgets: dict = {}
        cy = oy

        item_type = item.get("item_type", "weapon")
        self._current_item_type = item_type

        # ============================================================
        # GENERAL FIELDS (always shown)
        # ============================================================

        # Name
        widgets["name"] = TextInput(
            pygame.Rect(ox, cy + 18, w, 26),
            value=item.get("name", ""),
            placeholder="Item name...",
        )
        cy += 48

        # Description
        widgets["description"] = TextInput(
            pygame.Rect(ox, cy + 18, w, 26),
            value=item.get("description", "") or "",
            max_length=120,
            placeholder="Description...",
        )
        cy += 48

        # Item Type + Equipment Slot
        widgets["item_type"] = Dropdown(
            pygame.Rect(ox, cy + 16, 160, 26),
            ITEM_TYPE_OPTIONS,
        )
        try:
            widgets["item_type"].selected_index = ITEM_TYPE_OPTIONS.index(item_type)
        except ValueError:
            pass

        slot = item.get("equipment_slot", "none")
        widgets["equipment_slot"] = Dropdown(
            pygame.Rect(ox + 180, cy + 16, 160, 26),
            EQUIPMENT_SLOT_OPTIONS,
        )
        try:
            widgets["equipment_slot"].selected_index = EQUIPMENT_SLOT_OPTIONS.index(slot)
        except ValueError:
            pass
        cy += 48

        # Rarity + Magic Bonus
        rarity = item.get("rarity", "common")
        widgets["rarity"] = Dropdown(
            pygame.Rect(ox, cy + 16, 160, 26),
            RARITY_OPTIONS,
        )
        try:
            widgets["rarity"].selected_index = RARITY_OPTIONS.index(rarity)
        except ValueError:
            pass

        widgets["magic_bonus"] = NumberSpinner(
            pygame.Rect(ox + 180, cy + 16, 120, 26),
            value=item.get("magic_bonus", 0),
            min_val=0, max_val=3,
        )
        cy += 48

        # Is Magical + Requires Attunement
        widgets["is_magical"] = Checkbox(
            pygame.Rect(ox, cy, 160, 24),
            "Magical",
            checked=item.get("is_magical", False),
        )
        widgets["requires_attunement"] = Checkbox(
            pygame.Rect(ox + 170, cy, 200, 24),
            "Requires Attunement",
            checked=item.get("requires_attunement", False),
        )
        cy += 30

        # Weight
        widgets["weight"] = NumberSpinner(
            pygame.Rect(ox, cy + 16, 120, 26),
            value=int(item.get("weight", 0)),
            min_val=0, max_val=200,
        )
        cy += 48

        # ============================================================
        # WEAPON SECTION (when type == "weapon")
        # ============================================================
        if item_type == "weapon":
            # Damage Dice + Damage Type
            widgets["damage_dice"] = TextInput(
                pygame.Rect(ox, cy + 18, 100, 26),
                value=item.get("damage_dice", "") or "",
                placeholder="e.g. 1d8",
                max_length=10,
            )
            dmg_type = item.get("damage_type", "slashing") or "slashing"
            widgets["damage_type"] = Dropdown(
                pygame.Rect(ox + 110, cy + 18, 140, 26),
                DAMAGE_TYPE_OPTIONS,
            )
            try:
                widgets["damage_type"].selected_index = DAMAGE_TYPE_OPTIONS.index(dmg_type)
            except ValueError:
                pass
            cy += 48

            # Versatile Dice
            widgets["versatile_dice"] = TextInput(
                pygame.Rect(ox, cy + 18, 100, 26),
                value=item.get("versatile_dice", "") or "",
                placeholder="e.g. 1d10",
                max_length=10,
            )
            cy += 48

            # Range Normal + Range Long
            widgets["range_normal"] = NumberSpinner(
                pygame.Rect(ox, cy + 16, 140, 26),
                value=item.get("range_normal", 0) or 0,
                min_val=0, max_val=600, step=5,
            )
            widgets["range_long"] = NumberSpinner(
                pygame.Rect(ox + 160, cy + 16, 140, 26),
                value=item.get("range_long", 0) or 0,
                min_val=0, max_val=600, step=5,
            )
            cy += 48

            # Weapon Properties
            current_props = item.get("weapon_properties", [])
            widgets["weapon_properties"] = ListEditor(
                pygame.Rect(ox, cy + 16, w, 80),
                items=list(current_props),
                allowed_values=WEAPON_PROPERTY_OPTIONS,
            )
            cy += 100

        # ============================================================
        # ARMOR SECTION (when type == "armor" or "shield")
        # ============================================================
        if item_type in ("armor", "shield"):
            # Base AC
            widgets["armor_class"] = NumberSpinner(
                pygame.Rect(ox, cy + 16, 120, 26),
                value=item.get("armor_class", 10) or 10,
                min_val=0, max_val=30,
            )
            cy += 48

            if item_type == "armor":
                # Armor Type
                armor_type = item.get("armor_type", "light") or "light"
                widgets["armor_type"] = Dropdown(
                    pygame.Rect(ox, cy + 16, 160, 26),
                    ARMOR_TYPE_OPTIONS,
                )
                try:
                    widgets["armor_type"].selected_index = ARMOR_TYPE_OPTIONS.index(armor_type)
                except ValueError:
                    pass
                cy += 48

            # Max Dex Bonus (-1 = unlimited)
            max_dex = item.get("max_dex_bonus")
            widgets["max_dex_bonus"] = NumberSpinner(
                pygame.Rect(ox, cy + 16, 140, 26),
                value=max_dex if max_dex is not None else -1,
                min_val=-1, max_val=10,
            )
            cy += 48

            # Strength Requirement
            widgets["strength_requirement"] = NumberSpinner(
                pygame.Rect(ox, cy + 16, 140, 26),
                value=item.get("strength_requirement", 0) or 0,
                min_val=0, max_val=30,
            )

            # Stealth Disadvantage
            widgets["stealth_disadvantage"] = Checkbox(
                pygame.Rect(ox + 160, cy + 16, 220, 24),
                "Stealth Disadvantage",
                checked=item.get("stealth_disadvantage", False),
            )
            cy += 48

        # ============================================================
        # CONSUMABLE SECTION (when type == "potion" or "scroll")
        # ============================================================
        if item_type in ("potion", "scroll"):
            widgets["charges"] = NumberSpinner(
                pygame.Rect(ox, cy + 16, 140, 26),
                value=item.get("charges", 1) or 1,
                min_val=0, max_val=20,
            )
            widgets["current_charges"] = NumberSpinner(
                pygame.Rect(ox + 160, cy + 16, 140, 26),
                value=item.get("current_charges", 1) or 1,
                min_val=0, max_val=20,
            )
            cy += 48

            # Action type (action vs bonus action)
            action_type_options = ["action", "bonus_action"]
            act_type = item.get("potion_action_type", "action") or "action"
            widgets["potion_action_type"] = Dropdown(
                pygame.Rect(ox, cy + 16, 180, 26),
                action_type_options,
            )
            try:
                widgets["potion_action_type"].selected_index = (
                    action_type_options.index(act_type)
                )
            except ValueError:
                pass
            cy += 48

            # --- EFFECT FIELDS ---

            # Healing dice
            widgets["effect_healing"] = TextInput(
                pygame.Rect(ox, cy + 18, 140, 26),
                value=item.get("effect_healing", "") or "",
                placeholder="e.g. 2d4+2",
                max_length=20,
            )
            cy += 48

            # Target type + Range
            effect_target = item.get("effect_target_type", "self") or "self"
            widgets["effect_target_type"] = Dropdown(
                pygame.Rect(ox, cy + 16, 180, 26),
                TARGET_TYPE_OPTIONS,
            )
            try:
                widgets["effect_target_type"].selected_index = (
                    TARGET_TYPE_OPTIONS.index(effect_target)
                )
            except ValueError:
                pass

            widgets["effect_range"] = NumberSpinner(
                pygame.Rect(ox + 200, cy + 16, 140, 26),
                value=item.get("effect_range", 0) or 0,
                min_val=0, max_val=300, step=5,
            )
            cy += 48

            # Effect damage dice + type
            widgets["effect_damage_dice"] = TextInput(
                pygame.Rect(ox, cy + 18, 100, 26),
                value=item.get("effect_damage_dice", "") or "",
                placeholder="e.g. 8d6",
                max_length=10,
            )
            eff_dmg_type = item.get("effect_damage_type", "fire") or "fire"
            widgets["effect_damage_type"] = Dropdown(
                pygame.Rect(ox + 110, cy + 18, 140, 26),
                DAMAGE_TYPE_OPTIONS,
            )
            try:
                widgets["effect_damage_type"].selected_index = (
                    DAMAGE_TYPE_OPTIONS.index(eff_dmg_type)
                )
            except ValueError:
                pass
            cy += 48

            # Saving throw: ability + DC
            save_ability_opts = ["(none)"] + ABILITY_OPTIONS
            eff_save = item.get("effect_save_ability") or ""
            widgets["effect_save_ability"] = Dropdown(
                pygame.Rect(ox, cy + 16, 160, 26),
                save_ability_opts,
            )
            try:
                if eff_save:
                    widgets["effect_save_ability"].selected_index = (
                        save_ability_opts.index(eff_save)
                    )
            except ValueError:
                pass

            widgets["effect_save_dc"] = NumberSpinner(
                pygame.Rect(ox + 180, cy + 16, 100, 26),
                value=item.get("effect_save_dc", 10) or 10,
                min_val=1, max_val=30,
            )

            save_succ = item.get("effect_save_damage_on_success", "none") or "none"
            widgets["effect_save_damage_on_success"] = Dropdown(
                pygame.Rect(ox + 300, cy + 16, 100, 26),
                SAVE_ON_SUCCESS_OPTIONS,
            )
            try:
                widgets["effect_save_damage_on_success"].selected_index = (
                    SAVE_ON_SUCCESS_OPTIONS.index(save_succ)
                )
            except ValueError:
                pass
            cy += 48

            # Conditions applied / removed
            half_w = (w - 10) // 2
            cond_app = item.get("effect_conditions_applied", [])
            cond_rem = item.get("effect_conditions_removed", [])

            widgets["effect_conditions_applied"] = ListEditor(
                pygame.Rect(ox, cy + 16, half_w, 76),
                items=list(cond_app),
                allowed_values=CONDITION_OPTIONS,
            )
            widgets["effect_conditions_removed"] = ListEditor(
                pygame.Rect(ox + half_w + 10, cy + 16, half_w, 76),
                items=list(cond_rem),
                allowed_values=CONDITION_OPTIONS,
            )
            cy += 96

        # ── Passive Effects section (shown for ALL item types) ──────────
        cy += 12  # gap before section

        # Ability score bonuses — 3×2 grid
        ability_bonuses = item.get("bonus_ability_scores", {})
        col_w = (w - 10) // 3
        for row in range(2):
            for col in range(3):
                idx = row * 3 + col
                ab_name = ABILITY_OPTIONS[idx]
                ab_key = f"bonus_{ab_name}"
                widgets[ab_key] = NumberSpinner(
                    pygame.Rect(ox + col * col_w + 38, cy + 16, 70, 26),
                    value=ability_bonuses.get(ab_name, 0),
                    min_val=-5, max_val=6,
                )
            cy += 48

        # Speed bonus + AC bonus (side by side)
        widgets["bonus_speed"] = NumberSpinner(
            pygame.Rect(ox, cy + 16, 120, 26),
            value=item.get("bonus_speed", 0),
            min_val=-30, max_val=30, step=5,
        )
        widgets["bonus_ac"] = NumberSpinner(
            pygame.Rect(ox + 180, cy + 16, 100, 26),
            value=item.get("bonus_ac", 0),
            min_val=0, max_val=3,
        )
        cy += 48

        # Damage resistances granted
        grant_res = item.get("grants_damage_resistances", [])
        widgets["grants_damage_resistances"] = ListEditor(
            pygame.Rect(ox, cy + 16, w, 76),
            items=list(grant_res),
            allowed_values=DAMAGE_TYPE_OPTIONS,
        )
        cy += 96

        # Damage immunities granted
        grant_imm = item.get("grants_damage_immunities", [])
        widgets["grants_damage_immunities"] = ListEditor(
            pygame.Rect(ox, cy + 16, w, 76),
            items=list(grant_imm),
            allowed_values=DAMAGE_TYPE_OPTIONS,
        )
        cy += 96

        # Condition immunities granted
        grant_ci = item.get("grants_condition_immunities", [])
        widgets["grants_condition_immunities"] = ListEditor(
            pygame.Rect(ox, cy + 16, w, 76),
            items=list(grant_ci),
            allowed_values=CONDITION_OPTIONS,
        )
        cy += 96

        # Senses granted — 4 compact spinners
        current_senses = item.get("grants_senses", {})
        for sense_name in SENSES_OPTIONS:
            sense_key = f"grants_sense_{sense_name}"
            widgets[sense_key] = NumberSpinner(
                pygame.Rect(ox + 110, cy + 16, 100, 26),
                value=current_senses.get(sense_name, 0),
                min_val=0, max_val=300, step=10,
            )
            cy += 38
        cy += 10  # pad after senses

        # Track item name for rename detection
        self._last_synced_item_name = item.get("name")

        # Finalize
        self._detail_widgets = widgets
        self._detail_content_height = cy - oy

        self._detail_dropdowns = [
            v for v in widgets.values() if isinstance(v, Dropdown)
        ]
        self._detail_list_editors = [
            v for v in widgets.values() if isinstance(v, ListEditor)
        ]

    # ------------------------------------------------------------------
    # Sync detail widgets → item dict
    # ------------------------------------------------------------------

    def _sync_detail_to_item(self) -> None:
        item = self._get_selected_item()
        if item is None or self._detail_widgets is None:
            return

        w = self._detail_widgets

        item["name"] = w["name"].value
        item["description"] = w["description"].value or None

        new_type = w["item_type"].value
        old_type = self._current_item_type

        item["item_type"] = new_type
        item["equipment_slot"] = w["equipment_slot"].value
        item["rarity"] = w["rarity"].value
        item["magic_bonus"] = w["magic_bonus"].value
        item["is_magical"] = w["is_magical"].checked
        item["requires_attunement"] = w["requires_attunement"].checked
        item["weight"] = float(w["weight"].value)

        # Weapon fields
        if new_type == "weapon":
            item["damage_dice"] = w.get("damage_dice") and w["damage_dice"].value or None
            item["damage_type"] = w.get("damage_type") and w["damage_type"].value or None
            item["versatile_dice"] = w.get("versatile_dice") and w["versatile_dice"].value or None
            rn = w.get("range_normal")
            rl = w.get("range_long")
            item["range_normal"] = rn.value if rn and rn.value > 0 else None
            item["range_long"] = rl.value if rl and rl.value > 0 else None
            wp = w.get("weapon_properties")
            item["weapon_properties"] = list(wp.items) if wp else []

        # Armor/Shield fields
        if new_type in ("armor", "shield"):
            ac = w.get("armor_class")
            item["armor_class"] = ac.value if ac else None
            at = w.get("armor_type")
            item["armor_type"] = at.value if at else None
            md = w.get("max_dex_bonus")
            item["max_dex_bonus"] = md.value if md and md.value >= 0 else None
            sr = w.get("strength_requirement")
            item["strength_requirement"] = sr.value if sr and sr.value > 0 else None
            sd = w.get("stealth_disadvantage")
            item["stealth_disadvantage"] = sd.checked if sd else False

        # Consumable fields (potion + scroll)
        if new_type in ("potion", "scroll"):
            ch = w.get("charges")
            item["charges"] = ch.value if ch else None
            cc = w.get("current_charges")
            item["current_charges"] = cc.value if cc else None
            pat = w.get("potion_action_type")
            item["potion_action_type"] = pat.value if pat else "action"

            # Effect fields
            eh = w.get("effect_healing")
            item["effect_healing"] = eh.value if eh and eh.value else None

            ett = w.get("effect_target_type")
            item["effect_target_type"] = ett.value if ett else "self"

            er = w.get("effect_range")
            item["effect_range"] = er.value if er and er.value > 0 else None

            edd = w.get("effect_damage_dice")
            item["effect_damage_dice"] = edd.value if edd and edd.value else None

            edt = w.get("effect_damage_type")
            item["effect_damage_type"] = edt.value if edt else None

            esa = w.get("effect_save_ability")
            save_val = esa.value if esa else "(none)"
            item["effect_save_ability"] = (
                save_val if save_val != "(none)" else None
            )

            esd = w.get("effect_save_dc")
            item["effect_save_dc"] = esd.value if esd else None

            esds = w.get("effect_save_damage_on_success")
            item["effect_save_damage_on_success"] = (
                esds.value if esds else "none"
            )

            eca = w.get("effect_conditions_applied")
            item["effect_conditions_applied"] = (
                list(eca.items) if eca else []
            )

            ecr = w.get("effect_conditions_removed")
            item["effect_conditions_removed"] = (
                list(ecr.items) if ecr else []
            )

        # Passive effect fields (synced for ALL item types)
        ability_bonuses = {}
        for ab_name in ABILITY_OPTIONS:
            ab_widget = w.get(f"bonus_{ab_name}")
            if ab_widget and ab_widget.value != 0:
                ability_bonuses[ab_name] = ab_widget.value
        item["bonus_ability_scores"] = ability_bonuses

        bs = w.get("bonus_speed")
        item["bonus_speed"] = bs.value if bs else 0

        bac = w.get("bonus_ac")
        item["bonus_ac"] = bac.value if bac else 0

        gdr = w.get("grants_damage_resistances")
        item["grants_damage_resistances"] = list(gdr.items) if gdr else []

        gdi = w.get("grants_damage_immunities")
        item["grants_damage_immunities"] = list(gdi.items) if gdi else []

        gci = w.get("grants_condition_immunities")
        item["grants_condition_immunities"] = list(gci.items) if gci else []

        senses = {}
        for sense_name in SENSES_OPTIONS:
            sense_widget = w.get(f"grants_sense_{sense_name}")
            if sense_widget and sense_widget.value > 0:
                senses[sense_name] = sense_widget.value
        item["grants_senses"] = senses

        # Handle rename: update linked action's source_item before sync
        old_name = self._last_synced_item_name
        new_name = item["name"]
        if old_name and old_name != new_name:
            loc = find_linked_action(self.screen.actions_data, old_name)
            if loc is not None:
                cat, idx = loc
                self.screen.actions_data[cat][idx]["source_item"] = new_name
        self._last_synced_item_name = new_name

        # If item type changed, auto-set slot and rebuild
        if new_type != old_type:
            default_slot = _TYPE_TO_DEFAULT_SLOT.get(new_type, "none")
            item["equipment_slot"] = default_slot
            self._build_detail_widgets()

        # Sync equipment-generated actions
        sync_equipment_actions(self.screen.equipment_data, self.screen.actions_data)

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
                self._sync_detail_to_item()
                return True

        # Open ListEditor pickers get priority
        for le in self._detail_list_editors:
            if le.is_picker_open and le.handle_event(event):
                self._sync_detail_to_item()
                return True

        # Scrolling
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

        # Detail panel widgets
        if self._detail_widgets:
            for v in self._detail_widgets.values():
                if hasattr(v, "handle_event") and v.handle_event(event):
                    self._sync_detail_to_item()
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
        list_rect = self._get_list_panel_rect()
        if not list_rect.collidepoint(pos):
            return False

        ox = self.screen.content_rect.x + 10
        oy = self.screen.content_rect.y + 10 - self.list_scroll_y
        item_h = 28
        gap = 4

        # Add button
        add_rect = pygame.Rect(ox + LIST_PANEL_WIDTH - 75, oy, 56, 22)
        if add_rect.collidepoint(pos):
            self.screen.equipment_data.append(_default_item())
            self.selected_index = len(self.screen.equipment_data) - 1
            self._build_detail_widgets()
            return True

        current_y = oy + 28  # below header line

        items = self.screen.equipment_data
        for i, item_data in enumerate(items):
            item_rect = pygame.Rect(ox, current_y, LIST_PANEL_WIDTH - 50, item_h)
            rm_rect = pygame.Rect(
                ox + LIST_PANEL_WIDTH - 45, current_y + 4, 20, 20,
            )

            if rm_rect.collidepoint(pos):
                items.pop(i)
                if self.selected_index == i:
                    self.selected_index = None
                    self._detail_widgets = None
                    self._detail_dropdowns = []
                    self._detail_list_editors = []
                elif (self.selected_index is not None
                      and self.selected_index > i):
                    self.selected_index -= 1
                    self._build_detail_widgets()
                # Remove any linked actions for deleted equipment
                sync_equipment_actions(
                    self.screen.equipment_data, self.screen.actions_data,
                )
                return True

            if item_rect.collidepoint(pos):
                self.selected_index = i
                self._build_detail_widgets()
                return True

            current_y += item_h + gap

        return False

    def _update_hover(self, pos: tuple[int, int]) -> None:
        ox = self.screen.content_rect.x + 10
        oy = self.screen.content_rect.y + 10 - self.list_scroll_y
        add_rect = pygame.Rect(ox + LIST_PANEL_WIDTH - 75, oy, 56, 22)
        self.add_hovered = add_rect.collidepoint(pos)

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

        # Header
        header_surf = font.render(
            "Equipment", True, parse_color(COLORS["text_primary"]),
        )
        surface.blit(header_surf, (ox, oy + 2))

        # Add button
        add_rect = pygame.Rect(ox + LIST_PANEL_WIDTH - 75, oy, 56, 22)
        add_color = (
            parse_color(COLORS["button_hover"]) if self.add_hovered
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

        current_y = oy + 28

        items = self.screen.equipment_data
        for i, item_data in enumerate(items):
            item_rect = pygame.Rect(
                ox, current_y, LIST_PANEL_WIDTH - 50, item_h,
            )
            selected = i == self.selected_index
            bg = (
                parse_color(COLORS["button_active"]) if selected
                else parse_color(COLORS["button_normal"])
            )
            pygame.draw.rect(surface, bg, item_rect, border_radius=3)
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                item_rect, 1, border_radius=3,
            )

            name = item_data.get("name", "(unnamed)")
            itype = item_data.get("item_type", "")
            label = f"{name} ({itype})" if itype else name
            name_surf = small_font.render(
                label, True, parse_color(COLORS["text_primary"]),
            )
            surface.blit(name_surf, (item_rect.x + 6, current_y + 6))

            # Remove [x]
            draw_text_centered(
                surface, "x",
                (ox + LIST_PANEL_WIDTH - 35, current_y + item_h // 2),
                parse_color(COLORS["text_secondary"]), font_size=12,
            )

            current_y += item_h + gap

        if not items:
            empty = small_font.render("(no equipment)", True, label_color)
            surface.blit(empty, (ox + 6, current_y + 2))

        surface.set_clip(old_clip)

        # Scrollbar
        list_content_h = self._get_list_content_height()
        visible_h = list_clip.height
        if list_content_h > visible_h:
            bar_w = 5
            bar_margin = 2
            track_x = list_clip.x + bar_margin
            track_y = list_clip.y + bar_margin
            track_h = visible_h - bar_margin * 2

            track_color = parse_color(COLORS.get("bg_medium", "#2a2018"))
            pygame.draw.rect(
                surface, track_color,
                (track_x, track_y, bar_w, track_h),
                border_radius=bar_w // 2,
            )

            thumb_ratio = visible_h / list_content_h
            thumb_h = max(16, int(track_h * thumb_ratio))
            max_scroll = list_content_h - visible_h + 20
            scroll_ratio = self.list_scroll_y / max_scroll if max_scroll > 0 else 0.0
            thumb_y = track_y + int((track_h - thumb_h) * scroll_ratio)

            thumb_color = parse_color(COLORS.get("border_accent", "#6b5530"))
            pygame.draw.rect(
                surface, thumb_color,
                (track_x, thumb_y, bar_w, thumb_h),
                border_radius=bar_w // 2,
            )

        # Separator
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
        label_color = parse_color(COLORS["text_secondary"])

        item = self._get_selected_item()
        if item is None or self._detail_widgets is None:
            msg = font.render(
                "Select an item to edit", True, label_color,
            )
            surface.blit(msg, (ox, oy_base + 40))
            return

        w = self._detail_widgets
        item_type = item.get("item_type", "weapon")

        # Clip for scrolling
        detail_clip = pygame.Rect(
            ox - 5,
            self.screen.content_rect.y,
            self.screen.content_rect.width - DETAIL_PANEL_X_OFFSET + 10,
            self.screen.content_rect.height,
        )
        old_clip = surface.get_clip()
        surface.set_clip(detail_clip)

        def _lbl(text: str, widget_key: str) -> None:
            wgt = w.get(widget_key)
            if wgt is None:
                return
            surface.blit(
                font.render(text, True, label_color),
                (wgt.rect.x, wgt.rect.y - 18),
            )

        # General fields
        _lbl("Name:", "name")
        w["name"].render(surface)

        _lbl("Description:", "description")
        w["description"].render(surface)

        _lbl("Item Type:", "item_type")
        w["item_type"].render(surface)
        _lbl("Slot:", "equipment_slot")
        w["equipment_slot"].render(surface)

        _lbl("Rarity:", "rarity")
        w["rarity"].render(surface)
        _lbl("Magic +:", "magic_bonus")
        w["magic_bonus"].render(surface)

        w["is_magical"].render(surface)
        w["requires_attunement"].render(surface)

        _lbl("Weight:", "weight")
        w["weight"].render(surface)

        # Weapon section
        if item_type == "weapon":
            _lbl("Damage Dice:", "damage_dice")
            w["damage_dice"].render(surface)
            _lbl("Damage Type:", "damage_type")
            w["damage_type"].render(surface)

            _lbl("Versatile Dice:", "versatile_dice")
            w["versatile_dice"].render(surface)

            _lbl("Range:", "range_normal")
            w["range_normal"].render(surface)
            _lbl("Long Range:", "range_long")
            w["range_long"].render(surface)

            wp = w.get("weapon_properties")
            if wp:
                surface.blit(
                    font.render("Weapon Properties:", True, label_color),
                    (wp.rect.x, wp.rect.y - 16),
                )
                wp.render(surface)

        # Armor section
        if item_type in ("armor", "shield"):
            _lbl("Base AC:", "armor_class")
            w["armor_class"].render(surface)

            if item_type == "armor":
                _lbl("Armor Type:", "armor_type")
                w["armor_type"].render(surface)

            _lbl("Max Dex (-1=no limit):", "max_dex_bonus")
            w["max_dex_bonus"].render(surface)

            _lbl("STR Req:", "strength_requirement")
            w["strength_requirement"].render(surface)

            sd = w.get("stealth_disadvantage")
            if sd:
                sd.render(surface)

        # Consumable section (potion + scroll)
        if item_type in ("potion", "scroll"):
            _lbl("Charges:", "charges")
            w["charges"].render(surface)
            _lbl("Current:", "current_charges")
            w["current_charges"].render(surface)

            _lbl("Action Type:", "potion_action_type")
            pat_w = w.get("potion_action_type")
            if pat_w:
                pat_w.render(surface)

            # Effect fields
            _lbl("Healing:", "effect_healing")
            eh_w = w.get("effect_healing")
            if eh_w:
                eh_w.render(surface)

            _lbl("Target:", "effect_target_type")
            ett_w = w.get("effect_target_type")
            if ett_w:
                ett_w.render(surface)
            _lbl("Range:", "effect_range")
            er_w = w.get("effect_range")
            if er_w:
                er_w.render(surface)

            _lbl("Dmg Dice:", "effect_damage_dice")
            edd_w = w.get("effect_damage_dice")
            if edd_w:
                edd_w.render(surface)
            _lbl("Dmg Type:", "effect_damage_type")
            edt_w = w.get("effect_damage_type")
            if edt_w:
                edt_w.render(surface)

            _lbl("Save Ability:", "effect_save_ability")
            esa_w = w.get("effect_save_ability")
            if esa_w:
                esa_w.render(surface)
            _lbl("DC:", "effect_save_dc")
            esd_w = w.get("effect_save_dc")
            if esd_w:
                esd_w.render(surface)
            _lbl("On Succ:", "effect_save_damage_on_success")
            esds_w = w.get("effect_save_damage_on_success")
            if esds_w:
                esds_w.render(surface)

            # Conditions applied / removed
            eca_w = w.get("effect_conditions_applied")
            ecr_w = w.get("effect_conditions_removed")
            if eca_w:
                surface.blit(
                    font.render("Conditions Applied:", True, label_color),
                    (eca_w.rect.x, eca_w.rect.y - 16),
                )
                eca_w.render(surface)
            if ecr_w:
                surface.blit(
                    font.render("Conditions Removed:", True, label_color),
                    (ecr_w.rect.x, ecr_w.rect.y - 16),
                )
                ecr_w.render(surface)

        # ── Passive Effects section ──
        first_ab = w.get("bonus_strength")
        if first_ab:
            # Section header
            header_y = first_ab.rect.y - 34
            surface.blit(
                font.render("── Passive Effects ──", True, label_color),
                (ox, header_y),
            )

            # Ability score bonus labels + spinners
            for row in range(2):
                for col in range(3):
                    idx = row * 3 + col
                    ab_name = ABILITY_OPTIONS[idx]
                    ab_key = f"bonus_{ab_name}"
                    ab_w = w.get(ab_key)
                    if ab_w:
                        surface.blit(
                            font.render(
                                ABILITY_ABBREV[idx] + ":", True, label_color
                            ),
                            (ab_w.rect.x - 36, ab_w.rect.y + 4),
                        )
                        ab_w.render(surface)

        # Speed bonus + AC bonus
        bs_w = w.get("bonus_speed")
        if bs_w:
            surface.blit(
                font.render("Speed:", True, label_color),
                (bs_w.rect.x - 2, bs_w.rect.y - 16),
            )
            bs_w.render(surface)
        bac_w = w.get("bonus_ac")
        if bac_w:
            surface.blit(
                font.render("AC:", True, label_color),
                (bac_w.rect.x - 2, bac_w.rect.y - 16),
            )
            bac_w.render(surface)

        # Resistance / immunity / condition immunity ListEditors
        gdr_w = w.get("grants_damage_resistances")
        if gdr_w:
            surface.blit(
                font.render("Grants Resistances:", True, label_color),
                (gdr_w.rect.x, gdr_w.rect.y - 16),
            )
            gdr_w.render(surface)

        gdi_w = w.get("grants_damage_immunities")
        if gdi_w:
            surface.blit(
                font.render("Grants Immunities:", True, label_color),
                (gdi_w.rect.x, gdi_w.rect.y - 16),
            )
            gdi_w.render(surface)

        gci_w = w.get("grants_condition_immunities")
        if gci_w:
            surface.blit(
                font.render("Grants Cond. Immunities:", True, label_color),
                (gci_w.rect.x, gci_w.rect.y - 16),
            )
            gci_w.render(surface)

        # Senses spinners
        for sense_name in SENSES_OPTIONS:
            sense_key = f"grants_sense_{sense_name}"
            sense_w = w.get(sense_key)
            if sense_w:
                surface.blit(
                    font.render(
                        f"{sense_name.capitalize()}:", True, label_color
                    ),
                    (sense_w.rect.x - 108, sense_w.rect.y + 4),
                )
                sense_w.render(surface)

        # Restore clip and draw scrollbar
        surface.set_clip(old_clip)

        visible_h = detail_clip.height
        if self._detail_content_height > visible_h:
            bar_w = 6
            track_x = detail_clip.right - bar_w - 2
            track_y = detail_clip.y + 2
            track_h = visible_h - 4

            track_color = parse_color(COLORS.get("bg_medium", "#2a2018"))
            pygame.draw.rect(
                surface, track_color,
                (track_x, track_y, bar_w, track_h),
                border_radius=bar_w // 2,
            )

            thumb_ratio = visible_h / self._detail_content_height
            thumb_h = max(16, int(track_h * thumb_ratio))
            max_scroll = self._detail_content_height - visible_h + 20
            scroll_ratio = self.detail_scroll_y / max_scroll if max_scroll > 0 else 0.0
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
