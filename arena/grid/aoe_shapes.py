"""AoE shape geometry (D-AOE-1).

Which hexes a spell's area covers, by shape:

- **sphere / cylinder** — every hex within ``radius`` of a center hex.
- **cube** — a square of side ``size`` around a center hex (offset-coordinate
  approximation; a hex grid has no true axis-aligned square).
- **line** — a 5-ft-wide line emanating from the caster (origin) toward an aim
  hex, extended to its full ``length`` (Lightning Bolt). Reuses the cube-lerp
  ``hex_line`` already used by line-of-sight.
- **cone** — a widening wedge from the caster toward an aim hex, length ``length``
  and (RAW) as wide as it is long at the far end.

Spheres and cubes are *placed* (the aim hex is the center). Lines and cones
*emanate* (the aim hex only sets direction; the shape starts at the caster).

Simplifications (a first pass; polish with the wall/LOS work): areas are not
clipped at walls/total cover, and the cone is an angular approximation rather
than an exact RAW template.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from arena.grid.coordinates import HexCoord
from arena.grid.line_of_sight import (
    hex_line,
    _offset_to_cube,
    _cube_to_offset,
    _cube_round,
)
from arena.models.actions import TargetType

if TYPE_CHECKING:
    from arena.grid.hexgrid import HexGrid
    from arena.models.actions import Action


def _grid_hexes(grid: "HexGrid"):
    for q in range(grid.width):
        for r in range(grid.height):
            yield HexCoord(q, r)


# ── Placed shapes (aim hex = center) ──────────────────────────────────


def hexes_in_sphere(center: HexCoord, radius_feet: float, grid: "HexGrid") -> set[HexCoord]:
    """Every grid hex within ``radius_feet`` of ``center`` (Fireball, Confusion)."""
    radius = radius_feet / 5
    return {h for h in _grid_hexes(grid) if center.distance_to(h) <= radius}


def hexes_in_cube(center: HexCoord, size_feet: float, grid: "HexGrid") -> set[HexCoord]:
    """A square of side ``size_feet`` centered on ``center`` (Thunderwave, Slow).

    Approximated as a square in offset (q, r) space — a hex grid has no exact
    axis-aligned square, but for a 15-/40-ft cube this is the right hex count
    and shape to within the grid's stagger.
    """
    half = (size_feet / 5) / 2
    return {
        h for h in _grid_hexes(grid)
        if abs(h.q - center.q) <= half and abs(h.r - center.r) <= half
    }


# ── Emanating shapes (aim hex = direction) ────────────────────────────


def _extend_to_length(origin: HexCoord, aim: HexCoord, length_hexes: int) -> HexCoord:
    """The hex ``length_hexes`` away from ``origin`` in the direction of ``aim``."""
    dist = origin.distance_to(aim)
    if dist == 0:
        return origin
    a = _offset_to_cube(origin)
    b = _offset_to_cube(aim)
    scale = length_hexes / dist
    fx = a[0] + (b[0] - a[0]) * scale
    fy = a[1] + (b[1] - a[1]) * scale
    fz = a[2] + (b[2] - a[2]) * scale
    return _cube_to_offset(*_cube_round(fx, fy, fz))


def hexes_in_line(
    origin: HexCoord, aim: HexCoord, length_feet: float, grid: "HexGrid",
) -> set[HexCoord]:
    """A 5-ft-wide line from ``origin`` toward ``aim``, length ``length_feet``.

    The aim hex only picks the direction; the line always runs its full length.
    Excludes the origin (the caster's own hex).
    """
    if origin == aim:
        return set()
    length_hexes = max(1, round(length_feet / 5))
    far = _extend_to_length(origin, aim, length_hexes)
    return {h for h in hex_line(origin, far)[1:] if grid.is_valid(h)}


def hexes_in_cone(
    origin: HexCoord, aim: HexCoord, length_feet: float, grid: "HexGrid",
    half_angle_deg: float = 30.0,
) -> set[HexCoord]:
    """A cone of length ``length_feet`` from ``origin`` toward ``aim``.

    A hex is in the cone if it is within ``length`` of the origin and within
    ``half_angle_deg`` of the aim direction (measured in pixel space, so the
    angle is true regardless of the hex stagger). The default half-angle keeps
    the cone roughly "as wide as it is long" while staying playable on hexes.
    """
    if origin == aim:
        return set()
    length_hexes = length_feet / 5
    ox, oy = origin.to_pixel(1.0)
    ax, ay = aim.to_pixel(1.0)
    aim_ang = math.atan2(ay - oy, ax - ox)
    half = math.radians(half_angle_deg)

    out: set[HexCoord] = set()
    for h in _grid_hexes(grid):
        d = origin.distance_to(h)
        if d < 1 or d > length_hexes:
            continue
        hx, hy = h.to_pixel(1.0)
        ang = math.atan2(hy - oy, hx - ox)
        diff = abs((ang - aim_ang + math.pi) % (2 * math.pi) - math.pi)
        if diff <= half:
            out.add(h)
    return out


# ── Dispatcher ────────────────────────────────────────────────────────


def aoe_hexes(
    action: "Action", origin: HexCoord, aim: HexCoord, grid: "HexGrid",
) -> set[HexCoord]:
    """The set of hexes an AoE action covers.

    ``origin`` is the caster's anchor; ``aim`` is the targeted/hovered hex.
    Spheres/cubes/cylinders treat ``aim`` as the center; lines/cones treat it
    as the direction and emanate from ``origin``.
    """
    size = action.area_size or action.range
    tt = action.target_type
    if tt == TargetType.AREA_LINE:
        return hexes_in_line(origin, aim, size, grid)
    if tt == TargetType.AREA_CONE:
        return hexes_in_cone(origin, aim, size, grid)
    if tt == TargetType.AREA_CUBE:
        return hexes_in_cube(aim, size, grid)
    # sphere, cylinder, and any other area_* default to a radius burst
    return hexes_in_sphere(aim, size, grid)
