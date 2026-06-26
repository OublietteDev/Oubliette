"""D-MON-1: Legendary Resistance.

A legendary creature may turn a failed save-or-lose into a success a limited
number of times per encounter. DC 100 is unbeatable (max roll 20 + mod), so the
raw save always fails — any success in these tests is LR doing its job.
"""

from pathlib import Path
from unittest.mock import patch

from arena.combat.actions import resolve_saving_throw
from arena.combat.conditions import has_condition
from arena.combat.manager import CombatManager
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, ActionType, SavingThrowEffect, TargetType
from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.models.encounter import CombatantEntry, Encounter
from arena.models.monster import Monster


def _dragon(count: int = 3) -> Monster:
    return Monster(
        name="Adult Red Dragon", max_hit_points=256,
        ability_scores=AbilityScores(), legendary_resistance_count=count,
    )


def test_lr_converts_failed_save_when_eligible():
    dragon = _dragon()
    success, event = resolve_saving_throw(
        dragon, "d1", "wisdom", 100, legendary_resistance_eligible=True)
    assert success is True
    assert event.details.get("legendary_resistance") is True
    assert event.details["legendary_resistance_remaining"] == 2
    assert dragon.legendary_resistance_count == 2


def test_lr_pool_exhausts_after_count_uses():
    dragon = _dragon(count=3)
    for expected_left in (2, 1, 0):
        success, _ = resolve_saving_throw(
            dragon, "d1", "wisdom", 100, legendary_resistance_eligible=True)
        assert success is True
        assert dragon.legendary_resistance_count == expected_left
    # Pool empty → the failure now stands.
    success, event = resolve_saving_throw(
        dragon, "d1", "wisdom", 100, legendary_resistance_eligible=True)
    assert success is False
    assert event.details["success"] is False


def test_lr_not_burned_on_ineligible_save():
    """A plain damage save (eligible=False) must never spend a charge."""
    dragon = _dragon()
    success, _ = resolve_saving_throw(
        dragon, "d1", "dexterity", 100, legendary_resistance_eligible=False)
    assert success is False
    assert dragon.legendary_resistance_count == 3  # untouched


def test_non_legendary_creature_unaffected():
    commoner = Monster(name="Commoner", max_hit_points=4,
                       ability_scores=AbilityScores())
    success, _ = resolve_saving_throw(
        commoner, "c1", "wisdom", 100, legendary_resistance_eligible=True)
    assert success is False
    assert commoner.legendary_resistance_count == 0


# ── Integration: LR firing through the real player-cast path ────────────────

def _banishment() -> Action:
    """Banishment-shaped save-or-lose (CHA save or off the battlefield)."""
    return Action(
        name="Banishment", description="Send a creature to another plane.",
        action_type=ActionType.ACTION, target_type=TargetType.ONE_CREATURE,
        range=60, spell_level=4, requires_concentration=True,
        saving_throw=SavingThrowEffect(
            ability="charisma", dc=15,
            conditions_on_fail=["banished"], conditions_no_resave=True),
    )


def _duel_with_dragon(lr: int = 3) -> tuple[CombatManager, str]:
    """A player caster (initiative 20) vs a legendary dragon. Returns the manager
    plus the dragon's combatant key (the manager re-slugs monster ids from name)."""
    caster = Creature(
        name="Caster", max_hit_points=40, current_hit_points=40, armor_class=12,
        ability_scores=AbilityScores(), proficiency_bonus=2,
        is_player_controlled=True, actions=[])
    dragon = Monster(
        name="Adult Red Dragon", max_hit_points=256, current_hit_points=256,
        armor_class=19, ability_scores=AbilityScores(), proficiency_bonus=4,
        is_player_controlled=False, legendary_resistance_count=lr)
    encounter = Encounter(
        name="LR", grid_width=10, grid_height=10,
        combatants=[
            CombatantEntry(creature_id="caster", creature_data=caster,
                           team="player", starting_position=(4, 4)),
            CombatantEntry(creature_id="dragon", creature_data=dragon,
                           team="enemy", starting_position=(5, 5)),
        ])
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10]):
        cm.roll_initiative()
    cm.begin_combat()
    dragon_id = next(k for k, v in cm.combatants.items() if v.team == "enemy")
    return cm, dragon_id


def test_dragon_resists_banishment_through_full_cast_path():
    cm, dragon_id = _duel_with_dragon(lr=3)
    cm.selected_action = _banishment()
    with patch("arena.combat.actions.roll_die", return_value=1):  # forced fail
        cm.execute_effect(dragon_id)
    dragon = cm.combatants[dragon_id]
    assert not has_condition(dragon.creature, Condition.BANISHED)  # LR rescued it
    assert dragon.position is not None
    assert dragon.creature.legendary_resistance_count == 2


def test_banishment_lands_once_pool_is_empty():
    cm, dragon_id = _duel_with_dragon(lr=0)  # no charges left
    cm.selected_action = _banishment()
    with patch("arena.combat.actions.roll_die", return_value=1):
        cm.execute_effect(dragon_id)
    dragon = cm.combatants[dragon_id]
    assert has_condition(dragon.creature, Condition.BANISHED)  # nothing to resist with
