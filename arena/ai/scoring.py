"""Action scoring — evaluates which action+target combination is best.

All functions are pure.  No CombatManager or Pygame dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from arena.ai.behavior import AIProfile
from arena.ai.context import CombatContext, CreatureView, creature_distance
from arena.ai.evaluation import evaluate_target
from arena.models.character import CreatureSize

if TYPE_CHECKING:
    from arena.models.actions import Action


@dataclass(frozen=True)
class ScoredAction:
    """An action+target combination with its computed score."""

    action_name: str
    target_id: str | None  # None for SELF-targeting or standard actions
    score: float
    action_category: str  # "attack", "heal", "standard", "bonus_attack", "teleport", "shove"
    description: str  # Human-readable, e.g., "Longsword -> Goblin 1"
    target_hex: tuple[int, int] | None = None  # Destination hex for teleport
    cast_level: int | None = None  # Spell slot level for upcast spells


def score_attack_action(
    action: Action,
    profile: AIProfile,
    context: CombatContext,
    target: CreatureView,
    distance_hexes: int,
) -> float:
    """Score an attack action against a specific target.

    Factors:
    - action.ai_priority (1-10 scale)
    - profile.aggression weight
    - target desirability (from evaluate_target)
    - range feasibility
    - expected damage estimate
    """
    base = action.ai_priority * 10.0  # 10-100 range
    base *= profile.aggression  # 0.0-2.0 multiplier

    # Target desirability
    target_score = evaluate_target(profile, context.me, target)
    base += target_score * 0.5

    # Estimated damage value
    dmg_estimate = estimate_damage(action)
    base += dmg_estimate * 2.0

    # Range check penalty: if out of range, heavily penalize
    action_range_hexes = _get_action_range_hexes(action)
    if distance_hexes > action_range_hexes:
        base -= (distance_hexes - action_range_hexes) * 10

    # Melee/ranged alignment with profile
    is_melee_action = action.attack and action.attack.attack_type.startswith("melee")
    if is_melee_action and not profile.prefers_melee:
        base *= 0.7  # ranged profile using melee
    elif not is_melee_action and profile.prefers_melee:
        base *= 0.8  # melee profile using ranged

    return max(base, 0.0)


def score_healing_action(
    action: Action,
    profile: AIProfile,
    context: CombatContext,
    target: CreatureView,
) -> float:
    """Score a healing action on an ally (or self).

    Higher score when target is lower HP.
    Weighted by profile.protects_allies for allies, self_preservation for self.
    """
    if not action.healing:
        return 0.0

    base = action.ai_priority * 8.0
    hp_need = 1.0 - target.hp_percent  # 0.0 = full, 1.0 = dead

    base += hp_need * 60

    if target.creature_id == context.me.creature_id:
        base *= profile.self_preservation
    else:
        base *= (1.5 if profile.protects_allies else 0.5)

    return max(base, 0.0)


def score_effect_action(
    action: Action,
    profile: AIProfile,
    context: CombatContext,
    target: CreatureView,
    distance_hexes: int,
) -> float:
    """Score a saving-throw effect action against a specific target.

    Covers breath weapons, offensive spells with saves, and similar
    non-attack actions that deal damage or apply conditions to enemies.

    Factors:
    - action.ai_priority
    - profile.aggression
    - target desirability
    - estimated save damage
    - number of enemies (area effects are better against groups)
    """
    base = action.ai_priority * 10.0
    base *= profile.aggression

    # Target desirability
    target_score = evaluate_target(profile, context.me, target)
    base += target_score * 0.5

    # Estimated damage from saving throw
    dmg_estimate = estimate_save_damage(action)
    base += dmg_estimate * 2.0

    # Range check penalty
    action_range_hexes = _get_action_range_hexes(action)
    if distance_hexes > action_range_hexes:
        base -= (distance_hexes - action_range_hexes) * 10

    # Area effects: real geometry (B5). Execution centers the blast on the
    # CASTER (_resolve_effect_targets), so measure from me — enemies actually
    # inside raise the score; allies inside are friendly fire and lower it.
    if action.target_type.value.startswith("area_"):
        area_feet = action.area_size or action.range
        radius_hexes = area_feet / 5 if area_feet else 0
        if context.me.position is not None and radius_hexes > 0:
            enemies_hit = sum(
                1 for e in context.enemies
                if e.position is not None
                and creature_distance(context.me, e) <= radius_hexes
            )
            allies_hit = sum(
                1 for a in context.allies
                if a.position is not None
                and creature_distance(context.me, a) <= radius_hexes
            )
            if enemies_hit > 1:
                base *= 1.0 + 0.3 * (enemies_hit - 1)
            if allies_hit:
                penalty = 25.0 * allies_hit
                if profile.protects_allies:
                    penalty *= 2.0
                base -= penalty
        elif len(context.enemies) > 1:
            # No geometry available — fall back to the old crude group bonus
            base *= 1.0 + 0.3 * (len(context.enemies) - 1)

    # Condition application bonus (e.g., frightened, restrained)
    if action.saving_throw and action.saving_throw.conditions_on_fail:
        base += len(action.saving_throw.conditions_on_fail) * 10.0

    # Terrain modification bonus (Wall of Stone, Spike Growth, etc.)
    if action.terrain_modification is not None:
        terrain_bonus = 15.0
        if action.terrain_modification in ("wall", "pit"):
            # Area denial is very valuable
            terrain_bonus += 20.0
            if len(context.enemies) > 1:
                terrain_bonus *= 1.0 + 0.2 * (len(context.enemies) - 1)
        elif action.terrain_modification == "difficult":
            # Slowing melee enemies is more valuable
            terrain_bonus += 8.0
        elif action.terrain_modification == "normal":
            # Terrain removal is situational
            terrain_bonus = 5.0
        base += terrain_bonus

    return max(base, 0.0)


def score_standard_action(
    action_name: str,
    profile: AIProfile,
    context: CombatContext,
) -> float:
    """Score a standard action (Dash, Disengage, Dodge, Hide).

    Returns a score based on the profile and situation.
    """
    name = action_name.lower()

    if name == "dash":
        # Valuable when enemies are far and we want to close (melee)
        # or when retreating
        if not context.enemies:
            return 5.0
        min_dist = _min_enemy_distance(context)
        if profile.prefers_melee and min_dist > 2:
            return 30.0 + min_dist * 3
        # For retreat scenarios
        if context.me.hp_percent < profile.retreat_threshold and profile.will_flee:
            return 40.0
        return 10.0

    elif name == "disengage":
        # Valuable when we want to move away without OAs
        in_melee = _min_enemy_distance(context) <= 1
        if not in_melee:
            return 0.0  # pointless if not adjacent to enemy
        if profile.avoids_opportunity_attacks:
            wants_distance = (
                not profile.prefers_melee
                or (context.me.hp_percent < profile.retreat_threshold and profile.will_flee)
            )
            if wants_distance:
                return 50.0 * profile.self_preservation
        return 5.0

    elif name == "dodge":
        # Valuable when low HP and high self-preservation
        hp_factor = 1.0 - context.me.hp_percent
        return 20.0 * hp_factor * profile.self_preservation

    elif name == "hide":
        # Valuable for ranged profiles that want stealth advantage
        if not profile.prefers_melee and _min_enemy_distance(context) > 1:
            return 25.0
        return 5.0

    return 0.0


def score_teleport_action(
    action: Action,
    profile: AIProfile,
    context: CombatContext,
    dest_hex: tuple[int, int],
) -> float:
    """Score a teleport action to a specific destination.

    High value when:
    - Low HP and need to escape (defensive value)
    - Ranged profile surrounded in melee (reposition)
    - Origin damage + surrounded by enemies (Thunder Step)
    - Non-melee profile stuck in melee (even at full HP)
    """
    from arena.grid.coordinates import HexCoord

    base = float(action.ai_priority) * 5.0
    dest = HexCoord(dest_hex[0], dest_hex[1])

    # Calculate distances from destination to enemies
    if context.enemies:
        min_enemy_dist = 999
        for enemy in context.enemies:
            if enemy.position is not None:
                d = dest.distance_to(enemy.position)
                if d < min_enemy_dist:
                    min_enemy_dist = d

        # Escape value: high when low HP
        hp_pct = context.me.hp_percent
        if hp_pct < profile.retreat_threshold:
            escape_value = (1.0 - hp_pct) * min_enemy_dist * 10.0 * profile.self_preservation
            base += escape_value

        # Repositioning: ranged profiles want distance, melee want adjacency
        if profile.prefers_melee:
            if min_enemy_dist <= 1:
                base += 15.0  # Adjacent — good for melee
        else:
            # Ranged: reward distance from enemies
            if min_enemy_dist > 2:
                base += 10.0 + min_enemy_dist * 2.0

        # ── Melee escape bonus ────────────────────────────────────
        # Non-melee profiles stuck in melee get a significant bonus
        # for teleporting to safety, EVEN at full HP.
        # A caster adjacent to enemies should strongly prefer teleporting
        # away rather than provoking opportunity attacks by walking.
        if not profile.prefers_melee:
            currently_in_melee = _min_enemy_distance(context) <= 1
            if currently_in_melee and min_enemy_dist > 2:
                base += 40.0 * profile.self_preservation

    # Origin damage bonus (Thunder Step)
    if action.teleport_origin_effect and context.me.position:
        enemies_at_origin = 0
        for enemy in context.enemies:
            if enemy.position is not None:
                d = context.me.position.distance_to(enemy.position)
                origin_radius_hexes = (action.area_size or 10) // 5
                if d <= origin_radius_hexes:
                    enemies_at_origin += 1
        base += enemies_at_origin * 15.0

    return max(base, 0.0)


def score_shove_action(
    profile: AIProfile,
    context: CombatContext,
    target: CreatureView,
    distance_hexes: int,
) -> tuple[float, str]:
    """Score a Shove action against a specific target.

    Returns (score, choice) where choice is "push" or "prone".

    Shove requires adjacency (distance_hexes <= 1).
    Prone is better when allies are nearby to exploit advantage.
    Push is better for cliff edges, zone control, or separating enemies.
    """
    if distance_hexes > 1:
        return (0.0, "prone")

    # Base score: modest — shove is useful but usually less than a real attack
    base = 20.0 * profile.aggression

    # ── Score prone ────────────────────────────────────────────────
    prone_score = base
    # Prone gives advantage to melee allies — count how many are adjacent to target
    allies_near_target = 0
    for ally in context.allies:
        if ally.position is not None and target.position is not None:
            d = creature_distance(ally, target)
            if d <= 1:
                allies_near_target += 1
    # Also count self (we're adjacent)
    allies_near_target += 1
    prone_score += allies_near_target * 12.0

    # Melee profiles benefit more from prone (advantage on melee attacks)
    if profile.prefers_melee:
        prone_score += 10.0

    # ── Score push ─────────────────────────────────────────────────
    push_score = base
    # Push is useful for repositioning — ranged profiles want enemies away
    if not profile.prefers_melee:
        push_score += 15.0

    # Pick the better choice
    if prone_score >= push_score:
        return (prone_score, "prone")
    return (push_score, "push")


def _generate_upcast_variants(
    base_scored: list[ScoredAction],
    all_actions: list[Action],
    creature,
) -> list[ScoredAction]:
    """Generate upcast variant ScoredActions for spells that support upcasting.

    For each base-level spell scored action, creates additional entries
    for each available higher slot level. Scores are boosted by expected
    extra damage but penalized by opportunity cost of spending a higher slot.
    """
    from arena.combat.upcast import (
        can_upcast,
        get_available_upcast_levels,
        get_spell_level,
    )

    # Build name -> action lookup
    action_map: dict[str, Action] = {}
    for a in all_actions:
        action_map[a.name] = a

    variants: list[ScoredAction] = []
    seen: set[tuple[str, str | None, int]] = set()  # (name, target, level)

    for sa in base_scored:
        action = action_map.get(sa.action_name)
        if action is None or not can_upcast(action):
            continue

        base_level = get_spell_level(action)
        if base_level is None:
            continue

        levels = get_available_upcast_levels(action, creature)
        for lvl in levels:
            if lvl <= base_level:
                continue
            key = (sa.action_name, sa.target_id, lvl)
            if key in seen:
                continue
            seen.add(key)

            levels_above = lvl - base_level
            # Bonus: ~8 points per extra spell level (roughly 1d6 avg = 3.5 dmg)
            upcast_bonus = levels_above * 8.0
            # Opportunity cost: higher slots are more valuable
            slot_penalty = levels_above * 3.0
            # Reduced penalty when multiple slots remain at this level
            slots_remaining = getattr(creature, "class_resources", {}).get(
                f"spell_slot_{lvl}", 0
            )
            if slots_remaining > 1:
                slot_penalty *= 0.5

            adjusted_score = sa.score + upcast_bonus - slot_penalty

            variants.append(ScoredAction(
                action_name=sa.action_name,
                target_id=sa.target_id,
                score=adjusted_score,
                action_category=sa.action_category,
                description=f"{sa.action_name} (slot {lvl}) -> {sa.target_id or 'self'}",
                target_hex=sa.target_hex,
                cast_level=lvl,
            ))

    return variants


def generate_scored_actions(
    profile: AIProfile,
    context: CombatContext,
    actions: list[Action],
    bonus_actions: list[Action],
    can_use_action: bool,
    can_use_bonus_action: bool,
    can_twf: bool,
    reachable_enemies: dict[str, int],  # enemy_id -> distance in hexes
    creature=None,  # Creature object for upcast slot availability
) -> list[ScoredAction]:
    """Generate and score all possible action+target combinations.

    Returns a list of ScoredAction sorted by score descending.
    """
    scored: list[ScoredAction] = []

    if can_use_action:
        # ── Attack actions ───────────────────────────────────────────
        for action in actions:
            if not action.attack:
                continue
            if not check_use_condition(action.ai_use_condition, context):
                continue

            for enemy in context.enemies:
                dist = reachable_enemies.get(enemy.creature_id)
                if dist is None and enemy.position and context.me.position:
                    dist = creature_distance(context.me, enemy)
                if dist is None:
                    continue

                s = score_attack_action(action, profile, context, enemy, dist)
                scored.append(ScoredAction(
                    action_name=action.name,
                    target_id=enemy.creature_id,
                    score=s,
                    action_category="attack",
                    description=f"{action.name} -> {enemy.creature_id}",
                ))

        # ── Healing actions ──────────────────────────────────────────
        for action in actions:
            if not action.healing:
                continue
            if not check_use_condition(action.ai_use_condition, context):
                continue
            # Heal self
            if context.me.hp_percent < 1.0:
                s = score_healing_action(action, profile, context, context.me)
                scored.append(ScoredAction(
                    action_name=action.name,
                    target_id=context.me.creature_id,
                    score=s,
                    action_category="heal",
                    description=f"{action.name} (self)",
                ))
            # Heal allies
            for ally in context.allies:
                if ally.hp_percent < 1.0:
                    s = score_healing_action(action, profile, context, ally)
                    scored.append(ScoredAction(
                        action_name=action.name,
                        target_id=ally.creature_id,
                        score=s,
                        action_category="heal",
                        description=f"{action.name} -> {ally.creature_id}",
                    ))

        # ── Effect actions (saving throws / breath weapons) ──────────
        for action in actions:
            # Skip actions already handled (attack or healing)
            if action.attack or action.healing:
                continue
            # Must have a saving throw with damage or conditions
            if not action.saving_throw:
                continue
            has_damage = bool(action.saving_throw.damage_on_fail)
            has_conditions = bool(action.saving_throw.conditions_on_fail)
            if not has_damage and not has_conditions:
                continue
            if not check_use_condition(action.ai_use_condition, context):
                continue

            for enemy in context.enemies:
                dist = reachable_enemies.get(enemy.creature_id)
                if dist is None and enemy.position and context.me.position:
                    dist = creature_distance(context.me, enemy)
                if dist is None:
                    continue

                s = score_effect_action(action, profile, context, enemy, dist)
                scored.append(ScoredAction(
                    action_name=action.name,
                    target_id=enemy.creature_id,
                    score=s,
                    action_category="effect",
                    description=f"{action.name} -> {enemy.creature_id}",
                ))

        # ── Terrain modification actions (no saving throw) ──────────
        for action in actions:
            if action.terrain_modification is None:
                continue
            # Skip if already handled by the effect category
            # (has saving throw with damage or conditions)
            if action.saving_throw and (
                bool(action.saving_throw.damage_on_fail)
                or bool(action.saving_throw.conditions_on_fail)
            ):
                continue
            if action.attack or action.healing:
                continue
            if not check_use_condition(action.ai_use_condition, context):
                continue

            # Score once, targeting the centroid of enemies
            s = score_effect_action(action, profile, context, context.enemies[0], 0)
            # Use the nearest enemy's position as the target hex
            best_enemy = context.enemies[0]
            best_pos = best_enemy.position
            if best_pos is not None:
                scored.append(ScoredAction(
                    action_name=action.name,
                    target_id=best_enemy.creature_id,
                    target_hex=(best_pos.q, best_pos.r),
                    score=s,
                    action_category="terrain",
                    description=f"{action.name} near {best_enemy.creature_id}",
                ))

        # ── Teleport actions ─────────────────────────────────────────
        for action in actions:
            if action.teleport_range is None:
                continue
            if not check_use_condition(action.ai_use_condition, context):
                continue

            result = _score_best_teleport(action, profile, context, "teleport")
            if result is not None:
                scored.append(result)

        # ── Standard actions ─────────────────────────────────────────
        for std_name in ("dash", "disengage", "dodge", "hide"):
            s = score_standard_action(std_name, profile, context)
            scored.append(ScoredAction(
                action_name=std_name,
                target_id=None,
                score=s,
                action_category="standard",
                description=std_name.capitalize(),
            ))

        # ── Shove (universal tactic) ─────────────────────────────────
        for enemy in context.enemies:
            dist = reachable_enemies.get(enemy.creature_id)
            if dist is None and enemy.position and context.me.position:
                dist = creature_distance(context.me, enemy)
            if dist is None:
                continue
            shove_score, shove_choice = score_shove_action(
                profile, context, enemy, dist
            )
            if shove_score > 0:
                scored.append(ScoredAction(
                    action_name=f"shove:{shove_choice}",
                    target_id=enemy.creature_id,
                    score=shove_score,
                    action_category="shove",
                    description=f"Shove ({shove_choice}) -> {enemy.creature_id}",
                ))

    # ── Bonus action: TWF ────────────────────────────────────────────
    if can_twf and can_use_bonus_action:
        for enemy in context.enemies:
            dist = reachable_enemies.get(enemy.creature_id)
            if dist is None and enemy.position and context.me.position:
                dist = creature_distance(context.me, enemy)
            if dist is not None and dist <= 1:  # must be adjacent for melee
                s = 40.0 * profile.aggression  # bonus attack is always decent
                scored.append(ScoredAction(
                    action_name="offhand",
                    target_id=enemy.creature_id,
                    score=s,
                    action_category="bonus_attack",
                    description=f"Off-hand -> {enemy.creature_id}",
                ))

    # ── Bonus action: Teleport (e.g. Misty Step) ─────────────────
    if can_use_bonus_action:
        for action in bonus_actions:
            if action.teleport_range is None:
                continue
            if not check_use_condition(action.ai_use_condition, context):
                continue

            result = _score_best_teleport(
                action, profile, context, "bonus_teleport"
            )
            if result is not None:
                scored.append(result)

    # ── Upcast variants ──────────────────────────────────────────────
    if creature is not None:
        scored.extend(_generate_upcast_variants(scored, actions + bonus_actions, creature))

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored


def check_use_condition(condition_str: str | None, context: CombatContext) -> bool:
    """Evaluate an action's ai_use_condition against the current context.

    Safely evaluates simple conditions like "self.hp_percent < 50",
    "is_in_melee", "enemies_in_range >= 2", etc.

    Returns True if no condition is set (always usable).
    """
    if not condition_str:
        return True

    try:
        expr = condition_str.strip()

        # ── Replace known variables with runtime values ──────────────
        # HP
        expr = expr.replace("self.hp_percent", str(context.me.hp_percent * 100))
        expr = expr.replace("hp_percent", str(context.me.hp_percent * 100))

        # Melee check
        min_dist = _min_enemy_distance(context)
        expr = expr.replace("is_in_melee", str(min_dist <= 1))
        expr = expr.replace("distance_to_nearest_enemy", str(min_dist))

        # Enemy/ally counts (treat "enemies_in_range" as total enemies for now)
        expr = expr.replace("enemies_in_range", str(len(context.enemies)))
        expr = expr.replace("num_enemies", str(len(context.enemies)))
        expr = expr.replace("num_allies", str(len(context.allies)))

        # Ally health
        wounded_allies = sum(
            1 for a in context.allies if a.hp_percent < 1.0
        )
        expr = expr.replace("allies_wounded", str(wounded_allies))

        # Ally HP average
        if context.allies:
            ally_hp_avg = sum(a.hp_percent for a in context.allies) / len(context.allies)
            ally_hp_pct = ally_hp_avg * 100
        else:
            ally_hp_pct = 100.0
        expr = expr.replace("ally_hp_percent", str(ally_hp_pct))

        # Bloodied
        expr = expr.replace("is_bloodied", str(context.me.hp_percent < 0.5))

        # Only allow safe characters: digits, whitespace, comparisons,
        # boolean operators (and/or/not), True/False, parentheses, dots
        if re.match(r'^[\d\s.<>=!a-zA-Z_()]+$', expr):
            # Second safety check: must not contain dangerous patterns
            dangerous = {"import", "exec", "eval", "open", "print",
                         "system", "write", "read", "file", "class",
                         "def", "lambda", "getattr", "setattr", "__"}
            tokens = re.findall(r'[a-zA-Z_]+', expr)
            safe_tokens = {"True", "False", "and", "or", "not"}
            if all(t in safe_tokens for t in tokens):
                return bool(eval(expr))  # noqa: S307
    except Exception:
        pass

    return True  # default to allowing the action


def estimate_damage(action: Action) -> float:
    """Estimate average damage for an attack action (dice average + bonus).

    Used for scoring without rolling dice.
    """
    if action.attack is None:
        return 0.0

    total = 0.0
    for dr in action.attack.damage:
        total += _dice_average(dr.dice) + dr.bonus
    return total


def estimate_save_damage(action: Action) -> float:
    """Estimate average damage for a saving-throw effect action.

    Assumes ~50% chance to fail the save (rough heuristic).
    For "half" damage on success, effective = avg * 0.75.
    For "none" on success, effective = avg * 0.5.
    """
    if action.saving_throw is None or not action.saving_throw.damage_on_fail:
        return 0.0

    total = 0.0
    for dr in action.saving_throw.damage_on_fail:
        total += _dice_average(dr.dice) + dr.bonus

    # Adjust for save probability heuristic
    if action.saving_throw.damage_on_success == "half":
        return total * 0.75  # 50% full + 50% half
    elif action.saving_throw.damage_on_success == "none":
        return total * 0.5  # 50% full + 50% zero
    return total * 0.5  # default: assume 50% chance


def _score_best_teleport(
    action: Action,
    profile: AIProfile,
    context: CombatContext,
    category: str,
) -> ScoredAction | None:
    """Find the best destination hex and score a teleport action.

    Generates candidate destinations, scores each, and returns the best
    as a ScoredAction (or None if no viable destination).

    Args:
        action: The teleport action to evaluate.
        profile: AI behavior profile.
        context: Current combat context.
        category: "teleport" for main actions, "bonus_teleport" for bonus actions.
    """
    from arena.grid.coordinates import HexCoord

    if context.me.position is None:
        return None

    tp_range_hexes = action.teleport_range // 5
    me_pos = context.me.position
    best_tp_score = -1.0
    best_tp_dest: tuple[int, int] | None = None

    # ── Collect occupied hexes (filter these out of candidates) ──
    occupied: set[tuple[int, int]] = set()
    for cv in context.all_combatants:
        if cv.position is not None:
            occupied.add((cv.position.q, cv.position.r))
            # For Large+ creatures, also mark footprint neighbours
            if cv.size != CreatureSize.MEDIUM and cv.size != CreatureSize.SMALL:
                for nb in cv.position.neighbors():
                    occupied.add((nb.q, nb.r))

    # ── Build candidate destinations ──────────────────────────────
    candidates: set[tuple[int, int]] = set()

    # Nearby hexes: walk outward through neighbor chains
    for d in range(1, min(tp_range_hexes + 1, 8)):
        for n in me_pos.neighbors():
            coord = HexCoord(n.q, n.r)
            for _ in range(d - 1):
                nbs = coord.neighbors()
                if nbs:
                    coord = nbs[0]
            candidates.add((coord.q, coord.r))

    # Hexes adjacent to enemies (for approach / melee teleports)
    for enemy in context.enemies:
        if enemy.position:
            for nb in enemy.position.neighbors():
                if me_pos.distance_to(nb) <= tp_range_hexes:
                    candidates.add((nb.q, nb.r))

    # Hexes away from enemies (for escape teleports)
    # Project along retreat vectors to find safe positions
    if context.enemies and not profile.prefers_melee:
        for enemy in context.enemies:
            if enemy.position:
                dq = me_pos.q - enemy.position.q
                dr = me_pos.r - enemy.position.r
                for mult in range(2, min(tp_range_hexes + 1, 10)):
                    cq = me_pos.q + dq * mult // 2
                    cr = me_pos.r + dr * mult // 2
                    if 0 <= cq < context.grid_width and 0 <= cr < context.grid_height:
                        if me_pos.distance_to(HexCoord(cq, cr)) <= tp_range_hexes:
                            candidates.add((cq, cr))

    # Remove occupied hexes — teleport must land on an empty hex
    candidates -= occupied

    # ── Score each candidate ──────────────────────────────────────
    for cand in candidates:
        s = score_teleport_action(action, profile, context, cand)
        if s > best_tp_score:
            best_tp_score = s
            best_tp_dest = cand

    if best_tp_dest is not None and best_tp_score > 0:
        return ScoredAction(
            action_name=action.name,
            target_id=None,
            score=best_tp_score,
            action_category=category,
            description=f"{action.name} ({category.replace('_', ' ')})",
            target_hex=best_tp_dest,
        )
    return None


# ── Private helpers ──────────────────────────────────────────────────


class _ConditionProxy:
    """Safe proxy for use in ai_use_condition evaluation."""

    def __init__(self, me: CreatureView):
        self.hp_percent = me.hp_percent * 100  # 0-100


def _dice_average(expr: str) -> float:
    """Parse a dice expression like '2d6' and return the average roll."""
    match = re.match(r"(\d*)d(\d+)", expr.strip().lower())
    if not match:
        return 0.0
    count = int(match.group(1)) if match.group(1) else 1
    sides = int(match.group(2))
    return count * (sides + 1) / 2.0


def _min_enemy_distance(context: CombatContext) -> int:
    """Get the minimum distance to any enemy, in hexes (footprint-aware)."""
    if not context.enemies or context.me.position is None:
        return 999
    min_d = 999
    for e in context.enemies:
        if e.position is not None:
            d = creature_distance(context.me, e)
            if d < min_d:
                min_d = d
    return min_d


def _get_action_range_hexes(action: Action) -> int:
    """Get the effective range of an action in hexes."""
    if action.attack:
        if action.attack.range_normal:
            return action.attack.range_normal // 5
        return action.attack.reach // 5
    return action.range // 5
