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


def test_scroll_spell_rider_stacks_by_variant():
    """A5: a Spell Scroll's inscribed spell rides the inventory item. Stack identity is
    (item_id, spell) — differently-inscribed scrolls are distinct stacks, identical ones
    stack — so one generic `spell_scroll` catalog item covers every spell."""
    session = Session.open(InMemoryEventStore())   # fallback carries the generic scroll
    repo = session.repo
    repo.add_item("pc", "spell_scroll", 1, spell="fireball")
    repo.add_item("pc", "spell_scroll", 1, spell="fireball")     # stacks with the first
    repo.add_item("pc", "spell_scroll", 1, spell="cure_wounds")  # distinct variant
    repo.add_item("pc", "spell_scroll", 1)                       # a blank scroll, distinct
    pc = repo.pc()
    assert pc.variant_qty("spell_scroll", "fireball") == 2
    assert pc.variant_qty("spell_scroll", "cure_wounds") == 1
    assert pc.variant_qty("spell_scroll", None) == 1
    assert pc.item_qty("spell_scroll") == 4          # total across every variant
    # removal targets the exact variant, leaving the others intact
    repo.remove_item("pc", "spell_scroll", 1, spell="fireball")
    assert pc.variant_qty("spell_scroll", "fireball") == 1
    assert pc.variant_qty("spell_scroll", "cure_wounds") == 1


def test_give_scroll_with_spell_records_and_replays(tmp_path):
    """A5: the DM inscribes the spell at grant time; the rider rides the StateOp and so
    survives save/replay. Also exercises the SRD fallback catalog (the DM can `give` a
    scroll that no pack shipped) and the spell-id normalization ('Fireball' -> 'fireball')."""
    from oubliette.tools.dispatch import Dispatcher
    from oubliette.tools.schemas import Give, ValueEntry

    db = str(tmp_path / "scroll.sqlite")
    store = SqliteEventStore(db)
    session = Session.open(store)
    disp = Dispatcher(session.repo)
    call = Give(to="pc", items=[ValueEntry(item_id="spell scroll", spell="Fireball")],
                reason="a parting gift from the archmage")
    resolved = disp.resolve(call)
    assert resolved.ops[0].item_id == "spell_scroll"   # fuzzy-resolved via the fallback
    assert resolved.ops[0].spell == "fireball"         # normalized to the spell-id form
    session.emit_state(EventKind.TOOL_APPLIED, resolved.ops, reason=call.reason)
    assert session.repo.pc().variant_qty("spell_scroll", "fireball") == 1
    store.close()

    # reload: the inscribed scroll rebuilds from the log (the fallback re-resolves the id)
    store2 = SqliteEventStore(db)
    reloaded = Session.open(store2)
    assert reloaded.repo.pc().variant_qty("spell_scroll", "fireball") == 1
    store2.close()


def test_scroll_upcast_level_rider(tmp_path):
    """A5: a commissioned/upcast scroll carries a cast level. Level is part of the stack
    identity (a 3rd- and a 5th-level Fireball scroll don't merge), it must be >= the
    spell's base level, and it survives replay."""
    from oubliette.tools.dispatch import Dispatcher
    from oubliette.tools.schemas import Give, ValueEntry

    db = str(tmp_path / "upcast.sqlite")
    store = SqliteEventStore(db)
    session = Session.open(store)
    disp = Dispatcher(session.repo, ruleset=session.ruleset)

    # a 5th-level Fireball scroll (base 3rd) — allowed
    up = disp.resolve(Give(to="pc", items=[ValueEntry(item_id="spell_scroll",
                          spell="fireball", spell_level=5)], reason="commissioned"))
    assert up.ops[0].spell_level == 5
    session.emit_state(EventKind.TOOL_APPLIED, up.ops, reason="x")

    # a normal 3rd-level Fireball scroll is a DISTINCT stack
    session.repo.add_item("pc", "spell_scroll", 1, spell="fireball")   # level None = base
    pc = session.repo.pc()
    assert pc.variant_qty("spell_scroll", "fireball", 5) == 1
    assert pc.variant_qty("spell_scroll", "fireball", None) == 1
    assert pc.item_qty("spell_scroll") == 2            # they don't merge

    # below the spell's base level is rejected (Fireball can't cast at 1st)
    import pytest
    from oubliette.tools.dispatch import ToolApplyError
    with pytest.raises(ToolApplyError):
        disp.resolve(Give(to="pc", items=[ValueEntry(item_id="spell_scroll",
                     spell="fireball", spell_level=1)], reason="too low"))
    store.close()

    # the upcast level survives replay
    store2 = SqliteEventStore(db)
    reloaded = Session.open(store2)
    assert reloaded.repo.pc().variant_qty("spell_scroll", "fireball", 5) == 1
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


def test_inventory_view_shows_inscribed_scroll_spell():
    """A5: an inscribed Spell Scroll reads as 'Spell Scroll: <spell>' in the inventory
    and sheet views, with the spell exposed as structured fields for the Arena bridge."""
    import os
    import tempfile
    os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "scrollview.sqlite")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    from fastapi.testclient import TestClient
    from oubliette.app import server
    client = TestClient(server.app)
    client.post("/api/new")

    # inscribe a Fireball scroll (the generic scroll comes from the SRD fallback catalog)
    server.GAME.session.repo.add_item("pc", "spell_scroll", 1, spell="fireball")

    # and an upcast one, to confirm the level annotation renders
    server.GAME.session.repo.add_item("pc", "spell_scroll", 1, spell="fireball", spell_level=5)

    inv = client.get("/api/inventory").json()
    items = inv["party"][0]["items"]
    plain = next(i for i in items if i["item_id"] == "spell_scroll" and i["spell_level"] is None)
    upcast = next(i for i in items if i["item_id"] == "spell_scroll" and i["spell_level"] == 5)
    assert plain["name"] == "Spell Scroll: Fireball"
    assert plain["spell"] == "fireball" and plain["spell_name"] == "Fireball"
    assert upcast["name"] == "Spell Scroll: Fireball (5th-level)"

    sheet = client.get("/api/sheet").json()
    names = {it["name"] for it in sheet["party"][0]["inventory"]}
    assert "Spell Scroll: Fireball" in names
    assert "Spell Scroll: Fireball (5th-level)" in names
