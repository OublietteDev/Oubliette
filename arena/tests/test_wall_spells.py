"""Tests for the wall spell system (barrier creation, damage, properties)."""

from __future__ import annotations

import pytest

from arena.combat.wall_spells import (
    ActiveWall,
    WallPanel,
    create_wall,
    get_wall_at_hex,
    is_hex_blocked_by_wall,
    is_los_blocked_by_wall,
)
from arena.grid.coordinates import HexCoord
from arena.models.actions import Action, ActionType, TargetType


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _wall_of_fire_action() -> Action:
    """Wall of Fire: concentration, 60ft line, 5d8 fire on one side."""
    return Action(
        name="Wall of Fire",
        description="Creates a wall of fire that deals damage on one side.",
        action_type=ActionType.ACTION,
        target_type=TargetType.AREA_LINE,
        range=120,
        requires_concentration=True,
        is_wall=True,
        wall_length=60,
        wall_height=20,
        wall_thickness=1,
        wall_hp_per_panel=None,  # Indestructible
        wall_blocks_movement=False,
        wall_blocks_los=False,
        wall_damage_side="one_side",
        wall_damage_on_enter="5d8",
        wall_damage_type="fire",
    )


def _wall_of_force_action() -> Action:
    """Wall of Force: concentration, indestructible, blocks movement + LOS."""
    return Action(
        name="Wall of Force",
        description="Creates an invisible wall of force.",
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
        wall_damage_side=None,
        wall_damage_on_enter=None,
        wall_damage_type=None,
    )


def _wall_of_stone_action() -> Action:
    """Wall of Stone: concentration, destructible panels (15 HP each)."""
    return Action(
        name="Wall of Stone",
        description="Creates a stone wall with destructible panels.",
        action_type=ActionType.ACTION,
        target_type=TargetType.AREA_LINE,
        range=120,
        requires_concentration=True,
        is_wall=True,
        wall_length=60,
        wall_height=10,
        wall_thickness=1,
        wall_hp_per_panel=15,
        wall_blocks_movement=True,
        wall_blocks_los=True,
        wall_damage_side=None,
        wall_damage_on_enter=None,
        wall_damage_type=None,
    )


def _non_wall_action() -> Action:
    """A regular action that is not a wall spell."""
    return Action(
        name="Fireball",
        description="A bright streak flashes to a point and explodes.",
        action_type=ActionType.ACTION,
        target_type=TargetType.AREA_SPHERE,
        range=150,
    )


def _sample_wall_hexes() -> list[HexCoord]:
    """Six hexes forming a straight wall (3 panels of 2 hexes each)."""
    return [
        HexCoord(2, 5),
        HexCoord(3, 5),
        HexCoord(4, 5),
        HexCoord(5, 5),
        HexCoord(6, 5),
        HexCoord(7, 5),
    ]


# ------------------------------------------------------------------
# create_wall tests
# ------------------------------------------------------------------

