"""W5 — session wrap-up + two-faced notes (DM-robustness arc).

A "session" is a narrative unit, ended by an explicit wrap (distinct from just closing
the window, which is a free pause). On wrap the DM authors two-faced notes from the FULL
session transcript — a spoiler-free player recap + private DM continuity notes — sealing
the session: the notes become durable cross-session memory (dm_private feeds the DM's
context, player_facing the player's chronicle), and the beats window resets. The DM
PROPOSES a wrap via the `end_session` tool (player confirms); the player can also wrap
directly. Offline Mode writes no notes. Firewall: notes are prose, never protected state.
"""

from __future__ import annotations

import asyncio

from oubliette.dm.brain import Brain
from oubliette.dm.context import build_context
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore, SqliteEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.runtime.transcript import current_session_events, session_notes, transcript_turns
from oubliette.tools.dispatch import Dispatcher
from oubliette.tools.schemas import EndSession


def _loop(session: Session) -> TurnLoop:
    return TurnLoop(session, Rng(1, record=session.emit_log), Brain(ScriptedLLMClient()))


def test_end_session_tool_resolves_to_a_wrap_proposal():
    rt = Dispatcher(None, None).resolve(EndSession(reason="the party makes camp"))
    assert rt.wrap_proposed is True and rt.tool == "end_session"


def test_dm_proposes_wrap_without_recording_anything():
    """The proposal is transient — a turn flag, not a stored event. Nothing is sealed until
    the player confirms (calls wrap_session)."""
    s = Session.open(InMemoryEventStore())
    report = asyncio.run(_loop(s).take_turn("I think we should wrap up for tonight"))
    assert report.wrap_pending is True
    assert session_notes(s.store.read_all()) == []          # no wrap recorded yet


def test_wrap_writes_two_faced_notes_and_seals_the_session():
    s = Session.open(InMemoryEventStore())
    loop = _loop(s)
    asyncio.run(loop.take_turn("I look around the market"))
    assert loop.history                                      # a beat accrued this session

    report = asyncio.run(loop.wrap_session(write_notes=True))
    assert report.wrapped and report.player_facing and report.dm_private
    assert loop.history == []                                # beats window reset — session sealed

    notes = session_notes(s.store.read_all())
    assert len(notes) == 1
    assert notes[0]["player_facing"] == report.player_facing
    assert notes[0]["dm_private"] == report.dm_private
    # The wrap marker segments the log: the next turn belongs to a new session.
    asyncio.run(loop.take_turn("accept the task"))
    cur_players = [e.payload.get("text") for e in current_session_events(s.store.read_all())
                   if e.kind == EventKind.PLAYER_MESSAGE.value]
    assert cur_players == ["accept the task"]               # the market look-around is sealed away


def test_offline_wrap_writes_no_notes():
    s = Session.open(InMemoryEventStore())
    loop = _loop(s)
    asyncio.run(loop.take_turn("I look around the market"))
    report = asyncio.run(loop.wrap_session(write_notes=False))
    assert report.wrapped and not report.player_facing and not report.dm_private
    assert session_notes(s.store.read_all()) == [{"index": 1, "player_facing": "", "dm_private": ""}]


def test_wrap_refused_when_nothing_happened():
    s = Session.open(InMemoryEventStore())
    report = asyncio.run(_loop(s).wrap_session(write_notes=True))
    assert report.wrapped is False and report.notice
    assert session_notes(s.store.read_all()) == []


def test_past_notes_reach_the_dm_context_but_not_the_player():
    s = Session.open(InMemoryEventStore())
    loop = _loop(s)
    asyncio.run(loop.take_turn("I look around the market"))
    asyncio.run(loop.wrap_session(write_notes=True))
    dm = session_notes(s.store.read_all())[0]["dm_private"]

    # DM context carries the private note under STORY SO FAR...
    ctx = loop._build_context()
    assert "STORY SO FAR" in ctx and dm in ctx
    # ...but the player's chronicle only ever shows the spoiler-free face.
    turns_after = transcript_turns(s.store.read_all())      # new session: empty transcript
    assert turns_after == []


def test_notes_survive_reload(tmp_path):
    db = str(tmp_path / "wrap.sqlite")
    store = SqliteEventStore(db)
    s = Session.open(store)
    loop = _loop(s)
    asyncio.run(loop.take_turn("I look around the market"))
    asyncio.run(loop.wrap_session(write_notes=True))
    before = session_notes(s.store.read_all())
    store.close()

    reopened = Session.open(SqliteEventStore(db))
    assert session_notes(reopened.store.read_all()) == before   # durable, inert on replay
    assert reopened.repo.pc().gold == s.repo.pc().gold          # state still byte-identical


def test_build_context_renders_story_so_far():
    from oubliette.state.repository import Repository
    # A minimal repo is enough — we only assert the notes block renders.
    repo = Session.open(InMemoryEventStore()).repo
    ctx = build_context(repo, past_notes=["The cult still hunts the amulet.", ""])
    assert "STORY SO FAR" in ctx
    assert "Session 1: The cult still hunts the amulet." in ctx
    assert "Session 2" not in ctx          # empty notes are skipped, not numbered blank


def test_wrap_refused_when_note_writing_fails():
    """Finding #6 (v0.9 playtest): a note-gen failure must NOT seal the session — an
    empty note is a permanent hole in the campaign's memory. The wrap is refused with
    a notice and the session stays open, so the player can simply wrap again."""
    class _FailingNotesBrain(Brain):
        async def write_session_notes(self, *a, **k):
            raise RuntimeError("timed out")

    s = Session.open(InMemoryEventStore())
    loop = TurnLoop(s, Rng(1, record=s.emit_log), _FailingNotesBrain(ScriptedLLMClient()))
    asyncio.run(loop.take_turn("I look around the market"))
    assert loop.history

    report = asyncio.run(loop.wrap_session(write_notes=True))
    assert report.wrapped is False
    assert "try wrapping again" in (report.notice or "")
    assert session_notes(s.store.read_all()) == []          # nothing sealed
    assert loop.history                                     # beats window intact
