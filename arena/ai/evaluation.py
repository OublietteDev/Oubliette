"""Target and action evaluation for AI decision making.

All functions are pure — they take immutable inputs and return scores.
No CombatManager or Pygame dependency.
"""

from __future__ import annotations

from arena.ai.behavior import AIProfile
from arena.ai.context import CombatContext, CreatureView, creature_distance


def evaluate_target(
    profile: AIProfile,
    me: CreatureView,
    target: CreatureView,
) -> float:
    """Score a potential target.  Higher = more desirable.

    Factors:
    - Distance (profile.prefers_melee / maintains_distance)
    - HP percentage (target_priority modes)
    - Spellcaster focus
    - Concentration-breaking bonus
    """
    if target.position is None or me.position is None:
        return 0.0

    distance = creature_distance(me, target)
    score = 100.0

    # ── Distance factor ──────────────────────────────────────────────
    if profile.prefers_melee:
        # Melee: penalize distant targets more heavily
        score -= distance * 3
    else:
        # Ranged: prefer targets near optimal distance
        optimal = profile.maintains_distance // 5  # convert feet to hexes
        if optimal <= 0:
            optimal = 6  # default ~30 ft
        score -= abs(distance - optimal) * 2

    # ── Target priority mode ─────────────────────────────────────────
    if profile.target_priority == "nearest":
        # Already handled by distance penalty above; small extra nudge
        score -= distance * 1
    elif profile.target_priority == "weakest":
        score += (1.0 - target.hp_percent) * 50
    elif profile.target_priority == "strongest":
        score += target.hp_percent * 30
    elif profile.target_priority == "threatening":
        score += evaluate_threat(target, me) * 20
    elif profile.target_priority == "random":
        # Give a flat score so all targets are roughly equal
        score = 50.0

    # ── Spellcaster focus ────────────────────────────────────────────
    if profile.focuses_spellcasters and target.is_spellcaster:
        score += 30

    # ── Concentration-breaking bonus ─────────────────────────────────
    if target.has_concentration:
        score += 25

    # ── Low-HP kill opportunity ──────────────────────────────────────
    if target.hp_percent <= 0.25:
        score += 15  # finishing blow bonus

    return score


def rank_targets(
    profile: AIProfile,
    context: CombatContext,
) -> list[tuple[str, float]]:
    """Rank all living enemies by target score.

    Returns list of (creature_id, score) sorted by score descending.
    """
    scored: list[tuple[str, float]] = []
    for enemy in context.enemies:
        if not enemy.is_conscious:
            continue
        s = evaluate_target(profile, context.me, enemy)
        scored.append((enemy.creature_id, s))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def evaluate_threat(
    target: CreatureView,
    me: CreatureView,
) -> float:
    """Estimate how threatening *target* is to *me*.

    Heuristic:
    - More HP = more threatening (can sustain combat longer)
    - Lower AC = less threatening (easier to hit, less of a tank)
    - More actions = more dangerous
    - Closer = more threatening
    """
    threat = 0.0

    # HP factor — healthier creatures are more threatening
    threat += target.hp_percent * 2.0

    # Action count — more options = more dangerous
    threat += min(target.actions_count, 5) * 0.5

    # Proximity — closer is more threatening
    if target.position is not None and me.position is not None:
        dist = creature_distance(me, target)
        if dist > 0:
            threat += 3.0 / dist  # inverse distance
        else:
            threat += 3.0

    # Spellcasters are threatening
    if target.is_spellcaster:
        threat += 1.5

    return threat
