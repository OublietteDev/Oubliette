"""Dynamic terrain modification during combat.

Handles terrain-altering spells (Wall of Stone, Spike Growth, Mold Earth)
that add, remove, or change terrain hexes.  Modifications can be
concentration-linked and auto-revert when concentration breaks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from arena.combat.events import CombatEvent, CombatEventType
from arena.grid.coordinates import HexCoord
from arena.models.encounter import TerrainType

if TYPE_CHECKING:
    from arena.combat.manager import Combatant
    from arena.grid.hexgrid import HexGrid


@dataclass
class TerrainModification:
    """Record of a terrain change applied to the grid.

    Attributes:
        mod_id: Unique identifier for this modification batch.
        caster_id: creature_id of the caster who created this modification.
        spell_name: Display name (e.g., "Wall of Stone").
        applied_type: The terrain type that was applied to affected hexes.
        original_terrain: Mapping of ``(q, r)`` coords to their ORIGINAL
            terrain type before modification.  Used for safe reversion.
        concentration_linked: If True, reverts when the caster loses
            concentration.
    """

    mod_id: str
    caster_id: str
    spell_name: str
    applied_type: TerrainType
    original_terrain: dict[tuple[int, int], TerrainType] = field(default_factory=dict)
    concentration_linked: bool = False


# ------------------------------------------------------------------
# Geometry helpers
# ------------------------------------------------------------------

def get_terrain_mod_hexes(
    center: HexCoord,
    radius_feet: int,
    grid: HexGrid,
) -> list[HexCoord]:
    """Return all valid grid hexes within *radius_feet* of *center*.

    With ``radius_feet=0`` only the center hex is returned (if valid).
    """
    radius_hexes = radius_feet / 5
    hexes: list[HexCoord] = []
    for q in range(grid.width):
        for r in range(grid.height):
            coord = HexCoord(q, r)
            if center.distance_to(coord) <= radius_hexes:
                hexes.append(coord)
    return hexes


# ------------------------------------------------------------------
# Apply / revert
# ------------------------------------------------------------------

def apply_terrain_modification(
    grid: HexGrid,
    center: HexCoord,
    radius_feet: int,
    terrain_type: TerrainType,
    caster_id: str,
    spell_name: str,
    concentration_linked: bool,
    combatants: dict[str, Combatant],
) -> tuple[TerrainModification, list[CombatEvent]]:
    """Apply terrain modification to hexes within *radius_feet* of *center*.

    For impassable terrain types (WALL, PIT), skips hexes that are
    currently occupied by a living creature.  For all types, records the
    original terrain for safe reversion.

    Returns:
        ``(TerrainModification record, list of CombatEvents)``
    """
    events: list[CombatEvent] = []
    impassable = terrain_type in (TerrainType.WALL, TerrainType.PIT)

    # Build set of occupied hexes for fast lookup
    occupied_hexes: set[tuple[int, int]] = set()
    if impassable:
        from arena.grid.footprint import get_occupied_hexes

        for comb in combatants.values():
            if comb.position is not None and comb.creature.is_conscious:
                for h in get_occupied_hexes(comb.position, comb.creature.size):
                    occupied_hexes.add((h.q, h.r))

    target_hexes = get_terrain_mod_hexes(center, radius_feet, grid)
    mod = TerrainModification(
        mod_id=f"terrain_{uuid.uuid4().hex[:8]}",
        caster_id=caster_id,
        spell_name=spell_name,
        applied_type=terrain_type,
        concentration_linked=concentration_linked,
    )

    modified_count = 0
    for coord in target_hexes:
        cell = grid.get_cell(coord)
        if cell is None:
            continue

        # Skip occupied hexes for impassable terrain
        if impassable and (coord.q, coord.r) in occupied_hexes:
            continue

        # Skip if already this terrain type (no-op)
        if cell.terrain == terrain_type:
            continue

        # Record original and apply
        mod.original_terrain[(coord.q, coord.r)] = cell.terrain
        grid.set_terrain(coord, terrain_type)
        modified_count += 1

    if modified_count > 0:
        events.append(CombatEvent(
            event_type=CombatEventType.TERRAIN_MODIFICATION,
            message=(
                f"{spell_name} transforms {modified_count} "
                f"hex{'es' if modified_count != 1 else ''} to "
                f"{terrain_type.value} terrain!"
            ),
            source_id=caster_id,
            details={
                "terrain_modified": True,
                "terrain_mod_id": mod.mod_id,
                "terrain_type": terrain_type.value,
                "center_hex": (center.q, center.r),
                "radius_feet": radius_feet,
                "hex_count": modified_count,
            },
        ))

    return mod, events


def revert_terrain_modification(
    grid: HexGrid,
    mod: TerrainModification,
) -> list[CombatEvent]:
    """Revert a terrain modification, restoring original terrain.

    Only reverts hexes that STILL match ``mod.applied_type``.  This
    prevents reverting hexes that were subsequently changed by another
    spell or effect (stacking safety).
    """
    events: list[CombatEvent] = []
    reverted_count = 0

    for (q, r), original_type in mod.original_terrain.items():
        coord = HexCoord(q, r)
        cell = grid.get_cell(coord)
        if cell is None:
            continue

        # Only revert if hex still matches what we set
        if cell.terrain == mod.applied_type:
            grid.set_terrain(coord, original_type)
            reverted_count += 1

    if reverted_count > 0:
        events.append(CombatEvent(
            event_type=CombatEventType.TERRAIN_MODIFICATION,
            message=(
                f"{mod.spell_name} terrain fades away "
                f"({reverted_count} hex{'es' if reverted_count != 1 else ''} restored)."
            ),
            source_id=mod.caster_id,
            details={
                "terrain_reverted": True,
                "terrain_mod_id": mod.mod_id,
                "hex_count": reverted_count,
            },
        ))

    return events


# ------------------------------------------------------------------
# Concentration cleanup
# ------------------------------------------------------------------

def cleanup_terrain_modifications(
    mods: list[TerrainModification],
    combatants: dict[str, Combatant],
    grid: HexGrid,
) -> tuple[list[TerrainModification], list[CombatEvent]]:
    """Remove terrain modifications whose caster lost concentration.

    Mirrors ``_cleanup_orphaned_zones()`` logic: checks if each
    concentration-linked modification's caster is still concentrating.

    Returns:
        ``(remaining_mods, reversion_events)``
    """
    from arena.combat.conditions import has_condition
    from arena.models.conditions import Condition

    remaining: list[TerrainModification] = []
    all_events: list[CombatEvent] = []

    for mod in mods:
        if not mod.concentration_linked:
            remaining.append(mod)
            continue

        caster = combatants.get(mod.caster_id)
        if caster is not None and has_condition(caster.creature, Condition.CONCENTRATING):
            # Check that the caster is still concentrating on THIS spell,
            # not a different one (switching from Spike Growth to Moonbeam
            # should revert Spike Growth's terrain).
            conc_spell = None
            for ac in caster.creature.active_conditions:
                if ac.condition == Condition.CONCENTRATING:
                    conc_spell = ac.extra_data.get("spell")
                    break
            # If we can't determine the spell (legacy/manual apply_condition),
            # fall back to keeping the mod for backward compatibility.
            if conc_spell is None or conc_spell == mod.spell_name:
                remaining.append(mod)
                continue

        # Caster lost concentration or is gone or switched spells — revert
        revert_events = revert_terrain_modification(grid, mod)
        all_events.extend(revert_events)

    return remaining, all_events
