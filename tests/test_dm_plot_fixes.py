"""Fixes from the 2026-07-15 playtest post-mortem (the Hammerdeep incident):
the DM must never re-create a place that already exists (travel instead), the
context tells it the world is bigger than the adjacent-places list, and a
staged fight no longer writes two continuity beats for one player turn."""

from __future__ import annotations

import pytest

from oubliette.dm.context import build_context
from oubliette.record.events import EventKind
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop, TurnReport
from oubliette.runtime.session import Session
from oubliette.runtime.transcript import recent_beats
from oubliette.record.rng import Rng
from oubliette.dm.brain import Brain
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.tools.dispatch import Dispatcher, ToolApplyError
from oubliette.tools.schemas import CreateEntity


def _session() -> Session:
    return Session.open(InMemoryEventStore(), pack_id="brightvale")


def test_creating_an_existing_place_is_refused_toward_travel():
    session = _session()
    disp = Dispatcher(session.repo, places=session.places)
    known = next(iter(session.places.values()))
    with pytest.raises(ToolApplyError, match="travel"):
        disp.resolve(CreateEntity(entity_type="place", name=known.name,
                                  text="a duplicate", reason="test"))
    # A genuinely new place (and any non-place entity) still creates fine.
    rt = disp.resolve(CreateEntity(entity_type="place", name="The Gloamway",
                                   text="a lightless stair", reason="test"))
    assert rt.canon_create is not None
    rt2 = disp.resolve(CreateEntity(entity_type="npc", name=known.name,
                                    text="an NPC may share a place's name",
                                    reason="test"))
    assert rt2.canon_create is not None


def test_context_says_the_world_is_bigger_than_the_list():
    session = _session()
    ctx = build_context(session.repo, "a scene", location=session.location,
                        places=session.places, ruleset=session.ruleset)
    assert "WHERE YOU CAN GO" in ctx
    assert "the wider world holds more" in ctx
    assert "NEVER create_entity a place" in ctx


def _assessment():
    from oubliette.schemas import Intent, TurnAssessment
    return TurnAssessment(
        intent=Intent(raw_text="I test the walls.", verb="attack"),
        tier="freestyle")


def test_a_staged_fight_writes_one_beat_not_two():
    session = _session()
    loop = TurnLoop(session, Rng(seed=1, record=session.emit_log),
                    Brain(ScriptedLLMClient()))
    staged = TurnReport(player_text="I test the walls.",
                        assessment=_assessment(),
                        narration="Steel rings out — the fight is upon you.",
                        combat_pending=True)
    loop._record_beat(staged, caused_by=None)
    assert loop.history == []                      # the beat waits for the resolution
    events = session.store.read_all()
    narrs = [e for e in events if e.kind == EventKind.NARRATION_RECORDED.value]
    assert narrs and narrs[-1].payload["narration"].startswith("Steel rings out")
    assert narrs[-1].payload["beat"] == ""         # transcript kept, beat empty
    assert recent_beats(events, 8) == []           # and reload skips it too

    resolved = TurnReport(player_text="I test the walls.",
                          assessment=_assessment(),
                          narration="You slip away before it is settled.")
    loop._record_beat(resolved, caused_by=None)
    assert len(loop.history) == 1                  # exactly one beat for the turn
    assert recent_beats(session.store.read_all(), 8) == loop.history
