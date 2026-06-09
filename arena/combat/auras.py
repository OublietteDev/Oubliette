"""Aura effect queries -- passive proximity-based buffs for allies.

Paladin's Aura of Protection, Aura of Courage, etc.

Pure-function module: no state mutation.

Note: Callers should check get_aura_condition_immunities() before applying
conditions to creatures near aura sources.
"""

from arena.models.character import Creature, Feature
from arena.combat.stat_modifiers import get_effective_ability_modifier


def _get_aura_features(creature: Creature) -> list[Feature]:
    """Get all features with active auras from a creature."""
    if not hasattr(creature, "features"):
        return []
    return [f for f in creature.features if f.aura_range > 0]


def get_aura_save_bonus(
    creature: Creature,
    creature_id: str,
    combatants: dict,
    positions: dict,
    ability: str,
) -> int:
    """Get total saving throw bonus from nearby allies' auras.

    Checks all combatants for aura features that grant save bonuses,
    and returns the total bonus if the creature is within range.

    Args:
        creature: The creature making the save.
        creature_id: ID of the creature making the save.
        combatants: Dict of {id: Creature} for all combatants.
        positions: Dict of {id: HexCoord} for all positions.
        ability: The saving throw ability (unused currently, auras apply to all).

    Returns:
        Total flat bonus to the saving throw from auras.
    """
    if creature_id not in positions:
        return 0

    creature_pos = positions[creature_id]
    total_bonus = 0

    for ally_id, ally in combatants.items():
        if ally_id not in positions:
            continue

        # Check if this ally is friendly (same is_player_controlled status)
        # A creature benefits from its own aura, so we don't skip ally_id == creature_id
        if ally.is_player_controlled != creature.is_player_controlled:
            continue

        ally_pos = positions[ally_id]

        for feature in _get_aura_features(ally):
            if not feature.aura_save_bonus_ability:
                continue

            # Check consciousness requirement
            if feature.aura_requires_conscious and not ally.is_conscious:
                continue

            # Check range (hex distance * 5 = feet)
            distance_feet = creature_pos.distance_to(ally_pos) * 5
            if distance_feet > feature.aura_range:
                continue

            # Add the ability modifier as a bonus
            bonus = get_effective_ability_modifier(
                ally, feature.aura_save_bonus_ability
            )
            total_bonus += max(0, bonus)  # Minimum 0 (negative CHA doesn't penalize)

    return total_bonus


def get_aura_condition_immunities(
    creature: Creature,
    creature_id: str,
    combatants: dict,
    positions: dict,
) -> list[str]:
    """Get condition immunities granted by nearby allies' auras.

    Returns list of condition names the creature is immune to due to auras.
    """
    if creature_id not in positions:
        return []

    creature_pos = positions[creature_id]
    immunities: set[str] = set()

    for ally_id, ally in combatants.items():
        if ally_id not in positions:
            continue

        if ally.is_player_controlled != creature.is_player_controlled:
            continue

        ally_pos = positions[ally_id]

        for feature in _get_aura_features(ally):
            if not feature.aura_condition_immunity:
                continue

            if feature.aura_requires_conscious and not ally.is_conscious:
                continue

            distance_feet = creature_pos.distance_to(ally_pos) * 5
            if distance_feet > feature.aura_range:
                continue

            immunities.update(feature.aura_condition_immunity)

    return list(immunities)
