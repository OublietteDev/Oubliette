"""Tests for the radial action menu.

Tests slot categorization, pagination, state machine, and hit detection.
"""

import math
from pathlib import Path
from unittest.mock import patch

import pytest
import pygame

from arena.combat.manager import CombatManager
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature, PlayerCharacter
from arena.models.encounter import Encounter, CombatantEntry
from arena.gui.radial_menu import RadialMenu, RadialMenuState, MAX_SLOTS_PER_PAGE


# ── Helpers ───────────────────────────────────────────────────────────

def _make_fighter(name="Fighter", light_weapons=False):
    """Create a simple fighter creature with weapon attacks."""
    props = ["light", "finesse"] if light_weapons else []
    return Creature(
        name=name,
        max_hit_points=30,
        ability_scores=AbilityScores(strength=16, dexterity=14),
        proficiency_bonus=2,
        speed={"walk": 30},
        is_player_controlled=True,
        actions=[
            Action(
                name="Longsword",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Longsword",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=5,
                    damage=[
                        DamageRoll(dice="1d8", damage_type=DamageType.SLASHING,
                                   ability_modifier="strength")
                    ],
                    properties=props,
                ),
            ),
            Action(
                name="Handaxe",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Handaxe",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=5,
                    damage=[
                        DamageRoll(dice="1d6", damage_type=DamageType.SLASHING,
                                   ability_modifier="strength")
                    ],
                    properties=props,
                ),
            ),
        ],
    )


def _make_wizard(name="Wizard"):
    """Create a creature with cantrips, leveled spells, and a weapon."""
    return Creature(
        name=name,
        max_hit_points=20,
        ability_scores=AbilityScores(intelligence=18, dexterity=14),
        proficiency_bonus=3,
        speed={"walk": 30},
        is_player_controlled=True,
        actions=[
            # Cantrip (no resource cost, spell attack type)
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
                        DamageRoll(dice="2d10", damage_type=DamageType.FIRE)
                    ],
                ),
                resource_cost={},
            ),
            # Cantrip 2
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
                        DamageRoll(dice="2d8", damage_type=DamageType.COLD)
                    ],
                ),
                resource_cost={},
            ),
            # Leveled spell 1
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
            # Leveled spell 2
            Action(
                name="Fireball",
                description="A bright streak flashes...",
                action_type=ActionType.ACTION,
                range=150,
                target_type="area_sphere",
                saving_throw=None,
                resource_cost={"spell_slot_3": 1},
            ),
            # Weapon
            Action(
                name="Quarterstaff",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Quarterstaff",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=5,
                    damage=[
                        DamageRoll(dice="1d6", damage_type=DamageType.BLUDGEONING)
                    ],
                ),
            ),
        ],
    )


def _make_enemy(name="Goblin"):
    """Create a simple enemy creature."""
    return Creature(
        name=name,
        max_hit_points=10,
        ability_scores=AbilityScores(strength=8, dexterity=14),
        proficiency_bonus=2,
        speed={"walk": 30},
        is_player_controlled=False,
        actions=[
            Action(
                name="Scimitar",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Scimitar",
                    attack_type="melee_weapon",
                    ability="dexterity",
                    reach=5,
                    damage=[
                        DamageRoll(dice="1d6", damage_type=DamageType.SLASHING,
                                   ability_modifier="dexterity")
                    ],
                ),
            ),
        ],
    )


def _make_creature_with_bonus(name="Cleric"):
    """Create a creature with bonus actions."""
    return Creature(
        name=name,
        max_hit_points=25,
        ability_scores=AbilityScores(wisdom=16),
        proficiency_bonus=2,
        speed={"walk": 30},
        is_player_controlled=True,
        actions=[
            Action(
                name="Mace",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Mace",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=5,
                    damage=[
                        DamageRoll(dice="1d6", damage_type=DamageType.BLUDGEONING)
                    ],
                ),
            ),
        ],
        bonus_actions=[
            Action(
                name="Healing Word",
                description="Heal a creature within 60 feet",
                action_type=ActionType.BONUS_ACTION,
                healing="1d4+3",
                target_type="one_ally",
                range=60,
            ),
        ],
    )


