"""Front-end API tests (FastAPI in-process TestClient — no real socket/network).

Forces the scripted offline DM (no ANTHROPIC_API_KEY) and a throwaway DB, so the
HTTP layer + state serialization are exercised deterministically.
"""

from __future__ import annotations

import json
import os
import tempfile

# Must be set BEFORE importing the server (it builds the game at import time).
os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "test.sqlite")
os.environ.pop("ANTHROPIC_API_KEY", None)  # force the scripted client

from fastapi.testclient import TestClient  # noqa: E402

from oubliette.app.server import app  # noqa: E402

client = TestClient(app)


def _new():
    client.post("/api/new")


def test_state_endpoint_reports_scripted_and_seed():
    _new()
    r = client.get("/api/state")
    assert r.status_code == 200
    d = r.json()
    assert d["model"] == "scripted"
    assert d["state"]["pc"]["gold"] == 15
    assert any(i["id"] == "boots" for i in d["state"]["pc"]["inventory"])
    assert any(n["id"] == "merchant_thom" for n in d["state"]["npcs"])


def test_turn_sale_updates_surfaced_state():
    _new()
    r = client.post("/api/turn", json={"text": "Sold."})
    d = r.json()
    assert d["narration"]
    assert any("transact" in a for a in d["applied"])
    assert d["state"]["pc"]["gold"] == 265
    assert all(i["id"] != "boots" for i in d["state"]["pc"]["inventory"])


def test_turn_emits_roll_chip_data():
    _new()
    r = client.post("/api/turn", json={
        "text": "I tell the merchant these boots are priceless dwarven heirlooms."})
    d = r.json()
    assert d["roll"] is not None
    assert d["roll"]["purpose"] == "skill_check.deception"
    assert d["roll"]["result"] in {"success", "failure"}


def test_canon_appears_in_state():
    _new()
    r = client.post("/api/turn", json={
        "text": "I approach the old woman at the well and ask her name."})
    d = r.json()
    assert any("introduced" in a for a in d["applied"])
    canon = d["state"]["canon"]
    assert len(canon) == 1 and canon[0]["status"] == "provisional"


def test_trade_window_opens_and_buy_updates_state():
    _new()
    r = client.post("/api/turn", json={"text": "What do you have for sale?"})
    d = r.json()
    assert d["trade"] is not None
    mid = d["trade"]["merchant_id"]
    assert any(o["item_id"] == "waterskin" for o in d["trade"]["buy"])

    r2 = client.post("/api/trade", json={
        "merchant_id": mid, "action": "buy", "item_id": "waterskin", "qty": 1})
    d2 = r2.json()
    assert d2["ok"] is True
    assert d2["state"]["pc"]["gold"] == 11  # 15 - 4
    assert any(i["id"] == "waterskin" for i in d2["state"]["pc"]["inventory"])


def test_checkout_endpoint_settles_a_basket():
    _new()
    mid = client.post("/api/turn", json={"text": "What do you have for sale?"}).json()["trade"]["merchant_id"]
    r = client.post("/api/trade/checkout", json={
        "merchant_id": mid,
        "buy": [{"item_id": "waterskin", "qty": 1}, {"item_id": "sturdy_belt", "qty": 1}],
        "sell": [],
    })
    d = r.json()
    assert d["ok"] is True
    assert d["state"]["pc"]["gold"] == 15 - 9   # waterskin 4 + belt 5
    have = {i["id"] for i in d["state"]["pc"]["inventory"]}
    assert {"waterskin", "sturdy_belt"} <= have


def test_empty_message_rejected():
    _new()
    r = client.post("/api/turn", json={"text": "   "})
    assert r.status_code == 400


def test_stream_endpoint_yields_deltas_then_done():
    _new()
    events = []
    with client.stream("POST", "/api/turn/stream",
                       json={"text": "I look around the market."}) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    types = [e["t"] for e in events]
    assert "delta" in types and types[-1] == "done"
    done = events[-1]
    assert done["narration"] and done["state"]["pc"]["gold"] == 15
    # the streamed deltas reconstruct the final narration
    streamed = "".join(e["v"] for e in events if e["t"] == "delta")
    assert streamed.strip() == done["narration"].strip()


def test_index_page_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Oubliette Table" in r.text
