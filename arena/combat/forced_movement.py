"""Forced movement resolution — push, pull, slide, and shove contests.

Handles direction calculation, path walking with collision detection,
grid updates, and the contested Athletics check for Shove.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.grid.line_of_sight import hex_line, _offset_to_cube, _cube_to_offset, _cube_round
from arena.grid.footprint import is_valid_placement
from arena.models.character import Creature, CreatureSize
from arena.models.encounter import TerrainType
from arena.combat.events import CombatEvent, CombatEventType
from arena.combat.conditions import apply_condition
from arena.models.conditions import Condition
from arena.combat.stat_modifiers import get_effective_ability_modifier
from arena.util.dice import roll_die


@dataclass
class ForcedMovementResult:
    """Result of resolving forced movement."""

    destination_hex: HexCoord
    distance_moved: int  # Actual distance in feet
    stopped_by_wall: bool
    fell_in_pit: bool
    knocked_prone: bool
    events: list[CombatEvent] = field(default_factory=list)


def _get_skill_modifier(creature: Creature, skill: str) -> int:
    """Get a creature's modifier for a skill (ability mod + proficiency if proficient)."""
    ability_map = {
        "athletics": "strength",
        "acrobatics": "dexterity",
    }
    ability = ability_map.get(skill, "strength")
    mod = get_effective_ability_modifier(creature, ability)
    proficiencies = getattr(creature, "skill_proficiencies", [])
    if skill in proficiencies:
        mod += creature.proficiency_bonus
    return mod


def _project_far_point(
    origin: HexCoord, direction_cube: tuple[int, int, int], distance_hexes: int,
) -> HexCoord:
    """Project a point far away from origin in the given cube direction.

    Used to create a hex_line endpoint for path tracing.
    """
    ox, oy, oz = origin._to_cube()
    dx, dy, dz = direction_cube

    # Scale factor large enough to cover the requested distance
    # (hex_line will give us all hexes along the way)
    factor = distance_hexes + 2

    far_x = ox + dx * factor
    far_y = oy + dy * factor
    far_z = oz + dz * factor

    # Round to nearest valid cube coordinate
    rx, ry, rz = _cube_round(float(far_x), float(far_y), float(far_z))
    return _cube_to_offset(rx, ry, rz)


def _normalize_cube_direction(
    dx: int, dy: int, dz: int,
) -> tuple[int, int, int]:
    """Normalize a cube direction vector to unit-ish steps.

    For hex grids, we don't truly normalize to length 1. Instead we
    find the dominant axis and scale so the max component is 1, which
    gives us a direction that hex_line can trace cleanly.
    """
    max_abs = max(abs(dx), abs(dy), abs(dz))
    if max_abs == 0:
        return (0, 0, 0)

    # Use the raw direction -- hex_line handles interpolation for us.
    # We just need a far point in the right direction.
    return (dx, dy, dz)


def _walk_path(
    path: list[HexCoord],
    grid: HexGrid,
    target_id: str,
    target_size: CreatureSize,
    max_hexes: int,
) -> tuple[HexCoord, bool, bool]:
    """Walk along a path, stopping at first impassable/occupied hex.

    Args:
        path: Ordered hexes to walk through (first is current position).
        grid: The hex grid.
        target_id: The creature being moved (excluded from occupancy checks).
        target_size: Size of the creature being moved.
        max_hexes: Maximum number of hexes to move.

    Returns:
        (final_hex, stopped_by_wall, fell_in_pit)
    """
    if not path:
        return path[0] if path else HexCoord(0, 0), False, False

    current = path[0]
    stopped_by_wall = False
    fell_in_pit = False

    steps_taken = 0
    for hex_coord in path[1:]:
        if steps_taken >= max_hexes:
            break

        cell = grid.get_cell(hex_coord)

        # Off grid or wall: stop before this hex
        if cell is None:
            stopped_by_wall = True
            break

        if cell.terrain == TerrainType.WALL or cell.terrain == TerrainType.COVER_FULL:
            stopped_by_wall = True
            break

        # Pit: creature falls IN (stop on the pit)
        if cell.terrain == TerrainType.PIT:
            current = hex_coord
            fell_in_pit = True
            steps_taken += 1
            break

        # Occupied by another creature: stop before this hex
        if cell.occupant_id is not None and cell.occupant_id != target_id:
            stopped_by_wall = True
            break

        # Check valid placement for multi-hex creatures
        if target_size not in (CreatureSize.TINY, CreatureSize.SMALL, CreatureSize.MEDIUM):
            if not is_valid_placement(hex_coord, target_size, grid, exclude_creature_id=target_id):
                stopped_by_wall = True
                break

        current = hex_coord
        steps_taken += 1

    return current, stopped_by_wall, fell_in_pit


