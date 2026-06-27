"""Turn executor — bridges TurnPlan steps to CombatManager method calls.

Each TurnStep maps to one CombatManager method call.
No Pygame dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from arena.ai.controller import TurnPlan, TurnStep, TurnStepType
from arena.combat.events import CombatEvent, CombatEventType
from arena.grid.coordinates import HexCoord

if TYPE_CHECKING:
    from arena.combat.manager import CombatManager


def execute_step(step: TurnStep, manager: CombatManager) -> CombatEvent | None:
    """Execute a single TurnStep by calling the appropriate CombatManager method.

    Returns a CombatEvent if something notable happened, or None.
    """
    if step.step_type == TurnStepType.MOVE:
        return _execute_move(step, manager)

    elif step.step_type == TurnStepType.SELECT_ACTION:
        return _execute_select_action(step, manager)

    elif step.step_type == TurnStepType.EXECUTE_ATTACK:
        return _execute_attack(step, manager)

    elif step.step_type == TurnStepType.EXECUTE_EFFECT:
        return _execute_effect(step, manager)

    elif step.step_type == TurnStepType.EXECUTE_TELEPORT:
        return _execute_teleport(step, manager)

    elif step.step_type == TurnStepType.STANDARD_ACTION:
        return _execute_standard_action(step, manager)

    elif step.step_type == TurnStepType.BONUS_ATTACK:
        return _execute_bonus_attack(step, manager)

    elif step.step_type == TurnStepType.EXECUTE_SHOVE:
        return _execute_shove(step, manager)

    elif step.step_type == TurnStepType.END_TURN:
        manager.end_turn()
        return None

    elif step.step_type == TurnStepType.EXECUTE_LEGENDARY:
        return _execute_legendary(step, manager)

    elif step.step_type == TurnStepType.PASS_LEGENDARY:
        manager.pass_legendary_action()
        return None

    elif step.step_type == TurnStepType.EXECUTE_LAIR:
        return _execute_lair(step, manager)

    elif step.step_type == TurnStepType.PASS_LAIR:
        manager.pass_lair_action()
        return None

    elif step.step_type == TurnStepType.LOG_THINKING:
        if step.message:
            event = CombatEvent(
                event_type=CombatEventType.AI_THINKING,
                message=f"[AI] {step.message}",
            )
            manager.log.add(event)
            return event

    return None


def execute_full_plan(
    plan: TurnPlan, manager: CombatManager
) -> list[CombatEvent]:
    """Execute all steps in a TurnPlan sequentially.

    Useful for testing and headless (non-GUI) execution.
    Returns all CombatEvents produced.
    """
    events: list[CombatEvent] = []
    for step in plan.steps:
        event = execute_step(step, manager)
        if event is not None:
            events.append(event)
    return events


# ── Private step handlers ─────────────────────────────────────────


def _execute_move(step: TurnStep, manager: CombatManager) -> CombatEvent | None:
    """Execute a MOVE step."""
    if step.target_hex is None:
        return None

    target = HexCoord(step.target_hex[0], step.target_hex[1])
    combatant = manager.active_combatant
    if combatant is None or combatant.position is None:
        return None

    # Move one hex at a time along a path
    # For simplicity, use the grid's pathfinding to get a path,
    # then move along it step by step
    if manager.grid is None:
        return None

    from arena.grid.pathfinding import find_path

    path = find_path(
        combatant.position, target, manager.grid,
        creature_size=combatant.creature.size,
        creature_id=combatant.creature_id,
        dead_creature_ids=manager.movement.dead_creature_ids,
        blocked_hexes=manager.movement.blocked_hexes,
    )
    if path is None:
        # Try direct move if path not found
        manager.try_move(target)
        return None

    # Walk along the path one hex at a time
    for hex_coord in path:
        if hex_coord == combatant.position:
            continue
        success = manager.try_move(hex_coord)
        if not success:
            break
        # Stop if creature was knocked unconscious by opportunity attack
        if not combatant.creature.is_conscious:
            break

    return None  # Move events are logged by manager.try_move


def _execute_select_action(
    step: TurnStep, manager: CombatManager
) -> CombatEvent | None:
    """Execute a SELECT_ACTION step — find and select the matching action."""
    combatant = manager.active_combatant
    if combatant is None or step.action_name is None:
        return None

    # Search in creature's actions
    for action in combatant.creature.actions:
        if action.name == step.action_name:
            manager.select_action(action, cast_level=step.cast_level)
            return None

    # Search in bonus actions
    for action in combatant.creature.bonus_actions:
        if action.name == step.action_name:
            manager.select_action(action, cast_level=step.cast_level)
            return None

    return None


def _resolve_attack_target(
    manager: CombatManager, target_id: str | None
) -> str | None:
    """Return a valid (living, hostile) target id for the active attacker.

    Multiattack swings are planned up front against one chosen target. If an
    earlier swing drops that target, the remaining swings would otherwise
    flail at a corpse — so when the planned target is gone or unconscious,
    redirect to the nearest living enemy instead of wasting the attack.
    """
    attacker = manager.active_combatant
    if attacker is None:
        return target_id

    planned = manager.combatants.get(target_id) if target_id else None
    if (planned is not None
            and planned.team != attacker.team
            and planned.creature.is_conscious):
        return target_id  # original target still valid

    # Redirect to the nearest conscious enemy.
    best_id: str | None = None
    best_dist = None
    for cid, c in manager.combatants.items():
        if c.team == attacker.team or not c.creature.is_conscious:
            continue
        if c.position is None or attacker.position is None:
            dist = 0
        else:
            dist = attacker.position.distance_to(c.position)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_id = cid
    return best_id


def _execute_attack(
    step: TurnStep, manager: CombatManager
) -> CombatEvent | None:
    """Execute an EXECUTE_ATTACK step with on-hit rider evaluation."""
    target_id = _resolve_attack_target(manager, step.target_id)
    if target_id is None:
        return None

    # Two-phase attack to evaluate riders between hit and damage
    hit_result = manager.execute_attack_hit_check(target_id)
    if hit_result is None:
        return None

    rider_results = None
    damage_reduction = 0
    if hit_result.hit:
        rider_results = _evaluate_ai_riders(hit_result, manager)
        # Evaluate damage reduction reaction on the target
        damage_reduction = manager._evaluate_ai_damage_reduction(
            target_id, hit_result,
        )

    result = manager.complete_attack(
        hit_result, rider_results=rider_results,
        damage_reduction=damage_reduction,
    )
    if result and result.events:
        return result.events[0]
    return None


def _evaluate_ai_riders(
    hit_result, manager: CombatManager,
) -> list | None:
    """AI decides which on-hit riders to activate.

    Returns list of RiderResult or None.
    """
    from arena.combat.riders import resolve_rider, RiderResult, get_available_spell_slots
    from arena.models.character import RiderTrigger

    riders = manager.get_applicable_riders(hit_result)
    if not riders:
        return None

    results: list[RiderResult] = []
    for feature, rider in riders:
        if rider.trigger == RiderTrigger.AUTOMATIC:
            # Always use automatic riders
            rr = resolve_rider(
                feature, rider,
                hit_result.attacker, hit_result.target,
            )
            results.append(rr)
        else:
            # POST_HIT: simple heuristic — use if resources are plentiful
            score = _score_rider_for_ai(rider, hit_result)
            if score > 0:
                slot_level = None
                if rider.resource_type == "spell_slot":
                    # Pick lowest available slot
                    slots = get_available_spell_slots(hit_result.attacker)
                    available = [
                        lvl for lvl, cnt in sorted(slots.items()) if cnt > 0
                    ]
                    if available:
                        # Use highest on crits, lowest otherwise
                        slot_level = (
                            available[-1] if hit_result.critical
                            else available[0]
                        )
                    else:
                        continue  # No slots available

                rr = resolve_rider(
                    feature, rider,
                    hit_result.attacker, hit_result.target,
                    slot_level=slot_level,
                )
                results.append(rr)

    return results if results else None


def _score_rider_for_ai(rider, hit_result) -> float:
    """Simple heuristic for whether the AI should use a POST_HIT rider.

    Returns a positive score to use, 0 or negative to skip.
    """
    score = 5.0  # Base willingness

    # Crits are always worth using riders on (double dice)
    if hit_result.critical:
        score += 10.0

    # Resource conservation: less willing when resources are scarce
    if rider.resource_type:
        resources = getattr(hit_result.attacker, "class_resources", {})
        if rider.resource_type == "spell_slot":
            total_slots = sum(
                v for k, v in resources.items()
                if k.startswith("spell_slot_") and v > 0
            )
            if total_slots <= 1:
                score -= 8.0  # Save last slot for spells
            elif total_slots <= 2:
                score -= 3.0
        else:
            remaining = resources.get(rider.resource_type, 0)
            if remaining <= 1:
                score -= 5.0
            elif remaining <= 2:
                score -= 2.0

    # Save-based riders: less useful against high-save targets
    if rider.save_ability and hit_result.target:
        save_mod = hit_result.target.get_saving_throw_modifier(
            rider.save_ability,
        )
        if save_mod >= 8:
            score -= 4.0  # High save — likely to resist
        elif save_mod >= 5:
            score -= 2.0

    return score


def _execute_standard_action(
    step: TurnStep, manager: CombatManager
) -> CombatEvent | None:
    """Execute a STANDARD_ACTION step (dash, disengage, dodge, hide)."""
    if step.action_name is None:
        return None

    event = manager.execute_standard_action(step.action_name)
    return event


def _execute_effect(
    step: TurnStep, manager: CombatManager
) -> CombatEvent | None:
    """Execute an EXECUTE_EFFECT step (healing, saves, conditions).

    If ``target_hex`` is set (terrain-modification actions), uses
    ``execute_effect_at_hex`` so the effect is placed at the chosen
    hex rather than centred on the caster.
    """
    if step.target_hex is not None:
        from arena.grid.coordinates import HexCoord
        target = HexCoord(step.target_hex[0], step.target_hex[1])
        result = manager.execute_effect_at_hex(target)
        if result and result.events:
            return result.events[0]
        return None

    if step.target_id is None:
        return None

    result = manager.execute_effect(step.target_id)
    if result and result.events:
        return result.events[0]
    return None


def _execute_teleport(
    step: TurnStep, manager: CombatManager,
) -> CombatEvent | None:
    """Execute an EXECUTE_TELEPORT step (teleport caster to destination)."""
    if step.target_hex is None:
        return None

    from arena.grid.coordinates import HexCoord
    target = HexCoord(step.target_hex[0], step.target_hex[1])
    result = manager.execute_teleport(target)
    if result and result.events:
        return result.events[0]

    # Teleport failed — log a diagnostic event so the user can see why
    if result is None:
        event = CombatEvent(
            event_type=CombatEventType.AI_THINKING,
            message=f"[AI] Teleport to ({target.q},{target.r}) failed (invalid destination)",
        )
        manager.log.add(event)
        return event
    return None


def _execute_bonus_attack(
    step: TurnStep, manager: CombatManager
) -> CombatEvent | None:
    """Execute a BONUS_ATTACK (two-weapon fighting) step."""
    if step.target_id is None:
        return None

    result = manager.execute_bonus_action_attack(step.target_id)
    if result and result.events:
        return result.events[0]
    return None


def _execute_legendary(
    step: TurnStep, manager: CombatManager
) -> CombatEvent | None:
    """Execute an EXECUTE_LEGENDARY step."""
    if step.legendary_action is None or step.target_id is None:
        manager.pass_legendary_action()
        return None

    result = manager.execute_legendary_action(step.legendary_action, step.target_id)
    if result and result.events:
        return result.events[0]
    return None


def _execute_shove(
    step: TurnStep, manager: CombatManager,
) -> CombatEvent | None:
    """Execute an EXECUTE_SHOVE step."""
    if step.target_id is None or step.shove_choice is None:
        return None

    result = manager.execute_shove(step.target_id, step.shove_choice)
    if result and result.events:
        return result.events[0]
    return None


def _execute_lair(
    step: TurnStep, manager: CombatManager
) -> CombatEvent | None:
    """Execute an EXECUTE_LAIR step."""
    if step.lair_action is None or step.target_ids is None:
        manager.pass_lair_action()
        return None

    result = manager.execute_lair_action(step.lair_action, step.target_ids)
    if result and result.events:
        return result.events[0]
    return None
