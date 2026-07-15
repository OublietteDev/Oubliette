"""Front-end API tests (FastAPI in-process TestClient — no real socket/network).

Forces the scripted offline DM (no ANTHROPIC_API_KEY) and a throwaway DB, so the
HTTP layer + state serialization are exercised deterministically.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

# Must be set BEFORE importing the server (it builds the game at import time).
os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "test.sqlite")
os.environ["OUBLIETTE_CONFIG"] = os.path.join(tempfile.mkdtemp(), "cfg.json")  # isolate provider config
os.environ.pop("ANTHROPIC_API_KEY", None)  # force the scripted client

from fastapi.testclient import TestClient  # noqa: E402

from oubliette.app.server import GAME, app  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _one_portal():
    """Run the whole module inside the client's context manager: ONE anyio
    portal (one event loop) shared by every request and websocket, matching
    the single uvicorn loop in production. Without it each request gets a
    throwaway loop, and the background turn task /api/turn/submit spawns dies
    with its request's portal instead of broadcasting to /ws."""
    with client:
        yield


def _new():
    client.post("/api/new")


def test_state_endpoint_reports_scripted_and_seed():
    _new()
    r = client.get("/api/state")
    assert r.status_code == 200
    d = r.json()
    assert d["model"] == "scripted"
    assert d["state"]["purse_cp"] == 15_00
    assert any(i["id"] == "boots" for i in d["state"]["pc"]["inventory"])
    assert any(n["id"] == "merchant_thom" for n in d["state"]["npcs"])


def test_transcript_endpoint_replays_the_session():
    _new()
    assert client.get("/api/transcript").json()["turns"] == []   # fresh game: nothing to replay
    client.post("/api/turn", json={"text": "I look around the market"})
    turns = client.get("/api/transcript").json()["turns"]
    assert [t["role"] for t in turns] == ["player", "dm"]
    assert turns[0]["text"] == "I look around the market"
    assert turns[1]["text"].strip()


def test_dm_wrap_proposal_surfaces_to_the_client():
    _new()
    d = client.post("/api/turn", json={"text": "let's call it a night here"}).json()
    assert d["wrap_pending"] is True                 # the DM proposed; the client shows the bar


def test_wrap_endpoint_seals_the_session():
    _new()
    client.post("/api/turn", json={"text": "I look around the market"})
    w = client.post("/api/wrap").json()
    assert w["wrapped"] is True
    assert w["wrote_notes"] is False                 # Offline (scripted) writes no notes
    # The session is sealed: the current-session transcript resets to empty.
    assert client.get("/api/transcript").json()["turns"] == []


def test_wrap_endpoint_refuses_when_nothing_to_wrap():
    _new()
    w = client.post("/api/wrap").json()
    assert w["wrapped"] is False and w["notice"]


def test_turn_sale_updates_surfaced_state():
    _new()
    r = client.post("/api/turn", json={"text": "Sold."})
    d = r.json()
    assert d["narration"]
    assert any("transact" in a for a in d["applied"])
    assert d["state"]["purse_cp"] == 265_00
    assert all(i["id"] != "boots" for i in d["state"]["pc"]["inventory"])


def test_usage_meter_unavailable_offline():
    # The cost meter is Anthropic-only — the scripted DM reports no tokens.
    _new()
    d = client.get("/api/usage").json()
    assert d["available"] is False and d["provider"] == "scripted"


def test_usage_meter_reports_tokens_and_cost_on_anthropic():
    from oubliette.dm.brain import Brain
    from oubliette.llm.anthropic_client import AnthropicLLMClient

    _new()
    old_brain, old_name = GAME.loop.brain, GAME.client_name
    try:
        ac = AnthropicLLMClient(model="claude-sonnet-5", api_key="test-key")
        ac._record_usage({"input_tokens": 10_000, "output_tokens": 2_000})
        GAME.loop.brain, GAME.client_name = Brain(ac), "anthropic"
        d = client.get("/api/usage").json()
        assert d["available"] is True and d["model"] == "claude-sonnet-5"
        assert d["usage"]["input_tokens"] == 10_000 and d["usage"]["calls"] == 1
        assert d["cost"]["total"] > 0                # priced, whatever today's rate is
    finally:
        GAME.loop.brain, GAME.client_name = old_brain, old_name


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