class TestCreateWall:
    """Tests for the create_wall() factory function."""

    def test_wall_of_fire_creates_wall_with_damage(self):
        action = _wall_of_fire_action()
        hexes = _sample_wall_hexes()
        side_hexes = {HexCoord(3, 4), HexCoord(4, 4)}

        wall = create_wall(action, "wizard_1", hexes, damage_side_hexes=side_hexes)

        assert wall is not None
        assert wall.name == "Wall of Fire"
        assert wall.source_id == "wizard_1"
        assert wall.damage_on_enter == "5d8"
        assert wall.damage_type == "fire"
        assert wall.damage_side == "one_side"
        assert wall.damage_side_hexes == side_hexes
        assert wall.blocks_movement is False
        assert wall.blocks_los is False
        assert wall.concentration_linked is True

    def test_wall_of_force_indestructible_blocks_all(self):
        action = _wall_of_force_action()
        hexes = _sample_wall_hexes()

        wall = create_wall(action, "wizard_1", hexes)

        assert wall is not None
        assert wall.blocks_movement is True
        assert wall.blocks_los is True
        assert wall.damage_on_enter is None
        # All panels should be indestructible
        for panel in wall.panels:
            assert panel.max_hp is None
            assert panel.is_destroyed is False

    def test_non_wall_action_returns_none(self):
        action = _non_wall_action()
        hexes = _sample_wall_hexes()

        result = create_wall(action, "wizard_1", hexes)

        assert result is None

    def test_panels_split_into_two_hex_groups(self):
        action = _wall_of_fire_action()
        hexes = _sample_wall_hexes()  # 6 hexes

        wall = create_wall(action, "wizard_1", hexes)

        assert wall is not None
        assert len(wall.panels) == 3
        assert wall.panels[0].hexes == [HexCoord(2, 5), HexCoord(3, 5)]
        assert wall.panels[1].hexes == [HexCoord(4, 5), HexCoord(5, 5)]
        assert wall.panels[2].hexes == [HexCoord(6, 5), HexCoord(7, 5)]

    def test_odd_hex_count_last_panel_has_one_hex(self):
        action = _wall_of_fire_action()
        hexes = [HexCoord(2, 5), HexCoord(3, 5), HexCoord(4, 5)]  # 3 hexes

        wall = create_wall(action, "wizard_1", hexes)

        assert wall is not None
        assert len(wall.panels) == 2
        assert wall.panels[0].hexes == [HexCoord(2, 5), HexCoord(3, 5)]
        assert wall.panels[1].hexes == [HexCoord(4, 5)]

    def test_occupied_hexes_set_from_input(self):
        action = _wall_of_fire_action()
        hexes = _sample_wall_hexes()

        wall = create_wall(action, "wizard_1", hexes)

        assert wall is not None
        assert wall.occupied_hexes == set(hexes)

    def test_wall_of_fire_pattern(self):
        """Wall of Fire: damage_on_enter=5d8, damage_type=fire, damage_side=one_side."""
        action = _wall_of_fire_action()
        hexes = [HexCoord(0, 0), HexCoord(1, 0)]
        side = {HexCoord(0, 1), HexCoord(1, 1)}

        wall = create_wall(action, "caster_1", hexes, damage_side_hexes=side)

        assert wall is not None
        assert wall.damage_on_enter == "5d8"
        assert wall.damage_type == "fire"
        assert wall.damage_side == "one_side"
        assert wall.damage_side_hexes == side


# ------------------------------------------------------------------
# WallPanel tests
# ------------------------------------------------------------------

class TestWallPanel:
    """Tests for the WallPanel dataclass."""

    def test_destructible_panel_takes_damage(self):
        panel = WallPanel(
            hexes=[HexCoord(2, 5), HexCoord(3, 5)],
            max_hp=15,
            current_hp=15,
        )

        assert panel.is_destroyed is False
        panel.current_hp = panel.current_hp - 10
        assert panel.current_hp == 5
        assert panel.is_destroyed is False

    def test_destructible_panel_destroyed_at_zero_hp(self):
        panel = WallPanel(
            hexes=[HexCoord(2, 5), HexCoord(3, 5)],
            max_hp=15,
            current_hp=15,
        )

        panel.current_hp = 0
        assert panel.is_destroyed is True

    def test_indestructible_panel_ignores_damage(self):
        panel = WallPanel(
            hexes=[HexCoord(2, 5), HexCoord(3, 5)],
            max_hp=None,
            current_hp=None,
        )

        assert panel.is_destroyed is False


# ------------------------------------------------------------------
# ActiveWall tests
# ------------------------------------------------------------------

