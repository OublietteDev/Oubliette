"""SRD gap-fills, story side: the surprise flag's journey (DM tool / keyed
ambush → encounter file) and the battlefield's wall_hp stamping wall hexes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from oubliette.combat.arena_bridge import battle_setting, build_encounter, enemy_from_statblock
from oubliette.combat.schemas import EncounterRequest, TerrainSpec
from oubliette.content.ruleset import load_ruleset
from oubliette.content.schemas import BattleMap, BattleTerrain, KeyedEncounter, KeyedEnemy
from oubliette.enums import Ability
from oubliette.state.models import Character

RS = load_ruleset()


def _pc() -> Character:
    return Character(id="pc", name="You", kind="pc", level=3,
                     abilities={a: 10 for a in Ability}, hp=20, max_hp=20)


def test_encounter_request_surprised_flag_validates():
    assert EncounterRequest().surprised == "none"
    assert EncounterRequest(surprised="party").surprised == "party"
    with pytest.raises(ValidationError):
        EncounterRequest(surprised="everyone")


def test_keyed_encounter_ambush_defaults_off():
    enc = KeyedEncounter(id="e1", enemies=[KeyedEnemy(ref="wolf")])
    assert enc.ambush is False
    assert KeyedEncounter(id="e2", enemies=[KeyedEnemy(ref="wolf")],
                          ambush=True).ambush is True


def test_build_encounter_translates_surprise_to_arena_sides():
    enemies = [enemy_from_statblock(RS.bestiary["bandit"])]
    party_surprised = build_encounter([_pc()], enemies, TerrainSpec(),
                                      surprised="party")
    assert party_surprised.encounter.surprised_side == "player"
    foes_surprised = build_encounter([_pc()], enemies, TerrainSpec(),
                                     surprised="enemies")
    assert foes_surprised.encounter.surprised_side == "enemy"
    plain = build_encounter([_pc()], enemies, TerrainSpec())
    assert plain.encounter.surprised_side is None


def test_battle_wall_hp_stamps_every_wall_hex():
    battle = BattleMap(
        wall_hp=30,
        terrain=[
            BattleTerrain(position=(3, 3), terrain_type="wall"),
            BattleTerrain(position=(4, 3), terrain_type="wall",
                          extra_data={"hp": 5}),          # per-hex author wins
            BattleTerrain(position=(5, 3), terrain_type="difficult"),
        ])
    setting = battle_setting(battle, None)
    by_pos = {t.position: t for t in setting.terrain}
    assert by_pos[(3, 3)].extra_data == {"hp": 30}
    assert by_pos[(4, 3)].extra_data == {"hp": 5}
    assert "hp" not in by_pos[(5, 3)].extra_data


def test_battle_without_wall_hp_keeps_walls_as_scenery():
    battle = BattleMap(terrain=[
        BattleTerrain(position=(3, 3), terrain_type="wall")])
    setting = battle_setting(battle, None)
    assert "hp" not in setting.terrain[0].extra_data
