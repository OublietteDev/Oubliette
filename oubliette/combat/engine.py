"""Placeholder combat resolver. Deterministic auto-resolve via the shared seeded
RNG (so every swing is logged and reproducible). The revived tactical prototype
will replace this function without touching the boundary.
"""

from __future__ import annotations

from typing import Literal

from ..record.log import DebugLog
from ..record.rng import Rng
from .schemas import Combatant

_SAFETY_ROUND_CAP = 100


def _attack(attacker: Combatant, defender: Combatant, rng: Rng, log: DebugLog, rnd: int) -> None:
    to_hit = rng.roll(f"1d20+{attacker.attack_bonus}", f"attack:{attacker.id}->{defender.id}")
    hit = to_hit.total >= defender.armor_class
    dmg_total = 0
    if hit:
        dmg = rng.roll(attacker.damage, f"damage:{attacker.id}")
        dmg_total = dmg.total
        defender.hp = max(0, defender.hp - dmg_total)
    log.append("combat_swing", round=rnd, attacker=attacker.id, defender=defender.id,
               to_hit=to_hit.total, ac=defender.armor_class, hit=hit, damage=dmg_total,
               defender_hp=defender.hp)


def auto_resolve(
    combatants: list[Combatant], rng: Rng, log: DebugLog
) -> Literal["victory", "defeat"]:
    """Run the fight to a conclusion. PC side vs everything else.
    Returns 'victory' (PC stands) or 'defeat' (PC down)."""
    pc = next(c for c in combatants if c.is_pc)
    enemies = [c for c in combatants if not c.is_pc]

    rnd = 0
    while pc.hp > 0 and any(e.hp > 0 for e in enemies) and rnd < _SAFETY_ROUND_CAP:
        rnd += 1
        # PC acts: focus the first standing enemy.
        target = next((e for e in enemies if e.hp > 0), None)
        if target is not None:
            _attack(pc, target, rng, log, rnd)
        # Surviving enemies swing back.
        for e in enemies:
            if e.hp > 0 and pc.hp > 0:
                _attack(e, pc, rng, log, rnd)

    return "victory" if pc.hp > 0 else "defeat"
