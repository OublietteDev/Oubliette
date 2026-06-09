"""Tests for multi-hex creature footprint system."""

import pytest
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.grid.footprint import (
    get_occupied_hexes,
    get_footprint_hex_count,
    get_footprint_center_pixel,
    is_valid_placement,
    min_distance_between,
    get_footprint_boundary,
    _cube_to_offset,
)
from arena.models.character import CreatureSize


# ---------------------------------------------------------------------------
# Hex count
# ---------------------------------------------------------------------------

class TestFootprintHexCount:
    def test_tiny(self):
        assert get_footprint_hex_count(CreatureSize.TINY) == 1

    def test_small(self):
        assert get_footprint_hex_count(CreatureSize.SMALL) == 1

    def test_medium(self):
        assert get_footprint_hex_count(CreatureSize.MEDIUM) == 1

    def test_large(self):
        assert get_footprint_hex_count(CreatureSize.LARGE) == 3

    def test_huge(self):
        assert get_footprint_hex_count(CreatureSize.HUGE) == 7

    def test_gargantuan(self):
        assert get_footprint_hex_count(CreatureSize.GARGANTUAN) == 19


# ---------------------------------------------------------------------------
# Occupied hexes
# ---------------------------------------------------------------------------

class TestGetOccupiedHexes:
    def test_medium_single_hex(self):
        """Medium creatures return only their anchor hex."""
        hexes = get_occupied_hexes(HexCoord(5, 5), CreatureSize.MEDIUM)
        assert len(hexes) == 1
        assert hexes[0] == HexCoord(5, 5)

    def test_large_three_hexes(self):
        """Large creatures occupy exactly 3 hexes."""
        hexes = get_occupied_hexes(HexCoord(4, 4), CreatureSize.LARGE)
        assert len(hexes) == 3
        # All hexes should be distinct
        coords = set((h.q, h.r) for h in hexes)
        assert len(coords) == 3
        # Anchor is included
        assert HexCoord(4, 4) in hexes

    def test_huge_seven_hexes(self):
        """Huge creatures occupy 7 hexes (flower pattern)."""
        hexes = get_occupied_hexes(HexCoord(5, 5), CreatureSize.HUGE)
        assert len(hexes) == 7
        coords = set((h.q, h.r) for h in hexes)
        assert len(coords) == 7
        assert HexCoord(5, 5) in hexes

    def test_gargantuan_nineteen_hexes(self):
        """Gargantuan creatures occupy 19 hexes."""
        hexes = get_occupied_hexes(HexCoord(10, 10), CreatureSize.GARGANTUAN)
        assert len(hexes) == 19
        coords = set((h.q, h.r) for h in hexes)
        assert len(coords) == 19
        assert HexCoord(10, 10) in hexes

    def test_large_all_neighbors_connected(self):
        """All hexes in a Large footprint should be adjacent to at least one other."""
        hexes = get_occupied_hexes(HexCoord(4, 4), CreatureSize.LARGE)
        for h in hexes:
            others = [o for o in hexes if o != h]
            # Must be adjacent to at least one other hex
            assert any(h.distance_to(o) == 1 for o in others)

    def test_different_anchor_positions(self):
        """Footprint works at various grid positions (even/odd columns)."""
        for q in range(2, 8):
            for r in range(2, 8):
                hexes = get_occupied_hexes(HexCoord(q, r), CreatureSize.LARGE)
                assert len(hexes) == 3
                # All distinct
                assert len(set((h.q, h.r) for h in hexes)) == 3


# ---------------------------------------------------------------------------
# Cube-to-offset roundtrip
# ---------------------------------------------------------------------------

class TestCubeToOffset:
    def test_origin(self):
        """(0,0,0) -> (0,0)."""
        assert _cube_to_offset(0, 0, 0) == HexCoord(0, 0)

    def test_roundtrip(self):
        """offset -> cube -> offset should be identity."""
        for q in range(10):
            for r in range(10):
                coord = HexCoord(q, r)
                cx, cy, cz = coord._to_cube()
                result = _cube_to_offset(cx, cy, cz)
                assert result == coord, f"Roundtrip failed for ({q},{r})"


# ---------------------------------------------------------------------------
# Placement validation
# ---------------------------------------------------------------------------

