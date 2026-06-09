"""Concentration tracking and checks per 5e rules.

Key rules:
- Only one concentration effect at a time; starting a new one ends the old.
- Taking damage requires a CON save (DC = max(10, damage // 2)).
- Failing the save ends concentration.
- Being incapacitated or dying also ends concentration.
- Ending concentration removes the spell's conditions from all targets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.combat.conditions import apply_condition, remove_condition, has_condition
from arena.combat.events import CombatEvent, CombatEventType
from arena.combat.buff_effects import remove_buff

if TYPE_CHECKING:
    # Avoid circular import — only used for type hints.
    from arena.combat.manager import Combatant


def start_concentrating(
    creature: Creature,
    creature_id: str,
    source: str,
    combatants: dict[str, Combatant] | None = None,
) -> list[CombatEvent]:
    """Begin concentrating on an effect.

    If already concentrating, the old effect ends first (one-at-a-time rule).
    Ending the old effect also removes its linked conditions from targets.

    Args:
        creature: The creature beginning concentration.
        creature_id: Unique ID for logging.
        source: Name of the spell/effect being concentrated on.
        combatants: The combat manager's combatant registry, needed to
            clean up linked conditions from a previous concentration.

    Returns:
        List of events (may include a CONDITION_REMOVED for dropping old concentration,
        plus a CONDITION_APPLIED for the new one).
    """
    events: list[CombatEvent] = []

    # End existing concentration first (including target cleanup)
    if has_condition(creature, Condition.CONCENTRATING):
        end_events = end_concentration(creature, creature_id, combatants)
        events.extend(end_events)

    # Apply CONCENTRATING condition (indefinite duration, tracks the source)
    extra = {
        "spell": source,
        "linked_targets": [],
        "linked_buffs": [],
    }
    event = apply_condition(
        creature,
        creature_id,
        Condition.CONCENTRATING,
        source=source,
        duration_type="indefinite",
        extra_data=extra,
    )
    if event:
        events.append(event)

    return events


def add_concentration_link(
    creature: Creature,
    target_id: str,
    condition_name: str,
) -> None:
    """Register an additional target/condition link on an active concentration.

    Called after a condition is successfully applied to a target by a
    concentration spell, so that the link exists for cleanup later.
    """
    for ac in creature.active_conditions:
        if ac.condition == Condition.CONCENTRATING:
            links = ac.extra_data.setdefault("linked_targets", [])
            links.append([target_id, condition_name])
            return


def add_concentration_buff_link(
    creature: Creature,
    target_id: str,
    buff_name: str,
) -> None:
    """Register a buff link on an active concentration.

    Called after a buff is applied to a target by a concentration spell,
    so that the buff is removed when concentration ends.
    """
    for ac in creature.active_conditions:
        if ac.condition == Condition.CONCENTRATING:
            links = ac.extra_data.setdefault("linked_buffs", [])
            links.append([target_id, buff_name])
            return


def check_concentration(
    creature: Creature,
    creature_id: str,
    damage_taken: int,
    combatants: dict[str, Combatant] | None = None,
) -> list[CombatEvent]:
    """Check if concentration is maintained after taking damage.

    DC = max(10, damage_taken // 2) per 5e rules.

    Args:
        creature: The creature maintaining concentration.
        creature_id: Unique ID for logging.
        damage_taken: Amount of damage taken (after modifiers).
        combatants: The combat manager's combatant registry, needed to
            clean up linked conditions on targets if concentration drops.

    Returns:
        List of events. Empty if not concentrating. Includes the saving throw
        event and, if failed, the concentration-dropped event.
    """
    if not has_condition(creature, Condition.CONCENTRATING):
        return []

    events: list[CombatEvent] = []

    dc = max(10, damage_taken // 2)

    from arena.combat.actions import resolve_saving_throw

    success, save_event = resolve_saving_throw(
        creature, creature_id, "constitution", dc
    )
    # Annotate the save event
    save_event.message = f"Concentration check: {save_event.message}"
    save_event.details["concentration_check"] = True
    save_event.details["damage_taken"] = damage_taken
    events.append(save_event)

    if not success:
        end_events = end_concentration(creature, creature_id, combatants)
        events.extend(end_events)

    return events


def end_concentration(
    creature: Creature,
    creature_id: str,
    combatants: dict[str, Combatant] | None = None,
) -> list[CombatEvent]:
    """End concentration, removing the CONCENTRATING condition and any
    linked conditions from targets.

    Args:
        creature: The creature losing concentration.
        creature_id: Unique ID for logging.
        combatants: The combat manager's combatant registry.  When
            provided, any conditions that were applied by the
            concentrated spell are removed from their targets.

    Returns:
        List of events.
    """
    events: list[CombatEvent] = []

    # Gather linked targets and buffs before removing the condition
    linked_targets: list[tuple[str, str]] = []
    linked_buffs: list[tuple[str, str]] = []
    for ac in creature.active_conditions:
        if ac.condition == Condition.CONCENTRATING:
            linked_targets = [
                tuple(pair) for pair in ac.extra_data.get("linked_targets", [])
            ]
            linked_buffs = [
                tuple(pair) for pair in ac.extra_data.get("linked_buffs", [])
            ]
            break

    event = remove_condition(creature, creature_id, Condition.CONCENTRATING)
    if event:
        events.append(event)

    # Clean up conditions on targets
    if combatants and linked_targets:
        for target_id, cond_name in linked_targets:
            target_combatant = combatants.get(target_id)
            if target_combatant is None:
                continue
            try:
                cond = Condition(cond_name)
            except ValueError:
                continue
            rm_event = remove_condition(
                target_combatant.creature, target_id, cond,
            )
            if rm_event:
                events.append(rm_event)

    # Clean up buffs on targets
    if combatants and linked_buffs:
        for target_id, buff_name in linked_buffs:
            target_combatant = combatants.get(target_id)
            if target_combatant is None:
                continue
            rm_event = remove_buff(
                target_combatant.creature, target_id, buff_name,
            )
            if rm_event:
                events.append(rm_event)

    return events
