"""Movement tracking and execution during combat turns."""

from __future__ import annotations

from dataclasses import dataclass, field

from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.grid.pathfinding import get_reachable_hexes
from arena.combat.events import CombatEvent, CombatEventType
from arena.models.character import CreatureSize


@dataclass
class MovementTracker:
    """Tracks remaining movement for the current turn.

    Attributes:
        creature_id: ID of the creature whose movement is tracked.
        max_movement: Total movement speed in feet.
        remaining_movement: Feet of movement remaining this turn.
        has_moved: Whether the creature has moved at all this turn.
        dead_creature_ids: Creature IDs whose hexes are treated as difficult
            terrain rather than impassable (per 5e, dead creature spaces
            can be moved through).
    """

    creature_id: str
    max_movement: int
    remaining_movement: int
    has_moved: bool = False
    dead_creature_ids: set[str] = field(default_factory=set)
    blocked_hexes: set[tuple[int, int]] = field(default_factory=set)
    cost_multiplier: int = 1
    # Hexes that are difficult terrain on top of the grid (e.g. inside a
    # Spirit Guardians aura). Set per-turn by the manager; not cleared by
    # reset() — the manager refreshes it alongside blocked_hexes.
    difficult_hexes: set[tuple[int, int]] = field(default_factory=set)
    turn_start_position: HexCoord | None = None  # for move-then-strike riders (Charge)

    def reset(self, creature_id: str, speed: int,
              position: HexCoord | None = None) -> None:
        """Reset for a new creature's turn.

        Args:
            creature_id: ID of the creature taking its turn.
            speed: Walking speed in feet.
            position: The creature's position at the start of its turn (so a
                Charge rider can tell how far it moved toward its target).
        """
        self.creature_id = creature_id
        self.max_movement = speed
        self.remaining_movement = speed
        self.has_moved = False
        self.cost_multiplier = 1
        self.turn_start_position = position

    def get_reachable(
        self,
        grid: HexGrid,
        creature_size: CreatureSize = CreatureSize.MEDIUM,
        anchor_position: HexCoord | None = None,
    ) -> dict[tuple[int, int], int]:
        """Return hexes reachable with remaining movement.

        Args:
            grid: The hex grid to pathfind on.
            creature_size: Size of the creature (for footprint checks).
            anchor_position: The creature's canonical anchor position.
                For multi-hex creatures this MUST be the anchor, not an
                arbitrary occupied hex.  Falls back to ``find_creature``
                for backward compatibility.

        Returns:
            Dict mapping (q, r) tuples to movement cost in feet.
        """
        pos = anchor_position or grid.find_creature(self.creature_id)
        if pos is None:
            return {}
        return get_reachable_hexes(
            pos,
            grid,
            self.remaining_movement,
            creature_size=creature_size,
            creature_id=self.creature_id,
            dead_creature_ids=self.dead_creature_ids,
            blocked_hexes=self.blocked_hexes,
            cost_multiplier=self.cost_multiplier,
            difficult_hexes=self.difficult_hexes,
        )

    def try_move(
        self,
        target: HexCoord,
        grid: HexGrid,
        creature_size: CreatureSize = CreatureSize.MEDIUM,
        anchor_position: HexCoord | None = None,
    ) -> tuple[bool, CombatEvent | None]:
        """Attempt to move the creature to target hex.

        Args:
            target: Destination hex coordinate (anchor position).
            grid: The hex grid.
            creature_size: Size of the creature (for footprint).
            anchor_position: The creature's canonical anchor position.
                For multi-hex creatures this MUST be the anchor, not an
                arbitrary occupied hex.  Falls back to ``find_creature``
                for backward compatibility.

        Returns:
            (success, event) -- event is None on failure.
        """
        pos = anchor_position or grid.find_creature(self.creature_id)
        if pos is None:
            return False, None

        # Check reachability
        reachable = self.get_reachable(grid, creature_size, anchor_position=pos)
        target_key = (target.q, target.r)
        if target_key not in reachable:
            return False, None

        cost = reachable[target_key]
        if cost > self.remaining_movement:
            return False, None

        # Cannot move to occupied hex (for multi-hex, check entire footprint)
        from arena.grid.footprint import is_valid_placement

        if not is_valid_placement(
            target, creature_size, grid, self.creature_id,
            self.dead_creature_ids,
        ):
            return False, None

        # Execute the move
        start_key = (pos.q, pos.r)
        grid.remove_creature(pos, creature_size)

        # Clear dead creature occupants from target hexes so place_creature
        # won't reject the placement.  Per 5e, dead creature spaces are
        # treated as difficult terrain, not impassable.
        from arena.grid.footprint import get_occupied_hexes

        cleared_dead: list[tuple[HexCoord, str]] = []
        for h in get_occupied_hexes(target, creature_size):
            cell = grid.get_cell(h)
            if cell and cell.occupant_id and cell.occupant_id in self.dead_creature_ids:
                cleared_dead.append((h, cell.occupant_id))
                cell.occupant_id = None

        if not grid.place_creature(target, self.creature_id, creature_size):
            # Rollback: restore dead creature occupants and own position
            for h, dead_id in cleared_dead:
                cell = grid.get_cell(h)
                if cell:
                    cell.occupant_id = dead_id
            grid.place_creature(pos, self.creature_id, creature_size)
            return False, None

        self.remaining_movement -= cost
        self.has_moved = True

        event = CombatEvent(
            event_type=CombatEventType.MOVEMENT,
            message=f"moves to ({target.q}, {target.r})",
            source_id=self.creature_id,
            details={"from": start_key, "to": target_key, "cost": cost},
        )
        return True, event
