"""Bestiary knowledge-gate (per-world CR cutoff + encounter-unlock).

A world may set `bestiary_gate` in its manifest: creatures above a CR threshold stay
hidden in the player's bestiary until the party faces them in a fight, at which point
they come online. Mirrors the map's visit-gating — discovery is derived from the event
log, so it survives save/replay. Forces the scripted DM + a throwaway DB.
"""

from __future__ import annotations

import os
import tempfile
import types

# Must be set BEFORE importing the server (it builds the game at import time).
os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "gate-test.sqlite")
os.environ.pop("ANTHROPIC_API_KEY", None)  # force the scripted client

from fastapi.testclient import TestClient  # noqa: E402

from oubliette.app.server import GAME, app  # noqa: E402
from oubliette.combat.schemas import EncounterRequest, EnemyRef  # noqa: E402
from oubliette.content.schemas import BestiaryGate  # noqa: E402
from oubliette.dm.brain import Brain  # noqa: E402
from oubliette.llm.scripted import ScriptedLLMClient  # noqa: E402
from oubliette.record.events import EventKind  # noqa: E402
from oubliette.record.rng import Rng  # noqa: E402
from oubliette.record.store import InMemoryEventStore  # noqa: E402
from oubliette.runtime.loop import TurnLoop  # noqa: E402
from oubliette.runtime.session import Session  # noqa: E402

client = TestClient(app)


def _new():
    client.post("/api/new")


def _enable_gate(max_known_cr: float = 0.0):
    """Flip on the gate for the live session (as a gated world's manifest would)."""
    GAME.session.bestiary_gate = BestiaryGate(enabled=True, max_known_cr=max_known_cr)


def _bestiary() -> dict:
    return client.get("/api/bestiary").json()


def _record_fight(*keys: str):
    """Record a resolved fight against the given bestiary keys — the same field the
    turn loop writes onto the COMBAT_RESULT event."""
    GAME.session.emit_state(
        EventKind.COMBAT_RESULT, [], encountered=list(keys),
        outcome="victory", hp_final={}, xp_award=0, digest="x",
    )


# --- the gate at the bestiary endpoint --------------------------------------

def test_no_gate_by_default_shows_whole_bestiary():
    _new()                                   # default world (Brightvale) sets no gate
    data = _bestiary()
    assert data["gated"] is False and data["hidden_count"] == 0
    ids = {m["id"] for m in data["monsters"]}
    assert {"rat", "goblin", "tarrasque"} <= ids   # CR-30 apex visible with no gate


def test_gate_hides_unencountered_above_threshold():
    _new()
    _enable_gate(0.0)                          # CR ≤ 0 always known; above it, gated
    data = _bestiary()
    assert data["gated"] is True and data["hidden_count"] > 0
    shown = {m["id"] for m in data["monsters"]}
    assert "tarrasque" not in shown            # CR 30 withheld until faced
    # everything still shown sits at or below the threshold
    crs = [m["cr"] for m in data["monsters"] if m["cr"] is not None]
    assert crs and max(crs) <= 0.0


def test_threshold_keeps_common_creatures_known():
    _new()
    _enable_gate(0.25)                         # "everyone's seen a goblin" (CR 1/4)
    shown = {m["id"] for m in _bestiary()["monsters"]}
    assert "goblin" in shown                   # at threshold → known
    assert "tarrasque" not in shown            # far above → still gated


def test_negative_threshold_gates_all_rated_creatures():
    _new()
    _enable_gate(-1.0)                          # gate every *rated* creature, even CR 0
    data = _bestiary()
    assert data["gated"] is True and data["hidden_count"] > 0
    # rats included: nothing with a challenge rating shows until encountered. (Unrated
    # custom creatures, CR None, are the world's baseline cast and stay known.)
    assert all(m["cr"] is None for m in data["monsters"])
    assert "rat" not in {m["id"] for m in data["monsters"]}


def test_encountered_creature_comes_online_and_is_logged():
    _new()
    _enable_gate(0.0)
    assert "tarrasque" not in {m["id"] for m in _bestiary()["monsters"]}
    _record_fight("srd:tarrasque")
    assert "tarrasque" in {m["id"] for m in _bestiary()["monsters"]}
    # the unlock is event-sourced (replayed on every open), so it persists
    evs = [e for e in GAME.session.store.read_all()
           if e.kind == EventKind.COMBAT_RESULT.value]
    assert any("srd:tarrasque" in (e.payload.get("encountered") or []) for e in evs)


# --- the portrait guard (no peeking art by guessing the URL) ----------------

def test_hidden_creature_portrait_is_redacted_until_encountered():
    _new()
    # sanity: with no gate, the tarrasque's authored art resolves (a real PNG)
    assert "png" in client.get("/api/monster-portrait/srd/tarrasque").headers["content-type"]
    _enable_gate(0.0)
    # gated + unencountered → the neutral silhouette (SVG), not its art
    assert "svg" in client.get("/api/monster-portrait/srd/tarrasque").headers["content-type"]
    _record_fight("srd:tarrasque")
    # faced in play → the real art is served again
    assert "png" in client.get("/api/monster-portrait/srd/tarrasque").headers["content-type"]


# --- the loop helper that records what was faced ----------------------------

def _loop() -> TurnLoop:
    s = Session.open(InMemoryEventStore())     # no events → default world (Brightvale)
    return TurnLoop(s, Rng(seed=1, record=s.emit_log), Brain(ScriptedLLMClient()))


def test_loop_records_statblock_backed_enemies_as_bestiary_keys():
    loop = _loop()
    req = EncounterRequest(kind="brawl",
                           enemies=[EnemyRef(ref="goblin"), EnemyRef(ref="road_bandit")])
    keys = loop._encountered_keys(types.SimpleNamespace(encounter=req))
    assert set(keys) == {"srd:goblin", "pack:road_bandit"}   # SRD + this-world scopes


def test_loop_skips_non_bestiary_and_empty_refs():
    loop = _loop()
    # a template/unknown ref isn't a bestiary entry, so it's not recorded
    bad = EncounterRequest(enemies=[EnemyRef(ref="nonesuch_beast")])
    assert loop._encountered_keys(types.SimpleNamespace(encounter=bad)) == []
    # no encounter on the assessment at all → nothing recorded
    assert loop._encountered_keys(types.SimpleNamespace(encounter=None)) == []
