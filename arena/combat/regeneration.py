"""Regeneration (D-MON-3).

A creature with `regeneration_amount` heals that many HP at the start of each of
its turns — unless it took damage of a `regeneration_negated_by` type (Troll:
acid/fire) since its last turn, in which case the heal is suppressed for that one
turn. The negation flag is set by apply_damage and read/cleared here.

Deliberate deviation from RAW: a creature already at 0 HP does NOT regenerate
(the Arena treats a 0-HP monster as defeated), so there is no troll-back-from-0.
"""

from arena.combat.events import CombatEvent, CombatEventType


def process_regeneration_start_of_turn(creature, creature_id: str) -> list[CombatEvent]:
    amount = getattr(creature, "regeneration_amount", 0)
    if amount <= 0:
        return []
    current = creature.current_hit_points if creature.current_hit_points is not None else 0
    if current <= 0:
        return []  # defeated — no regeneration from 0

    if getattr(creature, "_regeneration_negated", False):
        creature._regeneration_negated = False  # consume the one-turn suppression
        return [CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{creature.name}'s regeneration is suppressed this turn.",
            source_id=creature_id,
            details={"regeneration_suppressed": True},
        )]

    from arena.combat.condition_effects import effective_max_hp
    cap = effective_max_hp(creature)  # exhaustion 4+ halves the max (D-COND-2)
    if current >= cap:
        return []  # already at full HP

    healed = min(amount, cap - current)
    creature.current_hit_points = current + healed
    return [CombatEvent(
        event_type=CombatEventType.INFO,
        message=(f"{creature.name} regenerates {healed} HP "
                 f"({creature.current_hit_points}/{cap})."),
        source_id=creature_id,
        details={"regeneration": True, "healed": healed},
    )]
