"""Lair Action Editor popup — used in the encounter setup screen.

Allows the DM to add, edit, and remove encounter-level lair actions.
Supports saving throw effects with damage, conditions, healing,
temporary HP, and summoning.  Each optional section is toggled by a
checkbox so the user only sees what's relevant.
"""

from __future__ import annotations

from pathlib import Path

import pygame

from arena.gui.renderer import get_font, draw_text_centered
from arena.gui.button_images import draw_image_button
from arena.gui.widgets.checkbox import Checkbox
from arena.gui.widgets.dropdown import Dropdown
from arena.gui.widgets.list_editor import ListEditor
from arena.models.actions import Action, ActionType, DamageRoll, DamageType, SavingThrowEffect
from arena.util.constants import COLORS, parse_color
from arena.util.loader import load_json


_SAVE_ABILITIES = ["strength", "dexterity", "constitution",
                   "intelligence", "wisdom", "charisma"]

_DAMAGE_TYPES = [dt.value for dt in DamageType]

# Conditions that make sense for lair actions (no source creature needed)
_LAIR_CONDITIONS = [
    "blinded", "frightened", "grappled", "paralyzed",
    "poisoned", "prone", "restrained", "stunned",
]

# Placeholder for "no creature selected"
_NO_SUMMON = "(none)"


def _scan_creature_options() -> tuple[list[str], list[str]]:
    """Scan data/monsters and data/characters for JSON files.

    Returns (display_names, file_paths) where display_names[i]
    corresponds to file_paths[i].  The first entry is the placeholder.
    """
    display_names: list[str] = [_NO_SUMMON]
    file_paths: list[str] = [""]
    data_dir = Path("data")

    for subdir, label in [("monsters", "Monster"), ("characters", "Character")]:
        folder = data_dir / subdir
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                data = load_json(path)
                name = data.get("name", path.stem)
                display = f"{name}  ({label})"
                rel_path = f"{subdir}/{path.name}"
                display_names.append(display)
                file_paths.append(rel_path)
            except Exception:
                continue

    return display_names, file_paths


