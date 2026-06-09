"""Damage reduction reaction queries and calculations.

Parry (Battlemaster), Uncanny Dodge (Rogue), Deflect Missiles (Monk).
These are reaction-based features that reduce incoming damage.
"""

from arena.models.character import Creature, Feature
from arena.combat.stat_modifiers import get_effective_ability_modifier
from arena.util.dice import roll_expression


def get_damage_reduction_features(creature: Creature) -> list[Feature]:
    """Get all features that can reduce incoming damage as a reaction."""
    if not hasattr(creature, 'features'):
        return []
    return [
        f for f in creature.features
        if f.damage_reduction_dice or f.damage_reduction_flat_half
    ]


def can_use_damage_reduction(
    feature: Feature,
    is_melee: bool = True,
    is_ranged: bool = False,
) -> bool:
    """Check if a damage reduction feature applies to this attack type."""
    if feature.damage_reduction_type == "melee_only" and not is_melee:
        return False
    if feature.damage_reduction_type == "ranged_only" and not is_ranged:
        return False
    return True


def calculate_damage_reduction(
    creature: Creature,
    feature: Feature,
) -> int:
    """Calculate the damage reduction amount from a feature.

    For Uncanny Dodge (flat_half), returns -1 as a sentinel to indicate halving.
    For Parry/Deflect Missiles, rolls dice + adds ability modifier.
    """
    if feature.damage_reduction_flat_half:
        return -1  # Sentinel: caller should halve damage

    total = 0
    if feature.damage_reduction_dice:
        dice_total, _rolls = roll_expression(feature.damage_reduction_dice)
        total += dice_total

    if feature.damage_reduction_bonus:
        ability_mod = get_effective_ability_modifier(creature, feature.damage_reduction_bonus)
        total += ability_mod

    return max(0, total)


def apply_damage_reduction(damage: int, reduction: int) -> int:
    """Apply damage reduction to incoming damage.

    Args:
        damage: The incoming damage amount.
        reduction: The reduction amount. -1 means halve damage (Uncanny Dodge).

    Returns:
        The reduced damage (minimum 0).
    """
    if reduction == -1:
        return damage // 2
    return max(0, damage - reduction)
