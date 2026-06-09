"""Pure functions for upcast scaling calculations.

Handles spell slot level detection, bonus damage/healing computation,
and resource cost adjustment when spells are cast at higher levels.

No CombatManager or Pygame dependency.
"""

from __future__ import annotations

from arena.models.actions import Action, DamageRoll, DamageType
from arena.models.character import Creature
from arena.util.dice import parse_dice_expression


def get_spell_level(action: Action) -> int | None:
    """Get the base spell level for an action.

    Checks action.spell_level first, then falls back to parsing resource_cost
    keys (e.g., "spell_slot_3" → 3) for backward compatibility.

    Returns None if the action is not a spell.
    """
    if action.spell_level is not None:
        return action.spell_level

    for key in action.resource_cost:
        if key.startswith("spell_slot_"):
            try:
                return int(key.split("_")[-1])
            except ValueError:
                pass
    return None


def can_upcast(action: Action) -> bool:
    """Check if an action supports upcasting.

    An action can be upcast if it has a spell level and at least one
    upcast scaling field is set.
    """
    base = get_spell_level(action)
    if base is None:
        return False
    return bool(action.upcast_damage_dice or action.upcast_healing_dice)


def get_available_upcast_levels(action: Action, creature: Creature) -> list[int]:
    """Get all slot levels available for casting this spell.

    Returns a sorted list of slot levels >= base that have remaining slots.
    """
    base = get_spell_level(action)
    if base is None:
        return []

    resources = getattr(creature, "class_resources", {})
    levels = []
    for key, count in resources.items():
        if key.startswith("spell_slot_") and count > 0:
            try:
                level = int(key.split("_")[-1])
                if level >= base:
                    levels.append(level)
            except ValueError:
                pass
    return sorted(levels)


def get_max_upcast_level(action: Action, creature: Creature) -> int:
    """Get the highest slot level available for upcasting this spell.

    Returns the base spell level if no higher slots are available,
    or 0 if the action is not a spell.
    """
    base = get_spell_level(action)
    if base is None:
        return 0

    levels = get_available_upcast_levels(action, creature)
    return levels[-1] if levels else base


def calculate_upcast_bonus_damage(
    action: Action,
    cast_level: int,
) -> list[DamageRoll]:
    """Calculate bonus damage dice from upcasting.

    Returns a list of DamageRoll for the bonus (empty if no upcast or no scaling).
    Respects upcast_damage_per_levels for per-2-level scaling (Spiritual Weapon).
    """
    base = get_spell_level(action)
    if base is None or cast_level <= base:
        return []
    if not action.upcast_damage_dice:
        return []

    levels_above = cast_level - base
    step = action.upcast_damage_per_levels
    scaling_steps = levels_above // step

    if scaling_steps <= 0:
        return []

    count, sides, bonus = parse_dice_expression(action.upcast_damage_dice)
    total_dice = count * scaling_steps

    if total_dice <= 0 and bonus == 0:
        return []

    damage_type = _get_primary_damage_type(action)

    return [DamageRoll(
        dice=f"{total_dice}d{sides}" if total_dice > 0 else "0d0",
        damage_type=damage_type,
        bonus=bonus * scaling_steps,
    )]


def calculate_upcast_bonus_healing(
    action: Action,
    cast_level: int,
) -> str | None:
    """Calculate the bonus healing expression from upcasting.

    Returns a dice expression string like "2d8" for the bonus, or None.
    """
    base = get_spell_level(action)
    if base is None or cast_level <= base:
        return None
    if not action.upcast_healing_dice:
        return None

    levels_above = cast_level - base
    step = action.upcast_damage_per_levels  # Reuse for healing scaling interval
    scaling_steps = levels_above // step

    if scaling_steps <= 0:
        return None

    count, sides, bonus = parse_dice_expression(action.upcast_healing_dice)
    total_dice = count * scaling_steps

    if total_dice <= 0 and bonus == 0:
        return None

    expr = f"{total_dice}d{sides}" if total_dice > 0 else ""
    total_bonus = bonus * scaling_steps
    if total_bonus > 0:
        expr += f"+{total_bonus}" if expr else str(total_bonus)
    elif total_bonus < 0:
        expr += str(total_bonus)

    return expr if expr else None


def calculate_upcast_zone_dice(
    action: Action,
    cast_level: int,
) -> str | None:
    """Calculate the augmented zone damage dice for an upcast zone spell.

    Combines the base zone damage with upcast bonus into a single dice string.
    Returns None if no upcasting applies.

    Example: Spirit Guardians base "3d8" + 2 levels of "1d8" → "5d8"
    """
    base = get_spell_level(action)
    if base is None or cast_level <= base:
        return None
    if not action.upcast_damage_dice:
        return None
    if not action.saving_throw or not action.saving_throw.damage_on_fail:
        return None

    # Parse base zone damage
    base_dice_str = action.saving_throw.damage_on_fail[0].dice
    base_count, base_sides, base_bonus = parse_dice_expression(base_dice_str)

    # Parse upcast bonus
    levels_above = cast_level - base
    step = action.upcast_damage_per_levels
    scaling_steps = levels_above // step

    if scaling_steps <= 0:
        return None

    up_count, up_sides, up_bonus = parse_dice_expression(action.upcast_damage_dice)

    # Combine (assume same die size for zone spells)
    total_count = base_count + (up_count * scaling_steps)
    total_bonus = base_bonus + (up_bonus * scaling_steps)

    expr = f"{total_count}d{base_sides}"
    if total_bonus > 0:
        expr += f"+{total_bonus}"
    elif total_bonus < 0:
        expr += str(total_bonus)

    return expr


def make_upcast_resource_cost(action: Action, cast_level: int) -> dict[str, int]:
    """Build the resource_cost dict for an upcast spell.

    Replaces spell_slot_N with spell_slot_{cast_level}.
    Non-spell-slot costs are preserved unchanged.
    """
    base = get_spell_level(action)
    if base is None or cast_level == base:
        return dict(action.resource_cost)

    new_cost: dict[str, int] = {}
    for key, value in action.resource_cost.items():
        if key.startswith("spell_slot_"):
            new_cost[f"spell_slot_{cast_level}"] = value
        else:
            new_cost[key] = value
    return new_cost


def _get_primary_damage_type(action: Action) -> DamageType:
    """Extract the primary damage type from an action's base damage."""
    if action.attack and action.attack.damage:
        return action.attack.damage[0].damage_type
    if action.saving_throw and action.saving_throw.damage_on_fail:
        return action.saving_throw.damage_on_fail[0].damage_type
    return DamageType.FORCE  # fallback
