"""Recharge abilities (D-MON-2).

A monster ability marked with `recharge_min` (e.g. a dragon's breath weapon,
"Recharge 5-6") is a single charge that, once spent, comes back probabilistically:
at the start of each of the creature's turns it rolls a d6 and recharges on a
result >= recharge_min. Availability rides the existing uses_per_rest gate —
current_uses == 0 means spent — so resolve_effect already refuses a spent breath
and this module only handles the refresh roll.
"""

from arena.combat.events import CombatEvent, CombatEventType
from arena.util.dice import roll_die


def process_recharge_start_of_turn(creature, creature_id: str) -> list[CombatEvent]:
    """Roll a d6 for each spent recharge ability the creature has; recharge any
    that meet their threshold. Returns the announcement events."""
    events: list[CombatEvent] = []
    for action in getattr(creature, "actions", []) or []:
        recharge_min = getattr(action, "recharge_min", None)
        if recharge_min is None:
            continue
        # Spent == the uses gate is exhausted. A still-charged ability is skipped.
        if action.current_uses is not None and action.current_uses <= 0:
            roll = roll_die(6)
            if roll >= recharge_min:
                action.current_uses = action.uses_per_rest or 1
                events.append(CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=f"{creature.name}'s {action.name} recharges! "
                            f"(rolled {roll} vs {recharge_min}+)",
                    source_id=creature_id,
                    details={"recharge": True, "action": action.name, "roll": roll},
                ))
    return events
