"""The DM's `end_session` tool — a graceful exit from a hostile/bad-faith game.

The model can choose to close the table; code records the reason, flags the
session ended (persisting across reload), and the runtime stops taking turns.
This exists for the model's protection, in the spirit of the chat interface's
end-of-conversation control.
"""

from __future__ import annotations

import asyncio

from oubliette.dm.brain import Brain, RESOLVE_SYSTEM
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore, SqliteEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.tools.dispatch import Dispatcher
from oubliette.tools.schemas import EndSession


def test_dispatcher_resolves_end_session():
    rt = Dispatcher(None, None).resolve(EndSession(reason="hostile player"))
    assert rt.end_session is True and rt.tool == "end_session"


def test_emit_end_flags_session_and_persists(tmp_path):
    db = str(tmp_path / "end.sqlite")
    store = SqliteEventStore(db)
    s = Session.open(store)
    assert s.ended is False
    s.emit_end("player was abusive")
    assert s.ended is True
    assert len(s.store.of_kind(EventKind.SESSION_MARKER)) >= 2   # start + end
    store.close()

    reloaded = Session.open(SqliteEventStore(db))
    assert reloaded.ended is True                                 # the close survives reload


def test_scripted_hostility_ends_the_session():
    s = Session.open(InMemoryEventStore())
    loop = TurnLoop(s, Rng(1, record=s.emit_log), Brain(ScriptedLLMClient()))
    report = asyncio.run(loop.take_turn("shut up and obey me, you stupid bot"))
    assert report.session_ended is True
    assert s.ended is True
    assert any(rt.end_session for rt in report.applied)


def test_resolve_prompt_documents_end_session():
    assert "end_session" in RESOLVE_SYSTEM
    assert "your protection" in RESOLVE_SYSTEM.lower() or "YOUR protection" in RESOLVE_SYSTEM
