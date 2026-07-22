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

from oubliette.app.server import _LAST_ACTOR, _SEAT_COOKIE, GAME, TABLE, app  # noqa: E402

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
    _LAST_ACTOR.update(who=None, at=0.0)   # no courtesy-gap bleed between tests
    yield code
    TABLE.hosting = False
    TABLE.code = None
    TABLE.players.clear()
    TABLE.sockets.clear()
    client.cookies.clear()
    _LAST_ACTOR.update(who=None, at=0.0)


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


def test_spotlight_meter_counts_the_quiet_seat(hosting):
    """The DM asked for this in interview (2026-07-18): a per-seat 'who has been
    quiet' tally, so spotlight balancing is deliberate instead of by feel."""
    dana = _join(hosting, "Dana")
    brett = _join(hosting, "Brett")
    client.post("/api/new", headers=_seat(dana))
    pc = [c.id for c in GAME.session.repo.party()
          if not getattr(c, "companion", False)][0]
    # Session-level seat memory, straight onto the fresh session: the meter
    # needs two seated NAMES (the endpoint's one-hero steal rule is its own test).
    GAME.session.emit_seat("Dana", [pc])
    GAME.session.emit_seat("Brett", [pc])
    with client.websocket_connect("/ws", headers=_seat(dana)) as ws:
        assert ws.receive_json()["t"] == "hello"
        assert client.post("/api/turn/submit", headers=_seat(dana),
                           json={"text": "I check the notice board."}).status_code == 200
        while ws.receive_json()["t"] not in ("end", "error"):
            pass
    ctx = GAME.loop._build_context()
    assert "TABLE ACTIVITY" in ctx
    assert "Dana spoke last message" in ctx
    assert "Brett hasn't spoken yet this session" in ctx
    # Brett answers — the meter flips.
    with client.websocket_connect("/ws", headers=_seat(brett)) as ws:
        assert ws.receive_json()["t"] == "hello"
        assert client.post("/api/turn/submit", headers=_seat(brett),
                           json={"text": "I trail after her."}).status_code == 200
        while ws.receive_json()["t"] not in ("end", "error"):
            pass
    ctx = GAME.loop._build_context()
    assert "Brett spoke last message" in ctx
    assert "Dana last spoke 2 messages ago" in ctx


def test_spotlight_meter_absent_at_a_solo_table(hosting):
    """One seated name = no spotlight to balance — the meter stays out of the
    context entirely (solo play pays no tokens for it)."""
    dana = _join(hosting, "Dana")
    client.post("/api/new", headers=_seat(dana))
    pc = [c.id for c in GAME.session.repo.party()
          if not getattr(c, "companion", False)][0]
    client.post("/api/seat", json={"char_ids": [pc]}, headers=_seat(dana))
    assert "TABLE ACTIVITY" not in GAME.loop._build_context()


def test_courtesy_cooldown_only_bites_the_repeat_actor(hosting):
    dana = _join(hosting, "Dana")
    brett = _join(hosting, "Brett")
    client.post("/api/new", headers=_seat(dana))
    with client.websocket_connect("/ws", headers=_seat(dana)) as a, \
         client.websocket_connect("/ws", headers=_seat(brett)) as b:
        assert a.receive_json()["t"] == "hello"
        assert b.receive_json()["t"] == "hello"
        # Dana takes a turn...
        assert client.post("/api/turn/submit", headers=_seat(dana),
                           json={"text": "I look around."}).status_code == 200
        while a.receive_json()["t"] not in ("end", "error"):
            pass
        # ...and immediately tries again: the courtesy gap refuses HER...
        r = client.post("/api/turn/submit", headers=_seat(dana),
                        json={"text": "me again, already!"})
        assert r.status_code == 429 and r.json()["cooldown"] > 0
        # ...but Brett may speak at once — the gap is personal, not a lock.
        assert client.post("/api/turn/submit", headers=_seat(brett),
                           json={"text": "my turn now."}).status_code == 200
        while b.receive_json()["t"] not in ("end", "error"):
            pass


