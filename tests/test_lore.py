"""Authored lore — world history/legend the DM can draw on.

Lore entries become authored, retrievable canon (like NPCs/places), with their
"about" subjects riding along as search keywords so the lore surfaces by SITUATION
(the party's location + who's present), not only when someone names it. Lore gets a
generous slice of the DM's context so it can be retold, not clipped.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from oubliette.canon.store import CanonStore
from oubliette.content.loader import (_PACKS_ROOT, PackValidationError, PlaceNode,
                                      load_pack)

# The Atria pack is local-only until the campaign is finished (untracked, so it
# never ships half-built) — its end-to-end tests run where the folder exists.
_HAS_ATRIA = (_PACKS_ROOT / "atria" / "pack.json").exists()
from oubliette.dm.brain import Brain
from oubliette.dm.context import LORE_CHARS, build_context
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.state.models import Character
from oubliette.state.repository import InMemoryRepository


def _write_pack(tmp_path, *, lore=None, places=None, npcs=None, pid="t"):
    d = tmp_path / pid
    d.mkdir(parents=True)
    places = places or [{"id": "harbor", "name": "Harbor", "description": "A salty harbor."}]
    files = {
        "pack": {"id": pid, "schema_version": 1, "name": "T", "version": "1.0.0",
                 "entry_scenario": "s"},
        "items": [], "statblocks": [], "npcs": npcs or [], "places": places,
        "scenarios": [{"id": "s", "name": "S", "start_location": places[0]["id"],
                       "party_source": "default",
                       "default_party": [{"id": "pc", "name": "Hero", "kind": "pc"}]}],
    }
    if lore is not None:
        files["lore"] = lore
    for k, v in files.items():
        (d / f"{k}.json").write_text(json.dumps(v), encoding="utf-8")
    return tmp_path


def _store(canon_records):
    store = CanonStore()
    for r in canon_records:
        store.add(r)
    return store


# --- loading ----------------------------------------------------------------
def test_lore_becomes_authored_canon(tmp_path):
    root = _write_pack(tmp_path, lore=[{
        "id": "founding", "title": "The Founding of Harbor",
        "text": "Long ago a fisher made a pact with the tide.",
        "subjects": ["Harbor", "Old Salt"], "tags": ["founding"]}])
    w = load_pack("t", packs_root=root)
    rec = next(r for r in w.canon if r.id == "founding")
    assert rec.entity_type == "lore" and rec.name == "The Founding of Harbor"
    assert rec.origin == "authored" and rec.status == "confirmed"
    assert "Harbor" in rec.keywords and "Old Salt" in rec.keywords and "founding" in rec.keywords


def test_pack_without_lore_still_loads(tmp_path):
    root = _write_pack(tmp_path)                  # no lore.json written
    w = load_pack("t", packs_root=root)
    assert not any(r.entity_type == "lore" for r in w.canon)


def test_existing_packs_still_load():
    for pid in ("brightvale",) + (("atria",) if _HAS_ATRIA else ()):
        load_pack(pid)                            # must not raise


def test_duplicate_lore_id_flagged(tmp_path):
    root = _write_pack(tmp_path, lore=[
        {"id": "x", "title": "A", "text": "..."},
        {"id": "x", "title": "B", "text": "..."}])
    with pytest.raises(PackValidationError) as e:
        load_pack("t", packs_root=root)
    assert any("duplicate id 'x'" in m for m in e.value.errors)


# --- retrieval by subject / situation ---------------------------------------
def test_lore_surfaces_by_subject_not_in_text(tmp_path):
    root = _write_pack(tmp_path, lore=[{
        "id": "dragon_tale", "title": "The Guardian",
        "text": "A great beast keeps the bay full and the town safe.",  # no "Seraphel"
        "subjects": ["Seraphel"]}])
    store = _store(load_pack("t", packs_root=root).canon)
    hits = store.search("what can you tell me about Seraphel?")
    assert "dragon_tale" in [h.id for h in hits]


def test_situational_query_includes_location_and_present():
    pc = Character(id="pc", name="You", kind="pc")
    here = Character(id="bromley", name="Captain Bromley", kind="npc", home_location="docks")
    away = Character(id="gov", name="Governor", kind="npc", home_location="hall")
    repo = InMemoryRepository([pc, here, away], [], "pc")
    session = Session.open(InMemoryEventStore(), seed=lambda: repo)
    session.places = {"docks": PlaceNode("docks", "Silverfin Docks", "salt", None, ())}
    session.location = "docks"
    loop = TurnLoop(session, Rng(1, record=session.emit_log), Brain(ScriptedLLMClient()))

    q = loop._retrieval_query("I look around")
    assert "Silverfin Docks" in q            # the place name
    assert "Captain Bromley" in q            # present here
    assert "Governor" not in q               # homed elsewhere


def test_situational_query_includes_parent_areas():
    """Lore anchored to a city must surface while the party stands in its districts:
    the query walks up the parent chain and includes each enclosing area's name."""
    repo = InMemoryRepository([Character(id="pc", name="You", kind="pc")], [], "pc")
    session = Session.open(InMemoryEventStore(), seed=lambda: repo)
    session.places = {
        "brightvale": PlaceNode("brightvale", "Brightvale", "city", None, ()),
        "market": PlaceNode("market", "The Coin Quarter", "market", "brightvale", ()),
    }
    session.location = "market"
    loop = TurnLoop(session, Rng(1, record=session.emit_log), Brain(ScriptedLLMClient()))

    q = loop._retrieval_query("I look around")
    assert "The Coin Quarter" in q           # the district itself
    assert "Brightvale" in q                 # the enclosing city — its lore now surfaces


@pytest.mark.skipif(not _HAS_ATRIA, reason="atria pack is local-only until finished")
def test_atria_city_lore_surfaces_inside_a_district():
    """End-to-end against the real Atria pack: standing in the Coin Quarter (a
    district of Brightvale), the founding lore is retrievable via the parent name."""
    world = load_pack("atria")
    store = _store(world.canon)
    # the query the loop builds in the Coin Quarter now includes its parent, Brightvale
    hits = [h.id for h in store.search("I look around The Coin Quarter (Market) Brightvale")]
    assert "the_founding_of_brightvale" in hits


# --- context budget ---------------------------------------------------------
def test_world_lore_section_gets_generous_budget(tmp_path):
    long_text = "The tale. " * 60           # ~600 chars, well over a snippet
    root = _write_pack(tmp_path, lore=[{"id": "saga", "title": "A Long Saga", "text": long_text}])
    lore_rec = next(r for r in load_pack("t", packs_root=root).canon if r.id == "saga")
    repo = InMemoryRepository([Character(id="pc", name="You", kind="pc")], [], "pc")
    ctx = build_context(repo, "scene", canon=[lore_rec])
    assert "WORLD LORE" in ctx
    assert "A Long Saga:" in ctx
    assert long_text.strip()[:300] in ctx    # far more than the 160-char canon snippet
    assert len(long_text) <= LORE_CHARS      # (sanity) this entry isn't even truncated
