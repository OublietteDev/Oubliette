"""W2 — durable narration (DM-robustness arc).

The DM is called fresh every turn; its narration and short-term memory were
transient (returned in the TurnReport, held only in `TurnLoop.history`), so a
reload lost all narrative continuity. W2 makes each completed turn durable: a
NARRATION_RECORDED event stores the verbatim narration (rebuilds the player
transcript) plus the compact continuity beat (rehydrates the DM's short-term
memory). It is model OUTPUT made durable — inert prose, a no-op on replay, never
an authority the model can use to assert protected state (the firewall holds).
W3 consumes this; here we prove the capture itself.
"""

from __future__ import annotations

import asyncio

from oubliette.dm.brain import Brain
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore, SqliteEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session


def _loop(session: Session) -> TurnLoop:
    return TurnLoop(session, Rng(1, record=session.emit_log), Brain(ScriptedLLMClient()))


def test_turn_records_one_narration_event_verbatim():
    s = Session.open(InMemoryEventStore())
    loop = _loop(s)
    report = asyncio.run(loop.take_turn("I look around the market"))

    recorded = s.store.of_kind(EventKind.NARRATION_RECORDED)
    assert len(recorded) == 1                       # exactly one per narrated turn
    ev = recorded[0]
    assert ev.payload["narration"] == report.narration   # stored verbatim, not clipped
    assert ev.payload["beat"] == loop.history[-1]         # beat == the in-memory continuity beat


def test_narration_links_to_its_player_message():
    s = Session.open(InMemoryEventStore())
    asyncio.run(_loop(s).take_turn("I look around the market"))

    pmsg = s.store.of_kind(EventKind.PLAYER_MESSAGE)[-1]
    narr = s.store.of_kind(EventKind.NARRATION_RECORDED)[-1]
    assert narr.caused_by == pmsg.seq               # the durable record points back at the prompt
    assert narr.seq > pmsg.seq                       # and lands after it in the log


def test_narration_carries_no_ops_and_is_inert_on_replay(tmp_path):
    """The firewall: narration is prose, never protected state. It carries no ops, so
    reopening the save reproduces identical authoritative state — the narration events
    ride along untouched and change nothing."""
    db = str(tmp_path / "narr.sqlite")
    store = SqliteEventStore(db)
    s = Session.open(store)
    loop = _loop(s)
    asyncio.run(loop.take_turn("I look around the market"))
    asyncio.run(loop.take_turn("accept the task"))    # starts a quest → real state change too
    live_beats = list(loop.history)
    live_gold = s.repo.pc().gold
    live_quests = len(s.quests.all())
    for ev in s.store.of_kind(EventKind.NARRATION_RECORDED):
        assert ev.state_ops() == []                   # no ops — inert record
    store.close()

    reopened = Session.open(SqliteEventStore(db))
    # Protected state replays byte-identical; narration events were pure no-ops.
    assert reopened.repo.pc().gold == live_gold
    assert len(reopened.quests.all()) == live_quests
    # And the durable beats are there to rehydrate the DM's short-term memory (W3).
    beats = [e.payload["beat"] for e in reopened.store.of_kind(EventKind.NARRATION_RECORDED)]
    assert beats == live_beats
    assert len(beats) == 2
