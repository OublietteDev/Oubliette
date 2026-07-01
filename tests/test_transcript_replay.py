"""W3 — current-session continuity on reload (DM-robustness arc).

Built on W2's durable NARRATION_RECORDED record. Two losses a reload used to inflict:
the player's chat (client-side DOM only) and the DM's short-term memory (in-memory
`TurnLoop.history`). W3 rebuilds both for the session in progress — transcript for the
player, recent beats for the DM — and lays the session-segmentation primitive (wrap
markers) that W5's per-session notes will stand on.
"""

from __future__ import annotations

import asyncio

from oubliette.dm.brain import Brain
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore, SqliteEventStore
from oubliette.runtime.loop import HISTORY_CAP, TurnLoop
from oubliette.runtime.session import Session
from oubliette.runtime.transcript import (WRAP_MARKER, current_session_events,
                                          recent_beats, transcript_turns)


def _loop(session: Session) -> TurnLoop:
    return TurnLoop(session, Rng(1, record=session.emit_log), Brain(ScriptedLLMClient()))


def _play(session: Session, *lines: str) -> TurnLoop:
    loop = _loop(session)
    for line in lines:
        asyncio.run(loop.take_turn(line))
    return loop


def test_transcript_pairs_player_and_dm_in_order():
    s = Session.open(InMemoryEventStore())
    _play(s, "I look around the market", "accept the task")

    turns = transcript_turns(s.store.read_all())
    roles = [t["role"] for t in turns]
    assert roles == ["player", "dm", "player", "dm"]        # strict player→DM alternation
    assert turns[0]["text"] == "I look around the market"    # verbatim player text
    assert turns[1]["text"].strip()                          # DM narration present, non-empty
    assert "Bless you" in turns[3]["text"]                   # the quest-accept narration


def test_reload_rehydrates_dm_short_term_memory(tmp_path):
    """A fresh TurnLoop built on an existing save resumes with the same recent-beats
    memory it had before — not an empty head."""
    db = str(tmp_path / "tx.sqlite")
    store = SqliteEventStore(db)
    s = Session.open(store)
    live = _play(s, "I look around the market", "accept the task")
    live_history = list(live.history)
    assert live_history                                       # sanity: it accrued beats
    store.close()

    reopened = Session.open(SqliteEventStore(db))
    resumed = _loop(reopened)                                 # construction rehydrates history
    assert resumed.history == live_history                    # picked up exactly where it left off


def test_reload_restores_player_transcript(tmp_path):
    db = str(tmp_path / "tx2.sqlite")
    store = SqliteEventStore(db)
    s = Session.open(store)
    _play(s, "I look around the market")
    before = transcript_turns(s.store.read_all())
    store.close()

    reopened = Session.open(SqliteEventStore(db))
    assert transcript_turns(reopened.store.read_all()) == before   # survives reload


def test_recent_beats_caps_to_limit():
    s = Session.open(InMemoryEventStore())
    _play(s, *["I look around the market"] * 6)
    beats = recent_beats(s.store.read_all(), 3)
    assert len(beats) == 3
    all_beats = recent_beats(s.store.read_all(), HISTORY_CAP)
    assert beats == all_beats[-3:]                            # it's the TAIL, the recent ones


def test_wrap_marker_segments_the_session():
    """The segmentation primitive W5 will use: a wrap marker starts a new session, so
    the current-session readers see only what came after it."""
    s = Session.open(InMemoryEventStore())
    _play(s, "I look around the market")                      # session 1 content
    # Simulate W5's wrap (the tool doesn't exist yet — emit the marker directly).
    s.store.append(EventKind.SESSION_MARKER, {"marker": WRAP_MARKER, "reason": "night 1 done"})
    _play(s, "accept the task")                               # session 2 content

    cur = current_session_events(s.store.read_all())
    # Only the post-wrap turn is "current"; the market look-around belongs to session 1.
    player_texts = [e.payload.get("text") for e in cur
                    if e.kind == EventKind.PLAYER_MESSAGE.value]
    assert player_texts == ["accept the task"]
    turns = transcript_turns(s.store.read_all())
    assert all("look around" not in t["text"] for t in turns)  # session-1 chat excluded
    assert any(t["text"] == "accept the task" for t in turns)


def test_force_end_marker_does_not_segment():
    """A force-end ('end' marker) is terminal, not a session boundary — it must not be
    mistaken for a wrap and hide the session's own transcript."""
    s = Session.open(InMemoryEventStore())
    _play(s, "I look around the market")
    s.emit_force_end("hostile")                               # writes an 'end' marker
    turns = transcript_turns(s.store.read_all())
    assert any("look around" in t["text"] for t in turns)     # still the current session