def test_active_quest_surfaced_in_state_then_clears_when_closed():
    _new()
    # the scripted DM starts "A Favor Asked" on this beat
    d = client.post("/api/turn", json={"text": "I accept the task."}).json()
    quest = d["state"]["quest"]
    assert quest is not None and quest["title"] == "A Favor Asked"
    assert "notes" in quest and isinstance(quest["notes"], list)
    # completing it (scripted) drops it from the panel — kept only in the journal now
    d2 = client.post("/api/turn", json={"text": "Good news — the job is done."}).json()
    assert d2["state"]["quest"] is None


def test_ooc_turn_stays_in_table_talk():
    _new()
    d = client.post("/api/turn", json={"text": "I attack the bandit!", "ooc": True}).json()
    assert d["verb"] == "meta"
    assert d["combat"] is None


def test_force_end_session_closes_the_game_and_blocks_further_turns():
    _new()
    d = client.post("/api/turn", json={"text": "shut up and obey me, you stupid bot"}).json()
    assert d["session_force_ended"] is True
    assert d["state"]["force_ended"] is True
    # a closed session refuses further turns
    assert client.post("/api/turn", json={"text": "hello?"}).status_code == 409
    # a new game clears the closed state
    _new()
    assert client.get("/api/state").json()["state"]["force_ended"] is False


def test_packs_listing_and_new_game_switches_world():
    _new()                                            # current world = brightvale
    listing = client.get("/api/packs").json()
    ids = [p["id"] for p in listing["packs"]]
    assert "brightvale" in ids
    assert listing["current"] == "brightvale"
    if "atria" not in ids:                            # local-only until finished
        pytest.skip("atria pack is local-only until finished")

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
    assert d2["state"]["purse_cp"] == 11_00  # 15 gp - 4 gp
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
    assert d["state"]["purse_cp"] == (15 - 9) * 100   # waterskin 4 gp + belt 5 gp
    have = {i["id"] for i in d["state"]["pc"]["inventory"]}
    assert {"waterskin", "sturdy_belt"} <= have


def test_empty_message_rejected():
    _new()
    r = client.post("/api/turn", json={"text": "   "})
    assert r.status_code == 400


def _ws_turn(payload: dict) -> list[dict]:
    """Submit a turn over HTTP and collect its events off the broadcast channel
    (/ws) — the persistent per-browser websocket that replaced the SSE stream."""
    events = []
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["t"] == "hello"
        r = client.post("/api/turn/submit", json=payload)
        assert r.status_code == 200 and r.json()["accepted"] is True
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["t"] in ("end", "error"):
                break
    return events


def test_submit_broadcasts_deltas_then_done():
    _new()
    events = _ws_turn({"text": "I look around the market."})
    types = [e["t"] for e in events]
    # The player's own text comes back as the broadcast's opening event (the
    # sender renders it from the channel like everyone else), the lock brackets
    # the turn, and "done" (the turn payload) precedes the "end" sentinel so
    # tail narration clips can ride after the chips land.
    assert types[0] == "turn_start" and events[0]["text"] == "I look around the market."
    assert [e["busy"] for e in events if e["t"] == "lock"] == [True, False]
    assert "delta" in types and types[-1] == "end"
    done = next(e for e in events if e["t"] == "done")
    assert done["narration"] and done["state"]["purse_cp"] == 15_00
    # the streamed deltas reconstruct the final narration
    streamed = "".join(e["v"] for e in events if e["t"] == "delta")
    assert streamed.strip() == done["narration"].strip()


def test_broadcast_reaches_every_connected_client():
    _new()
    # Two browsers at the table: BOTH see the whole turn — the sender's echo,
    # the deltas, the payload — regardless of who submitted it.
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        assert a.receive_json()["t"] == "hello"
        assert b.receive_json()["t"] == "hello"
        assert client.post("/api/turn/submit",
                           json={"text": "I wave to the merchant."}).status_code == 200
        seen = []
        for ws in (a, b):
            events = []
            while True:
                ev = ws.receive_json()
                events.append(ev)
                if ev["t"] in ("end", "error"):
                    break
            seen.append(events)
    assert [e["t"] for e in seen[0]] == [e["t"] for e in seen[1]]
    assert seen[0][0]["text"] == seen[1][0]["text"] == "I wave to the merchant."


