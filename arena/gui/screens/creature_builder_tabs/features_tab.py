"""Features & Spells tab — features list, class resources, feats, spell slots, spells."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from arena.gui.renderer import draw_text_centered, get_font
from arena.gui.widgets import TextInput, NumberSpinner, Dropdown, ListEditor
from arena.util.constants import COLORS, parse_color
from arena.util.dnd_data import FEATS, FEAT_DATA
from arena.gui.screens.creature_builder_tabs.combat_tab import DAMAGE_TYPES, CONDITIONS

if TYPE_CHECKING:
    from arena.gui.screens.character_builder import CreatureBuilderScreen

ABILITIES_PLUS_NONE = [
    "(none)", "intelligence", "wisdom", "charisma",
    "strength", "dexterity", "constitution",
]

ABILITY_NAMES = [
    "strength", "dexterity", "constitution",
    "intelligence", "wisdom", "charisma",
]

ABILITY_SHORT = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]

UNARMORED_DEFENSE_OPTIONS = ["(none)", "monk", "barbarian"]

SPELL_SLOT_COL_SPACING = 185

# Height of the feature bonus edit section (below name/desc/source)
_FEATURE_BONUS_HEIGHT = 300

# Extra height when rider section is visible (trigger != none)
_RIDER_SECTION_HEIGHT = 200

RIDER_TRIGGER_OPTIONS = ["(none)", "post_hit", "automatic"]

RIDER_RESOURCE_OPTIONS = [
    "(none)", "spell_slot", "ki_points", "superiority_dice",
    "sorcery_points", "rage_charges", "channel_divinity",
]

RIDER_DAMAGE_TYPES = [
    "radiant", "necrotic", "fire", "cold", "lightning", "thunder",
    "psychic", "force", "acid", "poison",
    "bludgeoning", "piercing", "slashing",
]

RIDER_SAVE_ABILITIES = [
    "(none)", "strength", "dexterity", "constitution",
    "intelligence", "wisdom", "charisma",
]

RIDER_CONDITIONS = [
    "(none)", "stunned", "frightened", "blinded", "charmed",
    "paralyzed", "poisoned", "prone", "restrained",
    "incapacitated", "deafened",
]

ABILITY_OPTIONS = [
    "(none)", "strength", "dexterity", "constitution",
    "intelligence", "wisdom", "charisma",
]

DAMAGE_REDUCTION_TYPE_OPTIONS = ["(none)", "melee_only", "ranged_only"]

# Collapsible section IDs for feature primitive fields
FEAT_SECTION_COMBAT = "feat_combat_mechanics"
FEAT_SECTION_DR = "feat_damage_reduction"
FEAT_SECTION_REROLL = "feat_forced_reroll"
FEAT_SECTION_AURA = "feat_aura_effects"
FEAT_SECTION_DEATH = "feat_death_prevention"
FEAT_SECTION_ACTIVE_COND = "feat_active_condition_immunity"

FEAT_SECTION_TITLES = {
    FEAT_SECTION_COMBAT: "Combat Mechanics",
    FEAT_SECTION_DR: "Damage Reduction",
    FEAT_SECTION_REROLL: "Forced Reroll",
    FEAT_SECTION_AURA: "Aura Effects",
    FEAT_SECTION_DEATH: "Death Prevention",
    FEAT_SECTION_ACTIVE_COND: "Active Condition Immunity",
}

FEAT_SECTION_IDS = [
    FEAT_SECTION_COMBAT, FEAT_SECTION_DR, FEAT_SECTION_REROLL,
    FEAT_SECTION_AURA, FEAT_SECTION_DEATH, FEAT_SECTION_ACTIVE_COND,
]


class FeaturesTab:
    """Renders and handles the Features & Spells tab."""

    def __init__(self, screen: CreatureBuilderScreen) -> None:
        self.screen = screen
        self._build_widgets()

    def _build_widgets(self) -> None:
        ox, oy = self.screen.get_content_origin()
        w = self.screen.content_rect.width - 20

        # --- Features / Special Abilities section ---
        self.features_list_rect = pygame.Rect(ox, oy + 20, w, 140)
        self.add_feature_btn = pygame.Rect(ox + w - 60, oy + 20, 56, 22)
        self.add_feature_hovered = False

        # Feature editing fields (shown when a feature is selected)
        edit_y = oy + 170
        half_w = int(w * 0.48)
        self.feat_name_input = TextInput(
            pygame.Rect(ox, edit_y + 16, half_w, 26),
            placeholder="Feature name...",
        )
        self.feat_desc_input = TextInput(
            pygame.Rect(ox + half_w + 10, edit_y + 16, half_w, 26),
            placeholder="Description...",
            max_length=120,
        )
        self.feat_source_input = TextInput(
            pygame.Rect(ox, edit_y + 60, half_w, 26),
            placeholder="Source (e.g. Fighter 1)...",
        )
        self.selected_feature_index: int | None = None
        self.feature_scroll_offset = 0

        # --- Feature bonus editing widgets (shown when a feature is selected) ---
        bonus_y = edit_y + 90
        third_w = int(w * 0.30)
        spinner_w = 80

        self.feat_ac_spinner = NumberSpinner(
            pygame.Rect(ox + 70, bonus_y, spinner_w, 24),
            value=0, min_val=-5, max_val=10,
        )
        self.feat_speed_spinner = NumberSpinner(
            pygame.Rect(ox + third_w + 70, bonus_y, spinner_w, 24),
            value=0, min_val=-30, max_val=60, step=5,
        )
        self.feat_init_spinner = NumberSpinner(
            pygame.Rect(ox + 2 * third_w + 80, bonus_y, spinner_w, 24),
            value=0, min_val=-5, max_val=10,
        )

        # Ability score bonus spinners (6 in two rows of 3)
        self.feat_ability_spinners: dict[str, NumberSpinner] = {}
        ab_spinner_w = 70
        ab_col_w = int(w / 3)
        for idx_ab, ability in enumerate(ABILITY_NAMES):
            col = idx_ab % 3
            row = idx_ab // 3
            ax = ox + col * ab_col_w + 36
            ay = bonus_y + 50 + row * 28
            self.feat_ability_spinners[ability] = NumberSpinner(
                pygame.Rect(ax, ay, ab_spinner_w, 24),
                value=0, min_val=-4, max_val=4,
            )

        # Unarmored defense dropdown
        self.feat_unarmored_dropdown = Dropdown(
            pygame.Rect(ox + 145, bonus_y + 114, 160, 24),
            UNARMORED_DEFENSE_OPTIONS,
        )

        # List editors for grants_* fields
        list_half = int(w * 0.48)
        list_h = 64
        list_y1 = bonus_y + 150
        self.feat_resist_list = ListEditor(
            pygame.Rect(ox, list_y1, list_half, list_h),
            items=[], allowed_values=DAMAGE_TYPES,
        )
        self.feat_immune_list = ListEditor(
            pygame.Rect(ox + list_half + 10, list_y1, list_half, list_h),
            items=[], allowed_values=DAMAGE_TYPES,
        )

        list_y2 = list_y1 + list_h + 20
        self.feat_cond_immune_list = ListEditor(
            pygame.Rect(ox, list_y2, list_half, list_h),
            items=[], allowed_values=CONDITIONS,
        )
        self.feat_save_prof_list = ListEditor(
            pygame.Rect(ox + list_half + 10, list_y2, list_half, list_h),
            items=[], allowed_values=ABILITY_NAMES,
        )

        self._feature_bonus_spinners = [
            self.feat_ac_spinner, self.feat_speed_spinner, self.feat_init_spinner,
        ] + list(self.feat_ability_spinners.values())
        self._feature_bonus_lists = [
            self.feat_resist_list, self.feat_immune_list,
            self.feat_cond_immune_list, self.feat_save_prof_list,
        ]

        # --- On-Hit Rider section (below feature bonuses) ---
        rider_y = list_y2 + list_h + 30  # Below save proficiency list
        self.rider_trigger_dropdown = Dropdown(
            pygame.Rect(ox + 60, rider_y, 140, 24),
            RIDER_TRIGGER_OPTIONS,
        )
        self.rider_once_per_turn_cb = pygame.Rect(ox + 220, rider_y, 140, 24)
        self._rider_once_per_turn = False

        self.rider_resource_dropdown = Dropdown(
            pygame.Rect(ox + 100, rider_y + 30, 140, 24),
            RIDER_RESOURCE_OPTIONS,
        )
        self.rider_cost_spinner = NumberSpinner(
            pygame.Rect(ox + 300, rider_y + 30, 80, 24),
            value=0, min_val=0, max_val=10,
        )

        self.rider_dice_input = TextInput(
            pygame.Rect(ox, rider_y + 60, 100, 24),
            placeholder="e.g. 2d8",
            max_length=10,
        )
        self.rider_damage_type_dropdown = Dropdown(
            pygame.Rect(ox + 110, rider_y + 60, 130, 24),
            RIDER_DAMAGE_TYPES,
        )
        self.rider_scale_input = TextInput(
            pygame.Rect(ox + 260, rider_y + 60, 80, 24),
            placeholder="e.g. 1d8",
            max_length=10,
        )
        self.rider_max_dice_spinner = NumberSpinner(
            pygame.Rect(ox + 410, rider_y + 60, 80, 24),
            value=0, min_val=0, max_val=20,
        )

        self.rider_save_dropdown = Dropdown(
            pygame.Rect(ox + 50, rider_y + 90, 130, 24),
            RIDER_SAVE_ABILITIES,
        )
        self.rider_dc_ability_dropdown = Dropdown(
            pygame.Rect(ox + 240, rider_y + 90, 130, 24),
            RIDER_SAVE_ABILITIES,
        )
        self.rider_condition_dropdown = Dropdown(
            pygame.Rect(ox + 100, rider_y + 120, 140, 24),
            RIDER_CONDITIONS,
        )

        self.rider_melee_cb_rect = pygame.Rect(ox, rider_y + 155, 150, 24)
        self._rider_requires_melee = False
        self.rider_weapon_cb_rect = pygame.Rect(ox + 170, rider_y + 155, 160, 24)
        self._rider_requires_weapon = False

        self._rider_spinners = [self.rider_cost_spinner, self.rider_max_dice_spinner]
        self._rider_text_inputs = [self.rider_dice_input, self.rider_scale_input]
        self._rider_dropdowns = [
            self.rider_trigger_dropdown, self.rider_resource_dropdown,
            self.rider_damage_type_dropdown, self.rider_save_dropdown,
            self.rider_dc_ability_dropdown, self.rider_condition_dropdown,
        ]

        # --- Collapsible primitive sections ---
        self._feat_section_expanded: dict[str, bool] = {sid: False for sid in FEAT_SECTION_IDS}
        self._feat_section_header_rects: dict[str, pygame.Rect] = {}

        # Section 1: Combat Mechanics
        self._cb_has_evasion = False
        self._sp_extra_attack = NumberSpinner(
            pygame.Rect(0, 0, 80, 24), value=0, min_val=0, max_val=3,
        )
        self._sp_crit_range = NumberSpinner(
            pygame.Rect(0, 0, 80, 24), value=0, min_val=0, max_val=4,
        )
        self._sp_bonus_crit_dice = NumberSpinner(
            pygame.Rect(0, 0, 80, 24), value=0, min_val=0, max_val=4,
        )
        self._cb_has_evasion_rect = pygame.Rect(0, 0, 200, 24)

        # Section 2: Damage Reduction
        self._inp_dr_dice = TextInput(
            pygame.Rect(0, 0, 100, 24), placeholder="e.g. 1d8", max_length=10,
        )
        self._dd_dr_ability = Dropdown(
            pygame.Rect(0, 0, 140, 24), ABILITY_OPTIONS,
        )
        self._cb_dr_flat_half = False
        self._cb_dr_flat_half_rect = pygame.Rect(0, 0, 240, 24)
        self._dd_dr_type = Dropdown(
            pygame.Rect(0, 0, 140, 24), DAMAGE_REDUCTION_TYPE_OPTIONS,
        )

        # Section 3: Forced Reroll
        self._cb_reroll_saves = False
        self._cb_reroll_saves_rect = pygame.Rect(0, 0, 200, 24)
        self._inp_reroll_resource = TextInput(
            pygame.Rect(0, 0, 200, 24), placeholder="e.g. indomitable_uses", max_length=30,
        )
        self._sp_reroll_cost = NumberSpinner(
            pygame.Rect(0, 0, 80, 24), value=1, min_val=0, max_val=5,
        )

        # Section 4: Aura Effects
        self._sp_aura_range = NumberSpinner(
            pygame.Rect(0, 0, 80, 24), value=0, min_val=0, max_val=60, step=5,
        )
        self._dd_aura_save_ability = Dropdown(
            pygame.Rect(0, 0, 140, 24), ABILITY_OPTIONS,
        )
        self._inp_aura_cond_immune = TextInput(
            pygame.Rect(0, 0, 300, 24), placeholder="e.g. frightened, charmed", max_length=80,
        )

        # Section 5: Death Prevention
        self._cb_death_prevention = False
        self._cb_death_prevention_rect = pygame.Rect(0, 0, 200, 24)
        self._dd_death_save_ability = Dropdown(
            pygame.Rect(0, 0, 140, 24), ABILITY_OPTIONS,
        )
        self._sp_death_save_dc = NumberSpinner(
            pygame.Rect(0, 0, 80, 24), value=10, min_val=1, max_val=30,
        )
        self._sp_death_dc_increment = NumberSpinner(
            pygame.Rect(0, 0, 80, 24), value=0, min_val=0, max_val=10,
        )
        self._inp_death_resource = TextInput(
            pygame.Rect(0, 0, 200, 24), placeholder="e.g. relentless_endurance", max_length=30,
        )

        # Section 6: Active Condition Immunity
        self._inp_active_cond = TextInput(
            pygame.Rect(0, 0, 300, 24), placeholder="e.g. charmed, frightened", max_length=80,
        )
        self._inp_active_cond_resource = TextInput(
            pygame.Rect(0, 0, 200, 24), placeholder="e.g. rage_uses", max_length=30,
        )

        # Collect all section widgets for event routing
        self._section_spinners = [
            self._sp_extra_attack, self._sp_crit_range, self._sp_bonus_crit_dice,
            self._sp_aura_range, self._sp_death_save_dc, self._sp_death_dc_increment,
            self._sp_reroll_cost,
        ]
        self._section_text_inputs = [
            self._inp_dr_dice, self._inp_reroll_resource,
            self._inp_aura_cond_immune, self._inp_death_resource,
            self._inp_active_cond, self._inp_active_cond_resource,
        ]
        self._section_dropdowns = [
            self._dd_dr_ability, self._dd_dr_type,
            self._dd_aura_save_ability, self._dd_death_save_ability,
        ]

        # --- Class Resources section (Character only) ---
        self._resource_section_y = oy + 280
        self.resource_name_inputs: list[TextInput] = []
        self.resource_value_spinners: list[NumberSpinner] = []
        self.add_resource_btn = pygame.Rect(ox + w - 80, self._resource_section_y, 76, 22)
        self.add_resource_hovered = False
        self._rebuild_resource_widgets()

        # --- Feats section (Character only) ---
        self.feats_data: list[dict] = list(self.screen.form_data.get("feats", []))
        self.selected_feat_index: int | None = None
        self.feat_dropdown = Dropdown(
            pygame.Rect(0, 0, 200, 26),  # Repositioned dynamically
            ["(select feat)"] + FEATS,
        )
        self.add_feat_btn = pygame.Rect(0, 0, 76, 22)  # Repositioned dynamically
        self.add_feat_hovered = False
        self.feat_desc_edit = TextInput(
            pygame.Rect(0, 0, half_w, 26),  # Repositioned dynamically
            placeholder="Description...",
            max_length=200,
        )

        # --- Spellcasting section (Character only) ---
        spell_y = oy + 280  # Will be offset dynamically
        self.spell_ability_dropdown = Dropdown(
            pygame.Rect(ox, spell_y + 18, 200, 26),
            ABILITIES_PLUS_NONE,
        )
        sc_ability = self.screen.form_data.get("spellcasting_ability", "")
        try:
            idx = ABILITIES_PLUS_NONE.index(sc_ability)
        except ValueError:
            idx = 0
        self.spell_ability_dropdown.selected_index = idx

        # Spell slots (levels 1-9)
        self.slot_spinners: dict[int, NumberSpinner] = {}
        slots = self.screen.form_data.get("spell_slots", {})
        slot_y = spell_y + 60
        for lvl in range(1, 10):
            col = (lvl - 1) % 5
            row = (lvl - 1) // 5
            sx = ox + col * SPELL_SLOT_COL_SPACING
            sy = slot_y + row * 50
            self.slot_spinners[lvl] = NumberSpinner(
                pygame.Rect(sx, sy + 18, 80, 24),
                value=slots.get(lvl, slots.get(str(lvl), 0)),
                min_val=0, max_val=9,
            )

        # Spells known/prepared
        list_y = slot_y + 120
        self.spells_known_list = ListEditor(
            pygame.Rect(ox, list_y + 18, int(w * 0.48), 100),
            items=list(self.screen.form_data.get("spells_known", [])),
            default_value="spell_name",
        )
        self.spells_prepared_list = ListEditor(
            pygame.Rect(ox + int(w * 0.52), list_y + 18, int(w * 0.48), 100),
            items=list(self.screen.form_data.get("spells_prepared", [])),
            default_value="spell_name",
        )

        # Monster: legendary action count
        self.legend_count_spinner = NumberSpinner(
            pygame.Rect(ox, oy + 280, 160, 28),
            value=self.screen.form_data.get("legendary_action_count", 0),
            min_val=0, max_val=5,
        )

        self._text_inputs = [
            self.feat_name_input, self.feat_desc_input, self.feat_source_input,
        ]
        self._dropdowns = [
            self.spell_ability_dropdown, self.feat_dropdown,
            self.feat_unarmored_dropdown,
        ] + self._rider_dropdowns + self._section_dropdowns

    def _get_feature_edit_height(self) -> int:
        """Height of the feature edit section (0 if no feature selected)."""
        if self.selected_feature_index is None:
            return 0
        # Name/desc row + source row + bonus widgets
        h = 90 + _FEATURE_BONUS_HEIGHT
        # Add rider section height if trigger is active
        if self.rider_trigger_dropdown.selected_index > 0:
            h += _RIDER_SECTION_HEIGHT
        else:
            h += 30  # Just the trigger dropdown row

        # Collapsible primitive sections (header height always, content when expanded)
        for sid in FEAT_SECTION_IDS:
            h += 30  # header bar
            if self._feat_section_expanded.get(sid, False):
                h += self._get_section_content_height(sid)
        return h

    def _get_section_content_height(self, section_id: str) -> int:
        """Return the pixel height of the content area for a given section."""
        if section_id == FEAT_SECTION_COMBAT:
            return 90   # checkbox + 3 spinners (2 rows)
        elif section_id == FEAT_SECTION_DR:
            return 90   # dice input + ability dropdown + checkbox + type dropdown (2 rows)
        elif section_id == FEAT_SECTION_REROLL:
            return 60   # checkbox + resource input + cost spinner
        elif section_id == FEAT_SECTION_AURA:
            return 90   # range spinner + ability dropdown + condition text
        elif section_id == FEAT_SECTION_DEATH:
            return 150  # checkbox + ability + dc + increment + resource (5 rows)
        elif section_id == FEAT_SECTION_ACTIVE_COND:
            return 60   # condition text + resource text
        return 0

    def _reposition_section_widgets(
        self, section_id: str, ix: int, cy: int, sw: int,
    ) -> None:
        """Reposition the widgets within a given collapsible section.

        Args:
            ix: indented x position
            cy: current y position (top of section content)
            sw: section width
        """
        half = int(sw * 0.48)

        if section_id == FEAT_SECTION_COMBAT:
            self._cb_has_evasion_rect = pygame.Rect(ix, cy, 200, 24)
            self._sp_extra_attack.rect = pygame.Rect(ix + 120, cy + 28, 80, 24)
            self._sp_extra_attack.update_subrects()
            self._sp_crit_range.rect = pygame.Rect(ix + 180, cy + 56, 80, 24)
            self._sp_crit_range.update_subrects()
            self._sp_bonus_crit_dice.rect = pygame.Rect(ix + 350, cy + 56, 80, 24)
            self._sp_bonus_crit_dice.update_subrects()

        elif section_id == FEAT_SECTION_DR:
            self._inp_dr_dice.rect = pygame.Rect(ix + 50, cy, 100, 24)
            self._dd_dr_ability.rect = pygame.Rect(ix + 220, cy, 140, 24)
            self._cb_dr_flat_half_rect = pygame.Rect(ix, cy + 30, 240, 24)
            self._dd_dr_type.rect = pygame.Rect(ix + 60, cy + 60, 140, 24)

        elif section_id == FEAT_SECTION_REROLL:
            self._cb_reroll_saves_rect = pygame.Rect(ix, cy, 200, 24)
            self._inp_reroll_resource.rect = pygame.Rect(ix + 80, cy + 28, 200, 24)
            self._sp_reroll_cost.rect = pygame.Rect(ix + 340, cy + 28, 80, 24)
            self._sp_reroll_cost.update_subrects()

        elif section_id == FEAT_SECTION_AURA:
            self._sp_aura_range.rect = pygame.Rect(ix + 120, cy, 80, 24)
            self._sp_aura_range.update_subrects()
            self._dd_aura_save_ability.rect = pygame.Rect(ix + 140, cy + 30, 140, 24)
            self._inp_aura_cond_immune.rect = pygame.Rect(ix + 170, cy + 60, 300, 24)

        elif section_id == FEAT_SECTION_DEATH:
            self._cb_death_prevention_rect = pygame.Rect(ix, cy, 200, 24)
            self._dd_death_save_ability.rect = pygame.Rect(ix + 110, cy + 30, 140, 24)
            self._sp_death_save_dc.rect = pygame.Rect(ix + 80, cy + 60, 80, 24)
            self._sp_death_save_dc.update_subrects()
            self._sp_death_dc_increment.rect = pygame.Rect(ix + 270, cy + 60, 80, 24)
            self._sp_death_dc_increment.update_subrects()
            self._inp_death_resource.rect = pygame.Rect(ix + 80, cy + 90, 200, 24)

        elif section_id == FEAT_SECTION_ACTIVE_COND:
            self._inp_active_cond.rect = pygame.Rect(ix + 100, cy, 300, 24)
            self._inp_active_cond_resource.rect = pygame.Rect(ix + 130, cy + 30, 200, 24)

    def _is_feat_section_active(self, section_id: str, feature: dict) -> bool:
        """Return True if the section has non-default values in the feature."""
        if section_id == FEAT_SECTION_COMBAT:
            return (
                feature.get("has_evasion", False)
                or (feature.get("extra_attack_count", 0) or 0) > 0
                or (feature.get("crit_range_reduction", 0) or 0) > 0
                or (feature.get("bonus_crit_dice", 0) or 0) > 0
            )
        elif section_id == FEAT_SECTION_DR:
            return (
                bool(feature.get("damage_reduction_dice"))
                or bool(feature.get("damage_reduction_bonus"))
                or feature.get("damage_reduction_flat_half", False)
                or bool(feature.get("damage_reduction_type"))
            )
        elif section_id == FEAT_SECTION_REROLL:
            return feature.get("forced_reroll_saves", False)
        elif section_id == FEAT_SECTION_AURA:
            return (feature.get("aura_range", 0) or 0) > 0
        elif section_id == FEAT_SECTION_DEATH:
            return feature.get("death_prevention", False)
        elif section_id == FEAT_SECTION_ACTIVE_COND:
            return bool(feature.get("active_condition_immunities"))
        return False

    def _render_feat_section_header(
        self, surface: pygame.Surface, section_id: str, feature: dict,
    ) -> None:
        """Draw a collapsible section header bar with triangle + title + dot."""
        rect = self._feat_section_header_rects.get(section_id)
        if rect is None:
            return

        font = get_font(13)
        expanded = self._feat_section_expanded.get(section_id, False)
        active = self._is_feat_section_active(section_id, feature)
        title = FEAT_SECTION_TITLES.get(section_id, section_id)

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
            pts = [(tri_x, tri_cy - 4), (tri_x + 8, tri_cy - 4), (tri_x + 4, tri_cy + 4)]
        else:
            pts = [(tri_x, tri_cy - 5), (tri_x, tri_cy + 5), (tri_x + 7, tri_cy)]
        pygame.draw.polygon(surface, tri_color, pts)

        # Title text
        text_color = parse_color(COLORS["text_primary"])
        title_surf = font.render(title, True, text_color)
        surface.blit(title_surf, (rect.x + 24, rect.y + 4))

        # Active indicator dot
        if active:
            dot_x = rect.right - 16
            dot_y = rect.centery
            pygame.draw.circle(surface, tri_color, (dot_x, dot_y), 5)

    def _reposition_widgets(self) -> None:
        """Reposition all widgets based on current scroll offset."""
        ox, oy = self.screen.get_content_origin()
        scroll_y = self.screen.get_scroll_y()
        oy -= scroll_y

        w = self.screen.content_rect.width - 20
        half_w = int(w * 0.48)

        # --- Features section ---
        self.features_list_rect = pygame.Rect(ox, oy + 20, w, 140)
        self.add_feature_btn = pygame.Rect(ox + w - 60, oy + 20, 56, 22)

        edit_y = oy + 170
        self.feat_name_input.rect = pygame.Rect(ox, edit_y + 16, half_w, 26)
        self.feat_desc_input.rect = pygame.Rect(ox + half_w + 10, edit_y + 16, half_w, 26)
        self.feat_source_input.rect = pygame.Rect(ox, edit_y + 60, half_w, 26)

        # --- Feature bonus widgets ---
        bonus_y = edit_y + 90
        third_w = int(w * 0.30)
        spinner_w = 80

        self.feat_ac_spinner.rect = pygame.Rect(ox + 70, bonus_y, spinner_w, 24)
        self.feat_ac_spinner.update_subrects()
        self.feat_speed_spinner.rect = pygame.Rect(ox + third_w + 70, bonus_y, spinner_w, 24)
        self.feat_speed_spinner.update_subrects()
        self.feat_init_spinner.rect = pygame.Rect(ox + 2 * third_w + 80, bonus_y, spinner_w, 24)
        self.feat_init_spinner.update_subrects()

        ab_spinner_w = 70
        ab_col_w = int(w / 3)
        for idx_ab, ability in enumerate(ABILITY_NAMES):
            col = idx_ab % 3
            row = idx_ab // 3
            ax = ox + col * ab_col_w + 36
            ay = bonus_y + 50 + row * 28
            self.feat_ability_spinners[ability].rect = pygame.Rect(ax, ay, ab_spinner_w, 24)
            self.feat_ability_spinners[ability].update_subrects()

        self.feat_unarmored_dropdown.rect = pygame.Rect(ox + 145, bonus_y + 114, 160, 24)

        list_half = int(w * 0.48)
        list_h = 64
        list_y1 = bonus_y + 150
        self.feat_resist_list.rect = pygame.Rect(ox, list_y1, list_half, list_h)
        self.feat_resist_list.update_subrects()
        self.feat_immune_list.rect = pygame.Rect(ox + list_half + 10, list_y1, list_half, list_h)
        self.feat_immune_list.update_subrects()

        list_y2 = list_y1 + list_h + 20
        self.feat_cond_immune_list.rect = pygame.Rect(ox, list_y2, list_half, list_h)
        self.feat_cond_immune_list.update_subrects()
        self.feat_save_prof_list.rect = pygame.Rect(ox + list_half + 10, list_y2, list_half, list_h)
        self.feat_save_prof_list.update_subrects()

        # --- On-Hit Rider section ---
        rider_y = list_y2 + list_h + 30
        self.rider_trigger_dropdown.rect = pygame.Rect(ox + 60, rider_y, 140, 24)
        self.rider_once_per_turn_cb = pygame.Rect(ox + 220, rider_y, 140, 24)

        self.rider_resource_dropdown.rect = pygame.Rect(ox + 100, rider_y + 30, 140, 24)
        self.rider_cost_spinner.rect = pygame.Rect(ox + 300, rider_y + 30, 80, 24)
        self.rider_cost_spinner.update_subrects()

        self.rider_dice_input.rect = pygame.Rect(ox, rider_y + 60, 100, 24)
        self.rider_damage_type_dropdown.rect = pygame.Rect(ox + 110, rider_y + 60, 130, 24)
        self.rider_scale_input.rect = pygame.Rect(ox + 260, rider_y + 60, 80, 24)
        self.rider_max_dice_spinner.rect = pygame.Rect(ox + 410, rider_y + 60, 80, 24)
        self.rider_max_dice_spinner.update_subrects()

        self.rider_save_dropdown.rect = pygame.Rect(ox + 50, rider_y + 90, 130, 24)
        self.rider_dc_ability_dropdown.rect = pygame.Rect(ox + 240, rider_y + 90, 130, 24)
        self.rider_condition_dropdown.rect = pygame.Rect(ox + 100, rider_y + 120, 140, 24)

        self.rider_melee_cb_rect = pygame.Rect(ox, rider_y + 155, 150, 24)
        self.rider_weapon_cb_rect = pygame.Rect(ox + 170, rider_y + 155, 160, 24)

        # --- Collapsible primitive sections (repositioned dynamically) ---
        # Compute start y after rider section
        if self.rider_trigger_dropdown.selected_index > 0:
            sections_start_y = rider_y + _RIDER_SECTION_HEIGHT
        else:
            sections_start_y = rider_y + 30

        self._feat_section_header_rects = {}
        cy = sections_start_y
        indent = ox + 10

        for sid in FEAT_SECTION_IDS:
            self._feat_section_header_rects[sid] = pygame.Rect(ox, cy, w, 26)
            cy += 30
            if self._feat_section_expanded.get(sid, False):
                # Reposition widgets for this section
                self._reposition_section_widgets(sid, indent, cy, w - 20)
                cy += self._get_section_content_height(sid)

        # --- Class Resources section (dynamic y based on feature edit) ---
        feature_edit_h = self._get_feature_edit_height()
        self._resource_section_y = oy + 170 + feature_edit_h + 15
        self.add_resource_btn = pygame.Rect(ox + w - 80, self._resource_section_y, 76, 22)
        entry_y = self._resource_section_y + 24
        for i in range(len(self.resource_name_inputs)):
            self.resource_name_inputs[i].rect = pygame.Rect(
                ox, entry_y, int(w * 0.5), 26,
            )
            self.resource_value_spinners[i].rect = pygame.Rect(
                ox + int(w * 0.52), entry_y, 100, 26,
            )
            self.resource_value_spinners[i].update_subrects()
            entry_y += 32

        # --- Feats section ---
        feats_y = self._get_feats_render_y()
        self.add_feat_btn = pygame.Rect(ox + w - 76, feats_y, 76, 22)
        self.feat_dropdown.rect = pygame.Rect(ox, feats_y + 24, 200, 26)

        # --- Spellcasting section ---
        base_y = feats_y + self._get_feats_section_height()
        self.spell_ability_dropdown.rect = pygame.Rect(ox, base_y + 18, 200, 26)

        slot_y = base_y + 60
        for lvl in range(1, 10):
            col = (lvl - 1) % 5
            row = (lvl - 1) // 5
            sx = ox + col * SPELL_SLOT_COL_SPACING
            sy = slot_y + row * 50
            self.slot_spinners[lvl].rect = pygame.Rect(sx, sy + 18, 80, 24)
            self.slot_spinners[lvl].update_subrects()

        list_y = slot_y + 120
        self.spells_known_list.rect = pygame.Rect(ox, list_y + 18, half_w, 100)
        self.spells_known_list.update_subrects()
        self.spells_prepared_list.rect = pygame.Rect(
            ox + int(w * 0.52), list_y + 18, half_w, 100,
        )
        self.spells_prepared_list.update_subrects()

        # --- Monster legendary ---
        self.legend_count_spinner.rect = pygame.Rect(
            ox, self._resource_section_y, 160, 28,
        )
        self.legend_count_spinner.update_subrects()

    def _rebuild_resource_widgets(self) -> None:
        """Rebuild resource name/value widgets from form_data.

        Spell-slot resources (``spell_slot_1``, ``spell_slot_2``, etc.)
        are managed by the Spell Slots spinners and are hidden here to
        avoid duplicate UI entries.
        """
        ox, _ = self.screen.get_content_origin()
        w = self.screen.content_rect.width - 20
        resources = self.screen.form_data.get("class_resources", {})

        self.resource_name_inputs = []
        self.resource_value_spinners = []

        y = self._resource_section_y + 24
        for name, value in resources.items():
            # Skip spell-slot keys — they are driven by the slot spinners
            if name.startswith("spell_slot_"):
                continue
            name_input = TextInput(
                pygame.Rect(ox, y, int(w * 0.5), 26),
                placeholder="Resource name...",
            )
            name_input.value = name

            value_spinner = NumberSpinner(
                pygame.Rect(ox + int(w * 0.52), y, 100, 26),
                value=value,
                min_val=0, max_val=99,
            )

            self.resource_name_inputs.append(name_input)
            self.resource_value_spinners.append(value_spinner)
            y += 32

        self.add_resource_btn = pygame.Rect(
            ox + w - 80, self._resource_section_y, 76, 22,
        )

    def _get_resource_section_height(self) -> int:
        """Height of the class resources section (header + entries + spacing)."""
        n = len(self.resource_name_inputs)
        return 30 + n * 32 + 8

    def _get_feats_section_height(self) -> int:
        """Height of the feats section."""
        n = len(self.feats_data)
        base = 30 + n * 28 + 8  # header + list + spacing
        if self.selected_feat_index is not None:
            base += 30  # description field
        return base

    def _get_dynamic_offset(self) -> int:
        """Compute total y offset from class resources + feats sections."""
        offset = self._get_resource_section_height()
        offset += self._get_feats_section_height()
        return offset

    def _get_features(self) -> list[dict]:
        """Get the appropriate features list based on creature mode."""
        from arena.gui.screens.character_builder import CreatureMode
        if self.screen.creature_mode == CreatureMode.CHARACTER:
            return self.screen.features_data
        return self.screen.special_abilities_data

    def has_open_dropdown(self) -> bool:
        if (self.spell_ability_dropdown.is_open
                or self.feat_dropdown.is_open
                or self.feat_unarmored_dropdown.is_open):
            return True
        for dd in self._section_dropdowns:
            if dd.is_open:
                return True
        return False

    def handle_escape(self) -> bool:
        for inp in self._text_inputs:
            if inp.active:
                inp.active = False
                return True
        for dd in self._dropdowns:
            if dd.is_open:
                dd.is_open = False
                return True
        return False

    def handle_event(self, event: pygame.event.Event) -> bool:
        self._reposition_widgets()

        # Dropdowns first (when open)
        for dd in self._dropdowns:
            if dd.is_open:
                if dd.handle_event(event):
                    if dd is self.feat_unarmored_dropdown:
                        self._sync_feature_edit()
                    else:
                        self._sync_to_form()
                    return True

        # Feature bonus list editor pickers (when open)
        if self.selected_feature_index is not None:
            for le in self._feature_bonus_lists:
                if le.is_picker_open:
                    if le.handle_event(event):
                        self._sync_feature_edit()
                        return True

        # Feature text inputs
        for inp in self._text_inputs:
            if inp.handle_event(event):
                self._sync_feature_edit()
                return True

        # Feature bonus spinners
        if self.selected_feature_index is not None:
            for spinner in self._feature_bonus_spinners:
                if spinner.handle_event(event):
                    self._sync_feature_edit()
                    return True
            # Feature bonus list editors
            for le in self._feature_bonus_lists:
                if le.handle_event(event):
                    self._sync_feature_edit()
                    return True
            # Rider spinners + text inputs
            for spinner in self._rider_spinners:
                if spinner.handle_event(event):
                    self._sync_feature_edit()
                    return True
            for inp in self._rider_text_inputs:
                if inp.handle_event(event):
                    self._sync_feature_edit()
                    return True
            # Rider checkbox clicks
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                pos = event.pos
                if self.rider_once_per_turn_cb.collidepoint(pos):
                    self._rider_once_per_turn = not self._rider_once_per_turn
                    self._sync_feature_edit()
                    return True
                if self.rider_melee_cb_rect.collidepoint(pos):
                    self._rider_requires_melee = not self._rider_requires_melee
                    self._sync_feature_edit()
                    return True
                if self.rider_weapon_cb_rect.collidepoint(pos):
                    self._rider_requires_weapon = not self._rider_requires_weapon
                    self._sync_feature_edit()
                    return True

                # Collapsible section header clicks
                for sid, rect in self._feat_section_header_rects.items():
                    if rect.collidepoint(pos):
                        self._feat_section_expanded[sid] = (
                            not self._feat_section_expanded[sid]
                        )
                        self._reposition_widgets()
                        return True

                # Collapsible section checkbox clicks
                if self._cb_has_evasion_rect.collidepoint(pos):
                    self._cb_has_evasion = not self._cb_has_evasion
                    self._sync_feature_edit()
                    return True
                if self._cb_dr_flat_half_rect.collidepoint(pos):
                    self._cb_dr_flat_half = not self._cb_dr_flat_half
                    self._sync_feature_edit()
                    return True
                if self._cb_reroll_saves_rect.collidepoint(pos):
                    self._cb_reroll_saves = not self._cb_reroll_saves
                    self._sync_feature_edit()
                    return True
                if self._cb_death_prevention_rect.collidepoint(pos):
                    self._cb_death_prevention = not self._cb_death_prevention
                    self._sync_feature_edit()
                    return True

            # Collapsible section spinners
            for spinner in self._section_spinners:
                if spinner.handle_event(event):
                    self._sync_feature_edit()
                    return True
            # Collapsible section text inputs
            for inp in self._section_text_inputs:
                if inp.handle_event(event):
                    self._sync_feature_edit()
                    return True

        # Resource text inputs
        for i, inp in enumerate(self.resource_name_inputs):
            if inp.handle_event(event):
                self._sync_resources()
                return True

        # Resource value spinners
        for spinner in self.resource_value_spinners:
            if spinner.handle_event(event):
                self._sync_resources()
                return True

        # Feat description edit
        if self.feat_desc_edit.handle_event(event):
            self._sync_feat_edit()
            return True

        # Click handling
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            pos = event.pos

            # Add Feature button
            if self.add_feature_btn.collidepoint(pos):
                features = self._get_features()
                features.append({"name": "", "description": "", "source": ""})
                self.selected_feature_index = len(features) - 1
                self._load_feature_edit()
                return True

            # Click on feature in list
            features = self._get_features()
            for i in range(len(features)):
                item_y = (
                    self.features_list_rect.y + 26
                    + i * 30 - self.feature_scroll_offset
                )
                item_rect = pygame.Rect(
                    self.features_list_rect.x, item_y,
                    self.features_list_rect.width - 30, 28,
                )
                if item_rect.collidepoint(pos):
                    # Check remove button
                    rm_rect = pygame.Rect(
                        item_rect.right + 2, item_y + 4, 20, 20,
                    )
                    if rm_rect.collidepoint(pos):
                        features.pop(i)
                        if self.selected_feature_index == i:
                            self.selected_feature_index = None
                        elif (self.selected_feature_index is not None
                              and self.selected_feature_index > i):
                            self.selected_feature_index -= 1
                        return True
                    self.selected_feature_index = i
                    self._load_feature_edit()
                    return True

            # Character-only clicks
            from arena.gui.screens.character_builder import CreatureMode
            if self.screen.creature_mode == CreatureMode.CHARACTER:
                # Add Resource button
                if self.add_resource_btn.collidepoint(pos):
                    resources = self.screen.form_data.get("class_resources", {})
                    # Generate unique default name
                    idx = 1
                    while f"resource_{idx}" in resources:
                        idx += 1
                    resources[f"resource_{idx}"] = 1
                    self.screen.form_data["class_resources"] = resources
                    self._rebuild_resource_widgets()
                    return True

                # Remove resource [x] buttons
                for i in range(len(self.resource_name_inputs)):
                    rm_x = self.resource_name_inputs[i].rect.x + int(
                        (self.screen.content_rect.width - 20) * 0.52
                    ) + 110
                    rm_y = self.resource_name_inputs[i].rect.y + 3
                    rm_rect = pygame.Rect(rm_x, rm_y, 20, 20)
                    if rm_rect.collidepoint(pos):
                        resources = self.screen.form_data.get("class_resources", {})
                        name = self.resource_name_inputs[i].value
                        if name in resources:
                            del resources[name]
                        self.screen.form_data["class_resources"] = resources
                        self._rebuild_resource_widgets()
                        return True

                # Add Feat button
                if self.add_feat_btn.collidepoint(pos):
                    self.feat_dropdown.is_open = True
                    return True

                # Click on feat in list
                feats_y = self._get_feats_render_y()
                for i in range(len(self.feats_data)):
                    fy = feats_y + 24 + i * 28
                    feat_rect = pygame.Rect(
                        self.screen.get_content_origin()[0], fy,
                        self.screen.content_rect.width - 50, 26,
                    )
                    if feat_rect.collidepoint(pos):
                        # Check remove button
                        rm_rect = pygame.Rect(feat_rect.right + 2, fy + 3, 20, 20)
                        if rm_rect.collidepoint(pos):
                            self.feats_data.pop(i)
                            self._sync_feats_to_form()
                            if self.selected_feat_index == i:
                                self.selected_feat_index = None
                            elif (self.selected_feat_index is not None
                                  and self.selected_feat_index > i):
                                self.selected_feat_index -= 1
                            return True
                        self.selected_feat_index = i
                        self._load_feat_edit()
                        return True

        if event.type == pygame.MOUSEMOTION:
            self.add_feature_hovered = self.add_feature_btn.collidepoint(event.pos)
            self.add_resource_hovered = self.add_resource_btn.collidepoint(event.pos)
            self.add_feat_hovered = self.add_feat_btn.collidepoint(event.pos)

        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if self.features_list_rect.collidepoint(pos):
                features = self._get_features()
                max_scroll = max(0, len(features) * 30 - self.features_list_rect.height + 26)
                self.feature_scroll_offset = max(
                    0, min(max_scroll, self.feature_scroll_offset - event.y * 20),
                )
                return True

        # Spell slots and other spinners
        from arena.gui.screens.character_builder import CreatureMode
        if self.screen.creature_mode == CreatureMode.CHARACTER:
            for dd in self._dropdowns:
                if dd.handle_event(event):
                    self._sync_to_form()
                    return True
            for spinner in self.slot_spinners.values():
                if spinner.handle_event(event):
                    self._sync_to_form()
                    return True
            if self.spells_known_list.handle_event(event):
                self._sync_to_form()
                return True
            if self.spells_prepared_list.handle_event(event):
                self._sync_to_form()
                return True
        else:
            if self.legend_count_spinner.handle_event(event):
                self._sync_to_form()
                return True

        return False

    def _load_feature_edit(self) -> None:
        """Populate edit fields from the selected feature."""
        features = self._get_features()
        if (self.selected_feature_index is not None
                and 0 <= self.selected_feature_index < len(features)):
            f = features[self.selected_feature_index]
            self.feat_name_input.value = f.get("name", "")
            self.feat_desc_input.value = f.get("description", "")
            self.feat_source_input.value = f.get("source", "")

            # Bonus fields
            self.feat_ac_spinner.value = f.get("bonus_ac", 0)
            self.feat_speed_spinner.value = f.get("bonus_speed", 0)
            self.feat_init_spinner.value = f.get("bonus_initiative", 0)

            ability_bonuses = f.get("bonus_ability_scores", {})
            for ability in ABILITY_NAMES:
                self.feat_ability_spinners[ability].value = ability_bonuses.get(ability, 0)

            ud = f.get("unarmored_defense") or "(none)"
            try:
                self.feat_unarmored_dropdown.selected_index = UNARMORED_DEFENSE_OPTIONS.index(ud)
            except ValueError:
                self.feat_unarmored_dropdown.selected_index = 0

            self.feat_resist_list.items = list(f.get("grants_damage_resistances", []))
            self.feat_immune_list.items = list(f.get("grants_damage_immunities", []))
            self.feat_cond_immune_list.items = list(f.get("grants_condition_immunities", []))
            self.feat_save_prof_list.items = list(f.get("grants_saving_throw_proficiencies", []))

            # On-hit rider
            rider = f.get("on_hit_rider")
            if rider and isinstance(rider, dict):
                trigger = rider.get("trigger", "(none)")
                try:
                    self.rider_trigger_dropdown.selected_index = RIDER_TRIGGER_OPTIONS.index(trigger)
                except ValueError:
                    self.rider_trigger_dropdown.selected_index = 0
                self._rider_once_per_turn = rider.get("once_per_turn", False)

                res_type = rider.get("resource_type") or "(none)"
                try:
                    self.rider_resource_dropdown.selected_index = RIDER_RESOURCE_OPTIONS.index(res_type)
                except ValueError:
                    self.rider_resource_dropdown.selected_index = 0
                self.rider_cost_spinner.value = rider.get("resource_cost", 0)

                self.rider_dice_input.value = rider.get("damage_dice", "") or ""
                dtype = rider.get("damage_type", "radiant")
                try:
                    self.rider_damage_type_dropdown.selected_index = RIDER_DAMAGE_TYPES.index(dtype)
                except ValueError:
                    self.rider_damage_type_dropdown.selected_index = 0
                self.rider_scale_input.value = rider.get("damage_per_slot_level", "") or ""
                self.rider_max_dice_spinner.value = rider.get("max_dice", 0) or 0

                save_ab = rider.get("save_ability") or "(none)"
                try:
                    self.rider_save_dropdown.selected_index = RIDER_SAVE_ABILITIES.index(save_ab)
                except ValueError:
                    self.rider_save_dropdown.selected_index = 0
                dc_ab = rider.get("save_dc_ability") or "(none)"
                try:
                    self.rider_dc_ability_dropdown.selected_index = RIDER_SAVE_ABILITIES.index(dc_ab)
                except ValueError:
                    self.rider_dc_ability_dropdown.selected_index = 0
                cond = rider.get("condition_on_fail") or "(none)"
                try:
                    self.rider_condition_dropdown.selected_index = RIDER_CONDITIONS.index(cond)
                except ValueError:
                    self.rider_condition_dropdown.selected_index = 0

                self._rider_requires_melee = rider.get("requires_melee", False)
                self._rider_requires_weapon = rider.get("requires_weapon", False)
            else:
                self._reset_rider_widgets()

            # --- Load collapsible primitive fields ---
            # Combat Mechanics
            self._cb_has_evasion = f.get("has_evasion", False)
            self._sp_extra_attack.value = f.get("extra_attack_count", 0) or 0
            self._sp_crit_range.value = f.get("crit_range_reduction", 0) or 0
            self._sp_bonus_crit_dice.value = f.get("bonus_crit_dice", 0) or 0

            # Damage Reduction
            self._inp_dr_dice.value = f.get("damage_reduction_dice", "") or ""
            dr_bonus = f.get("damage_reduction_bonus") or "(none)"
            try:
                self._dd_dr_ability.selected_index = ABILITY_OPTIONS.index(dr_bonus)
            except ValueError:
                self._dd_dr_ability.selected_index = 0
            self._cb_dr_flat_half = f.get("damage_reduction_flat_half", False)
            dr_type = f.get("damage_reduction_type") or "(none)"
            try:
                self._dd_dr_type.selected_index = DAMAGE_REDUCTION_TYPE_OPTIONS.index(dr_type)
            except ValueError:
                self._dd_dr_type.selected_index = 0

            # Forced Reroll
            self._cb_reroll_saves = f.get("forced_reroll_saves", False)
            self._inp_reroll_resource.value = f.get("forced_reroll_resource", "") or ""
            self._sp_reroll_cost.value = f.get("forced_reroll_resource_cost", 1) or 1

            # Aura Effects
            self._sp_aura_range.value = f.get("aura_range", 0) or 0
            aura_ab = f.get("aura_save_bonus_ability") or "(none)"
            try:
                self._dd_aura_save_ability.selected_index = ABILITY_OPTIONS.index(aura_ab)
            except ValueError:
                self._dd_aura_save_ability.selected_index = 0
            aura_conds = f.get("aura_condition_immunity", [])
            self._inp_aura_cond_immune.value = ", ".join(aura_conds) if aura_conds else ""

            # Death Prevention
            self._cb_death_prevention = f.get("death_prevention", False)
            death_ab = f.get("death_prevention_save_ability") or "(none)"
            try:
                self._dd_death_save_ability.selected_index = ABILITY_OPTIONS.index(death_ab)
            except ValueError:
                self._dd_death_save_ability.selected_index = 0
            self._sp_death_save_dc.value = f.get("death_prevention_save_dc", 10) or 10
            self._sp_death_dc_increment.value = f.get("death_prevention_dc_increment", 0) or 0
            self._inp_death_resource.value = f.get("death_prevention_resource", "") or ""

            # Active Condition Immunity
            active_conds = f.get("active_condition_immunities", [])
            self._inp_active_cond.value = ", ".join(active_conds) if active_conds else ""
            self._inp_active_cond_resource.value = f.get("active_condition_resource", "") or ""

    def _reset_rider_widgets(self) -> None:
        """Reset all rider widgets to defaults."""
        self.rider_trigger_dropdown.selected_index = 0
        self._rider_once_per_turn = False
        self.rider_resource_dropdown.selected_index = 0
        self.rider_cost_spinner.value = 0
        self.rider_dice_input.value = ""
        self.rider_damage_type_dropdown.selected_index = 0
        self.rider_scale_input.value = ""
        self.rider_max_dice_spinner.value = 0
        self.rider_save_dropdown.selected_index = 0
        self.rider_dc_ability_dropdown.selected_index = 0
        self.rider_condition_dropdown.selected_index = 0
        self._rider_requires_melee = False
        self._rider_requires_weapon = False

    def _sync_feature_edit(self) -> None:
        """Write edit fields back to the selected feature."""
        features = self._get_features()
        if (self.selected_feature_index is not None
                and 0 <= self.selected_feature_index < len(features)):
            # Build ability score bonuses (only non-zero)
            ability_bonuses = {}
            for ability in ABILITY_NAMES:
                val = self.feat_ability_spinners[ability].value
                if val != 0:
                    ability_bonuses[ability] = val

            # Unarmored defense
            ud_val = self.feat_unarmored_dropdown.value
            unarmored = None if ud_val == "(none)" else ud_val

            # On-hit rider
            rider_data = None
            trigger_val = self.rider_trigger_dropdown.value
            if trigger_val != "(none)":
                res_val = self.rider_resource_dropdown.value
                save_val = self.rider_save_dropdown.value
                dc_val = self.rider_dc_ability_dropdown.value
                cond_val = self.rider_condition_dropdown.value
                max_d = self.rider_max_dice_spinner.value
                rider_data = {
                    "trigger": trigger_val,
                    "once_per_turn": self._rider_once_per_turn,
                    "resource_type": None if res_val == "(none)" else res_val,
                    "resource_cost": self.rider_cost_spinner.value,
                    "damage_dice": self.rider_dice_input.value or None,
                    "damage_type": self.rider_damage_type_dropdown.value,
                    "damage_per_slot_level": self.rider_scale_input.value or None,
                    "max_dice": max_d if max_d > 0 else None,
                    "save_ability": None if save_val == "(none)" else save_val,
                    "save_dc_ability": None if dc_val == "(none)" else dc_val,
                    "condition_on_fail": None if cond_val == "(none)" else cond_val,
                    "requires_melee": self._rider_requires_melee,
                    "requires_weapon": self._rider_requires_weapon,
                }

            features[self.selected_feature_index] = {
                "name": self.feat_name_input.value,
                "description": self.feat_desc_input.value,
                "source": self.feat_source_input.value,
                "bonus_ac": self.feat_ac_spinner.value,
                "bonus_speed": self.feat_speed_spinner.value,
                "bonus_initiative": self.feat_init_spinner.value,
                "bonus_ability_scores": ability_bonuses,
                "unarmored_defense": unarmored,
                "grants_damage_resistances": list(self.feat_resist_list.items),
                "grants_damage_immunities": list(self.feat_immune_list.items),
                "grants_condition_immunities": list(self.feat_cond_immune_list.items),
                "grants_saving_throw_proficiencies": list(self.feat_save_prof_list.items),
                "on_hit_rider": rider_data,
                # Combat Mechanics
                "has_evasion": self._cb_has_evasion,
                "extra_attack_count": self._sp_extra_attack.value,
                "crit_range_reduction": self._sp_crit_range.value,
                "bonus_crit_dice": self._sp_bonus_crit_dice.value,
                # Damage Reduction
                "damage_reduction_dice": self._inp_dr_dice.value or None,
                "damage_reduction_bonus": (
                    None if self._dd_dr_ability.value == "(none)"
                    else self._dd_dr_ability.value
                ),
                "damage_reduction_flat_half": self._cb_dr_flat_half,
                "damage_reduction_type": (
                    None if self._dd_dr_type.value == "(none)"
                    else self._dd_dr_type.value
                ),
                # Forced Reroll
                "forced_reroll_saves": self._cb_reroll_saves,
                "forced_reroll_resource": self._inp_reroll_resource.value or None,
                "forced_reroll_resource_cost": self._sp_reroll_cost.value,
                # Aura Effects
                "aura_range": self._sp_aura_range.value,
                "aura_save_bonus_ability": (
                    None if self._dd_aura_save_ability.value == "(none)"
                    else self._dd_aura_save_ability.value
                ),
                "aura_condition_immunity": [
                    s.strip() for s in self._inp_aura_cond_immune.value.split(",")
                    if s.strip()
                ],
                # Death Prevention
                "death_prevention": self._cb_death_prevention,
                "death_prevention_save_ability": (
                    None if self._dd_death_save_ability.value == "(none)"
                    else self._dd_death_save_ability.value
                ),
                "death_prevention_save_dc": self._sp_death_save_dc.value,
                "death_prevention_dc_increment": self._sp_death_dc_increment.value,
                "death_prevention_resource": self._inp_death_resource.value or None,
                # Active Condition Immunity
                "active_condition_immunities": [
                    s.strip() for s in self._inp_active_cond.value.split(",")
                    if s.strip()
                ],
                "active_condition_resource": self._inp_active_cond_resource.value or None,
            }

    def _sync_resources(self) -> None:
        """Write resource widgets back to form_data.

        Preserves any ``spell_slot_*`` keys that exist in
        ``class_resources`` (managed by the spell-slot spinners, not
        the resource widgets).
        """
        old = self.screen.form_data.get("class_resources", {})
        new_resources: dict[str, int] = {
            k: v for k, v in old.items() if k.startswith("spell_slot_")
        }
        for i, inp in enumerate(self.resource_name_inputs):
            name = inp.value.strip()
            if name:
                value = self.resource_value_spinners[i].value
                new_resources[name] = value
        self.screen.form_data["class_resources"] = new_resources

    def _load_feat_edit(self) -> None:
        """Populate feat edit fields from the selected feat."""
        if (self.selected_feat_index is not None
                and 0 <= self.selected_feat_index < len(self.feats_data)):
            f = self.feats_data[self.selected_feat_index]
            self.feat_desc_edit.value = f.get("description", "")

    def _sync_feat_edit(self) -> None:
        """Write feat description back to feats_data."""
        if (self.selected_feat_index is not None
                and 0 <= self.selected_feat_index < len(self.feats_data)):
            self.feats_data[self.selected_feat_index]["description"] = self.feat_desc_edit.value
            self._sync_feats_to_form()

    def _sync_feats_to_form(self) -> None:
        """Write feats_data back to form_data."""
        self.screen.form_data["feats"] = list(self.feats_data)

    def _get_feats_render_y(self) -> int:
        """Get the y position where the feats section starts."""
        return self._resource_section_y + self._get_resource_section_height()

    def _sync_to_form(self) -> None:
        d = self.screen.form_data
        from arena.gui.screens.character_builder import CreatureMode
        if self.screen.creature_mode == CreatureMode.CHARACTER:
            ability = self.spell_ability_dropdown.value
            d["spellcasting_ability"] = "" if ability == "(none)" else ability
            slots = {}
            for lvl, spinner in self.slot_spinners.items():
                if spinner.value > 0:
                    slots[lvl] = spinner.value
            d["spell_slots"] = slots
            d["spells_known"] = list(self.spells_known_list.items)
            d["spells_prepared"] = list(self.spells_prepared_list.items)

            # Handle feat dropdown selection
            if self.feat_dropdown.selected_index > 0:
                feat_name = self.feat_dropdown.value
                feat_data = FEAT_DATA.get(feat_name, {})
                new_feat = {
                    "name": feat_name,
                    "description": feat_data.get("description", ""),
                    "bonus_ability_scores": dict(feat_data.get("bonus_ability_scores", {})),
                    "bonus_speed": feat_data.get("bonus_speed", 0),
                    "bonus_ac": feat_data.get("bonus_ac", 0),
                    "bonus_initiative": feat_data.get("bonus_initiative", 0),
                    "grants_damage_resistances": list(feat_data.get("grants_damage_resistances", [])),
                    "grants_damage_immunities": list(feat_data.get("grants_damage_immunities", [])),
                    "grants_condition_immunities": list(feat_data.get("grants_condition_immunities", [])),
                    "grants_saving_throw_proficiencies": list(feat_data.get("grants_saving_throw_proficiencies", [])),
                }
                self.feats_data.append(new_feat)
                self._sync_feats_to_form()
                self.feat_dropdown.selected_index = 0  # Reset dropdown
        else:
            d["legendary_action_count"] = self.legend_count_spinner.value

    def render(self, surface: pygame.Surface) -> None:
        self._reposition_widgets()

        ox, oy = self.screen.get_content_origin()
        scroll_y = self.screen.get_scroll_y()
        oy -= scroll_y

        label_color = parse_color(COLORS["text_secondary"])
        gold_color = parse_color(COLORS["text_gold"])
        font = get_font(14)
        w = self.screen.content_rect.width - 20

        from arena.gui.screens.character_builder import CreatureMode
        is_char = self.screen.creature_mode == CreatureMode.CHARACTER

        # --- Features section header ---
        section_name = "Features" if is_char else "Special Abilities"
        header = get_font(18)
        header_surf = header.render(
            section_name, True, gold_color,
        )
        surface.blit(header_surf, (ox, oy + 2))

        # Add button
        add_color = (
            parse_color(COLORS["button_hover"]) if self.add_feature_hovered
            else parse_color(COLORS["button_normal"])
        )
        pygame.draw.rect(surface, add_color, self.add_feature_btn, border_radius=3)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            self.add_feature_btn, 1, border_radius=3,
        )
        draw_text_centered(
            surface, "+ Add", self.add_feature_btn.center,
            parse_color(COLORS["text_primary"]), font_size=12,
        )

        # Feature list
        features = self._get_features()
        list_clip = pygame.Rect(
            self.features_list_rect.x, self.features_list_rect.y + 26,
            self.features_list_rect.width, self.features_list_rect.height - 26,
        )
        old_clip = surface.get_clip()
        surface.set_clip(list_clip)

        for i, feat in enumerate(features):
            item_y = (
                self.features_list_rect.y + 26
                + i * 30 - self.feature_scroll_offset
            )
            item_rect = pygame.Rect(
                self.features_list_rect.x, item_y,
                self.features_list_rect.width - 30, 28,
            )
            selected = i == self.selected_feature_index
            bg = (
                parse_color(COLORS["button_active"]) if selected
                else parse_color(COLORS["button_normal"])
            )
            pygame.draw.rect(surface, bg, item_rect, border_radius=3)
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                item_rect, 1, border_radius=3,
            )

            name = feat.get("name", "") or "(unnamed)"
            name_surf = font.render(
                name, True, parse_color(COLORS["text_primary"]),
            )
            surface.blit(name_surf, (item_rect.x + 6, item_y + 5))

            # Remove [x]
            draw_text_centered(
                surface, "x",
                (item_rect.right + 12, item_y + 14),
                parse_color(COLORS["text_secondary"]), font_size=12,
            )

        if not features:
            empty = font.render("(none)", True, label_color)
            surface.blit(empty, (ox + 6, self.features_list_rect.y + 30))

        surface.set_clip(old_clip)

        # --- Feature edit fields ---
        if self.selected_feature_index is not None:
            edit_y = oy + 170
            lbl_n = font.render("Name:", True, label_color)
            surface.blit(lbl_n, (ox, edit_y))
            self.feat_name_input.render(surface)

            lbl_d = font.render("Description:", True, label_color)
            surface.blit(lbl_d, (ox + int((self.screen.content_rect.width - 20) * 0.52) - 10, edit_y))
            self.feat_desc_input.render(surface)

            lbl_s = font.render("Source:", True, label_color)
            surface.blit(lbl_s, (ox, edit_y + 44))
            self.feat_source_input.render(surface)

            # --- Feature bonus fields ---
            bonus_y = edit_y + 90
            small_font = get_font(12)
            third_w = int(w * 0.30)

            # Row 1: AC / Speed / Initiative spinners
            lbl_ac = small_font.render("AC:", True, label_color)
            surface.blit(lbl_ac, (ox, bonus_y + 4))
            self.feat_ac_spinner.render(surface)

            lbl_spd = small_font.render("Speed:", True, label_color)
            surface.blit(lbl_spd, (ox + third_w + 10, bonus_y + 4))
            self.feat_speed_spinner.render(surface)

            lbl_init = small_font.render("Initiative:", True, label_color)
            surface.blit(lbl_init, (ox + 2 * third_w + 10, bonus_y + 4))
            self.feat_init_spinner.render(surface)

            # Row 2-3: Ability score bonuses
            lbl_abs = small_font.render("Ability Score Bonuses:", True, label_color)
            surface.blit(lbl_abs, (ox, bonus_y + 32))

            ab_col_w = int(w / 3)
            for idx_ab, ability in enumerate(ABILITY_NAMES):
                col = idx_ab % 3
                row = idx_ab // 3
                ax = ox + col * ab_col_w
                ay = bonus_y + 50 + row * 28
                ab_lbl = small_font.render(ABILITY_SHORT[idx_ab] + ":", True, label_color)
                surface.blit(ab_lbl, (ax, ay + 4))
                self.feat_ability_spinners[ability].render(surface)

            # Unarmored Defense dropdown
            lbl_ud = small_font.render("Unarmored Defense:", True, label_color)
            surface.blit(lbl_ud, (ox, bonus_y + 118))
            self.feat_unarmored_dropdown.render(surface)

            # List editors row 1: Damage Resistances / Damage Immunities
            list_half = int(w * 0.48)
            list_y1 = bonus_y + 150
            lbl_dr = small_font.render("Damage Resistances:", True, label_color)
            surface.blit(lbl_dr, (ox, list_y1 - 14))
            self.feat_resist_list.render(surface)

            lbl_di = small_font.render("Damage Immunities:", True, label_color)
            surface.blit(lbl_di, (ox + list_half + 10, list_y1 - 14))
            self.feat_immune_list.render(surface)

            # List editors row 2: Condition Immunities / Save Proficiencies
            list_h = 64
            list_y2 = list_y1 + list_h + 20
            lbl_ci = small_font.render("Condition Immunities:", True, label_color)
            surface.blit(lbl_ci, (ox, list_y2 - 14))
            self.feat_cond_immune_list.render(surface)

            lbl_sp = small_font.render("Save Proficiencies:", True, label_color)
            surface.blit(lbl_sp, (ox + list_half + 10, list_y2 - 14))
            self.feat_save_prof_list.render(surface)

            # --- On-Hit Rider section ---
            rider_y = list_y2 + list_h + 30
            lbl_trigger = small_font.render("Rider:", True, label_color)
            surface.blit(lbl_trigger, (ox, rider_y + 4))
            self.rider_trigger_dropdown.render(surface)

            if self.rider_trigger_dropdown.selected_index > 0:
                # Once per turn checkbox
                cb_rect = self.rider_once_per_turn_cb
                cb_box = pygame.Rect(cb_rect.x, cb_rect.y + 4, 16, 16)
                pygame.draw.rect(surface, parse_color(COLORS["bg_dark"]), cb_box, border_radius=2)
                pygame.draw.rect(surface, parse_color(COLORS["hex_border"]), cb_box, 1, border_radius=2)
                if self._rider_once_per_turn:
                    pygame.draw.line(
                        surface, parse_color(COLORS["text_primary"]),
                        (cb_box.x + 3, cb_box.centery),
                        (cb_box.centerx, cb_box.bottom - 4), 2,
                    )
                    pygame.draw.line(
                        surface, parse_color(COLORS["text_primary"]),
                        (cb_box.centerx, cb_box.bottom - 4),
                        (cb_box.right - 3, cb_box.y + 3), 2,
                    )
                cb_lbl = small_font.render("Once/turn", True, label_color)
                surface.blit(cb_lbl, (cb_rect.x + 20, rider_y + 4))

                # Resource row
                lbl_res = small_font.render("Resource:", True, label_color)
                surface.blit(lbl_res, (ox, rider_y + 34))
                self.rider_resource_dropdown.render(surface)
                lbl_cost = small_font.render("Cost:", True, label_color)
                surface.blit(lbl_cost, (ox + 255, rider_y + 34))
                self.rider_cost_spinner.render(surface)

                # Damage row
                lbl_dice = small_font.render("Dice:", True, label_color)
                surface.blit(lbl_dice, (ox - 40 + 40, rider_y + 64))
                self.rider_dice_input.render(surface)
                self.rider_damage_type_dropdown.render(surface)
                lbl_scale = small_font.render("Scale:", True, label_color)
                surface.blit(lbl_scale, (ox + 250, rider_y + 64))
                self.rider_scale_input.render(surface)
                lbl_max = small_font.render("Max:", True, label_color)
                surface.blit(lbl_max, (ox + 375, rider_y + 64))
                self.rider_max_dice_spinner.render(surface)

                # Save row
                lbl_save = small_font.render("Save:", True, label_color)
                surface.blit(lbl_save, (ox, rider_y + 94))
                self.rider_save_dropdown.render(surface)
                lbl_dc = small_font.render("DC Ability:", True, label_color)
                surface.blit(lbl_dc, (ox + 190, rider_y + 94))
                self.rider_dc_ability_dropdown.render(surface)

                # Condition row
                lbl_cond = small_font.render("Condition:", True, label_color)
                surface.blit(lbl_cond, (ox, rider_y + 124))
                self.rider_condition_dropdown.render(surface)

                # Checkbox row: requires melee / requires weapon
                self._render_rider_checkbox(
                    surface, self.rider_melee_cb_rect,
                    self._rider_requires_melee, "Requires Melee",
                    small_font, label_color,
                )
                self._render_rider_checkbox(
                    surface, self.rider_weapon_cb_rect,
                    self._rider_requires_weapon, "Requires Weapon",
                    small_font, label_color,
                )

            # --- Collapsible primitive sections ---
            features = self._get_features()
            cur_feature = {}
            if (self.selected_feature_index is not None
                    and 0 <= self.selected_feature_index < len(features)):
                cur_feature = features[self.selected_feature_index]

            for sid in FEAT_SECTION_IDS:
                self._render_feat_section_header(surface, sid, cur_feature)
                if self._feat_section_expanded.get(sid, False):
                    self._render_section_content(surface, sid, small_font, label_color)

        # Separator (dynamic y based on feature edit height)
        feature_edit_h = self._get_feature_edit_height()
        sep_y = oy + 170 + feature_edit_h + 10
        pygame.draw.line(
            surface, parse_color(COLORS["hex_border"]),
            (ox, sep_y), (ox + w, sep_y),
        )

        # --- Mode-specific section ---
        if is_char:
            self._render_resources(surface, ox, label_color, gold_color, font, w)
            self._render_feats(surface, ox, label_color, gold_color, font, w)
            self._render_spellcasting(surface, ox, label_color, font, w)
        else:
            self._render_legendary(surface, ox, oy, label_color, font)

    def _render_resources(self, surface, ox, label_color, gold_color, font, w):
        """Render the Class Resources section."""
        y = self._resource_section_y

        # Section header
        header_surf = get_font(16).render("Class Resources", True, gold_color)
        surface.blit(header_surf, (ox, y))

        # Add Resource button
        add_color = (
            parse_color(COLORS["button_hover"]) if self.add_resource_hovered
            else parse_color(COLORS["button_normal"])
        )
        pygame.draw.rect(surface, add_color, self.add_resource_btn, border_radius=3)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            self.add_resource_btn, 1, border_radius=3,
        )
        draw_text_centered(
            surface, "+ Resource", self.add_resource_btn.center,
            parse_color(COLORS["text_primary"]), font_size=11,
        )

        # Resource entries
        for i in range(len(self.resource_name_inputs)):
            self.resource_name_inputs[i].render(surface)
            self.resource_value_spinners[i].render(surface)

            # Remove [x] button
            rm_x = ox + int(w * 0.52) + 110
            rm_y = self.resource_name_inputs[i].rect.y + 3
            draw_text_centered(
                surface, "x", (rm_x + 10, rm_y + 10),
                parse_color(COLORS["text_secondary"]), font_size=12,
            )

        if not self.resource_name_inputs:
            empty_y = y + 24
            empty_surf = font.render("(none — click + Resource to add)", True, label_color)
            surface.blit(empty_surf, (ox + 6, empty_y))

    def _render_feats(self, surface, ox, label_color, gold_color, font, w):
        """Render the Feats section."""
        y = self._get_feats_render_y()

        # Separator
        pygame.draw.line(
            surface, parse_color(COLORS["hex_border"]),
            (ox, y - 2), (ox + w, y - 2),
        )

        # Section header
        header_surf = get_font(16).render("Feats", True, gold_color)
        surface.blit(header_surf, (ox, y))

        # Add Feat button (rect already positioned by _reposition_widgets)
        add_color = (
            parse_color(COLORS["button_hover"]) if self.add_feat_hovered
            else parse_color(COLORS["button_normal"])
        )
        pygame.draw.rect(surface, add_color, self.add_feat_btn, border_radius=3)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            self.add_feat_btn, 1, border_radius=3,
        )
        draw_text_centered(
            surface, "+ Feat", self.add_feat_btn.center,
            parse_color(COLORS["text_primary"]), font_size=11,
        )

        # Feat list
        feat_y = y + 24
        for i, feat_d in enumerate(self.feats_data):
            feat_rect = pygame.Rect(ox, feat_y, w - 30, 26)
            selected = i == self.selected_feat_index
            bg = (
                parse_color(COLORS["button_active"]) if selected
                else parse_color(COLORS["button_normal"])
            )
            pygame.draw.rect(surface, bg, feat_rect, border_radius=3)
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                feat_rect, 1, border_radius=3,
            )

            fname = feat_d.get("name", "") or "(unnamed)"
            # Show brief bonuses inline
            bonuses = []
            if feat_d.get("bonus_initiative"):
                bonuses.append(f"+{feat_d['bonus_initiative']} init")
            if feat_d.get("bonus_speed"):
                bonuses.append(f"+{feat_d['bonus_speed']} spd")
            if feat_d.get("bonus_ac"):
                bonuses.append(f"+{feat_d['bonus_ac']} AC")
            for ability, val in feat_d.get("bonus_ability_scores", {}).items():
                bonuses.append(f"+{val} {ability[:3].upper()}")
            bonus_text = f"  ({', '.join(bonuses)})" if bonuses else ""

            name_surf = font.render(
                fname + bonus_text, True, parse_color(COLORS["text_primary"]),
            )
            surface.blit(name_surf, (feat_rect.x + 6, feat_y + 5))

            # Remove [x]
            draw_text_centered(
                surface, "x",
                (feat_rect.right + 12, feat_y + 13),
                parse_color(COLORS["text_secondary"]), font_size=12,
            )
            feat_y += 28

        if not self.feats_data:
            empty_surf = font.render("(none — click + Feat to add)", True, label_color)
            surface.blit(empty_surf, (ox + 6, feat_y))
            feat_y += 18

        # Selected feat description edit
        if (self.selected_feat_index is not None
                and 0 <= self.selected_feat_index < len(self.feats_data)):
            self.feat_desc_edit.rect = pygame.Rect(ox, feat_y + 2, w, 26)
            desc_lbl = font.render("Description:", True, label_color)
            surface.blit(desc_lbl, (ox, feat_y - 12))
            self.feat_desc_edit.render(surface)

    def _render_spellcasting(self, surface, ox, label_color, font, w):
        """Render the Spellcasting section with dynamic y offset."""
        base_y = self._get_feats_render_y() + self._get_feats_section_height()

        # Separator
        pygame.draw.line(
            surface, parse_color(COLORS["hex_border"]),
            (ox, base_y - 2), (ox + w, base_y - 2),
        )

        spell_y = base_y

        # Spellcasting ability (rect already positioned by _reposition_widgets)
        lbl = font.render("Spellcasting Ability:", True, label_color)
        surface.blit(lbl, (ox, spell_y))
        self.spell_ability_dropdown.render(surface)

        # Spell slots (rects already positioned by _reposition_widgets)
        slot_y = spell_y + 60
        lbl2 = font.render("Spell Slots:", True, label_color)
        surface.blit(lbl2, (ox, slot_y - 4))
        for lvl in range(1, 10):
            col = (lvl - 1) % 5
            row = (lvl - 1) // 5
            sx = ox + col * SPELL_SLOT_COL_SPACING
            sy = slot_y + row * 50
            lvl_lbl = font.render(f"Lvl {lvl}:", True, label_color)
            surface.blit(lvl_lbl, (sx, sy + 2))
            self.slot_spinners[lvl].render(surface)

        # Spells known / prepared (rects already positioned by _reposition_widgets)
        list_y = slot_y + 120
        half_w = int(w * 0.48)

        lbl3 = font.render("Spells Known:", True, label_color)
        surface.blit(lbl3, (ox, list_y))
        self.spells_known_list.render(surface)

        lbl4 = font.render("Spells Prepared:", True, label_color)
        surface.blit(lbl4, (ox + int(w * 0.52), list_y))
        self.spells_prepared_list.render(surface)

    def _render_legendary(self, surface, ox, oy, label_color, font):
        leg_y = self._resource_section_y
        lbl = font.render("Legendary Action Count:", True, label_color)
        surface.blit(lbl, (ox, leg_y))
        self.legend_count_spinner.render(surface)

    def _render_rider_checkbox(
        self, surface, rect, checked, label_text, font, color,
    ) -> None:
        """Render a simple checkbox with label."""
        cb_box = pygame.Rect(rect.x, rect.y + 4, 16, 16)
        pygame.draw.rect(surface, parse_color(COLORS["bg_dark"]), cb_box, border_radius=2)
        pygame.draw.rect(surface, parse_color(COLORS["hex_border"]), cb_box, 1, border_radius=2)
        if checked:
            pygame.draw.line(
                surface, parse_color(COLORS["text_primary"]),
                (cb_box.x + 3, cb_box.centery),
                (cb_box.centerx, cb_box.bottom - 4), 2,
            )
            pygame.draw.line(
                surface, parse_color(COLORS["text_primary"]),
                (cb_box.centerx, cb_box.bottom - 4),
                (cb_box.right - 3, cb_box.y + 3), 2,
            )
        lbl = font.render(label_text, True, color)
        surface.blit(lbl, (rect.x + 20, rect.y + 4))

    def _render_section_content(
        self, surface: pygame.Surface, section_id: str,
        font: pygame.font.Font, label_color: tuple,
    ) -> None:
        """Render the widgets inside an expanded collapsible section."""
        ix = self._feat_section_header_rects[section_id].x + 10

        if section_id == FEAT_SECTION_COMBAT:
            # Has Evasion checkbox
            self._render_rider_checkbox(
                surface, self._cb_has_evasion_rect,
                self._cb_has_evasion, "Has Evasion",
                font, label_color,
            )
            # Extra Attacks spinner
            lbl = font.render("Extra Attacks:", True, label_color)
            surface.blit(lbl, (ix, self._sp_extra_attack.rect.y + 4))
            self._sp_extra_attack.render(surface)
            # Crit Range Reduction + Bonus Crit Dice
            lbl2 = font.render("Crit Range Reduction:", True, label_color)
            surface.blit(lbl2, (ix, self._sp_crit_range.rect.y + 4))
            self._sp_crit_range.render(surface)
            lbl3 = font.render("Bonus Crit Dice:", True, label_color)
            surface.blit(lbl3, (ix + 270, self._sp_bonus_crit_dice.rect.y + 4))
            self._sp_bonus_crit_dice.render(surface)

        elif section_id == FEAT_SECTION_DR:
            # Dice + Ability
            lbl = font.render("Dice:", True, label_color)
            surface.blit(lbl, (ix, self._inp_dr_dice.rect.y + 4))
            self._inp_dr_dice.render(surface)
            lbl2 = font.render("Ability Bonus:", True, label_color)
            surface.blit(lbl2, (ix + 160, self._dd_dr_ability.rect.y + 4))
            self._dd_dr_ability.render(surface)
            # Flat half checkbox
            self._render_rider_checkbox(
                surface, self._cb_dr_flat_half_rect,
                self._cb_dr_flat_half, "Halve Damage (Uncanny Dodge)",
                font, label_color,
            )
            # Type dropdown
            lbl3 = font.render("Type:", True, label_color)
            surface.blit(lbl3, (ix, self._dd_dr_type.rect.y + 4))
            self._dd_dr_type.render(surface)

        elif section_id == FEAT_SECTION_REROLL:
            # Checkbox
            self._render_rider_checkbox(
                surface, self._cb_reroll_saves_rect,
                self._cb_reroll_saves, "Reroll Failed Saves",
                font, label_color,
            )
            # Resource + Cost
            lbl = font.render("Resource:", True, label_color)
            surface.blit(lbl, (ix, self._inp_reroll_resource.rect.y + 4))
            self._inp_reroll_resource.render(surface)
            lbl2 = font.render("Cost:", True, label_color)
            surface.blit(lbl2, (ix + 290, self._sp_reroll_cost.rect.y + 4))
            self._sp_reroll_cost.render(surface)

        elif section_id == FEAT_SECTION_AURA:
            # Range spinner
            lbl = font.render("Aura Range (ft):", True, label_color)
            surface.blit(lbl, (ix, self._sp_aura_range.rect.y + 4))
            self._sp_aura_range.render(surface)
            # Save Bonus Ability
            lbl2 = font.render("Save Bonus Ability:", True, label_color)
            surface.blit(lbl2, (ix, self._dd_aura_save_ability.rect.y + 4))
            self._dd_aura_save_ability.render(surface)
            # Condition Immunities
            lbl3 = font.render("Condition Immunities:", True, label_color)
            surface.blit(lbl3, (ix, self._inp_aura_cond_immune.rect.y + 4))
            self._inp_aura_cond_immune.render(surface)

        elif section_id == FEAT_SECTION_DEATH:
            # Death Prevention checkbox
            self._render_rider_checkbox(
                surface, self._cb_death_prevention_rect,
                self._cb_death_prevention, "Has Death Prevention",
                font, label_color,
            )
            # Save Ability
            lbl = font.render("Save Ability:", True, label_color)
            surface.blit(lbl, (ix, self._dd_death_save_ability.rect.y + 4))
            self._dd_death_save_ability.render(surface)
            # Base DC + Increment
            lbl2 = font.render("Base DC:", True, label_color)
            surface.blit(lbl2, (ix, self._sp_death_save_dc.rect.y + 4))
            self._sp_death_save_dc.render(surface)
            lbl3 = font.render("DC Increment:", True, label_color)
            surface.blit(lbl3, (ix + 170, self._sp_death_dc_increment.rect.y + 4))
            self._sp_death_dc_increment.render(surface)
            # Resource
            lbl4 = font.render("Resource:", True, label_color)
            surface.blit(lbl4, (ix, self._inp_death_resource.rect.y + 4))
            self._inp_death_resource.render(surface)

        elif section_id == FEAT_SECTION_ACTIVE_COND:
            # Condition Immunities
            lbl = font.render("Immunities:", True, label_color)
            surface.blit(lbl, (ix, self._inp_active_cond.rect.y + 4))
            self._inp_active_cond.render(surface)
            # Required Resource
            lbl2 = font.render("Required Resource:", True, label_color)
            surface.blit(lbl2, (ix, self._inp_active_cond_resource.rect.y + 4))
            self._inp_active_cond_resource.render(surface)

    def render_overlays(self, surface: pygame.Surface) -> None:
        self.spell_ability_dropdown.render_dropdown(surface)
        self.feat_dropdown.render_dropdown(surface)
        self.feat_unarmored_dropdown.render_dropdown(surface)
        for le in self._feature_bonus_lists:
            le.render_overlay(surface)
        # Rider dropdowns
        for dd in self._rider_dropdowns:
            dd.render_dropdown(surface)
        # Section dropdowns
        for dd in self._section_dropdowns:
            dd.render_dropdown(surface)
