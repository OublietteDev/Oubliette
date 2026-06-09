"""Recurring action tracking for spells that can be reused on subsequent turns.

Sunbeam (action to fire beam again), Witch Bolt (action for auto damage),
Spiritual Weapon (bonus action to move + attack), Call Lightning (action for bolt).

This module provides pure functions for:
- Checking if a creature has an active recurring action
- Getting the recurring action details
- Creating the recurring action entry
"""

from dataclasses import dataclass
from arena.models.actions import Action


@dataclass
class ActiveRecurringAction:
    """Tracks an active recurring spell/effect that can be used on future turns."""

    action_name: str  # Name of the original action (e.g., "Sunbeam")
    source_action: Action  # The original Action object for reference
    action_type: str  # "action" or "bonus_action" — what it costs to reuse
    source_id: str = ""  # creature_id of the caster (set by CombatManager)
    damage_dice: str | None = None  # Damage on subsequent uses
    damage_type: str | None = None  # Damage type for recurring damage
    auto_hit: bool = False  # Witch Bolt: subsequent hits are automatic
    move_distance: int | None = None  # Spiritual Weapon: move before attacking
    linked_to_concentration: bool = False  # Ends when concentration ends
    target_id: str | None = None  # Witch Bolt: locked to original target
    remaining_rounds: int | None = None  # None = unlimited (concentration-based)


def create_recurring_action(
    action: Action,
    target_id: str | None = None,
) -> ActiveRecurringAction | None:
    """Create a recurring action entry from an Action that has recurring fields.

    Returns None if the action has no recurring properties.
    """
    if not action.recurring_action_type:
        return None

    return ActiveRecurringAction(
        action_name=action.name,
        source_action=action,
        action_type=action.recurring_action_type,
        damage_dice=action.recurring_damage_dice,
        damage_type=action.recurring_damage_type,
        auto_hit=action.recurring_auto_hit,
        move_distance=action.recurring_move_distance,
        linked_to_concentration=action.requires_concentration,
        target_id=target_id,
    )


def can_use_recurring_action(
    recurring: ActiveRecurringAction,
    available_action: bool = True,
    available_bonus: bool = True,
) -> bool:
    """Check if a recurring action can be used this turn.

    Args:
        recurring: The active recurring action.
        available_action: Whether the creature has their action available.
        available_bonus: Whether the creature has their bonus action available.
    """
    if recurring.action_type == "action":
        return available_action
    elif recurring.action_type == "bonus_action":
        return available_bonus
    return False


def get_recurring_damage(recurring: ActiveRecurringAction) -> tuple[str | None, str | None]:
    """Get the damage dice and type for a recurring action's subsequent use.

    Returns (damage_dice, damage_type) or (None, None) if no damage.
    """
    return recurring.damage_dice, recurring.damage_type