def test_submit_refused_while_a_turn_is_in_flight():
    _new()
    # Free-for-all with a lock, not a queue: a second send while the DM is
    # answering is refused outright, never queued.
    GAME.turn_busy = True
    try:
        r = client.post("/api/turn/submit", json={"text": "me too!"})
        assert r.status_code == 409 and r.json()["busy"] is True
    finally:
        GAME.turn_busy = False


def test_ws_hello_carries_the_lock_state():
    _new()
    GAME.turn_busy = True
    try:
        with client.websocket_connect("/ws") as ws:
            hello = ws.receive_json()
            assert hello["t"] == "hello" and hello["busy"] is True
    finally:
        GAME.turn_busy = False


def _drain_until(ws, t_type: str, guard: int = 60) -> dict:
    """Read broadcast events until one of type `t_type` arrives."""
    for _ in range(guard):
        ev = ws.receive_json()
        if ev["t"] == t_type:
            return ev
    raise AssertionError(f"never saw a {t_type!r} event")


def test_confirmations_broadcast_to_the_table():
    """Table moments — a rest, a companion answer, a wrap, gear moving — render
    from the broadcast channel on EVERY browser, not just the clicker's."""
    _new()
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["t"] == "hello"
        # a short rest resolves on the channel, fresh snapshot stapled on
        assert client.post("/api/rest", json={"kind": "short"}).json()["ok"]
        ev = _drain_until(ws, "rest_taken")
        assert ev["kind"] == "short" and "purse_cp" in ev["state"]
        # gear moving is a bare state refresh for every sidebar
        r = client.post("/api/equip", json={"char_id": "pc", "item_id": "leather_jerkin",
                                            "equip": True})
        assert r.json()["ok"]
        assert "purse_cp" in _drain_until(ws, "state")["state"]
        # a companion answer carries the outcome
        from oubliette.app.server import GAME
        GAME.session.pending_companion = {
            "action": "recruit", "char_id": "stray_pup", "name": "Scrap",
            "kind": "creature", "origin": "recruited", "reason": "test"}
        assert client.post("/api/companion", json={"accept": True}).json()["ok"]
        ev = _drain_until(ws, "companion_answered")
        assert ev["accepted"] is True and ev["name"] == "Scrap"
        # the wrap ceremony: the pen comes out, then the recap — for everyone
        client.post("/api/turn", json={"text": "I look around the market."})
        assert client.post("/api/wrap").json()["wrapped"] is True
        _drain_until(ws, "wrapping")
        assert _drain_until(ws, "wrapped")["wrapped"] is True


def test_journal_roundtrips_and_is_invisible_to_the_dm():
    _new()
    # a never-written journal opens seeded (the blank-page fix), with default binding
    fresh = client.get("/api/journal").json()
    assert [s["name"] for s in fresh["sections"]] == ["Quests", "People", "Places", "Creatures"]
    assert fresh["style"]["hand"] == "caveat" and fresh["style"]["paper"] == "clean"

    doc = {"sections": [{
        "id": "s1", "name": "Quests",
        "entries": [{"id": "e1", "title": "The Missing Children",
                     "status": "In-Progress", "body": "Search the **caves** past Brightvale."}],
    }]}
    assert client.put("/api/journal", json=doc).json()["ok"] is True

    got = client.get("/api/journal").json()
    assert got["sections"][0]["name"] == "Quests"
    assert got["sections"][0]["entries"][0]["title"] == "The Missing Children"
    # a legacy entry (no format/kind keys) loads as markdown-format note
    assert got["sections"][0]["entries"][0]["format"] == "md"
    assert got["sections"][0]["entries"][0]["kind"] == "note"
    # ...and the player's emptiness is respected once a row exists (no re-seeding)
    assert client.put("/api/journal", json={"sections": []}).json()["ok"] is True
    assert client.get("/api/journal").json()["sections"] == []

    # The guarantee: journal content NEVER reaches the DM's context, and writing it
    # produces no game events.
    client.put("/api/journal", json=doc)
    from oubliette.app.server import GAME
    from oubliette.dm.context import build_context
    from oubliette.record.events import EventKind
    ctx = build_context(GAME.session.repo, "a scene")
    assert "Missing Children" not in ctx and "caves" not in ctx
    assert GAME.session.store.of_kind(EventKind.TOOL_APPLIED) == []


