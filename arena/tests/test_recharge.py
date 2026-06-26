"""D-MON-2: Recharge abilities.

A spent recharge ability (recharge_min set, current_uses == 0) rolls a d6 at the
start of the creature's turn and comes back on a result >= recharge_min. The
uses_per_rest=1 gate is the spent/available flag.
"""

from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager
from arena.combat.recharge import process_recharge_start_of_turn
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action, ActionType, DamageRoll, DamageType, SavingThrowEffect, TargetType,
)
from arena.models.character import Creature
from arena.models.encounter import CombatantEntry, Encounter
from arena.models.monster import Monster


def _breath(current_uses: int = 1, recharge_min: int = 5) -> Action:
    return Action(
        name="Fire Breath", description="A cone of fire.",
        action_type=ActionType.ACTION, target_type=TargetType.ONE_CREATURE,
        recharge_min=recharge_min, uses_per_rest=1, current_uses=current_uses,
        saving_throw=SavingThrowEffect(
            ability="dexterity", dc=15,
            damage_on_fail=[DamageRoll(dice="2d6", damage_type=DamageType.FIRE)],
            damage_on_success="half"),
    )


def _dragon_with(action: Action) -> Monster:
    return Monster(name="Red Dragon", max_hit_points=200,
                   ability_scores=AbilityScores(), actions=[action])


def test_spent_recharge_refreshes_on_high_roll():
    breath = _breath(current_uses=0)
    with patch("arena.combat.recharge.roll_die", return_value=5):
        events = process_recharge_start_of_turn(_dragon_with(breath), "d1")
    assert breath.current_uses == 1
    assert any(e.details.get("recharge") for e in events)


def test_spent_recharge_stays_spent_on_low_roll():
    breath = _breath(current_uses=0)
    with patch("arena.combat.recharge.roll_die", return_value=4):
        events = process_recharge_start_of_turn(_dragon_with(breath), "d1")
    assert breath.current_uses == 0
    assert events == []


def test_charged_ability_is_not_rerolled():
    breath = _breath(current_uses=1)
    with patch("arena.combat.recharge.roll_die", return_value=6) as rd:
        events = process_recharge_start_of_turn(_dragon_with(breath), "d1")
    assert breath.current_uses == 1
    rd.assert_not_called()
    assert events == []


def test_non_recharge_action_ignored():
    bite = Action(name="Bite", description="bite", action_type=ActionType.ACTION)
    with patch("arena.combat.recharge.roll_die", return_value=6):
        events = process_recharge_start_of_turn(_dragon_with(bite), "d1")
    assert events == []


def test_recharge_fires_at_turn_start_through_manager():
    """The spent breath of a dragon refreshes when the manager begins its turn."""
    caster = Creature(
        name="Caster", max_hit_points=30, current_hit_points=30,
        ability_scores=AbilityScores(), is_player_controlled=True, actions=[])
    dragon = Monster(
        name="Red Dragon", max_hit_points=200, current_hit_points=200,
        ability_scores=AbilityScores(), is_player_controlled=False,
        actions=[_breath(current_uses=0)])  # breath already spent
    encounter = Encounter(
        name="R", grid_width=10, grid_height=10, combatants=[
            CombatantEntry(creature_id="caster", creature_data=caster,
                           team="player", starting_position=(4, 4)),
            CombatantEntry(creature_id="dragon", creature_data=dragon,
                           team="enemy", starting_position=(6, 6)),
        ])
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10]):
        cm.roll_initiative()
    cm.begin_combat()  # caster (init 20) acts first
    # End the caster's turn → the dragon's turn begins → recharge roll fires.
    with patch("arena.combat.recharge.roll_die", return_value=6):
        cm.end_turn()
    dragon_key = next(k for k, v in cm.combatants.items() if v.team == "enemy")
    breath = next(a for a in cm.combatants[dragon_key].creature.actions
                  if a.name == "Fire Breath")
    assert breath.current_uses == 1
