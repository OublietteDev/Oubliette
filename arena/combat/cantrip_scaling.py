"""Cantrip damage scaling by character level.

Pure functions for computing cantrip scale factors and scaling dice
expressions.  No CombatManager or Pygame dependency.
"""

from __future__ import annotations

from arena.models.character import Creature, PlayerCharacter
from arena.util.dice import parse_dice_expression


def get_cantrip_scale_factor(caster_level: int) -> int:
    """Return how many times to multiply the base cantrip dice.

    Level 1-4: 1x (base), Level 5-10: 2x, Level 11-16: 3x, Level 17+: 4x.
    """
    if caster_level >= 17:
        return 4
    elif caster_level >= 11:
        return 3
    elif caster_level >= 5:
        return 2
    return 1


def scale_cantrip_damage(base_dice: str, caster_level: int) -> str:
    """Scale a cantrip damage dice expression by caster level.

    Example: scale_cantrip_damage("1d10", 5) -> "2d10"
             scale_cantrip_damage("2d6", 11) -> "6d6" (base is 2 dice)

    Args:
        base_dice: The base dice expression (e.g., "1d10", "1d8")
        caster_level: The caster's total character level

    Returns:
        Scaled dice expression string.
    """
    factor = get_cantrip_scale_factor(caster_level)
    count, sides, modifier = parse_dice_expression(base_dice)

    if count == 0 or sides == 0:
        # Flat number or unparseable — return as-is
        return base_dice

    scaled_count = count * factor
    expr = f"{scaled_count}d{sides}"
    if modifier > 0:
        expr += f"+{modifier}"
    elif modifier < 0:
        expr += str(modifier)
    return expr


def get_cantrip_extra_beam_count(caster_level: int) -> int:
    """For Eldritch Blast-style cantrips, get total beam count.

    Level 1-4: 1, Level 5-10: 2, Level 11-16: 3, Level 17+: 4.
    """
    return get_cantrip_scale_factor(caster_level)


def estimate_level_from_proficiency(prof_bonus: int) -> int:
    """Estimate character level from proficiency bonus.

    Prof 2 → level 1, Prof 3 → level 5, Prof 4 → level 9, etc.
    """
    return max(1, (prof_bonus - 2) * 4 + 1)


def get_caster_level(creature: Creature) -> int:
    """Get the effective caster level for cantrip scaling.

    Uses PlayerCharacter.total_level if available, otherwise estimates
    from proficiency bonus.
    """
    if isinstance(creature, PlayerCharacter):
        return creature.total_level
    return estimate_level_from_proficiency(creature.proficiency_bonus)
