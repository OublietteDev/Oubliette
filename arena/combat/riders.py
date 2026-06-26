"""On-hit rider resolution — pure functions for discovering, calculating, and resolving riders.

Riders are triggered abilities that fire when an attack hits (Divine Smite,
Sneak Attack, Stunning Strike, etc.).  They live on Feature.on_hit_rider.

No GUI or CombatManager dependency — this module is purely functional.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arena.models.character import Creature, Feature, OnHitRider, RiderTrigger
from arena.models.actions import Action, DamageRoll
from arena.util.dice import roll_die, parse_dice_expression


# ── Result type ──────────────────────────────────────────────────────

@dataclass
class RiderResult:
    """The resolved outcome of applying one on-hit rider."""

    feature_name: str
    used: bool = False  # Player chose to use (or automatic fired)
    slot_level: int | None = None  # For spell-slot riders: which level was spent
    bonus_damage: list[DamageRoll] = field(default_factory=list)
    condition_to_apply: str | None = None  # Condition name if save failed
    condition_duration: str = "end_of_turn"
    condition_save_to_end: bool = True
    save_dc: int | None = None
    save_ability: str | None = None  # For the condition's save_to_end
    log_message: str | None = None  # Human-readable description


# ── Discovery ────────────────────────────────────────────────────────

def discover_riders(
    creature: Creature,
    action: Action,
    used_this_turn: set[str] | None = None,
) -> list[tuple[Feature, OnHitRider]]:
    """Find all on-hit riders applicable to the given attack.

    Args:
        creature: The attacking creature.
        action: The action being used (needed for attack_type context).
        used_this_turn: Set of feature names already used this turn
            (for once_per_turn filtering).

    Returns:
        List of (feature, rider) tuples for applicable riders.
    """
    if used_this_turn is None:
        used_this_turn = set()

    attack = action.attack
    if attack is None:
        return []

    is_melee = attack.attack_type.startswith("melee")
    is_weapon = attack.attack_type.endswith("weapon")

    features = getattr(creature, "features", []) or []
    # Monsters use special_abilities (also list[Feature])
    special = getattr(creature, "special_abilities", []) or []

    results: list[tuple[Feature, OnHitRider]] = []
    for feat in list(features) + list(special):
        rider = feat.on_hit_rider
        if rider is None:
            continue

        # Requirement checks
        if rider.requires_melee and not is_melee:
            continue
        if rider.requires_weapon and not is_weapon:
            continue

        # Once-per-turn check
        if rider.once_per_turn and feat.name in used_this_turn:
            continue

        # Resource availability check
        if rider.resource_type and rider.resource_cost > 0:
            if not _has_resource(creature, rider):
                continue

        results.append((feat, rider))

    return results


def _has_resource(creature: Creature, rider: OnHitRider) -> bool:
    """Check if the creature has enough resources to use this rider."""
    resources = getattr(creature, "class_resources", {})

    if rider.resource_type == "spell_slot":
        # Any spell slot level with remaining charges
        for key, count in resources.items():
            if key.startswith("spell_slot_") and count > 0:
                return True
        return False

    # Flat resource (ki_points, superiority_dice, etc.)
    return resources.get(rider.resource_type, 0) >= rider.resource_cost


# ── Damage calculation ───────────────────────────────────────────────

def calculate_rider_damage(
    rider: OnHitRider,
    slot_level: int | None = None,
) -> list[DamageRoll]:
    """Build the DamageRoll list for a rider activation.

    Args:
        rider: The rider configuration.
        slot_level: For spell-slot riders, the slot level spent.
            Determines scaling dice (e.g., Divine Smite adds 1d8 per level).

    Returns:
        List of DamageRoll (usually one element).
    """
    if rider.damage_dice is None:
        return []

    base_count, base_sides, base_bonus = parse_dice_expression(rider.damage_dice)

    total_dice = base_count

    # Add scaling dice for spell-slot riders
    if slot_level is not None and rider.damage_per_slot_level:
        scale_count, scale_sides, _ = parse_dice_expression(
            rider.damage_per_slot_level,
        )
        # For Divine Smite: damage_dice="2d8" is level-1 base,
        # damage_per_slot_level="1d8" adds 1d8 per level above 1st.
        # So at slot level N: total = base + (N - 1) * scale
        extra = (slot_level - 1) * scale_count
        total_dice += extra
        # scale_sides should match base_sides for this to make sense
        # but we use base_sides for the final expression

    # Apply dice cap
    if rider.max_dice is not None and total_dice > rider.max_dice:
        total_dice = rider.max_dice

    if total_dice <= 0 and base_bonus == 0:
        return []

    if total_dice > 0:
        dice_str = f"{total_dice}d{base_sides}"
        if base_bonus > 0:
            dice_str += f"+{base_bonus}"
        elif base_bonus < 0:
            dice_str += str(base_bonus)
    else:
        dice_str = str(base_bonus)

    return [DamageRoll(dice=dice_str, damage_type=rider.damage_type)]


# ── Save resolution ──────────────────────────────────────────────────

def calculate_rider_save_dc(
    rider: OnHitRider,
    attacker: Creature,
) -> int | None:
    """Calculate the save DC for a save-based rider.

    Returns None if the rider has no save component.
    """
    if rider.save_ability is None:
        return None

    # A stat-block fixed DC (Trampling Charge) wins over the computed one.
    if rider.save_dc_fixed is not None:
        return rider.save_dc_fixed

    if rider.save_dc_ability:
        # DC = 8 + proficiency + ability modifier
        mod = attacker.ability_scores.get_modifier(rider.save_dc_ability)
        return 8 + attacker.proficiency_bonus + mod

    # No DC ability specified — shouldn't happen for a save rider,
    # but fall back to a baseline
    return 8 + attacker.proficiency_bonus


def resolve_rider_save(
    rider: OnHitRider,
    attacker: Creature,
    target: Creature,
) -> tuple[bool, int]:
    """Roll the target's saving throw against a rider's save effect.

    Args:
        rider: The rider with save_ability and save_dc_ability set.
        attacker: The creature using the rider (for DC calculation).
        target: The creature making the save.

    Returns:
        (saved: bool, dc: int) — True if the target succeeded.
    """
    dc = calculate_rider_save_dc(rider, attacker) or 10

    save_mod = target.get_saving_throw_modifier(rider.save_ability or "constitution")
    roll = roll_die(20)
    total = roll + save_mod

    return total >= dc, dc


# ── Resource deduction ───────────────────────────────────────────────

def deduct_rider_resource(
    creature: Creature,
    rider: OnHitRider,
    slot_level: int | None = None,
) -> bool:
    """Deduct the resource cost for a rider activation.

    Args:
        creature: The attacking creature.
        rider: The rider configuration.
        slot_level: For spell-slot riders, which slot level to deduct.

    Returns:
        True if deduction succeeded, False if insufficient resources.
    """
    if rider.resource_type is None or rider.resource_cost <= 0:
        return True  # No cost

    resources = getattr(creature, "class_resources", {})

    if rider.resource_type == "spell_slot":
        if slot_level is None:
            return False
        key = f"spell_slot_{slot_level}"
        if resources.get(key, 0) < rider.resource_cost:
            return False
        resources[key] -= rider.resource_cost
        return True

    # Flat resource
    key = rider.resource_type
    if resources.get(key, 0) < rider.resource_cost:
        return False
    resources[key] -= rider.resource_cost
    return True


# ── Full resolution helper ───────────────────────────────────────────

def resolve_rider(
    feature: Feature,
    rider: OnHitRider,
    attacker: Creature,
    target: Creature,
    slot_level: int | None = None,
) -> RiderResult:
    """Fully resolve a rider activation: damage + save + resource deduction.

    This is a convenience function that chains calculate_rider_damage,
    resolve_rider_save, and deduct_rider_resource.

    Args:
        feature: The Feature owning this rider.
        rider: The rider configuration.
        attacker: The attacking creature.
        target: The target creature.
        slot_level: For spell-slot riders, the chosen slot level.

    Returns:
        RiderResult with all resolved effects.
    """
    result = RiderResult(feature_name=feature.name, used=True, slot_level=slot_level)

    # Deduct resource
    if not deduct_rider_resource(attacker, rider, slot_level):
        result.used = False
        result.log_message = f"{feature.name}: insufficient resources"
        return result

    # Calculate damage
    result.bonus_damage = calculate_rider_damage(rider, slot_level)

    # Resolve save if applicable
    if rider.save_ability and rider.condition_on_fail:
        saved, dc = resolve_rider_save(rider, attacker, target)
        result.save_dc = dc
        result.save_ability = rider.save_ability
        if not saved:
            result.condition_to_apply = rider.condition_on_fail
            result.condition_duration = rider.condition_duration
            result.condition_save_to_end = rider.condition_save_to_end
            result.log_message = (
                f"{feature.name}: {target.name} failed "
                f"{rider.save_ability.upper()} save (DC {dc}) — "
                f"{rider.condition_on_fail}!"
            )
        else:
            result.log_message = (
                f"{feature.name}: {target.name} passed "
                f"{rider.save_ability.upper()} save (DC {dc})"
            )
    else:
        # Damage-only rider
        if result.bonus_damage:
            dmg = result.bonus_damage[0]
            result.log_message = (
                f"{feature.name}: {dmg.dice} {dmg.damage_type} damage"
            )

    return result


# ── Spell slot helpers ───────────────────────────────────────────────

def get_available_spell_slots(creature: Creature) -> dict[int, int]:
    """Build a {level: remaining_count} dict from class_resources.

    Only includes levels 1-9 with remaining count > 0 or == 0
    (so the UI can show exhausted slots grayed out).
    """
    resources = getattr(creature, "class_resources", {})
    slots: dict[int, int] = {}
    for key, count in resources.items():
        if key.startswith("spell_slot_"):
            try:
                level = int(key.split("_")[-1])
                if 1 <= level <= 9:
                    slots[level] = count
            except ValueError:
                continue
    return dict(sorted(slots.items()))


def get_rider_dice_preview(
    rider: OnHitRider,
    slot_level: int,
) -> str:
    """Get a human-readable dice string for a spell-slot rider at a given level.

    E.g., "3d8 radiant" for Divine Smite at 2nd level.
    """
    damage_rolls = calculate_rider_damage(rider, slot_level)
    if not damage_rolls:
        return "no damage"
    d = damage_rolls[0]
    dtype = d.damage_type.value if hasattr(d.damage_type, "value") else d.damage_type
    return f"{d.dice} {dtype}"


# ── Presets ──────────────────────────────────────────────────────────

RIDER_PRESETS: dict[str, dict] = {
    "divine_smite": {
        "trigger": "post_hit",
        "resource_type": "spell_slot",
        "resource_cost": 1,
        "damage_dice": "2d8",
        "damage_type": "radiant",
        "damage_per_slot_level": "1d8",
        "max_dice": 5,
        "requires_melee": True,
        "requires_weapon": True,
    },
    "sneak_attack": {
        "trigger": "automatic",
        "once_per_turn": True,
        "damage_dice": "1d6",
        "damage_type": "piercing",
    },
    "stunning_strike": {
        "trigger": "post_hit",
        "resource_type": "ki_points",
        "resource_cost": 1,
        "save_ability": "constitution",
        "save_dc_ability": "wisdom",
        "condition_on_fail": "stunned",
        "condition_duration": "end_of_turn",
        "condition_save_to_end": False,
        "requires_melee": True,
    },
    "eldritch_smite": {
        "trigger": "post_hit",
        "resource_type": "spell_slot",
        "resource_cost": 1,
        "damage_dice": "1d8",
        "damage_type": "force",
        "damage_per_slot_level": "1d8",
        "max_dice": 6,
        "requires_weapon": True,
    },
    "hex_damage": {
        "trigger": "automatic",
        "once_per_turn": False,
        "damage_dice": "1d6",
        "damage_type": "necrotic",
    },
}