class TestActiveWall:
    """Tests for the ActiveWall dataclass."""

    def test_get_wall_hexes_excludes_destroyed_panels(self):
        panel_a = WallPanel(
            hexes=[HexCoord(2, 5), HexCoord(3, 5)],
            max_hp=15,
            current_hp=15,
        )
        panel_b = WallPanel(
            hexes=[HexCoord(4, 5), HexCoord(5, 5)],
            max_hp=15,
            current_hp=0,  # Destroyed
        )
        wall = ActiveWall(
            name="Wall of Stone",
            source_id="wizard_1",
            panels=[panel_a, panel_b],
        )

        hexes = wall.get_wall_hexes()

        assert HexCoord(2, 5) in hexes
        assert HexCoord(3, 5) in hexes
        assert HexCoord(4, 5) not in hexes
        assert HexCoord(5, 5) not in hexes

    def test_is_blocking_hex_with_movement_blocked(self):
        wall = ActiveWall(
            name="Wall of Force",
            source_id="wizard_1",
            panels=[WallPanel(hexes=[HexCoord(3, 3)], max_hp=None)],
            blocks_movement=True,
        )

        assert wall.is_blocking_hex(HexCoord(3, 3)) is True
        assert wall.is_blocking_hex(HexCoord(4, 4)) is False

    def test_is_blocking_hex_with_movement_not_blocked(self):
        wall = ActiveWall(
            name="Wall of Fire",
            source_id="wizard_1",
            panels=[WallPanel(hexes=[HexCoord(3, 3)], max_hp=None)],
            blocks_movement=False,
        )

        assert wall.is_blocking_hex(HexCoord(3, 3)) is False

    def test_damage_panel_destroys_panel(self):
        panel_a = WallPanel(
            hexes=[HexCoord(2, 5), HexCoord(3, 5)],
            max_hp=15,
            current_hp=15,
        )
        panel_b = WallPanel(
            hexes=[HexCoord(4, 5), HexCoord(5, 5)],
            max_hp=15,
            current_hp=15,
        )
        wall = ActiveWall(
            name="Wall of Stone",
            source_id="wizard_1",
            panels=[panel_a, panel_b],
            blocks_movement=True,
        )

        # Destroy first panel
        destroyed = wall.damage_panel(0, 20)
        assert destroyed is True
        assert wall.panels[0].current_hp == 0

        # Second panel still blocks
        assert wall.is_blocking_hex(HexCoord(4, 5)) is True
        # First panel no longer blocks
        assert wall.is_blocking_hex(HexCoord(2, 5)) is False

    def test_damage_panel_indestructible_returns_false(self):
        wall = ActiveWall(
            name="Wall of Force",
            source_id="wizard_1",
            panels=[WallPanel(hexes=[HexCoord(2, 5)], max_hp=None, current_hp=None)],
        )

        result = wall.damage_panel(0, 100)
        assert result is False

    def test_damage_panel_invalid_index_returns_false(self):
        wall = ActiveWall(
            name="Wall of Stone",
            source_id="wizard_1",
            panels=[WallPanel(hexes=[HexCoord(2, 5)], max_hp=15, current_hp=15)],
        )

        result = wall.damage_panel(5, 10)
        assert result is False

    def test_is_blocking_los_hex(self):
        wall = ActiveWall(
            name="Wall of Force",
            source_id="wizard_1",
            panels=[WallPanel(hexes=[HexCoord(3, 3)], max_hp=None)],
            blocks_los=True,
        )

        assert wall.is_blocking_los_hex(HexCoord(3, 3)) is True
        assert wall.is_blocking_los_hex(HexCoord(4, 4)) is False

    def test_is_blocking_los_hex_false_when_not_blocking(self):
        wall = ActiveWall(
            name="Wall of Fire",
            source_id="wizard_1",
            panels=[WallPanel(hexes=[HexCoord(3, 3)], max_hp=None)],
            blocks_los=False,
        )

        assert wall.is_blocking_los_hex(HexCoord(3, 3)) is False


# ------------------------------------------------------------------
# Module-level query function tests
# ------------------------------------------------------------------

