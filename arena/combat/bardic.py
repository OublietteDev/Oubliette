"""Bardic Inspiration & Cutting Words — the reaction-modify-roll mechanic (P-CONTROL/C4).

A Bardic Inspiration die is a banked resource that nudges a d20 roll:

  * **Bardic Inspiration** — a bard spends a use to *grant* an ally a die; the
    ally later adds it to a roll (here: their attack roll, to turn a miss into a
    hit). Modeled as an ``inspiration_die`` buff (1 charge) on the recipient.
  * **Cutting Words** (College of Lore) — a reaction: a bard subtracts a die from
    a roll a creature it can see makes (here: an enemy's attack roll, to turn a
    hit into a miss). Spends from the bard's ``bardic_inspiration`` pool directly.

Both are applied **auto-optimally** for now: the die is spent only when it could
actually flip the outcome (the gap to AC is within the die's range). The RAW
player-choice prompt (and use on saves / ability checks / damage rolls) is a
follow-up that rides the existing reroll-popup pattern. Bard resource pools are
CHA-scaled — `class_resources["bardic_inspiration"]` (uses) and
`["bardic_inspiration_die"]` (die size); staging them from real bard sheets is
the noted classes.json data gap.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from arena.models.character import Creature
from arena.models.conditions import ActiveBuff, BuffEffect
from arena.combat.buff_effects import get_buff_stat_set_values
from arena.combat.events import CombatEvent, CombatEventType
from arena.util.dice import roll_die

if TYPE_CHECKING:
    from arena.combat.manager import Combatant


def inspiration_die_size(creature: Creature) -> int | None:
    """Size of a banked Bardic Inspiration die on this creature, if any."""
    vals = [v for v in get_buff_stat_set_values(creature, "inspiration_die") if isinstance(v, int)]
    return max(vals) if vals else None


def _consume_inspiration_die(creature: Creature) -> None:
    creature.active_buffs = [
        b for b in creature.active_buffs
        if not any(m.stat == "inspiration_die" for m in b.modifiers)
    ]


def grant_inspiration(
    target: Creature, target_id: str, die_size: int, source_id: str, source_name: str = "Bard",
) -> list[CombatEvent]:
    """Bank a Bardic Inspiration die on an ally (the grant half)."""
    target.active_buffs.append(ActiveBuff(
        name="Bardic Inspiration", source_id=source_id,
        modifiers=[BuffEffect(stat="inspiration_die", modifier_type="set", value=die_size)],
        charges=1, duration_type="rounds", duration_rounds=100,
    ))
    return [CombatEvent(
        event_type=CombatEventType.CONDITION_APPLIED,
        message=f"{source_name} grants {target.name} a Bardic Inspiration die (d{die_size}).",
        source_id=source_id, target_id=target_id,
        details={"bardic_inspiration_granted": die_size},
    )]


def _has_cutting_words(creature: Creature) -> bool:
    return any(getattr(f, "cutting_words", False) for f in getattr(creature, "features", []) or [])


def find_cutting_words_bard(target_id: str, combatants: dict[str, "Combatant"]):
    """An ally of the defender who can Cut Words: has the feature + a pool use."""
    target_cb = combatants.get(target_id)
    if target_cb is None:
        return None, None
    for cid, cb in combatants.items():
        if cid == target_id:
            continue
        if cb.team != target_cb.team:
            continue
        cr = cb.creature
        if not cr.is_conscious or not _has_cutting_words(cr):
            continue
        if getattr(cr, "class_resources", {}).get("bardic_inspiration", 0) <= 0:
            continue
        return cr, cid
    return None, None


def apply_bard_dice_to_attack(
    attacker: Creature, attacker_id: str,
    target: Creature, target_id: str,
    total_roll: int, target_ac: int, hit: bool,
    combatants: dict[str, "Combatant"],
) -> tuple[int, bool, list[CombatEvent]]:
    """Apply Bardic Inspiration / Cutting Words to a (non-crit) attack outcome.

    Returns (possibly-updated total_roll, hit, events). Only spends a die when it
    could flip the result.
    """
    events: list[CombatEvent] = []

    if not hit:
        # Bardic Inspiration on the attacker's OWN roll: close a near-miss.
        die = inspiration_die_size(attacker)
        gap = target_ac - total_roll
        if die and 1 <= gap <= die:
            val = roll_die(die)
            _consume_inspiration_die(attacker)
            total_roll += val
            if total_roll >= target_ac:
                hit = True
                events.append(CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=(f"{attacker.name} calls on their Bardic Inspiration "
                             f"(d{die}={val}) — the miss becomes a HIT!"),
                    source_id=attacker_id, target_id=target_id,
                    details={"bardic_inspiration_used": val},
                ))
            else:
                events.append(CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=(f"{attacker.name} spends a Bardic Inspiration die "
                             f"(d{die}={val}) — but it still misses."),
                    source_id=attacker_id, target_id=target_id,
                    details={"bardic_inspiration_used": val},
                ))
    else:
        # Cutting Words: a defending bard subtracts a die to spoil the hit.
        bard, bard_id = find_cutting_words_bard(target_id, combatants)
        if bard is not None:
            die = int(getattr(bard, "class_resources", {}).get("bardic_inspiration_die", 6))
            margin = total_roll - target_ac
            if 0 <= margin < die:  # a max subtract could drop it below AC
                val = roll_die(die)
                bard.class_resources["bardic_inspiration"] = (
                    bard.class_resources.get("bardic_inspiration", 0) - 1)
                total_roll -= val
                if total_roll < target_ac:
                    hit = False
                    events.append(CombatEvent(
                        event_type=CombatEventType.INFO,
                        message=(f"{bard.name} cuts {attacker.name} down with Cutting "
                                 f"Words (d{die}={val}) — the hit becomes a MISS!"),
                        source_id=bard_id, target_id=attacker_id,
                        details={"cutting_words_used": val},
                    ))
                else:
                    events.append(CombatEvent(
                        event_type=CombatEventType.INFO,
                        message=(f"{bard.name} uses Cutting Words (d{die}={val}) on "
                                 f"{attacker.name} — but the strike lands anyway."),
                        source_id=bard_id, target_id=attacker_id,
                        details={"cutting_words_used": val},
                    ))
    return total_roll, hit, events
