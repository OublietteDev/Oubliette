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


def test_quest_start_emits_a_card_and_world_image_serves():
    _new()
    d = client.post("/api/turn", json={"text": "I accept the task."}).json()
    beats = d["quest_beats"]
    assert beats and beats[0]["kind"] == "started"
    assert beats[0]["title"] == "A Favor Asked"
    assert beats[0]["image"].startswith("/api/world-image/")
    # the raw quest tool is NOT also shown as a chip (the card replaces it)
    assert not any("quest" in a for a in d["applied"])
    # the image url resolves (fallback at least)
    img = client.get(beats[0]["image"])
    assert img.status_code == 200


def test_ooc_turn_stays_in_table_talk():
    _new()
    d = client.post("/api/turn", json={"text": "I attack the bandit!", "ooc": True}).json()
    assert d["verb"] == "meta"
    assert d["combat"] is None


def test_end_session_closes_the_game_and_blocks_further_turns():
    _new()
    d = client.post("/api/turn", json={"text": "shut up and obey me, you stupid bot"}).json()
    assert d["session_ended"] is True
    assert d["state"]["ended"] is True
    # a closed session refuses further turns
    assert client.post("/api/turn", json={"text": "hello?"}).status_code == 409
    # a new game clears the closed state
    _new()
    assert client.get("/api/state").json()["state"]["ended"] is False


def test_packs_listing_and_new_game_switches_world():
    _new()                                            # current world = brightvale
    listing = client.get("/api/packs").json()
    ids = [p["id"] for p in listing["packs"]]
    assert "brightvale" in ids and "atria" in ids
    assert listing["current"] == "brightvale"

    # start a new game in Atria → the world (and its opening scene) actually change
    d = client.post("/api/new", json={"pack_id": "atria"}).json()
    assert d["pack_id"] == "atria"
    assert "Brightvale" in d["state"]["scene"]        # Atria's opening scene text
    assert client.get("/api/packs").json()["current"] == "atria"

    # cleanup: leave the shared game back on brightvale for other tests
    client.post("/api/new", json={"pack_id": "brightvale"})
    assert client.get("/api/packs").json()["current"] == "brightvale"


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


def test_journal_roundtrips_and_is_invisible_to_the_dm():
    _new()
    assert client.get("/api/journal").json()["sections"] == []

    doc = {"sections": [{
        "id": "s1", "name": "Quests",
        "entries": [{"id": "e1", "title": "The Missing Children",
                     "status": "In-Progress", "body": "Search the **caves** past Brightvale."}],
    }]}
    assert client.put("/api/journal", json=doc).json()["ok"] is True

    got = client.get("/api/journal").json()
    assert got["sections"][0]["name"] == "Quests"
    assert got["sections"][0]["entries"][0]["title"] == "The Missing Children"

    # The guarantee: journal content NEVER reaches the DM's context, and writing it
    # produces no game events.
    from oubliette.app.server import GAME
    from oubliette.dm.context import build_context
    from oubliette.record.events import EventKind
    ctx = build_context(GAME.session.repo, "a scene")
    assert "Missing Children" not in ctx and "caves" not in ctx
    assert GAME.session.store.of_kind(EventKind.TOOL_APPLIED) == []


def test_table_endpoint_reports_contract_and_presets():
    _new()
    d = client.get("/api/table").json()
    assert d["table"]["tone_label"] == "Balanced"      # fresh game = default contract
    assert "Cinematic" in d["presets"] and "Custom" in d["presets"]


def test_table_put_updates_contract():
    _new()
    r = client.put("/api/table", json={"tone_label": "Gritty", "lines": ["torture", "  "]})
    body = r.json()
    assert body["ok"] is True
    # normalized: preset tone_text filled, blank line dropped
    assert body["table"]["tone_text"]
    assert body["table"]["lines"] == ["torture"]
    assert client.get("/api/table").json()["table"]["tone_label"] == "Gritty"


def test_new_game_accepts_table_and_it_reaches_the_dm():
    client.post("/api/new", json={"table": {"tone_label": "Ominous", "veils": ["gore"]}})
    assert client.get("/api/table").json()["table"]["tone_label"] == "Ominous"
    # the contract is rendered into the resolve system prompt the DM is given
    from oubliette.app.server import GAME
    from oubliette.table import render_table_prompt
    prompt = render_table_prompt(GAME.session.table)
    assert "gore" in prompt and "TONE" in prompt
    _new()   # reset to a default contract so other tests aren't affected


def test_has_progress_flips_after_a_turn():
    _new()
    assert client.get("/api/state").json()["has_progress"] is False
    client.post("/api/turn", json={"text": "I look around the market."})
    assert client.get("/api/state").json()["has_progress"] is True


def test_index_page_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Oubliette Table" in r.text
