"""Hex grid data structure."""

from __future__ import annotations

from dataclasses import dataclass, field

from .coordinates import HexCoord
from arena.models.encounter import TerrainType
from arena.models.character import CreatureSize


@dataclass
class HexCell:
    """A single cell in the hex grid."""

    coord: HexCoord
    terrain: TerrainType = TerrainType.NORMAL
    occupant_id: str | None = None  # ID of creature occupying this hex


@dataclass
class HexGrid:
    """The hex grid data structure."""

    width: int
    height: int
    cells: dict[tuple[int, int], HexCell] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize all cells."""
        for q in range(self.width):
            for r in range(self.height):
                coord = HexCoord(q, r)
                self.cells[(q, r)] = HexCell(coord=coord)

    def get_cell(self, coord: HexCoord) -> HexCell | None:
        """Get a cell by its coordinate."""
        return self.cells.get((coord.q, coord.r))

    def is_valid(self, coord: HexCoord) -> bool:
        """Check if a coordinate is within the grid bounds."""
        return 0 <= coord.q < self.width and 0 <= coord.r < self.height

    def is_passable(self, coord: HexCoord) -> bool:
        """Check if a hex can be moved through."""
        cell = self.get_cell(coord)
        if cell is None:
            return False
        if cell.terrain in (TerrainType.WALL, TerrainType.PIT):
            return False
        return True

    def is_occupied(self, coord: HexCoord) -> bool:
        """Check if a hex is occupied by a creature."""
        cell = self.get_cell(coord)
        return cell is not None and cell.occupant_id is not None

    def get_movement_cost(self, coord: HexCoord) -> int:
        """Get movement cost for entering a hex (in feet)."""
        cell = self.get_cell(coord)
        if cell is None:
            return 999  # Impassable
        if cell.terrain == TerrainType.DIFFICULT:
            return 10  # 2x movement cost
        if cell.terrain == TerrainType.WATER:
            return 10  # Typically difficult terrain
        return 5  # Normal movement

    def set_terrain(self, coord: HexCoord, terrain: TerrainType) -> None:
        """Set the terrain type for a hex."""
        cell = self.get_cell(coord)
        if cell:
            cell.terrain = terrain

    def place_creature(
        self,
        coord: HexCoord,
        creature_id: str,
        size: CreatureSize = CreatureSize.MEDIUM,
    ) -> bool:
        """Place a creature on the grid.

        For multi-hex creatures, places the creature_id on ALL hexes
        of the footprint.  Returns False if any hex is out of bounds
        or already occupied.

        Args:
            coord: Anchor hex coordinate.
            creature_id: Unique creature identifier.
            size: Creature size (determines footprint).
        """
        from arena.grid.footprint import get_occupied_hexes

        hexes = get_occupied_hexes(coord, size)

        # Validate all hexes first
        for h in hexes:
            cell = self.get_cell(h)
            if cell is None or cell.occupant_id is not None:
                return False

        # Place on all hexes
        for h in hexes:
            self.get_cell(h).occupant_id = creature_id  # type: ignore[union-attr]
        return True

    def remove_creature(
        self,
        coord: HexCoord,
        size: CreatureSize = CreatureSize.MEDIUM,
    ) -> str | None:
        """Remove a creature from all hexes of its footprint.

        Args:
            coord: Anchor hex coordinate.
            size: Creature size (determines footprint).

        Returns:
            The creature_id that was removed, or None.
        """
        from arena.grid.footprint import get_occupied_hexes

        hexes = get_occupied_hexes(coord, size)
        creature_id: str | None = None
        for h in hexes:
            cell = self.get_cell(h)
            if cell and cell.occupant_id is not None:
                creature_id = cell.occupant_id
                cell.occupant_id = None
        return creature_id

    def find_creature(self, creature_id: str) -> HexCoord | None:
        """Find a hex occupied by a creature.

        For multi-hex creatures this may return any occupied hex, not
        necessarily the anchor.  Callers that need the canonical anchor
        should use ``combatant.position`` instead.
        """
        for (q, r), cell in self.cells.items():
            if cell.occupant_id == creature_id:
                return HexCoord(q, r)
        return None