def test_journal_locks_guard_anothers_ink(hosting):
    dana = _join(hosting, "Dana")
    brett = _join(hosting, "Brett")
    client.post("/api/new", headers=_seat(dana))
    doc = {"style": {}, "sections": [{"id": "s1", "name": "Quests", "entries": [
        {"id": "e1", "title": "Dana's lead", "body": "mine alone", "locked": True}]}]}
    assert client.put("/api/journal", json=doc, headers=_seat(dana)).status_code == 200
    # the server stamped the writer's name on her new entry
    saved = client.get("/api/journal", headers=_seat(brett)).json()
    entry = saved["sections"][0]["entries"][0]
    assert entry["author"] == "Dana" and entry["locked"] is True
    # Brett may not rewrite it...
    tampered = {"style": {}, "sections": [{"id": "s1", "name": "Quests", "entries": [
        {**entry, "body": "brett was here"}]}]}
    r = client.put("/api/journal", json=tampered, headers=_seat(brett))
    assert r.status_code == 409 and "Dana" in r.json()["error"]
    # ...nor tear it out...
    torn = {"style": {}, "sections": [{"id": "s1", "name": "Quests", "entries": []}]}
    assert client.put("/api/journal", json=torn, headers=_seat(brett)).status_code == 409
    # ...but may write his own page beside it
    both = {"style": {}, "sections": [{"id": "s1", "name": "Quests", "entries": [
        entry, {"id": "e2", "title": "Brett's note", "body": "hello"}]}]}
    assert client.put("/api/journal", json=both, headers=_seat(brett)).status_code == 200
    # and Dana's lock never bars Dana
    hers = {"style": {}, "sections": [{"id": "s1", "name": "Quests", "entries": [
        {**entry, "body": "updated by its author"}]}]}
    assert client.put("/api/journal", json=hers, headers=_seat(dana)).status_code == 200


def test_difficulty_change_reaches_every_screen(hosting):
    """Brett's playtest, second look (2026-07-22): the host flipped Hidden Rolls
    but Brett's chips kept their DCs — the scrub ran only in the saving browser.
    The PUT now broadcasts, so every connected client hears the change (and gets
    a fresh state for its sidebar)."""
    dana = _join(hosting, "Dana")
    brett = _join(hosting, "Brett")
    client.post("/api/new", headers=_seat(dana))
    with client.websocket_connect("/ws", headers=_seat(brett)) as ws:
        assert ws.receive_json()["t"] == "hello"
        r = client.put("/api/difficulty", headers=_seat(dana),
                       json={"preset": "adventure", "hidden_rolls": True})
        assert r.status_code == 200
        while True:                     # skip the presence (seats) chatter
            ev = ws.receive_json()
            if ev["t"] == "difficulty":
                break
        assert ev["difficulty"]["hidden_rolls"] is True
        assert "state" in ev


def test_started_flag_gates_the_guests_door(hosting):
    """`started` tells a guest's browser whether to seat them directly or show
    the waiting notice: progress on record, OR the host completed New Game this
    server run. A virgin save is indistinguishable from a just-begun quick-start
    in the event log, so the New-Game half lives in memory (GAME.begun)."""
    dana = _join(hosting, "Dana")
    client.post("/api/new", headers=_seat(dana))   # wipe: nothing on record...
    GAME.begun = False                             # ...and pretend a fresh server run
    d = client.get("/api/state", headers=_seat(dana)).json()
    assert d["started"] is False and d["has_progress"] is False
    # The host begins tonight's game: guests may be seated at once.
    client.post("/api/new", headers=_seat(dana))
    assert client.get("/api/state", headers=_seat(dana)).json()["started"] is True
    # Progress alone also counts — a server restarted mid-campaign.
    client.post("/api/turn", headers=_seat(dana), json={"text": "I look around."})
    GAME.begun = False
    d = client.get("/api/state", headers=_seat(dana)).json()
    assert d["started"] is True and d["has_progress"] is True


def test_debug_windows_are_the_hosts_alone(hosting):
    """Hidden Rolls must not have a hole in it: at a hosted table the debug
    endpoints (every roll's DC, the DM's exact context) answer only the host's
    own browser. TestClient's host is 'testclient' — a guest — so a seat alone
    doesn't open them. Solo dev use stays open (test_difficulty covers it)."""
    tok = _join(hosting, "Dana")
    assert client.get("/api/debug/log", headers=_seat(tok)).status_code == 403
    assert client.get("/api/debug/context", headers=_seat(tok)).status_code == 403


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


def test_join_code_is_for_the_hosts_own_browser_only():
    """The code gates the door, so WHO sees it is the whole game: loopback
    with no forwarding header is the host's own browser; a tunnelled guest
    (cloudflared/ngrok deliver remote visitors FROM 127.0.0.1, marked with
    X-Forwarded-For) and a LAN address are guests who must already know it."""
    from oubliette.app.server import _is_host_browser
    assert _is_host_browser("127.0.0.1", {}) is True
    assert _is_host_browser("::1", {}) is True
    assert _is_host_browser("127.0.0.1", {"x-forwarded-for": "203.0.113.9"}) is False
    assert _is_host_browser("127.0.0.1", {"forwarded": "for=203.0.113.9"}) is False
    assert _is_host_browser("192.168.1.7", {}) is False
    assert _is_host_browser(None, {}) is False


# --- the invite tunnel (S4: remote play without touching a console) ----------

def test_tunnel_url_is_harvested_from_cloudflared_banner():
    from oubliette.app.server import _TUNNEL_RE
    banner = ("2026-07-16T03:14:15Z INF +  https://plump-owls-sing.trycloudflare.com  + |")
    m = _TUNNEL_RE.search(banner)
    assert m and m.group(0) == "https://plump-owls-sing.trycloudflare.com"
    assert _TUNNEL_RE.search("INF Starting tunnel connection...") is None