class TestQueryFunctions:
    """Tests for module-level query functions."""

    def test_get_wall_at_hex_finds_wall(self):
        wall = ActiveWall(
            name="Wall of Force",
            source_id="wizard_1",
            panels=[WallPanel(hexes=[HexCoord(3, 3), HexCoord(4, 3)], max_hp=None)],
        )

        result = get_wall_at_hex([wall], HexCoord(3, 3))
        assert result is wall

    def test_get_wall_at_hex_returns_none(self):
        wall = ActiveWall(
            name="Wall of Force",
            source_id="wizard_1",
            panels=[WallPanel(hexes=[HexCoord(3, 3)], max_hp=None)],
        )

        result = get_wall_at_hex([wall], HexCoord(10, 10))
        assert result is None

    def test_is_hex_blocked_by_wall_multiple_walls(self):
        wall_a = ActiveWall(
            name="Wall of Stone",
            source_id="wizard_1",
            panels=[WallPanel(hexes=[HexCoord(3, 3)], max_hp=15, current_hp=15)],
            blocks_movement=True,
        )
        wall_b = ActiveWall(
            name="Wall of Force",
            source_id="wizard_2",
            panels=[WallPanel(hexes=[HexCoord(5, 5)], max_hp=None)],
            blocks_movement=True,
        )

        assert is_hex_blocked_by_wall([wall_a, wall_b], HexCoord(3, 3)) is True
        assert is_hex_blocked_by_wall([wall_a, wall_b], HexCoord(5, 5)) is True
        assert is_hex_blocked_by_wall([wall_a, wall_b], HexCoord(7, 7)) is False

    def test_is_hex_blocked_non_blocking_wall(self):
        wall = ActiveWall(
            name="Wall of Fire",
            source_id="wizard_1",
            panels=[WallPanel(hexes=[HexCoord(3, 3)], max_hp=None)],
            blocks_movement=False,
        )

        assert is_hex_blocked_by_wall([wall], HexCoord(3, 3)) is False

    def test_is_los_blocked_by_wall(self):
        wall = ActiveWall(
            name="Wall of Force",
            source_id="wizard_1",
            panels=[WallPanel(hexes=[HexCoord(3, 3)], max_hp=None)],
            blocks_los=True,
        )
        path = [HexCoord(1, 3), HexCoord(2, 3), HexCoord(3, 3), HexCoord(4, 3), HexCoord(5, 3)]

        result = is_los_blocked_by_wall(
            [wall],
            from_hex=HexCoord(1, 3),
            to_hex=HexCoord(5, 3),
            path_hexes=path,
        )

        assert result is True

    def test_is_los_not_blocked_by_non_los_wall(self):
        wall = ActiveWall(
            name="Wall of Fire",
            source_id="wizard_1",
            panels=[WallPanel(hexes=[HexCoord(3, 3)], max_hp=None)],
            blocks_los=False,
        )
        path = [HexCoord(1, 3), HexCoord(2, 3), HexCoord(3, 3), HexCoord(4, 3), HexCoord(5, 3)]

        result = is_los_blocked_by_wall(
            [wall],
            from_hex=HexCoord(1, 3),
            to_hex=HexCoord(5, 3),
            path_hexes=path,
        )

        assert result is False

    def test_is_los_not_blocked_at_endpoints(self):
        """LOS check skips the from_hex and to_hex."""
        wall = ActiveWall(
            name="Wall of Force",
            source_id="wizard_1",
            panels=[WallPanel(hexes=[HexCoord(1, 3), HexCoord(5, 3)], max_hp=None)],
            blocks_los=True,
        )
        path = [HexCoord(1, 3), HexCoord(5, 3)]

        result = is_los_blocked_by_wall(
            [wall],
            from_hex=HexCoord(1, 3),
            to_hex=HexCoord(5, 3),
            path_hexes=path,
        )

        assert result is False

    def test_empty_walls_list(self):
        assert is_hex_blocked_by_wall([], HexCoord(3, 3)) is False
        assert get_wall_at_hex([], HexCoord(3, 3)) is None
        assert is_los_blocked_by_wall(
            [], HexCoord(1, 1), HexCoord(5, 5), [HexCoord(3, 3)]
        ) is False
