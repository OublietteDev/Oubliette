"""Tests for P-CONTROL — Dominate Person / Beast / Monster.

On a failed Wisdom save the target flips to the caster's control (team +
is_player_controlled), driven by the radial with its own actions. Reverts when
the caster loses concentration or the target succeeds a Wisdom save on taking
damage. Creature-type gating restricts each spell (beast / humanoid / any).
"""
import json
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager
from arena.combat.domination import (
    check_domination_on_damage, end_domination, is_dominated,
)
from arena.combat.concentration import end_concentration
from arena.combat.conditions import has_condition
from arena.models.conditions import Condition
from arena.models.actions import Action
from arena.models.abilities import AbilityScores
from arena.models.character import Creature, CreatureType
from arena.models.encounter import Encounter, CombatantEntry
from arena.paths import DATA_DIR


def _spell(sid):
    p = DATA_DIR / "spells" / "srd" / f"{sid}.json"
    return Action.model_validate(json.loads(p.read_text())).model_copy(update={"resource_cost": {}})


def _combat(spell_id="dominate_beast", target_type=CreatureType.BEAST):
    caster = Creature(name="Caster", max_hit_points=30,
                      ability_scores=AbilityScores(intelligence=16), proficiency_bonus=3,
                      is_player_controlled=True, actions=[_spell(spell_id)])
    target = Creature(name="Beast", max_hit_points=20,
                      ability_scores=AbilityScores(wisdom=10), proficiency_bonus=2,
                      is_player_controlled=False, creature_type=target_type)
    enc = Encounter(name="t", grid_width=10, grid_height=10, combatants=[
        CombatantEntry(creature_id="caster", creature_data=caster, team="player", starting_position=(4, 4)),
        CombatantEntry(creature_id="beast", creature_data=target, team="enemy", starting_position=(4, 6)),
    ])
    cm = CombatManager(); cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
        cm.roll_initiative()
    cm.begin_combat()
    cm.selected_action = cm.combatants["caster"].creature.actions[0]
    return cm


def _cast(cm, roll, target_id="beast"):
    with patch("arena.combat.actions.roll_die", return_value=roll):
        return cm.execute_effect(target_id)


class TestDominate:
    def test_failed_save_flips_target_to_caster_control(self):
        cm = _combat()
        _cast(cm, roll=1)  # target rolls a 1 → fails
        b = cm.combatants["beast"]
        assert b.team == "player"
        assert b.creature.is_player_controlled is True
        assert is_dominated(b.creature)
        assert has_condition(cm.combatants["caster"].creature, Condition.CONCENTRATING)

    def test_successful_save_resists(self):
        cm = _combat()
        res = _cast(cm, roll=20)  # target rolls 20 → resists
        b = cm.combatants["beast"]
        assert res.success is False
        assert b.team == "enemy"
        assert not is_dominated(b.creature)

    def test_damage_resave_breaks_free(self):
        cm = _combat()
        _cast(cm, roll=1)
        b = cm.combatants["beast"]
        with patch("arena.combat.actions.roll_die", return_value=20):  # WIS save succeeds
            check_domination_on_damage(b.creature, "beast", cm.combatants)
        assert not is_dominated(b.creature)
        assert b.team == "enemy"
        assert b.creature.is_player_controlled is False

    def test_damage_resave_can_fail_and_hold(self):
        cm = _combat()
        _cast(cm, roll=1)
        b = cm.combatants["beast"]
        with patch("arena.combat.actions.roll_die", return_value=1):  # WIS save fails
            check_domination_on_damage(b.creature, "beast", cm.combatants)
        assert is_dominated(b.creature)  # still held
        assert b.team == "player"

    def test_concentration_end_reverts(self):
        cm = _combat()
        _cast(cm, roll=1)
        end_concentration(cm.combatants["caster"].creature, "caster", cm.combatants)
        b = cm.combatants["beast"]
        assert not is_dominated(b.creature)
        assert b.team == "enemy"
        assert b.creature.is_player_controlled is False


class TestCreatureTypeGating:
    def test_dominate_beast_refuses_humanoid(self):
        cm = _combat(spell_id="dominate_beast", target_type=CreatureType.HUMANOID)
        res = _cast(cm, roll=1)
        assert res.success is False
        assert not is_dominated(cm.combatants["beast"].creature)

    def test_dominate_monster_accepts_any_type(self):
        cm = _combat(spell_id="dominate_monster", target_type=CreatureType.ABERRATION)
        _cast(cm, roll=1)
        assert is_dominated(cm.combatants["beast"].creature)

    def test_dominate_person_requires_humanoid(self):
        cm = _combat(spell_id="dominate_person", target_type=CreatureType.HUMANOID)
        _cast(cm, roll=1)
        assert is_dominated(cm.combatants["beast"].creature)
