"""Tests for P-CONTROL — Compulsion.

On a failed Wisdom save the target gains COMPELLED: at the start of each of its
turns it is dragged toward the caster (spending its movement) and barred from
reactions, for the concentration duration. Ends when the caster loses
concentration. Simplifications: single-target, drawn *toward the caster* (the
"chosen direction"), and no per-turn re-save.
"""
import json
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager
from arena.combat.compulsion import is_compelled, process_compulsion_start_of_turn
from arena.combat.concentration import end_concentration
from arena.combat.conditions import has_condition
from arena.models.conditions import Condition
from arena.models.actions import Action
from arena.models.abilities import AbilityScores
from arena.models.character import Creature, CreatureType
from arena.models.encounter import Encounter, CombatantEntry
from arena.paths import DATA_DIR


def _spell(sid="compulsion"):
    p = DATA_DIR / "spells" / "srd" / f"{sid}.json"
    return Action.model_validate(json.loads(p.read_text())).model_copy(update={"resource_cost": {}})


def _combat():
    caster = Creature(name="Caster", max_hit_points=30,
                      ability_scores=AbilityScores(intelligence=16), proficiency_bonus=3,
                      is_player_controlled=True, actions=[_spell()])
    target = Creature(name="Brute", max_hit_points=20,
                      ability_scores=AbilityScores(wisdom=10), proficiency_bonus=2,
                      is_player_controlled=False, creature_type=CreatureType.HUMANOID)
    enc = Encounter(name="t", grid_width=10, grid_height=10, combatants=[
        CombatantEntry(creature_id="caster", creature_data=caster, team="player", starting_position=(4, 4)),
        CombatantEntry(creature_id="brute", creature_data=target, team="enemy", starting_position=(4, 7)),
    ])
    cm = CombatManager(); cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
        cm.roll_initiative()
    cm.begin_combat()
    cm.selected_action = cm.combatants["caster"].creature.actions[0]
    return cm


def _cast(cm, roll, target_id="brute"):
    with patch("arena.combat.actions.roll_die", return_value=roll):
        return cm.execute_effect(target_id)


class TestCompulsionCast:
    def test_failed_save_compels_target(self):
        cm = _combat()
        _cast(cm, roll=1)  # WIS save fails
        assert is_compelled(cm.combatants["brute"].creature)
        assert has_condition(cm.combatants["caster"].creature, Condition.CONCENTRATING)

    def test_successful_save_resists(self):
        cm = _combat()
        res = _cast(cm, roll=20)  # WIS save passes
        assert res.success is False
        assert not is_compelled(cm.combatants["brute"].creature)

    def test_concentration_end_clears_compulsion(self):
        cm = _combat()
        _cast(cm, roll=1)
        end_concentration(cm.combatants["caster"].creature, "caster", cm.combatants)
        assert not is_compelled(cm.combatants["brute"].creature)


class TestCompulsionStartOfTurn:
    def test_drags_toward_caster_and_spends_movement_and_bars_reactions(self):
        cm = _combat()
        _cast(cm, roll=1)
        brute_cb = cm.combatants["brute"]
        caster_pos = cm.grid.find_creature("caster")
        before = cm.grid.find_creature("brute")
        cm.movement.reset("brute", 30)
        cm.reaction_used["brute"] = False

        evs = process_compulsion_start_of_turn(cm, brute_cb)

        after = cm.grid.find_creature("brute")
        assert after.distance_to(caster_pos) < before.distance_to(caster_pos)  # pulled closer
        assert cm.movement.remaining_movement == 0                              # movement spent
        assert cm.reaction_used["brute"] is True                               # reactions barred
        assert evs                                                              # a movement event fired

    def test_uncompelled_creature_is_untouched(self):
        cm = _combat()  # no cast → not compelled
        brute_cb = cm.combatants["brute"]
        cm.movement.reset("brute", 30)
        cm.reaction_used["brute"] = False
        evs = process_compulsion_start_of_turn(cm, brute_cb)
        assert evs == []
        assert cm.movement.remaining_movement == 30
        assert cm.reaction_used["brute"] is False

    def test_no_pull_when_caster_off_grid_but_reactions_still_barred(self):
        cm = _combat()
        _cast(cm, roll=1)
        caster_size = cm.combatants["caster"].creature.size
        cm.grid.remove_creature(cm.grid.find_creature("caster"), caster_size)
        brute_cb = cm.combatants["brute"]
        before = cm.grid.find_creature("brute")
        cm.movement.reset("brute", 30)
        process_compulsion_start_of_turn(cm, brute_cb)
        assert cm.grid.find_creature("brute") == before     # nowhere to be drawn
        assert cm.reaction_used["brute"] is True             # still can't react
