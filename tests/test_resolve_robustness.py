"""The turn loop must survive a malformed model resolution.

A live model (Sonnet) occasionally emits the forced structured-output tool with
empty input, so `TurnResolution.model_validate({})` raises (narration is required).
That must NOT crash the player's turn: the loop treats it like a failed attempt,
retries with feedback, and finally degrades to a graceful narration-only turn with
a meta_notice — never a stack trace, never an empty bubble.
"""

from __future__ import annotations

import asyncio

from oubliette.dm.brain import Brain
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.schemas import TurnResolution


class _EmptyResolveBrain(Brain):
    """Real (scripted) assess; resolve always returns the empty-tool-call error."""

    async def resolve(self, *args, **kwargs) -> TurnResolution:
        return TurnResolution.model_validate({})   # raises ValidationError: narration required


def test_empty_resolution_degrades_gracefully():
    s = Session.open(InMemoryEventStore())
    loop = TurnLoop(s, Rng(1, record=s.emit_log), _EmptyResolveBrain(ScriptedLLMClient()))

    report = asyncio.run(loop.take_turn("I look around the market."))

    assert report.meta_notice and "lost the thread" in report.meta_notice
    assert report.narration                         # the player never gets an empty bubble
    assert report.applied == []                     # a failed turn changes no state
    assert not s.ended
