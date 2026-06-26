"""Standard actions available to all creatures during combat.

These are built-in actions that don't require creature-specific data:
Dash, Disengage, Dodge, Help, Hide.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from arena.combat.events import CombatEvent, CombatEventType
from arena.combat.conditions import apply_condition, has_condition, remove_condition
from arena.combat.stat_modifiers import (
    has_stealth_disadvantage,
    get_effective_speed,
    get_effective_ability_modifier,
)
from arena.models.conditions import Condition
from arena.util.dice import roll_die, roll_with_disadvantage

if TYPE_CHECKING:
    from arena.combat.manager import CombatManager


def execute_dash(
    manager: CombatManager, *, consume_action: bool = True
) -> CombatEvent | None:
    """Use the Dash action to double remaining movement this turn.

    Adds the creature's base speed to their remaining movement.
    Uses the action slot, unless ``consume_action`` is False — then the
    caller owns the economy (Cunning Action's bonus-action Dash).

    Returns:
        A combat event describing the dash, or None if invalid.
    """
    combatant = manager.active_combatant
    if combatant is None:
        return None
    if consume_action and manager.turn_resources.has_used_action:
        return None

    # Dash grants extra movement equal to the creature's CURRENT speed, so it
    # honours the same condition multiplier the turn budget uses — halved by
    # exhaustion 2-4 (D-COND-2), zero when speed is 0 (exhaustion 5+, grappled,
    # restrained). int() floors, matching the turn-start budget calc.
    from arena.combat.condition_effects import get_movement_multiplier
    base_speed = get_effective_speed(combatant.creature)
    dash_bonus = int(base_speed * get_movement_multiplier(combatant.creature))
    manager.movement.remaining_movement += dash_bonus
    if consume_action:
        manager.turn_resources.has_used_action = True

    return CombatEvent(
        event_type=CombatEventType.INFO,
        message=(
            f"{combatant.creature.name} uses Dash! "
            f"Movement: {manager.movement.remaining_movement} ft"
        ),
        source_id=combatant.creature_id,
        details={"action": "dash", "extra_movement": dash_bonus},
    )


def execute_disengage(
    manager: CombatManager, *, consume_action: bool = True
) -> CombatEvent | None:
    """Use the Disengage action to avoid opportunity attacks this turn.

    Sets the is_disengaging flag on turn resources.
    Uses the action slot, unless ``consume_action`` is False (Cunning Action).

    Returns:
        A combat event, or None if invalid.
    """
    combatant = manager.active_combatant
    if combatant is None:
        return None
    if consume_action and manager.turn_resources.has_used_action:
        return None

    if consume_action:
        manager.turn_resources.has_used_action = True
    manager.turn_resources.is_disengaging = True

    return CombatEvent(
        event_type=CombatEventType.INFO,
        message=(
            f"{combatant.creature.name} uses Disengage! "
            f"Movement won't provoke opportunity attacks."
        ),
        source_id=combatant.creature_id,
        details={"action": "disengage"},
    )


def execute_dodge(
    manager: CombatManager, *, consume_action: bool = True
) -> CombatEvent | None:
    """Use the Dodge action.

    Applies the DODGING pseudo-condition, which gives attackers
    disadvantage and grants advantage on DEX saves.
    The condition lasts until the start of the creature's next turn.
    Uses the action slot, unless ``consume_action`` is False.

    Returns:
        A combat event, or None if invalid.
    """
    combatant = manager.active_combatant
    if combatant is None:
        return None
    if consume_action and manager.turn_resources.has_used_action:
        return None

    if consume_action:
        manager.turn_resources.has_used_action = True
    apply_condition(
        combatant.creature,
        combatant.creature_id,
        Condition.DODGING,
        source="dodge_action",
        duration_type="rounds",
        duration_rounds=1,
    )

    return CombatEvent(
        event_type=CombatEventType.INFO,
        message=(
            f"{combatant.creature.name} uses Dodge! "
            f"Attacks have disadvantage, DEX saves with advantage."
        ),
        source_id=combatant.creature_id,
        details={"action": "dodge"},
    )


def execute_help(
    manager: CombatManager, target_id: str
) -> CombatEvent | None:
    """Use the Help action to give an ally advantage on their next attack.

    Applies the HELPED pseudo-condition to the target ally.
    Target must be within 5 feet (1 hex).
    Uses the action slot.

    Args:
        manager: The combat manager.
        target_id: creature_id of the ally to help.

    Returns:
        A combat event, or None if invalid.
    """
    combatant = manager.active_combatant
    if combatant is None or manager.grid is None:
        return None
    if manager.turn_resources.has_used_action:
        return None

    target = manager.combatants.get(target_id)
    if target is None:
        return None

    # Must be within 5 feet (1 hex)
    combatant_pos = manager.grid.find_creature(combatant.creature_id)
    target_pos = manager.grid.find_creature(target_id)
    if combatant_pos is None or target_pos is None:
        return None

    distance = combatant_pos.distance_to(target_pos) * 5
    if distance > 5:
        return CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{target.creature.name} is too far to Help (must be within 5 ft)",
            source_id=combatant.creature_id,
        )

    manager.turn_resources.has_used_action = True
    apply_condition(
        target.creature,
        target_id,
        Condition.HELPED,
        source=combatant.creature_id,
        duration_type="rounds",
        duration_rounds=2,
    )

    return CombatEvent(
        event_type=CombatEventType.INFO,
        message=(
            f"{combatant.creature.name} uses Help on {target.creature.name}! "
            f"{target.creature.name} has advantage on their next attack."
        ),
        source_id=combatant.creature_id,
        target_id=target_id,
        details={"action": "help"},
    )


def execute_action_surge(manager: CombatManager) -> CombatEvent | None:
    """Use Action Surge to gain an additional action this turn.

    Per 5e rules (Fighter 2+):
    - Costs 1 use of action_surge resource.
    - Grants one additional action on this turn.
    - Does not cost an action or bonus action to use.
    - Recharges on a short or long rest.

    Returns:
        A combat event describing the surge, or None if invalid.
    """
    combatant = manager.active_combatant
    if combatant is None:
        return None

    creature = combatant.creature
    class_resources = getattr(creature, "class_resources", None)
    if not class_resources or class_resources.get("action_surge", 0) <= 0:
        return None

    # Deduct the resource
    class_resources["action_surge"] -= 1

    # Reset the action slot so the creature can take another action
    manager.turn_resources.has_used_action = False

    return CombatEvent(
        event_type=CombatEventType.INFO,
        message=(
            f"{combatant.creature.name} uses Action Surge! "
            f"An additional action is available this turn."
        ),
        source_id=combatant.creature_id,
        details={"action": "action_surge"},
    )


def execute_stabilize(manager: CombatManager, target_id: str) -> CombatEvent | None:
    """Administer first aid to an adjacent dying ally (5e RAW).

    Uses the action to make a DC 10 Wisdom (Medicine) check on an unconscious,
    dying creature within 5 ft. On success the ally is stabilized (stops rolling
    death saves, stays at 0 HP). Returns None if the action is unavailable or
    the target isn't a valid dying creature.

    Args:
        manager: The combat manager.
        target_id: creature_id of the dying ally to stabilize.

    Returns:
        A combat event describing the result, or None if invalid.
    """
    combatant = manager.active_combatant
    if combatant is None or manager.grid is None:
        return None
    if manager.turn_resources.has_used_action:
        return None

    target = manager.combatants.get(target_id)
    if target is None:
        return None
    tc = target.creature
    # Must be a dying creature: at 0 HP, runs death saves, not already stable.
    if tc.is_conscious or not hasattr(tc, "death_save_successes"):
        return None
    if getattr(tc, "is_stabilized", False):
        return CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{tc.name} is already stable.",
            source_id=combatant.creature_id,
        )

    combatant_pos = manager.grid.find_creature(combatant.creature_id)
    target_pos = manager.grid.find_creature(target_id)
    if combatant_pos is None or target_pos is None:
        return None
    if combatant_pos.distance_to(target_pos) * 5 > 5:
        return CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{tc.name} is too far to stabilize (must be within 5 ft).",
            source_id=combatant.creature_id,
        )

    manager.turn_resources.has_used_action = True
    wis_mod = get_effective_ability_modifier(combatant.creature, "wisdom")
    roll = roll_die(20)
    total = roll + wis_mod
    success = total >= 10

    if success:
        from arena.combat.death_saves import stabilize_creature
        stabilize_creature(tc)
        msg = (f"{combatant.creature.name} stabilizes {tc.name}! "
               f"(Medicine {total} vs DC 10)")
    else:
        msg = (f"{combatant.creature.name} fails to stabilize {tc.name}. "
               f"(Medicine {total} vs DC 10)")

    return CombatEvent(
        event_type=CombatEventType.INFO,
        message=msg,
        source_id=combatant.creature_id,
        target_id=target_id,
        details={"action": "stabilize", "roll": total, "success": success},
    )


def execute_stand_up(manager: CombatManager) -> CombatEvent | None:
    """Stand up from prone, spending half the creature's speed in movement.

    Per 5e RAW, standing up costs an amount of movement equal to half the
    creature's speed and removes the PRONE condition. It is part of movement,
    NOT an action — so it does not touch the action/bonus-action economy and
    remains available even after the creature has attacked this turn.

    Fails (returns an info event, no state change) if the creature isn't
    prone or doesn't have enough movement left to stand.

    Returns:
        A combat event describing the result, or None if invalid.
    """
    combatant = manager.active_combatant
    if combatant is None:
        return None
    if not has_condition(combatant.creature, Condition.PRONE):
        return None

    base_speed = get_effective_speed(combatant.creature)
    stand_cost = base_speed // 2

    # A creature with no speed (0) can't stand up at all per RAW.
    if base_speed <= 0:
        return CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{combatant.creature.name} has no speed and cannot stand up.",
            source_id=combatant.creature_id,
        )

    if manager.movement.remaining_movement < stand_cost:
        return CombatEvent(
            event_type=CombatEventType.INFO,
            message=(
                f"{combatant.creature.name} needs {stand_cost} ft of movement to "
                f"stand up (only {manager.movement.remaining_movement} ft left)."
            ),
            source_id=combatant.creature_id,
        )

    manager.movement.remaining_movement -= stand_cost
    remove_condition(combatant.creature, combatant.creature_id, Condition.PRONE)
    # Standing clears the crawl penalty for the rest of the turn.
    manager.movement.cost_multiplier = 1

    return CombatEvent(
        event_type=CombatEventType.INFO,
        message=(
            f"{combatant.creature.name} stands up "
            f"(spent {stand_cost} ft; {manager.movement.remaining_movement} ft left)."
        ),
        source_id=combatant.creature_id,
        details={"action": "stand_up", "movement_cost": stand_cost},
    )


def execute_hide(
    manager: CombatManager, *, consume_action: bool = True
) -> CombatEvent | None:
    """Use the Hide action to attempt to become hidden.

    Makes a Dexterity (Stealth) check vs the highest passive Perception
    among hostile creatures that can see the hiding creature.
    Uses the action slot, unless ``consume_action`` is False (Cunning
    Action / Vanish hide as a bonus action — the check still rolls).

    Returns:
        A combat event describing the result, or None if invalid.
    """
    combatant = manager.active_combatant
    if combatant is None:
        return None
    if consume_action and manager.turn_resources.has_used_action:
        return None

    if consume_action:
        manager.turn_resources.has_used_action = True

    # Roll stealth check: d20 + DEX modifier
    # Armor with stealth_disadvantage imposes disadvantage on Stealth checks
    dex_mod = get_effective_ability_modifier(combatant.creature, "dexterity")
    if has_stealth_disadvantage(combatant.creature):
        stealth_roll, _, _ = roll_with_disadvantage()
        stealth_roll += dex_mod
    else:
        stealth_roll = roll_die(20) + dex_mod

    # Find highest passive Perception among hostile combatants
    highest_pp = 10  # Default if no enemies have passive_perception set
    for cid, c in manager.combatants.items():
        if c.team == combatant.team:
            continue
        if not c.creature.is_conscious:
            continue
        # Passive Perception = 10 + WIS modifier (or explicit value)
        pp = getattr(c.creature, "passive_perception", None)
        if pp is None:
            pp = 10 + get_effective_ability_modifier(c.creature, "wisdom")
        highest_pp = max(highest_pp, pp)

    success = stealth_roll >= highest_pp

    if success:
        apply_condition(
            combatant.creature,
            combatant.creature_id,
            Condition.HIDDEN,
            source="hide_action",
            duration_type="indefinite",
        )
        return CombatEvent(
            event_type=CombatEventType.INFO,
            message=(
                f"{combatant.creature.name} uses Hide! "
                f"Stealth {stealth_roll} vs PP {highest_pp} - SUCCESS! "
                f"{combatant.creature.name} is now hidden."
            ),
            source_id=combatant.creature_id,
            details={
                "action": "hide",
                "stealth_roll": stealth_roll,
                "passive_perception": highest_pp,
                "success": True,
            },
        )
    else:
        return CombatEvent(
            event_type=CombatEventType.INFO,
            message=(
                f"{combatant.creature.name} uses Hide! "
                f"Stealth {stealth_roll} vs PP {highest_pp} - FAILED! "
                f"{combatant.creature.name} fails to hide."
            ),
            source_id=combatant.creature_id,
            details={
                "action": "hide",
                "stealth_roll": stealth_roll,
                "passive_perception": highest_pp,
                "success": False,
            },
        )
