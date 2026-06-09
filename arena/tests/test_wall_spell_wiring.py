"""Tests for wall spell wiring into movement blocking and line-of-sight."""

from __future__ import annotations

import pytest

from arena.combat.wall_spells import ActiveWall, WallPanel, create_wall
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.grid.pathfinding import find_path, get_reachable_hexes
from arena.grid.line_of_sight import has_line_of_sight
from arena.combat.movement import MovementTracker
from arena.models.actions import Action, ActionType, TargetType
from arena.models.character import CreatureSize


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _wall_of_force_action() -> Action:
    """Wall of Force: concentration, indestructible, blocks movement + LOS."""
    return Action(
        name="Wall of Force",
        description="Invisible wall of force.",
        action_type=ActionType.ACTION,
        target_type=TargetType.AREA_LINE,
        range=120,
        requires_concentration=True,
        is_wall=True,
        wall_length=100,
        wall_height=10,
        wall_thickness=1,
        wall_hp_per_panel=None,
        wall_blocks_movement=True,
        wall_blocks_los=True,
    )


def _wall_of_fire_action() -> Action:
    """Wall of Fire: concentration, doesn't block movement."""
    return Action(
        name="Wall of Fire",
        description="Wall of fire.",
        action_type=ActionType.ACTION,
        target_type=TargetType.AREA_LINE,
        range=120,
        requires_concentration=True,
        is_wall=True,
        wall_length=60,
        wall_height=20,
        wall_thickness=1,
        wall_hp_per_panel=None,
        wall_blocks_movement=False,
        wall_blocks_los=False,
        wall_damage_side="one_side",
        wall_damage_on_enter="5d8",
        wall_damage_type="fire",
    )


def _make_grid(width=10, height=10):
    return HexGrid(width, height)


def _create_wall_blocking_row(
    blocks_movement: bool = True,
    blocks_los: bool = False,
) -> tuple[ActiveWall, list[HexCoord]]:
    """Create a wall spanning a row of hexes at r=3 from q=0 to q=4."""
    wall_hexes = [HexCoord(q, 3) for q in range(5)]
    panels = [
        WallPanel(hexes=[wall_hexes[0], wall_hexes[1]]),
        WallPanel(hexes=[wall_hexes[2], wall_hexes[3]]),
        WallPanel(hexes=[wall_hexes[4]]),
    ]
    wall = ActiveWall(
        name="Test Wall",
        source_id="caster_1",
        panels=panels,
        blocks_movement=blocks_movement,
        blocks_los=blocks_los,
        concentration_linked=True,
    )
    return wall, wall_hexes


# ------------------------------------------------------------------
# Pathfinding: blocked_hexes parameter
# ------------------------------------------------------------------


