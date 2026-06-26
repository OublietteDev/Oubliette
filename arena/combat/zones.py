"""Persistent AoE zone tracking and per-turn/entry damage processing.

Zones are created by concentration AoE spells (e.g., Spirit Guardians).
They persist until the caster loses concentration and deal damage to
creatures that start their turn inside the zone or move into it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from arena.combat.events import CombatEvent, CombatEventType
from arena.grid.coordinates import HexCoord

if TYPE_CHECKING:
    from arena.combat.manager import Combatant
    from arena.grid.hexgrid import HexGrid


@dataclass
class ActiveZone:
    """A persistent AoE zone on the battlefield.

    Attributes:
        zone_id: Unique identifier (e.g., "spirit_guardians_aldric").
        caster_id: creature_id of the zone's owner.
        name: Display name (e.g., "Spirit Guardians").
        radius_feet: Zone radius in feet.
        follows_caster: If True, zone is centered on the caster's current
            position.  If False, uses the fixed ``center`` coordinate.
        center: Fixed center hex (only used when follows_caster is False).
        saving_throw_ability: Ability used for the save (e.g., "wisdom").
        saving_throw_dc: Save DC.
        damage_dice: Dice expression (e.g., "3d8").
        damage_type: Damage type string (e.g., "radiant").
        damage_on_save: What happens on a successful save ("half" or "none").
        affects_enemies_only: If True, only damages creatures on opposing teams.
        team: The caster's team string for friend/foe filtering.
        concentration_linked: If True, removed when the caster's concentration
            ends.
        already_damaged: Set of creature_ids that have already been damaged by
            this zone this round (prevents double-dip from start-of-turn +
            entry in the same round).
    """

    zone_id: str
    caster_id: str
    name: str
    radius_feet: int
    follows_caster: bool = True
    center: HexCoord | None = None
    saving_throw_ability: str = "wisdom"
    saving_throw_dc: int = 10
    damage_dice: str = "0"
    damage_type: str = "radiant"
    damage_on_save: str = "half"
    affects_enemies_only: bool = True
    team: str = "player"
    concentration_linked: bool = True
    already_damaged: set[str] = field(default_factory=set)

    # P-VISION-LIGHT: obscurement / light zones carry no damage.
    obscures_vision: bool = False        # fog cloud / darkness block sight
    is_magical: bool = False             # darkness (magical) vs natural fog
    provides_bright_light: bool = False  # daylight — dispels magical darkness
    spell_level: int = 0                 # for daylight-vs-darkness comparison

    # P-TERRAIN: condition-zones (Sleet Storm prone, Stinking Cloud retching).
    # Applied on a FAILED start-of-turn/entry save (reuses saving_throw_*).
    condition_on_fail: str | None = None
    condition_duration_type: str = "end_of_turn"

    # D-CTRL-1: Spike Growth. When set, this zone is a MOVEMENT HAZARD: it
    # deals these dice per 5 ft a creature travels through it (each hex step),
    # NO save — resolved on movement, not at start-of-turn/entry. Such zones
    # are skipped by the normal start-of-turn/entry save-damage processing.
    movement_hazard_dice: str | None = None
    movement_hazard_type: str = "piercing"

    # D-CTRL-1: Spirit Guardians. When True, the zone's area is difficult
    # terrain for the creatures it affects (enemies of the caster).
    slows_movement: bool = False


# ------------------------------------------------------------------
# Geometry helpers
# ------------------------------------------------------------------

def _get_zone_center(
    zone: ActiveZone,
    combatants: dict[str, Combatant],
) -> HexCoord | None:
    """Return the current center hex of a zone."""
    if zone.follows_caster:
        caster = combatants.get(zone.caster_id)
        if caster is None or caster.position is None:
            return None
        return caster.position
    return zone.center


def get_zone_hexes(
    zone: ActiveZone,
    combatants: dict[str, Combatant],
    grid: HexGrid | None,
) -> set[HexCoord]:
    """Return all hex coordinates inside a zone's area.

    Iterates grid hexes and keeps those within ``radius_feet`` of the
    zone center (accounting for multi-hex caster footprint when the zone
    follows the caster).
    """
    if grid is None:
        return set()

    center = _get_zone_center(zone, combatants)
    if center is None:
        return set()

    from arena.grid.footprint import min_distance_between

    caster = combatants.get(zone.caster_id)
    caster_size = caster.creature.size if caster else 1
    radius_hexes = zone.radius_feet / 5

    hexes: set[HexCoord] = set()
    for q in range(grid.width):
        for r in range(grid.height):
            coord = HexCoord(q, r)
            dist = min_distance_between(center, caster_size, coord, 1)
            if dist <= radius_hexes:
                hexes.add(coord)

    return hexes


def compute_obscured_hexes(
    zones: list[ActiveZone],
    combatants: dict[str, "Combatant"],
    grid: "HexGrid | None",
) -> set[tuple[int, int]]:
    """Return the (q, r) hexes heavily obscured by fog/darkness (P-VISION-LIGHT).

    Fed to grid.vision.can_see for the pairwise-visibility advantage check.
    Magical-darkness hexes are dropped where an overlapping bright-light
    (Daylight) zone of equal-or-higher spell level dispels them; natural fog
    is physical and is NOT dispelled by light.
    """
    if grid is None:
        return set()

    bright: list[tuple[set[tuple[int, int]], int]] = []
    for z in zones:
        if getattr(z, "provides_bright_light", False):
            bright.append((
                {(h.q, h.r) for h in get_zone_hexes(z, combatants, grid)},
                z.spell_level,
            ))

    obscured: set[tuple[int, int]] = set()
    for z in zones:
        if not getattr(z, "obscures_vision", False):
            continue
        for h in get_zone_hexes(z, combatants, grid):
            key = (h.q, h.r)
            if z.is_magical and any(
                key in bh and lvl >= z.spell_level for bh, lvl in bright
            ):
                continue
            obscured.add(key)
    return obscured


def is_in_zone(
    creature_id: str,
    zone: ActiveZone,
    combatants: dict[str, Combatant],
    grid: HexGrid | None,
) -> bool:
    """Return True if any part of the creature's footprint is inside the zone."""
    if grid is None:
        return False

    creature_comb = combatants.get(creature_id)
    if creature_comb is None or creature_comb.position is None:
        return False

    center = _get_zone_center(zone, combatants)
    if center is None:
        return False

    from arena.grid.footprint import min_distance_between

    caster = combatants.get(zone.caster_id)
    caster_size = caster.creature.size if caster else 1

    dist = min_distance_between(
        center, caster_size,
        creature_comb.position, creature_comb.creature.size,
    )
    return dist * 5 <= zone.radius_feet


