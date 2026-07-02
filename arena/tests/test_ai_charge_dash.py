"""AI planning fixes from OublietteDev's 2026-07-02 playtest.

1. Dash order: the planner used to emit MOVE → DASH → END, so the
   movement Dash grants was never spent (action paid, budget wasted).
   Now Dash is planned before the walk and the walk is computed with
   the doubled budget.

2. Charge awareness: a move-then-strike attacker (Charge/Pounce,
   OnHitRider.requires_charge_ft) used to creep adjacent over multi-
   turn approaches, guaranteeing the rider never fired (the engine
   gate needs 20+ ft closed in the turn of the hit). When such a
   creature can't attack this turn anyway, it now holds at charge
   distance so next turn is a full run-in.
"""

from pathlib import Path
from unittest.mock import patch

from arena.ai.controller import AIController, TurnStepType
from arena.combat.manager import CombatManager
from arena.grid.coordinates import HexCoord
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, ActionType, Attack, DamageRoll, DamageType
from arena.models.character import (
    Creature, CreatureSize, Feature, OnHitRider, RiderTrigger,
)
from arena.models.encounter import CombatantEntry, Encounter
from arena.models.monster import Monster


# ── Helpers ──────────────────────────────────────────────────────────


def _tusk():
    return Action(
        name="Tusk", description="x", action_type=ActionType.ACTION,
        attack=Attack(
            name="Tusk", attack_type="melee_weapon", ability="strength",
            reach=5,
            damage=[DamageRoll(dice="1d6", damage_type=DamageType.SLASHING,
                               ability_modifier="strength")],
        ),
    )


def _charge_rider():
    return OnHitRider(
        trigger=RiderTrigger.AUTOMATIC, once_per_turn=True,
        requires_melee=True, requires_charge_ft=20,
        damage_dice="1d6", damage_type="slashing",
        save_ability="strength", save_dc_fixed=11, condition_on_fail="prone",
        condition_duration="indefinite", condition_save_to_end=False,
    )


def _monster(actions=None, charge=False, size=CreatureSize.MEDIUM):
    special = []
    if charge:
        special = [Feature(name="Charge", description="x",
                           on_hit_rider=_charge_rider())]
    return Monster(
        name="Beast", max_hit_points=40, armor_class=13,  # default speed: 30 ft
        size=size,
        ability_scores=AbilityScores(strength=16, dexterity=12),
        proficiency_bonus=2, is_player_controlled=False,
        ai_profile="berserker",  # melee, aggressive, never flees
        actions=actions if actions is not None else [],
        special_abilities=special,
    )


def _player():
    return Creature(
        name="Hero", max_hit_points=30, armor_class=14,
        ability_scores=AbilityScores(strength=14, dexterity=12),
        proficiency_bonus=2, is_player_controlled=True,
        actions=[_tusk()],
    )


