"""Damage calculation and application.

Damage flows as a LIST of typed ``DamagePacket`` objects (one per damage type)
from the roll all the way to the target, and is realized into hit points only at
the very end of :func:`apply_damage`.  Keeping the per-type breakdown alive means
mixed-type attacks (a dragon's piercing+fire bite, a flame tongue's slashing+fire,
Divine Smite's weapon+radiant) resolve resistance / immunity / vulnerability
*per type*, the way 5e intends.

Single-type damage is just a one-element packet list, so its arithmetic is
identical to the old "one int + one type" path — the overwhelming majority of
content (and tests) is unaffected by construction.  ``apply_damage`` still accepts
a bare ``int`` + ``damage_type`` for callers that only ever deal one type
(recurring effects, zones); that path wraps the value in a single packet.
"""

from dataclasses import dataclass, field

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


@dataclass
class DamagePacket:
    """A single typed chunk of damage flowing through resolution.

    ``tags`` is an OPEN set (``"magical"``, ``"silvered"``, a source id, …): the
    extension point for later effects, which attach tags that defense handlers
    check for — the packet *structure* never has to change.  ``can_reduce``
    lets a packet opt out of flat/reaction reductions.  ``breakdown`` carries the
    dice/rolls detail purely for the event log.
    """

    amount: int
    dtype: str
    source: str = ""
    tags: set = field(default_factory=set)
    can_reduce: bool = True
    breakdown: dict = field(default_factory=dict)

    def to_detail(self) -> dict:
        """Render this packet as an event/log detail dict."""
        detail = dict(self.breakdown)
        detail["damage_type"] = self.dtype
        detail["subtotal"] = self.amount
        if self.source:
            detail["source"] = self.source
        return detail


def roll_damage(
    damage_rolls: list[DamageRoll],
    attacker: Creature,
    is_critical: bool = False,
) -> list[DamagePacket]:
    """Roll an attack's damage into a list of typed packets (one per DamageRoll).

    Args:
        damage_rolls: List of DamageRoll from the Attack model.
        attacker: The attacking creature (for ability modifiers).
        is_critical: If True, double the dice (not the modifier).

    Returns:
        A list of DamagePacket, one per damage roll, each amount floored at 0.
    """
    packets: list[DamagePacket] = []

    for dr in damage_rolls:
        # Roll the dice
        dice_total, dice_list = roll_expression(dr.dice)

        # Critical hit: roll dice again and add
        if is_critical:
            crit_total, crit_list = roll_expression(dr.dice)
            dice_total += crit_total
            dice_list = dice_list + crit_list

        bonus = dr.bonus

        ability_bonus = 0
        if dr.ability_modifier:
            ability_bonus = get_effective_ability_modifier(attacker, dr.ability_modifier)

        subtotal = dice_total + bonus + ability_bonus

        packets.append(
            DamagePacket(
                amount=max(0, subtotal),
                dtype=dr.damage_type.value,
                breakdown={
                    "dice": dr.dice,
                    "rolls": dice_list,
                    "bonus": bonus,
                    "ability_bonus": ability_bonus,
                },
            )
        )

    return packets


def halve_packets(packets: list[DamagePacket]) -> list[DamagePacket]:
    """Halve every packet's amount (rounded down per packet).

    Used by save-for-half, Evasion, and Uncanny Dodge.  For single-type damage
    this is identical to halving the scalar total.
    """
    for p in packets:
        p.amount = p.amount // 2
    return packets


def zero_packets(packets: list[DamagePacket]) -> list[DamagePacket]:
    """Set every packet's amount to 0 (save-for-none, Evasion on success)."""
    for p in packets:
        p.amount = 0
    return packets


def reduce_packets_flat(packets: list[DamagePacket], amount: int) -> list[DamagePacket]:
    """Drain a flat ``amount`` of reduction across reducible packets, in order.

    Mirrors the old scalar ``max(0, damage - reduction)`` for a single packet.
    """
    remaining = amount
    for p in packets:
        if remaining <= 0:
            break
        if not p.can_reduce:
            continue
        take = min(p.amount, remaining)
        p.amount -= take
        remaining -= take
    return packets


def _defend_packet(
    packet: DamagePacket,
    immunities: list[str],
    resistances: list[str],
    vulnerabilities: list[str],
) -> tuple[int, str]:
    """Apply immunity / resistance / vulnerability to one packet by its type.

    Processing order per 5e: immunity negates, then resistance halves, then
    vulnerability doubles.  Resistance and vulnerability to the same type cancel.

    Returns:
        (modified_amount, modifier_text) for logging.
    """
    dtype = packet.dtype.lower()
    is_immune = dtype in immunities
    is_resistant = dtype in resistances
    is_vulnerable = dtype in vulnerabilities

    if is_immune:
        return 0, " [IMMUNE]"

    if is_resistant and is_vulnerable:
        return packet.amount, ""

    if is_resistant:
        return packet.amount // 2, " [RESISTANT - halved]"

    if is_vulnerable:
        return packet.amount * 2, " [VULNERABLE - doubled]"

    return packet.amount, ""