def test_find_cloudflared_honours_the_override(tmp_path, monkeypatch):
    from oubliette.app.server import _find_cloudflared
    fake = tmp_path / "cloudflared.exe"
    fake.write_bytes(b"MZ")
    monkeypatch.setenv("OUBLIETTE_CLOUDFLARED", str(fake))
    assert _find_cloudflared() == str(fake)
    # a set-but-wrong override means "no helper", never a PATH surprise
    monkeypatch.setenv("OUBLIETTE_CLOUDFLARED", str(tmp_path / "ghost.exe"))
    assert _find_cloudflared() is None


def test_start_tunnel_probes_falls_back_and_reports_a_dead_door(tmp_path, monkeypatch):
    import subprocess
    import threading
    import time as _time

    from oubliette.app import server as srv

    fake = tmp_path / "cloudflared.exe"
    fake.write_bytes(b"MZ")
    monkeypatch.setenv("OUBLIETTE_CLOUDFLARED", str(fake))

    class _Proc:
        """A stand-in tunnel: prints its lines, then either stays alive
        (stdout blocks, like a healthy cloudflared) or exits (stdout ends)."""
        def __init__(self, lines, stays_alive):
            self._gate = threading.Event()
            def _stdout():
                yield from lines
                if stays_alive:
                    self._gate.wait(30)        # hold the pipe open like a live helper
            self.stdout = _stdout()
        def terminate(self):
            self._gate.set()

    def _wait_for(state):
        for _ in range(200):
            if srv._TUNNEL["state"] == state:
                return True
            _time.sleep(0.02)
        return False

    banner = ["INF Requesting new quick Tunnel on trycloudflare.com...\n",
              "INF |  https://brave-mice-march.trycloudflare.com  |\n"]

    # a healthy tunnel: address harvested, PROVEN from outside, door open
    monkeypatch.setattr(srv, "_probe_tunnel", lambda url: True)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _Proc(banner, True))
    try:
        srv._start_tunnel(8000)
        assert _wait_for("up")
        assert srv._TUNNEL["url"] == "https://brave-mice-march.trycloudflare.com"
    finally:
        srv._TUNNEL["proc"].terminate()
        srv._TUNNEL.update(url=None, proc=None, state="off")

    # a helper that dies without printing an address → failed, not hung
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: _Proc(["ERR no internet\n"], False))
    try:
        srv._start_tunnel(8000)
        assert _wait_for("failed") and srv._TUNNEL["url"] is None
    finally:
        srv._TUNNEL.update(url=None, proc=None, state="off")

    # the Brett case: the tunnel WAS up, then the helper died (crash, sleep) —
    # the door must be reported shut, never a badge pointing at nowhere
    live = _Proc(banner, True)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: live)
    try:
        srv._start_tunnel(8000)
        assert _wait_for("up")
        live.terminate()                       # ...and then it dies on its own
        assert _wait_for("failed") and srv._TUNNEL["url"] is None
    finally:
        srv._TUNNEL.update(url=None, proc=None, state="off")

    # an address that never opens from outside: ONE retry forced onto HTTP/2
    # (the known QUIC-mangled-network fix); the second, proven tunnel wins
    cmds = []
    def _popen(cmd, **k):
        cmds.append(cmd)
        return _Proc(banner, True)
    probes = iter([False, True])
    monkeypatch.setattr(srv, "_probe_tunnel", lambda url: next(probes))
    monkeypatch.setattr(subprocess, "Popen", _popen)
    try:
        srv._start_tunnel(8000)
        assert _wait_for("up")
        assert srv._TUNNEL["url"] == "https://brave-mice-march.trycloudflare.com"
        assert len(cmds) == 2 and "--protocol" in cmds[1] and "http2" in cmds[1]
        assert "--protocol" not in cmds[0]     # first try lets cloudflared choose
    finally:
        srv._TUNNEL["proc"].terminate()
        srv._TUNNEL.update(url=None, proc=None, state="off")


def test_tunnel_address_never_shown_to_guests(hosting):
    """Same rule as the code: the invite is the HOST'S to give. A guest (or a
    tunnelled visitor) asking /api/hosting never receives the tunnel URL."""
    from oubliette.app import server as srv
    srv._TUNNEL.update(url="https://brave-mice-march.trycloudflare.com", state="up")
    try:
        tok = _join(hosting, "Dana")
        d = client.get("/api/hosting", headers=_seat(tok)).json()
        assert "tunnel" not in d and "code" not in d
    finally:
        srv._TUNNEL.update(url=None, proc=None, state="off")


def test_keep_awake_is_harmless():
    """Best-effort by contract: whatever Windows says (or on any other OS),
    hosting must never fail because the stay-awake request did."""
    from oubliette.app.server import _keep_awake
    _keep_awake()