# ------------------------------------------------------------------
# Zone damage resolution
# ------------------------------------------------------------------

def _resolve_zone_damage(
    zone: ActiveZone,
    creature_id: str,
    combatants: dict[str, Combatant],
) -> list[CombatEvent]:
    """Resolve a zone's saving throw + damage against a single creature.

    Returns a list of combat events (save roll, damage, concentration
    check if applicable).
    """
    from arena.combat.actions import resolve_saving_throw, apply_damage
    from arena.combat.concentration import check_concentration
    from arena.util.dice import roll_expression

    target_comb = combatants.get(creature_id)
    if target_comb is None:
        return []

    target = target_comb.creature
    events: list[CombatEvent] = []

    events.append(CombatEvent(
        event_type=CombatEventType.INFO,
        message=f"{target.name} is affected by {zone.name}!",
        source_id=zone.caster_id,
        target_id=creature_id,
        details={"zone_damage": zone.zone_id},
    ))

    # Saving throw — a spell zone (Spirit Guardians, Web, Cloudkill) is a save
    # against a spell, so Magic Resistance / Brave / Fey Ancestry apply.
    success, save_event = resolve_saving_throw(
        target, creature_id, zone.saving_throw_ability, zone.saving_throw_dc,
        is_spell_save=getattr(zone, "spell_level", 0) > 0,
        imposes_conditions=([zone.condition_on_fail]
                            if getattr(zone, "condition_on_fail", None) else None),
    )
    events.append(save_event)

    # Damage
    total_dmg, _rolls = roll_expression(zone.damage_dice)
    if success:
        if zone.damage_on_save == "half":
            total_dmg = total_dmg // 2
        elif zone.damage_on_save == "none":
            total_dmg = 0

    if total_dmg > 0:
        # Zones only ever come from spells, so their damage is magical —
        # it overcomes "B/P/S from nonmagical attacks" defenses.
        from arena.combat.damage import DamagePacket

        packet = DamagePacket(
            amount=total_dmg, dtype=zone.damage_type,
            source=zone.name, tags={"magical"},
        )
        dmg_event, dp_events = apply_damage(
            target, [packet], creature_id=creature_id,
        )
        dmg_event.source_id = zone.caster_id
        dmg_event.target_id = creature_id
        dmg_event.message = f"{target.name} {dmg_event.message}"
        events.append(dmg_event)
        events.extend(dp_events)

        # Concentration check on the damaged creature
        conc_events = check_concentration(
            target, creature_id, dmg_event.details.get("damage", total_dmg),
            combatants=combatants,
        )
        events.extend(conc_events)

    # Condition on a failed save (Sleet Storm → prone, Stinking Cloud → retching).
    # Reuses the save already rolled above (same ability/DC).
    if zone.condition_on_fail and not success:
        from arena.combat.conditions import apply_condition
        from arena.models.conditions import Condition
        try:
            cond = Condition(zone.condition_on_fail)
        except ValueError:
            cond = None
        if cond is not None:
            cev = apply_condition(
                target, creature_id, cond, source=zone.name,
                duration_type=zone.condition_duration_type,
            )
            if cev:
                events.append(cev)

    zone.already_damaged.add(creature_id)
    return events


