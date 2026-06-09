"""Creature builder screen for creating and editing characters, monsters, and NPCs."""

from __future__ import annotations

import re
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from arena.gui.renderer import draw_text_centered, get_font
from arena.gui.screens.base import Screen
from arena.gui.button_images import draw_image_button
from arena.gui.tray_backgrounds import draw_tray_background
from arena.util.constants import COLORS, parse_color
from arena.util.loader import (
    load_character,
    load_json,
    load_monster,
    save_character,
    save_monster,
)

if TYPE_CHECKING:
    from arena.gui.app import App

# Layout constants
TOP_BAR_HEIGHT = 40
LEFT_PANEL_WIDTH = 300
STATUS_BAR_HEIGHT = 40
CONTENT_PADDING = 10


class CreatureMode(Enum):
    CHARACTER = auto()
    MONSTER = auto()
    NPC = auto()


TAB_NAMES = [
    "Identity",
    "Abilities",
    "Combat",
    "Actions",
    "Features",
    "Equipment",
    "Token/AI",
]


class CreatureBuilderScreen(Screen):
    """Screen for creating and editing creature stat blocks."""

    def __init__(
        self,
        screen_width: int,
        screen_height: int,
        creature_path: Path | None = None,
    ) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.app: App | None = None

        # Tab state
        self.active_tab = 0
        self.tab_hovered: int | None = None

        # Creature mode
        self.creature_mode = CreatureMode.CHARACTER

        # Form data — plain dicts for flexibility during editing
        self.form_data: dict = self._default_form_data()
        self.actions_data: dict[str, list[dict]] = {
            "actions": [],
            "bonus_actions": [],
            "reactions": [],
            "legendary_actions": [],
            "lair_actions": [],
        }
        self.features_data: list[dict] = []
        self.special_abilities_data: list[dict] = []
        self.equipment_data: list[dict] = []

        # Source path for re-saving
        self._source_path: Path | None = creature_path

        # Status message
        self.status_message = ""
        self.status_timer = 0

        # Hover states for top bar buttons
        self.back_hovered = False
        self.save_hovered = False

        # Scroll state per tab
        self.tab_scroll: dict[int, int] = {i: 0 for i in range(len(TAB_NAMES))}

        # Build layout rects
        self._build_ui_rects()

        # Initialize tab renderers (imported lazily to avoid circular deps)
        self._init_tabs()

        # Load existing creature if path provided
        if creature_path is not None:
            self._load_creature(creature_path)

    def _default_form_data(self) -> dict:
        """Return default values for all form fields."""
        return {
            # Shared fields
            "name": "",
            "size": "medium",
            "creature_type": "humanoid",
            "alignment": "",
            # Ability scores
            "strength": 10,
            "dexterity": 10,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 10,
            "charisma": 10,
            # Combat
            "armor_class": 10,
            "max_hit_points": 10,
            "hit_dice": "",
            "proficiency_bonus": 2,
            "speed_walk": 30,
            "speed_fly": 0,
            "speed_swim": 0,
            "speed_climb": 0,
            "speed_burrow": 0,
            # Saves
            "save_str": False,
            "save_dex": False,
            "save_con": False,
            "save_int": False,
            "save_wis": False,
            "save_cha": False,
            # Defense lists
            "damage_resistances": [],
            "damage_immunities": [],
            "damage_vulnerabilities": [],
            "condition_immunities": [],
            # Senses
            "senses": {},
            "passive_perception": 10,
            # Character-specific
            "character_class": "",
            "subclass": "",
            "level": 1,
            "race": "Human",
            "background": "",
            "skill_proficiencies": [],
            "skill_expertise": [],
            "equipped_armor": "",
            "equipped_shield": False,
            "equipped_weapons": [],
            "spellcasting_ability": "",
            "spell_slots": {},
            "spells_known": [],
            "spells_prepared": [],
            "class_resources": {},
            "feats": [],
            # Monster-specific
            "challenge_rating": 1.0,
            "experience_points": 200,
            "legendary_action_count": 0,
            "source_book": "",
            "source_page": 0,
            # Token / AI
            "token_color": "#808080",
            "token_image": "",
            "is_player_controlled": True,
            "ai_profile": "",
        }

    def _build_ui_rects(self) -> None:
        """Compute all layout rectangles."""
        sw, sh = self.screen_width, self.screen_height

        self.top_bar_rect = pygame.Rect(0, 0, sw, TOP_BAR_HEIGHT)
        self.left_panel_rect = pygame.Rect(
            0, TOP_BAR_HEIGHT, LEFT_PANEL_WIDTH,
            sh - TOP_BAR_HEIGHT - STATUS_BAR_HEIGHT,
        )
        self.content_rect = pygame.Rect(
            LEFT_PANEL_WIDTH, TOP_BAR_HEIGHT,
            sw - LEFT_PANEL_WIDTH,
            sh - TOP_BAR_HEIGHT - STATUS_BAR_HEIGHT,
        )
        self.status_bar_rect = pygame.Rect(
            0, sh - STATUS_BAR_HEIGHT, sw, STATUS_BAR_HEIGHT,
        )

        # Top bar buttons
        self.back_btn = pygame.Rect(10, 6, 80, 28)
        self.save_btn = pygame.Rect(sw - 100, 6, 80, 28)

        # Tab buttons in left panel
        tab_w = LEFT_PANEL_WIDTH - 20
        tab_h = 36
        tab_gap = 4
        tab_start_y = TOP_BAR_HEIGHT + 10
        self.tab_rects: list[pygame.Rect] = []
        for i in range(len(TAB_NAMES)):
            self.tab_rects.append(pygame.Rect(
                10, tab_start_y + i * (tab_h + tab_gap),
                tab_w, tab_h,
            ))

    def _init_tabs(self) -> None:
        """Initialize tab renderer instances."""
        from arena.gui.screens.creature_builder_tabs.identity_tab import IdentityTab
        from arena.gui.screens.creature_builder_tabs.abilities_tab import AbilitiesTab
        from arena.gui.screens.creature_builder_tabs.combat_tab import CombatTab
        from arena.gui.screens.creature_builder_tabs.actions_tab import ActionsTab
        from arena.gui.screens.creature_builder_tabs.features_tab import FeaturesTab
        from arena.gui.screens.creature_builder_tabs.equipment_tab import EquipmentTab
        from arena.gui.screens.creature_builder_tabs.token_ai_tab import TokenAITab

        self.tabs = [
            IdentityTab(self),
            AbilitiesTab(self),
            CombatTab(self),
            ActionsTab(self),
            FeaturesTab(self),
            EquipmentTab(self),
            TokenAITab(self),
        ]

    def on_enter(self, app: App) -> None:
        self.app = app

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> None:
        # Check if any dropdown is open — if so, it gets priority
        active_tab = self.tabs[self.active_tab]
        if hasattr(active_tab, "has_open_dropdown") and active_tab.has_open_dropdown():
            if active_tab.handle_event(event):
                return

        # ESC handling
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            # Let active tab handle ESC first (e.g., close text input)
            if hasattr(active_tab, "handle_escape") and active_tab.handle_escape():
                return
            self.app.go_to_main_menu()
            return

        # Mouse motion — update hovers
        if event.type == pygame.MOUSEMOTION:
            pos = event.pos
            self.back_hovered = self.back_btn.collidepoint(pos)
            self.save_hovered = self.save_btn.collidepoint(pos)
            self.tab_hovered = None
            for i, rect in enumerate(self.tab_rects):
                if rect.collidepoint(pos):
                    self.tab_hovered = i
                    break
            # Forward to active tab
            if self.content_rect.collidepoint(pos):
                active_tab.handle_event(event)
            return

        # Mouse wheel
        if event.type == pygame.MOUSEWHEEL:
            if self.content_rect.collidepoint(pygame.mouse.get_pos()):
                self.tab_scroll[self.active_tab] = max(
                    0, self.tab_scroll[self.active_tab] - event.y * 30,
                )
                active_tab.handle_event(event)
            return

        # Mouse button up — clicks
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            pos = event.pos

            # Top bar
            if self.back_btn.collidepoint(pos):
                self.app.go_to_main_menu()
                return
            if self.save_btn.collidepoint(pos):
                self._save_creature()
                return

            # Tab buttons
            for i, rect in enumerate(self.tab_rects):
                if rect.collidepoint(pos):
                    self.active_tab = i
                    return

            # Content area
            if self.content_rect.collidepoint(pos):
                active_tab.handle_event(event)
            return

        # Mouse button down — forward to tab for text input focus
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.content_rect.collidepoint(event.pos):
                active_tab.handle_event(event)
            return

        # Keyboard — forward to active tab
        if event.type == pygame.KEYDOWN:
            active_tab.handle_event(event)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self) -> None:
        if self.status_timer > 0:
            self.status_timer -= 1
            if self.status_timer <= 0:
                self.status_message = ""

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        # Shared background slideshow (kept alive in App)
        self.app.render_background(surface)

        self._render_top_bar(surface)
        self._render_left_panel(surface)
        self._render_content_area(surface)
        self._render_status_bar(surface)

        # Render dropdown overlays last (on top of everything)
        active_tab = self.tabs[self.active_tab]
        if hasattr(active_tab, "render_overlays"):
            active_tab.render_overlays(surface)

    def _render_top_bar(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(
            surface, parse_color(COLORS["bg_medium"]), self.top_bar_rect,
        )

        # Back button (quit/back style)
        draw_image_button(
            surface, self.back_btn, "Back",
            is_hovered=self.back_hovered, is_quit=True, font_size=14,
        )

        # Title
        draw_text_centered(
            surface, "CREATURE BUILDER",
            (self.screen_width // 2, TOP_BAR_HEIGHT // 2),
            parse_color(COLORS["text_gold"]), font_size=22,
        )

        # Save button (standard style)
        draw_image_button(
            surface, self.save_btn, "Save",
            is_hovered=self.save_hovered, font_size=14,
        )

    def _render_left_panel(self, surface: pygame.Surface) -> None:
        if not draw_tray_background(surface, self.left_panel_rect, variant="standard"):
            pygame.draw.rect(
                surface, parse_color(COLORS["bg_medium"]), self.left_panel_rect,
            )

        for i, (name, rect) in enumerate(zip(TAB_NAMES, self.tab_rects)):
            active = i == self.active_tab
            hovered = i == self.tab_hovered
            if active:
                color = parse_color(COLORS["button_active"])
            elif hovered:
                color = parse_color(COLORS["button_hover"])
            else:
                color = parse_color(COLORS["button_normal"])

            pygame.draw.rect(surface, color, rect, border_radius=4)
            pygame.draw.rect(
                surface, parse_color(COLORS["hex_border"]),
                rect, 1, border_radius=4,
            )
            draw_text_centered(
                surface, name, rect.center,
                parse_color(COLORS["text_primary"]), font_size=15,
            )

    def _render_content_area(self, surface: pygame.Surface) -> None:
        # Clip to content area
        old_clip = surface.get_clip()
        surface.set_clip(self.content_rect)

        active_tab = self.tabs[self.active_tab]
        active_tab.render(surface)

        surface.set_clip(old_clip)

    def _render_status_bar(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(
            surface, parse_color(COLORS["bg_medium"]), self.status_bar_rect,
        )

        text = self.status_message or self._get_default_status()
        font = get_font(14)
        txt = font.render(text, True, parse_color(COLORS["text_secondary"]))
        surface.blit(txt, (12, self.status_bar_rect.y + 12))

    def _get_default_status(self) -> str:
        mode_name = self.creature_mode.name.title()
        name = self.form_data["name"] or "unnamed"
        if self._source_path:
            return f"Editing {name} ({mode_name})"
        return f"New {mode_name}"

    # ------------------------------------------------------------------
    # Save / Load
    # ------------------------------------------------------------------

    def _build_creature_dict(self) -> dict:
        """Convert form state into a dict suitable for Pydantic model_validate."""
        d = self.form_data
        result: dict = {
            "name": d["name"] or "Unnamed Creature",
            "size": d["size"],
            "creature_type": d["creature_type"],
            "alignment": d["alignment"] or None,
            "ability_scores": {
                "strength": d["strength"],
                "dexterity": d["dexterity"],
                "constitution": d["constitution"],
                "intelligence": d["intelligence"],
                "wisdom": d["wisdom"],
                "charisma": d["charisma"],
            },
            "armor_class": d["armor_class"],
            "max_hit_points": d["max_hit_points"],
            "hit_dice": d["hit_dice"] or None,
            "proficiency_bonus": d["proficiency_bonus"],
            "token_color": d["token_color"],
            "token_image": d["token_image"] or None,
            "is_player_controlled": d["is_player_controlled"],
            "ai_profile": d["ai_profile"] or None,
        }

        # Speed
        speed = {}
        for key in ("walk", "fly", "swim", "climb", "burrow"):
            val = d[f"speed_{key}"]
            if val > 0:
                speed[key] = val
        result["speed"] = speed or {"walk": 0}

        # Saving throw proficiencies
        save_profs = []
        for ability in ("str", "dex", "con", "int", "wis", "cha"):
            if d[f"save_{ability}"]:
                full_name = {
                    "str": "strength", "dex": "dexterity",
                    "con": "constitution", "int": "intelligence",
                    "wis": "wisdom", "cha": "charisma",
                }[ability]
                save_profs.append(full_name)
        result["saving_throw_proficiencies"] = save_profs

        # Defense lists
        result["damage_resistances"] = list(d["damage_resistances"])
        result["damage_immunities"] = list(d["damage_immunities"])
        result["damage_vulnerabilities"] = list(d["damage_vulnerabilities"])
        result["condition_immunities"] = list(d["condition_immunities"])

        # Senses
        result["senses"] = dict(d["senses"])
        if d["passive_perception"]:
            result["passive_perception"] = d["passive_perception"]

        # Actions
        result["actions"] = list(self.actions_data.get("actions", []))
        result["bonus_actions"] = list(self.actions_data.get("bonus_actions", []))
        result["reactions"] = list(self.actions_data.get("reactions", []))

        # Equipment (shared across all creature types)
        result["equipment"] = list(self.equipment_data)

        if self.creature_mode == CreatureMode.CHARACTER:
            result["character_class"] = d["character_class"] or "Fighter"
            result["subclass"] = d["subclass"] or None
            result["level"] = d["level"]
            result["race"] = d["race"] or "Human"
            result["background"] = d["background"] or None
            result["skill_proficiencies"] = list(d["skill_proficiencies"])
            result["skill_expertise"] = list(d["skill_expertise"])
            result["equipped_armor"] = d["equipped_armor"] or None
            result["equipped_shield"] = d["equipped_shield"]
            result["equipped_weapons"] = list(d["equipped_weapons"])
            result["features"] = list(self.features_data)
            result["spellcasting_ability"] = d["spellcasting_ability"] or None
            result["spell_slots"] = dict(d["spell_slots"])
            result["spells_known"] = list(d["spells_known"])
            result["spells_prepared"] = list(d["spells_prepared"])
            result["class_resources"] = dict(d["class_resources"])
            result["feats"] = list(d["feats"])
        else:
            # Monster or NPC
            result["challenge_rating"] = d["challenge_rating"]
            result["experience_points"] = d["experience_points"]
            result["legendary_action_count"] = d["legendary_action_count"]
            result["legendary_actions"] = list(
                self.actions_data.get("legendary_actions", []),
            )
            result["lair_actions"] = list(
                self.actions_data.get("lair_actions", []),
            )
            result["special_abilities"] = list(self.special_abilities_data)
            result["source_book"] = d["source_book"] or None
            result["source_page"] = d["source_page"] or None
            if self.creature_mode == CreatureMode.NPC:
                result["is_player_controlled"] = True
            else:
                result["is_player_controlled"] = False

        return result

    def _slugify(self, name: str) -> str:
        slug = name.lower().strip()
        slug = re.sub(r"[^a-z0-9\s_-]", "", slug)
        slug = re.sub(r"[\s-]+", "_", slug)
        return slug or "creature"

    def _save_creature(self) -> None:
        """Build a Pydantic model from form data and save to JSON."""
        data = self._build_creature_dict()

        try:
            if self.creature_mode == CreatureMode.CHARACTER:
                from arena.models.character import PlayerCharacter
                creature = PlayerCharacter.model_validate(data)
                slug = self._slugify(creature.name)
                path = self._source_path or Path("data") / "characters" / f"{slug}.json"
                save_character(creature, path)
            else:
                from arena.models.monster import Monster
                creature = Monster.model_validate(data)
                slug = self._slugify(creature.name)
                path = self._source_path or Path("data") / "monsters" / f"{slug}.json"
                save_monster(creature, path)

            self._source_path = path
            self.status_message = f"Saved to {path}"
            self.status_timer = 180
        except Exception as e:
            self.status_message = f"Save failed: {e}"
            self.status_timer = 240

    def _load_creature(self, path: Path) -> None:
        """Load an existing creature from a JSON file into form data."""
        try:
            raw = load_json(path)
        except Exception:
            self.status_message = "Failed to load file"
            self.status_timer = 150
            return

        # Detect type
        if "character_class" in raw:
            self.creature_mode = CreatureMode.CHARACTER
            try:
                creature = load_character(path)
            except Exception as e:
                self.status_message = f"Load error: {e}"
                self.status_timer = 180
                return
            self._populate_from_character(creature)
        else:
            try:
                creature = load_monster(path)
            except Exception as e:
                self.status_message = f"Load error: {e}"
                self.status_timer = 180
                return
            if creature.is_player_controlled:
                self.creature_mode = CreatureMode.NPC
            else:
                self.creature_mode = CreatureMode.MONSTER
            self._populate_from_monster(creature)

        self._source_path = path
        self.status_message = f"Loaded {creature.name}"
        self.status_timer = 150

        # Re-initialize tabs so they pick up new data
        self._init_tabs()

        # Sync equipment-generated actions (ensures consistency)
        from arena.gui.screens.creature_builder_tabs.equipment_actions import (
            sync_equipment_actions,
        )
        sync_equipment_actions(self.equipment_data, self.actions_data)

    def _populate_shared_fields(self, creature) -> None:
        """Fill form_data with fields from the Creature base class."""
        d = self.form_data
        d["name"] = creature.name
        d["size"] = creature.size.value
        d["creature_type"] = creature.creature_type.value
        d["alignment"] = creature.alignment or ""

        # Ability scores
        scores = creature.ability_scores
        d["strength"] = scores.strength
        d["dexterity"] = scores.dexterity
        d["constitution"] = scores.constitution
        d["intelligence"] = scores.intelligence
        d["wisdom"] = scores.wisdom
        d["charisma"] = scores.charisma

        d["armor_class"] = creature.armor_class
        d["max_hit_points"] = creature.max_hit_points
        d["hit_dice"] = creature.hit_dice or ""
        d["proficiency_bonus"] = creature.proficiency_bonus

        # Speed
        speed = creature.speed
        d["speed_walk"] = speed.get("walk", 0)
        d["speed_fly"] = speed.get("fly", 0)
        d["speed_swim"] = speed.get("swim", 0)
        d["speed_climb"] = speed.get("climb", 0)
        d["speed_burrow"] = speed.get("burrow", 0)

        # Saving throws
        profs = [s.lower() for s in creature.saving_throw_proficiencies]
        d["save_str"] = "strength" in profs
        d["save_dex"] = "dexterity" in profs
        d["save_con"] = "constitution" in profs
        d["save_int"] = "intelligence" in profs
        d["save_wis"] = "wisdom" in profs
        d["save_cha"] = "charisma" in profs

        # Defense lists
        d["damage_resistances"] = list(creature.damage_resistances)
        d["damage_immunities"] = list(creature.damage_immunities)
        d["damage_vulnerabilities"] = list(creature.damage_vulnerabilities)
        d["condition_immunities"] = list(creature.condition_immunities)

        # Senses
        d["senses"] = dict(creature.senses)
        d["passive_perception"] = creature.passive_perception or 10

        # Token / AI
        d["token_color"] = creature.token_color
        d["token_image"] = creature.token_image or ""
        d["is_player_controlled"] = creature.is_player_controlled
        d["ai_profile"] = creature.ai_profile or ""

        # Equipment — convert to dicts
        self.equipment_data = [
            item.model_dump(mode="json") for item in creature.equipment
        ]

        # Actions — convert to dicts
        self.actions_data["actions"] = [
            a.model_dump(mode="json") for a in creature.actions
        ]
        self.actions_data["bonus_actions"] = [
            a.model_dump(mode="json") for a in creature.bonus_actions
        ]
        self.actions_data["reactions"] = [
            a.model_dump(mode="json") for a in creature.reactions
        ]

    def _populate_from_character(self, char) -> None:
        """Fill form_data from a PlayerCharacter."""
        self._populate_shared_fields(char)
        d = self.form_data
        d["character_class"] = char.character_class
        d["subclass"] = char.subclass or ""
        d["level"] = char.level
        d["race"] = char.race
        d["background"] = char.background or ""
        d["skill_proficiencies"] = list(char.skill_proficiencies)
        d["skill_expertise"] = list(char.skill_expertise)
        d["equipped_armor"] = char.equipped_armor or ""
        d["equipped_shield"] = char.equipped_shield
        d["equipped_weapons"] = list(char.equipped_weapons)
        d["spellcasting_ability"] = char.spellcasting_ability or ""
        d["spell_slots"] = dict(char.spell_slots)
        d["spells_known"] = list(char.spells_known)
        d["spells_prepared"] = list(char.spells_prepared)
        d["class_resources"] = dict(char.class_resources)
        d["feats"] = [f.model_dump(mode="json") for f in char.feats]
        self.features_data = [
            f.model_dump(mode="json") for f in char.features
        ]

    def _populate_from_monster(self, mon) -> None:
        """Fill form_data from a Monster."""
        self._populate_shared_fields(mon)
        d = self.form_data
        d["challenge_rating"] = mon.challenge_rating
        d["experience_points"] = mon.experience_points
        d["legendary_action_count"] = mon.legendary_action_count
        d["source_book"] = mon.source_book or ""
        d["source_page"] = mon.source_page or 0
        self.actions_data["legendary_actions"] = [
            a.model_dump(mode="json") for a in mon.legendary_actions
        ]
        self.actions_data["lair_actions"] = [
            a.model_dump(mode="json") for a in mon.lair_actions
        ]
        self.special_abilities_data = [
            f.model_dump(mode="json") for f in mon.special_abilities
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_content_origin(self) -> tuple[int, int]:
        """Get the top-left corner of the usable content area."""
        return (
            self.content_rect.x + CONTENT_PADDING,
            self.content_rect.y + CONTENT_PADDING,
        )

    def get_scroll_y(self) -> int:
        """Get the current scroll offset for the active tab."""
        return self.tab_scroll.get(self.active_tab, 0)

    def _draw_button(
        self, surface: pygame.Surface, rect: pygame.Rect,
        label: str, hovered: bool,
    ) -> None:
        color = (
            parse_color(COLORS["button_hover"]) if hovered
            else parse_color(COLORS["button_normal"])
        )
        pygame.draw.rect(surface, color, rect, border_radius=4)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            rect, 1, border_radius=4,
        )
        draw_text_centered(
            surface, label, rect.center,
            parse_color(COLORS["text_primary"]), font_size=14,
        )
