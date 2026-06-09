"""Hex coordinate math using axial coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class HexCoord:
    """Axial hex coordinate (q, r)."""

    q: int  # Column
    r: int  # Row

    def _to_cube(self) -> tuple[int, int, int]:
        """Convert even-q offset coordinate to cube coordinates."""
        cx = self.q
        cz = self.r - (self.q - (self.q & 1)) // 2
        cy = -cx - cz
        return (cx, cy, cz)

    @property
    def s(self) -> int:
        """Cube coordinate s (derived via offset-to-cube conversion)."""
        _, _, cz = self._to_cube()
        return cz

    def distance_to(self, other: HexCoord) -> int:
        """Calculate distance in hexes to another coordinate."""
        ax, ay, az = self._to_cube()
        bx, by, bz = other._to_cube()
        return (abs(ax - bx) + abs(ay - by) + abs(az - bz)) // 2

    def neighbors(self) -> list[HexCoord]:
        """Get all 6 adjacent hex coordinates (even-q offset convention).

        In even-q offset, the neighbor directions differ depending on
        whether the column (q) is even or odd.
        """
        if self.q & 1:  # Odd column
            directions = [
                (1, 0), (1, 1), (0, 1),
                (-1, 1), (-1, 0), (0, -1),
            ]
        else:  # Even column
            directions = [
                (1, -1), (1, 0), (0, 1),
                (-1, 0), (-1, -1), (0, -1),
            ]
        return [HexCoord(self.q + dq, self.r + dr) for dq, dr in directions]

    def to_pixel(self, size: float) -> tuple[float, float]:
        """Convert to pixel coordinates (flat-top hexagon, even-q offset).

        Uses even-q offset convention so that grid coordinates (col, row)
        produce a rectangular grid layout with staggered columns.
        Even columns are flush; odd columns are shifted down by half a hex.
        """
        x = size * 3 / 2 * self.q
        y = size * sqrt(3) * (self.r + 0.5 * (self.q & 1))
        return (x, y)

    @staticmethod
    def from_pixel(x: float, y: float, size: float) -> HexCoord:
        """Convert pixel coordinates to offset hex coordinate (with rounding).

        Inverse of to_pixel using even-q offset convention.
        """
        # Determine q from x
        q_frac = (2 / 3 * x) / size
        q = round(q_frac)

        # Determine r from y, accounting for the offset of odd columns
        r_frac = y / (size * sqrt(3)) - 0.5 * (q & 1)
        r = round(r_frac)

        return HexCoord(int(q), int(r))

    def __add__(self, other: HexCoord) -> HexCoord:
        """Add two hex coordinates."""
        return HexCoord(self.q + other.q, self.r + other.r)

    def __sub__(self, other: HexCoord) -> HexCoord:
        """Subtract two hex coordinates."""
        return HexCoord(self.q - other.q, self.r - other.r)