# ------------------------------------------------------------------
# Turn / movement hooks
# ------------------------------------------------------------------

def process_zone_start_of_turn(
    zones: list[ActiveZone],
    creature_id: str,
    combatants: dict[str, Combatant],
    grid: HexGrid | None,
) -> list[CombatEvent]:
    """Process zone damage for a creature starting its turn.

    Called at the beginning of the creature's turn, after normal
    start-of-turn condition processing.
    """
    events: list[CombatEvent] = []
    creature_comb = combatants.get(creature_id)
    if creature_comb is None:
        return events

    for zone in zones:
        # Movement hazards (Spike Growth) deal damage per 5 ft TRAVELLED, not
        # for starting a turn here — handled by process_zone_movement_step.
        if zone.movement_hazard_dice:
            continue
        # Don't damage the zone's own caster
        if creature_id == zone.caster_id:
            continue
        # Enemy-only filtering
        if zone.affects_enemies_only and creature_comb.team == zone.team:
            continue
        # Already damaged this round (shouldn't happen at start-of-turn,
        # but guard against it)
        if creature_id in zone.already_damaged:
            continue
        # Check if creature is inside the zone
        if is_in_zone(creature_id, zone, combatants, grid):
            events.extend(_resolve_zone_damage(zone, creature_id, combatants))

    return events


def process_zone_entry(
    zones: list[ActiveZone],
    creature_id: str,
    combatants: dict[str, Combatant],
    grid: HexGrid | None,
) -> list[CombatEvent]:
    """Process zone damage when a creature moves into a zone.

    Called after each movement step.  Only triggers if the creature
    wasn't already damaged by this zone this round.
    """
    events: list[CombatEvent] = []
    creature_comb = combatants.get(creature_id)
    if creature_comb is None:
        return events

    for zone in zones:
        # Movement hazards are resolved per step, not on one-time entry.
        if zone.movement_hazard_dice:
            continue
        if creature_id == zone.caster_id:
            continue
        if zone.affects_enemies_only and creature_comb.team == zone.team:
            continue
        if creature_id in zone.already_damaged:
            continue
        if is_in_zone(creature_id, zone, combatants, grid):
            events.extend(_resolve_zone_damage(zone, creature_id, combatants))

    return events


