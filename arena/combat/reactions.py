"""Reaction system and opportunity attacks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from arena.models.character import Creature
from arena.models.actions import Action
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.combat.actions import resolve_attack, ActionResult
from arena.combat.events import CombatEvent, CombatEventType
from arena.combat.condition_effects import can_take_actions

if TYPE_CHECKING:
    from arena.combat.manager import Combatant


def check_opportunity_attacks(
    mover_id: str,
    from_pos: HexCoord,
    to_pos: HexCoord,
    combatants: dict[str, Combatant],
    reaction_used: dict[str, bool],
    is_disengaging: bool,
) -> list[tuple[str, Combatant, Action]]:
    """Check which creatures can make opportunity attacks against the mover.

    An opportunity attack triggers when a creature leaves the reach of a
    hostile creature, unless the mover used Disengage.

    Args:
        mover_id: ID of the moving creature.
        from_pos: Position the mover is leaving.
        to_pos: Position the mover is moving to.
        combatants: All combatants in combat.
        reaction_used: Dict of creature_id -> bool tracking reaction usage.
        is_disengaging: Whether the mover used Disengage.

    Returns:
        List of (reactor_id, reactor_combatant, melee_attack) tuples for
        creatures that can make opportunity attacks.
    """
    if is_disengaging:
        return []

    mover = combatants.get(mover_id)
    if mover is None:
        return []

    attackers = []

    for cid, combatant in combatants.items():
        if cid == mover_id:
            continue
        if combatant.position is None:
            continue
        if not combatant.creature.is_conscious:
            continue
        if not can_take_actions(combatant.creature):
            continue

        # Check if reaction already used
        if reaction_used.get(cid, False):
            continue

        # Must be hostile (different team)
        if combatant.team == mover.team:
            continue

        # Check if mover is leaving this creature's reach
        reach_hexes = 1  # Default 5ft reach = 1 hex

        # Find the creature's melee attack for reach
        melee_action = _get_melee_attack(combatant.creature)
        if melee_action and melee_action.attack:
            reach_hexes = melee_action.attack.reach // 5

        # Use footprint-aware distance for multi-hex creatures
        from arena.grid.footprint import min_distance_between
        dist_from = min_distance_between(
            combatant.position, combatant.creature.size,
            from_pos, mover.creature.size,
        )
        dist_to = min_distance_between(
            combatant.position, combatant.creature.size,
            to_pos, mover.creature.size,
        )

        # Opportunity attack triggers when moving OUT of reach
        if dist_from <= reach_hexes and dist_to > reach_hexes:
            if melee_action:
                attackers.append((cid, combatant, melee_action))

    return attackers


def execute_opportunity_attack(
    reactor_id: str,
    reactor: Combatant,
    target_id: str,
    target: Combatant,
    action: Action,
    grid: HexGrid,
    reaction_used: dict[str, bool],
    combatants: dict[str, Combatant] | None = None,
) -> ActionResult:
    """Execute an opportunity attack as a reaction.

    Consumes the reactor's reaction for this round.

    Args:
        reactor_id: ID of the creature making the opportunity attack.
        reactor: The combatant making the attack.
        target_id: ID of the creature being attacked.
        target: The combatant being attacked.
        action: The melee attack action to use.
        grid: The hex grid.
        reaction_used: Reaction tracking dict to update.
        combatants: All combatants, for concentration cleanup on damage.

    Returns:
        ActionResult with events from the attack.
    """
    # Mark reaction as used
    reaction_used[reactor_id] = True

    # Create a reaction announcement event
    announce = CombatEvent(
        event_type=CombatEventType.REACTION,
        message=(
            f"{reactor.creature.name} makes an opportunity attack "
            f"against {target.creature.name}!"
        ),
        source_id=reactor_id,
        target_id=target_id,
        details={"reaction_type": "opportunity_attack"},
    )

    # Resolve the attack
    result = resolve_attack(
        attacker=reactor.creature,
        attacker_id=reactor_id,
        target=target.creature,
        target_id=target_id,
        action=action,
        grid=grid,
        combatants=combatants,
        attacker_pos=reactor.position,
        target_pos=target.position,
    )

    # Prepend the announcement
    result.events.insert(0, announce)

    return result


def _get_melee_attack(creature: Creature) -> Action | None:
    """Find the first melee weapon attack action on a creature."""
    for action in creature.actions:
        if action.attack and action.attack.attack_type.startswith("melee"):
            return action
    return None
