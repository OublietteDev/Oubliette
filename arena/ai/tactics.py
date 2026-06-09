"""Tactical behaviors — retreat, focus fire, protect ally.

These are high-level tactical overrides that can pre-empt the normal
scoring pipeline when specific conditions are met.

All functions are pure.  No CombatManager or Pygame dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from arena.ai.behavior import AIProfile
from arena.ai.context import CombatContext


@dataclass(frozen=True)
class TacticalDecision:
    """A high-level tactical decision that overrides normal scoring."""

    decision_type: str  # "retreat", "focus_fire", "protect_ally", "normal"
    reason: str  # Human-readable explanation
    forced_action: str | None = None  # e.g., "disengage" for retreat
    target_id: str | None = None  # creature to focus/protect


def check_retreat(
    profile: AIProfile,
    context: CombatContext,
) -> TacticalDecision | None:
    """Check if the AI should retreat this turn.

    Returns a retreat TacticalDecision if:
    - HP percent < profile.retreat_threshold AND profile.will_flee

    The retreat decision forces Disengage action and maximal-distance movement.
    """
    if not profile.will_flee:
        return None

    if context.me.hp_percent >= profile.retreat_threshold:
        return None

    hp_pct = int(context.me.hp_percent * 100)
    return TacticalDecision(
        decision_type="retreat",
        reason=f"HP at {hp_pct}%, retreating!",
        forced_action="disengage",
    )


def check_focus_fire(
    profile: AIProfile,
    context: CombatContext,
) -> str | None:
    """Check if we should focus fire on a nearly-dead enemy.

    Returns creature_id of the focus target, or None.
    Focus fire when an enemy is below 25% HP and we can finish them.
    """
    if not context.enemies:
        return None

    # Find the lowest-HP enemy that's close to death
    best_target: str | None = None
    lowest_hp = 1.0

    for enemy in context.enemies:
        if enemy.hp_percent <= 0.25 and enemy.hp_percent < lowest_hp:
            lowest_hp = enemy.hp_percent
            best_target = enemy.creature_id

    return best_target


def check_protect_ally(
    profile: AIProfile,
    context: CombatContext,
) -> str | None:
    """Check if we should protect a low-HP ally (profile.protects_allies).

    Returns creature_id of ally to protect, or None.
    Triggers when protects_allies is True and an ally is below 30% HP.
    """
    if not profile.protects_allies:
        return None

    if not context.allies:
        return None

    # Find most wounded ally
    worst_ally: str | None = None
    lowest_hp = 1.0

    for ally in context.allies:
        if ally.hp_percent < 0.3 and ally.hp_percent < lowest_hp:
            lowest_hp = ally.hp_percent
            worst_ally = ally.creature_id

    return worst_ally
