"""Creature-type-based bonus damage for actions like Divine Smite vs undead."""

from arena.models.actions import Action
from arena.models.character import Creature


def check_creature_type_bonus(action: Action, target: Creature) -> str | None:
    """Check if an action's creature type bonus applies to the target.

    Args:
        action: The action being used.
        target: The creature being targeted.

    Returns:
        The bonus damage dice string (e.g., "1d8") if the target matches,
        None otherwise.
    """
    if not action.creature_type_bonus_damage or not action.creature_type_bonus_types:
        return None

    target_type = target.creature_type.value.lower()
    bonus_types = [t.lower() for t in action.creature_type_bonus_types]

    if target_type in bonus_types:
        return action.creature_type_bonus_damage
    return None