class TestPathfindingBlockedHexes:
    """Test that find_path and get_reachable_hexes respect blocked_hexes."""

    def test_find_path_blocked_goal(self):
        """Path to a blocked hex returns None."""
        grid = _make_grid()
        start = HexCoord(2, 2)
        goal = HexCoord(2, 3)
        blocked = {(2, 3)}

        result = find_path(start, goal, grid, blocked_hexes=blocked)
        assert result is None

    def test_find_path_blocked_intermediate(self):
        """Path through a wall of blocked hexes forces detour or None."""
        grid = _make_grid()
        start = HexCoord(2, 2)
        goal = HexCoord(2, 5)
        # Block the entire row at r=3 from q=0 to q=4
        blocked = {(q, 3) for q in range(5)}

        result = find_path(start, goal, grid, blocked_hexes=blocked)
        if result is not None:
            # If a detour exists, none of the path hexes should be blocked
            for h in result:
                assert (h.q, h.r) not in blocked
        # On a 10x10 grid the creature can go around, so path should exist
        assert result is not None

    def test_find_path_no_blocked_hexes(self):
        """Without blocked_hexes, path goes through normally."""
        grid = _make_grid()
        start = HexCoord(2, 2)
        goal = HexCoord(2, 4)

        result = find_path(start, goal, grid)
        assert result is not None
        assert result[0] == start
        assert result[-1] == goal

    def test_find_path_wall_blocks_direct_path(self):
        """Wall of Force hexes block the direct path."""
        grid = _make_grid()
        start = HexCoord(2, 2)
        goal = HexCoord(2, 4)

        wall, wall_hexes = _create_wall_blocking_row(blocks_movement=True)
        blocked = set()
        for h in wall.get_wall_hexes():
            if wall.is_blocking_hex(h):
                blocked.add((h.q, h.r))

        # The direct path from (2,2) to (2,4) must go through (2,3)
        # which is blocked, so path must detour
        result = find_path(start, goal, grid, blocked_hexes=blocked)
        if result is not None:
            for h in result:
                assert (h.q, h.r) not in blocked

    def test_get_reachable_excludes_blocked(self):
        """Blocked hexes are not in reachable set."""
        grid = _make_grid()
        start = HexCoord(5, 5)
        blocked = {(5, 6), (4, 6), (6, 6)}

        reachable = get_reachable_hexes(
            start, grid, max_cost=30, blocked_hexes=blocked,
        )
        for bh in blocked:
            assert bh not in reachable

    def test_get_reachable_without_blocked(self):
        """Without blocked_hexes, adjacent hexes are reachable."""
        grid = _make_grid()
        start = HexCoord(5, 5)

        reachable = get_reachable_hexes(start, grid, max_cost=30)
        # At least the 6 neighbors should be reachable
        assert len(reachable) > 6

    def test_find_path_wall_of_fire_no_block(self):
        """Wall of Fire (blocks_movement=False) does NOT block pathfinding."""
        grid = _make_grid()
        start = HexCoord(2, 2)
        goal = HexCoord(2, 4)

        wall, _ = _create_wall_blocking_row(blocks_movement=False)
        blocked = set()
        for h in wall.get_wall_hexes():
            if wall.is_blocking_hex(h):
                blocked.add((h.q, h.r))

        # blocks_movement=False means no hexes are blocking
        assert len(blocked) == 0

        result = find_path(start, goal, grid, blocked_hexes=blocked)
        assert result is not None
        assert result[-1] == goal


# ------------------------------------------------------------------
# LOS blocking
# ------------------------------------------------------------------


class TestWallLosBlocking:
    """Test that has_line_of_sight respects los_blocked_hexes."""

    def test_los_blocked_by_wall(self):
        """LOS through a wall hex with blocks_los=True is blocked."""
        grid = _make_grid()
        origin = HexCoord(3, 1)
        target = HexCoord(3, 5)
        # Block hex at (3, 3) in the line between origin and target
        los_blocked = {(3, 3)}

        assert has_line_of_sight(origin, target, grid, los_blocked_hexes=los_blocked) is False

    def test_los_not_blocked_without_param(self):
        """Without los_blocked_hexes, LOS is clear on open terrain."""
        grid = _make_grid()
        origin = HexCoord(3, 1)
        target = HexCoord(3, 5)

        assert has_line_of_sight(origin, target, grid) is True

    def test_los_not_blocked_by_non_los_wall(self):
        """Wall with blocks_los=False doesn't generate LOS-blocking hexes."""
        wall, _ = _create_wall_blocking_row(blocks_movement=True, blocks_los=False)
        los_blocked = set()
        for h in wall.get_wall_hexes():
            if wall.is_blocking_los_hex(h):
                los_blocked.add((h.q, h.r))

        # blocks_los=False means no hexes block LOS
        assert len(los_blocked) == 0

    def test_los_blocked_by_los_wall(self):
        """Wall with blocks_los=True generates LOS-blocking hexes."""
        wall, _ = _create_wall_blocking_row(blocks_movement=True, blocks_los=True)
        los_blocked = set()
        for h in wall.get_wall_hexes():
            if wall.is_blocking_los_hex(h):
                los_blocked.add((h.q, h.r))

        assert len(los_blocked) == 5  # All 5 wall hexes block LOS

    def test_los_blocked_at_endpoints_is_allowed(self):
        """LOS check skips origin and target hexes, even if in blocked set."""
        grid = _make_grid()
        origin = HexCoord(3, 3)
        target = HexCoord(3, 4)
        # Block origin and target themselves
        los_blocked = {(3, 3), (3, 4)}

        # Adjacent hexes: line has no intervening hex, so LOS is clear
        assert has_line_of_sight(origin, target, grid, los_blocked_hexes=los_blocked) is True