def _apply_hazard_tick(
    zone: ActiveZone,
    creature_id: str,
    combatants: dict[str, Combatant],
) -> list[CombatEvent]:
    """Deal one movement-hazard tick (e.g. Spike Growth's 2d4) to a creature.

    No save, no ``already_damaged`` guard — every 5 ft travelled hurts. Returns
    the damage + concentration-check events (empty if the roll was 0)."""
    from arena.combat.actions import apply_damage
    from arena.combat.concentration import check_concentration
    from arena.combat.damage import DamagePacket
    from arena.util.dice import roll_expression

    creature_comb = combatants.get(creature_id)
    if creature_comb is None:
        return []
    total_dmg, _rolls = roll_expression(zone.movement_hazard_dice or "0")
    if total_dmg <= 0:
        return []

    target = creature_comb.creature
    events: list[CombatEvent] = []
    packet = DamagePacket(
        amount=total_dmg, dtype=zone.movement_hazard_type,
        source=zone.name, tags={"magical"},
    )
    dmg_event, dp_events = apply_damage(target, [packet], creature_id=creature_id)
    dmg_event.source_id = zone.caster_id
    dmg_event.target_id = creature_id
    dmg_event.message = f"{target.name} {dmg_event.message}"
    events.append(dmg_event)
    events.extend(dp_events)
    events.extend(check_concentration(
        target, creature_id, dmg_event.details.get("damage", total_dmg),
        combatants=combatants,
    ))
    return events


def process_zone_movement_step(
    zones: list[ActiveZone],
    creature_id: str,
    combatants: dict[str, Combatant],
    grid: HexGrid | None,
) -> list[CombatEvent]:
    """Resolve movement-hazard damage for a single 5-ft step (D-CTRL-1).

    Called after each successful voluntary movement step. For every movement-
    hazard zone (Spike Growth) whose area now contains the creature, deal the
    hazard dice with NO save — 2d4 per 5 ft. Every step that lands in the spikes
    hurts, including the step that first enters them.
    """
    events: list[CombatEvent] = []
    if combatants.get(creature_id) is None:
        return events

    for zone in zones:
        if not zone.movement_hazard_dice:
            continue
        # The caster of Spike Growth still takes damage moving through it RAW,
        # but the established zone convention spares the caster; keep that.
        if creature_id == zone.caster_id:
            continue
        if not is_in_zone(creature_id, zone, combatants, grid):
            continue
        events.extend(_apply_hazard_tick(zone, creature_id, combatants))

    return events


def process_zone_movement_path(
    zones: list[ActiveZone],
    creature_id: str,
    from_hex: HexCoord,
    to_hex: HexCoord,
    combatants: dict[str, Combatant],
    grid: HexGrid | None,
) -> list[CombatEvent]:
    """Resolve movement-hazard damage along a FORCED move's path (D-AOE-1).

    Forced movement (push/pull) teleports a creature straight to its destination,
    so — unlike a voluntary hex-by-hex walk — there is no per-step hook. This
    reconstructs the line of hexes the creature crossed (``hex_line``) and deals
    one hazard tick (2d4, no save) for every spike hex on that path, matching RAW
    "2d4 per 5 ft travelled (voluntary or forced)".
    """
    from arena.grid.line_of_sight import hex_line

    events: list[CombatEvent] = []
    creature_comb = combatants.get(creature_id)
    if creature_comb is None or grid is None:
        return events

    path = hex_line(from_hex, to_hex)[1:]  # exclude the starting hex
    if not path:
        return events

    for zone in zones:
        if not zone.movement_hazard_dice or creature_id == zone.caster_id:
            continue
        zone_hexes = {(h.q, h.r) for h in get_zone_hexes(zone, combatants, grid)}
        for ph in path:
            if (ph.q, ph.r) in zone_hexes:
                events.extend(_apply_hazard_tick(zone, creature_id, combatants))
                if not creature_comb.creature.is_conscious:
                    break

    return events


# ------------------------------------------------------------------
# Lifecycle helpers
# ------------------------------------------------------------------

def remove_zones_for_caster(
    zones: list[ActiveZone],
    caster_id: str,
) -> list[ActiveZone]:
    """Return a new list with all zones belonging to *caster_id* removed."""
    return [z for z in zones if z.caster_id != caster_id]


def reset_zone_round_tracking(zones: list[ActiveZone]) -> None:
    """Clear per-round ``already_damaged`` sets at the start of a new round."""
    for zone in zones:
        zone.already_damaged.clear()
