"""Phase 3 acceptance — canonization lifecycle + retrieval (spec §11, §7).

Covers: create_entity is born provisional and retrievable; promote_canon confirms
(and rejects unknown ids); the canon set rebuilds byte-identically on replay; and
the scripted loop end-to-end introduces provisional canon.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from oubliette.canon.models import CanonDraft
from oubliette.dm.brain import Brain
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore, SqliteEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.tools.dispatch import Dispatcher, ToolApplyError
from oubliette.tools.schemas import CreateEntity, PromoteCanon


def _canon_snapshot(canon) -> str:
    recs = [r.model_dump() for r in canon.all()]
    recs.sort(key=lambda r: r["id"])
    return json.dumps(recs, sort_keys=True)


def test_create_entity_is_provisional_and_retrievable():
    session = Session.open(InMemoryEventStore())
    rec = session.emit_create_entity(
        CanonDraft(entity_type="npc", name="the old woman at the well",
                   text="A weathered fortune-teller who trades names for coin."),
        reason="introduced in play",
    )
    assert rec.status == "provisional"
    assert rec.origin in ("recombined", "freestyle")
    assert session.canon.get(rec.id) is not None
    assert len(session.store.of_kind(EventKind.CREATE_ENTITY)) == 1

    hits = session.canon.search("who is the old fortune teller woman")
    assert rec.id in [h.id for h in hits]
    # an unrelated query retrieves nothing
    assert session.canon.search("dragon volcano") == []


def test_promote_canon_confirms_and_rejects_unknown():
    session = Session.open(InMemoryEventStore())
    disp = Dispatcher(session.repo, session.canon)
    rec = session.emit_create_entity(
        CanonDraft(entity_type="npc", name="Captain Bromley", text="A dock-watch captain."),
        reason="met on the pier",
    )

    # unknown id → rejected, nothing mutated
    with pytest.raises(ToolApplyError):
        disp.resolve(PromoteCanon(entity_id="canon-999", reason="nope"))

    # known id → resolves, then session applies → confirmed
    rt = disp.resolve(PromoteCanon(entity_id=rec.id, reason="player cares about Bromley"))
    assert rt.canon_promote == rec.id
    session.emit_promote(rt.canon_promote, rt.reason)
    assert session.canon.get(rec.id).status == "confirmed"
    assert len(session.store.of_kind(EventKind.CANON_PROMOTED)) == 1


def test_create_entity_tool_forces_provisional_draft():
    session = Session.open(InMemoryEventStore())
    disp = Dispatcher(session.repo, session.canon)
    rt = disp.resolve(CreateEntity(entity_type="place", name="The Drowned Lantern",
                                   text="A tavern by the docks.", reason="scene"))
    assert rt.canon_create is not None
    assert rt.canon_create.entity_type == "place"
    # the dispatcher never produces a 'confirmed' or 'authored' draft
    assert rt.canon_create.origin in ("recombined", "freestyle")


def test_canon_rebuilds_byte_identical_on_reload(tmp_path):
    db = str(tmp_path / "canon.sqlite")
    store = SqliteEventStore(db)
    session = Session.open(store)
    woman = session.emit_create_entity(
        CanonDraft(entity_type="npc", name="the old woman at the well", text="fortune-teller"),
        reason="intro")
    session.emit_create_entity(
        CanonDraft(entity_type="place", name="the well", text="an old stone well"), reason="intro")
    session.emit_promote(woman.id, reason="she matters")
    live = _canon_snapshot(session.canon)
    store.close()

    store2 = SqliteEventStore(db)
    reloaded = Session.open(store2)
    assert _canon_snapshot(reloaded.canon) == live
    # ids stable, statuses preserved across the reload
    assert reloaded.canon.get(woman.id).status == "confirmed"
    assert reloaded.canon.get("canon-1").status == "provisional"
    store2.close()


def test_scripted_loop_introduces_provisional_canon():
    session = Session.open(InMemoryEventStore())
    loop = TurnLoop(session, Rng(1, record=session.emit_log), Brain(ScriptedLLMClient()))
    r = asyncio.run(loop.take_turn("I approach the old woman at the well and ask her name."))

    assert any(rt.canon_create is not None for rt in r.applied)
    records = session.canon.all()
    assert len(records) == 1
    assert records[0].status == "provisional"
    assert records[0].entity_type == "npc"
    assert len(session.store.of_kind(EventKind.CREATE_ENTITY)) == 1