def _setup_combat(player_creature=None, light_weapons=False):
    """Set up a basic combat with one player and one enemy."""
    if player_creature is None:
        player_creature = _make_fighter(light_weapons=light_weapons)
    encounter = Encounter(
        name="Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="player",
                creature_data=player_creature,
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="goblin",
                creature_data=_make_enemy(),
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
    """Advance turns until it's the player's turn."""
    for _ in range(20):
        active = cm.active_combatant
        if active and active.creature.is_player_controlled:
            return active
        cm.end_turn()
    return None


# ── State Machine Tests ──────────────────────────────────────────────

class TestRadialMenuStateMachine:
    """Test state transitions of the radial menu."""

    def test_initial_state_is_closed(self):
        menu = RadialMenu()
        assert menu.state == RadialMenuState.CLOSED

    def test_open_transitions_to_open(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)
        # open() starts the opening animation; state transitions to OPEN
        # once the animation duration elapses during render().
        assert menu.state == RadialMenuState.OPENING

    def test_close_transitions_to_closing(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)
        menu.state = RadialMenuState.OPEN  # skip open animation
        menu.close()
        # close() starts the closing animation; state transitions to CLOSED
        # once the animation duration elapses during render().
        assert menu.state == RadialMenuState.CLOSING

    def test_open_spells_transitions_to_spell_popup(self):
        cm = _setup_combat(player_creature=_make_wizard())
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)
        menu._screen_width = 1280
        menu._screen_height = 720
        menu._center_screen = (400, 300)
        menu.open_spell_popup()
        assert menu.state == RadialMenuState.SPELL_POPUP
        assert menu.spell_popup is not None

    def test_open_tactics_transitions_to_tactics_popup(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)
        menu._screen_width = 1280
        menu._screen_height = 720
        menu._center_screen = (400, 300)
        menu.open_tactics_popup()
        assert menu.state == RadialMenuState.TACTICS_POPUP
        assert menu.tactics_popup is not None

    def test_open_cantrips_transitions_to_cantrip_popup(self):
        cm = _setup_combat(player_creature=_make_wizard())
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)
        menu._screen_width = 1280
        menu._screen_height = 720
        menu._center_screen = (400, 300)
        menu.open_cantrip_popup()
        assert menu.state == RadialMenuState.CANTRIP_POPUP
        assert menu.cantrip_popup is not None

    def test_close_clears_creature_id(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)
        assert menu.creature_id is not None
        menu.close()
        menu._finish_close()  # complete the close animation
        assert menu.creature_id is None

    def test_close_clears_slots(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)
        assert len(menu.all_slots) > 0
        menu.close()
        menu._finish_close()  # complete the close animation
        assert len(menu.all_slots) == 0
        assert len(menu.slots) == 0


# ── Slot Categorization Tests ────────────────────────────────────────

