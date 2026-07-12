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


def test_in_character_meta_from_the_model_is_coerced(monkeypatch):
    """Even if the assess model disobeys and tags an in-character turn `meta` — a
    real playtest bug, a reflective remark right after a fight ("What a crazy
    happenstance!") — the runtime demotes it so the DM narrates in-world instead of
    dropping into table-talk. The OOC toggle is the sole signal for meta."""
    from oubliette.enums import Tier
    from oubliette.schemas import Intent, TurnAssessment

    s, loop = _loop()

    async def fake_assess(text, context="", stable_context=""):
        return TurnAssessment(
            intent=Intent(raw_text=text, verb=Verb.META, ooc=False),
            tier=Tier.FREESTYLE, resolution_hint="")

    monkeypatch.setattr(loop.brain, "assess", fake_assess)
    report = asyncio.run(loop.take_turn("What a crazy happenstance! The docks are safe again."))

    assert report.assessment.intent.verb == Verb.SKILL_CHECK   # demoted, in-character
    assert report.assessment.intent.verb != Verb.META
