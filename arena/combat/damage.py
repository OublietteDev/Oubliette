"""Damage calculation and application."""

from arena.models.character import Creature
from arena.models.actions import DamageRoll
from arena.util.dice import roll_expression
from arena.combat.events import CombatEvent, CombatEventType
from arena.combat.stat_modifiers import (
    get_effective_ability_modifier,
    get_effective_damage_immunities,
    get_effective_damage_resistances,
)
from arena.combat.death_prevention import (
    get_death_prevention_features,
    can_use_death_prevention,
    resolve_death_prevention,
)


def roll_damage(
    damage_rolls: list[DamageRoll],
    attacker: Creature,
    is_critical: bool = False,
) -> tuple[int, list[dict]]:
    """Roll damage for an attack.

    Args:
        damage_rolls: List of DamageRoll from the Attack model.
        attacker: The attacking creature (for ability modifiers).
        is_critical: If True, double the dice (not the modifier).

    Returns:
        (total_damage, details_list) where details_list has per-roll breakdown.
    """
    total = 0
    details = []

    for dr in damage_rolls:
        # Roll the dice
        dice_total, dice_list = roll_expression(dr.dice)

        # Critical hit: roll dice again and add
        if is_critical:
            crit_total, crit_list = roll_expression(dr.dice)
            dice_total += crit_total
            dice_list = dice_list + crit_list

        # Add flat bonus from the DamageRoll
        bonus = dr.bonus

        # Add ability modifier if specified
        ability_bonus = 0
        if dr.ability_modifier:
            ability_bonus = get_effective_ability_modifier(attacker, dr.ability_modifier)

        subtotal = dice_total + bonus + ability_bonus
        total += subtotal

        details.append(
            {
                "dice": dr.dice,
                "rolls": dice_list,
                "bonus": bonus,
                "ability_bonus": ability_bonus,
                "damage_type": dr.damage_type.value,
                "subtotal": subtotal,
            }
        )

    return max(0, total), details


def _apply_damage_modifiers(
    target: Creature, damage: int, damage_type: str
) -> tuple[int, str]:
    """Apply resistance, immunity, and vulnerability to damage.

    Processing order per 5e rules:
    1. Immunity (negates all damage of that type)
    2. Resistance (halves damage)
    3. Vulnerability (doubles damage)

    If a creature has both resistance and vulnerability to the same type,
    they cancel out (apply neither).

    Args:
        target: The creature taking damage.
        damage: Raw damage amount.
        damage_type: The damage type string (e.g., "fire", "slashing").

    Returns:
        (modified_damage, modifier_text) for logging.
    """
    dtype = damage_type.lower()
    is_immune = dtype in [d.lower() for d in get_effective_damage_immunities(target)]
    is_resistant = dtype in [d.lower() for d in get_effective_damage_resistances(target)]
    is_vulnerable = dtype in [d.lower() for d in target.damage_vulnerabilities]

    if is_immune:
        return 0, " [IMMUNE]"

    # Resistance and vulnerability cancel each other
    if is_resistant and is_vulnerable:
        return damage, ""

    if is_resistant:
        return damage // 2, " [RESISTANT - halved]"

    if is_vulnerable:
        return damage * 2, " [VULNERABLE - doubled]"

    return damage, ""


