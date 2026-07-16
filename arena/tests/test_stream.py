"""The frame bridge, Arena side (multiplayer S2) — headless unit tests.

No websocket is opened anywhere here: the bridge's network legs are two daemon
threads the tests never start. What IS tested is everything the main loop
touches — env activation, capture change-detection, JPEG encoding, and the
replay of remote input messages into synthesized pygame events (the seam the
whole feature hangs on: these events must look exactly like the host's own).
"""

from __future__ import annotations

import json

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


def test_malformed_coordinates_never_kill_the_fight():
    """Found live: a hidden browser tab has a 0×0 canvas, Infinity coords
    JSON-encode as null, and int(None) raised straight through the main loop —
    one bad message from any browser crashed the host's Arena. Bad messages
    drop; the good ones around them still land."""
    b = _bridge()
    b._inputs.append({"k": "move", "x": None, "y": None})
    b._inputs.append({"k": "down", "x": "junk", "y": 3, "b": 1})
    b._inputs.append({"k": "wheel", "x": 5, "y": 5, "dy": "no"})
    b._inputs.append({"k": "move", "x": 25, "y": 20})
    evs = b.take_events()
    assert [e.type for e in evs] == [pygame.MOUSEMOTION]
    assert evs[0].pos == (25, 20)


# --- audio cues (S3) ----------------------------------------------------------

class _FakeWS:
    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(json.loads(data))


def _live_bridge(monkeypatch) -> _FakeWS:
    from arena import stream
    b = _bridge()
    b.alive = True
    ws = _FakeWS()
    b._ws = ws
    monkeypatch.setattr(stream, "_ACTIVE", b)
    return ws


def test_emit_cue_rides_the_live_bridge(monkeypatch):
    from arena import stream
    ws = _live_bridge(monkeypatch)
    stream.emit_cue({"t": "music", "file": "x.ogg", "loops": -1})
    assert ws.sent == [{"t": "music", "file": "x.ogg", "loops": -1}]


def test_emit_cue_without_a_bridge_is_a_noop(monkeypatch):
    from arena import stream
    monkeypatch.setattr(stream, "_ACTIVE", None)
    stream.emit_cue({"t": "sfx", "file": "x.wav"})   # must not raise


def test_music_survives_the_connect_race(monkeypatch):
    """The fight's opening music fires while the websocket is still shaking
    hands — the cue is remembered and must go out the moment the link is up.
    A pre-connect stinger, by contrast, is honestly dropped."""
    from arena import stream
    b = _bridge()                      # not alive: still connecting
    monkeypatch.setattr(stream, "_ACTIVE", b)
    stream.emit_cue({"t": "sfx", "file": "early.wav"})
    stream.emit_cue({"t": "music", "file": "battle.ogg", "loops": -1})
    assert b._pending_music == {"t": "music", "file": "battle.ogg", "loops": -1}
    ws = _FakeWS()                     # ...the handshake completes
    b._ws = ws
    b.alive = True
    cue, b._pending_music = b._pending_music, None
    if cue is not None:                # what _run does right after alive=True
        b._ws.send(json.dumps(cue))
    assert ws.sent == [{"t": "music", "file": "battle.ogg", "loops": -1}]


def _tiny_wav(path):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * 200)


def test_sound_manager_announces_what_it_plays(monkeypatch, tmp_path):
    """The three cue seams: a stinger, a soundtrack, and silence — each emits
    with the RESOLVED path (the app server's cwd is not the Arena's)."""
    import arena.audio.manager as mgr
    ws = _live_bridge(monkeypatch)
    monkeypatch.setattr(mgr, "SOUNDS_DIR", tmp_path)
    monkeypatch.setattr(mgr, "MUSIC_DIR", tmp_path)
    _tiny_wav(tmp_path / "blip.wav")
    sm = mgr.SoundManager()
    if not sm._initialized:
        pytest.skip("no audio device, not even a dummy one")
    sm.play_sfx("blip")
    sm.play_music("blip.wav", loops=-1)
    sm.stop_music()
    kinds = [c["t"] for c in ws.sent]
    assert kinds == ["sfx", "music", "music_stop"]
    from pathlib import Path
    assert Path(ws.sent[0]["file"]).is_absolute() and ws.sent[0]["file"].endswith("blip.wav")
    assert Path(ws.sent[1]["file"]) == (tmp_path / "blip.wav").resolve()
    assert ws.sent[1]["loops"] == -1