# ------------------------------------------------------------------
# MovementTracker integration
# ------------------------------------------------------------------


class TestMovementTrackerBlockedHexes:
    """Test that MovementTracker passes blocked_hexes to pathfinding."""

    def test_blocked_hexes_field_default(self):
        """MovementTracker has blocked_hexes defaulting to empty set."""
        mt = MovementTracker(creature_id="a", max_movement=30, remaining_movement=30)
        assert mt.blocked_hexes == set()

    def test_get_reachable_respects_blocked(self):
        """MovementTracker.get_reachable excludes wall-blocked hexes."""
        grid = _make_grid()
        start = HexCoord(5, 5)
        grid.place_creature(start, "fighter")

        mt = MovementTracker(
            creature_id="fighter",
            max_movement=30,
            remaining_movement=30,
            blocked_hexes={(5, 6), (4, 5)},
        )
        reachable = mt.get_reachable(grid)
        assert (5, 6) not in reachable
        assert (4, 5) not in reachable


# ------------------------------------------------------------------
# Wall creation via create_wall
# ------------------------------------------------------------------


class TestWallCreation:
    """Test create_wall from action + hex list."""

    def test_create_wall_from_action(self):
        """create_wall creates an ActiveWall with correct properties."""
        action = _wall_of_force_action()
        hexes = [HexCoord(0, 0), HexCoord(1, 0), HexCoord(2, 0)]
        wall = create_wall(action, "wizard_1", hexes)

        assert wall is not None
        assert wall.name == "Wall of Force"
        assert wall.source_id == "wizard_1"
        assert wall.blocks_movement is True
        assert wall.blocks_los is True
        assert wall.concentration_linked is True
        assert len(wall.panels) == 2  # 3 hexes -> 2 panels (2+1)

    def test_create_wall_non_wall_action_returns_none(self):
        """create_wall returns None for a non-wall action."""
        action = Action(
            name="Fireball",
            description="Boom.",
            action_type=ActionType.ACTION,
            target_type=TargetType.AREA_SPHERE,
            range=150,
            is_wall=False,
        )
        result = create_wall(action, "wizard", [HexCoord(0, 0)])
        assert result is None

    def test_wall_of_fire_no_movement_block(self):
        """Wall of Fire doesn't block movement."""
        action = _wall_of_fire_action()
        hexes = [HexCoord(0, 0), HexCoord(1, 0)]
        wall = create_wall(action, "wizard", hexes)

        assert wall is not None
        assert wall.blocks_movement is False
        for h in wall.get_wall_hexes():
            assert wall.is_blocking_hex(h) is False


# ------------------------------------------------------------------
# Manager integration
# ------------------------------------------------------------------


class TestManagerWallState:
    """Test CombatManager wall state management."""

    def _make_manager(self):
        """Create a minimal CombatManager."""
        from arena.combat.manager import CombatManager

        manager = CombatManager()
        return manager

    def test_manager_has_active_walls(self):
        """CombatManager initializes with empty active_walls list."""
        manager = self._make_manager()
        assert hasattr(manager, "active_walls")
        assert manager.active_walls == []

    def test_get_wall_blocked_hexes_empty(self):
        """_get_wall_blocked_hexes returns empty set with no walls."""
        manager = self._make_manager()
        assert manager._get_wall_blocked_hexes() == set()

    def test_get_wall_blocked_hexes_with_wall(self):
        """_get_wall_blocked_hexes returns correct hexes for blocking wall."""
        manager = self._make_manager()
        wall, _ = _create_wall_blocking_row(blocks_movement=True)
        manager.active_walls.append(wall)

        blocked = manager._get_wall_blocked_hexes()
        assert len(blocked) == 5
        for q in range(5):
            assert (q, 3) in blocked

    def test_get_wall_blocked_hexes_nonblocking_wall(self):
        """_get_wall_blocked_hexes returns empty set for non-blocking wall."""
        manager = self._make_manager()
        wall, _ = _create_wall_blocking_row(blocks_movement=False)
        manager.active_walls.append(wall)

        blocked = manager._get_wall_blocked_hexes()
        assert len(blocked) == 0

    def test_get_wall_los_blocked_hexes(self):
        """_get_wall_los_blocked_hexes returns correct hexes for LOS-blocking wall."""
        manager = self._make_manager()
        wall, _ = _create_wall_blocking_row(blocks_movement=True, blocks_los=True)
        manager.active_walls.append(wall)

        los_blocked = manager._get_wall_los_blocked_hexes()
        assert len(los_blocked) == 5

    def test_get_wall_los_blocked_hexes_non_los_wall(self):
        """_get_wall_los_blocked_hexes returns empty for non-LOS wall."""
        manager = self._make_manager()
        wall, _ = _create_wall_blocking_row(blocks_movement=True, blocks_los=False)
        manager.active_walls.append(wall)

        los_blocked = manager._get_wall_los_blocked_hexes()
        assert len(los_blocked) == 0


