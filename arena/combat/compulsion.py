"""Compulsion — a 4th-level enchantment that yanks creatures around (P-CONTROL).

On a failed Wisdom save the target gains the COMPELLED condition: at the start of
each of its turns it must spend its movement being drawn toward the caster, and it
can't take reactions, for the spell's (concentration) duration. State lives on the
condition's ``extra_data`` (just the caster id) — no manager-side bookkeeping — so
the Arena's transient-subprocess model stays clean. Reversion rides the caster's
concentration link: when concentration drops, the generic cleanup removes the
COMPELLED condition (there's no team/control to restore, unlike domination).

Simplifications vs RAW (fun > fiddly — matching the domination call):
  * "a direction you choose" is modeled as *toward the caster* (a deterministic
    draw); the caster's bonus-action redirect folds into that automatic pull.
  * single-target, not the RAW area-of-effect (stays within the one-target cast
    dispatch).
  * no per-turn re-save — Compulsion ends only when the caster drops concentration
    or the duration lapses (which is RAW: base Compulsion grants no repeat save).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.combat.conditions import apply_condition, remove_condition, has_condition
from arena.combat.events import CombatEvent, CombatEventType

if TYPE_CHECKING:
    from arena.combat.manager import CombatManager, Combatant


def is_compelled(creature: Creature) -> bool:
    return has_condition(creature, Condition.COMPELLED)


def _compulsion_data(creature: Creature) -> dict | None:
    for ac in creature.active_conditions:
        if ac.condition == Condition.COMPELLED:
            return ac.extra_data
    return None


def start_compulsion(
    target: Creature,
    target_id: str,
    caster: Creature,
    caster_id: str,
    dc: int,
) -> list[CombatEvent]:
    """Apply COMPELLED to ``target``. Returns events."""
    events: list[CombatEvent] = []
    ev = apply_condition(
        target, target_id, Condition.COMPELLED, source=caster.name,
        duration_type="indefinite",
        extra_data={"caster_id": caster_id, "save_dc": dc},
    )
    if ev:
        events.append(ev)
    events.append(CombatEvent(
        event_type=CombatEventType.INFO,
        message=f"{target.name} is compelled by {caster.name} — drawn helplessly toward them!",
        source_id=caster_id, target_id=target_id,
        details={"compelled": True, "compulsion_started": True},
    ))
    return events


def end_compulsion(
    target: Creature,
    target_id: str,
    combatants: dict[str, "Combatant"] | None = None,
) -> list[CombatEvent]:
    """Clear COMPELLED from a creature (also reachable via the generic
    concentration cleanup — there's no team/control to restore)."""
    events: list[CombatEvent] = []
    ev = remove_condition(target, target_id, Condition.COMPELLED)
    if ev:
        events.append(ev)
    events.append(CombatEvent(
        event_type=CombatEventType.INFO,
        message=f"{target.name} is no longer compelled.",
        target_id=target_id,
        details={"compulsion_ended": True},
    ))
    return events


def process_compulsion_start_of_turn(
    manager: "CombatManager", combatant: "Combatant",
) -> list[CombatEvent]:
    """At the start of a compelled creature's turn: drag it toward the caster,
    spending its movement, and bar it from reactions for the round.

    Called from ``_start_current_turn`` after movement has been reset (so the
    full speed is available as the pull distance) and the creature is on-grid."""
    creature = combatant.creature
    cid = combatant.creature_id
    data = _compulsion_data(creature)
    if data is None:
        return []

    events: list[CombatEvent] = []

    # Can't take reactions while compelled — re-asserted each of its turns so the
    # bar holds across the other combatants' turns until its next reset.
    manager.reaction_used[cid] = True

    caster_id = data.get("caster_id")
    caster_pos = manager.grid.find_creature(caster_id) if caster_id else None
    target_pos = manager.grid.find_creature(cid)
    # Caster gone / either side off-grid (banished, downed): nothing to pull to.
    if caster_pos is None or target_pos is None:
        return events

    speed = manager.movement.remaining_movement
    if speed <= 0 or caster_pos == target_pos:
        return events

    from arena.combat.forced_movement import resolve_forced_movement
    result = resolve_forced_movement(
        source_id=caster_id, source_pos=caster_pos,
        target_id=cid, target_pos=target_pos,
        movement_type="pull", distance_feet=speed,
        grid=manager.grid, combatants=manager.combatants,
        target_creature=creature,
    )
    events.extend(result.events)
    # The forced draw consumes the creature's movement for the turn.
    manager.movement.remaining_movement = 0
    return events