def calculate_push_path(
    source_pos: HexCoord,
    target_pos: HexCoord,
    distance_feet: int,
    grid: HexGrid,
    target_id: str,
    target_size: CreatureSize = CreatureSize.MEDIUM,
) -> tuple[HexCoord, bool, bool]:
    """Calculate destination for pushing a creature away from source.

    Returns:
        (final_hex, stopped_by_wall, fell_in_pit)
    """
    if source_pos == target_pos or distance_feet <= 0:
        return target_pos, False, False

    max_hexes = distance_feet // 5

    # Direction: from source toward target (push continues past target)
    src_cube = _offset_to_cube(source_pos)
    tgt_cube = _offset_to_cube(target_pos)
    direction = (
        tgt_cube[0] - src_cube[0],
        tgt_cube[1] - src_cube[1],
        tgt_cube[2] - src_cube[2],
    )

    if direction == (0, 0, 0):
        return target_pos, False, False

    # Project a far point past the target in this direction
    far_point = _project_far_point(target_pos, direction, max_hexes)

    # Get the line from target outward
    path = hex_line(target_pos, far_point)

    return _walk_path(path, grid, target_id, target_size, max_hexes)


def calculate_pull_path(
    source_pos: HexCoord,
    target_pos: HexCoord,
    distance_feet: int,
    grid: HexGrid,
    target_id: str,
    source_id: str | None = None,
    target_size: CreatureSize = CreatureSize.MEDIUM,
) -> tuple[HexCoord, bool, bool]:
    """Calculate destination for pulling a creature toward source.

    The creature stops before occupying the source's hex.

    Returns:
        (final_hex, stopped_by_wall, fell_in_pit)
    """
    if source_pos == target_pos or distance_feet <= 0:
        return target_pos, False, False

    max_hexes = distance_feet // 5

    # Direction: from target toward source (pull)
    path = hex_line(target_pos, source_pos)

    # Don't let the target land on the source's hex
    # Trim the path to stop before the source
    trimmed = []
    for h in path:
        if h == source_pos:
            break
        trimmed.append(h)

    if not trimmed:
        return target_pos, False, False

    return _walk_path(trimmed, grid, target_id, target_size, max_hexes)


def calculate_slide_path(
    target_pos: HexCoord,
    slide_destination: HexCoord,
    distance_feet: int,
    grid: HexGrid,
    target_id: str,
    target_size: CreatureSize = CreatureSize.MEDIUM,
) -> tuple[HexCoord, bool, bool]:
    """Calculate destination for sliding a creature in a chosen direction.

    The slide_destination is the desired end point. The creature moves
    along the line from current position to destination, stopping at
    obstacles.

    Returns:
        (final_hex, stopped_by_wall, fell_in_pit)
    """
    if target_pos == slide_destination or distance_feet <= 0:
        return target_pos, False, False

    max_hexes = distance_feet // 5

    # Validate destination is within range
    hex_dist = target_pos.distance_to(slide_destination)
    if hex_dist > max_hexes:
        # Clamp: trace line and limit to max_hexes
        pass

    path = hex_line(target_pos, slide_destination)

    return _walk_path(path, grid, target_id, target_size, max_hexes)


