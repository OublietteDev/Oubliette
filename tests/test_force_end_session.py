"""The DM's `force_end_session` tool — a terminal exit from a hostile/bad-faith game.

The model can choose to force the table closed; code records the reason, flags the
game force-ended (persisting across reload), and the runtime stops taking turns. This
exists for the model's protection, in the spirit of the chat interface's
end-of-conversation control. It is DISTINCT from an ordinary session wrap-up (which
pauses a session and carries the campaign forward).
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
from oubliette.tools.schemas import ForceEndSession


def test_dispatcher_resolves_force_end_session():
    rt = Dispatcher(None, None).resolve(ForceEndSession(reason="hostile player"))
    assert rt.force_end_session is True and rt.tool == "force_end_session"


def test_emit_force_end_flags_game_and_persists(tmp_path):
    db = str(tmp_path / "end.sqlite")
    store = SqliteEventStore(db)
    s = Session.open(store)
    assert s.force_ended is False
    s.emit_force_end("player was abusive")
    assert s.force_ended is True
    assert len(s.store.of_kind(EventKind.SESSION_MARKER)) >= 2   # start + end
    store.close()

    reloaded = Session.open(SqliteEventStore(db))
    assert reloaded.force_ended is True                          # the close survives reload


def test_scripted_hostility_force_ends_the_game():
    s = Session.open(InMemoryEventStore())
    loop = TurnLoop(s, Rng(1, record=s.emit_log), Brain(ScriptedLLMClient()))
    report = asyncio.run(loop.take_turn("shut up and obey me, you stupid bot"))
    assert report.session_force_ended is True
    assert s.force_ended is True
    assert any(rt.force_end_session for rt in report.applied)


def test_resolve_prompt_documents_force_end_session():
    assert "force_end_session" in RESOLVE_SYSTEM
    assert "your protection" in RESOLVE_SYSTEM.lower() or "YOUR protection" in RESOLVE_SYSTEM