def _start(beast, beast_pos, hero_pos):
    enc = Encounter(name="AI test", grid_width=20, grid_height=12, combatants=[
        CombatantEntry(creature_id="beast", creature_data=beast,
                       team="enemy", starting_position=beast_pos),
        CombatantEntry(creature_id="hero", creature_data=_player(),
                       team="player", starting_position=hero_pos),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", return_value=10):
        cm.roll_initiative()
    cm.begin_combat()
    for _ in range(len(cm.combatants) + 1):
        if cm.active_combatant and cm.active_combatant.creature_id == "beast":
            break
        cm.end_turn()
    assert cm.active_combatant.creature_id == "beast"
    return cm


def _plan(cm):
    return AIController(randomness=0.0).plan_turn(cm)


def _step_types(plan):
    return [s.step_type for s in plan.steps]


def _move_target(plan):
    move = next(s for s in plan.steps if s.step_type == TurnStepType.MOVE)
    return HexCoord(move.target_hex[0], move.target_hex[1])


# ── Fix 1: Dash is planned before the walk ───────────────────────────


def test_dash_planned_before_move():
    """An actionless melee monster far from its enemy dashes FIRST,
    then walks — the old plan walked, dashed, and wasted the bonus."""
    cm = _start(_monster(actions=[]), beast_pos=(0, 5), hero_pos=(10, 5))
    plan = _plan(cm)

    types = _step_types(plan)
    assert TurnStepType.STANDARD_ACTION in types
    assert TurnStepType.MOVE in types
    assert (types.index(TurnStepType.STANDARD_ACTION)
            < types.index(TurnStepType.MOVE))


def test_dash_walk_uses_extended_budget():
    """The walk destination is computed with base + dash movement:
    30 ft speed = 6 hexes, but the plan reaches adjacency 9 hexes out."""
    cm = _start(_monster(actions=[]), beast_pos=(0, 5), hero_pos=(10, 5))
    plan = _plan(cm)

    dest = _move_target(plan)
    hero = HexCoord(10, 5)
    assert dest.distance_to(hero) <= 1  # unreachable on the base budget
    assert HexCoord(0, 5).distance_to(dest) > 6  # walked past base speed


def test_dash_movement_actually_spent_on_execution():
    """End-to-end: executing the plan moves the beast beyond its base
    speed (the dash budget is consumed, not stranded)."""
    from arena.ai.executor import execute_step

    cm = _start(_monster(actions=[]), beast_pos=(0, 5), hero_pos=(10, 5))
    plan = _plan(cm)
    for step in plan.steps:
        if step.step_type == TurnStepType.END_TURN:
            break
        execute_step(step, cm)

    final = cm.combatants["beast"].position
    assert HexCoord(0, 5).distance_to(final) > 6


# ── Fix 3 (2026-07-02): Dash must not outbid a reachable attack ──────


def test_charger_attacks_now_instead_of_dashing_to_the_line():
    """OublietteDev's 'I never see a charge' report: at 6 hexes out with 40 ft
    of speed the boar's guaranteed charge turn was spent Dashing to the
    hold line (Dash 48 vs Tusk 47), handing the player a turn to close
    the gap and deny the run-up for the rest of the fight. A reachable
    target must outrank Dash."""
    beast = _monster(actions=[_tusk()], charge=True)
    beast.speed["walk"] = 40  # 8 hexes: adjacency at dist 6 is reachable
    cm = _start(beast, beast_pos=(3, 5), hero_pos=(9, 5))
    plan = _plan(cm)

    types = _step_types(plan)
    assert TurnStepType.EXECUTE_ATTACK in types
    dest = _move_target(plan)
    assert dest.distance_to(HexCoord(9, 5)) <= 1  # full run-in, rider arms


def test_plain_melee_monster_attacks_instead_of_dashing_when_reachable():
    """Same bug without the charge rider: any melee monster within
    (speed + reach) should swing this turn, not Dash past the enemy's
    face and attack a round late."""
    cm = _start(_monster(actions=[_tusk()], charge=False),
                beast_pos=(4, 5), hero_pos=(9, 5))  # 5 out, 6 hexes speed
    plan = _plan(cm)

    types = _step_types(plan)
    assert TurnStepType.EXECUTE_ATTACK in types
    assert TurnStepType.STANDARD_ACTION not in types


# ── Fix 2: chargers hold at charge distance ──────────────────────────


def test_charger_holds_instead_of_creeping():
    """A charger that can't reach its target this turn stops at the
    charge line (5 hexes: 20 ft run-up + attack from reach 1) instead
    of creeping to 3 hexes — from 3 out, next turn's hit can never
    close 20 ft and the charge would silently never fire."""
    cm = _start(_monster(actions=[_tusk()], charge=True),
                beast_pos=(0, 5), hero_pos=(9, 5))
    plan = _plan(cm)

    dest = _move_target(plan)
    assert dest.distance_to(HexCoord(9, 5)) >= 5


def test_charger_attacks_when_target_reachable():
    """The hold must NOT fire when the charger can reach and hit this
    turn — closing from 5 hexes out both attacks AND procs the charge."""
    cm = _start(_monster(actions=[_tusk()], charge=True),
                beast_pos=(4, 5), hero_pos=(9, 5))
    plan = _plan(cm)

    assert TurnStepType.EXECUTE_ATTACK in _step_types(plan)
    dest = _move_target(plan)
    assert dest.distance_to(HexCoord(9, 5)) <= 1


def test_dashing_charger_holds_line():
    """A dashing charger could land adjacent on the doubled budget, but
    the action is spent — parking adjacent kills next turn's charge, so
    it stops at the line."""
    cm = _start(_monster(actions=[], charge=True),
                beast_pos=(0, 5), hero_pos=(14, 5))
    plan = _plan(cm)

    types = _step_types(plan)
    assert TurnStepType.STANDARD_ACTION in types  # it does dash
    dest = _move_target(plan)
    assert dest.distance_to(HexCoord(14, 5)) >= 5


def test_charger_inside_line_walks_in_and_attacks():
    """OublietteDev's triceratops freeze (2026-07-02): a charger that STARTS
    inside the charge line can never charge (no run-up exists), so the
    hold must disengage — old behavior penalized every closer hex and
    'stand still' won, leaving the beast frozen and attacking air."""
    cm = _start(_monster(actions=[_tusk()], charge=True),
                beast_pos=(6, 5), hero_pos=(9, 5))  # 3 hexes = 15 ft out
    plan = _plan(cm)

    types = _step_types(plan)
    assert TurnStepType.MOVE in types  # it moves — no freeze
    assert TurnStepType.EXECUTE_ATTACK in types
    dest = _move_target(plan)
    assert dest.distance_to(HexCoord(9, 5)) <= 1


def test_large_charger_inside_line_does_not_freeze():
    """Same freeze, Large edition: adjacency checks must be footprint-
    aware for the mover (a Large anchor sits 2 hexes out when its body
    is adjacent), or the hold misfires on every big charger."""
    from arena.grid.footprint import min_distance_between

    cm = _start(_monster(actions=[_tusk()], charge=True,
                         size=CreatureSize.LARGE),
                beast_pos=(6, 5), hero_pos=(9, 5))
    plan = _plan(cm)

    types = _step_types(plan)
    assert TurnStepType.MOVE in types
    assert TurnStepType.EXECUTE_ATTACK in types
    dest = _move_target(plan)
    assert min_distance_between(
        dest, CreatureSize.LARGE, HexCoord(9, 5), CreatureSize.MEDIUM,
    ) <= 1


def test_non_charger_still_closes_to_melee():
    """Regression: an ordinary melee monster keeps the old creep-in."""
    cm = _start(_monster(actions=[_tusk()], charge=False),
                beast_pos=(0, 5), hero_pos=(9, 5))
    plan = _plan(cm)

    dest = _move_target(plan)
    # Base budget 6 hexes: it should close as far as it can, well
    # inside the 5-hex line a charger would respect.
    assert dest.distance_to(HexCoord(9, 5)) < 5