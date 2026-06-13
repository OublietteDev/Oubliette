"""Pure query functions for how conditions affect combat mechanics.

This module never mutates state — it only answers questions like
"does this creature have advantage on this attack?" based on the
active conditions of the attacker and/or target.
"""

from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.combat.buff_effects import get_buff_attack_advantage, get_buff_save_advantage


def _has(creature: Creature, condition: Condition) -> bool:
    """Check if a creature has a specific condition."""
    return any(ac.condition == condition for ac in creature.active_conditions)


# ── Attack Advantage/Disadvantage ────────────────────────────────────

def get_attack_advantage(
    attacker: Creature,
    target: Creature,
    is_melee: bool = True,
) -> int:
    """Calculate net advantage/disadvantage for an attack roll.

    Per 5e: if ANY source of advantage and ANY source of disadvantage
    both exist, they fully cancel regardless of counts. Otherwise,
    any advantage sources → advantage, any disadvantage → disadvantage.

    Args:
        attacker: The creature making the attack.
        target: The creature being attacked.
        is_melee: True for melee attacks, False for ranged.

    Returns:
        > 0 for advantage, < 0 for disadvantage, 0 for straight roll.
    """
    has_adv = False
    has_dis = False

    # ── Sources of ADVANTAGE ──

    # Target is blinded: attacker has advantage
    if _has(target, Condition.BLINDED):
        has_adv = True

    # Target is paralyzed: attacks have advantage
    if _has(target, Condition.PARALYZED):
        has_adv = True

    # Target is stunned: attacks have advantage
    if _has(target, Condition.STUNNED):
        has_adv = True

    # Target is unconscious: attacks have advantage
    if _has(target, Condition.UNCONSCIOUS):
        has_adv = True

    # Target is restrained: attacks have advantage
    if _has(target, Condition.RESTRAINED):
        has_adv = True

    # Target is prone: melee within 5ft has advantage
    if _has(target, Condition.PRONE) and is_melee:
        has_adv = True

    # Attacker has HELPED pseudo-condition: advantage on next attack
    if _has(attacker, Condition.HELPED):
        has_adv = True

    # Attacker is invisible: has advantage
    if _has(attacker, Condition.INVISIBLE):
        has_adv = True

    # ── Sources of DISADVANTAGE ──

    # Attacker is blinded: has disadvantage
    if _has(attacker, Condition.BLINDED):
        has_dis = True

    # Attacker is frightened (of target): disadvantage while source visible
    if _has(attacker, Condition.FRIGHTENED):
        has_dis = True

    # Attacker is poisoned: disadvantage on attack rolls
    if _has(attacker, Condition.POISONED):
        has_dis = True

    # Attacker is restrained: disadvantage on attack rolls
    if _has(attacker, Condition.RESTRAINED):
        has_dis = True

    # Attacker is prone: disadvantage on attack rolls
    if _has(attacker, Condition.PRONE):
        has_dis = True

    # Target is dodging: attackers have disadvantage
    if _has(target, Condition.DODGING):
        has_dis = True

    # Target is invisible: attacker has disadvantage
    if _has(target, Condition.INVISIBLE):
        has_dis = True

    # Target is prone but ranged: disadvantage
    if _has(target, Condition.PRONE) and not is_melee:
        has_dis = True

    # Active buffs/debuffs (Faerie Fire on target, etc.)
    buff_adv = get_buff_attack_advantage(attacker, target)
    if buff_adv > 0:
        has_adv = True
    elif buff_adv < 0:
        has_dis = True

    # Cancel rule: any advantage + any disadvantage = normal
    if has_adv and has_dis:
        return 0
    elif has_adv:
        return 1
    elif has_dis:
        return -1
    return 0


# ── Saving Throw Modifiers ──────────────────────────────────────────

def get_save_advantage(creature: Creature, ability: str) -> int:
    """Calculate advantage/disadvantage on saving throws from conditions.

    Returns > 0 for advantage, < 0 for disadvantage, 0 for normal.
    """
    has_adv = False
    has_dis = False

    # Restrained: disadvantage on DEX saves
    if _has(creature, Condition.RESTRAINED) and ability.lower() == "dexterity":
        has_dis = True

    # Dodging: advantage on DEX saves
    if _has(creature, Condition.DODGING) and ability.lower() == "dexterity":
        has_adv = True

    # Active buffs/debuffs (Haste DEX save advantage, etc.)
    buff_adv = get_buff_save_advantage(creature, ability)
    if buff_adv > 0:
        has_adv = True
    elif buff_adv < 0:
        has_dis = True

    if has_adv and has_dis:
        return 0
    elif has_adv:
        return 1
    elif has_dis:
        return -1
    return 0


def is_auto_fail_save(creature: Creature, ability: str) -> bool:
    """Check if a creature auto-fails a saving throw due to conditions.

    Stunned and paralyzed creatures auto-fail STR and DEX saves.
    """
    ability_lower = ability.lower()
    if ability_lower in ("strength", "dexterity"):
        if _has(creature, Condition.STUNNED):
            return True
        if _has(creature, Condition.PARALYZED):
            return True
    return False


# ── Action Capability ────────────────────────────────────────────────

def can_take_actions(creature: Creature) -> bool:
    """Check if a creature can take actions, bonus actions, and reactions.

    Returns False if the creature is incapacitated by any condition.
    """
    incapacitating = (
        Condition.INCAPACITATED,
        Condition.STUNNED,
        Condition.PARALYZED,
        Condition.PETRIFIED,
        Condition.UNCONSCIOUS,
        # Banished creatures are not on this plane: no actions, no
        # reactions, no legendary actions until they return.
        Condition.BANISHED,
    )
    return not any(_has(creature, c) for c in incapacitating)


# ── Movement ─────────────────────────────────────────────────────────

def get_movement_multiplier(creature: Creature) -> float:
    """Get the movement speed multiplier based on conditions.

    Returns:
        0.0 if speed is reduced to 0 (grappled, restrained, etc.)
        0.5 if speed is halved (prone - costs double to move)
        1.0 if normal movement
    """
    # Speed = 0
    if _has(creature, Condition.GRAPPLED):
        return 0.0
    if _has(creature, Condition.RESTRAINED):
        return 0.0
    if _has(creature, Condition.STUNNED):
        return 0.0
    if _has(creature, Condition.PARALYZED):
        return 0.0
    if _has(creature, Condition.PETRIFIED):
        return 0.0
    if _has(creature, Condition.UNCONSCIOUS):
        return 0.0

    # Half speed (prone costs extra movement to move)
    if _has(creature, Condition.PRONE):
        return 0.5

    return 1.0


# ── Auto-Critical Hits ──────────────────────────────────────────────

def is_auto_crit(target: Creature, is_melee: bool = True) -> bool:
    """Check if hits against the target are automatic critical hits.

    Per 5e: attacks within 5 feet of a paralyzed or unconscious
    creature that hit are automatically critical hits.
    Only applies to melee (within 5 feet).
    """
    if not is_melee:
        return False
    if _has(target, Condition.PARALYZED):
        return True
    if _has(target, Condition.UNCONSCIOUS):
        return True
    return False