def test_journal_binding_persists_and_assets_serve():
    _new()
    doc = {"style": {"hand": "kalam", "ink": "indigo", "cover": "oxblood",
                     "emblem": "emblem-d20.svg", "paper": "weathered"},
           "sections": []}
    assert client.put("/api/journal", json=doc).json()["ok"] is True
    assert client.get("/api/journal").json()["style"]["cover"] == "oxblood"

    art = client.get("/api/journal/art").json()
    assert "emblem-d20.svg" in art["emblems"] and len(art["emblems"]) >= 6
    # papers and seals are drop-a-file extensible; the three built-in papers ship
    assert {"paper-clean.svg", "paper-weathered.svg", "paper-stained.svg"} <= set(art["papers"])
    assert isinstance(art["seals"], list)

    # art + fonts serve; traversal is refused
    assert client.get("/journal-art/paper-weathered.svg").status_code == 200
    assert client.get("/journal-fonts/kalam-regular.woff2").status_code == 200
    assert client.get("/journal-art/..%2f..%2fserver.py").status_code == 404


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


# --- chargen (CS2) ----------------------------------------------------------
_FIGHTER_BUILD = {
    "name": "Bron", "race": "human", "char_class": "fighter", "background": "acolyte",
    "ability_method": "standard_array",
    "base_abilities": {"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8},
    "skills": ["perception", "survival"],
    "languages": ["Draconic", "Celestial"],            # acolyte grants 2 free languages
    "race_languages": ["Orc"],                         # human grants 1 extra language of choice
    "equipment_choices": [[0], [0], [0]],
}


def test_chargen_options_serialize_the_ruleset():
    opt = client.get("/api/chargen/options").json()
    ids = {c["id"] for c in opt["classes"]}
    assert {"fighter", "wizard"} <= ids
    fighter = next(c for c in opt["classes"] if c["id"] == "fighter")
    assert fighter["skill_choose"] == 2 and not fighter["is_caster"]
    assert fighter["equipment"]["fixed"][0]["name"] == "Explorer's Pack"
    wizard = next(c for c in opt["classes"] if c["id"] == "wizard")
    assert wizard["is_caster"] and wizard["caster_prep"] == "prepared"
    assert {r["id"] for r in opt["races"]} >= {"human", "elf", "dwarf"}
    elf = next(r for r in opt["races"] if r["id"] == "elf")
    assert any(s["id"] == "high_elf" for s in elf["subraces"])
    assert opt["standard_array"] == [15, 14, 13, 12, 10, 8]
    # every spell in the pickers carries its SRD text — the hover tooltip's fuel
    wiz_spells = opt["spells_by_class"]["wizard"]
    acid = next(s for s in wiz_spells["cantrips"] if s["id"] == "acid_splash")
    assert "1d6 acid damage" in acid["desc"]
    assert all(s["desc"] for s in wiz_spells["leveled"])


def test_bestiary_endpoint_serializes_the_srd_monsters():
    _new()
    mons = client.get("/api/bestiary").json()["monsters"]
    ids = {m["id"] for m in mons}
    assert {"goblin", "wolf", "young_red_dragon"} <= ids
    # ordered by challenge rating, ascending (None-CR pack blocks sort first).
    crs = [(m["cr"] if m["cr"] is not None else -1.0) for m in mons]
    assert crs == sorted(crs)
    assert mons[-1]["id"] == "tarrasque"            # CR 30, the apex of the merged list
    drake = next(m for m in mons if m["id"] == "young_red_dragon")
    assert drake["cr_label"] == "10" and drake["size"] == "Large"
    assert drake["damage_immunities"] == ["fire"]
    assert drake["speed"]["fly"] == "80 ft."
    assert any(a["name"] == "Multiattack" for a in drake["actions"])
    # every entry is source-tagged and carries a portrait URL routed by scope.
    assert drake["source"] == "SRD" and drake["scope"] == "srd"
    assert drake["portrait_url"] == "/api/monster-portrait/srd/young_red_dragon"
    # sub-1 CR renders as a fraction for the player.
    goblin = next(m for m in mons if m["id"] == "goblin")
    assert goblin["cr_label"] == "1/4"


def test_bestiary_merges_the_loaded_world_monsters():
    """The panel shows the loaded pack's own monsters alongside the SRD library, each
    tagged with its source so the front-end can badge pack vs SRD."""
    _new()                                   # default world = Brightvale
    mons = client.get("/api/bestiary").json()["monsters"]
    pack = [m for m in mons if m["scope"] == "pack"]
    assert {m["id"] for m in pack} >= {"road_bandit", "lean_wolf"}
    assert all(m["source"] and m["source"] != "SRD" for m in pack)
    bandit = next(m for m in pack if m["id"] == "road_bandit")
    assert bandit["portrait_url"] == "/api/monster-portrait/pack/road_bandit"


def test_monster_portrait_serves_art_or_falls_back():
    """A monster with no authored art resolves to the bundled silhouette (so combat
    tokens are never blank); one with a real <id>.png on disk serves that file."""
    drake = client.get("/api/monster-portrait/srd/young_red_dragon")   # no art yet
    assert drake.status_code == 200
    assert drake.headers["content-type"].startswith("image/svg")
    goblin = client.get("/api/monster-portrait/srd/goblin")            # goblin.png exists
    assert goblin.status_code == 200
    assert goblin.headers["content-type"].startswith("image/png")


def test_chargen_preview_accepts_a_valid_build():
    d = client.post("/api/chargen/preview", json=_FIGHTER_BUILD).json()
    assert d["ok"] is True and d["errors"] == []
    p = d["preview"]
    assert p["max_hp"] == 12                       # d10 + CON 2
    assert p["derived"]["armor_class"] == 18       # chain mail + shield
    assert p["abilities"]["str"] == 16             # 15 + human 1
    assert "chain_mail" not in p["equipped"]       # shown by name, not id
    assert "Chain Mail" in p["equipped"]


def test_chargen_preview_reports_errors():
    bad = {**_FIGHTER_BUILD, "skills": ["perception", "arcana"]}   # arcana off-list
    d = client.post("/api/chargen/preview", json=bad).json()
    assert d["ok"] is False
    assert any("Fighter skill option" in e for e in d["errors"])


def test_new_game_with_a_build_installs_the_pc():
    d = client.post("/api/new", json={"pack_id": "brightvale", "build": _FIGHTER_BUILD}).json()
    assert d["ok"] is True
    pc = d["state"]["pc"]
    assert pc["name"] == "Bron" and pc["max_hp"] == 12 and pc["armor_class"] == 18
    assert any(i["id"] == "chain_mail" for i in pc["inventory"])   # SRD gear registered
    _new()   # reset to default-party quick-start for other tests


def test_new_game_with_invalid_build_is_rejected_and_save_survives():
    # play a turn so there's progress to lose, then attempt an invalid new game
    _new()
    client.post("/api/turn", json={"text": "I look around the market."})
    bad = {**_FIGHTER_BUILD, "base_abilities": {"str": 18, "dex": 14, "con": 13,
                                                "int": 12, "wis": 10, "cha": 8}}
    r = client.post("/api/new", json={"build": bad})
    assert r.status_code == 400
    assert any("standard array" in e for e in r.json()["errors"])
    # the prior save is untouched — the bad build never erased it
    assert client.get("/api/state").json()["has_progress"] is True
    _new()


def test_quick_start_keeps_the_default_party():
    d = client.post("/api/new", json={"pack_id": "brightvale"}).json()   # no build
    assert d["state"]["purse_cp"] == 15_00       # brightvale's default-party hero


# --- character sheet (CS3) --------------------------------------------------
def test_sheet_for_a_created_pc_is_fully_derived():
    client.post("/api/new", json={"pack_id": "brightvale", "build": _FIGHTER_BUILD})
    m = client.get("/api/sheet").json()["party"][0]
    assert m["has_sheet"] and m["name"] == "Bron"
    assert m["identity"]["char_class"] == "Fighter" and m["identity"]["race"] == "Human"
    assert m["abilities"]["str"] == {"score": 16, "mod": 3}
    assert m["saves"]["str"]["proficient"] is True and m["saves"]["dex"]["proficient"] is False
    assert m["skills"]["insight"]["proficient"] is True        # from the acolyte background
    assert m["derived"]["armor_class"] == 18
    assert m["hit_dice"] == {"die": 10, "total": 1, "used": 0}
    srcs = {g["source"] for g in m["features"]}
    assert {"class", "background"} <= srcs
    assert any(it["name"] == "Chain Mail" and it["equipped"] for it in m["inventory"])
    _new()


def test_sheet_degrades_for_a_quickstart_hero():
    client.post("/api/new", json={"pack_id": "brightvale"})   # no build → default party
    m = client.get("/api/sheet").json()["party"][0]
    assert m["has_sheet"] is False
    assert "identity" not in m and "spellcasting" not in m
    # basic code-owned numbers still render
    assert set(m["abilities"]) == {"str", "dex", "con", "int", "wis", "cha"}
    assert "armor_class" in m["derived"]


# --- rests & level-up over HTTP (CS5) ---------------------------------------
def test_rest_endpoint_restores_after_short_rest_hit_dice():
    # a level-1 fighter has one d10 hit die; spending it on a short rest marks it used,
    # a long rest gives it back
    # A Story table: long rests stay one-click (the S3 gate is its own test file).
    client.post("/api/new", json={"pack_id": "brightvale", "build": _FIGHTER_BUILD,
                                  "difficulty": {"preset": "story"}})
    d = client.post("/api/rest", json={"kind": "short", "hit_dice": 1}).json()
    assert d["ok"] and d["party"][0]["hit_dice_used"] == 1
    d2 = client.post("/api/rest", json={"kind": "long"}).json()
    assert d2["party"][0]["hit_dice_used"] == 0
    _new()


def test_levelup_flow_over_http():
    client.post("/api/new", json={"pack_id": "brightvale", "build": _FIGHTER_BUILD})
    # leveling is XP-gated now: a fresh PC has 0 XP and can't advance yet.
    assert client.get("/api/levelup/plan").json()["can_level"] is False
    GAME.session.repo.adjust_xp("pc", 2700)        # enough for levels 2, 3, and 4
    plan = client.get("/api/levelup/plan").json()
    assert plan["next_level"] == 2 and plan["is_asi"] is False
    assert plan["xp"]["xp"] == 2700                 # the bar sees it
    # L1 -> L2 (plain)
    d = client.post("/api/levelup", json={"hp_method": "average"}).json()
    assert d["ok"] and d["party"][0]["level"] == 2 and d["party"][0]["max_hp"] == 20
    # L2 -> L3 needs a subclass (fighter Martial Archetype)
    assert client.post("/api/levelup", json={}).status_code == 400
    d3 = client.post("/api/levelup", json={"subclass": "champion"}).json()
    assert d3["party"][0]["identity"]["subclass"] == "Champion"
    # L3 -> L4 is an ASI level: bare attempt fails, an ASI succeeds
    assert client.post("/api/levelup", json={}).status_code == 400
    d4 = client.post("/api/levelup", json={"ability_increases": {"str": 2}}).json()
    m = d4["party"][0]
    assert m["level"] == 4 and m["abilities"]["str"]["score"] == 18
    _new()


def test_chargen_options_half_casters_have_no_level1_spellcasting():
    """The chargen wizard renders a spell picker only when there's something to pick.
    Half casters (paladin/ranger) gain spellcasting at level 2, so at level 1 the
    class view reports 0 cantrips and max_spell_level 0 — the cue the UI uses to show
    a 'no spells yet' note instead of demanding an unpickable spell (CS4 regression)."""
    opts = client.get("/api/chargen/options").json()
    classes = {c["id"]: c for c in opts["classes"]}
    for half in ("paladin", "ranger"):
        cv = classes[half]
        assert cv["is_caster"] is True
        assert cv["cantrips_at_1"] == 0
        assert cv["max_spell_level"] == 0          # no slots at level 1
    # full casters still cast at level 1 (sanity: the guard doesn't over-fire)
    for full in ("cleric", "wizard", "druid", "bard"):
        assert classes[full]["max_spell_level"] >= 1


# --- provider / API-key front door (connect-your-AI) ----------------------

def test_providers_endpoint_lists_roster_and_offline_state():
    r = client.get("/api/providers")
    assert r.status_code == 200
    d = r.json()
    by_id = {p["id"]: p for p in d["providers"]}
    for pid in ("anthropic", "openai", "google", "local"):   # v0.9: all four wired
        assert by_id[pid]["implemented"] is True
    assert d["online"] is False and d["client"] == "scripted"  # no key in this harness


def test_setting_an_unknown_provider_is_refused():
    r = client.post("/api/providers", json={"provider": "closedai", "api_key": "x"})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_saving_an_anthropic_key_brings_the_dm_online(monkeypatch):
    async def fake_ping(c):        # the save-path connection test, minus the network
        return True, None
    monkeypatch.setattr("oubliette.llm.connect.ping", fake_ping)
    r = client.post("/api/providers", json={"provider": "anthropic", "api_key": "sk-ant-test"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["online"] is True
    assert d["client"] == "anthropic" and "Sonnet" in d["model"]
    assert GAME.client_name == "anthropic"               # the live client was re-picked
    # the roster now reports a key on file, still without leaking it
    assert {p["id"]: p for p in d["providers"]}["anthropic"]["has_key"] is True
    assert "sk-ant-test" not in r.text
    # disconnect again so the rest of the suite stays offline/deterministic
    client.post("/api/providers", json={"provider": "anthropic", "disconnect": True})
    assert GAME.client_name == "scripted"


def test_applied_chip_labels():
    """Travel gets a real 'travelled to <place>' chip (it has no StateOps, so the old code
    rendered 'travel: (none)'); dm_note / set_environment / wrap / force-end produce NO chip
    (dm_note must not leak the DM's private note to the player)."""
    from oubliette.app.server import _describe_applied
    from oubliette.record.events import StateOp
    from oubliette.tools.dispatch import ResolvedTool

    _new()
    dest = next(iter(GAME.session.places))
    name = GAME.session.places[dest].name

    travel = ResolvedTool("travel", "go", travel_to=dest)
    assert _describe_applied(travel) == f"travelled to {name}"

    note = ResolvedTool("dm_note", "note", note_text="the innkeeper is a spy")
    assert _describe_applied(note) is None                 # private — never a player chip

    env = ResolvedTool("set_environment", "dusk", env_time="night")
    assert _describe_applied(env) is None                  # ambient — no chip

    wrap = ResolvedTool("end_session", "rest", wrap_proposed=True)
    assert _describe_applied(wrap) is None                 # surfaces via the wrap-bar

    give = ResolvedTool("give", "reward", ops=[StateOp.coin("pc", 5_00)])
    assert _describe_applied(give) and _describe_applied(give).startswith("give:")


def test_item_grant_chip_shows_display_name_not_raw_id():
    """A granted item's chip reads its display name — `tickle_bat` never reaches the
    player, whether the item is in the catalog, the SRD ruleset, or nowhere at all."""
    from oubliette.app.server import _describe_applied
    from oubliette.record.events import StateOp
    from oubliette.tools.dispatch import ResolvedTool

    _new()
    give = ResolvedTool("give_item", "reward",
                        ops=[StateOp.item("pc", "potion_of_healing", 1)])
    chip = _describe_applied(give)
    assert "Potion of Healing" in chip and "potion_of_healing" not in chip
    # an id known nowhere still reads cleanly (title-cased fallback)
    stray = ResolvedTool("give_item", "reward",
                         ops=[StateOp.item("pc", "tickle_bat_9999", 1)])
    assert "Tickle Bat 9999" in _describe_applied(stray)


# --- inventory item details (the hover-card payload) --------------------------
def test_inventory_details_cover_carried_ids_only():
    """/api/inventory ships a compact {item_id: facts} map for the ids the party
    actually carries — never the whole catalog — sourced from the mechanics catalog."""
    _new()
    d = client.get("/api/inventory").json()
    carried = {it["item_id"] for m in d["party"] for it in m["items"]}
    assert carried and set(d["details"]) <= carried
    boots = d["details"]["boots"]                   # a pack item, through the merged catalog
    assert boots["value_text"] == "2 gp" and boots["description"].startswith("Scuffed")
    knife = d["details"]["knife"]
    assert knife["weapon"]["damage"] == "1d4"
    assert knife["weapon"]["properties"] == ["finesse", "light"]


def test_inventory_details_carry_magic_item_facts():
    _new()
    GAME.session.repo.add_item("pc", "potion_of_healing", 1)
    GAME.session.repo.add_item("pc", "dagger_of_venom", 1)
    det = client.get("/api/inventory").json()["details"]
    pot = det["potion_of_healing"]
    assert pot["item_type"] == "potion" and pot["rarity"] == "common"
    assert pot["consumable"]["healing"] == "2d4+2"
    assert "requires_attunement" not in pot          # only true facts ship (compact map)
    dag = det["dagger_of_venom"]
    assert dag["item_type"] == "weapon" and dag["rarity"] == "rare"
    assert dag["magic_bonus"] == 1 and dag["value_text"] == "400 pp" and dag["description"]
    _new()                                           # reset the shared save for other tests
