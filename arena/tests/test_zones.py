"""Tests for persistent AoE zone system."""

import pytest
from unittest.mock import patch

from arena.combat.zones import (
    ActiveZone,
    get_zone_hexes,
    is_in_zone,
    process_zone_start_of_turn,
    process_zone_entry,
    remove_zones_for_caster,
    reset_zone_round_tracking,
)
from arena.combat.events import CombatEventType
from arena.combat.manager import Combatant
from arena.models.abilities import AbilityScores
from arena.models.character import Creature
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_creature(name="Cleric", hp=30, wisdom=10, team="player"):
    creature = Creature(
        name=name,
        max_hit_points=hp,
        ability_scores=AbilityScores(wisdom=wisdom),
        proficiency_bonus=2,
    )
    return creature


def _make_combatant(creature_id, creature, team, position):
    return Combatant(
        creature_id=creature_id,
        creature=creature,
        team=team,
        position=position,
    )


def _make_zone(caster_id="cleric", team="player", radius=15, dc=15):
    return ActiveZone(
        zone_id=f"spirit_guardians_{caster_id}",
        caster_id=caster_id,
        name="Spirit Guardians",
        radius_feet=radius,
        follows_caster=True,
        center=None,
        saving_throw_ability="wisdom",
        saving_throw_dc=dc,
        damage_dice="3d8",
        damage_type="radiant",
        damage_on_save="half",
        affects_enemies_only=True,
        team=team,
        concentration_linked=True,
        already_damaged=set(),
    )


def _setup_basic():
    """Create a basic grid + combatants setup for testing."""
    grid = HexGrid(10, 10)
    cleric = _make_creature("Cleric", hp=30, team="player")
    skeleton = _make_creature("Skeleton", hp=13, wisdom=8, team="enemy")

    combatants = {
        "cleric": _make_combatant("cleric", cleric, "player", HexCoord(5, 5)),
        "skeleton": _make_combatant("skeleton", skeleton, "enemy", HexCoord(5, 6)),
    }
    zone = _make_zone()
    return grid, combatants, zone


# ------------------------------------------------------------------
# Geometry tests
# ------------------------------------------------------------------

class TestGetZoneHexes:
    def test_returns_hexes_within_radius(self):
        grid, combatants, zone = _setup_basic()
        hexes = get_zone_hexes(zone, combatants, grid)
        # Center hex (5,5) should be in the zone
        assert HexCoord(5, 5) in hexes
        # Adjacent hex (5,6) is 1 hex = 5 ft away, within 15 ft
        assert HexCoord(5, 6) in hexes

    def test_excludes_hexes_outside_radius(self):
        grid, combatants, zone = _setup_basic()
        zone.radius_feet = 5  # Only 1 hex radius
        hexes = get_zone_hexes(zone, combatants, grid)
        # Center should be in
        assert HexCoord(5, 5) in hexes
        # Adjacent hex at distance 1 = 5 ft should be in
        assert HexCoord(5, 6) in hexes
        # Far away hex should not be in
        assert HexCoord(0, 0) not in hexes

    def test_follows_caster_position(self):
        grid, combatants, zone = _setup_basic()
        zone.radius_feet = 5  # Tight radius
        # Move caster to corner
        combatants["cleric"].position = HexCoord(0, 0)
        hexes = get_zone_hexes(zone, combatants, grid)
        assert HexCoord(0, 0) in hexes
        # Original position should no longer be in zone
        assert HexCoord(5, 5) not in hexes

    def test_returns_empty_if_no_grid(self):
        _, combatants, zone = _setup_basic()
        hexes = get_zone_hexes(zone, combatants, None)
        assert hexes == set()

    def test_returns_empty_if_caster_missing(self):
        grid, combatants, zone = _setup_basic()
        del combatants["cleric"]
        hexes = get_zone_hexes(zone, combatants, grid)
        assert hexes == set()

    def test_fixed_center_zone(self):
        grid, combatants, zone = _setup_basic()
        zone.follows_caster = False
        zone.center = HexCoord(2, 2)
        zone.radius_feet = 5
        hexes = get_zone_hexes(zone, combatants, grid)
        assert HexCoord(2, 2) in hexes
        # Caster's position should not be in the zone (too far)
        assert HexCoord(5, 5) not in hexes


class TestIsInZone:
    def test_creature_inside_zone(self):
        grid, combatants, zone = _setup_basic()
        assert is_in_zone("skeleton", zone, combatants, grid) is True

    def test_creature_outside_zone(self):
        grid, combatants, zone = _setup_basic()
        zone.radius_feet = 0  # Zero radius
        # Skeleton at (5,6) is 1 hex away from caster at (5,5)
        assert is_in_zone("skeleton", zone, combatants, grid) is False

    def test_caster_is_in_own_zone(self):
        grid, combatants, zone = _setup_basic()
        # Caster IS geometrically inside, but zone processing should skip them
        assert is_in_zone("cleric", zone, combatants, grid) is True

    def test_missing_creature_returns_false(self):
        grid, combatants, zone = _setup_basic()
        assert is_in_zone("nonexistent", zone, combatants, grid) is False


# ------------------------------------------------------------------
# Start-of-turn processing
# ------------------------------------------------------------------

