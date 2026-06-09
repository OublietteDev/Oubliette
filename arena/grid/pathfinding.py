"""A* pathfinding for hex grid."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from .coordinates import HexCoord
from .hexgrid import HexGrid
from arena.models.character import CreatureSize


@dataclass(order=True)
class PathNode:
    """A node in the pathfinding priority queue."""

    f_score: int
    coord: HexCoord = field(compare=False)
    g_score: int = field(compare=False)


def _get_footprint_movement_cost(
    anchor: HexCoord, size: CreatureSize, grid: HexGrid
) -> int:
    """Return the maximum movement cost across all footprint hexes.

    For single-hex creatures this is just the cost of the anchor hex.
    For multi-hex creatures the most expensive terrain in the
    footprint determines the cost.
    """
    from arena.grid.footprint import get_occupied_hexes

    hexes = get_occupied_hexes(anchor, size)
    return max(grid.get_movement_cost(h) for h in hexes)


def find_path(
    start: HexCoord,
    goal: HexCoord,
    grid: HexGrid,
    max_cost: int | None = None,
    creature_size: CreatureSize = CreatureSize.MEDIUM,
    creature_id: str | None = None,
    dead_creature_ids: set[str] | None = None,
    blocked_hexes: set[tuple[int, int]] | None = None,
) -> list[HexCoord] | None:
    """Find the shortest path between two hexes using A*.

    Args:
        start: Starting hex coordinate (anchor position).
        goal: Target hex coordinate (anchor position).
        grid: The hex grid to pathfind on.
        max_cost: Maximum movement cost (in feet) to consider.
        creature_size: Size of the moving creature (for footprint checks).
        creature_id: ID of the creature moving (its own hexes are ignored
            during occupancy checks).
        dead_creature_ids: Set of creature IDs whose hexes are treated as
            difficult terrain (passable) rather than impassable.  Per 5e,
            dead creatures' spaces can be moved through and stopped on.
        blocked_hexes: Set of (q, r) tuples that are completely impassable
            (e.g., wall spell hexes).  The goal hex is also blocked if it
            appears in this set.

    Returns:
        List of hex coordinates from start to goal (inclusive),
        or None if no path exists.
    """
    from arena.grid.footprint import is_valid_placement, get_footprint_hex_count

    single_hex = get_footprint_hex_count(creature_size) == 1
    dead_ids = dead_creature_ids or set()
    _blocked = blocked_hexes or set()

    # Validate goal
    if (goal.q, goal.r) in _blocked:
        return None
    if single_hex:
        if not grid.is_valid(goal) or not grid.is_passable(goal):
            return None
        # Goal blocked by a living creature (not self, not dead)
        cell = grid.get_cell(goal)
        if (
            cell and cell.occupant_id is not None
            and cell.occupant_id != creature_id
            and cell.occupant_id not in dead_ids
        ):
            return None
    else:
        if not is_valid_placement(
            goal, creature_size, grid, creature_id, dead_ids
        ):
            return None

    # Priority queue: (f_score, coord, g_score)
    open_set: list[PathNode] = [PathNode(0, start, 0)]
    came_from: dict[tuple[int, int], HexCoord] = {}
    g_scores: dict[tuple[int, int], int] = {(start.q, start.r): 0}

    while open_set:
        current_node = heapq.heappop(open_set)
        current = current_node.coord
        current_g = current_node.g_score

        if current == goal:
            # Reconstruct path
            path = [current]
            while (current.q, current.r) in came_from:
                current = came_from[(current.q, current.r)]
                path.append(current)
            path.reverse()
            return path

        for neighbor in current.neighbors():
            # Wall-blocked hexes are completely impassable
            if (neighbor.q, neighbor.r) in _blocked:
                continue
            if single_hex:
                # Original single-hex checks
                if not grid.is_valid(neighbor) or not grid.is_passable(neighbor):
                    continue
                cell = grid.get_cell(neighbor)
                if cell and cell.occupant_id is not None and neighbor != goal:
                    if (
                        cell.occupant_id != creature_id
                        and cell.occupant_id not in dead_ids
                    ):
                        continue
                move_cost = grid.get_movement_cost(neighbor)
                # Dead creature's space costs difficult terrain (10 ft)
                if (
                    cell and cell.occupant_id is not None
                    and cell.occupant_id in dead_ids
                    and move_cost < 10
                ):
                    move_cost = 10
            else:
                # Multi-hex: check entire footprint
                if not is_valid_placement(
                    neighbor, creature_size, grid, creature_id, dead_ids
                ):
                    continue
                move_cost = _get_footprint_movement_cost(
                    neighbor, creature_size, grid
                )

            tentative_g = current_g + move_cost

            # Check max cost constraint
            if max_cost is not None and tentative_g > max_cost:
                continue

            neighbor_key = (neighbor.q, neighbor.r)
            if neighbor_key not in g_scores or tentative_g < g_scores[neighbor_key]:
                came_from[neighbor_key] = current
                g_scores[neighbor_key] = tentative_g
                f_score = tentative_g + neighbor.distance_to(goal) * 5  # Heuristic
                heapq.heappush(open_set, PathNode(f_score, neighbor, tentative_g))

    return None  # No path found


@dataclass(order=True)
class ReachNode:
    """A node in the reachability priority queue."""

    cost: int
    coord: HexCoord = field(compare=False)


def get_reachable_hexes(
    start: HexCoord,
    grid: HexGrid,
    max_cost: int,
    creature_size: CreatureSize = CreatureSize.MEDIUM,
    creature_id: str | None = None,
    dead_creature_ids: set[str] | None = None,
    blocked_hexes: set[tuple[int, int]] | None = None,
) -> dict[tuple[int, int], int]:
    """Get all hexes reachable within a movement budget.

    Args:
        start: Starting hex coordinate (anchor position).
        grid: The hex grid.
        max_cost: Maximum movement cost in feet.
        creature_size: Size of the moving creature.
        creature_id: ID of the creature moving (its own hexes are ignored).
        dead_creature_ids: Set of creature IDs whose hexes are treated as
            difficult terrain (passable) rather than impassable.
        blocked_hexes: Set of (q, r) tuples that are completely impassable
            (e.g., wall spell hexes).

    Returns:
        Dict mapping (q, r) to movement cost to reach that hex.
    """
    from arena.grid.footprint import is_valid_placement, get_footprint_hex_count

    single_hex = get_footprint_hex_count(creature_size) == 1
    dead_ids = dead_creature_ids or set()
    _blocked = blocked_hexes or set()

    reachable: dict[tuple[int, int], int] = {(start.q, start.r): 0}
    frontier: list[ReachNode] = [ReachNode(0, start)]

    while frontier:
        node = heapq.heappop(frontier)
        current_cost = node.cost
        current = node.coord

        for neighbor in current.neighbors():
            # Wall-blocked hexes are completely impassable
            if (neighbor.q, neighbor.r) in _blocked:
                continue
            if single_hex:
                # Original single-hex checks
                if not grid.is_valid(neighbor) or not grid.is_passable(neighbor):
                    continue
                cell = grid.get_cell(neighbor)
                if cell and cell.occupant_id is not None:
                    if (
                        cell.occupant_id != creature_id
                        and cell.occupant_id not in dead_ids
                    ):
                        continue
                move_cost = grid.get_movement_cost(neighbor)
                # Dead creature's space costs difficult terrain (10 ft)
                if (
                    cell and cell.occupant_id is not None
                    and cell.occupant_id in dead_ids
                    and move_cost < 10
                ):
                    move_cost = 10
            else:
                # Multi-hex: check entire footprint
                if not is_valid_placement(
                    neighbor, creature_size, grid, creature_id, dead_ids
                ):
                    continue
                move_cost = _get_footprint_movement_cost(
                    neighbor, creature_size, grid
                )

            new_cost = current_cost + move_cost

            if new_cost > max_cost:
                continue

            neighbor_key = (neighbor.q, neighbor.r)
            if neighbor_key not in reachable or new_cost < reachable[neighbor_key]:
                reachable[neighbor_key] = new_cost
                heapq.heappush(frontier, ReachNode(new_cost, neighbor))

    return reachable
