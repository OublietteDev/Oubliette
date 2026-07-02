"""AI movement decisions — where to move and when.

Uses the grid pathfinding infrastructure (A*, Dijkstra reachable hexes)
to evaluate positions and choose optimal movement.
"""

from __future__ import annotations

from dataclasses import dataclass

from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.grid.pathfinding import get_reachable_hexes
from arena.grid.line_of_sight import has_line_of_sight, get_cover
from arena.grid.footprint import get_occupied_hexes, get_footprint_boundary, min_distance_between
from arena.models.character import CreatureSize
from arena.ai.behavior import AIProfile
from arena.ai.context import CombatContext, CreatureView, pos_to_creature_distance


@dataclass(frozen=True)
class MovementGoal:
    """A scored movement destination."""

    target_hex: HexCoord
    score: float
    purpose: str  # "approach_enemy", "maintain_range", "retreat", "flank", "stay"


def evaluate_position(
    hex_coord: HexCoord,
    profile: AIProfile,
    context: CombatContext,
    grid: HexGrid,
    preferred_target: CreatureView | None = None,
) -> float:
    """Score a hex position for desirability.

    Considers:
    - Distance to preferred target (melee wants adjacent, ranged wants optimal range)
    - Cover from enemies
    - Line of sight to targets
    - Flanking opportunities
    - Number of enemies in melee range
    """
    score = 50.0  # neutral baseline

    # ── Distance to preferred target ─────────────────────────────────
    if preferred_target and preferred_target.position:
        dist = pos_to_creature_distance(hex_coord, preferred_target)

        if profile.prefers_melee:
            # Melee wants to be adjacent (distance 1)
            if dist == 1:
                score += 40  # ideal melee position
            elif dist == 0:
                score += 10  # same hex (shouldn't happen, but handle it)
            else:
                score -= (dist - 1) * 8  # penalty per hex away from ideal
        else:
            # Ranged wants to be at optimal distance
            optimal = profile.maintains_distance // 5
            if optimal <= 0:
                optimal = 6
            deviation = abs(dist - optimal)
            score -= deviation * 5
            # Must have LOS to be useful
            if not has_line_of_sight(hex_coord, preferred_target.position, grid):
                score -= 30

    # ── Enemies in melee range (adjacent) ────────────────────────────
    adjacent_enemies = 0
    for enemy in context.enemies:
        if enemy.position and pos_to_creature_distance(hex_coord, enemy) <= 1:
            adjacent_enemies += 1

    if profile.prefers_melee:
        # Being adjacent to enemies is fine for melee
        pass
    else:
        # Ranged: penalize being adjacent to enemies
        score -= adjacent_enemies * 15

    # ── Cover bonus ──────────────────────────────────────────────────
    # Check cover from the nearest enemy
    if context.enemies:
        best_cover = 0
        for enemy in context.enemies:
            if enemy.position:
                cover = get_cover(enemy.position, hex_coord, grid)
                best_cover = max(best_cover, cover)
        score += best_cover * 2  # +0, +4, +10 for no/half/3-4 cover

    # ── Flanking bonus ───────────────────────────────────────────────
    if profile.flanks_when_possible and preferred_target and preferred_target.position:
        ally_positions = [
            a.position for a in context.allies if a.position is not None
        ]
        if check_flanking(hex_coord, preferred_target.position, ally_positions, preferred_target.size):
            score += 15

    return score


def find_best_movement(
    profile: AIProfile,
    context: CombatContext,
    grid: HexGrid,
    current_pos: HexCoord,
    remaining_movement: int,
    preferred_target: CreatureView | None = None,
    creature_size: CreatureSize = CreatureSize.MEDIUM,
    creature_id: str | None = None,
    dead_creature_ids: set[str] | None = None,
    blocked_hexes: set[tuple[int, int]] | None = None,
    charge_hold_hexes: int = 0,
    attack_this_turn: bool = True,
) -> MovementGoal:
    """Determine the best hex to move to.

    Steps:
    1. Get all reachable hexes within movement budget
    2. Score each reachable hex using evaluate_position
    3. Return the best-scoring hex, or "stay" if current position is best

    ``charge_hold_hexes``: for move-then-strike attackers (Charge/
    Pounce). When set and the creature can't attack this turn anyway,
    hexes closer than the hold line to the preferred target are heavily
    penalized — creeping adjacent guarantees next turn's hit has no
    run-up and the charge rider never fires. ``attack_this_turn`` is
    False when the action is already committed elsewhere (e.g. Dash).
    """
    # Get reachable positions (in feet budget)
    reachable = get_reachable_hexes(
        current_pos, grid, remaining_movement,
        creature_size=creature_size, creature_id=creature_id,
        dead_creature_ids=dead_creature_ids,
        blocked_hexes=blocked_hexes,
    )

    # Charge-aware hold: only bite when no attack can land this turn —
    # if the target is reachable, closing in and hitting NOW beats
    # posturing for next turn.
    hold_hexes = 0
    if (
        charge_hold_hexes > 0
        and preferred_target is not None
        and preferred_target.position is not None
    ):
        can_attack = attack_this_turn and (
            pos_to_creature_distance(current_pos, preferred_target) <= 1
            or any(
                pos_to_creature_distance(HexCoord(q, r), preferred_target) <= 1
                for (q, r) in reachable
            )
        )
        if not can_attack:
            hold_hexes = charge_hold_hexes

    # Score current position
    current_score = evaluate_position(
        current_pos, profile, context, grid, preferred_target
    )
    best = MovementGoal(
        target_hex=current_pos, score=current_score, purpose="stay"
    )

    for (q, r), cost in reachable.items():
        hex_coord = HexCoord(q, r)
        if hex_coord == current_pos:
            continue

        score = evaluate_position(hex_coord, profile, context, grid, preferred_target)

        # Inside the charge hold line: decisive penalty (outweighs the
        # +40 adjacency bonus so nothing positional can override it)
        if (
            hold_hexes
            and pos_to_creature_distance(hex_coord, preferred_target) < hold_hexes
        ):
            score -= 100.0

        # Determine purpose
        purpose = "approach_enemy"
        if preferred_target and preferred_target.position:
            new_dist = pos_to_creature_distance(hex_coord, preferred_target)
            old_dist = pos_to_creature_distance(current_pos, preferred_target)
            if new_dist > old_dist:
                purpose = "maintain_range"

        if score > best.score:
            best = MovementGoal(
                target_hex=hex_coord, score=score, purpose=purpose
            )

    return best