def apply_damage(
    target: Creature,
    damage: int,
    damage_type: str,
    creature_id: str = "",
) -> tuple[CombatEvent, list[CombatEvent]]:
    """Apply damage to a creature, accounting for defenses and temp HP.

    Processing order:
    1. Apply resistance/immunity/vulnerability modifiers.
    2. Subtract from temporary hit points first.
    3. Remainder subtracts from current hit points (minimum 0).
    4. If creature just dropped to 0 HP, check death prevention features.

    Args:
        target: The creature taking damage.
        damage: Amount of damage to apply.
        damage_type: Type of damage (e.g., "slashing", "fire").
        creature_id: ID of the creature taking damage (for death prevention events).

    Returns:
        A tuple of (damage_event, extra_events) where extra_events contains
        any death prevention events that fired.
    """
    extra_events: list[CombatEvent] = []

    # Apply resistance/immunity/vulnerability
    modified_damage, modifier_text = _apply_damage_modifiers(
        target, damage, damage_type
    )

    old_hp = target.current_hit_points if target.current_hit_points is not None else 0
    old_temp = target.temporary_hit_points

    # Absorb damage with temp HP first
    temp_absorbed = 0
    remaining_damage = modified_damage
    if target.temporary_hit_points > 0 and remaining_damage > 0:
        temp_absorbed = min(target.temporary_hit_points, remaining_damage)
        target.temporary_hit_points -= temp_absorbed
        remaining_damage -= temp_absorbed

    # Apply remaining to real HP
    new_hp = max(0, old_hp - remaining_damage)
    target.current_hit_points = new_hp

    was_conscious = old_hp > 0
    is_now_unconscious = new_hp <= 0
    death_prevented = False

    # Death prevention check: creature just dropped to 0 HP
    if was_conscious and is_now_unconscious:
        dp_features = get_death_prevention_features(target)
        for feature in dp_features:
            if not can_use_death_prevention(target, feature):
                continue
            # Calculate use_count for escalating DC features:
            # For resource-based features, count uses as (initial - current)
            # For non-resource features (Relentless Rage), use
            # death_prevention_use_count tracked on the creature.
            use_count = getattr(target, '_death_prevention_use_count', {}).get(
                feature.name, 0
            )
            success, dp_events = resolve_death_prevention(
                target, creature_id, feature, use_count=use_count
            )
            extra_events.extend(dp_events)
            # Track use count (increment regardless of success for escalating DC)
            if not hasattr(target, '_death_prevention_use_count'):
                target._death_prevention_use_count = {}
            target._death_prevention_use_count[feature.name] = use_count + 1
            if success:
                # Death was prevented -- update state
                new_hp = target.current_hit_points  # resolve set it to 1
                is_now_unconscious = False
                death_prevented = True
                break  # Only need one successful prevention

    # Build message
    msg = f"takes {modified_damage} {damage_type} damage{modifier_text}"
    if temp_absorbed > 0:
        msg += f" ({temp_absorbed} absorbed by temp HP)"
    msg += f" ({new_hp}/{target.max_hit_points} HP)"
    if is_now_unconscious and was_conscious:
        msg += " and falls unconscious!"

    dmg_event = CombatEvent(
        event_type=CombatEventType.DAMAGE,
        message=msg,
        details={
            "damage": modified_damage,
            "raw_damage": damage,
            "damage_type": damage_type,
            "old_hp": old_hp,
            "new_hp": new_hp,
            "temp_absorbed": temp_absorbed,
            "knocked_out": is_now_unconscious and was_conscious,
            "death_prevented": death_prevented,
            "modifier_text": modifier_text,
        },
    )
    return dmg_event, extra_events


def apply_healing(target: Creature, amount: int) -> CombatEvent:
    """Heal a creature. HP cannot exceed max.

    If the creature is at 0 HP (unconscious), healing brings them back.

    Args:
        target: The creature to heal.
        amount: Amount of HP to restore.

    Returns:
        A CombatEvent describing the healing.
    """
    old_hp = target.current_hit_points if target.current_hit_points is not None else 0
    new_hp = min(target.max_hit_points, old_hp + amount)
    target.current_hit_points = new_hp

    was_unconscious = old_hp <= 0
    healed_amount = new_hp - old_hp

    msg = f"heals for {healed_amount} HP ({new_hp}/{target.max_hit_points} HP)"
    if was_unconscious and new_hp > 0:
        msg += " and regains consciousness!"

    return CombatEvent(
        event_type=CombatEventType.HEALING,
        message=msg,
        details={
            "healing": healed_amount,
            "old_hp": old_hp,
            "new_hp": new_hp,
            "regained_consciousness": was_unconscious and new_hp > 0,
        },
    )
