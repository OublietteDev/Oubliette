"""Pure query functions and lifecycle management for spell-applied buffs/debuffs.

This module parallels condition_effects.py — query functions are pure (no mutation),
and lifecycle functions (apply, remove, tick) handle buff state changes.

Buffs are temporary stat modifications from spells like Shield (+5 AC),
Bless (+1d4 attacks/saves), Haste (+2 AC, speed x2), Absorb Elements
(fire resistance), Faerie Fire (advantage on attacks against target), etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from arena.models.character import Creature
from arena.models.conditions import ActiveBuff, BuffEffect
from arena.combat.events import CombatEvent, CombatEventType

if TYPE_CHECKING:
    from arena.combat.manager import Combatant


# ── Query Functions (pure, no mutation) ─────────────────────────────


def get_buff_ac_bonus(creature: Creature) -> int:
    """Sum all AC bonuses from active buffs.

    Includes flat_bonus modifiers where stat="ac". Handles both
    positive (Shield +5) and negative (Slow -2) values.
    """
    total = 0
    for buff in creature.active_buffs:
        for mod in buff.modifiers:
            if mod.stat == "ac" and mod.modifier_type == "flat_bonus":
                if isinstance(mod.value, (int, float)):
                    total += int(mod.value)
    return total


def get_buff_stat_set_values(creature: Creature, stat: str) -> list[int | str]:
    """Raw "set" values from active buffs for one stat (floor semantics).

    Returns the unevaluated values — ints (Giant Strength 21) or formula
    strings ("13+DEX" for Mage Armor).  Evaluation against the creature
    happens in stat_modifiers (which owns ability lookups); keeping this a
    raw query avoids a circular import.
    """
    values: list[int | str] = []
    stat_lower = stat.lower()
    for buff in creature.active_buffs:
        for mod in buff.modifiers:
            if mod.stat.lower() == stat_lower and mod.modifier_type == "set":
                if isinstance(mod.value, (int, float)):
                    values.append(int(mod.value))
                elif isinstance(mod.value, str):
                    values.append(mod.value)
    return values


def get_buff_speed_bonus(creature: Creature) -> int:
    """Sum all flat speed bonuses from active buffs (e.g., Longstrider +10)."""
    total = 0
    for buff in creature.active_buffs:
        for mod in buff.modifiers:
            if mod.stat == "speed" and mod.modifier_type == "flat_bonus":
                if isinstance(mod.value, (int, float)):
                    total += int(mod.value)
    return total


def get_buff_speed_multiplier(creature: Creature) -> float:
    """Get the combined speed multiplier from active buffs.

    Multiplied together: Haste (2.0) * Slow (0.5) = 1.0.
    Returns 1.0 if no speed multipliers are active.
    """
    result = 1.0
    for buff in creature.active_buffs:
        for mod in buff.modifiers:
            if mod.stat == "speed" and mod.modifier_type == "multiply":
                if isinstance(mod.value, (int, float)):
                    result *= float(mod.value)
    return result


def get_buff_attack_modifiers(creature: Creature) -> tuple[int, list[str]]:
    """Get attack roll bonuses from active buffs on the attacker.

    Returns (flat_bonus, [dice_expressions]).
    Only includes self-buffs (target_grants_to_attacker=False).

    Example: Bless → (0, ["1d4"]), flat +2 weapon buff → (2, [])
    """
    flat = 0
    dice: list[str] = []
    for buff in creature.active_buffs:
        for mod in buff.modifiers:
            if mod.stat != "attack_rolls" or mod.modifier_type != "flat_bonus":
                continue
            if mod.target_grants_to_attacker:
                continue  # This is a debuff on targets, not a self-buff
            if isinstance(mod.value, int):
                flat += mod.value
            elif isinstance(mod.value, str):
                dice.append(mod.value)
    return flat, dice


def get_buff_damage_bonus(creature: Creature, attack_type: str | None = None) -> int:
    """Sum flat damage-roll bonuses from active buffs (Rage +2 melee, etc.).

    Only self-buffs with stat="damage_rolls" + modifier_type="flat_bonus" count.
    A scope of "all" applies to every attack; "melee"/"ranged" match against the
    attack_type prefix ("melee_weapon", "ranged_spell", ...). Applied once per
    attack — flat bonuses never double on crits.
    """
    total = 0
    for buff in creature.active_buffs:
        for mod in buff.modifiers:
            if mod.stat != "damage_rolls" or mod.modifier_type != "flat_bonus":
                continue
            if mod.target_grants_to_attacker:
                continue
            scope = (mod.scope or "all").lower()
            if scope != "all":
                if attack_type is None or not attack_type.startswith(scope):
                    continue
            if isinstance(mod.value, (int, float)):
                total += int(mod.value)
    return total


def get_buff_save_modifiers(creature: Creature, ability: str) -> tuple[int, list[str]]:
    """Get saving throw bonuses from active buffs.

    Returns (flat_bonus, [dice_expressions]).
    Respects scope: "all" matches any ability, or matches specific ability.

    Example: Bless with scope="all" → (0, ["1d4"]) for any ability.
    """
    flat = 0
    dice: list[str] = []
    ability_lower = ability.lower()
    for buff in creature.active_buffs:
        for mod in buff.modifiers:
            if mod.stat != "saving_throws" or mod.modifier_type != "flat_bonus":
                continue
            if mod.scope != "all" and mod.scope.lower() != ability_lower:
                continue
            if isinstance(mod.value, int):
                flat += mod.value
            elif isinstance(mod.value, str):
                dice.append(mod.value)
    return flat, dice


def get_buff_attack_advantage(attacker: Creature, target: Creature) -> int:
    """Get attack advantage/disadvantage from active buffs.

    Checks two sources:
    1. Attacker's own buffs with stat="attack_rolls" + modifier_type="advantage"
    2. Target's debuffs with stat="attack_rolls" + target_grants_to_attacker=True

    Returns > 0 for advantage, < 0 for disadvantage, 0 for none.
    Per 5e, any advantage + any disadvantage cancel (handled by caller).
    """
    has_adv = False
    has_dis = False

    # Check attacker's self-buffs
    for buff in attacker.active_buffs:
        for mod in buff.modifiers:
            if mod.stat != "attack_rolls" or mod.target_grants_to_attacker:
                continue
            if mod.modifier_type == "advantage":
                has_adv = True
            elif mod.modifier_type == "disadvantage":
                has_dis = True

    # Check target's debuffs that grant effects to attackers
    for buff in target.active_buffs:
        for mod in buff.modifiers:
            if mod.stat != "attack_rolls" or not mod.target_grants_to_attacker:
                continue
            if mod.modifier_type == "advantage":
                has_adv = True
            elif mod.modifier_type == "disadvantage":
                has_dis = True

    if has_adv and has_dis:
        return 0
    elif has_adv:
        return 1
    elif has_dis:
        return -1
    return 0


def get_buff_save_advantage(creature: Creature, ability: str) -> int:
    """Get saving throw advantage/disadvantage from active buffs.

    Respects scope: "all" matches any ability, or matches specific ability.
    Example: Haste → advantage on DEX saves (scope="dexterity").

    Returns > 0 for advantage, < 0 for disadvantage, 0 for none.
    """
    has_adv = False
    has_dis = False
    ability_lower = ability.lower()

    for buff in creature.active_buffs:
        for mod in buff.modifiers:
            if mod.stat != "saving_throws":
                continue
            if mod.scope != "all" and mod.scope.lower() != ability_lower:
                continue
            if mod.modifier_type == "advantage":
                has_adv = True
            elif mod.modifier_type == "disadvantage":
                has_dis = True

    if has_adv and has_dis:
        return 0
    elif has_adv:
        return 1
    elif has_dis:
        return -1
    return 0


def get_buff_damage_resistances(creature: Creature) -> list[str]:
    """Get damage types the creature has resistance to from active buffs.

    Example: Absorb Elements → ["fire"]
    """
    resistances: list[str] = []
    for buff in creature.active_buffs:
        for mod in buff.modifiers:
            if mod.stat == "damage_resistance" and mod.modifier_type == "resistance":
                if isinstance(mod.value, str):
                    resistances.append(mod.value)
    return resistances


def get_buff_damage_immunities(creature: Creature) -> list[str]:
    """Get damage types the creature has immunity to from active buffs."""
    immunities: list[str] = []
    for buff in creature.active_buffs:
        for mod in buff.modifiers:
            if mod.stat == "damage_resistance" and mod.modifier_type == "immunity":
                if isinstance(mod.value, str):
                    immunities.append(mod.value)
    return immunities


# ── Lifecycle Functions ──────────────────────────────────────────────


def apply_buff(
    creature: Creature,
    creature_id: str,
    buff: ActiveBuff,
) -> CombatEvent:
    """Apply a buff to a creature.

    If a buff with the same name from the same source already exists,
    it is replaced (no stacking of identical buffs).
    """
    # Remove existing buff with same name + source (no stacking)
    creature.active_buffs = [
        b for b in creature.active_buffs
        if not (b.name == buff.name and b.source_id == buff.source_id)
    ]
    creature.active_buffs.append(buff)

    mod_descriptions = []
    for mod in buff.modifiers:
        desc = _describe_modifier(mod)
        if desc:
            mod_descriptions.append(desc)

    effect_text = ", ".join(mod_descriptions) if mod_descriptions else "buff applied"
    return CombatEvent(
        event_type=CombatEventType.INFO,
        message=f"{creature.name} is affected by {buff.name} ({effect_text}).",
        source_id=buff.source_id,
        target_id=creature_id,
        details={"buff_applied": buff.name, "buff_source": buff.source_id},
    )


def remove_buff(
    creature: Creature,
    creature_id: str,
    buff_name: str,
    source_id: str | None = None,
) -> CombatEvent | None:
    """Remove a buff by name (and optionally by source).

    Returns a CombatEvent if a buff was removed, None otherwise.
    """
    original_count = len(creature.active_buffs)
    if source_id:
        creature.active_buffs = [
            b for b in creature.active_buffs
            if not (b.name == buff_name and b.source_id == source_id)
        ]
    else:
        creature.active_buffs = [
            b for b in creature.active_buffs
            if b.name != buff_name
        ]
    if len(creature.active_buffs) < original_count:
        return CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{creature.name}'s {buff_name} effect has ended.",
            source_id=creature_id,
            target_id=creature_id,
            details={"buff_removed": buff_name},
        )
    return None


def process_buff_start_of_turn(
    creature: Creature,
    creature_id: str,
) -> list[CombatEvent]:
    """Tick buff durations at start of creature's turn.

    Handles duration_type="rounds": decrement and remove when expired.
    """
    events: list[CombatEvent] = []
    expired: list[ActiveBuff] = []

    for buff in creature.active_buffs:
        if buff.duration_type == "rounds" and buff.duration_rounds is not None:
            buff.duration_rounds -= 1
            if buff.duration_rounds <= 0:
                expired.append(buff)

    for buff in expired:
        creature.active_buffs.remove(buff)
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{creature.name}'s {buff.name} effect has expired.",
            source_id=creature_id,
            target_id=creature_id,
            details={"buff_expired": buff.name},
        ))

    return events


def process_buff_end_of_turn(
    creature: Creature,
    creature_id: str,
) -> list[CombatEvent]:
    """Process buffs at end of creature's turn.

    Handles duration_type="end_of_turn" save-to-end buffs (debuffs like Bane).
    The creature rolls a saving throw; on success the buff/debuff is removed.
    """
    from arena.combat.actions import resolve_saving_throw

    events: list[CombatEvent] = []
    removed: list[ActiveBuff] = []

    for buff in creature.active_buffs:
        if buff.duration_type != "end_of_turn":
            continue
        if buff.save_to_end is None or buff.save_dc is None:
            continue

        success, save_event = resolve_saving_throw(
            creature, creature_id,
            buff.save_to_end, buff.save_dc,
        )
        save_event.message = (
            f"{buff.name} save: {save_event.message}"
        )
        events.append(save_event)

        if success:
            removed.append(buff)

    for buff in removed:
        creature.active_buffs.remove(buff)
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{creature.name} shakes off {buff.name}!",
            source_id=creature_id,
            target_id=creature_id,
            details={"buff_saved_off": buff.name},
        ))

    return events


# ── Helpers ──────────────────────────────────────────────────────────


def _describe_modifier(mod: BuffEffect) -> str:
    """Return a human-readable description of a buff modifier."""
    value_str = ""
    if mod.value is not None:
        if isinstance(mod.value, float) and mod.modifier_type == "multiply":
            value_str = f"x{mod.value}"
        elif isinstance(mod.value, int) and mod.value > 0:
            value_str = f"+{mod.value}"
        else:
            value_str = str(mod.value)

    scope_str = ""
    if mod.scope != "all":
        scope_str = f" {mod.scope}"

    stat_names = {
        "ac": "AC",
        "attack_rolls": "attack rolls",
        "saving_throws": "saving throws",
        "speed": "speed",
        "damage_resistance": "damage resistance",
        "ability_checks": "ability checks",
    }
    stat_display = stat_names.get(mod.stat, mod.stat)

    if mod.modifier_type == "advantage":
        return f"advantage on{scope_str} {stat_display}"
    elif mod.modifier_type == "disadvantage":
        return f"disadvantage on{scope_str} {stat_display}"
    elif mod.modifier_type == "resistance":
        return f"resistance to {mod.value}"
    elif mod.modifier_type == "immunity":
        return f"immunity to {mod.value}"
    elif mod.modifier_type == "multiply":
        return f"{stat_display} {value_str}"
    else:
        return f"{value_str}{scope_str} {stat_display}"
