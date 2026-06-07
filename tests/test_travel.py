"""Travel as a DM tool + place hierarchy (sublocations).

The DM proposes a `travel` to a place; code validates it, moves the party,
updates the scene + who's present, and records a LOCATION_CHANGED event so a
reload lands the party where they left off. Places can be sublocations of other
places (Atria > Brightvale > Marketplace; dungeon > rooms).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from oubliette.content.loader import PackValidationError, PlaceNode, load_pack
from oubliette.dm.brain import Brain
from oubliette.dm.context import _reachable, build_context
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore, SqliteEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.state.models import Character
from oubliette.state.repository import InMemoryRepository
from oubliette.tools.dispatch import Dispatcher, ToolApplyError
from oubliette.tools.schemas import Travel


# --- sublocation validation -------------------------------------------------
def _write_pack(tmp_path, places, pid="t"):
    d = tmp_path / pid
    d.mkdir(parents=True)
    files = {
        "pack": {"id": pid, "schema_version": 1, "name": "T", "version": "1.0.0",
                 "entry_scenario": "s"},
        "items": [], "statblocks": [], "npcs": [], "places": places,
        "scenarios": [{"id": "s", "name": "S", "start_location": places[0]["id"],
                       "party_source": "default",
                       "default_party": [{"id": "pc", "name": "Hero", "kind": "pc"}]}],
    }
    for k, v in files.items():
        (d / f"{k}.json").write_text(json.dumps(v), encoding="utf-8")
    return tmp_path


def test_parent_must_resolve(tmp_path):
    root = _write_pack(tmp_path, [
        {"id": "area", "name": "Area", "description": "d"},
        {"id": "room", "name": "Room", "description": "d", "parent": "ghost"},
    ])
    with pytest.raises(PackValidationError) as e:
        load_pack("t", packs_root=root)
    assert any("unknown place 'ghost'" in m for m in e.value.errors)


def test_self_parent_flagged(tmp_path):
    root = _write_pack(tmp_path, [{"id": "loop", "name": "Loop", "description": "d", "parent": "loop"}])
    with pytest.raises(PackValidationError) as e:
        load_pack("t", packs_root=root)
    assert any("its own parent" in m for m in e.value.errors)


# --- reachable destinations (exits + children + siblings) -------------------
def _hierarchy():
    return {
        "town": PlaceNode("town", "Town", "d", None, ()),
        "market": PlaceNode("market", "Market", "d", "town", ("inn",)),
        "inn": PlaceNode("inn", "Inn", "d", "town", ()),
        "cellar": PlaceNode("cellar", "Cellar", "d", "inn", ()),
    }


def test_reachable_exits_children_siblings():
    places = _hierarchy()
    # market: exit→inn, sibling (under town)→inn → {inn}
    assert {p.id for p in _reachable("market", places)} == {"inn"}
    # inn: sibling→market, child→cellar → {market, cellar}
    assert {p.id for p in _reachable("inn", places)} == {"market", "cellar"}
    # unknown / no location → nothing
    assert _reachable(None, places) == []


def test_context_lists_destinations():
    places = {"market": PlaceNode("market", "Market", "d", None, ("gate",)),
              "gate": PlaceNode("gate", "North Gate", "d", None, ())}
    repo = InMemoryRepository([Character(id="pc", name="You", kind="pc")], [], "pc")
    ctx = build_context(repo, "scene", location="market", places=places)
    assert "WHERE YOU CAN GO" in ctx
    assert "North Gate" in ctx and "id: gate" in ctx


# --- the travel tool --------------------------------------------------------
def test_dispatcher_resolves_travel_by_id_and_name():
    places = {"gate": PlaceNode("gate", "North Gate", "d", None, ())}
    disp = Dispatcher(None, None, places)
    assert disp.resolve(Travel(to="gate", reason="x")).travel_to == "gate"
    assert disp.resolve(Travel(to="North Gate", reason="x")).travel_to == "gate"
    with pytest.raises(ToolApplyError):
        disp.resolve(Travel(to="nowhere", reason="x"))


def test_travel_updates_location_scene_and_survives_reload(tmp_path):
    db = str(tmp_path / "travel.sqlite")
    store = SqliteEventStore(db)
    s = Session.open(store)
    assert s.location == "brightvale_market"
    market_scene = s.scene

    s.emit_travel("brightvale_gate", reason="walk north")
    assert s.location == "brightvale_gate"
    assert s.scene != market_scene and "gate" in s.scene.lower()
    store.close()

    # reload lands the party back at the gate (LOCATION_CHANGED folded over the start)
    reloaded = Session.open(SqliteEventStore(db))
    assert reloaded.location == "brightvale_gate"
    assert reloaded.scene == s.scene


def test_scripted_travel_moves_party_and_rescopes_present():
    s = Session.open(InMemoryEventStore())
    loop = TurnLoop(s, Rng(1, record=s.emit_log), Brain(ScriptedLLMClient()))

    before = build_context(s.repo, s.scene, location=s.location, places=s.places)
    assert "Thom" in before                       # Thom is home at the market

    r = asyncio.run(loop.take_turn("I travel to the north gate."))
    assert s.location == "brightvale_gate"
    assert any(rt.travel_to == "brightvale_gate" for rt in r.applied)
    assert len(s.store.of_kind(EventKind.LOCATION_CHANGED)) == 1

    after = build_context(s.repo, s.scene, location=s.location, places=s.places)
    assert "Thom" not in after                    # Thom isn't at the gate