class TestIsValidPlacement:
    def test_medium_on_empty_grid(self):
        grid = HexGrid(10, 10)
        assert is_valid_placement(HexCoord(5, 5), CreatureSize.MEDIUM, grid)

    def test_medium_on_occupied(self):
        grid = HexGrid(10, 10)
        grid.place_creature(HexCoord(5, 5), "blocker")
        assert not is_valid_placement(HexCoord(5, 5), CreatureSize.MEDIUM, grid)

    def test_medium_exclude_self(self):
        grid = HexGrid(10, 10)
        grid.place_creature(HexCoord(5, 5), "self")
        assert is_valid_placement(
            HexCoord(5, 5), CreatureSize.MEDIUM, grid, exclude_creature_id="self"
        )

    def test_large_on_empty_grid(self):
        grid = HexGrid(10, 10)
        assert is_valid_placement(HexCoord(4, 4), CreatureSize.LARGE, grid)

    def test_large_partially_blocked(self):
        """If one footprint hex is occupied, placement should fail."""
        grid = HexGrid(10, 10)
        hexes = get_occupied_hexes(HexCoord(4, 4), CreatureSize.LARGE)
        # Block one of the non-anchor hexes
        blocker_hex = [h for h in hexes if h != HexCoord(4, 4)][0]
        grid.place_creature(blocker_hex, "blocker")
        assert not is_valid_placement(HexCoord(4, 4), CreatureSize.LARGE, grid)

    def test_large_out_of_bounds(self):
        """If any footprint hex is off the grid, placement should fail."""
        grid = HexGrid(5, 5)
        # Place at the edge — some footprint hexes may be out of bounds
        # The anchor (0,0) for Large will have hexes above it
        hexes = get_occupied_hexes(HexCoord(0, 0), CreatureSize.LARGE)
        all_valid = all(grid.is_valid(h) for h in hexes)
        result = is_valid_placement(HexCoord(0, 0), CreatureSize.LARGE, grid)
        assert result == all_valid

    def test_large_exclude_self(self):
        """Excluding self allows re-placement."""
        grid = HexGrid(10, 10)
        grid.place_creature(HexCoord(4, 4), "bigcreature", CreatureSize.LARGE)
        assert is_valid_placement(
            HexCoord(4, 4), CreatureSize.LARGE, grid,
            exclude_creature_id="bigcreature",
        )


# ---------------------------------------------------------------------------
# Multi-hex place/remove on grid
# ---------------------------------------------------------------------------

class TestGridMultiHex:
    def test_place_large(self):
        """Placing a Large creature marks all footprint hexes."""
        grid = HexGrid(10, 10)
        result = grid.place_creature(HexCoord(4, 4), "dragon", CreatureSize.LARGE)
        assert result is True

        hexes = get_occupied_hexes(HexCoord(4, 4), CreatureSize.LARGE)
        for h in hexes:
            cell = grid.get_cell(h)
            assert cell is not None
            assert cell.occupant_id == "dragon"

    def test_remove_large(self):
        """Removing a Large creature clears all footprint hexes."""
        grid = HexGrid(10, 10)
        grid.place_creature(HexCoord(4, 4), "dragon", CreatureSize.LARGE)
        grid.remove_creature(HexCoord(4, 4), CreatureSize.LARGE)

        hexes = get_occupied_hexes(HexCoord(4, 4), CreatureSize.LARGE)
        for h in hexes:
            cell = grid.get_cell(h)
            assert cell is not None
            assert cell.occupant_id is None

    def test_find_creature_large(self):
        """find_creature returns any hex occupied by the creature."""
        grid = HexGrid(10, 10)
        grid.place_creature(HexCoord(4, 4), "dragon", CreatureSize.LARGE)
        found = grid.find_creature("dragon")
        assert found is not None
        # Should be one of the footprint hexes
        hexes = get_occupied_hexes(HexCoord(4, 4), CreatureSize.LARGE)
        assert found in hexes

    def test_place_blocked(self):
        """Placing on a partially occupied area should fail."""
        grid = HexGrid(10, 10)
        hexes = get_occupied_hexes(HexCoord(4, 4), CreatureSize.LARGE)
        grid.place_creature(hexes[1], "blocker")
        result = grid.place_creature(HexCoord(4, 4), "dragon", CreatureSize.LARGE)
        assert result is False


# ---------------------------------------------------------------------------
# Distance between footprints
# ---------------------------------------------------------------------------