def find_retreat_destination(
    context: CombatContext,
    grid: HexGrid,
    current_pos: HexCoord,
    remaining_movement: int,
    creature_size: CreatureSize = CreatureSize.MEDIUM,
    creature_id: str | None = None,
    dead_creature_ids: set[str] | None = None,
    blocked_hexes: set[tuple[int, int]] | None = None,
) -> HexCoord | None:
    """Find the best hex to retreat to (maximize distance from all enemies).

    Used when HP < retreat_threshold and will_flee is True.
    """
    reachable = get_reachable_hexes(
        current_pos, grid, remaining_movement,
        creature_size=creature_size, creature_id=creature_id,
        dead_creature_ids=dead_creature_ids,
        blocked_hexes=blocked_hexes,
    )

    if not context.enemies:
        return None

    best_hex: HexCoord | None = None
    best_min_dist = -1

    # Include current position as a candidate
    candidates = [(current_pos.q, current_pos.r, 0)]
    candidates.extend([(q, r, c) for (q, r), c in reachable.items()])

    for q, r, _cost in candidates:
        pos = HexCoord(q, r)
        # Minimum distance to any enemy (footprint-aware)
        min_dist = min(
            (pos_to_creature_distance(pos, e) for e in context.enemies if e.position),
            default=0,
        )
        if min_dist > best_min_dist:
            best_min_dist = min_dist
            best_hex = pos

    if best_hex == current_pos:
        return None  # nowhere better to go

    return best_hex


def find_flee_destination(
    grid: HexGrid,
    current_pos: HexCoord,
    flee_from: HexCoord,
    remaining_movement: int,
    creature_size: CreatureSize = CreatureSize.MEDIUM,
    creature_id: str | None = None,
    dead_creature_ids: set[str] | None = None,
    blocked_hexes: set[tuple[int, int]] | None = None,
) -> HexCoord | None:
    """Find the reachable hex that maximizes distance from a single point — the
    fear source a frightened creature flees. Returns None if no reachable hex is
    farther than where it stands (cornered: it can't increase the distance).
    """
    reachable = get_reachable_hexes(
        current_pos, grid, remaining_movement,
        creature_size=creature_size, creature_id=creature_id,
        dead_creature_ids=dead_creature_ids,
        blocked_hexes=blocked_hexes,
    )
    best_hex: HexCoord | None = None
    best_dist = current_pos.distance_to(flee_from)
    for (q, r), _cost in reachable.items():
        pos = HexCoord(q, r)
        d = pos.distance_to(flee_from)
        if d > best_dist:
            best_dist = d
            best_hex = pos
    return best_hex


def get_adjacent_hexes_to_target(
    target_pos: HexCoord,
    grid: HexGrid,
    reach: int = 1,
    target_size: CreatureSize = CreatureSize.MEDIUM,
) -> list[HexCoord]:
    """Get unoccupied hexes within reach of a target's footprint.

    Used to find valid melee attack positions.
    """
    result: list[HexCoord] = []
    if reach <= 0:
        reach = 1

    target_hexes = set(get_occupied_hexes(target_pos, target_size))

    if reach == 1:
        # Get boundary hexes (adjacent to footprint but not part of it)
        boundary = get_footprint_boundary(target_pos, target_size)
        for h in boundary:
            if grid.is_valid(h) and not grid.is_occupied(h):
                result.append(h)
    else:
        # For extended reach, check all hexes within range of any footprint hex
        for q in range(grid.width):
            for r in range(grid.height):
                pos = HexCoord(q, r)
                if pos in target_hexes:
                    continue
                dist = min(pos.distance_to(th) for th in target_hexes)
                if dist <= reach:
                    if grid.is_valid(pos) and not grid.is_occupied(pos):
                        result.append(pos)

    return result


def check_flanking(
    attacker_pos: HexCoord,
    target_pos: HexCoord,
    ally_positions: list[HexCoord],
    target_size: CreatureSize = CreatureSize.MEDIUM,
) -> bool:
    """Check if an ally is on the opposite side of the target.

    On a hex grid, flanking means the attacker and ally are
    on opposite sides of the target — i.e., the target is
    between them on a straight line, and both are adjacent.

    For multi-hex targets, checks adjacency to any footprint hex
    and looks for an ally on the opposite side of the anchor.
    """
    target_hexes = get_occupied_hexes(target_pos, target_size)
    # Attacker must be adjacent to at least one footprint hex
    adjacent = any(attacker_pos.distance_to(th) <= 1 for th in target_hexes)
    if not adjacent:
        return False

    # Find the "opposite" hex: target + (target - attacker)
    opposite = HexCoord(
        target_pos.q + (target_pos.q - attacker_pos.q),
        target_pos.r + (target_pos.r - attacker_pos.r),
    )

    return opposite in ally_positions