def resolve_forced_movement(
    source_id: str,
    source_pos: HexCoord,
    target_id: str,
    target_pos: HexCoord,
    movement_type: str,
    distance_feet: int,
    grid: HexGrid,
    combatants: dict,
    target_creature: Creature,
    knock_prone: bool = False,
    slide_destination: HexCoord | None = None,
) -> ForcedMovementResult:
    """Resolve forced movement of a target creature.

    Calculates the destination based on movement_type, moves the
    creature on the grid, and optionally applies prone.

    Args:
        source_id: ID of the creature/effect causing the movement.
        source_pos: Position of the source (for push/pull direction).
        target_id: ID of the creature being moved.
        target_pos: Current position of the target.
        movement_type: "push", "pull", or "slide".
        distance_feet: Maximum distance in feet.
        grid: The hex grid.
        combatants: Dict of all combatants (for position lookups).
        target_creature: The creature being moved.
        knock_prone: Whether to also knock the target prone.
        slide_destination: For slide type, the chosen destination hex.

    Returns:
        ForcedMovementResult with events and final position.
    """
    events: list[CombatEvent] = []
    target_size = target_creature.size

    # Calculate destination based on movement type
    if movement_type == "push":
        final_hex, stopped, pit = calculate_push_path(
            source_pos, target_pos, distance_feet, grid,
            target_id, target_size,
        )
    elif movement_type == "pull":
        final_hex, stopped, pit = calculate_pull_path(
            source_pos, target_pos, distance_feet, grid,
            target_id, source_id, target_size,
        )
    elif movement_type == "slide":
        dest = slide_destination if slide_destination is not None else target_pos
        # If no explicit destination, default to push direction
        if dest == target_pos:
            final_hex, stopped, pit = calculate_push_path(
                source_pos, target_pos, distance_feet, grid,
                target_id, target_size,
            )
        else:
            final_hex, stopped, pit = calculate_slide_path(
                target_pos, dest, distance_feet, grid,
                target_id, target_size,
            )
    else:
        return ForcedMovementResult(
            destination_hex=target_pos,
            distance_moved=0,
            stopped_by_wall=False,
            fell_in_pit=False,
            knocked_prone=False,
            events=events,
        )

    # Calculate actual distance moved
    distance_moved = target_pos.distance_to(final_hex) * 5

    # Move on grid (only if actually moved)
    if final_hex != target_pos:
        grid.remove_creature(target_pos, target_size)
        placed = grid.place_creature(final_hex, target_id, target_size)
        if not placed:
            # Fallback: couldn't place at destination, stay put
            grid.place_creature(target_pos, target_id, target_size)
            final_hex = target_pos
            distance_moved = 0
            stopped = True

    # Generate movement event
    type_labels = {"push": "pushed", "pull": "pulled", "slide": "slid"}
    type_label = type_labels.get(movement_type, "moved")

    if distance_moved > 0:
        msg = f"{target_creature.name} is {type_label} {distance_moved} feet"
        if stopped:
            msg += " (blocked by obstacle)"
        if pit:
            msg += " and falls into a pit!"
        msg += "!"

        events.append(CombatEvent(
            event_type=CombatEventType.FORCED_MOVEMENT,
            message=msg,
            source_id=source_id,
            target_id=target_id,
            details={
                "from_hex": (target_pos.q, target_pos.r),
                "to_hex": (final_hex.q, final_hex.r),
                "fm_type": movement_type,
                "distance_moved": distance_moved,
                "stopped_by_wall": stopped,
                "fell_in_pit": pit,
            },
        ))
    elif stopped:
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{target_creature.name} cannot be {type_label} (blocked)!",
            source_id=source_id,
            target_id=target_id,
        ))

    # Knock prone
    applied_prone = False
    if knock_prone and target_creature.is_conscious:
        cond_event = apply_condition(
            target_creature, target_id, Condition.PRONE,
            source="forced movement",
        )
        if cond_event:
            events.append(cond_event)
            applied_prone = True

    return ForcedMovementResult(
        destination_hex=final_hex,
        distance_moved=distance_moved,
        stopped_by_wall=stopped,
        fell_in_pit=pit,
        knocked_prone=applied_prone,
        events=events,
    )


def resolve_shove_contest(
    attacker: Creature,
    attacker_id: str,
    target: Creature,
    target_id: str,
    combatants: dict | None = None,
    verb: str = "shove",
) -> tuple[bool, list[CombatEvent]]:
    """Resolve a contested Athletics check for the Shove action.

    5e Shove rules:
    - Attacker rolls d20 + Athletics modifier
    - Defender rolls d20 + higher of Athletics or Acrobatics
    - Attacker wins on tie

    With ``combatants``, bard dice may swing the contest from the shover's side
    (their own Bardic Inspiration, or the target-side Cutting Words against a
    winning shove).

    ``verb`` only flavours the log line ("shove" vs "grapple") — Grapple uses
    the identical contest (RAW: Athletics vs the target's Athletics/Acrobatics).

    Returns:
        (success, events) where success means the shove worked.
    """
    events: list[CombatEvent] = []

    # Attacker: Athletics (STR + proficiency if proficient)
    atk_mod = _get_skill_modifier(attacker, "athletics")
    atk_roll = roll_die(20)
    atk_total = atk_roll + atk_mod

    # Defender: higher of Athletics or Acrobatics
    def_athletics = _get_skill_modifier(target, "athletics")
    def_acrobatics = _get_skill_modifier(target, "acrobatics")
    if def_athletics >= def_acrobatics:
        def_mod = def_athletics
        def_skill = "Athletics"
    else:
        def_mod = def_acrobatics
        def_skill = "Acrobatics"

    def_roll = roll_die(20)
    def_total = def_roll + def_mod

    # Attacker wins ties
    success = atk_total >= def_total

    bard_events: list[CombatEvent] = []
    if combatants is not None:
        from arena.combat.bardic import apply_bard_dice_to_contest
        atk_total, success, bard_events = apply_bard_dice_to_contest(
            attacker, attacker_id, target_id, atk_total, def_total, combatants)

    result_text = "SUCCESS" if success else "FAILURE"
    events.append(CombatEvent(
        event_type=CombatEventType.SAVING_THROW,
        message=(
            f"{attacker.name} attempts to {verb} {target.name}: "
            f"Athletics {atk_total} ({atk_roll}+{atk_mod}) vs "
            f"{def_skill} {def_total} ({def_roll}+{def_mod}) "
            f"- {result_text}"
        ),
        source_id=attacker_id,
        target_id=target_id,
        details={
            "contest": True,
            "attacker_roll": atk_total,
            "attacker_natural": atk_roll,
            "attacker_modifier": atk_mod,
            "defender_roll": def_total,
            "defender_natural": def_roll,
            "defender_modifier": def_mod,
            "defender_skill": def_skill.lower(),
            "success": success,
        },
    ))
    events.extend(bard_events)

    return success, events
