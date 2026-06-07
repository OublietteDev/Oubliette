"""The explicit out-of-character signal. The composer toggle (an `ooc` flag on the
turn) is authoritative: when set, the turn is table-talk (meta) with no combat /
trade / tools; when not set, the message is in-character and the DM never gets a
chance to mistake it for breaking character. Diagnosed from a real playtest where
the model over-classified `meta` even on lines like "Back in character: Wizardo…".
"""

from __future__ import annotations

import asyncio

from oubliette.dm.brain import Brain
from oubliette.enums import Verb
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session


def _loop():
    s = Session.open(InMemoryEventStore())
    return s, TurnLoop(s, Rng(1, record=s.emit_log), Brain(ScriptedLLMClient()))


def test_ooc_forces_meta_and_skips_combat():
    s, loop = _loop()
    # in-character this would summon combat; flagged OOC it must not
    report = asyncio.run(loop.take_turn("I attack the bandit!", ooc=True))
    assert report.assessment.intent.verb == Verb.META
    assert report.assessment.intent.ooc is True
    assert report.combat_result is None and report.trade_open is None
    assert report.applied == []                    # table-talk emits no tools


def test_in_character_turn_is_not_meta():
    s, loop = _loop()
    report = asyncio.run(loop.take_turn("I look around the market", ooc=False))
    assert report.assessment.intent.verb != Verb.META
