"""Tests for the spell list popup."""

import pytest
import pygame

from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.abilities import AbilityScores
from arena.models.character import Creature, PlayerCharacter
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


def _make_upcast_spell():
    """A 1st-level spell with upcast scaling (Magic Missile style)."""
    return Action(
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
        upcast_damage_dice="1d4",
    )


def _make_slotted_wizard(slots: dict[str, int]):
    """A PlayerCharacter whose class_resources hold the given slot counts."""
    spell_slots = {
        int(key.split("_")[-1]): count for key, count in slots.items()
    }
    return PlayerCharacter(
        name="TestWizard",
        max_hit_points=20,
        character_class="Wizard",
        ability_scores=AbilityScores(intelligence=18),
        proficiency_bonus=3,
        speed={"walk": 30},
        is_player_controlled=True,
        actions=[],
        spell_slots=spell_slots,
        class_resources=dict(slots),  # explicit counts win over the sync
    )


class TestSpellPopupUpcast:
    """Upcast level selection via the popup's up/down controls."""

    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        pygame.display.set_mode((1, 1))
        yield
        pygame.quit()

    def _popup(self, slots=None):
        slots = slots if slots is not None else {
            "spell_slot_1": 2, "spell_slot_2": 1, "spell_slot_3": 1,
        }
        creature = _make_slotted_wizard(slots)
        return SpellPopup(
            spells=[_make_upcast_spell()], creature=creature, action_used=False,
        )

    def test_defaults_to_base_level(self):
        popup = self._popup()
        spell = popup._entries[1].action
        assert popup.chosen_level(spell) == 1

    def test_step_up_walks_available_slots(self):
        popup = self._popup()
        spell = popup._entries[1].action
        popup._step_cast_level(spell, +1)
        assert popup.chosen_level(spell) == 2
        popup._step_cast_level(spell, +1)
        assert popup.chosen_level(spell) == 3
        popup._step_cast_level(spell, +1)  # clamped at the top
        assert popup.chosen_level(spell) == 3

    def test_step_down_never_goes_below_base(self):
        popup = self._popup()
        spell = popup._entries[1].action
        popup._step_cast_level(spell, +1)
        popup._step_cast_level(spell, -1)
        assert popup.chosen_level(spell) == 1
        popup._step_cast_level(spell, -1)  # clamped at base
        assert popup.chosen_level(spell) == 1

    def test_step_skips_empty_slot_levels(self):
        # No 2nd-level slots left: up from base jumps straight to 3rd
        popup = self._popup({"spell_slot_1": 1, "spell_slot_2": 0,
                             "spell_slot_3": 1})
        spell = popup._entries[1].action
        popup._step_cast_level(spell, +1)
        assert popup.chosen_level(spell) == 3

    def test_click_returns_level_suffix_when_upcast(self):
        popup = self._popup()
        popup.reposition((400, 300), 100)
        spell = popup._entries[1].action
        popup._step_cast_level(spell, +1)

        entry_y = popup._entry_y(1)
        click = pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1,
            pos=(popup.rect.x + 40, entry_y + 4),
        )
        assert popup.handle_event(click) == "action:Magic Missile@2"

    def test_click_returns_plain_command_at_base(self):
        popup = self._popup()
        popup.reposition((400, 300), 100)
        entry_y = popup._entry_y(1)
        click = pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1,
            pos=(popup.rect.x + 40, entry_y + 4),
        )
        assert popup.handle_event(click) == "action:Magic Missile"

    def test_arrow_click_adjusts_without_casting(self):
        popup = self._popup()
        popup.reposition((400, 300), 100)
        spell = popup._entries[1].action
        zone = popup._upcast_zone(1)
        assert zone is not None

        up_click = pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1,
            pos=(zone.centerx, zone.y + 3),
        )
        assert popup.handle_event(up_click) is None   # no cast
        assert popup.chosen_level(spell) == 2

        down_click = pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1,
            pos=(zone.centerx, zone.bottom - 3),
        )
        assert popup.handle_event(down_click) is None
        assert popup.chosen_level(spell) == 1

    def test_no_controls_without_upcast_scaling(self):
        # Shield has no upcast dice: no upcast zone even with higher slots
        creature = _make_slotted_wizard({"spell_slot_1": 1, "spell_slot_2": 1})
        shield = Action(
            name="Shield",
            description="Invisible barrier of magical force",
            action_type=ActionType.REACTION,
            resource_cost={"spell_slot_1": 1},
        )
        popup = SpellPopup(
            spells=[shield], creature=creature, action_used=False,
        )
        popup.reposition((400, 300), 100)
        assert popup._upcast_zone(1) is None
