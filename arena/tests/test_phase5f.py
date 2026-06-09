"""Tests for Phase 5f: Line of Sight and Cover."""

import pytest

from arena.grid.line_of_sight import hex_line, has_line_of_sight, get_cover
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.encounter import TerrainType


# ── hex_line Tests ──────────────────────────────────────────────────

class TestHexLine:
    def test_same_hex(self):
        result = hex_line(HexCoord(5, 5), HexCoord(5, 5))
        assert result == [HexCoord(5, 5)]

    def test_adjacent_hex(self):
        result = hex_line(HexCoord(5, 5), HexCoord(5, 6))
        assert len(result) == 2
        assert result[0] == HexCoord(5, 5)
        assert result[-1] == HexCoord(5, 6)

    def test_line_includes_endpoints(self):
        origin = HexCoord(0, 0)
        target = HexCoord(0, 5)
        result = hex_line(origin, target)
        assert result[0] == origin
        assert result[-1] == target

    def test_line_length(self):
        origin = HexCoord(2, 2)
        target = HexCoord(2, 5)
        result = hex_line(origin, target)
        # Distance of 3 -> should have 4 hexes (start + 3)
        assert len(result) == origin.distance_to(target) + 1


# ── has_line_of_sight Tests ────────────────────────────────────────

class TestHasLineOfSight:
    def test_clear_path(self):
        grid = HexGrid(10, 10)
        assert has_line_of_sight(HexCoord(2, 2), HexCoord(2, 5), grid) is True

    def test_adjacent_always_visible(self):
        grid = HexGrid(10, 10)
        assert has_line_of_sight(HexCoord(3, 3), HexCoord(3, 4), grid) is True

    def test_same_hex(self):
        grid = HexGrid(10, 10)
        assert has_line_of_sight(HexCoord(5, 5), HexCoord(5, 5), grid) is True

    def test_blocked_by_wall(self):
        grid = HexGrid(10, 10)
        # Place a wall between origin and target
        grid.set_terrain(HexCoord(2, 3), TerrainType.WALL)
        assert has_line_of_sight(HexCoord(2, 2), HexCoord(2, 5), grid) is False

    def test_blocked_by_full_cover(self):
        grid = HexGrid(10, 10)
        grid.set_terrain(HexCoord(2, 4), TerrainType.COVER_FULL)
        assert has_line_of_sight(HexCoord(2, 2), HexCoord(2, 5), grid) is False

    def test_half_cover_does_not_block_los(self):
        grid = HexGrid(10, 10)
        grid.set_terrain(HexCoord(2, 3), TerrainType.COVER_HALF)
        assert has_line_of_sight(HexCoord(2, 2), HexCoord(2, 5), grid) is True

    def test_three_quarter_cover_does_not_block_los(self):
        grid = HexGrid(10, 10)
        grid.set_terrain(HexCoord(2, 3), TerrainType.COVER_THREE_QUARTERS)
        assert has_line_of_sight(HexCoord(2, 2), HexCoord(2, 5), grid) is True

    def test_wall_on_target_does_not_block(self):
        """Walls on target or origin hex don't block LOS (only intervening)."""
        grid = HexGrid(10, 10)
        grid.set_terrain(HexCoord(2, 5), TerrainType.WALL)
        # Target is ON the wall hex, but that's the endpoint
        assert has_line_of_sight(HexCoord(2, 2), HexCoord(2, 5), grid) is True


# ── get_cover Tests ─────────────────────────────────────────────────

class TestGetCover:
    def test_no_cover_clear_path(self):
        grid = HexGrid(10, 10)
        assert get_cover(HexCoord(2, 2), HexCoord(2, 5), grid) == 0

    def test_adjacent_no_cover(self):
        grid = HexGrid(10, 10)
        assert get_cover(HexCoord(3, 3), HexCoord(3, 4), grid) == 0

    def test_same_hex_no_cover(self):
        grid = HexGrid(10, 10)
        assert get_cover(HexCoord(5, 5), HexCoord(5, 5), grid) == 0

    def test_half_cover(self):
        grid = HexGrid(10, 10)
        grid.set_terrain(HexCoord(2, 3), TerrainType.COVER_HALF)
        assert get_cover(HexCoord(2, 2), HexCoord(2, 5), grid) == 2

    def test_three_quarter_cover(self):
        grid = HexGrid(10, 10)
        grid.set_terrain(HexCoord(2, 3), TerrainType.COVER_THREE_QUARTERS)
        assert get_cover(HexCoord(2, 2), HexCoord(2, 5), grid) == 5

    def test_creature_provides_half_cover(self):
        grid = HexGrid(10, 10)
        grid.place_creature(HexCoord(2, 3), "bystander")
        assert get_cover(HexCoord(2, 2), HexCoord(2, 5), grid) == 2

    def test_highest_cover_wins(self):
        grid = HexGrid(10, 10)
        grid.set_terrain(HexCoord(2, 3), TerrainType.COVER_HALF)
        grid.set_terrain(HexCoord(2, 4), TerrainType.COVER_THREE_QUARTERS)
        assert get_cover(HexCoord(2, 2), HexCoord(2, 5), grid) == 5


# ── Integration: resolve_attack with LOS/Cover ─────────────────────

class TestResolveAttackLOS:
    def test_attack_blocked_by_wall(self):
        from unittest.mock import patch
        from arena.combat.actions import resolve_attack
        from arena.combat.events import CombatEventType
        from arena.models.abilities import AbilityScores
        from arena.models.character import Creature
        from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType

        grid = HexGrid(10, 10)
        grid.place_creature(HexCoord(2, 2), "archer")
        grid.place_creature(HexCoord(2, 5), "target")
        grid.set_terrain(HexCoord(2, 3), TerrainType.WALL)

        attacker = Creature(
            name="Archer", max_hit_points=20,
            ability_scores=AbilityScores(dexterity=16), proficiency_bonus=2,
        )
        target = Creature(name="Target", max_hit_points=20, armor_class=10)
        action = Action(
            name="Bow", description="Ranged", action_type=ActionType.ACTION,
            attack=Attack(
                name="Bow", attack_type="ranged_weapon", ability="dexterity",
                range_normal=80,
                damage=[DamageRoll(dice="1d6", damage_type=DamageType.PIERCING)],
            ),
        )

        result = resolve_attack(attacker, "archer", target, "target", action, grid)
        assert result.success is False
        assert "not visible" in result.events[0].message
