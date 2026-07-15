"""Hosting mode (multiplayer S1): the join-code gate, seats, and attribution.

Forces the scripted offline DM and a throwaway DB, like the other front-end
suites. Hosting is toggled per-test on the module-global TABLE — the fixture
guarantees it's off again afterwards, so the rest of the suite stays solo.
"""

from __future__ import annotations

import os
import tempfile

import pytest

# Must be set BEFORE importing the server (it builds the game at import time).
os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "test.sqlite")
os.environ["OUBLIETTE_CONFIG"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.pop("ANTHROPIC_API_KEY", None)  # force the scripted client

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from oubliette.app.server import _SEAT_COOKIE, GAME, TABLE, app  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _one_portal():
    """One anyio portal (one event loop) for every request and websocket —
    matches production's single uvicorn loop; see test_server_frontend.py."""
    with client:
        yield


@pytest.fixture
def hosting():
    """Turn hosting on for one test, hand back the join code, clean up fully."""
    code = TABLE.start_hosting()
    client.cookies.clear()
    yield code
    TABLE.hosting = False
    TABLE.code = None
    TABLE.players.clear()
    TABLE.sockets.clear()
    client.cookies.clear()


def _join(code: str, name: str) -> str:
    """Join and return the seat token, keeping the shared cookie jar CLEAN so
    multiple identities can coexist in one test (explicit headers per call)."""
    r = client.post("/api/join", json={"code": code, "name": name})
    assert r.status_code == 200, r.text
    token = client.cookies.get(_SEAT_COOKIE)
    assert token
    client.cookies.clear()
    return token


def _seat(token: str) -> dict:
    return {"cookie": f"{_SEAT_COOKIE}={token}"}


def test_solo_defaults_have_no_gate():
    d = client.get("/api/hosting").json()
    assert d == {"hosting": False, "joined": True}
    assert client.post("/api/join", json={"code": "X", "name": "Y"}).status_code == 409
    assert client.get("/api/state").status_code == 200   # nothing is gated


def test_gate_blocks_the_unseated(hosting):
    r = client.get("/api/state")
    assert r.status_code == 401 and r.json()["join_required"] is True
    # ...but the page itself and the join screen's two endpoints stay open
    assert client.get("/").status_code == 200
    assert client.get("/api/hosting").status_code == 200


def test_bad_code_and_blank_name_refused(hosting):
    assert client.post("/api/join", json={"code": "WRONG", "name": "Dana"}).status_code == 403
    assert client.post("/api/join", json={"code": hosting, "name": "   "}).status_code == 400


def test_join_grants_a_seat(hosting):
    # lower-case code is fine; the name is trimmed and echoed
    r = client.post("/api/join", json={"code": hosting.lower(), "name": "  Dana  "})
    assert r.status_code == 200 and r.json()["name"] == "Dana"
    assert client.get("/api/state").status_code == 200        # cookie jar carries the seat
    d = client.get("/api/hosting").json()
    assert d["joined"] is True and d["you"] == "Dana" and d["players"] == ["Dana"]


def test_code_never_shown_to_remote_clients(hosting):
    # TestClient's request.client.host is "testclient" — not local — so even a
    # seated player is NOT handed the code or the host's addresses.
    _tok = _join(hosting, "Dana")
    d = client.get("/api/hosting", headers=_seat(_tok)).json()
    assert "code" not in d and "addresses" not in d


def test_ws_refused_without_a_seat(hosting):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws"):
            pass
    assert exc.value.code == 4401


def test_seats_presence_and_attribution(hosting):
    dana = _join(hosting, "Dana")
    brett = _join(hosting, "Brett")
    client.post("/api/new", headers=_seat(dana))
    with client.websocket_connect("/ws", headers=_seat(dana)) as ws:
        assert ws.receive_json()["t"] == "hello"
        seats = ws.receive_json()
        assert seats["t"] == "seats"
        by_name = {p["name"]: p["connected"] for p in seats["players"]}
        assert by_name == {"Dana": True, "Brett": False}   # Brett joined, isn't connected
        # Dana speaks: the broadcast carries who, for every client to render
        r = client.post("/api/turn/submit", headers=_seat(dana),
                        json={"text": "I look around the market."})
        assert r.status_code == 200
        while True:
            ev = ws.receive_json()
            if ev["t"] == "turn_start":
                assert ev["who"] == "Dana"
            if ev["t"] in ("end", "error"):
                break


def test_seat_endpoint_needs_a_hosted_table():
    assert client.post("/api/seat", json={"char_ids": []}).status_code == 409


def test_seat_memory_claim_steal_release_and_replay(hosting):
    dana = _join(hosting, "Dana")
    brett = _join(hosting, "Brett")
    client.post("/api/new", headers=_seat(dana))
    heroes = [c.id for c in GAME.session.repo.party()
              if not getattr(c, "companion", False)]
    pc = heroes[0]
    # Dana claims a hero; the seat map is whole-assignment per name
    r = client.post("/api/seat", json={"char_ids": [pc]}, headers=_seat(dana))
    assert r.status_code == 200 and r.json()["seats"] == {"Dana": [pc]}
    # a hero sits in ONE chair: Brett claiming it empties Dana's seat
    r = client.post("/api/seat", json={"char_ids": [pc]}, headers=_seat(brett))
    assert r.json()["seats"] == {"Brett": [pc]}
    # only real heroes can be claimed
    assert client.post("/api/seat", json={"char_ids": ["nobody"]},
                       headers=_seat(dana)).status_code == 400
    # the save remembers the chairs: a full replay rebuilds the map
    GAME.reload_world()
    assert GAME.session.seats == {"Brett": [pc]}
    # /api/hosting hands the map to the seats UI
    d = client.get("/api/hosting", headers=_seat(brett)).json()
    assert d["seats"] == {"Brett": [pc]}
    # an empty claim releases the seat
    r = client.post("/api/seat", json={"char_ids": []}, headers=_seat(brett))
    assert r.json()["seats"] == {}


def test_attribution_reaches_context_transcript_and_beats(hosting):
    dana = _join(hosting, "Dana")
    client.post("/api/new", headers=_seat(dana))
    pc = [c.id for c in GAME.session.repo.party()
          if not getattr(c, "companion", False)][0]
    client.post("/api/seat", json={"char_ids": [pc]}, headers=_seat(dana))
    with client.websocket_connect("/ws", headers=_seat(dana)) as ws:
        assert ws.receive_json()["t"] == "hello"
        assert client.post("/api/turn/submit", headers=_seat(dana),
                           json={"text": "I look around the market."}).status_code == 200
        while True:
            ev = ws.receive_json()
            if ev["t"] == "lock" and ev["busy"]:
                assert ev["who"] == "Dana"    # "the Phantom is listening to Dana…"
            if ev["t"] in ("end", "error"):
                break
    # the DM's context knows the seats and the speaker...
    ctx = GAME.loop._build_context()
    assert "[played by Dana]" in ctx
    assert "SPEAKING NOW: Dana" in ctx
    # ...the durable transcript replays the name...
    turns = client.get("/api/transcript", headers=_seat(dana)).json()["turns"]
    player_turns = [t for t in turns if t["role"] == "player"]
    assert player_turns[-1]["who"] == "Dana"
    # ...and the continuity beat is attributed too
    assert GAME.loop.history[-1].startswith('Dana: "I look around the market.')


def test_solo_turns_carry_no_speaker():
    client.post("/api/new")
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["t"] == "hello"
        assert client.post("/api/turn/submit",
                           json={"text": "I stretch and yawn."}).status_code == 200
        while True:
            ev = ws.receive_json()
            if ev["t"] == "turn_start":
                assert ev["who"] is None
            if ev["t"] in ("end", "error"):
                break
