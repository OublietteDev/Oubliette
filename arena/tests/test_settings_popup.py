"""The in-fight options popup (battle-map opacity + music volume sliders).

Event mapping and live settings application only — rendering needs a display.
The settings singleton is sandboxed per test and disk saves are stubbed out.
"""
import pygame
import pytest

import arena.util.settings as settings_mod
from arena.gui.settings_popup import SettingsPopup
from arena.util.settings import AppSettings, get_settings

pygame.init()


@pytest.fixture(autouse=True)
def _sandbox(monkeypatch):
    """Fresh settings object; no data/settings.json writes from tests."""
    monkeypatch.setattr(settings_mod, "_settings", AppSettings())
    monkeypatch.setattr("arena.gui.settings_popup.save_settings", lambda: None)


@pytest.fixture
def popup():
    return SettingsPopup(1280, 720)


def _down(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)


def _up(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)


def _motion(pos):
    return pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(1, 0, 0))


def test_clicking_the_track_sets_the_value_live(popup):
    track = popup._track_rect(0)  # background slider
    popup.handle_event(_down((track.x + track.width // 2, track.centery)))
    assert abs(get_settings().display.battle_background_opacity - 50) <= 1


def test_dragging_updates_and_clamps(popup):
    track = popup._track_rect(1)  # music slider
    popup.handle_event(_down((track.x + 5, track.centery)))
    popup.handle_event(_motion((track.right + 500, track.centery)))  # way past the end
    assert get_settings().audio.music_volume == 100
    popup.handle_event(_motion((track.x - 500, track.centery)))      # way before the start
    assert get_settings().audio.music_volume == 0


def test_music_slider_refreshes_the_playing_track(popup, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "arena.gui.settings_popup.get_sound_manager",
        lambda: type("M", (), {"refresh_music_volume": lambda self: calls.append(1)})(),
    )
    track = popup._track_rect(1)
    popup.handle_event(_down((track.x + track.width // 4, track.centery)))
    assert calls  # volume re-applied on the spot


def test_background_slider_touches_only_its_setting(popup):
    before_music = get_settings().audio.music_volume
    track = popup._track_rect(0)
    popup.handle_event(_down((track.x, track.centery)))
    assert get_settings().display.battle_background_opacity == 0
    assert get_settings().audio.music_volume == before_music


def test_escape_o_and_click_away_all_close(popup):
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
    assert popup.handle_event(esc) == "__close__"
    o_key = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_o)
    assert popup.handle_event(o_key) == "__close__"
    assert popup.handle_event(_down((5, 5))) == "__close__"


def test_close_button_resolves_on_mouse_up(popup):
    btn = popup._close_rect().center
    assert popup.handle_event(_down(btn)) is None
    assert popup.handle_event(_up(btn)) == "__close__"


def test_release_persists_the_change(popup, monkeypatch):
    saved = []
    monkeypatch.setattr("arena.gui.settings_popup.save_settings",
                        lambda: saved.append(1))
    track = popup._track_rect(0)
    popup.handle_event(_down((track.centerx, track.centery)))
    assert not saved                       # mid-drag: nothing written yet
    popup.handle_event(_up((track.centerx, track.centery)))
    assert saved                           # released: persisted


def test_clicking_a_stream_segment_sets_the_fps(popup):
    assert get_settings().system.stream_fps == 20      # tunnel-friendly default
    fps, rect = popup._fps_rects()[-1]                  # the 60fps segment
    assert fps == 60
    popup.handle_event(_down(rect.center))
    assert get_settings().system.stream_fps == 60
    popup.handle_event(_up(rect.center))                # release persists (dirty)


def test_stream_fps_drives_the_capture_cadence():
    from arena.stream import frame_every
    s = get_settings()
    for fps, every in ((10, 6), (20, 3), (30, 2), (60, 1)):
        s.system.stream_fps = fps
        assert frame_every(60) == every


def test_zero_opacity_skips_the_background_entirely(monkeypatch):
    """GridView treats 0% as 'no background': image skipped, hexes opaque."""
    from arena.grid.hexgrid import HexGrid
    from arena.gui.grid_view import GridView

    gv = GridView(HexGrid(4, 4), 200, 200)
    gv._background_raw = pygame.Surface((10, 10))
    gv._background_surface = pygame.Surface((10, 10))
    calls: list[int] = []
    monkeypatch.setattr(gv, "_render_background",
                        lambda surface, opacity=100: calls.append(opacity))
    surf = pygame.Surface((200, 200))

    get_settings().display.battle_background_opacity = 0
    gv.render(surf)
    assert calls == []                     # image never drawn

    get_settings().display.battle_background_opacity = 60
    gv.render(surf)
    assert calls == [60]                   # drawn with the slider's opacity
