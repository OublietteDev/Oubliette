"""Difficulty S3 — long-rest gating: the DM's grant opens the door, the night
has a price (lodging or rations), a dangerous unsafe night can break, and
short rests stay convenient everywhere.

Cost ops ride the same REST_TAKEN event as the recovery (replay-safe for
free); the grant is a transient session flag set by the DM's propose_rest
and spent (or invalidated by the next in-character turn) exactly once.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "rest-gate.sqlite")
os.environ.pop("ANTHROPIC_API_KEY", None)   # force the scripted client

from fastapi.testclient import TestClient  # noqa: E402

import oubliette.app.server as server  # noqa: E402
from oubliette.app.server import GAME, app  # noqa: E402
from oubliette.rules.rest_gate import (  # noqa: E402
    RATION_ID,
    RestGateError,
    long_rest_cost,
)

client = TestClient(app)


# --- the cost, as a unit -----------------------------------------------------

def _fake_repo(party_cp=0, members=()):
    return SimpleNamespace(party_cp=party_cp, party=lambda: list(members))


def _member(cid, rations=0):
    inv = [SimpleNamespace(item_id=RATION_ID, qty=rations)] if rations else []
    return SimpleNamespace(id=cid, inventory=inv)


def test_safe_haven_bills_the_purse_per_hero():
    repo = _fake_repo(party_cp=500, members=[_member("pc"), _member("pc2")])
    ops, desc = long_rest_cost(repo, safe_haven=True)
    assert len(ops) == 1 and ops[0].op == "coin" and ops[0].delta == -100  # 2 × 5 sp
    assert "lodging" in desc


def test_safe_haven_refuses_an_empty_purse():
    repo = _fake_repo(party_cp=30, members=[_member("pc")])   # night costs 50 cp
    with pytest.raises(RestGateError) as e:
        long_rest_cost(repo, safe_haven=True)
    assert "lodging" in str(e.value)


def test_wilderness_draws_rations_from_whoever_carries_them():
    repo = _fake_repo(members=[_member("pc", rations=1), _member("pc2", rations=3)])
    ops, desc = long_rest_cost(repo, safe_haven=False)
    assert sum(-op.delta for op in ops) == 2 and all(op.item_id == RATION_ID for op in ops)
    assert desc == "2 rations"


def test_wilderness_refuses_a_hungry_party():
    repo = _fake_repo(members=[_member("pc"), _member("pc2", rations=1)])
    with pytest.raises(RestGateError) as e:
        long_rest_cost(repo, safe_haven=False)
    assert "short 1" in str(e.value) and "resupply" in str(e.value)


# --- the gate over HTTP --------------------------------------------------------

def _grant():
    GAME.session.pending_rest = "long"


def _give_rations(n=5):
    GAME.session.repo.add_item("pc", RATION_ID, n)


def test_gated_table_refuses_a_long_rest_without_the_dms_grant():
    assert client.post("/api/new", json={}).json()["ok"]        # adventure = gated
    r = client.post("/api/rest", json={"kind": "long"})
    assert r.status_code == 409 and r.json()["error"] == "gated"
    assert "ask" in r.json()["message"]


def test_short_rests_are_never_gated():
    assert client.post("/api/new", json={"difficulty": {"preset": "hardcore"}}).json()["ok"]
    assert client.post("/api/rest", json={"kind": "short"}).json()["ok"]


def test_story_tables_keep_the_one_click_long_rest():
    assert client.post("/api/new", json={"difficulty": {"preset": "story"}}).json()["ok"]
    d = client.post("/api/rest", json={"kind": "long"}).json()
    assert d["ok"] and d["cost"] is None and d["interrupted"] is False


def test_granted_wilderness_rest_eats_rations_and_spends_the_grant():
    assert client.post("/api/new", json={}).json()["ok"]
    _give_rations(5)
    _grant()
    d = client.post("/api/rest", json={"kind": "long"}).json()
    assert d["ok"] and d["cost"] == "1 ration" and d["interrupted"] is False
    inv = {s.item_id: s.qty for s in GAME.session.repo.pc().inventory}
    assert inv[RATION_ID] == 4
    # The grant is spent: the very next long rest is refused again.
    assert client.post("/api/rest", json={"kind": "long"}).status_code == 409


def test_granted_rest_without_rations_is_refused_with_a_shopping_hint():
    assert client.post("/api/new", json={}).json()["ok"]
    _grant()
    r = client.post("/api/rest", json={"kind": "long"})
    assert r.status_code == 409 and r.json()["error"] == "cost"
    assert "resupply" in r.json()["message"]


def _flag_here_safe(safe: bool):
    from dataclasses import replace
    loc = GAME.session.location
    GAME.session.places[loc] = replace(GAME.session.places[loc], safe_haven=safe)


def test_safe_haven_charges_lodging_instead_of_rations():
    assert client.post("/api/new", json={}).json()["ok"]
    _flag_here_safe(True)
    before = GAME.session.repo.party_cp
    _grant()
    d = client.post("/api/rest", json={"kind": "long"}).json()
    assert d["ok"] and "lodging" in d["cost"]
    assert GAME.session.repo.party_cp == before - 50    # 5 sp, party of one


def test_dangerous_unsafe_night_can_break_into_a_short_rest(monkeypatch):
    assert client.post("/api/new", json={"difficulty": {
        "preset": "custom", "encounter_challenge": "standard",
        "rest_strictness": "dangerous", "pc_death": False,
        "companion_death": False, "hardcore": False}}).json()["ok"]
    _give_rations(5)
    pc = GAME.session.repo.pc()
    pc.hp = 1                                            # wounded, to observe recovery
    monkeypatch.setattr(server, "roll_interruption", lambda rng: True)
    _grant()
    d = client.post("/api/rest", json={"kind": "long"}).json()
    assert d["ok"] and d["interrupted"] is True
    assert GAME.session.repo.pc().hp == 1                # a broken night heals nothing
    inv = {s.item_id: s.qty for s in GAME.session.repo.pc().inventory}
    assert inv[RATION_ID] == 4                           # ...but the night was still paid for
    # The record says what actually happened: a short rest, interrupted.
    from oubliette.record.events import EventKind
    rests = [e for e in GAME.session.store.read_all()
             if e.kind == EventKind.REST_TAKEN.value]
    assert rests[-1].payload["rest"] == "short" and rests[-1].payload["interrupted"] is True


def test_safe_haven_never_breaks(monkeypatch):
    assert client.post("/api/new", json={"difficulty": {
        "preset": "custom", "encounter_challenge": "standard",
        "rest_strictness": "dangerous", "pc_death": False,
        "companion_death": False, "hardcore": False}}).json()["ok"]
    _flag_here_safe(True)
    monkeypatch.setattr(server, "roll_interruption", lambda rng: True)   # would break, if rolled
    _grant()
    d = client.post("/api/rest", json={"kind": "long"}).json()
    assert d["ok"] and d["interrupted"] is False         # safe havens don't roll at all


# --- the grant's lifecycle (through the loop) -----------------------------------

def test_dm_proposal_sets_the_grant_and_the_next_turn_spends_or_expires_it():
    from oubliette.dm.brain import Brain
    from oubliette.llm.scripted import ScriptedLLMClient
    from oubliette.record.rng import Rng
    from oubliette.record.store import InMemoryEventStore
    from oubliette.runtime.loop import TurnLoop
    from oubliette.runtime.session import Session

    session = Session.open(InMemoryEventStore())
    loop = TurnLoop(session, Rng(seed=7, record=session.emit_log),
                    Brain(ScriptedLLMClient()))

    r = asyncio.run(loop.take_turn("We make camp beneath the overhang."))
    assert r.rest_pending == "long"
    assert session.pending_rest == "long"                # the DM's grant stands

    # Out-of-character table-talk leaves the offer standing...
    asyncio.run(loop.take_turn("How do hit dice work again?", ooc=True))
    assert session.pending_rest == "long"

    # ...but a new in-character turn moves the fiction on and expires it.
    asyncio.run(loop.take_turn("Actually, I look around the clearing first."))
    assert session.pending_rest is None
