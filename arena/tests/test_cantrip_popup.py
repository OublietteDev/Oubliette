"""Tests for the cantrip popup."""

import pytest
import pygame

from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.abilities import AbilityScores
from arena.models.character import Creature
from arena.gui.cantrip_popup import CantripPopup


def _make_cantrips():
    """Create a set of cantrips for testing."""
    return [
        Action(
            name="Fire Bolt",
            description="Ranged spell attack cantrip",
            action_type=ActionType.ACTION,
            attack=Attack(
                name="Fire Bolt",
                attack_type="ranged_spell",
                ability="intelligence",
                range_normal=120,
                damage=[
                    DamageRoll(dice="2d10", damage_type=DamageType.FIRE),
                ],
            ),
            resource_cost={},
        ),
        Action(
            name="Ray of Frost",
            description="Ranged spell attack cantrip",
            action_type=ActionType.ACTION,
            attack=Attack(
                name="Ray of Frost",
                attack_type="ranged_spell",
                ability="intelligence",
                range_normal=60,
                damage=[
                    DamageRoll(dice="2d8", damage_type=DamageType.COLD),
                ],
            ),
            resource_cost={},
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


class TestCantripPopup:
    """Test the cantrip popup panel."""

    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        pygame.display.set_mode((1, 1))
        yield
        pygame.quit()

    def test_popup_creation(self):
        cantrips = _make_cantrips()
        creature = _make_wizard_creature()
        popup = CantripPopup(
            cantrips=cantrips, creature=creature, action_used=False,
        )
        assert popup.rect.width == CantripPopup.WIDTH
        assert popup.hovered_index is None

    def test_all_cantrips_present(self):
        cantrips = _make_cantrips()
        creature = _make_wizard_creature()
        popup = CantripPopup(
            cantrips=cantrips, creature=creature, action_used=False,
        )
        assert len(popup.cantrips) == 2
        names = [c.name for c in popup.cantrips]
        assert "Fire Bolt" in names
        assert "Ray of Frost" in names

    def test_action_used_flag(self):
        cantrips = _make_cantrips()
        creature = _make_wizard_creature()
        popup = CantripPopup(
            cantrips=cantrips, creature=creature, action_used=True,
        )
        assert popup.action_used is True

    def test_reposition_right_side(self):
        cantrips = _make_cantrips()
        creature = _make_wizard_creature()
        popup = CantripPopup(
            cantrips=cantrips, creature=creature, action_used=False,
            screen_width=1280, screen_height=720,
        )
        popup.reposition((400, 300), 100)
        assert popup.rect.x > 400

    def test_reposition_flips_left_near_edge(self):
        cantrips = _make_cantrips()
        creature = _make_wizard_creature()
        popup = CantripPopup(
            cantrips=cantrips, creature=creature, action_used=False,
            screen_width=1280, screen_height=720,
        )
        popup.reposition((1200, 300), 100)
        assert popup.rect.x < 1200

    def test_entry_at_returns_correct_index(self):
        cantrips = _make_cantrips()
        creature = _make_wizard_creature()
        popup = CantripPopup(
            cantrips=cantrips, creature=creature, action_used=False,
        )
        popup.reposition((400, 300), 100)

        # Click on first entry area
        entry_y = popup.rect.y + popup.TITLE_HEIGHT + 5
        idx = popup._entry_at((popup.rect.x + 10, entry_y))
        assert idx == 0

    def test_entry_at_returns_none_outside(self):
        cantrips = _make_cantrips()
        creature = _make_wizard_creature()
        popup = CantripPopup(
            cantrips=cantrips, creature=creature, action_used=False,
        )
        popup.reposition((400, 300), 100)
        idx = popup._entry_at((0, 0))
        assert idx is None

    def test_empty_cantrip_list(self):
        creature = _make_wizard_creature()
        popup = CantripPopup(
            cantrips=[], creature=creature, action_used=False,
        )
        assert len(popup.cantrips) == 0

    def test_tooltip_has_cantrip_tag(self):
        """Cantrip tooltip should start with 'Cantrip • Action'."""
        cantrips = _make_cantrips()
        creature = _make_wizard_creature()
        popup = CantripPopup(
            cantrips=cantrips, creature=creature, action_used=False,
        )
        tooltip = popup._build_cantrip_tooltip(cantrips[0])
        assert tooltip[0] == "Cantrip \u2022 Action"

    def test_tooltip_has_attack_info(self):
        """Cantrip tooltip should contain 'to hit' info."""
        cantrips = _make_cantrips()
        creature = _make_wizard_creature()
        popup = CantripPopup(
            cantrips=cantrips, creature=creature, action_used=False,
        )
        tooltip = popup._build_cantrip_tooltip(cantrips[0])
        assert any("to hit" in line for line in tooltip)

    def test_tooltip_has_damage(self):
        """Cantrip tooltip should contain damage info."""
        cantrips = _make_cantrips()
        creature = _make_wizard_creature()
        popup = CantripPopup(
            cantrips=cantrips, creature=creature, action_used=False,
        )
        tooltip = popup._build_cantrip_tooltip(cantrips[0])
        assert any("fire" in line for line in tooltip)
