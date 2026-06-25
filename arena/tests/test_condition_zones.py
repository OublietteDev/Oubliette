"""Tests for P-TERRAIN — condition-zones: Stinking Cloud, Sleet Storm, Plant Growth.

Extends the zone system from damage-only to applying a condition on a failed
start-of-turn/entry save, plus reuse of obscurement (Sleet Storm) and difficult
terrain (Sleet Storm, Plant Growth).
"""
import json
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager
from arena.combat.zones import process_zone_start_of_turn, compute_obscured_hexes
from arena.combat.conditions import has_condition
from arena.models.conditions import Condition
from arena.models.actions import Action
from arena.models.abilities import AbilityScores
from arena.models.character import Creature
from arena.models.encounter import Encounter, CombatantEntry, TerrainType
from arena.grid.coordinates import HexCoord
from arena.paths import DATA_DIR


def _spell(sid):
    p = DATA_DIR / "spells" / "srd" / f"{sid}.json"
    return Action.model_validate(json.loads(p.read_text())).model_copy(update={"resource_cost": {}})


def _combat(sid):
    caster = Creature(name="Caster", max_hit_points=30,
                      ability_scores=AbilityScores(intelligence=16), proficiency_bonus=3,
                      is_player_controlled=True, actions=[_spell(sid)])
    foe = Creature(name="Foe", max_hit_points=20,
                   ability_scores=AbilityScores(dexterity=8, constitution=8), proficiency_bonus=2,
                   is_player_controlled=False)
    enc = Encounter(name="t", grid_width=14, grid_height=14, combatants=[
        CombatantEntry(creature_id="caster", creature_data=caster, team="player", starting_position=(3, 7)),
        CombatantEntry(creature_id="foe", creature_data=foe, team="enemy", starting_position=(8, 7)),
    ])
    cm = CombatManager(); cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
        cm.roll_initiative()
    cm.begin_combat()
    cm.selected_action = cm.combatants["caster"].creature.actions[0]
    cm.execute_effect_at_hex(HexCoord(8, 7))
    return cm


def _start_turn(cm, roll):
    with patch("arena.combat.actions.roll_die", return_value=roll):
        return process_zone_start_of_turn(cm.active_zones, "foe", cm.combatants, cm.grid)


class TestStinkingCloud:
    def test_creates_condition_zone(self):
        cm = _combat("stinking_cloud")
        assert len(cm.active_zones) == 1
        assert cm.active_zones[0].condition_on_fail == "incapacitated"

    def test_failed_save_incapacitates(self):
        cm = _combat("stinking_cloud")
        _start_turn(cm, roll=1)
        assert has_condition(cm.combatants["foe"].creature, Condition.INCAPACITATED)

    def test_made_save_no_condition(self):
        cm = _combat("stinking_cloud")
        _start_turn(cm, roll=20)
        assert not has_condition(cm.combatants["foe"].creature, Condition.INCAPACITATED)


class TestSleetStorm:
    def test_obscures_and_difficult_terrain(self):
        cm = _combat("sleet_storm")
        z = cm.active_zones[0]
        assert z.obscures_vision is True
        assert z.condition_on_fail == "prone"
        assert (8, 7) in compute_obscured_hexes(cm.active_zones, cm.combatants, cm.grid)
        assert cm.grid.get_cell(HexCoord(8, 7)).terrain == TerrainType.DIFFICULT

    def test_failed_save_knocks_prone(self):
        cm = _combat("sleet_storm")
        _start_turn(cm, roll=1)
        assert has_condition(cm.combatants["foe"].creature, Condition.PRONE)


class TestPlantGrowth:
    def test_lays_difficult_terrain_no_zone(self):
        cm = _combat("plant_growth")
        assert len(cm.active_zones) == 0          # instantaneous, not a persistent zone
        assert cm.grid.get_cell(HexCoord(8, 7)).terrain == TerrainType.DIFFICULT