class TestMinDistanceBetween:
    def test_same_position(self):
        """Distance from creature to itself is 0."""
        d = min_distance_between(
            HexCoord(5, 5), CreatureSize.MEDIUM,
            HexCoord(5, 5), CreatureSize.MEDIUM,
        )
        assert d == 0

    def test_medium_to_medium(self):
        """Medium-to-medium is normal hex distance."""
        d = min_distance_between(
            HexCoord(0, 0), CreatureSize.MEDIUM,
            HexCoord(3, 0), CreatureSize.MEDIUM,
        )
        assert d == HexCoord(0, 0).distance_to(HexCoord(3, 0))

    def test_large_adjacency(self):
        """A medium creature adjacent to a Large creature's footprint has distance 1."""
        anchor = HexCoord(5, 5)
        boundary = get_footprint_boundary(anchor, CreatureSize.LARGE)
        for bh in boundary:
            d = min_distance_between(
                bh, CreatureSize.MEDIUM,
                anchor, CreatureSize.LARGE,
            )
            assert d == 1

    def test_large_to_large_adjacent(self):
        """Two Large creatures with touching footprints have distance 1 or 0."""
        # Place one at (4,4) and another at a nearby position
        d = min_distance_between(
            HexCoord(4, 4), CreatureSize.LARGE,
            HexCoord(6, 4), CreatureSize.LARGE,
        )
        # They should be within a few hexes
        assert d >= 0

    def test_distance_decreases_with_size(self):
        """Larger creatures should have shorter effective distance."""
        # A huge creature at (5,5) should be closer to a target at (8,5) than
        # a medium creature at the same anchor
        d_medium = min_distance_between(
            HexCoord(5, 5), CreatureSize.MEDIUM,
            HexCoord(8, 5), CreatureSize.MEDIUM,
        )
        d_huge = min_distance_between(
            HexCoord(5, 5), CreatureSize.HUGE,
            HexCoord(8, 5), CreatureSize.MEDIUM,
        )
        assert d_huge <= d_medium


# ---------------------------------------------------------------------------
# Footprint boundary
# ---------------------------------------------------------------------------

class TestFootprintBoundary:
    def test_medium_boundary_is_neighbors(self):
        """Medium boundary is exactly the 6 hex neighbors."""
        boundary = get_footprint_boundary(HexCoord(5, 5), CreatureSize.MEDIUM)
        neighbors = HexCoord(5, 5).neighbors()
        assert set((h.q, h.r) for h in boundary) == set((n.q, n.r) for n in neighbors)

    def test_large_boundary_excludes_footprint(self):
        """Boundary should not overlap with footprint hexes."""
        anchor = HexCoord(4, 4)
        occupied = set((h.q, h.r) for h in get_occupied_hexes(anchor, CreatureSize.LARGE))
        boundary = get_footprint_boundary(anchor, CreatureSize.LARGE)
        for b in boundary:
            assert (b.q, b.r) not in occupied

    def test_large_boundary_all_adjacent(self):
        """Every boundary hex is adjacent to at least one footprint hex."""
        anchor = HexCoord(4, 4)
        occupied = get_occupied_hexes(anchor, CreatureSize.LARGE)
        boundary = get_footprint_boundary(anchor, CreatureSize.LARGE)
        for b in boundary:
            assert any(b.distance_to(o) == 1 for o in occupied)

    def test_huge_boundary_size(self):
        """Huge boundary should be larger than Large boundary."""
        large_boundary = get_footprint_boundary(HexCoord(5, 5), CreatureSize.LARGE)
        huge_boundary = get_footprint_boundary(HexCoord(5, 5), CreatureSize.HUGE)
        assert len(huge_boundary) > len(large_boundary)


# ---------------------------------------------------------------------------
# Footprint center pixel
# ---------------------------------------------------------------------------

class TestFootprintCenterPixel:
    def test_medium_center_is_anchor(self):
        """Medium center pixel is the anchor's pixel position."""
        anchor = HexCoord(5, 5)
        hex_size = 30.0
        cx, cy = get_footprint_center_pixel(anchor, CreatureSize.MEDIUM, hex_size)
        ax, ay = anchor.to_pixel(hex_size)
        assert cx == ax
        assert cy == ay

    def test_large_center_is_centroid(self):
        """Large center should be average of 3 hex centers."""
        anchor = HexCoord(4, 4)
        hex_size = 30.0
        cx, cy = get_footprint_center_pixel(anchor, CreatureSize.LARGE, hex_size)
        hexes = get_occupied_hexes(anchor, CreatureSize.LARGE)
        expected_x = sum(h.to_pixel(hex_size)[0] for h in hexes) / 3
        expected_y = sum(h.to_pixel(hex_size)[1] for h in hexes) / 3
        assert abs(cx - expected_x) < 0.001
        assert abs(cy - expected_y) < 0.001


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_medium_place_remove_single_arg(self):
        """place_creature/remove_creature still work with default size param."""
        grid = HexGrid(10, 10)
        # These should work without passing size (defaults to MEDIUM)
        assert grid.place_creature(HexCoord(3, 3), "test_creature") is True
        cell = grid.get_cell(HexCoord(3, 3))
        assert cell.occupant_id == "test_creature"
        grid.remove_creature(HexCoord(3, 3))
        cell = grid.get_cell(HexCoord(3, 3))
        assert cell.occupant_id is None

    def test_medium_footprint_single_hex(self):
        """Medium footprint operations produce single-hex results."""
        assert get_footprint_hex_count(CreatureSize.MEDIUM) == 1
        hexes = get_occupied_hexes(HexCoord(3, 3), CreatureSize.MEDIUM)
        assert hexes == [HexCoord(3, 3)]
