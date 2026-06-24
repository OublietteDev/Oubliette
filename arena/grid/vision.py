"""Pairwise vision resolution: can creature A actually *see* creature B?

This is the spatial half of the 5e "you can't see your target" rule, used by
the attack-advantage system. It is a pure module — it takes positions, a set of
heavily-obscured hexes (fog cloud, magical darkness), and the observer's special
senses, and answers a yes/no question. State and zone-tracking live elsewhere
(the combat manager builds the obscured-hex set and reads creature senses).

Modeling notes (faithful pairwise vision, the approved design):
  * A creature is "blind to" anything it is trying to see if the sight-line
    passes through — or ends in — a heavily-obscured hex, OR if the creature
    itself stands in one (a creature in heavy obscurement is effectively blinded
    when trying to see anything).
  * Heavy obscurement defeats ordinary sight *and* darkvision. Darkvision lets a
    creature see in the absence of light, not through fog or magical darkness, so
    it does not help here (RAW). Only blindsight and truesight pierce it.
  * Invisibility is handled separately, by the INVISIBLE condition in
    condition_effects.get_attack_advantage — this module is purely about
    obscurement, so the two compose without double-counting.
"""

from __future__ import annotations

from arena.grid.coordinates import HexCoord
from arena.grid.line_of_sight import hex_line

# 5e: one hex = 5 feet.
FEET_PER_HEX = 5


def can_see(
    observer_pos: HexCoord | None,
    target_pos: HexCoord | None,
    obscured_hexes: set[tuple[int, int]],
    *,
    truesight_ft: int = 0,
    blindsight_ft: int = 0,
) -> bool:
    """Return True if the observer can see the target.

    Args:
        observer_pos: Observer's hex (None → treated as able to see; off-grid
            fallback so non-positional contexts never spuriously blind anyone).
        target_pos: Target's hex (None → treated as visible, same fallback).
        obscured_hexes: (q, r) tuples that are heavily obscured (fog/darkness).
        truesight_ft: Observer's truesight range in feet (pierces all obscurement
            within range).
        blindsight_ft: Observer's blindsight range in feet (pierces obscurement
            within range).

    Returns:
        True if the observer perceives the target for the purpose of attacks.
    """
    if observer_pos is None or target_pos is None:
        return True

    distance_ft = observer_pos.distance_to(target_pos) * FEET_PER_HEX

    # Blindsight / truesight pierce obscurement within their range.
    if truesight_ft and distance_ft <= truesight_ft:
        return True
    if blindsight_ft and distance_ft <= blindsight_ft:
        return True

    if not obscured_hexes:
        return True

    # The observer's own hex counts: standing in fog blinds you to everything.
    if (observer_pos.q, observer_pos.r) in obscured_hexes:
        return False

    # Any obscured hex along the line — including the target's own hex — blocks
    # sight. line[1:] excludes the observer hex (already checked) and includes
    # every intervening hex plus the target hex.
    for coord in hex_line(observer_pos, target_pos)[1:]:
        if (coord.q, coord.r) in obscured_hexes:
            return False

    return True
