"""Ready action system for holding actions with triggers.

Per 5e rules:
- Ready uses your action to set up a trigger and a response.
- When the trigger occurs, you use your reaction to execute the response.
- If the trigger never occurs, the action is wasted.
- Readied actions expire at the start of your next turn.
- Readied spells require concentration (handled elsewhere).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from arena.models.actions import Action
from arena.combat.events import CombatEvent, CombatEventType

if TYPE_CHECKING:
    from arena.combat.manager import CombatManager


class TriggerType(str, Enum):
    """Types of triggers for readied actions."""

    CREATURE_MOVES = "creature_moves"      # A specific creature moves
    CREATURE_ENTERS_RANGE = "enters_range"  # A creature enters reach/range
    CREATURE_ATTACKS = "creature_attacks"    # A creature makes an attack
    CREATURE_CASTS = "creature_casts"       # A creature casts a spell
    CUSTOM = "custom"                       # Freeform (for display only)


@dataclass
class ReadiedAction:
    """A readied action waiting to be triggered.

    Attributes:
        creature_id: ID of the creature holding the action.
        action: The action being readied.
        trigger_type: What kind of event triggers the action.
        trigger_target_id: Optional specific creature that triggers it.
        description: Human-readable description of the trigger.
    """

    creature_id: str
    action: Action
    trigger_type: TriggerType
    trigger_target_id: str | None = None
    description: str = ""


def set_ready_action(
    manager: CombatManager,
    action: Action,
    trigger_type: TriggerType,
    trigger_target_id: str | None = None,
    description: str = "",
) -> CombatEvent | None:
    """Ready an action with a specified trigger.

    Uses the action slot. The readied action fires as a reaction when triggered.

    Args:
        manager: The combat manager.
        action: The action to ready.
        trigger_type: When the action should trigger.
        trigger_target_id: Optional specific creature to watch.
        description: Human-readable trigger description.

    Returns:
        A combat event, or None if invalid.
    """
    combatant = manager.active_combatant
    if combatant is None:
        return None
    if manager.turn_resources.has_used_action:
        return None

    manager.turn_resources.has_used_action = True

    readied = ReadiedAction(
        creature_id=combatant.creature_id,
        action=action,
        trigger_type=trigger_type,
        trigger_target_id=trigger_target_id,
        description=description or f"Trigger: {trigger_type.value}",
    )
    manager.readied_actions[combatant.creature_id] = readied

    trigger_text = description or trigger_type.value
    return CombatEvent(
        event_type=CombatEventType.INFO,
        message=(
            f"{combatant.creature.name} readies {action.name}! "
            f"({trigger_text})"
        ),
        source_id=combatant.creature_id,
        details={
            "action": "ready",
            "readied_action": action.name,
            "trigger_type": trigger_type.value,
            "trigger_target_id": trigger_target_id,
        },
    )


def check_ready_triggers(
    manager: CombatManager,
    trigger_type: TriggerType,
    trigger_creature_id: str | None = None,
) -> list[CombatEvent]:
    """Check if any readied actions should trigger.

    Called after events that could match triggers (movement, attacks, etc.).
    Matching readied actions are executed as reactions and removed.

    Args:
        manager: The combat manager.
        trigger_type: The type of event that just occurred.
        trigger_creature_id: The creature that caused the trigger.

    Returns:
        List of events from triggered actions.
    """
    events: list[CombatEvent] = []
    to_remove: list[str] = []

    for cid, readied in manager.readied_actions.items():
        # Skip if creature already used reaction
        if manager.reaction_used.get(cid, False):
            continue

        # Check trigger match
        if readied.trigger_type != trigger_type:
            continue

        # If trigger has a specific target, check it
        if readied.trigger_target_id and readied.trigger_target_id != trigger_creature_id:
            continue

        # Trigger matched! Execute the readied action as a reaction
        combatant = manager.combatants.get(cid)
        if combatant is None or not combatant.creature.is_conscious:
            to_remove.append(cid)
            continue

        # Mark reaction as used
        manager.reaction_used[cid] = True
        to_remove.append(cid)

        # Announce the triggered action
        events.append(
            CombatEvent(
                event_type=CombatEventType.REACTION,
                message=(
                    f"{combatant.creature.name}'s readied action triggers! "
                    f"Using {readied.action.name} as a reaction."
                ),
                source_id=cid,
                details={
                    "reaction_type": "readied_action",
                    "action_name": readied.action.name,
                    "trigger_type": trigger_type.value,
                },
            )
        )

        # If the action has an attack and there's a valid target, resolve it
        if readied.action.attack and trigger_creature_id:
            target = manager.combatants.get(trigger_creature_id)
            if target and manager.grid:
                from arena.combat.actions import resolve_attack

                result = resolve_attack(
                    attacker=combatant.creature,
                    attacker_id=cid,
                    target=target.creature,
                    target_id=trigger_creature_id,
                    action=readied.action,
                    grid=manager.grid,
                    combatants=manager.combatants,
                    attacker_pos=combatant.position,
                    target_pos=target.position,
                )
                events.extend(result.events)

    # Clean up triggered/expired readied actions
    for cid in to_remove:
        manager.readied_actions.pop(cid, None)

    return events


def expire_readied_actions(manager: CombatManager, creature_id: str) -> list[CombatEvent]:
    """Expire readied actions at the start of the creature's turn.

    Called during _start_current_turn.

    Args:
        manager: The combat manager.
        creature_id: The creature whose turn is starting.

    Returns:
        List of expiry events.
    """
    events: list[CombatEvent] = []
    readied = manager.readied_actions.pop(creature_id, None)
    if readied:
        combatant = manager.combatants.get(creature_id)
        name = combatant.creature.name if combatant else creature_id
        events.append(
            CombatEvent(
                event_type=CombatEventType.INFO,
                message=f"{name}'s readied {readied.action.name} expires unused.",
                source_id=creature_id,
                details={"action": "ready_expired", "readied_action": readied.action.name},
            )
        )
    return events
