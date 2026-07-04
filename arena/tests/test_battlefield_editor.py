"""The battlefield editor (location-battles S2) — headless coverage.

Rendering needs a display, so these exercise the data path: spec → grid,
painting/erasing, grid resize (terrain-preserving — the old editor threw the
layout away), the build_battle round-trip, and the save/cancel contract the
Forge relies on (out-file on Save, no out-file on cancel).
"""

import json

import pygame
import pytest

from arena.grid.coordinates import HexCoord
from arena.gui.screens.battlefield_editor import (
    BattlefieldEditorScreen, ToolMode,
)
from arena.models.encounter import TerrainType

pygame.init()


class FakeApp:
    def __init__(self):
        self.quit_called = False

    def quit(self):
        self.quit_called = True


def _spec(**over) -> dict:
    base = {
        "place_name": "The Gilded Flagon",
        "battle": {
            "background_image": "tavern.png",
            "background_offset": [10.0, -5.0],
            "background_scale": 1.3,
            "music_track": "fiddle.mp3",
            "grid_width": 12,
            "grid_height": 9,
            "terrain": [
                {"position": [3, 3], "terrain_type": "wall"},
                {"position": [5, 4], "terrain_type": "cover_half"},
                {"position": [6, 4], "terrain_type": "hazard",
                 "extra_data": {"damage": "1d6 fire"}},
                {"position": [99, 99], "terrain_type": "pit"},      # out of bounds
                {"position": [2, 2], "terrain_type": "lava_geyser"},  # unknown type
            ],
        },
        "background_path": None,   # no display in tests — image loading untested here
        "music_path": None,
    }
    base.update(over)
    return base


@pytest.fixture
def screen(tmp_path):
    s = BattlefieldEditorScreen(1280, 720, _spec(), tmp_path / "out.json")
    s.app = FakeApp()
    return s


# --- loading ---------------------------------------------------------------

def test_spec_terrain_lands_on_the_grid_defensively(screen):
    assert screen.grid.get_cell(HexCoord(3, 3)).terrain == TerrainType.WALL
    assert screen.grid.get_cell(HexCoord(5, 4)).terrain == TerrainType.COVER_HALF
    assert screen.grid.get_cell(HexCoord(2, 2)).terrain == TerrainType.NORMAL  # unknown skipped
    assert (screen.grid_width, screen.grid_height) == (12, 9)


# --- painting / erasing ----------------------------------------------------

def test_paint_and_erase_round_trip(screen):
    screen.selected_terrain = TerrainType.DIFFICULT
    screen._paint_terrain(HexCoord(1, 1))
    assert screen.grid.get_cell(HexCoord(1, 1)).terrain == TerrainType.DIFFICULT
    screen._erase_hex(HexCoord(1, 1))
    assert screen.grid.get_cell(HexCoord(1, 1)).terrain == TerrainType.NORMAL


def test_untouched_extra_data_survives_but_repainting_drops_it(screen):
    battle = screen.build_battle()
    by_pos = {tuple(t["position"]): t for t in battle["terrain"]}
    assert by_pos[(6, 4)]["extra_data"] == {"damage": "1d6 fire"}  # untouched: kept

    screen.selected_terrain = TerrainType.WALL
    screen._paint_terrain(HexCoord(6, 4))                          # repainted: dropped
    by_pos = {tuple(t["position"]): t for t in screen.build_battle()["terrain"]}
    assert "extra_data" not in by_pos[(6, 4)]


# --- grid resize -----------------------------------------------------------

def test_resize_preserves_in_bounds_terrain(screen):
    screen._adjust_grid_size(-6, 0)   # 12 -> 6 wide: q<6 fits, so (6,4) drops
    assert (screen.grid_width, screen.grid_height) == (6, 9)
    assert screen.grid.get_cell(HexCoord(3, 3)).terrain == TerrainType.WALL
    positions = {tuple(t["position"]) for t in screen.build_battle()["terrain"]}
    assert positions == {(3, 3), (5, 4)}