# ------------------------------------------------------------------
# Concentration cleanup
# ------------------------------------------------------------------


class TestWallConcentrationCleanup:
    """Test that concentration-linked walls are removed when concentration ends."""

    def _setup_combat_with_wall(self):
        """Set up a CombatManager with two combatants and a wall."""
        from arena.combat.manager import CombatManager
        from arena.models.character import Creature, AbilityScores
        from arena.models.conditions import Condition
        from arena.combat.conditions import apply_condition

        manager = CombatManager()

        # Create a simple creature for the caster
        scores = AbilityScores(
            strength=10, dexterity=10, constitution=10,
            intelligence=18, wisdom=12, charisma=10,
        )
        wizard = Creature(
            name="Wizard",
            hit_points=40,
            max_hit_points=40,
            armor_class=12,
            ability_scores=scores,
            actions=[],
        )
        fighter = Creature(
            name="Fighter",
            hit_points=50,
            max_hit_points=50,
            armor_class=18,
            ability_scores=scores,
            actions=[],
            is_player=False,
        )

        grid = HexGrid(10, 10)
        manager.grid = grid

        from arena.combat.manager import Combatant
        wizard_c = Combatant(creature=wizard, creature_id="wizard_1", team="player", position=HexCoord(1, 1))
        fighter_c = Combatant(creature=fighter, creature_id="fighter_1", team="enemy", position=HexCoord(5, 5))
        manager.combatants["wizard_1"] = wizard_c
        manager.combatants["fighter_1"] = fighter_c

        # Add concentration to wizard
        apply_condition(wizard, "wizard_1", Condition.CONCENTRATING, source="Wall of Force", extra_data={"spell": "Wall of Force"})

        # Create a concentration-linked wall
        wall, _ = _create_wall_blocking_row(blocks_movement=True, blocks_los=True)
        wall.source_id = "wizard_1"
        wall.concentration_linked = True
        manager.active_walls.append(wall)

        return manager, wizard

    def test_wall_removed_when_concentration_ends(self):
        """Concentration-linked wall is removed when caster loses concentration."""
        from arena.combat.conditions import remove_condition
        from arena.models.conditions import Condition

        manager, wizard = self._setup_combat_with_wall()
        assert len(manager.active_walls) == 1

        # Remove concentration from wizard
        remove_condition(wizard, "wizard_1", Condition.CONCENTRATING)

        # Trigger cleanup
        manager._cleanup_orphaned_zones()

        assert len(manager.active_walls) == 0

    def test_wall_persists_with_concentration(self):
        """Concentration-linked wall stays while caster is concentrating."""
        manager, wizard = self._setup_combat_with_wall()
        assert len(manager.active_walls) == 1

        # Trigger cleanup without removing concentration
        manager._cleanup_orphaned_zones()

        assert len(manager.active_walls) == 1

    def test_non_concentration_wall_persists(self):
        """Non-concentration wall is not removed by cleanup."""
        from arena.combat.manager import CombatManager

        manager = CombatManager()
        wall, _ = _create_wall_blocking_row()
        wall.concentration_linked = False
        manager.active_walls.append(wall)

        manager._cleanup_orphaned_zones()
        assert len(manager.active_walls) == 1
