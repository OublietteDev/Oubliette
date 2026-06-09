"""AI resource management — deciding when to use limited abilities.

Pure functions.  No CombatManager or Pygame dependency.
"""

from __future__ import annotations

from arena.ai.behavior import AIProfile
from arena.ai.context import CombatContext
from arena.models.actions import Action


def should_use_limited_ability(
    action: Action,
    profile: AIProfile,
    context: CombatContext,
) -> bool:
    """Decide whether to spend a limited-use ability now.

    Factors:
    - profile.uses_limited_abilities (0=never, 1=freely)
    - Number of remaining uses vs max uses
    - Number of enemies remaining
    - Current HP situation (desperate = more willing)
    - action.ai_priority (high-priority abilities used more freely)
    """
    remaining = get_remaining_uses(action)

    # Unlimited ability — always OK
    if remaining is None:
        return True

    # No uses left
    if remaining <= 0:
        return False

    # Profile says never use limited abilities
    if profile.uses_limited_abilities <= 0:
        return False

    # Calculate willingness threshold (0.0-1.0)
    willingness = profile.uses_limited_abilities

    # High ai_priority makes us more willing
    priority_factor = action.ai_priority / 10.0  # 0.1-1.0
    willingness *= (0.5 + priority_factor * 0.5)  # scale by priority

    # Desperate (low HP) makes us more willing
    if context.me.hp_percent < 0.3:
        willingness += 0.3

    # Conservation: save if many enemies remain and few uses left
    # High-priority abilities (8+) are signature moves (breath weapons,
    # smites, etc.) — don't conserve these, use them when tactically good.
    battle_progress = estimate_battle_progress(context)
    if battle_progress < 0.3 and remaining == 1 and action.ai_priority < 8:
        willingness *= 0.5  # save last use for later

    return willingness >= 0.4


def get_remaining_uses(action: Action) -> int | None:
    """Get remaining uses of a limited ability, or None if unlimited."""
    if action.uses_per_rest is None:
        return None

    if action.current_uses is not None:
        return action.current_uses
    return action.uses_per_rest


def estimate_battle_progress(context: CombatContext) -> float:
    """Estimate how far through the battle we are (0.0=start, 1.0=end).

    Based on total enemy HP remaining vs starting potential.
    """
    if not context.enemies:
        return 1.0

    total_current = sum(e.current_hit_points for e in context.enemies)
    total_max = sum(e.max_hit_points for e in context.enemies)

    if total_max == 0:
        return 1.0

    damage_dealt = 1.0 - (total_current / total_max)
    return damage_dealt