def _apply_damage_modifiers(
    target: Creature, damage: int, damage_type: str
) -> tuple[int, str]:
    """Scalar resistance/immunity/vulnerability helper (single type).

    Kept as a thin wrapper over the packet defense logic for callers/tests that
    work in single-type scalars.

    Returns:
        (modified_damage, modifier_text) for logging.
    """
    immunities = [d.lower() for d in get_effective_damage_immunities(target)]
    resistances = [d.lower() for d in get_effective_damage_resistances(target)]
    vulnerabilities = [d.lower() for d in target.damage_vulnerabilities]
    return _defend_packet(
        DamagePacket(amount=damage, dtype=damage_type),
        immunities,
        resistances,
        vulnerabilities,
    )


def apply_damage(
    target: Creature,
    damage: "int | list[DamagePacket]",
    damage_type: str | None = None,
    creature_id: str = "",
) -> tuple[CombatEvent, list[CombatEvent]]:
    """Apply damage to a creature, accounting for per-type defenses and temp HP.

    ``damage`` may be either a list of :class:`DamagePacket` (the full pipeline)
    or a bare ``int`` with ``damage_type`` (single-type convenience, wrapped into
    one packet).

    Processing order:
    1. Per packet: apply resistance / immunity / vulnerability by its damage type.
    2. Subtract from temporary hit points first (across packets).
    3. Remainder subtracts from current hit points (minimum 0).
    4. If the creature just dropped to 0 HP, check death prevention features.

    Returns:
        A tuple of (damage_event, extra_events) where extra_events contains any
        death prevention events that fired.
    """
    if isinstance(damage, list):
        packets = damage
    else:
        packets = [DamagePacket(amount=int(damage), dtype=damage_type or "untyped")]

    extra_events: list[CombatEvent] = []

    immunities = [d.lower() for d in get_effective_damage_immunities(target)]
    resistances = [d.lower() for d in get_effective_damage_resistances(target)]
    vulnerabilities = [d.lower() for d in target.damage_vulnerabilities]

    raw_damage = sum(max(0, p.amount) for p in packets)

    # 1. Per-type defenses
    defended: list[tuple[int, str, str]] = []  # (amount, dtype, modifier_text)
    for p in packets:
        amt, text = _defend_packet(p, immunities, resistances, vulnerabilities)
        defended.append((max(0, amt), p.dtype, text))

    modified_damage = sum(amt for amt, _, _ in defended)

    old_hp = target.current_hit_points if target.current_hit_points is not None else 0

    # 2. Absorb with temp HP first (across all packets)
    temp_absorbed = 0
    remaining_damage = modified_damage
    if target.temporary_hit_points > 0 and remaining_damage > 0:
        temp_absorbed = min(target.temporary_hit_points, remaining_damage)
        target.temporary_hit_points -= temp_absorbed
        remaining_damage -= temp_absorbed

    # 3. Apply remaining to real HP
    new_hp = max(0, old_hp - remaining_damage)
    target.current_hit_points = new_hp

    was_conscious = old_hp > 0
    is_now_unconscious = new_hp <= 0
    death_prevented = False

    # 4. Death prevention check: creature just dropped to 0 HP
    if was_conscious and is_now_unconscious:
        dp_features = get_death_prevention_features(target)
        for feature in dp_features:
            if not can_use_death_prevention(target, feature):
                continue
            use_count = getattr(target, '_death_prevention_use_count', {}).get(
                feature.name, 0
            )
            success, dp_events = resolve_death_prevention(
                target, creature_id, feature, use_count=use_count
            )
            extra_events.extend(dp_events)
            if not hasattr(target, '_death_prevention_use_count'):
                target._death_prevention_use_count = {}
            target._death_prevention_use_count[feature.name] = use_count + 1
            if success:
                new_hp = target.current_hit_points  # resolve set it to 1
                is_now_unconscious = False
                death_prevented = True
                break

    # Build the damage-type label + modifier text for the message
    if len(defended) == 1:
        type_label = defended[0][1]
        modifier_text = defended[0][2]
    else:
        type_label = "+".join(dt for _, dt, _ in defended)
        # Combine any distinct per-type modifier notes (e.g. " [IMMUNE]")
        seen: list[str] = []
        for _, _, text in defended:
            if text and text not in seen:
                seen.append(text)
        modifier_text = "".join(seen)

    msg = f"takes {modified_damage} {type_label} damage{modifier_text}"
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
            "raw_damage": raw_damage,
            "damage_type": type_label,
            "old_hp": old_hp,
            "new_hp": new_hp,
            "temp_absorbed": temp_absorbed,
            "knocked_out": is_now_unconscious and was_conscious,
            "death_prevented": death_prevented,
            "modifier_text": modifier_text,
            "packets": [
                {"amount": amt, "damage_type": dt, "modifier_text": text}
                for amt, dt, text in defended
            ],
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
