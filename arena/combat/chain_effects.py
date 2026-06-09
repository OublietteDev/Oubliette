"""Chain effect mechanics -- spells that bounce/arc between targets.

Chain Lightning, etc. Primary target is resolved normally, then the effect
chains to additional targets within range of the primary.
"""

from arena.models.actions import Action
from arena.grid.coordinates import HexCoord


def get_chain_targets(
    action: Action,
    primary_target_id: str,
    combatants: dict,
    positions: dict,
    caster_id: str,
    excluded_ids: list[str] | None = None,
) -> list[str]:
    """Find valid secondary targets for a chain effect.

    Finds creatures within chain_range of the primary target that are
    valid chain targets (not the caster, not the primary, not already chained).

    Args:
        action: The action with chain properties.
        primary_target_id: ID of the primary target.
        combatants: Dict of {id: Creature}.
        positions: Dict of {id: HexCoord}.
        caster_id: ID of the caster (excluded from chaining).
        excluded_ids: Additional IDs to exclude (already-hit targets).

    Returns:
        List of creature IDs for secondary targets, up to chain_target_count.
    """
    if action.chain_target_count <= 0:
        return []

    if primary_target_id not in positions:
        return []

    primary_pos = positions[primary_target_id]
    excluded = set(excluded_ids or [])
    excluded.add(primary_target_id)
    excluded.add(caster_id)

    # Find candidates within range, sorted by distance (closest first)
    candidates = []
    for cid, creature in combatants.items():
        if cid in excluded:
            continue
        if cid not in positions:
            continue
        if not creature.is_conscious:
            continue

        distance_feet = primary_pos.distance_to(positions[cid]) * 5
        if distance_feet <= action.chain_range:
            candidates.append((distance_feet, cid))

    # Sort by distance, take up to chain_target_count
    candidates.sort(key=lambda x: x[0])
    return [cid for _, cid in candidates[: action.chain_target_count]]


def has_chain_effect(action: Action) -> bool:
    """Check if an action has a chain effect."""
    return action.chain_target_count > 0
