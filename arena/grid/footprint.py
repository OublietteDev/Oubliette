"""Multi-hex creature footprint definitions and utilities.

Defines which hexes a creature occupies based on its size category.
Uses cube-coordinate offsets for position-independent geometry,
converting to/from even-q offset coordinates at the boundary.
"""

from __future__ import annotations

from arena.grid.coordinates import HexCoord
from arena.models.character import CreatureSize


# ---------------------------------------------------------------------------
# Cube-coordinate offsets for each size.
# (dx, dy, dz) offsets from the anchor hex.
# ---------------------------------------------------------------------------

_FOOTPRINT_OFFSETS: dict[CreatureSize, list[tuple[int, int, int]]] = {
    CreatureSize.TINY: [(0, 0, 0)],
    CreatureSize.SMALL: [(0, 0, 0)],
    CreatureSize.MEDIUM: [(0, 0, 0)],
    # Large: upward-pointing triangle (anchor at bottom, two hexes above)
    CreatureSize.LARGE: [
        (0, 0, 0),      # anchor (bottom)
        (0, 1, -1),     # above-left
        (1, 0, -1),     # above-right
    ],
    # Huge: center hex + 6 neighbors ("flower")
    CreatureSize.HUGE: [
        (0, 0, 0),      # center
        (1, -1, 0),     # E
        (1, 0, -1),     # NE
        (0, 1, -1),     # NW
        (-1, 1, 0),     # W
        (-1, 0, 1),     # SW
        (0, -1, 1),     # SE
    ],
    # Gargantuan: center + ring 1 (6) + ring 2 (12) = 19 hexes
    CreatureSize.GARGANTUAN: [
        # Ring 0 (center)
        (0, 0, 0),
        # Ring 1
        (1, -1, 0), (1, 0, -1), (0, 1, -1),
        (-1, 1, 0), (-1, 0, 1), (0, -1, 1),
        # Ring 2
        (2, -2, 0), (2, -1, -1), (2, 0, -2),
        (1, 1, -2), (0, 2, -2), (-1, 2, -1),
        (-2, 2, 0), (-2, 1, 1), (-2, 0, 2),
        (-1, -1, 2), (0, -2, 2), (1, -2, 1),
    ],
}


def _cube_to_offset(x: int, y: int, z: int) -> HexCoord:
    """Convert cube coordinates to even-q offset.

    Inverse of ``HexCoord._to_cube()``.
    """
    q = x
    r = z + (x - (x & 1)) // 2
    return HexCoord(q, r)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_footprint_hex_count(size: CreatureSize) -> int:
    """Return the number of hexes in a creature's footprint."""
    return len(_FOOTPRINT_OFFSETS.get(size, [(0, 0, 0)]))


def get_occupied_hexes(anchor: HexCoord, size: CreatureSize) -> list[HexCoord]:
    """Get all hex coordinates occupied by a creature of the given size.

    Args:
        anchor: The anchor/position hex coordinate (even-q offset).
        size: The creature's size category.

    Returns:
        List of HexCoord in even-q offset that the creature occupies.
        For SMALL/MEDIUM/TINY, returns ``[anchor]``.
    """
    offsets = _FOOTPRINT_OFFSETS.get(size, [(0, 0, 0)])
    if len(offsets) == 1:
        return [anchor]

    ax, ay, az = anchor._to_cube()
    return [_cube_to_offset(ax + dx, ay + dy, az + dz) for dx, dy, dz in offsets]


def get_footprint_center_pixel(
    anchor: HexCoord, size: CreatureSize, hex_size: float
) -> tuple[float, float]:
    """Get the pixel-space centroid of a creature's footprint.

    For single-hex creatures, returns the anchor's pixel position.
    For multi-hex creatures, returns the average of all hex centres.
    """
    hexes = get_occupied_hexes(anchor, size)
    if len(hexes) == 1:
        return hexes[0].to_pixel(hex_size)

    total_x, total_y = 0.0, 0.0
    for h in hexes:
        px, py = h.to_pixel(hex_size)
        total_x += px
        total_y += py
    return (total_x / len(hexes), total_y / len(hexes))


def is_valid_placement(
    anchor: HexCoord,
    size: CreatureSize,
    grid,
    exclude_creature_id: str | None = None,
    dead_creature_ids: set[str] | None = None,
) -> bool:
    """Check if a creature can be placed at *anchor*.

    All hexes in the footprint must be within grid bounds, passable,
    and unoccupied (or occupied by *exclude_creature_id* or a dead
    creature in *dead_creature_ids*).
    """
    dead_ids = dead_creature_ids or set()
    for h in get_occupied_hexes(anchor, size):
        if not grid.is_valid(h):
            return False
        if not grid.is_passable(h):
            return False
        cell = grid.get_cell(h)
        if cell and cell.occupant_id is not None:
            if (
                cell.occupant_id != exclude_creature_id
                and cell.occupant_id not in dead_ids
            ):
                return False
    return True


def min_distance_between(
    anchor_a: HexCoord,
    size_a: CreatureSize,
    anchor_b: HexCoord,
    size_b: CreatureSize,
) -> int:
    """Minimum hex distance between any hex of creature A and creature B."""
    hexes_a = get_occupied_hexes(anchor_a, size_a)
    hexes_b = get_occupied_hexes(anchor_b, size_b)
    return min(a.distance_to(b) for a in hexes_a for b in hexes_b)


def get_footprint_boundary(
    anchor: HexCoord, size: CreatureSize
) -> list[HexCoord]:
    """Get hexes adjacent to (but not part of) the creature's footprint.

    Useful for determining melee adjacency.
    """
    occupied = set((h.q, h.r) for h in get_occupied_hexes(anchor, size))
    boundary: set[tuple[int, int]] = set()
    for h in get_occupied_hexes(anchor, size):
        for n in h.neighbors():
            key = (n.q, n.r)
            if key not in occupied:
                boundary.add(key)
    return [HexCoord(q, r) for q, r in boundary]
