"""Inventory panel + equipment: categories, the equip toggle, and that a loadout
change is recorded so it survives reload (event-sourced like other state)."""

from __future__ import annotations

import json

from oubliette.record.events import EventKind, StateOp, replay
from oubliette.record.store import InMemoryEventStore, SqliteEventStore
from oubliette.runtime.session import Session
from oubliette.seed import seed_world


def test_seed_categories_and_starting_loadout():
    repo = seed_world()
    pc = repo.pc()
    assert set(pc.equipped) == {"knife", "leather_jerkin"}
    assert repo.get_item("knife").category == "weapon"
    assert repo.get_item("leather_jerkin").category == "armor"
    assert repo.get_item("leather_jerkin").armor_class == 11
    assert repo.get_item("boots").category == "gear"
    assert repo.get_item("healing_draught").category == "consumable"
    assert repo.get_item("knife").equippable and not repo.get_item("healing_draught").equippable


def test_party_lists_pcs_only():
    repo = seed_world()
    ids = {c.id for c in repo.party()}
    assert ids == {"pc"}  # one party member for now (architecture supports more)


def test_equip_op_sets_loadout_and_replays(tmp_path):
    db = str(tmp_path / "equip.sqlite")
    store = SqliteEventStore(db)
    session = Session.open(store)
    pc = session.repo.pc()

    # unequip the jerkin, equip the boots
    session.emit_state(EventKind.EQUIP_CHANGED, [StateOp.equip("pc", ["knife", "boots"])], reason="x")
    assert set(pc.equipped) == {"knife", "boots"}
    assert len(store.of_kind(EventKind.EQUIP_CHANGED)) == 1
    store.close()

    # reload: the loadout rebuilds from the event log
    store2 = SqliteEventStore(db)
    reloaded = Session.open(store2)
    assert set(reloaded.repo.pc().equipped) == {"knife", "boots"}
    # idempotent replay into a fresh repo
    repo3 = seed_world()
    replay(store2.read_all(), repo3)
    assert set(repo3.pc().equipped) == {"knife", "boots"}
    store2.close()


def test_equip_endpoint_validates_and_toggles():
    import os
    import tempfile
    os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "inv.sqlite")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    from fastapi.testclient import TestClient
    from oubliette.app.server import app
    client = TestClient(app)
    client.post("/api/new")

    inv = client.get("/api/inventory").json()
    me = inv["party"][0]
    assert me["id"] == "pc"
    cats = {i["item_id"]: i["category"] for i in me["items"]}
    assert cats["knife"] == "weapon" and cats["leather_jerkin"] == "armor"
    assert next(i for i in me["items"] if i["item_id"] == "knife")["equipped"] is True

    # equip the boots
    r = client.post("/api/equip", json={"char_id": "pc", "item_id": "boots", "equip": True})
    d = r.json()
    assert d["ok"] is True
    boots = next(i for i in d["inventory"]["party"][0]["items"] if i["item_id"] == "boots")
    assert boots["equipped"] is True

    # can't equip something you don't hold
    bad = client.post("/api/equip", json={"char_id": "pc", "item_id": "dragon_helm", "equip": True})
    assert bad.json()["ok"] is False
