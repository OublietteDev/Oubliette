"""Combat perception — snapshot of battlefield state for AI decisions.

All AI scoring functions consume the immutable CombatContext rather than
reaching into the mutable CombatManager directly.  This makes AI logic
pure-functional and easy to unit-test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from arena.combat.stat_modifiers import (
    get_effective_armor_class,
    get_effective_speed,
    has_sculpt_spells,
)
from arena.grid.coordinates import HexCoord
from arena.models.character import CreatureSize
from arena.models.conditions import Condition

if TYPE_CHECKING:
    from arena.combat.manager import CombatManager, Combatant


@dataclass(frozen=True)
class CreatureView:
    """Immutable view of a single combatant for AI evaluation."""

    creature_id: str
    team: str
    position: HexCoord | None
    hp_percent: float
    is_conscious: bool
    armor_class: int
    has_concentration: bool
    is_spellcaster: bool
    condition_names: tuple[str, ...]
    max_hit_points: int
    current_hit_points: int
    speed: int  # walking speed in feet
    actions_count: int  # number of available actions (for threat heuristic)
    size: CreatureSize = CreatureSize.MEDIUM
    has_sculpt_spells: bool = False  # Evocation wizard: own AoE spares allies


@dataclass(frozen=True)
class CombatContext:
    """Immutable snapshot of the battlefield for AI decisions.

    All AI scoring functions take this as input, making them
    pure functions that are easy to test.
    """

    me: CreatureView
    allies: tuple[CreatureView, ...]  # same team, alive, excludes self
    enemies: tuple[CreatureView, ...]  # hostile team, alive
    all_combatants: tuple[CreatureView, ...]  # everyone including self
    grid_width: int
    grid_height: int
    round_number: int
    remaining_movement: int  # feet left this turn
    has_used_action: bool
    has_used_bonus_action: bool


def creature_distance(a: CreatureView, b: CreatureView) -> int:
    """Footprint-aware distance between two creatures.

    Returns minimum hex distance between any hex of *a* and any hex of *b*.
    Falls back to simple ``distance_to`` for single-hex creatures.
    """
    if a.position is None or b.position is None:
        return 999
    from arena.grid.footprint import min_distance_between
    return min_distance_between(a.position, a.size, b.position, b.size)


def pos_to_creature_distance(
    pos: HexCoord, creature: CreatureView
) -> int:
    """Distance from a single hex position to a creature's footprint."""
    if creature.position is None:
        return 999
    from arena.grid.footprint import min_distance_between
    return min_distance_between(
        pos, CreatureSize.MEDIUM, creature.position, creature.size
    )


def build_context(manager: CombatManager) -> CombatContext | None:
    """Build a CombatContext snapshot from the current combat state.

    Returns None if there is no active combatant or no grid.
    """
    combatant = manager.active_combatant
    if combatant is None or manager.grid is None:
        return None

    me_view = _make_creature_view(combatant)

    allies: list[CreatureView] = []
    enemies: list[CreatureView] = []
    all_views: list[CreatureView] = [me_view]

    for cid, c in manager.combatants.items():
        if cid == combatant.creature_id:
            continue

        view = _make_creature_view(c)
        all_views.append(view)

        if not c.creature.is_conscious:
            continue

        if c.team == combatant.team:
            allies.append(view)
        else:
            enemies.append(view)

    return CombatContext(
        me=me_view,
        allies=tuple(allies),
        enemies=tuple(enemies),
        all_combatants=tuple(all_views),
        grid_width=manager.grid.width,
        grid_height=manager.grid.height,
        round_number=manager.initiative.round_number,
        remaining_movement=manager.movement.remaining_movement,
        has_used_action=manager.turn_resources.has_used_action,
        has_used_bonus_action=manager.turn_resources.has_used_bonus_action,
    )


def _make_creature_view(combatant: Combatant) -> CreatureView:
    """Extract an immutable view from a mutable Combatant."""
    creature = combatant.creature

    # Detect spellcaster heuristically:
    # Has any ranged_spell or melee_spell attack, OR has spell_slots
    is_caster = False
    for action in creature.actions:
        if action.attack and action.attack.attack_type in (
            "ranged_spell",
            "melee_spell",
        ):
            is_caster = True
            break

    if not is_caster:
        # Check for spell_slots (PlayerCharacter only)
        spell_slots = getattr(creature, "spell_slots", None)
        if spell_slots:
            is_caster = True

    # Check for concentration
    has_concentration = any(
        ac.condition == Condition.CONCENTRATING
        for ac in creature.active_conditions
    )

    condition_names = tuple(
        ac.condition.value for ac in creature.active_conditions
    )

    return CreatureView(
        creature_id=combatant.creature_id,
        team=combatant.team,
        position=combatant.position,
        hp_percent=creature.hp_percent,
        is_conscious=creature.is_conscious,
        armor_class=get_effective_armor_class(creature),
        has_concentration=has_concentration,
        is_spellcaster=is_caster,
        condition_names=condition_names,
        max_hit_points=creature.max_hit_points,
        current_hit_points=creature.current_hit_points or 0,
        speed=get_effective_speed(creature),
        actions_count=len(creature.actions),
        size=creature.size,
        has_sculpt_spells=has_sculpt_spells(creature),
    )
