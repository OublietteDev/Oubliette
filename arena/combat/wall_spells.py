"""Wall spell mechanics — barrier creation, damage, and properties.

Wall of Fire, Wall of Force, Wall of Stone, etc.
Walls are placed on the hex grid as a series of hexes forming a line.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arena.grid.coordinates import HexCoord
from arena.models.actions import Action


@dataclass
class WallPanel:
    """A single 10ft (2-hex) panel of a wall."""

    hexes: list[HexCoord] = field(default_factory=list)
    max_hp: int | None = None  # None = indestructible
    current_hp: int | None = None

    @property
    def is_destroyed(self) -> bool:
        if self.max_hp is None:
            return False
        return (self.current_hp or 0) <= 0


@dataclass
class ActiveWall:
    """A wall spell currently active on the battlefield."""

    name: str  # Action name (e.g., "Wall of Fire")
    source_id: str  # Creature ID of the caster
    panels: list[WallPanel] = field(default_factory=list)
    blocks_movement: bool = True
    blocks_los: bool = False
    damage_on_enter: str | None = None  # Dice expression
    damage_type: str | None = None
    damage_side: str | None = None  # "one_side" or None
    damage_side_hexes: set[HexCoord] = field(default_factory=set)
    concentration_linked: bool = False  # Removed when concentration ends
    occupied_hexes: set[HexCoord] = field(default_factory=set)

    def get_wall_hexes(self) -> set[HexCoord]:
        """Get all hexes occupied by non-destroyed panels."""
        hexes: set[HexCoord] = set()
        for panel in self.panels:
            if not panel.is_destroyed:
                hexes.update(panel.hexes)
        return hexes

    def is_blocking_hex(self, hex_coord: HexCoord) -> bool:
        """Check if a hex is blocked by this wall (for movement)."""
        if not self.blocks_movement:
            return False
        return hex_coord in self.get_wall_hexes()

    def is_blocking_los_hex(self, hex_coord: HexCoord) -> bool:
        """Check if a hex blocks line of sight."""
        if not self.blocks_los:
            return False
        return hex_coord in self.get_wall_hexes()

    def damage_panel(self, panel_index: int, damage: int) -> bool:
        """Apply damage to a specific panel. Returns True if panel is destroyed."""
        if panel_index >= len(self.panels):
            return False
        panel = self.panels[panel_index]
        if panel.max_hp is None:
            return False  # Indestructible
        panel.current_hp = max(0, (panel.current_hp or 0) - damage)
        return panel.is_destroyed


def create_wall(
    action: Action,
    caster_id: str,
    wall_hexes: list[HexCoord],
    damage_side_hexes: set[HexCoord] | None = None,
) -> ActiveWall | None:
    """Create an ActiveWall from an Action with wall properties.

    Args:
        action: The wall spell action.
        caster_id: ID of the casting creature.
        wall_hexes: List of hex coordinates forming the wall path.
        damage_side_hexes: Hexes on the damage side (for Wall of Fire).

    Returns:
        An ActiveWall instance, or None if the action isn't a wall spell.
    """
    if not action.is_wall:
        return None

    # Create panels (every 2 hexes = one 10ft panel)
    panels: list[WallPanel] = []
    panel_hexes: list[HexCoord] = []
    for i, hex_coord in enumerate(wall_hexes):
        panel_hexes.append(hex_coord)
        if len(panel_hexes) == 2 or i == len(wall_hexes) - 1:
            panel = WallPanel(
                hexes=list(panel_hexes),
                max_hp=action.wall_hp_per_panel,
                current_hp=action.wall_hp_per_panel,
            )
            panels.append(panel)
            panel_hexes = []

    return ActiveWall(
        name=action.name,
        source_id=caster_id,
        panels=panels,
        blocks_movement=action.wall_blocks_movement,
        blocks_los=action.wall_blocks_los,
        damage_on_enter=action.wall_damage_on_enter,
        damage_type=action.wall_damage_type,
        damage_side=action.wall_damage_side,
        damage_side_hexes=set(damage_side_hexes or set()),
        concentration_linked=action.requires_concentration,
        occupied_hexes=set(wall_hexes),
    )


def get_wall_at_hex(
    walls: list[ActiveWall], hex_coord: HexCoord
) -> ActiveWall | None:
    """Find a wall that occupies a specific hex."""
    for wall in walls:
        if hex_coord in wall.get_wall_hexes():
            return wall
    return None


def is_hex_blocked_by_wall(
    walls: list[ActiveWall], hex_coord: HexCoord
) -> bool:
    """Check if any wall blocks movement through a hex."""
    return any(wall.is_blocking_hex(hex_coord) for wall in walls)


def is_los_blocked_by_wall(
    walls: list[ActiveWall],
    from_hex: HexCoord,
    to_hex: HexCoord,
    path_hexes: list[HexCoord],
) -> bool:
    """Check if any wall blocks line of sight along a path.

    Simplified: checks if any hex in the path is a LOS-blocking wall hex.
    """
    for hex_coord in path_hexes:
        if hex_coord == from_hex or hex_coord == to_hex:
            continue
        for wall in walls:
            if wall.is_blocking_los_hex(hex_coord):
                return True
    return False