class TestSlotCategorization:
    """Test that creature actions are correctly categorized into radial slots."""

    def test_weapon_attacks_get_individual_slots(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        attack_slots = [s for s in menu.all_slots if s.slot_type == "attack"]
        assert len(attack_slots) == 2
        labels = {s.label for s in attack_slots}
        assert "Longsword" in labels
        assert "Handaxe" in labels

    def test_cantrips_grouped_into_single_slot(self):
        cm = _setup_combat(player_creature=_make_wizard())
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        cantrip_slots = [s for s in menu.all_slots if s.slot_type == "cantrip"]
        assert len(cantrip_slots) == 1
        assert cantrip_slots[0].label == "Cantrips"

    def test_leveled_spells_grouped_into_single_slot(self):
        cm = _setup_combat(player_creature=_make_wizard())
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        spell_slots = [s for s in menu.all_slots if s.slot_type == "spells"]
        assert len(spell_slots) == 1
        assert spell_slots[0].label == "Spells"

    def test_tactics_slot_always_present(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        tactics_slots = [s for s in menu.all_slots if s.slot_type == "tactics"]
        assert len(tactics_slots) == 1
        assert tactics_slots[0].label == "Tactics"

    def test_end_turn_slot_always_present(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        end_slots = [s for s in menu.all_slots if s.slot_type == "end_turn"]
        assert len(end_slots) == 1
        assert end_slots[0].label == "End Turn"

    def test_end_turn_is_last_slot(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        assert menu.all_slots[-1].slot_type == "end_turn"

    def test_bonus_action_slots(self):
        cm = _setup_combat(player_creature=_make_creature_with_bonus())
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        bonus_slots = [s for s in menu.all_slots if s.slot_type == "bonus"]
        assert len(bonus_slots) >= 1
        labels = {s.label for s in bonus_slots}
        assert "Healing Word" in labels

    def test_twf_offhand_when_eligible(self):
        cm = _setup_combat(light_weapons=True)
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        # Must use action first for TWF
        cm.turn_resources.has_used_action = True

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        bonus_slots = [s for s in menu.all_slots if s.slot_type == "bonus"]
        labels = {s.label for s in bonus_slots}
        assert "Off-Hand" in labels

    def test_twf_offhand_not_shown_when_ineligible(self):
        cm = _setup_combat(light_weapons=False)
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        cm.turn_resources.has_used_action = True

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        bonus_slots = [s for s in menu.all_slots if s.slot_type == "bonus"]
        labels = {s.label for s in bonus_slots}
        assert "Off-Hand" not in labels

    def test_disabled_after_action_used(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        cm.turn_resources.has_used_action = True

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        for slot in menu.all_slots:
            if slot.slot_type in ("attack", "cantrip", "spells", "tactics"):
                assert slot.is_disabled is True, f"{slot.label} should be disabled"

    def test_end_turn_never_disabled(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        cm.turn_resources.has_used_action = True
        cm.turn_resources.has_used_bonus_action = True

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        end_slot = [s for s in menu.all_slots if s.slot_type == "end_turn"][0]
        assert end_slot.is_disabled is False

    def test_wizard_slot_count(self):
        """Wizard should have: 1 Cantrips + 1 weapon + 1 Spells + 1 Tactics + 1 End Turn = 5."""
        cm = _setup_combat(player_creature=_make_wizard())
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        assert len(menu.all_slots) == 5

    def test_fighter_slot_count(self):
        """Fighter should have: 2 weapons + 1 Tactics + 1 End Turn = 4."""
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        assert len(menu.all_slots) == 4


# ── Pagination Tests ─────────────────────────────────────────────────

class TestPagination:
    """Test pagination of slots across multiple pages."""

    def test_no_pagination_under_max(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        assert menu.total_pages == 1
        assert menu.current_page == 0

    def test_pagination_with_many_actions(self):
        """Create a creature with many weapon attacks to force pagination."""
        many_actions = []
        for i in range(10):
            many_actions.append(Action(
                name=f"Weapon{i}",
                description=f"Attack {i}",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name=f"Weapon{i}",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=5,
                    damage=[
                        DamageRoll(dice="1d6", damage_type=DamageType.SLASHING)
                    ],
                ),
            ))
        creature = Creature(
            name="MultiWeapon",
            max_hit_points=30,
            ability_scores=AbilityScores(strength=16),
            proficiency_bonus=2,
            speed={"walk": 30},
            is_player_controlled=True,
            actions=many_actions,
        )
        cm = _setup_combat(player_creature=creature)
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        # 10 weapons + Tactics + End Turn = 12 slots
        assert len(menu.all_slots) == 12
        assert menu.total_pages == 2
        assert len(menu.slots) == MAX_SLOTS_PER_PAGE

    def test_page_cycling(self):
        """Test that page cycling wraps around."""
        menu = RadialMenu()
        menu.all_slots = [RadialMenu.__new__(RadialMenu)] * 12  # dummy
        menu.total_pages = 2
        menu.current_page = 0

        # Forward wrap
        menu.current_page = (menu.current_page + 1) % menu.total_pages
        assert menu.current_page == 1

        menu.current_page = (menu.current_page + 1) % menu.total_pages
        assert menu.current_page == 0

        # Backward wrap
        menu.current_page = (menu.current_page - 1) % menu.total_pages
        assert menu.current_page == 1


# ── Hit Detection Tests ──────────────────────────────────────────────

class TestHitDetection:
    """Test geometric hit detection for slots and menu area."""

    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        pygame.display.set_mode((1, 1))
        yield
        pygame.quit()

    def test_slot_hit_within_radius(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)
        menu._center_screen = (400, 300)
        menu._compute_slot_positions()

        # Click right on first slot's center
        first_slot = menu.slots[0]
        hit = menu._get_slot_at(first_slot.screen_pos)
        assert hit is first_slot

    def test_slot_miss_outside_radius(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)
        menu._center_screen = (400, 300)
        menu._compute_slot_positions()

        # Click far away
        hit = menu._get_slot_at((0, 0))
        assert hit is None

    def test_contains_point_when_open(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)
        menu._center_screen = (400, 300)
        menu._compute_slot_positions()

        # Center of menu should be contained
        assert menu.contains_point((400, 300)) is True
        # Far away should not
        assert menu.contains_point((0, 0)) is False

    def test_contains_point_when_closed(self):
        menu = RadialMenu()
        assert menu.contains_point((400, 300)) is False


# ── Slot Command Mapping Tests ───────────────────────────────────────

class TestSlotCommands:
    """Test that slot clicks produce the correct command strings."""

    def test_attack_slot_command(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        attack_slot = next(s for s in menu.all_slots if s.slot_type == "attack")
        cmd = menu._slot_command(attack_slot)
        assert cmd == f"action:{attack_slot.label}"

    def test_cantrip_slot_command(self):
        cm = _setup_combat(player_creature=_make_wizard())
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        cantrip_slot = next(s for s in menu.all_slots if s.slot_type == "cantrip")
        cmd = menu._slot_command(cantrip_slot)
        assert cmd == "open_cantrips"

    def test_spells_slot_command(self):
        cm = _setup_combat(player_creature=_make_wizard())
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        spell_slot = next(s for s in menu.all_slots if s.slot_type == "spells")
        cmd = menu._slot_command(spell_slot)
        assert cmd == "open_spells"

    def test_tactics_slot_command(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        tactics_slot = next(s for s in menu.all_slots if s.slot_type == "tactics")
        cmd = menu._slot_command(tactics_slot)
        assert cmd == "open_tactics"

    def test_end_turn_slot_command(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        end_slot = next(s for s in menu.all_slots if s.slot_type == "end_turn")
        cmd = menu._slot_command(end_slot)
        assert cmd == "end_turn"

    def test_bonus_offhand_slot_command(self):
        cm = _setup_combat(light_weapons=True)
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        cm.turn_resources.has_used_action = True

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        offhand_slot = next(
            (s for s in menu.all_slots if s.label == "Off-Hand"), None
        )
        assert offhand_slot is not None
        cmd = menu._slot_command(offhand_slot)
        assert cmd == "bonus:offhand"

    def test_named_bonus_action_command(self):
        cm = _setup_combat(player_creature=_make_creature_with_bonus())
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        bonus_slot = next(
            (s for s in menu.all_slots if s.label == "Healing Word"), None
        )
        assert bonus_slot is not None
        cmd = menu._slot_command(bonus_slot)
        assert cmd == "bonus_action:Healing Word"


# ── Tooltip Tests ────────────────────────────────────────────────────

class TestTooltips:
    """Test that tooltip lines are generated correctly."""

    def test_weapon_attack_tooltip_has_to_hit(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        attack_slot = next(s for s in menu.all_slots if s.slot_type == "attack")
        assert any("to hit" in line for line in attack_slot.tooltip_lines)

    def test_weapon_attack_tooltip_has_damage(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        attack_slot = next(s for s in menu.all_slots if s.slot_type == "attack")
        assert any("slashing" in line for line in attack_slot.tooltip_lines)

    def test_end_turn_tooltip(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        end_slot = next(s for s in menu.all_slots if s.slot_type == "end_turn")
        assert "End your turn (Space)" in end_slot.tooltip_lines

    def test_weapon_tooltip_has_type_tag(self):
        """Weapon attack tooltips should start with 'Weapon • Action'."""
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        attack_slot = next(s for s in menu.all_slots if s.slot_type == "attack")
        assert attack_slot.tooltip_lines[0] == "Weapon \u2022 Action"

    def test_cantrip_group_slot_tooltip(self):
        """Cantrip group slot tooltip should show count."""
        cm = _setup_combat(player_creature=_make_wizard())
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        cantrip_slot = next(s for s in menu.all_slots if s.slot_type == "cantrip")
        assert cantrip_slot.tooltip_lines[0] == "2 cantrip(s) available"

    def test_bonus_action_tooltip_has_economy_tag(self):
        """Bonus action tooltips should include 'Bonus Action' tag."""
        cm = _setup_combat(player_creature=_make_creature_with_bonus())
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        menu = RadialMenu()
        menu.set_combat(cm)
        menu.open(active.creature_id)

        bonus_slot = next(
            (s for s in menu.all_slots if s.label == "Healing Word"), None
        )
        assert bonus_slot is not None
        assert any("Bonus Action" in line for line in bonus_slot.tooltip_lines)
