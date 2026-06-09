"""Tests for the spell list popup."""

import pytest
import pygame

from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.abilities import AbilityScores
from arena.models.character import Creature
from arena.gui.spell_popup import SpellPopup, _spell_level


def _make_spells():
    """Create a set of leveled spells for testing."""
    return [
        Action(
            name="Magic Missile",
            description="Three darts of magical force",
            action_type=ActionType.ACTION,
            attack=Attack(
                name="Magic Missile",
                attack_type="ranged_spell",
                ability="intelligence",
                range_normal=120,
                damage=[
                    DamageRoll(dice="1d4", damage_type=DamageType.FORCE, bonus=1),
                ],
            ),
            resource_cost={"spell_slot_1": 1},
        ),
        Action(
            name="Shield",
            description="Invisible barrier of magical force",
            action_type=ActionType.REACTION,
            resource_cost={"spell_slot_1": 1},
        ),
        Action(
            name="Scorching Ray",
            description="Three rays of fire",
            action_type=ActionType.ACTION,
            attack=Attack(
                name="Scorching Ray",
                attack_type="ranged_spell",
                ability="intelligence",
                range_normal=120,
                damage=[
                    DamageRoll(dice="2d6", damage_type=DamageType.FIRE),
                ],
            ),
            resource_cost={"spell_slot_2": 1},
        ),
        Action(
            name="Fireball",
            description="A bright streak flashes...",
            action_type=ActionType.ACTION,
            range=150,
            resource_cost={"spell_slot_3": 1},
        ),
    ]


def _make_wizard_creature():
    return Creature(
        name="TestWizard",
        max_hit_points=20,
        ability_scores=AbilityScores(intelligence=18),
        proficiency_bonus=3,
        speed={"walk": 30},
        is_player_controlled=True,
        actions=[],
    )


class TestSpellLevel:
    """Test spell level extraction from resource_cost."""

    def test_level_1_spell(self):
        action = Action(
            name="Test", description="", action_type=ActionType.ACTION,
            resource_cost={"spell_slot_1": 1},
        )
        assert _spell_level(action) == 1

    def test_level_3_spell(self):
        action = Action(
            name="Test", description="", action_type=ActionType.ACTION,
            resource_cost={"spell_slot_3": 1},
        )
        assert _spell_level(action) == 3

    def test_no_spell_slot(self):
        action = Action(
            name="Test", description="", action_type=ActionType.ACTION,
            resource_cost={},
        )
        assert _spell_level(action) == 0


class TestSpellPopup:
    """Test the spell popup panel."""

    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        pygame.display.set_mode((1, 1))
        yield
        pygame.quit()

    def test_spells_grouped_by_level(self):
        spells = _make_spells()
        creature = _make_wizard_creature()
        popup = SpellPopup(
            spells=spells, creature=creature, action_used=False,
        )

        # Check entries have headers for each spell level
        header_levels = [e.level for e in popup._entries if e.is_header]
        assert 1 in header_levels
        assert 2 in header_levels
        assert 3 in header_levels

    def test_spell_entries_under_correct_headers(self):
        spells = _make_spells()
        creature = _make_wizard_creature()
        popup = SpellPopup(
            spells=spells, creature=creature, action_used=False,
        )

        # Group entries by level
        current_level = 0
        for entry in popup._entries:
            if entry.is_header:
                current_level = entry.level
            else:
                assert entry.level == current_level

    def test_popup_creation(self):
        spells = _make_spells()
        creature = _make_wizard_creature()
        popup = SpellPopup(
            spells=spells, creature=creature, action_used=False,
        )
        assert popup.rect.width == SpellPopup.WIDTH
        assert popup.hovered_index is None

    def test_reposition_right_side(self):
        spells = _make_spells()
        creature = _make_wizard_creature()
        popup = SpellPopup(
            spells=spells, creature=creature, action_used=False,
            screen_width=1280, screen_height=720,
        )
        popup.reposition((400, 300), 100)
        assert popup.rect.x > 400

    def test_reposition_flips_left_near_edge(self):
        spells = _make_spells()
        creature = _make_wizard_creature()
        popup = SpellPopup(
            spells=spells, creature=creature, action_used=False,
            screen_width=1280, screen_height=720,
        )
        popup.reposition((1200, 300), 100)
        assert popup.rect.x < 1200

    def test_action_used_flag(self):
        spells = _make_spells()
        creature = _make_wizard_creature()
        popup = SpellPopup(
            spells=spells, creature=creature, action_used=True,
        )
        assert popup.action_used is True

    def test_empty_spell_list(self):
        creature = _make_wizard_creature()
        popup = SpellPopup(
            spells=[], creature=creature, action_used=False,
        )
        assert len(popup._entries) == 0

    def test_entry_count(self):
        """4 spells across 3 levels = 3 headers + 4 spell entries = 7 entries."""
        spells = _make_spells()
        creature = _make_wizard_creature()
        popup = SpellPopup(
            spells=spells, creature=creature, action_used=False,
        )
        headers = [e for e in popup._entries if e.is_header]
        spell_entries = [e for e in popup._entries if not e.is_header]
        assert len(headers) == 3
        assert len(spell_entries) == 4
