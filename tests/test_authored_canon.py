"""Authored-canon-from-pack: NPCs and places in a content pack become confirmed,
load-bearing CanonRecords so the DM's retrieval (canon search) and the canon
lifecycle work over authored content too (design doc §1, §5).

Key invariants pinned here:
  * authored records carry origin=authored / status=confirmed and use the pack
    SLUG as id (not 'canon-N'), so they never perturb the runtime id counter;
  * a fresh session seeds them and they're retrievable by keyword;
  * they survive a SQLite reload byte-identically alongside runtime canon;
  * runtime create_entity still starts at 'canon-0' despite authored seeding.
"""

from __future__ import annotations

import json

from oubliette.canon.models import CanonDraft
from oubliette.content.loader import DEFAULT_PACK, load_pack
from oubliette.record.store import InMemoryEventStore, SqliteEventStore
from oubliette.runtime.session import Session


def test_pack_builds_authored_canon():
    world = load_pack(DEFAULT_PACK)
    by_id = {r.id: r for r in world.canon}

    # Thom (npc) and both places are present, confirmed + authored + load-bearing.
    assert {"merchant_thom", "brightvale_market", "brightvale_gate"} <= set(by_id)
    for r in world.canon:
        assert r.origin == "authored"
        assert r.status == "confirmed"
        assert r.load_bearing is True
        assert r.created_by_event is None

    assert by_id["merchant_thom"].entity_type == "npc"
    assert by_id["brightvale_market"].entity_type == "place"


def test_session_seeds_and_retrieves_authored_canon():
    session = Session.open(InMemoryEventStore())
    # Retrievable by keyword, just like runtime canon.
    hits = {h.id for h in session.canon.search("leather goods merchant")}
    assert "merchant_thom" in hits
    place_hits = {h.id for h in session.canon.search("crowded market square in town")}
    assert "brightvale_market" in place_hits


def test_authored_ids_do_not_consume_runtime_counter():
    """Authored slug ids must not advance the 'canon-N' counter, so the DM's first
    live creation is still 'canon-0'."""
    session = Session.open(InMemoryEventStore())
    rec = session.emit_create_entity(
        CanonDraft(entity_type="npc", name="Captain Bromley", text="A dock-watch captain."),
        reason="met on the pier",
    )
    assert rec.id == "canon-0"
    # The authored records are still there, untouched.
    assert session.canon.get("merchant_thom").status == "confirmed"


def test_authored_canon_survives_reload(tmp_path):
    db = str(tmp_path / "authored.sqlite")
    store = SqliteEventStore(db)
    session = Session.open(store)
    session.emit_create_entity(
        CanonDraft(entity_type="place", name="The Drowned Lantern", text="A dockside tavern."),
        reason="intro")

    def snapshot(canon):
        recs = sorted((r.model_dump() for r in canon.all()), key=lambda r: r["id"])
        return json.dumps(recs, sort_keys=True)

    live = snapshot(session.canon)
    store.close()

    reloaded = Session.open(SqliteEventStore(db))
    assert snapshot(reloaded.canon) == live
    # both authored and the runtime creation are present after reload
    assert reloaded.canon.get("merchant_thom").origin == "authored"
    assert reloaded.canon.get("canon-0").name == "The Drowned Lantern"


def test_custom_seed_session_has_no_authored_canon():
    """A session opened with a custom seed (bypassing the pack) gets no authored
    canon — authored content rides with the pack only."""
    from oubliette.seed import seed_world

    session = Session.open(InMemoryEventStore(), seed=seed_world)
    assert session.canon.all() == []
