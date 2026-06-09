"""Identity tab for creature builder — name, type, class/race/level or CR/XP."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from arena.gui.renderer import draw_text_centered, get_font
from arena.gui.widgets import TextInput, NumberSpinner, Dropdown
from arena.models.character import CreatureSize, CreatureType
from arena.util.constants import COLORS, parse_color
from arena.util.dnd_data import ALIGNMENTS, RACES, CLASSES, SUBCLASSES, BACKGROUNDS

if TYPE_CHECKING:
    from arena.gui.screens.character_builder import CreatureBuilderScreen, CreatureMode

# CR options for dropdown
CR_OPTIONS = [
    "0", "1/8", "1/4", "1/2",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
    "21", "22", "23", "24", "25", "26", "27", "28", "29", "30",
]
CR_VALUES = {
    "0": 0.0, "1/8": 0.125, "1/4": 0.25, "1/2": 0.5,
    **{str(i): float(i) for i in range(1, 31)},
}
CR_XP = {
    0: 10, 0.125: 25, 0.25: 50, 0.5: 100, 1: 200, 2: 450, 3: 700,
    4: 1100, 5: 1800, 6: 2300, 7: 2900, 8: 3900, 9: 5000, 10: 5900,
    11: 7200, 12: 8400, 13: 10000, 14: 11500, 15: 13000, 16: 15000,
    17: 18000, 18: 20000, 19: 22000, 20: 25000, 21: 33000, 22: 41000,
    23: 50000, 24: 62000, 25: 75000, 26: 90000, 27: 105000, 28: 120000,
    29: 135000, 30: 155000,
}


class IdentityTab:
    """Renders and handles the Identity tab."""

    def __init__(self, screen: CreatureBuilderScreen) -> None:
        self.screen = screen
        ox, oy = screen.get_content_origin()
        w = screen.content_rect.width - 20

        # Creature mode toggle buttons
        btn_w = 100
        btn_h = 28
        btn_gap = 6
        mode_x = ox
        mode_y = oy
        self.mode_buttons: dict[str, pygame.Rect] = {}
        from arena.gui.screens.character_builder import CreatureMode
        for i, mode in enumerate(CreatureMode):
            self.mode_buttons[mode.name] = pygame.Rect(
                mode_x + i * (btn_w + btn_gap), mode_y, btn_w, btn_h,
            )

        # Name input
        self.name_input = TextInput(
            pygame.Rect(ox, oy + 50, w, 28),
            value=screen.form_data["name"],
            max_length=40,
            placeholder="Creature name...",
        )

        # Size dropdown
        size_options = [s.value.title() for s in CreatureSize]
        self.size_dropdown = Dropdown(
            pygame.Rect(ox, oy + 110, 140, 26),
            size_options,
        )
        self._set_dropdown_value(self.size_dropdown, screen.form_data["size"].title())

        # Creature type dropdown
        type_options = [t.value.title() for t in CreatureType]
        self.type_dropdown = Dropdown(
            pygame.Rect(ox + 160, oy + 110, 160, 26),
            type_options,
        )
        self._set_dropdown_value(self.type_dropdown, screen.form_data["creature_type"].title())

        # Alignment dropdown
        alignment_options = [""] + ALIGNMENTS
        self.alignment_dropdown = Dropdown(
            pygame.Rect(ox, oy + 165, w, 26),
            alignment_options,
            max_visible=11,
        )
        stored_alignment = screen.form_data["alignment"]
        if stored_alignment:
            self._set_dropdown_value(
                self.alignment_dropdown, stored_alignment.title(),
            )

        # --- Character-specific ---
        char_y = oy + 220

        # Race dropdown
        race_options = [""] + RACES
        self.race_dropdown = Dropdown(
            pygame.Rect(ox, char_y, w, 26),
            race_options,
            max_visible=10,
        )
        stored_race = screen.form_data["race"]
        if stored_race:
            self._set_dropdown_value(self.race_dropdown, stored_race)

        # Class dropdown
        class_options = [""] + CLASSES
        self.class_dropdown = Dropdown(
            pygame.Rect(ox, char_y + 50, int(w * 0.48), 26),
            class_options,
            max_visible=10,
        )
        stored_class = screen.form_data["character_class"]
        if stored_class:
            self._set_dropdown_value(self.class_dropdown, stored_class)

        # Subclass dropdown — depends on selected class
        current_class = screen.form_data["character_class"]
        if current_class and current_class in SUBCLASSES:
            subclass_options = [""] + SUBCLASSES[current_class]
            subclass_disabled = False
        else:
            subclass_options = [""]
            subclass_disabled = True

        self.subclass_dropdown = Dropdown(
            pygame.Rect(ox + int(w * 0.52), char_y + 50, int(w * 0.48), 26),
            subclass_options,
            max_visible=8,
            disabled=subclass_disabled,
            disabled_text="Select a class first...",
        )
        stored_subclass = screen.form_data["subclass"]
        if stored_subclass:
            self._set_dropdown_value(self.subclass_dropdown, stored_subclass)

        # Track previous class for change detection
        self._prev_class = current_class

        # Level spinner
        self.level_spinner = NumberSpinner(
            pygame.Rect(ox, char_y + 100, 160, 28),
            value=screen.form_data["level"],
            min_val=1, max_val=20,
        )

        # Background dropdown
        background_options = [""] + BACKGROUNDS
        self.background_dropdown = Dropdown(
            pygame.Rect(ox, char_y + 150, w, 26),
            background_options,
            max_visible=10,
        )
        stored_bg = screen.form_data["background"]
        if stored_bg:
            self._set_dropdown_value(self.background_dropdown, stored_bg)

        # --- Monster-specific ---
        mon_y = oy + 220

        cr_val = screen.form_data["challenge_rating"]
        cr_str = self._cr_to_string(cr_val)
        self.cr_dropdown = Dropdown(
            pygame.Rect(ox, mon_y, 160, 26),
            CR_OPTIONS,
        )
        self._set_dropdown_value(self.cr_dropdown, cr_str)

        self.xp_spinner = NumberSpinner(
            pygame.Rect(ox, mon_y + 50, 200, 28),
            value=screen.form_data["experience_points"],
            min_val=0, max_val=999999, step=50,
        )

        self.source_book_input = TextInput(
            pygame.Rect(ox, mon_y + 100, w, 28),
            value=screen.form_data["source_book"],
            placeholder="Source book...",
        )
        self.source_page_spinner = NumberSpinner(
            pygame.Rect(ox, mon_y + 150, 160, 28),
            value=screen.form_data["source_page"],
            min_val=0, max_val=9999,
        )

        # Collect widgets for ESC handling and dropdown management
        self._text_inputs = [
            self.name_input, self.source_book_input,
        ]
        # Shared dropdowns (visible in all modes)
        self._shared_dropdowns = [
            self.size_dropdown, self.type_dropdown,
            self.alignment_dropdown,
        ]
        # Character-mode-only dropdowns (bottom-to-top for overlay z-order)
        self._char_dropdowns = [
            self.background_dropdown,
            self.subclass_dropdown, self.class_dropdown,
            self.race_dropdown,
        ]
        # Monster-mode-only dropdowns
        self._monster_dropdowns = [
            self.cr_dropdown,
        ]

    def _set_dropdown_value(self, dropdown: Dropdown, val: str) -> None:
        try:
            dropdown.selected_index = dropdown.options.index(val)
        except ValueError:
            pass

    def _cr_to_string(self, cr: float) -> str:
        if cr == 0.125:
            return "1/8"
        if cr == 0.25:
            return "1/4"
        if cr == 0.5:
            return "1/2"
        if cr == int(cr):
            return str(int(cr))
        return str(cr)

    def _active_dropdowns(self) -> list[Dropdown]:
        """Return the dropdowns relevant to the current creature mode."""
        from arena.gui.screens.character_builder import CreatureMode
        if self.screen.creature_mode == CreatureMode.CHARACTER:
            return self._shared_dropdowns + self._char_dropdowns
        return self._shared_dropdowns + self._monster_dropdowns

    def _on_class_changed(self) -> None:
        """Update subclass dropdown when the selected class changes."""
        selected_class = self.class_dropdown.value
        if selected_class and selected_class in SUBCLASSES:
            self.subclass_dropdown.options = [""] + SUBCLASSES[selected_class]
            self.subclass_dropdown.disabled = False
        else:
            self.subclass_dropdown.options = [""]
            self.subclass_dropdown.disabled = True
        # Reset subclass selection
        self.subclass_dropdown.selected_index = 0
        self.subclass_dropdown.scroll_offset = 0
        self.subclass_dropdown.is_open = False

    def has_open_dropdown(self) -> bool:
        return any(dd.is_open for dd in self._active_dropdowns())

    def handle_escape(self) -> bool:
        for inp in self._text_inputs:
            if inp.active:
                inp.active = False
                return True
        for dd in self._active_dropdowns():
            if dd.is_open:
                dd.is_open = False
                return True
        return False

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Handle events for this tab. Returns True if consumed."""
        active_dds = self._active_dropdowns()

        # Dropdowns get priority when open
        for dd in active_dds:
            if dd.is_open and dd.handle_event(event):
                self._sync_to_form()
                return True

        # Mode buttons
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            from arena.gui.screens.character_builder import CreatureMode
            for mode_name, rect in self.mode_buttons.items():
                if rect.collidepoint(event.pos):
                    self.screen.creature_mode = CreatureMode[mode_name]
                    # Close any stale dropdowns from the previous mode
                    for dd in self._char_dropdowns + self._monster_dropdowns:
                        dd.is_open = False
                    # Update player controlled default
                    if self.screen.creature_mode == CreatureMode.CHARACTER:
                        self.screen.form_data["is_player_controlled"] = True
                    elif self.screen.creature_mode == CreatureMode.NPC:
                        self.screen.form_data["is_player_controlled"] = True
                    else:
                        self.screen.form_data["is_player_controlled"] = False
                    return True

        # Text inputs
        for inp in self._text_inputs:
            if inp.handle_event(event):
                self._sync_to_form()
                return True

        # Dropdowns (only active mode)
        for dd in active_dds:
            if dd.handle_event(event):
                self._sync_to_form()
                return True

        # Spinners (character)
        from arena.gui.screens.character_builder import CreatureMode
        if self.screen.creature_mode == CreatureMode.CHARACTER:
            if self.level_spinner.handle_event(event):
                self._sync_to_form()
                return True
        else:
            if self.xp_spinner.handle_event(event):
                self._sync_to_form()
                return True
            if self.source_page_spinner.handle_event(event):
                self._sync_to_form()
                return True

        return False

    def _sync_to_form(self) -> None:
        """Write widget values back to form_data."""
        d = self.screen.form_data
        d["name"] = self.name_input.value
        d["size"] = self.size_dropdown.value.lower()
        d["creature_type"] = self.type_dropdown.value.lower()

        # Alignment — stored as lowercase
        alignment_val = self.alignment_dropdown.value
        d["alignment"] = alignment_val.lower() if alignment_val else ""

        # Character fields
        d["race"] = self.race_dropdown.value
        new_class = self.class_dropdown.value
        if new_class != self._prev_class:
            self._prev_class = new_class
            self._on_class_changed()
        d["character_class"] = new_class
        d["subclass"] = self.subclass_dropdown.value
        d["level"] = self.level_spinner.value
        d["background"] = self.background_dropdown.value

        # Monster fields
        cr_str = self.cr_dropdown.value
        d["challenge_rating"] = CR_VALUES.get(cr_str, 1.0)
        # Auto-fill XP from CR
        cr_float = d["challenge_rating"]
        if cr_float in CR_XP:
            self.xp_spinner.value = CR_XP[cr_float]
        d["experience_points"] = self.xp_spinner.value
        d["source_book"] = self.source_book_input.value
        d["source_page"] = self.source_page_spinner.value

    def render(self, surface: pygame.Surface) -> None:
        ox, oy = self.screen.get_content_origin()
        label_color = parse_color(COLORS["text_secondary"])
        font = get_font(14)

        # Mode toggle
        from arena.gui.screens.character_builder import CreatureMode
        for mode in CreatureMode:
            rect = self.mode_buttons[mode.name]
            active = mode == self.screen.creature_mode
            color = (
                parse_color(COLORS["button_active"]) if active
                else parse_color(COLORS["button_normal"])
            )
            pygame.draw.rect(surface, color, rect, border_radius=4)
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                rect, 1, border_radius=4,
            )
            draw_text_centered(
                surface, mode.name.title(), rect.center,
                parse_color(COLORS["text_primary"]), font_size=14,
            )

        # Name
        lbl = font.render("Name:", True, label_color)
        surface.blit(lbl, (ox, oy + 38))
        self.name_input.render(surface)

        # Size + Creature Type
        lbl2 = font.render("Size:", True, label_color)
        surface.blit(lbl2, (ox, oy + 96))
        self.size_dropdown.render(surface)

        lbl3 = font.render("Type:", True, label_color)
        surface.blit(lbl3, (ox + 160, oy + 96))
        self.type_dropdown.render(surface)

        # Alignment
        lbl4 = font.render("Alignment:", True, label_color)
        surface.blit(lbl4, (ox, oy + 150))
        self.alignment_dropdown.render(surface)

        # Separator
        sep_y = oy + 205
        pygame.draw.line(
            surface, parse_color(COLORS["hex_border"]),
            (ox, sep_y), (ox + self.screen.content_rect.width - 20, sep_y),
        )

        if self.screen.creature_mode == CreatureMode.CHARACTER:
            self._render_character_fields(surface, ox, oy, label_color, font)
        else:
            self._render_monster_fields(surface, ox, oy, label_color, font)

    def _render_character_fields(self, surface, ox, oy, label_color, font):
        char_y = oy + 220

        lbl = font.render("Race:", True, label_color)
        surface.blit(lbl, (ox, char_y - 16))
        self.race_dropdown.render(surface)

        lbl2 = font.render("Class:", True, label_color)
        surface.blit(lbl2, (ox, char_y + 34))
        lbl3 = font.render("Subclass:", True, label_color)
        surface.blit(lbl3, (ox + int(self.screen.content_rect.width * 0.52) - 10, char_y + 34))
        self.class_dropdown.render(surface)
        self.subclass_dropdown.render(surface)

        lbl4 = font.render("Level:", True, label_color)
        surface.blit(lbl4, (ox, char_y + 84))
        self.level_spinner.render(surface)

        lbl5 = font.render("Background:", True, label_color)
        surface.blit(lbl5, (ox, char_y + 134))
        self.background_dropdown.render(surface)

    def _render_monster_fields(self, surface, ox, oy, label_color, font):
        mon_y = oy + 220

        lbl = font.render("Challenge Rating:", True, label_color)
        surface.blit(lbl, (ox, mon_y - 16))
        self.cr_dropdown.render(surface)

        lbl2 = font.render("Experience Points:", True, label_color)
        surface.blit(lbl2, (ox, mon_y + 34))
        self.xp_spinner.render(surface)

        lbl3 = font.render("Source Book:", True, label_color)
        surface.blit(lbl3, (ox, mon_y + 84))
        self.source_book_input.render(surface)

        lbl4 = font.render("Source Page:", True, label_color)
        surface.blit(lbl4, (ox, mon_y + 134))
        self.source_page_spinner.render(surface)

    def render_overlays(self, surface: pygame.Surface) -> None:
        """Render open dropdowns on top of other content."""
        for dd in self._active_dropdowns():
            dd.render_dropdown(surface)
