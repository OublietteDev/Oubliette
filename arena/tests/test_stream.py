"""The frame bridge, Arena side (multiplayer S2) — headless unit tests.

No websocket is opened anywhere here: the bridge's network legs are two daemon
threads the tests never start. What IS tested is everything the main loop
touches — env activation, capture change-detection, JPEG encoding, and the
replay of remote input messages into synthesized pygame events (the seam the
whole feature hangs on: these events must look exactly like the host's own).
"""

from __future__ import annotations

import pygame
import pytest

from arena.stream import ENV_VAR, Bridge, _encode_jpeg


@pytest.fixture(autouse=True, scope="module")
def _pygame():
    pygame.init()          # key name lookups + event synthesis (dummy driver)
    yield


def _bridge() -> Bridge:
    return Bridge("ws://127.0.0.1:1/ws/arena?token=t")


# --- activation --------------------------------------------------------------

def test_absent_env_means_no_bridge(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert Bridge.from_env() is None


def test_env_url_activates_the_bridge(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "ws://127.0.0.1:8000/ws/arena?token=abc")
    b = Bridge.from_env()
    assert b is not None and b.url.endswith("token=abc")


# --- frames ------------------------------------------------------------------

def test_encode_produces_a_jpeg():
    out = _encode_jpeg(bytes(4 * 4 * 3), (4, 4))
    assert out[:2] == b"\xff\xd8"          # JPEG SOI marker


def test_offer_skips_an_unchanged_board():
    b = _bridge()
    b.alive = True
    surf = pygame.Surface((8, 8))
    surf.fill((10, 20, 30))
    b.offer(surf)
    assert b._raw is not None              # first sight of the board: captured
    b._raw = None                          # (as if the send thread took it)
    b.offer(surf)
    assert b._raw is None                  # idle board: no bytes offered
    surf.fill((99, 0, 0))
    b.offer(surf)
    assert b._raw is not None              # something moved: captured again


def test_offer_without_a_link_leaves_no_trace():
    """A frame dropped while disconnected must not poison the change hash —
    the first frame after the link comes up has to go out."""
    b = _bridge()
    b.offer(pygame.Surface((8, 8)))
    assert b._raw is None and b._last_hash is None


# --- remote input → pygame events ---------------------------------------------

def test_click_replays_as_button_down_and_up():
    b = _bridge()
    b._inputs.append({"k": "down", "x": 100, "y": 50, "b": 1})
    b._inputs.append({"k": "up", "x": 100, "y": 50, "b": 1})
    evs = b.take_events()
    assert [e.type for e in evs] == [pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP]
    assert evs[0].pos == (100, 50) and evs[0].button == 1
    assert b.take_events() == []           # drained


def test_motion_carries_rel_and_held_buttons():
    b = _bridge()
    b._inputs.append({"k": "down", "x": 10, "y": 10, "b": 1})
    b._inputs.append({"k": "move", "x": 25, "y": 20})
    move = b.take_events()[-1]
    assert move.type == pygame.MOUSEMOTION
    assert move.pos == (25, 20) and move.rel == (15, 10)
    assert move.buttons == (1, 0, 0)       # the remote drag reads as a drag


def test_wheel_scrolls_and_coordinates_clamp():
    b = _bridge()
    b._inputs.append({"k": "wheel", "x": 5000, "y": -3, "dy": 1})
    evs = b.take_events()
    assert evs[0].type == pygame.MOUSEWHEEL and evs[0].y == 1
    # A wild coordinate clamps into the frozen 1280×720 space — the get_pos
    # gates (action bar, wheel targets) depend on the warp landing on-screen.
    assert b._last_pos == (1279, 0)


def test_key_replays_as_down_then_up():
    b = _bridge()
    b._inputs.append({"k": "key", "key": "escape"})
    evs = b.take_events()
    assert [e.type for e in evs] == [pygame.KEYDOWN, pygame.KEYUP]
    assert evs[0].key == pygame.K_ESCAPE


def test_nonsense_input_is_dropped_quietly():
    b = _bridge()
    b._inputs.append({"k": "dance"})
    b._inputs.append({"k": "key", "key": "definitely not a key"})
    b._inputs.append({})
    assert b.take_events() == []