def test_resize_clamps_to_limits(screen):
    screen._adjust_grid_size(-100, -100)
    assert (screen.grid_width, screen.grid_height) == (5, 5)
    screen._adjust_grid_size(100, 100)
    assert (screen.grid_width, screen.grid_height) == (40, 40)


# --- the save / cancel contract ---------------------------------------------

def test_build_battle_updates_geometry_and_passes_filenames_through(screen):
    screen.grid_view.set_background_transform((42.0, -7.0), 2.0)
    battle = screen.build_battle()
    assert battle["background_image"] == "tavern.png"   # untouched
    assert battle["music_track"] == "fiddle.mp3"        # untouched
    assert battle["background_offset"] == [42.0, -7.0]
    assert battle["background_scale"] == 2.0
    assert battle["grid_width"] == 12 and battle["grid_height"] == 9


def test_save_writes_the_block_and_quits(screen):
    screen._save_and_close()
    assert screen.app.quit_called
    data = json.loads(screen.out_path.read_text(encoding="utf-8"))
    kinds = {tuple(t["position"]): t["terrain_type"] for t in data["battle"]["terrain"]}
    assert kinds[(3, 3)] == "wall" and kinds[(5, 4)] == "cover_half"


def test_escape_cancels_without_writing(screen):
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
    screen.handle_event(esc)
    assert screen.app.quit_called
    assert not screen.out_path.exists()


def test_back_button_cancels_without_writing(screen):
    screen._handle_top_bar_click(screen.back_btn.center)
    assert screen.app.quit_called
    assert not screen.out_path.exists()


# --- CLI contract ------------------------------------------------------------

def test_main_rejects_bad_argv(monkeypatch, capsys):
    import arena.battlefield_editor as be
    monkeypatch.setattr("sys.argv", ["battlefield_editor"])
    assert be.main() == 2
    assert "usage" in capsys.readouterr().err


def test_main_rejects_unreadable_spec(monkeypatch, tmp_path, capsys):
    import arena.battlefield_editor as be
    monkeypatch.setattr(
        "sys.argv",
        ["battlefield_editor", str(tmp_path / "missing.json"), str(tmp_path / "o.json")],
    )
    assert be.main() == 2
    assert "bad spec" in capsys.readouterr().err


# --- the hazard damage brush -------------------------------------------------

def test_hazard_brush_stamps_its_damage_spec(screen):
    screen.selected_terrain = TerrainType.HAZARD
    assert screen.hazard_spec == "1d6 fire"           # the default brush
    screen._paint_terrain(HexCoord(1, 1))
    by_pos = {tuple(t["position"]): t for t in screen.build_battle()["terrain"]}
    assert by_pos[(1, 1)]["extra_data"] == {"damage": "1d6 fire"}


def test_hazard_brush_cyclers_change_the_spec(screen):
    screen.selected_terrain = TerrainType.HAZARD
    r = screen._hazard_cfg_rects()
    screen._handle_terrain_palette_click(r["dice_next"].center)   # 1d6 -> 1d8
    screen._handle_terrain_palette_click(r["type_next"].center)   # fire -> cold
    assert screen.hazard_spec == "1d8 cold"
    screen._paint_terrain(HexCoord(2, 2))
    by_pos = {tuple(t["position"]): t for t in screen.build_battle()["terrain"]}
    assert by_pos[(2, 2)]["extra_data"] == {"damage": "1d8 cold"}
    # restamping an existing hazard replaces its spec
    screen._handle_terrain_palette_click(r["type_prev"].center)   # cold -> fire
    screen._paint_terrain(HexCoord(2, 2))
    by_pos = {tuple(t["position"]): t for t in screen.build_battle()["terrain"]}
    assert by_pos[(2, 2)]["extra_data"] == {"damage": "1d8 fire"}


def test_non_hazard_brush_still_clears_extra_data(screen):
    # (6,4) is the spec's authored hazard with 1d6 fire; repaint it as wall
    screen.selected_terrain = TerrainType.WALL
    screen._paint_terrain(HexCoord(6, 4))
    by_pos = {tuple(t["position"]): t for t in screen.build_battle()["terrain"]}
    assert by_pos[(6, 4)]["terrain_type"] == "wall"
    assert "extra_data" not in by_pos[(6, 4)]
