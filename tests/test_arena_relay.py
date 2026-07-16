"""The Arena frame relay, server side (multiplayer S2).

The Arena subprocess connects to /ws/arena (token-gated) and pushes binary
board frames; every browser's /ws receives them on the same pipe as the JSON
events; browser input tagged {"t": "arena"} flows back. These tests play the
Arena's part with a plain test websocket — no pygame anywhere.

Portal note: the module-scoped `with client:` fixture is REQUIRED for any test
file touching /ws (see the dev gotcha) — one anyio portal for every request
and socket, matching uvicorn's single loop.
"""

from __future__ import annotations

import json
import os
import tempfile
import time

import pytest

# Must be set BEFORE importing the server (it builds the game at import time).
os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "test.sqlite")

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from oubliette.app.server import _ARENA, _ARENA_TOKEN, _Hub, app  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _one_portal():
    with client:
        yield


def _arena_ws():
    return client.websocket_connect(f"/ws/arena?token={_ARENA_TOKEN}")


def test_wrong_token_is_turned_away():
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/arena?token=wrong"):
            pass
    assert exc.value.code == 4403


def test_frames_fan_out_to_every_browser():
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        assert a.receive_json()["t"] == "hello"
        assert b.receive_json()["t"] == "hello"
        with _arena_ws() as arena:
            arena.send_bytes(b"\xff\xd8 board one")
            assert a.receive_bytes() == b"\xff\xd8 board one"
            assert b.receive_bytes() == b"\xff\xd8 board one"


def test_late_joiner_gets_the_cached_board():
    """Change-detection means an idle board sends nothing — a browser arriving
    mid-fight is handed the last frame right after its hello."""
    with client.websocket_connect("/ws") as first:
        first.receive_json()
        with _arena_ws() as arena:
            arena.send_bytes(b"the board")
            assert first.receive_bytes() == b"the board"   # frame has landed server-side
            with client.websocket_connect("/ws") as late:
                assert late.receive_json()["t"] == "hello"
                assert late.receive_bytes() == b"the board"


def test_browser_input_reaches_the_arena():
    click = {"t": "arena", "k": "down", "x": 640, "y": 360, "b": 1}
    with _arena_ws() as arena:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json(click)
            assert json.loads(arena.receive_text()) == click


def test_fight_over_clears_the_cached_board():
    """No stale board for the next fight's early arrivals."""
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        with _arena_ws() as arena:
            arena.send_bytes(b"stale")
            ws.receive_bytes()
    for _ in range(100):                    # the disconnect lands asynchronously
        if _ARENA["last_jpeg"] is None:
            break
        time.sleep(0.02)
    assert _ARENA["last_jpeg"] is None and _ARENA["sock"] is None


def test_music_cue_broadcasts_serves_and_greets_late_joiners(tmp_path):
    """S3: a music cue becomes an event on every browser, its asset becomes
    fetchable by opaque id, and a browser sitting down mid-fight is handed the
    playing soundtrack with its hello."""
    track = tmp_path / "battle.ogg"
    track.write_bytes(b"OggS fake track")
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        with _arena_ws() as arena:
            arena.send_text(json.dumps({"t": "music", "file": str(track), "loops": -1}))
            ev = ws.receive_json()
            assert ev["t"] == "arena_audio" and ev["kind"] == "music"
            assert ev["loops"] == -1
            r = client.get(f"/api/arena/audio/{ev['id']}")
            assert r.status_code == 200 and r.content == b"OggS fake track"
            with client.websocket_connect("/ws") as late:
                assert late.receive_json()["t"] == "hello"
                late_ev = late.receive_json()
                assert late_ev["kind"] == "music" and late_ev["id"] == ev["id"]
            arena.send_text(json.dumps({"t": "music_stop"}))
            assert ws.receive_json()["kind"] == "music_stop"
            assert _ARENA["music"] is None      # silence is remembered too


def test_sfx_cue_fires_and_forgets(tmp_path):
    """A stinger reaches the table but is never replayed to late joiners, and
    a cue naming a file that doesn't exist is dropped, not broadcast."""
    blip = tmp_path / "hit.wav"
    blip.write_bytes(b"RIFF fake")
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        with _arena_ws() as arena:
            arena.send_text(json.dumps({"t": "sfx", "file": str(tmp_path / "ghost.wav")}))
            arena.send_text(json.dumps({"t": "sfx", "file": str(blip)}))
            ev = ws.receive_json()              # the ghost was dropped: first event is the real one
            assert ev["kind"] == "sfx"
            assert _ARENA["music"] is None      # a stinger is not a soundtrack


def test_audio_route_serves_only_announced_ids():
    r = client.get("/api/arena/audio/no-such-id")
    assert r.status_code == 404


def test_hub_coalesces_frames_for_a_slow_browser():
    """Two frames before the pump wakes → ONE queued marker holding the
    freshest picture. A slow link means a lower frame rate, never a backlog."""
    hub = _Hub()
    q = hub.attach()
    hub.broadcast_frame(b"one")
    hub.broadcast_frame(b"two")
    assert q.qsize() == 1
    slot = q.get_nowait()["_frame"]
    assert slot["jpeg"] == b"two"