class TestProcessZoneStartOfTurn:
    @patch("arena.util.dice.roll_expression", return_value=(12, [4, 4, 4]))
    @patch("arena.combat.actions.resolve_saving_throw")
    def test_damages_enemy_in_zone(self, mock_save, mock_roll):
        grid, combatants, zone = _setup_basic()
        # Skeleton fails the save
        mock_save.return_value = (False, _make_save_event("skeleton", False))

        events = process_zone_start_of_turn(
            [zone], "skeleton", combatants, grid,
        )
        # Should have events: info, save, damage
        assert len(events) >= 3
        assert any(e.event_type == CombatEventType.SAVING_THROW for e in events)
        assert any(e.event_type == CombatEventType.DAMAGE for e in events)

    @patch("arena.util.dice.roll_expression", return_value=(12, [4, 4, 4]))
    @patch("arena.combat.actions.resolve_saving_throw")
    def test_half_damage_on_save(self, mock_save, mock_roll):
        grid, combatants, zone = _setup_basic()
        mock_save.return_value = (True, _make_save_event("skeleton", True))

        old_hp = combatants["skeleton"].creature.current_hit_points
        events = process_zone_start_of_turn(
            [zone], "skeleton", combatants, grid,
        )
        new_hp = combatants["skeleton"].creature.current_hit_points
        # Half of 12 = 6
        assert old_hp - new_hp == 6

    def test_skips_caster(self):
        grid, combatants, zone = _setup_basic()
        events = process_zone_start_of_turn(
            [zone], "cleric", combatants, grid,
        )
        assert len(events) == 0

    def test_skips_ally(self):
        grid, combatants, zone = _setup_basic()
        # Add a friendly ally
        ally = _make_creature("Paladin", hp=30)
        combatants["paladin"] = _make_combatant(
            "paladin", ally, "player", HexCoord(5, 4),
        )
        events = process_zone_start_of_turn(
            [zone], "paladin", combatants, grid,
        )
        assert len(events) == 0

    def test_skips_already_damaged(self):
        grid, combatants, zone = _setup_basic()
        zone.already_damaged.add("skeleton")
        events = process_zone_start_of_turn(
            [zone], "skeleton", combatants, grid,
        )
        assert len(events) == 0

    def test_skips_creature_outside_zone(self):
        grid, combatants, zone = _setup_basic()
        # Move skeleton far away
        combatants["skeleton"].position = HexCoord(0, 0)
        events = process_zone_start_of_turn(
            [zone], "skeleton", combatants, grid,
        )
        assert len(events) == 0

    @patch("arena.util.dice.roll_expression", return_value=(12, [4, 4, 4]))
    @patch("arena.combat.actions.resolve_saving_throw")
    def test_marks_already_damaged(self, mock_save, mock_roll):
        grid, combatants, zone = _setup_basic()
        mock_save.return_value = (False, _make_save_event("skeleton", False))

        process_zone_start_of_turn([zone], "skeleton", combatants, grid)
        assert "skeleton" in zone.already_damaged


# ------------------------------------------------------------------
# Zone entry processing
# ------------------------------------------------------------------

class TestProcessZoneEntry:
    @patch("arena.util.dice.roll_expression", return_value=(10, [3, 3, 4]))
    @patch("arena.combat.actions.resolve_saving_throw")
    def test_damages_enemy_entering_zone(self, mock_save, mock_roll):
        grid, combatants, zone = _setup_basic()
        mock_save.return_value = (False, _make_save_event("skeleton", False))

        events = process_zone_entry(
            [zone], "skeleton", combatants, grid,
        )
        assert len(events) >= 3

    def test_no_double_damage(self):
        """Creature already damaged this round shouldn't be hit on entry."""
        grid, combatants, zone = _setup_basic()
        zone.already_damaged.add("skeleton")
        events = process_zone_entry(
            [zone], "skeleton", combatants, grid,
        )
        assert len(events) == 0

    def test_skips_caster(self):
        grid, combatants, zone = _setup_basic()
        events = process_zone_entry(
            [zone], "cleric", combatants, grid,
        )
        assert len(events) == 0


# ------------------------------------------------------------------
# Lifecycle tests
# ------------------------------------------------------------------

class TestZoneLifecycle:
    def test_remove_zones_for_caster(self):
        zone1 = _make_zone(caster_id="cleric")
        zone2 = _make_zone(caster_id="wizard")
        remaining = remove_zones_for_caster([zone1, zone2], "cleric")
        assert len(remaining) == 1
        assert remaining[0].caster_id == "wizard"

    def test_reset_zone_round_tracking(self):
        zone = _make_zone()
        zone.already_damaged = {"skeleton", "zombie"}
        reset_zone_round_tracking([zone])
        assert zone.already_damaged == set()

    def test_multiple_zones_reset(self):
        zone1 = _make_zone(caster_id="cleric")
        zone1.already_damaged = {"a", "b"}
        zone2 = _make_zone(caster_id="wizard")
        zone2.already_damaged = {"c"}
        reset_zone_round_tracking([zone1, zone2])
        assert zone1.already_damaged == set()
        assert zone2.already_damaged == set()


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------

def _make_save_event(creature_id, success):
    from arena.combat.events import CombatEvent
    return CombatEvent(
        event_type=CombatEventType.SAVING_THROW,
        message=f"Save {'SUCCESS' if success else 'FAILURE'}",
        source_id=creature_id,
        details={
            "ability": "wisdom",
            "roll": 15 if success else 5,
            "natural": 15 if success else 5,
            "modifier": 0,
            "dc": 15,
            "success": success,
            "advantage": 0,
        },
    )