class LairActionEditor:
    """Modal popup for editing encounter-level lair actions.

    Opened from the encounter setup screen.  Manages a list of lair
    Action objects with add / edit / remove functionality.

    Returns ``"__done__"`` from ``handle_event`` when the user closes
    the editor.  Call ``get_actions()`` to retrieve the edited list.
    """

    WIDTH = 620
    # Height is dynamically computed based on enabled sections
    MIN_HEIGHT = 340
    MAX_HEIGHT = 700

    def __init__(
        self,
        lair_actions: list[Action],
        screen_width: int,
        screen_height: int,
    ) -> None:
        self.actions: list[Action] = [
            a.model_copy(deep=True) for a in lair_actions
        ]
        self.selected_index: int | None = (
            0 if self.actions else None
        )
        self._screen_width = screen_width
        self._screen_height = screen_height

        # Active text input field
        # (None, "name", "description", "dc", "dice", "heal", "temp_hp")
        self._active_field: str | None = None

        # Scan creature files for summon dropdown
        self._summon_display, self._summon_paths = _scan_creature_options()

        # Section toggle checkboxes (created with dummy rects, rebuilt later)
        _dummy = pygame.Rect(0, 0, 1, 1)
        self.cb_save = Checkbox(_dummy, "Requires Saving Throw", checked=True)
        self.cb_damage = Checkbox(_dummy, "Deal Damage", checked=True)
        self.cb_conditions = Checkbox(_dummy, "Apply Conditions", checked=False)
        self.cb_heal = Checkbox(_dummy, "Heal Allies", checked=False)
        self.cb_temp_hp = Checkbox(_dummy, "Grant Temp HP", checked=False)
        self.cb_summon = Checkbox(_dummy, "Summon Creature", checked=False)

        # Save ability dropdown (created with dummy rect, rebuilt later)
        self.save_dropdown = Dropdown(
            _dummy,
            options=[a.title() for a in _SAVE_ABILITIES],
            selected_index=1,  # default Dexterity
            max_visible=6,
        )

        # Damage type dropdown
        self.dmg_type_dropdown = Dropdown(
            _dummy,
            options=[dt.replace("_", " ").title() for dt in _DAMAGE_TYPES],
            selected_index=_DAMAGE_TYPES.index("fire"),
            max_visible=8,
        )

        # Conditions on fail (ListEditor)
        self.cond_fail_editor = ListEditor(
            _dummy,
            items=[],
            item_height=24,
            allowed_values=_LAIR_CONDITIONS,
        )

        # Summon creature dropdown
        self.summon_dropdown = Dropdown(
            _dummy,
            options=self._summon_display,
            selected_index=0,
            max_visible=8,
        )

        # Build layout rects
        self._build_rects()

        # Sync initial selection
        if self.selected_index is not None:
            self._sync_form_from_action(self.actions[self.selected_index])

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_rects(self) -> None:
        """Compute all widget positions based on current checkbox states."""
        row_h = 28
        gap = 4
        cb_h = 26  # checkbox row height
        indent = 24  # indent for fields inside a checkbox section

        # Edit area measurements
        edit_w = self.WIDTH - 210
        # We'll compute total height dynamically
        # Start by measuring how tall the edit area needs to be

        # Fixed rows: title(36) + name + desc = 36 + 2*(row_h+gap)
        content_h = 36 + 2 * (row_h + gap)

        # Saving throw checkbox
        content_h += cb_h + gap
        if self.cb_save.checked:
            # Save ability + DC rows
            content_h += 2 * (row_h + gap)
            # Damage checkbox
            content_h += cb_h + gap
            if self.cb_damage.checked:
                # Dice + half-on-save rows
                content_h += 2 * (row_h + gap)
            # Conditions checkbox
            content_h += cb_h + gap
            if self.cb_conditions.checked:
                content_h += 80 + gap  # ListEditor

        # Heal checkbox
        content_h += cb_h + gap
        if self.cb_heal.checked:
            content_h += row_h + gap

        # Temp HP checkbox
        content_h += cb_h + gap
        if self.cb_temp_hp.checked:
            content_h += row_h + gap

        # Summon checkbox
        content_h += cb_h + gap
        if self.cb_summon.checked:
            content_h += row_h + gap

        # Bottom buttons
        content_h += 44

        height = max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, content_h))

        cx = self._screen_width // 2
        cy = self._screen_height // 2
        self.rect = pygame.Rect(
            cx - self.WIDTH // 2, cy - height // 2,
            self.WIDTH, height,
        )

        x, y = self.rect.x, self.rect.y

        # List area (left)
        self.list_rect = pygame.Rect(x + 8, y + 36, 180, height - 80)
        self.add_btn = pygame.Rect(x + 8, self.rect.bottom - 38, 86, 28)
        self.remove_btn = pygame.Rect(x + 100, self.rect.bottom - 38, 86, 28)

        # Edit area (right) — position widgets top-down
        edit_x = x + 200

        ey = y + 40

        # Name
        self.name_rect = pygame.Rect(edit_x + 80, ey, edit_w - 80, row_h)
        ey += row_h + gap

        # Description
        self.desc_rect = pygame.Rect(edit_x + 80, ey, edit_w - 80, row_h)
        ey += row_h + gap

        # --- Saving throw section ---
        self.cb_save.rect = pygame.Rect(edit_x, ey, edit_w, cb_h)
        self.cb_save.box_rect = pygame.Rect(
            edit_x, ey + (cb_h - 20) // 2, 20, 20,
        )
        ey += cb_h + gap

        if self.cb_save.checked:
            # Save ability dropdown
            self.save_dropdown.rect = pygame.Rect(
                edit_x + indent + 80, ey, 130, 24,
            )
            self._save_label_y = ey + 2
            ey += row_h + gap

            # DC
            self.dc_rect = pygame.Rect(edit_x + indent + 80, ey, 60, row_h)
            self._dc_label_y = ey + 4
            ey += row_h + gap

            # --- Damage sub-section ---
            self.cb_damage.rect = pygame.Rect(
                edit_x + indent, ey, edit_w - indent, cb_h,
            )
            self.cb_damage.box_rect = pygame.Rect(
                edit_x + indent, ey + (cb_h - 20) // 2, 20, 20,
            )
            ey += cb_h + gap

            if self.cb_damage.checked:
                # Dice + damage type
                self.dice_rect = pygame.Rect(
                    edit_x + indent + 80, ey, 80, row_h,
                )
                self.dmg_type_dropdown.rect = pygame.Rect(
                    edit_x + indent + 170, ey, 130, 24,
                )
                self.dmg_type_dropdown.disabled = False
                self._dice_label_y = ey + 4
                ey += row_h + gap

                # Half damage on success
                self.half_dmg_rect = pygame.Rect(
                    edit_x + indent + 80, ey, 20, 20,
                )
                self._half_label_y = ey + 2
                ey += row_h + gap

            # --- Conditions sub-section ---
            self.cb_conditions.rect = pygame.Rect(
                edit_x + indent, ey, edit_w - indent, cb_h,
            )
            self.cb_conditions.box_rect = pygame.Rect(
                edit_x + indent, ey + (cb_h - 20) // 2, 20, 20,
            )
            ey += cb_h + gap

            if self.cb_conditions.checked:
                self.cond_fail_editor.rect = pygame.Rect(
                    edit_x + indent, ey, edit_w - indent, 76,
                )
                self.cond_fail_editor.update_subrects()
                self._cond_label_y = ey
                ey += 80 + gap

        # --- Heal section ---
        self.cb_heal.rect = pygame.Rect(edit_x, ey, edit_w, cb_h)
        self.cb_heal.box_rect = pygame.Rect(
            edit_x, ey + (cb_h - 20) // 2, 20, 20,
        )
        ey += cb_h + gap

        if self.cb_heal.checked:
            self.heal_rect = pygame.Rect(
                edit_x + indent + 80, ey, 100, row_h,
            )
            self._heal_label_y = ey + 4
            ey += row_h + gap

        # --- Temp HP section ---
        self.cb_temp_hp.rect = pygame.Rect(edit_x, ey, edit_w, cb_h)
        self.cb_temp_hp.box_rect = pygame.Rect(
            edit_x, ey + (cb_h - 20) // 2, 20, 20,
        )
        ey += cb_h + gap

        if self.cb_temp_hp.checked:
            self.temp_hp_rect = pygame.Rect(
                edit_x + indent + 80, ey, 100, row_h,
            )
            self._temp_hp_label_y = ey + 4
            ey += row_h + gap

        # --- Summon section ---
        self.cb_summon.rect = pygame.Rect(edit_x, ey, edit_w, cb_h)
        self.cb_summon.box_rect = pygame.Rect(
            edit_x, ey + (cb_h - 20) // 2, 20, 20,
        )
        ey += cb_h + gap

        if self.cb_summon.checked:
            self.summon_dropdown.rect = pygame.Rect(
                edit_x + indent + 80, ey, edit_w - indent - 80, 24,
            )
            self.summon_dropdown.disabled = False
            self._summon_label_y = ey + 2
            ey += row_h + gap

        # Done button
        self.done_btn = pygame.Rect(
            self.rect.right - 90, self.rect.bottom - 38, 80, 28,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _selected_action(self) -> Action | None:
        if self.selected_index is not None and self.selected_index < len(self.actions):
            return self.actions[self.selected_index]
        return None

    def _sync_form_from_action(self, action: Action) -> None:
        """Set checkbox / dropdown / widget states from the selected action."""
        has_save = action.saving_throw is not None
        has_damage = has_save and bool(
            action.saving_throw.damage_on_fail
        )
        has_conditions = has_save and bool(
            action.saving_throw.conditions_on_fail
        )

        self.cb_save.checked = has_save
        self.cb_damage.checked = has_damage
        self.cb_conditions.checked = has_conditions
        self.cb_heal.checked = bool(action.healing)
        self.cb_temp_hp.checked = bool(action.grants_temporary_hp)
        self.cb_summon.checked = bool(action.summon_creature)

        # Save ability
        if has_save:
            ability = action.saving_throw.ability
            if ability in _SAVE_ABILITIES:
                self.save_dropdown.selected_index = _SAVE_ABILITIES.index(ability)
            # Damage type
            if has_damage:
                dt = action.saving_throw.damage_on_fail[0].damage_type.value
                if dt in _DAMAGE_TYPES:
                    self.dmg_type_dropdown.selected_index = _DAMAGE_TYPES.index(dt)
            # Conditions
            self.cond_fail_editor.items = list(
                action.saving_throw.conditions_on_fail
            )
        else:
            self.cond_fail_editor.items = []

        # Summon dropdown
        if action.summon_creature and action.summon_creature in self._summon_paths:
            self.summon_dropdown.selected_index = self._summon_paths.index(
                action.summon_creature
            )
        else:
            self.summon_dropdown.selected_index = 0

        # Rebuild layout for new checkbox states
        self._build_rects()

    def _sync_action_from_form(self) -> None:
        """Write widget state back to the selected action."""
        action = self._selected_action()
        if action is None:
            return

        # --- Saving throw ---
        if self.cb_save.checked:
            ability = _SAVE_ABILITIES[self.save_dropdown.selected_index]
            dmg_type_val = _DAMAGE_TYPES[self.dmg_type_dropdown.selected_index]

            dice_str = ""
            dc_val = 10
            half_on_success = False

            if action.saving_throw:
                dice_str = (
                    action.saving_throw.damage_on_fail[0].dice
                    if action.saving_throw.damage_on_fail
                    else ""
                )
                dc_val = action.saving_throw.dc or 10
                half_on_success = action.saving_throw.damage_on_success == "half"

            # Damage
            damage_list = []
            if self.cb_damage.checked and dice_str:
                damage_list = [DamageRoll(
                    dice=dice_str,
                    damage_type=DamageType(dmg_type_val),
                )]

            # Conditions
            conditions = (
                list(self.cond_fail_editor.items)
                if self.cb_conditions.checked else []
            )

            action.saving_throw = SavingThrowEffect(
                ability=ability,
                dc=dc_val,
                damage_on_fail=damage_list,
                damage_on_success="half" if half_on_success else "none",
                conditions_on_fail=conditions,
            )
        else:
            action.saving_throw = None

        # --- Healing ---
        if not self.cb_heal.checked:
            action.healing = None

        # --- Temp HP ---
        if not self.cb_temp_hp.checked:
            action.grants_temporary_hp = None

        # --- Summon ---
        if self.cb_summon.checked:
            idx = self.summon_dropdown.selected_index
            path = self._summon_paths[idx] if idx < len(self._summon_paths) else ""
            action.summon_creature = path if path else None
        else:
            action.summon_creature = None

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Process input.  Returns ``"__done__"`` when the user closes."""
        # ListEditor picker has highest priority when open
        if self.cb_conditions.checked and self.cond_fail_editor.is_picker_open:
            if self.cond_fail_editor.handle_event(event):
                self._sync_action_from_form()
                return None
            return None  # Consume all events while picker is open

        # Dropdowns (open state intercepts first)
        for dd in self._open_dropdowns():
            if dd.is_open:
                if dd.handle_event(event):
                    self._sync_action_from_form()
                    return None

        # ListEditor normal events (not picker)
        if self.cb_conditions.checked and self.cb_save.checked:
            if self.cond_fail_editor.handle_event(event):
                self._sync_action_from_form()
                return None

        # Keyboard
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._active_field = None
                return "__done__"
            if self._active_field:
                self._handle_text_input(event)
                return None

        # Mouse click
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._handle_click(event.pos)

        # Checkbox hover tracking (MOUSEMOTION)
        if event.type == pygame.MOUSEMOTION:
            for cb in self._all_checkboxes():
                cb.handle_event(event)

        return None

    def _open_dropdowns(self) -> list[Dropdown]:
        """Return list of dropdowns that are currently relevant."""
        dds = []
        if self.cb_save.checked:
            dds.append(self.save_dropdown)
            if self.cb_damage.checked:
                dds.append(self.dmg_type_dropdown)
        if self.cb_summon.checked:
            dds.append(self.summon_dropdown)
        return dds

    def _all_checkboxes(self) -> list[Checkbox]:
        """All checkboxes in display order."""
        cbs = [self.cb_save]
        if self.cb_save.checked:
            cbs.extend([self.cb_damage, self.cb_conditions])
        cbs.extend([self.cb_heal, self.cb_temp_hp, self.cb_summon])
        return cbs

    def _handle_click(self, pos: tuple[int, int]) -> str | None:
        """Handle a left mouse click."""
        # Done button
        if self.done_btn.collidepoint(pos):
            self._active_field = None
            return "__done__"

        # Add button
        if self.add_btn.collidepoint(pos):
            new_action = Action(
                name=f"Lair Effect {len(self.actions) + 1}",
                description="A lair effect",
                action_type=ActionType.LAIR,
                saving_throw=SavingThrowEffect(
                    ability="dexterity",
                    dc=15,
                    damage_on_fail=[DamageRoll(
                        dice="2d6",
                        damage_type=DamageType.FIRE,
                    )],
                    damage_on_success="half",
                ),
            )
            self.actions.append(new_action)
            self.selected_index = len(self.actions) - 1
            self._sync_form_from_action(new_action)
            return None

        # Remove button
        if self.remove_btn.collidepoint(pos) and self.selected_index is not None:
            if self.selected_index < len(self.actions):
                self.actions.pop(self.selected_index)
                if self.actions:
                    self.selected_index = min(
                        self.selected_index, len(self.actions) - 1,
                    )
                else:
                    self.selected_index = None
                if self.selected_index is not None:
                    self._sync_form_from_action(self.actions[self.selected_index])
            return None

        # List item click
        if self.list_rect.collidepoint(pos):
            rel_y = pos[1] - self.list_rect.y
            idx = rel_y // 28
            if 0 <= idx < len(self.actions):
                self.selected_index = idx
                self._sync_form_from_action(self.actions[idx])
                self._active_field = None
            return None

        # No action selected — nothing else to do
        if self._selected_action() is None:
            self._active_field = None
            return None

        # Checkboxes — toggle and rebuild layout
        for cb in self._all_checkboxes():
            if cb.rect.collidepoint(pos):
                cb.checked = not cb.checked
                self._sync_action_from_form()
                self._build_rects()
                return None

        # Dropdowns (closed state click)
        for dd in self._open_dropdowns():
            if dd.rect.collidepoint(pos):
                if dd.handle_event(
                    pygame.event.Event(
                        pygame.MOUSEBUTTONUP, pos=pos, button=1,
                    )
                ):
                    self._sync_action_from_form()
                    return None

        # Text field clicks
        if self.cb_save.checked:
            if hasattr(self, 'dc_rect') and self.dc_rect.collidepoint(pos):
                self._active_field = "dc"
                return None
            if self.cb_damage.checked:
                if hasattr(self, 'dice_rect') and self.dice_rect.collidepoint(pos):
                    self._active_field = "dice"
                    return None
                # Half damage checkbox
                if hasattr(self, 'half_dmg_rect') and self.half_dmg_rect.collidepoint(pos):
                    action = self._selected_action()
                    if action and action.saving_throw:
                        current = action.saving_throw.damage_on_success
                        action.saving_throw = action.saving_throw.model_copy(
                            update={
                                "damage_on_success": "none" if current == "half" else "half",
                            },
                        )
                    return None

        if self.name_rect.collidepoint(pos):
            self._active_field = "name"
            return None
        if self.desc_rect.collidepoint(pos):
            self._active_field = "description"
            return None
        if self.cb_heal.checked and hasattr(self, 'heal_rect') and self.heal_rect.collidepoint(pos):
            self._active_field = "heal"
            return None
        if self.cb_temp_hp.checked and hasattr(self, 'temp_hp_rect') and self.temp_hp_rect.collidepoint(pos):
            self._active_field = "temp_hp"
            return None

        self._active_field = None
        return None

    def _handle_text_input(self, event: pygame.event.Event) -> None:
        """Handle typing into the active text field."""
        action = self._selected_action()
        if action is None:
            return

        if event.key == pygame.K_RETURN or event.key == pygame.K_TAB:
            self._active_field = None
            return

        if self._active_field == "name":
            if event.key == pygame.K_BACKSPACE:
                action.name = action.name[:-1]
            elif event.unicode and event.unicode.isprintable() and len(action.name) < 30:
                action.name += event.unicode

        elif self._active_field == "description":
            if event.key == pygame.K_BACKSPACE:
                action.description = (action.description or "")[:-1]
            elif event.unicode and event.unicode.isprintable():
                desc = action.description or ""
                if len(desc) < 80:
                    action.description = desc + event.unicode

        elif self._active_field == "dc":
            if action.saving_throw:
                dc_str = str(action.saving_throw.dc or 10)
                if event.key == pygame.K_BACKSPACE:
                    dc_str = dc_str[:-1] or "0"
                elif event.unicode and event.unicode.isdigit() and len(dc_str) < 3:
                    dc_str += event.unicode
                try:
                    new_dc = max(1, min(30, int(dc_str)))
                except ValueError:
                    new_dc = 10
                action.saving_throw = action.saving_throw.model_copy(
                    update={"dc": new_dc},
                )

        elif self._active_field == "dice":
            if action.saving_throw:
                dice_str = ""
                if action.saving_throw.damage_on_fail:
                    dice_str = action.saving_throw.damage_on_fail[0].dice

                if event.key == pygame.K_BACKSPACE:
                    dice_str = dice_str[:-1]
                elif event.unicode and event.unicode.isprintable() and len(dice_str) < 10:
                    dice_str += event.unicode

                if dice_str:
                    dmg_type_val = _DAMAGE_TYPES[self.dmg_type_dropdown.selected_index]
                    new_dr = DamageRoll(
                        dice=dice_str, damage_type=DamageType(dmg_type_val),
                    )
                    action.saving_throw = action.saving_throw.model_copy(
                        update={"damage_on_fail": [new_dr]},
                    )
                else:
                    action.saving_throw = action.saving_throw.model_copy(
                        update={"damage_on_fail": []},
                    )

        elif self._active_field == "heal":
            val = action.healing or ""
            if event.key == pygame.K_BACKSPACE:
                val = val[:-1]
            elif event.unicode and event.unicode.isprintable() and len(val) < 15:
                val += event.unicode
            action.healing = val if val else None

        elif self._active_field == "temp_hp":
            val = action.grants_temporary_hp or ""
            if event.key == pygame.K_BACKSPACE:
                val = val[:-1]
            elif event.unicode and event.unicode.isprintable() and len(val) < 15:
                val += event.unicode
            action.grants_temporary_hp = val if val else None

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        # Dim background
        dim = pygame.Surface(
            (self._screen_width, self._screen_height), pygame.SRCALPHA,
        )
        dim.fill((0, 0, 0, 140))
        surface.blit(dim, (0, 0))

        # Panel background
        bg = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        bg.fill((30, 25, 20, 245))
        surface.blit(bg, self.rect.topleft)

        # Gold border
        gold = parse_color(COLORS["text_gold"])
        pygame.draw.rect(surface, gold, self.rect, 2)

        font = get_font(14)
        font_sm = get_font(12)
        label_color = parse_color(COLORS["text_secondary"])
        white = parse_color(COLORS["text_primary"])

        # Title
        title = get_font(16).render("Lair Actions", True, gold)
        tx = self.rect.x + (self.WIDTH - title.get_width()) // 2
        surface.blit(title, (tx, self.rect.y + 8))

        # ---- List area ----
        pygame.draw.rect(
            surface, parse_color(COLORS["bg_dark"]),
            self.list_rect, border_radius=3,
        )
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            self.list_rect, 1, border_radius=3,
        )

        for i, action in enumerate(self.actions):
            iy = self.list_rect.y + i * 28
            if iy + 28 > self.list_rect.bottom:
                break
            item_rect = pygame.Rect(self.list_rect.x, iy, self.list_rect.width, 28)
            if i == self.selected_index:
                hl = pygame.Surface((item_rect.width, item_rect.height), pygame.SRCALPHA)
                hl.fill((100, 80, 30, 100))
                surface.blit(hl, item_rect.topleft)
            name_surf = font_sm.render(
                action.name[:20], True, white,
            )
            surface.blit(name_surf, (item_rect.x + 6, item_rect.y + 6))

        # Add / Remove buttons
        draw_image_button(surface, self.add_btn, "Add", font_size=12)
        draw_image_button(surface, self.remove_btn, "Remove", font_size=12)

        # ---- Edit area ----
        action = self._selected_action()
        if action is None:
            hint = font.render("Select or add a lair action", True, label_color)
            surface.blit(hint, (self.rect.x + 240, self.rect.y + 100))
        else:
            self._render_edit_area(surface, action)

        # Done button
        draw_image_button(surface, self.done_btn, "Done", font_size=13)

        # Dropdown overlays (must be last for z-order)
        if self.cb_save.checked:
            self.save_dropdown.render_dropdown(surface)
            if self.cb_damage.checked:
                self.dmg_type_dropdown.render_dropdown(surface)
        if self.cb_summon.checked:
            self.summon_dropdown.render_dropdown(surface)

        # ListEditor picker overlay (last for z-order)
        if self.cb_save.checked and self.cb_conditions.checked:
            self.cond_fail_editor.render_overlay(surface)

    def _render_edit_area(self, surface: pygame.Surface, action: Action) -> None:
        """Render all edit fields for the selected action."""
        font = get_font(14)
        font_sm = get_font(12)
        edit_x = self.rect.x + 200
        indent_x = edit_x + 24
        label_color = parse_color(COLORS["text_secondary"])
        white = parse_color(COLORS["text_primary"])
        dim_color = parse_color(COLORS["text_secondary"])
        section_color = parse_color(COLORS["text_gold"])

        # Name
        surface.blit(font.render("Name:", True, label_color),
                     (edit_x, self.name_rect.y + 4))
        self._draw_text_field(surface, self.name_rect, action.name, "name")

        # Description
        surface.blit(font.render("Desc:", True, label_color),
                     (edit_x, self.desc_rect.y + 4))
        self._draw_text_field(
            surface, self.desc_rect, action.description or "", "description",
        )

        # --- Saving throw checkbox ---
        self.cb_save.render(surface)

        if self.cb_save.checked:
            # Save ability
            surface.blit(font.render("Save:", True, label_color),
                         (indent_x, self._save_label_y))
            self.save_dropdown.render(surface)

            # DC
            dc_val = str(action.saving_throw.dc) if action.saving_throw else "10"
            surface.blit(font.render("DC:", True, label_color),
                         (indent_x, self._dc_label_y))
            self._draw_text_field(surface, self.dc_rect, dc_val, "dc")

            # --- Damage sub-section ---
            self.cb_damage.render(surface)

            if self.cb_damage.checked:
                dice_val = ""
                if action.saving_throw and action.saving_throw.damage_on_fail:
                    dice_val = action.saving_throw.damage_on_fail[0].dice
                surface.blit(font.render("Dice:", True, label_color),
                             (indent_x, self._dice_label_y))
                self._draw_text_field(surface, self.dice_rect, dice_val, "dice")
                self.dmg_type_dropdown.render(surface)

                # Half damage on success
                is_half = (
                    action.saving_throw is not None
                    and action.saving_throw.damage_on_success == "half"
                )
                surface.blit(
                    font.render("Half on save:", True, label_color),
                    (indent_x, self._half_label_y),
                )
                cb_color = (
                    parse_color(COLORS["button_active"]) if is_half
                    else parse_color(COLORS["hex_border"])
                )
                pygame.draw.rect(surface, cb_color, self.half_dmg_rect, border_radius=2)
                pygame.draw.rect(
                    surface, parse_color(COLORS["hex_border"]),
                    self.half_dmg_rect, 1, border_radius=2,
                )
                if is_half:
                    pts = [
                        (self.half_dmg_rect.x + 4, self.half_dmg_rect.centery),
                        (self.half_dmg_rect.centerx - 1, self.half_dmg_rect.bottom - 5),
                        (self.half_dmg_rect.right - 4, self.half_dmg_rect.y + 4),
                    ]
                    pygame.draw.lines(surface, white, False, pts, 2)

            # --- Conditions sub-section ---
            self.cb_conditions.render(surface)

            if self.cb_conditions.checked:
                self.cond_fail_editor.render(surface)

        # --- Heal section ---
        self.cb_heal.render(surface)
        if self.cb_heal.checked:
            surface.blit(font.render("Dice:", True, label_color),
                         (indent_x, self._heal_label_y))
            self._draw_text_field(
                surface, self.heal_rect, action.healing or "", "heal",
            )
            surface.blit(
                font_sm.render("(heals enemies)", True, dim_color),
                (self.heal_rect.right + 4, self._heal_label_y + 2),
            )

        # --- Temp HP section ---
        self.cb_temp_hp.render(surface)
        if self.cb_temp_hp.checked:
            surface.blit(font.render("Value:", True, label_color),
                         (indent_x, self._temp_hp_label_y))
            self._draw_text_field(
                surface, self.temp_hp_rect,
                action.grants_temporary_hp or "", "temp_hp",
            )
            surface.blit(
                font_sm.render("(enemies)", True, dim_color),
                (self.temp_hp_rect.right + 4, self._temp_hp_label_y + 2),
            )

        # --- Summon section ---
        self.cb_summon.render(surface)
        if self.cb_summon.checked:
            surface.blit(font.render("Creature:", True, label_color),
                         (indent_x, self._summon_label_y))
            self.summon_dropdown.render(surface)

    def _draw_text_field(
        self, surface: pygame.Surface, rect: pygame.Rect,
        value: str, field_name: str,
    ) -> None:
        """Draw a text input field."""
        is_active = self._active_field == field_name
        bg_color = parse_color(COLORS["bg_dark"])
        border = (
            parse_color(COLORS["button_active"]) if is_active
            else parse_color(COLORS["hex_border"])
        )
        pygame.draw.rect(surface, bg_color, rect, border_radius=3)
        pygame.draw.rect(surface, border, rect, 1, border_radius=3)

        font = get_font(13)
        text_surf = font.render(value, True, parse_color(COLORS["text_primary"]))
        clip = pygame.Rect(0, 0, rect.width - 8, rect.height)
        surface.blit(text_surf, (rect.x + 4, rect.y + 5), clip)

        # Cursor
        if is_active and (pygame.time.get_ticks() // 500) % 2 == 0:
            cx = min(rect.x + 4 + text_surf.get_width(), rect.right - 4)
            pygame.draw.line(
                surface, parse_color(COLORS["text_primary"]),
                (cx, rect.y + 4), (cx, rect.bottom - 4),
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_actions(self) -> list[Action]:
        """Return the edited list of lair actions."""
        return self.actions
