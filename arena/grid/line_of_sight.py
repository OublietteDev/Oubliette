"""Line of sight and cover calculations on the hex grid."""

from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.encounter import TerrainType


def _offset_to_cube(coord: HexCoord) -> tuple[int, int, int]:
    """Convert even-q offset to cube coordinates."""
    return coord._to_cube()


def _cube_to_offset(x: int, y: int, z: int) -> HexCoord:
    """Convert cube coordinates to even-q offset."""
    q = x
    r = z + (x - (x & 1)) // 2
    return HexCoord(q, r)


def _cube_lerp(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
    t: float,
) -> tuple[float, float, float]:
    """Linearly interpolate between two cube coordinates."""
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def _cube_round(x: float, y: float, z: float) -> tuple[int, int, int]:
    """Round fractional cube coordinates to nearest hex."""
    rx, ry, rz = round(x), round(y), round(z)
    dx, dy, dz = abs(rx - x), abs(ry - y), abs(rz - z)

    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy > dz:
        ry = -rx - rz
    else:
        rz = -rx - ry

    return (rx, ry, rz)


def hex_line(origin: HexCoord, target: HexCoord) -> list[HexCoord]:
    """Get all hexes along a line from origin to target.

    Uses cube coordinate linear interpolation. Returns the list of
    hexes in order from origin to target, inclusive.
    """
    n = origin.distance_to(target)
    if n == 0:
        return [origin]

    a_cube = _offset_to_cube(origin)
    b_cube = _offset_to_cube(target)

    results = []
    for i in range(n + 1):
        t = i / n
        fx, fy, fz = _cube_lerp(a_cube, b_cube, t)
        rx, ry, rz = _cube_round(fx, fy, fz)
        results.append(_cube_to_offset(rx, ry, rz))

    return results


def has_line_of_sight(
    origin: HexCoord,
    target: HexCoord,
    grid: HexGrid,
    los_blocked_hexes: set[tuple[int, int]] | None = None,
) -> bool:
    """Check if origin has unobstructed line of sight to target.

    LOS is blocked by WALL and COVER_FULL terrain in any intervening
    hex (not including origin or target hexes themselves).  Additionally,
    hexes in *los_blocked_hexes* (e.g., from wall spells) block LOS.

    Args:
        origin: Observer's hex coordinate.
        target: Target's hex coordinate.
        grid: The hex grid.
        los_blocked_hexes: Optional set of (q, r) tuples that block LOS
            (e.g., Wall of Force, Wall of Stone hexes with blocks_los).

    Returns:
        True if line of sight is clear.
    """
    if origin == target:
        return True

    blocking = (TerrainType.WALL, TerrainType.COVER_FULL)
    _los_blocked = los_blocked_hexes or set()
    line = hex_line(origin, target)

    # Check intervening hexes (not origin or target)
    for coord in line[1:-1]:
        if (coord.q, coord.r) in _los_blocked:
            return False
        cell = grid.get_cell(coord)
        if cell is None:
            return False  # Off-grid = blocked
        if cell.terrain in blocking:
            return False

    return True


def get_cover(
    attacker_pos: HexCoord,
    target_pos: HexCoord,
    grid: HexGrid,
) -> int:
    """Calculate cover bonus to AC for the target.

    Checks intervening hexes along the line from attacker to target.
    Returns the highest cover bonus found.

    Cover bonuses:
    - No cover: +0
    - Half cover (COVER_HALF or occupied hex): +2
    - Three-quarters cover (COVER_THREE_QUARTERS): +5
    - Full cover: attack is impossible (handled by has_line_of_sight)

    Args:
        attacker_pos: Attacker's hex coordinate.
        target_pos: Target's hex coordinate.
        grid: The hex grid.

    Returns:
        Cover bonus to AC (0, 2, or 5).
    """
    if attacker_pos == target_pos:
        return 0

    # Adjacent hexes have no cover from intervening terrain
    if attacker_pos.distance_to(target_pos) <= 1:
        return 0

    line = hex_line(attacker_pos, target_pos)
    max_cover = 0

    # Check intervening hexes (not attacker or target)
    for coord in line[1:-1]:
        cell = grid.get_cell(coord)
        if cell is None:
            continue

        if cell.terrain == TerrainType.COVER_THREE_QUARTERS:
            max_cover = max(max_cover, 5)
        elif cell.terrain == TerrainType.COVER_HALF:
            max_cover = max(max_cover, 2)
        elif cell.occupant_id is not None:
            # Other creatures provide half cover
            max_cover = max(max_cover, 2)

    return max_cover
