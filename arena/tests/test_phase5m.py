"""Tests for Phase 5m: GUI Integration.

Tests the logic underlying the GUI components:
- Action bar button generation and routing
- Combat log event color mapping
- Condition display data completeness
- Standard action / bonus action / end turn button types
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import pygame

from arena.combat.events import CombatEventType
from arena.combat.manager import CombatManager
from arena.combat.conditions import apply_condition, has_condition
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.models.encounter import Encounter, CombatantEntry
from arena.util.constants import COLORS, CONDITION_DISPLAY


# ── Helpers ───────────────────────────────────────────────────────────

def _make_creature(name, hp=20, is_player=True, light_weapons=False):
    props = ["light", "finesse"] if light_weapons else []
    return Creature(
        name=name,
        max_hit_points=hp,
        ability_scores=AbilityScores(strength=10, dexterity=14),
        proficiency_bonus=2,
        speed={"walk": 30},
        is_player_controlled=is_player,
        actions=[
            Action(
                name="Shortsword",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Shortsword",
                    attack_type="melee_weapon",
                    ability="dexterity",
                    reach=5,
                    damage=[
                        DamageRoll(dice="1d6", damage_type=DamageType.PIERCING,
                                   ability_modifier="dexterity")
                    ],
                    properties=props,
                ),
            )
        ],
    )


def _setup_combat(light_weapons=False):
    encounter = Encounter(
        name="Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="fighter",
                creature_data=_make_creature("Fighter", is_player=True,
                                              light_weapons=light_weapons),
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="goblin",
                creature_data=_make_creature("Goblin", is_player=False,
                                              light_weapons=light_weapons),
                team="enemy",
                starting_position=(3, 2),
            ),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    cm.roll_initiative()
    cm.begin_combat()
    return cm


def _skip_to_player(cm):
    for _ in range(20):
        active = cm.active_combatant
        if active and active.creature.is_player_controlled:
            return active
        cm.end_turn()
    return None


# ── Event Color Mapping Tests ────────────────────────────────────────

class TestEventColorMapping:
    """Verify that all event types have color mappings in the log panel."""

    def test_all_event_types_have_color_mapping(self):
        from arena.gui.panels.log import EVENT_COLORS
        for event_type in CombatEventType:
            assert event_type in EVENT_COLORS, (
                f"CombatEventType.{event_type.name} has no color mapping in EVENT_COLORS"
            )

    def test_all_mapped_colors_exist_in_palette(self):
        from arena.gui.panels.log import EVENT_COLORS
        for event_type, color_key in EVENT_COLORS.items():
            assert color_key in COLORS, (
                f"Color key '{color_key}' for {event_type.name} not in COLORS"
            )

    def test_new_event_types_are_mapped(self):
        from arena.gui.panels.log import EVENT_COLORS
        new_types = [
            CombatEventType.SAVING_THROW,
            CombatEventType.CONDITION_APPLIED,
            CombatEventType.CONDITION_REMOVED,
            CombatEventType.DEATH_SAVE,
            CombatEventType.HEALING,
            CombatEventType.REACTION,
        ]
        for et in new_types:
            assert et in EVENT_COLORS


# ── Condition Display Tests ──────────────────────────────────────────

class TestConditionDisplay:
    """Verify condition display metadata completeness."""

    def test_all_conditions_have_display_entry(self):
        for cond in Condition:
            assert cond.value in CONDITION_DISPLAY, (
                f"Condition '{cond.value}' has no entry in CONDITION_DISPLAY"
            )

    def test_display_abbreviations_are_two_chars(self):
        for cond_name, (abbrev, _) in CONDITION_DISPLAY.items():
            assert len(abbrev) == 2, (
                f"Abbreviation for '{cond_name}' is '{abbrev}' (expected 2 chars)"
            )

    def test_display_colors_exist_in_palette(self):
        for cond_name, (_, color_key) in CONDITION_DISPLAY.items():
            assert color_key in COLORS, (
                f"Color key '{color_key}' for condition '{cond_name}' not in COLORS"
            )


# ── Action Bar Logic Tests ───────────────────────────────────────────

class TestActionBarLogic:
    """Test action bar button building and routing logic."""

    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        pygame.display.set_mode((1, 1))
        yield
        pygame.quit()

    def test_action_bar_builds_attack_buttons(self):
        from arena.gui.panels.action_bar import ActionBar
        cm = _setup_combat()
        _skip_to_player(cm)

        bar = ActionBar(pygame.Rect(0, 0, 800, 52))
        bar.set_combat(cm)
        bar.rebuild_buttons()

        action_btns = [b for b in bar.buttons if b.btn_type == "action"]
        assert len(action_btns) >= 1
        assert action_btns[0].label == "Shortsword"

    def test_action_bar_builds_standard_action_buttons(self):
        from arena.gui.panels.action_bar import ActionBar
        cm = _setup_combat()
        _skip_to_player(cm)

        bar = ActionBar(pygame.Rect(0, 0, 800, 52))
        bar.set_combat(cm)
        bar.rebuild_buttons()

        std_btns = [b for b in bar.buttons if b.btn_type == "standard"]
        std_labels = {b.label for b in std_btns}
        assert "Dash" in std_labels
        assert "Disengage" in std_labels
        assert "Dodge" in std_labels
        assert "Hide" in std_labels

    def test_action_bar_builds_end_turn_button(self):
        from arena.gui.panels.action_bar import ActionBar
        cm = _setup_combat()
        _skip_to_player(cm)

        bar = ActionBar(pygame.Rect(0, 0, 800, 52))
        bar.set_combat(cm)
        bar.rebuild_buttons()

        end_btns = [b for b in bar.buttons if b.btn_type == "end_turn"]
        assert len(end_btns) == 1
        assert end_btns[0].label == "End Turn"

    def test_action_bar_twf_button_when_eligible(self):
        from arena.gui.panels.action_bar import ActionBar
        cm = _setup_combat(light_weapons=True)
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        # Need to use action first for TWF to be available
        cm.turn_resources.has_used_action = True

        bar = ActionBar(pygame.Rect(0, 0, 800, 52))
        bar.set_combat(cm)
        bar.rebuild_buttons()

        bonus_btns = [b for b in bar.buttons if b.btn_type == "bonus"]
        assert len(bonus_btns) == 1
        assert bonus_btns[0].label == "Off-Hand"

    def test_action_bar_no_twf_without_light_weapons(self):
        from arena.gui.panels.action_bar import ActionBar
        cm = _setup_combat(light_weapons=False)
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        cm.turn_resources.has_used_action = True

        bar = ActionBar(pygame.Rect(0, 0, 800, 52))
        bar.set_combat(cm)
        bar.rebuild_buttons()

        bonus_btns = [b for b in bar.buttons if b.btn_type == "bonus"]
        assert len(bonus_btns) == 0

    def test_action_buttons_disabled_after_action_used(self):
        from arena.gui.panels.action_bar import ActionBar
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        cm.turn_resources.has_used_action = True

        bar = ActionBar(pygame.Rect(0, 0, 800, 52))
        bar.set_combat(cm)
        bar.rebuild_buttons()

        action_btns = [b for b in bar.buttons if b.btn_type == "action"]
        for btn in action_btns:
            assert btn.is_disabled is True

        std_btns = [b for b in bar.buttons if b.btn_type == "standard"]
        for btn in std_btns:
            assert btn.is_disabled is True


# ── Combat Screen Routing Tests ──────────────────────────────────────

class TestCombatScreenRouting:
    """Test that combat screen correctly routes action bar results."""

    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        pygame.display.set_mode((1, 1))
        yield
        pygame.quit()

    def test_standard_action_routing(self):
        """Standard actions route through execute_standard_action."""
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        # Execute dodge via standard action
        event = cm.execute_standard_action("dodge")
        assert event is not None
        assert has_condition(active.creature, Condition.DODGING)

    def test_end_turn_advances_turn(self):
        """End turn should advance to next combatant."""
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        old_id = active.creature_id
        cm.end_turn()
        new_active = cm.active_combatant
        assert new_active is not None
        assert new_active.creature_id != old_id
