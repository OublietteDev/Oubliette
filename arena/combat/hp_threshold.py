"""HP threshold effect checks for spells like Power Word Kill/Stun, Toll the Dead."""

from arena.models.actions import Action
from arena.models.character import Creature


def check_hp_threshold(action: Action, target: Creature) -> str | None:
    """Check if the target meets the HP threshold for a special effect.

    Returns:
        The effect type ("kill", "condition", "bonus_damage_die") if threshold met,
        None otherwise.
    """
    if action.hp_threshold is None or action.hp_threshold_effect is None:
        return None

    current_hp = target.current_hit_points or 0
    if current_hp <= action.hp_threshold:
        return action.hp_threshold_effect
    return None


def check_damaged_threshold(action: Action, target: Creature) -> bool:
    """Check if target is missing HP (for Toll the Dead-style effects).

    For "bonus_damage_die" effect type, returns True if target is below max HP.
    """
    if action.hp_threshold_effect != "bonus_damage_die":
        return False
    if action.hp_threshold_alt_dice is None:
        return False
    current_hp = target.current_hit_points or 0
    return current_hp < target.max_hit_points


def get_threshold_alt_dice(action: Action) -> str | None:
    """Get the alternate damage dice when HP threshold is met."""
    return action.hp_threshold_alt_dice
