"""Location battles S1 — fights look/sound/play like WHERE they happen.

The authored `Place.battle` block (grid size, terrain, background, music)
threads loader → session → `stage_combat` → the Arena `Encounter` fields that
survived the trim. Everything here is the wiring; the Arena needs no changes
(absolute asset paths win pathlib joins on its side).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from arena.models.encounter import Encounter, TerrainType

from oubliette.combat import arena_launch
from oubliette.combat.arena_bridge import (
    battle_setting,
    build_encounter,
    enemy_from_statblock,
)
from oubliette.combat.arena_launch import stage_combat
from oubliette.combat.schemas import EncounterRequest, EnemyRef, TerrainSpec
from oubliette.content.loader import PlaceNode
from oubliette.content.schemas import BattleMap, BattleTerrain, Place
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.session import Session
from tests.test_arena_bridge import _goblin_statblock, _pc


def _session() -> Session:
    return Session.open(InMemoryEventStore())


def _tavern() -> BattleMap:
    return BattleMap(
        background_image="tavern.png",
        background_offset=(12.5, -4.0),
        background_scale=1.4,
        music_track="fiddle.mp3",
        grid_width=12,
        grid_height=9,
        terrain=[
            BattleTerrain(position=(5, 4), terrain_type="cover_half"),   # a chair
            BattleTerrain(position=(6, 4), terrain_type="difficult"),    # the spill
            BattleTerrain(position=(3, 3), terrain_type="wall"),         # the bar
            BattleTerrain(position=(99, 99), terrain_type="pit"),        # out of bounds
        ],
    )


# --- schema ---------------------------------------------------------------

def test_battle_map_defaults_are_the_plain_field():
    b = BattleMap()
    assert (b.grid_width, b.grid_height) == (20, 15)
    assert b.background_image is None and b.music_track is None
    assert b.terrain == []


def test_battle_map_rejects_out_of_range_grids_and_unknown_terrain():
    with pytest.raises(ValidationError):
        BattleMap(grid_width=4)
    with pytest.raises(ValidationError):
        BattleMap(grid_height=41)
    with pytest.raises(ValidationError):
        BattleTerrain(position=(1, 1), terrain_type="lava_geyser")


def test_place_carries_an_optional_battle_block():
    p = Place(id="inn", name="The Gilded Flagon", description="A busy taproom.",
              battle=_tavern())
    assert p.battle.music_track == "fiddle.mp3"
    # and stays fully optional — legacy places are untouched
    assert Place(id="road", name="Road", description="A road.").battle is None


# --- battle_setting: BattleMap → Arena-ready pieces ------------------------

def test_battle_setting_converts_terrain_and_drops_out_of_bounds(tmp_path):
    s = battle_setting(_tavern(), tmp_path)
    assert (s.grid_width, s.grid_height) == (12, 9)
    kinds = {tuple(t.position): t.terrain_type for t in s.terrain}
    assert kinds[(5, 4)] == TerrainType.COVER_HALF
    assert kinds[(6, 4)] == TerrainType.DIFFICULT
    assert kinds[(3, 3)] == TerrainType.WALL
    assert (99, 99) not in kinds  # out-of-bounds hex silently dropped


def test_battle_setting_resolves_assets_to_absolute_paths(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "audio").mkdir()
    (tmp_path / "images" / "tavern.png").write_bytes(b"png")
    (tmp_path / "audio" / "fiddle.mp3").write_bytes(b"mp3")
    s = battle_setting(_tavern(), tmp_path)
    assert s.background_path == str(tmp_path / "images" / "tavern.png")
    assert s.music_path == str(tmp_path / "audio" / "fiddle.mp3")
    assert s.background_offset == (12.5, -4.0) and s.background_scale == 1.4


def test_battle_setting_degrades_missing_assets_to_none(tmp_path):
    # no files on disk, and no pack dir at all — both degrade, never raise
    assert battle_setting(_tavern(), tmp_path).background_path is None
    s = battle_setting(_tavern(), None)
    assert s.background_path is None and s.music_path is None
    assert len(s.terrain) == 3  # terrain still converts without a pack dir


# --- build_encounter with a battlefield ------------------------------------

def _plan(battle=None, kind="brawl"):
    enemies = [enemy_from_statblock(_goblin_statblock())]
    return build_encounter([_pc()], enemies, TerrainSpec(kind=kind), battle=battle)


def test_battle_grid_terrain_and_assets_reach_the_encounter(tmp_path):
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "fiddle.mp3").write_bytes(b"mp3")
    setting = battle_setting(_tavern(), tmp_path)
    enc = _plan(battle=setting).encounter
    assert (enc.grid_width, enc.grid_height) == (12, 9)
    assert {tuple(t.position) for t in enc.terrain} == {(5, 4), (6, 4), (3, 3)}
    assert enc.music_track == str(tmp_path / "audio" / "fiddle.mp3")
    assert enc.background_image is None  # image file absent → gray field
    assert enc.background_offset == (12.5, -4.0) and enc.background_scale == 1.4


def test_authored_terrain_replaces_the_kind_palette(tmp_path):
    # chokepoint alone lays a wall line; an authored battlefield must win —
    # no chokepoint walls inside a tavern.
    setting = battle_setting(_tavern(), tmp_path)
    enc = _plan(battle=setting, kind="chokepoint").encounter
    assert {tuple(t.position) for t in enc.terrain} == {(5, 4), (6, 4), (3, 3)}


def test_no_battle_block_stages_exactly_as_before():
    enc = _plan(battle=None, kind="chokepoint").encounter
    assert (enc.grid_width, enc.grid_height) == (20, 15)
    assert enc.music_track is None and enc.background_image is None
    assert any(t.terrain_type == TerrainType.WALL for t in enc.terrain)


def test_spawns_avoid_authored_walls_pits_and_hazards():
    # Wall off most of the default player column (q=2) plus a pit and a fire:
    # every spawn must land on a free hex, never inside the furniture.
    blocked = [BattleTerrain(position=(2, r), terrain_type="wall") for r in range(8)]
    blocked += [BattleTerrain(position=(2, 8), terrain_type="pit"),
                BattleTerrain(position=(2, 9), terrain_type="hazard",
                              extra_data={"damage": "1d6 fire"})]
    setting = battle_setting(BattleMap(grid_width=12, grid_height=10,
                                       terrain=blocked), None)
    enc = _plan(battle=setting).encounter
    bad = {tuple(t.position) for t in setting.terrain}
    for c in enc.combatants:
        assert tuple(c.starting_position) not in bad


# --- the full staging path (session location → encounter file) -------------

def _tavern_session() -> Session:
    s = _session()
    s.location = "inn"
    s.places = {"inn": PlaceNode(id="inn", name="The Gilded Flagon",
                                 description="A busy taproom.", parent=None,
                                 exits=(), battle=_tavern())}
    return s


def test_stage_combat_reads_the_locations_battle_block():
    s = _tavern_session()
    req = EncounterRequest(kind="brawl", enemies=[EnemyRef(ref="goblin", count=2)],
                           terrain=TerrainSpec(kind="chokepoint"))
    pending = stage_combat(req, s.repo, s).pending
    enc = Encounter.model_validate(json.loads(pending.encounter_path.read_text("utf-8")))
    assert (enc.grid_width, enc.grid_height) == (12, 9)
    assert {tuple(t.position) for t in enc.terrain} == {(5, 4), (6, 4), (3, 3)}
    # the session's pack has no such asset files → fields stay None, no crash
    assert enc.music_track is None and enc.background_image is None
    arena_launch.cleanup(pending)


def test_stage_combat_elsewhere_or_without_places_is_unchanged():
    for s in (_session(),                      # no places at all (legacy/test sessions)
              _tavern_session()):
        if s.places:
            s.location = "road"                # somewhere without a battle block
        req = EncounterRequest(kind="brawl", enemies=[EnemyRef(ref="goblin")])
        pending = stage_combat(req, s.repo, s).pending
        enc = Encounter.model_validate(json.loads(pending.encounter_path.read_text("utf-8")))
        assert (enc.grid_width, enc.grid_height) == (20, 15)
        assert enc.music_track is None and enc.background_image is None
        arena_launch.cleanup(pending)


def test_battle_encounter_loads_into_a_real_combat_manager():
    """The staged tavern fight deserializes through the Arena's OWN
    CombatManager — custom grid + authored terrain included — without the GUI."""
    from arena.combat.manager import CombatManager

    s = _tavern_session()
    req = EncounterRequest(kind="brawl", enemies=[EnemyRef(ref="goblin", count=2)])
    pending = stage_combat(req, s.repo, s).pending
    enc = Encounter.model_validate(json.loads(pending.encounter_path.read_text("utf-8")))
    mgr = CombatManager()
    mgr.load_encounter(enc, pending.scratch_dir)
    assert mgr.grid.width == 12 and mgr.grid.height == 9
    from arena.grid.coordinates import HexCoord
    assert mgr.grid.get_cell(HexCoord(3, 3)).terrain == TerrainType.WALL
    assert not mgr.grid.is_passable(HexCoord(3, 3))
    arena_launch.cleanup(pending)
