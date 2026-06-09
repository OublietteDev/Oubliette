"""Combat Stats tab — AC, HP, speed, saves, resistances, senses."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from arena.gui.renderer import draw_text_centered, get_font
from arena.gui.widgets import TextInput, NumberSpinner, Checkbox, ListEditor
from arena.util.constants import COLORS, parse_color

if TYPE_CHECKING:
    from arena.gui.screens.character_builder import CreatureBuilderScreen

ABILITIES_SHORT = [
    ("str", "STR"),
    ("dex", "DEX"),
    ("con", "CON"),
    ("int", "INT"),
    ("wis", "WIS"),
    ("cha", "CHA"),
]

DAMAGE_TYPES = [
    "acid", "bludgeoning", "cold", "fire", "force", "lightning",
    "necrotic", "piercing", "poison", "psychic", "radiant",
    "slashing", "thunder",
]

CONDITIONS = [
    "blinded", "charmed", "deafened", "exhaustion", "frightened",
    "grappled", "incapacitated", "invisible", "paralyzed",
    "petrified", "poisoned", "prone", "restrained", "stunned",
    "unconscious",
]

SKILLS = [
    "acrobatics", "animal_handling", "arcana", "athletics",
    "deception", "history", "insight", "intimidation",
    "investigation", "medicine", "nature", "perception",
    "performance", "persuasion", "religion", "sleight_of_hand",
    "stealth", "survival",
]


class CombatTab:
    """Renders and handles the Combat Stats tab."""

    def __init__(self, screen: CreatureBuilderScreen) -> None:
        self.screen = screen
        self._build_widgets()

    def _build_widgets(self) -> None:
        ox, oy = self.screen.get_content_origin()
        w = self.screen.content_rect.width - 20

        # AC, HP, hit dice, proficiency
        self.ac_spinner = NumberSpinner(
            pygame.Rect(ox, oy + 20, 160, 28),
            value=self.screen.form_data["armor_class"],
            min_val=1, max_val=30,
        )
        self.hp_spinner = NumberSpinner(
            pygame.Rect(ox + 200, oy + 20, 180, 28),
            value=self.screen.form_data["max_hit_points"],
            min_val=1, max_val=999,
        )
        self.hit_dice_input = TextInput(
            pygame.Rect(ox + 420, oy + 20, 120, 28),
            value=self.screen.form_data["hit_dice"],
            placeholder="e.g. 8d8",
        )
        self.prof_spinner = NumberSpinner(
            pygame.Rect(ox, oy + 70, 160, 28),
            value=self.screen.form_data["proficiency_bonus"],
            min_val=2, max_val=9,
        )

        # Speed spinners
        speed_y = oy + 120
        speed_names = ["walk", "fly", "swim", "climb", "burrow"]
        self.speed_spinners: dict[str, NumberSpinner] = {}
        for i, name in enumerate(speed_names):
            col = i % 3
            row = i // 3
            sx = ox + col * 180
            sy = speed_y + row * 50
            self.speed_spinners[name] = NumberSpinner(
                pygame.Rect(sx, sy + 18, 150, 26),
                value=self.screen.form_data[f"speed_{name}"],
                min_val=0, max_val=120, step=5,
            )

        # Saving throw checkboxes
        save_y = speed_y + 100 + 20
        self.save_checkboxes: dict[str, Checkbox] = {}
        for i, (key, label) in enumerate(ABILITIES_SHORT):
            col = i % 3
            row = i // 3
            sx = ox + col * 140
            sy = save_y + row * 30
            self.save_checkboxes[key] = Checkbox(
                pygame.Rect(sx, sy, 130, 24),
                label,
                checked=self.screen.form_data[f"save_{key}"],
            )

        # Defense lists
        defense_y = save_y + 80
        list_w = int(w * 0.48)
        self.resist_list = ListEditor(
            pygame.Rect(ox, defense_y + 18, list_w, 100),
            items=list(self.screen.form_data["damage_resistances"]),
            default_value="fire",
            allowed_values=DAMAGE_TYPES,
        )
        self.immune_list = ListEditor(
            pygame.Rect(ox + list_w + 10, defense_y + 18, list_w, 100),
            items=list(self.screen.form_data["damage_immunities"]),
            default_value="poison",
            allowed_values=DAMAGE_TYPES,
        )
        self.vuln_list = ListEditor(
            pygame.Rect(ox, defense_y + 140, list_w, 100),
            items=list(self.screen.form_data["damage_vulnerabilities"]),
            default_value="fire",
            allowed_values=DAMAGE_TYPES,
        )
        self.cond_immune_list = ListEditor(
            pygame.Rect(ox + list_w + 10, defense_y + 140, list_w, 100),
            items=list(self.screen.form_data["condition_immunities"]),
            default_value="poisoned",
            allowed_values=CONDITIONS,
        )

        # Passive perception
        self.pp_spinner = NumberSpinner(
            pygame.Rect(ox, defense_y + 260, 160, 28),
            value=self.screen.form_data["passive_perception"],
            min_val=0, max_val=30,
        )

        # Collect all widgets for event routing
        self._text_inputs = [self.hit_dice_input]
        self._spinners = [
            self.ac_spinner, self.hp_spinner, self.prof_spinner,
            self.pp_spinner,
        ] + list(self.speed_spinners.values())
        self._checkboxes = list(self.save_checkboxes.values())
        self._lists = [
            self.resist_list, self.immune_list,
            self.vuln_list, self.cond_immune_list,
        ]

        # The three damage-type lists are mutually exclusive:
        # a damage type can only appear in one of resistance,
        # immunity, or vulnerability at a time.
        self._damage_lists = [
            self.resist_list, self.immune_list, self.vuln_list,
        ]
        self._sync_damage_exclusions()

    def has_open_dropdown(self) -> bool:
        return any(lst.is_picker_open for lst in self._lists)

    def handle_escape(self) -> bool:
        for inp in self._text_inputs:
            if inp.active:
                inp.active = False
                return True
        return False

    def handle_event(self, event: pygame.event.Event) -> bool:
        # Give open picker dropdowns first priority
        for lst in self._lists:
            if lst.is_picker_open:
                if lst.handle_event(event):
                    self._sync_to_form()
                    return True

        for inp in self._text_inputs:
            if inp.handle_event(event):
                self._sync_to_form()
                return True
        for spinner in self._spinners:
            if spinner.handle_event(event):
                self._sync_to_form()
                return True
        for cb in self._checkboxes:
            if cb.handle_event(event):
                self._sync_to_form()
                return True
        for lst in self._lists:
            if lst.handle_event(event):
                self._sync_to_form()
                return True
        return False

    def _sync_damage_exclusions(self) -> None:
        """Update each damage-type list's excluded_values so that a damage
        type already present in one list cannot be added to the others.

        In D&D 5e a creature's stat block never lists the same damage
        type in more than one of resistance / immunity / vulnerability.
        """
        for lst in self._damage_lists:
            others: set[str] = set()
            for sibling in self._damage_lists:
                if sibling is not lst:
                    others.update(sibling.items)
            lst.excluded_values = others

    def _sync_to_form(self) -> None:
        d = self.screen.form_data
        d["armor_class"] = self.ac_spinner.value
        d["max_hit_points"] = self.hp_spinner.value
        d["hit_dice"] = self.hit_dice_input.value
        d["proficiency_bonus"] = self.prof_spinner.value

        for name, spinner in self.speed_spinners.items():
            d[f"speed_{name}"] = spinner.value

        for key, cb in self.save_checkboxes.items():
            d[f"save_{key}"] = cb.checked

        d["damage_resistances"] = list(self.resist_list.items)
        d["damage_immunities"] = list(self.immune_list.items)
        d["damage_vulnerabilities"] = list(self.vuln_list.items)
        d["condition_immunities"] = list(self.cond_immune_list.items)
        d["passive_perception"] = self.pp_spinner.value

        # Keep cross-list exclusions in sync after every change
        self._sync_damage_exclusions()

    def render(self, surface: pygame.Surface) -> None:
        ox, oy = self.screen.get_content_origin()
        label_color = parse_color(COLORS["text_secondary"])
        font = get_font(14)

        # --- Core combat stats ---
        lbl = font.render("AC:", True, label_color)
        surface.blit(lbl, (ox, oy + 4))
        self.ac_spinner.render(surface)

        lbl2 = font.render("HP:", True, label_color)
        surface.blit(lbl2, (ox + 200, oy + 4))
        self.hp_spinner.render(surface)

        lbl3 = font.render("Hit Dice:", True, label_color)
        surface.blit(lbl3, (ox + 420, oy + 4))
        self.hit_dice_input.render(surface)

        lbl4 = font.render("Proficiency Bonus:", True, label_color)
        surface.blit(lbl4, (ox, oy + 54))
        self.prof_spinner.render(surface)

        # Separator
        sep_y = oy + 105
        pygame.draw.line(
            surface, parse_color(COLORS["hex_border"]),
            (ox, sep_y), (ox + self.screen.content_rect.width - 20, sep_y),
        )

        # --- Speed ---
        speed_y = oy + 120
        speed_header = font.render("Speed (ft):", True, label_color)
        surface.blit(speed_header, (ox, speed_y - 4))

        speed_names = ["walk", "fly", "swim", "climb", "burrow"]
        for i, name in enumerate(speed_names):
            col = i % 3
            row = i // 3
            sx = ox + col * 180
            sy = speed_y + row * 50
            lbl = font.render(name.title() + ":", True, label_color)
            surface.blit(lbl, (sx, sy + 2))
            self.speed_spinners[name].render(surface)

        # Separator
        sep_y2 = speed_y + 100 + 5
        pygame.draw.line(
            surface, parse_color(COLORS["hex_border"]),
            (ox, sep_y2), (ox + self.screen.content_rect.width - 20, sep_y2),
        )

        # --- Saving Throws ---
        save_y = sep_y2 + 15
        save_header = font.render("Saving Throw Proficiencies:", True, label_color)
        surface.blit(save_header, (ox, save_y - 14))
        for cb in self._checkboxes:
            cb.render(surface)

        # Separator
        sep_y3 = save_y + 65
        pygame.draw.line(
            surface, parse_color(COLORS["hex_border"]),
            (ox, sep_y3), (ox + self.screen.content_rect.width - 20, sep_y3),
        )

        # --- Defense lists ---
        defense_y = sep_y3 + 8
        w = self.screen.content_rect.width - 20
        list_w = int(w * 0.48)

        lbl_r = font.render("Damage Resistances:", True, label_color)
        surface.blit(lbl_r, (ox, defense_y))
        self.resist_list.render(surface)

        lbl_i = font.render("Damage Immunities:", True, label_color)
        surface.blit(lbl_i, (ox + list_w + 10, defense_y))
        self.immune_list.render(surface)

        lbl_v = font.render("Damage Vulnerabilities:", True, label_color)
        surface.blit(lbl_v, (ox, defense_y + 122))
        self.vuln_list.render(surface)

        lbl_c = font.render("Condition Immunities:", True, label_color)
        surface.blit(lbl_c, (ox + list_w + 10, defense_y + 122))
        self.cond_immune_list.render(surface)

        # Passive perception
        pp_y = defense_y + 245
        lbl_pp = font.render("Passive Perception:", True, label_color)
        surface.blit(lbl_pp, (ox, pp_y))
        self.pp_spinner.render(surface)

    def render_overlays(self, surface: pygame.Surface) -> None:
        for lst in self._lists:
            lst.render_overlay(surface)
