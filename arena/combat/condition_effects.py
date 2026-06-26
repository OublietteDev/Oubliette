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


def _has_blood_frenzy(creature: Creature) -> bool:
    """Whether the creature has the Blood Frenzy trait (D-MON)."""
    feats = list(getattr(creature, "special_abilities", []) or [])
    feats += list(getattr(creature, "features", []) or [])
    return any(getattr(f, "attack_advantage_vs_damaged", False) for f in feats)


def _is_damaged(creature: Creature) -> bool:
    """Whether the creature is below its hit-point maximum (Blood Frenzy)."""
    cur = creature.current_hit_points
    mx = creature.max_hit_points
    # current_hit_points is None when the creature is at full (un-instantiated).
    if cur is None or mx is None:
        return False
    return cur < mx


# ── Attack Advantage/Disadvantage ────────────────────────────────────

def get_attack_advantage(
    attacker: Creature,
    target: Creature,
    is_melee: bool = True,
    attacker_sees_target: bool = True,
    target_sees_attacker: bool = True,
    attacker_can_see_invisible: bool = False,
    target_can_see_invisible: bool = False,
) -> int:
    """Calculate net advantage/disadvantage for an attack roll.

    Per 5e: if ANY source of advantage and ANY source of disadvantage
    both exist, they fully cancel regardless of counts. Otherwise,
    any advantage sources → advantage, any disadvantage → disadvantage.

    Args:
        attacker: The creature making the attack.
        target: The creature being attacked.
        is_melee: True for melee attacks, False for ranged.
        attacker_sees_target: False if the attacker cannot see the target
            (e.g. target hidden in fog/darkness) → disadvantage on the attack.
        target_sees_attacker: False if the target cannot see the attacker
            (e.g. attacker striking from concealment) → advantage on the attack.
            The combat manager computes both via grid.vision.can_see; defaults
            keep this a pure condition query when no spatial context is supplied.

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

    # Attacker is invisible: has advantage (unless the target sees invisible)
    if _has(attacker, Condition.INVISIBLE) and not target_can_see_invisible:
        has_adv = True

    # Attacker is hidden (unseen + unheard): attacking from hiding has
    # advantage. The attack then reveals the attacker (handled by the caller,
    # which clears HIDDEN after the advantage is locked in).
    if _has(attacker, Condition.HIDDEN):
        has_adv = True

    # Target cannot see the attacker (concealment/obscurement): unseen
    # attacker strikes with advantage.
    if not target_sees_attacker:
        has_adv = True

    # Reckless Attack (D-MON): the attacker chose to attack recklessly this
    # turn — advantage on its own melee weapon attacks.
    if _has(attacker, Condition.RECKLESS) and is_melee:
        has_adv = True

    # Reckless Attack (D-MON), the downside: attack rolls against a creature
    # that attacked recklessly have advantage until the start of its next turn
    # (any attack — melee or ranged).
    if _has(target, Condition.RECKLESS):
        has_adv = True

    # Blood Frenzy (D-MON): advantage on melee attacks against a target that
    # doesn't have all its hit points.
    if is_melee and _has_blood_frenzy(attacker) and _is_damaged(target):
        has_adv = True

    # ── Sources of DISADVANTAGE ──

    # Attacker cannot see the target (target in fog/darkness): attacking a
    # target you can't see is at disadvantage.
    if not attacker_sees_target:
        has_dis = True

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

    # Target is invisible: attacker has disadvantage (unless attacker sees invisible)
    if _has(target, Condition.INVISIBLE) and not attacker_can_see_invisible:
        has_dis = True

    # Target is hidden (unseen): attacking what you can't see is at disadvantage.
    if _has(target, Condition.HIDDEN):
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


def get_trait_save_advantage(
    creature: Creature,
    is_spell_save: bool = False,
    imposes_conditions: list[str] | None = None,
) -> tuple[int, str | None]:
    """Advantage on a saving throw from a monster trait (D-MON-4a).

    - Magic Resistance (``save_advantage_vs_spells``): advantage on saves
      against spells.
    - Brave / Dark Devotion (``save_advantage_vs_conditions=['frightened']``)
      and Fey Ancestry (``['charmed']``): advantage on a save that would
      impose one of those conditions.

    These traits only ever grant advantage (never disadvantage). Returns
    ``(advantage, trait_label)`` where advantage is 0 or 1 and trait_label
    names the trait for the combat log (or None).
    """
    imposed = {c.lower() for c in (imposes_conditions or [])}
    feats = list(getattr(creature, "special_abilities", []) or [])
    feats += list(getattr(creature, "features", []) or [])
    for feat in feats:
        if is_spell_save and getattr(feat, "save_advantage_vs_spells", False):
            return 1, getattr(feat, "name", None) or "Magic Resistance"
        vs = getattr(feat, "save_advantage_vs_conditions", None) or []
        if imposed and {c.lower() for c in vs} & imposed:
            return 1, getattr(feat, "name", None)
    return 0, None


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
        1.0 if normal movement

    Note: prone does NOT halve the budget here. Crawling's "costs double"
    penalty lives in ``get_movement_cost_multiplier`` (a per-hex cost
    doubling) so that it composes correctly with standing up — a creature
    that spends half its speed to stand then moves the rest at full cost.
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

    return 1.0


def get_movement_cost_multiplier(creature: Creature) -> int:
    """Get the per-hex movement cost multiplier based on conditions.

    A prone creature that crawls spends 1 extra foot for every foot of
    movement (5e RAW) — i.e. each hex costs double. Returns 2 while prone,
    1 otherwise. Standing up (which clears prone) resets this to 1 so the
    rest of the turn's movement is at normal cost.
    """
    if _has(creature, Condition.PRONE):
        return 2
    return 1


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
