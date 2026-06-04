"""The single source of dice. Every roll flows through here and is emitted as a
ROLL event (spec §4.3), so the rules engine stays pure and replay never re-rolls.

`record` is the session's event sink (`Session.emit_log`). Replay never builds an
Rng — past rolls live in the log; future rolls are recorded as they happen.
"""

from __future__ import annotations

import random
import re
from typing import Callable

from pydantic import BaseModel

from .events import EventKind

_DICE_RE = re.compile(r"^\s*(\d+)d(\d+)\s*([+-]\s*\d+)?\s*$", re.IGNORECASE)


class RollOutcome(BaseModel):
    spec: str
    rolls: list[int]
    modifier: int
    total: int
    purpose: str


def _parse(spec: str) -> tuple[int, int, int]:
    m = _DICE_RE.match(spec)
    if not m:
        raise ValueError(f"unparseable dice spec: {spec!r}")
    count, sides = int(m.group(1)), int(m.group(2))
    modifier = int(m.group(3).replace(" ", "")) if m.group(3) else 0
    return count, sides, modifier


class Rng:
    """Seeded for reproducible live play. `record(kind, **payload)` receives each
    ROLL (typically `Session.emit_log`); pass None to roll without recording."""

    def __init__(self, seed: int, record: Callable[..., object] | None = None) -> None:
        self._rand = random.Random(seed)
        self._record = record

    def roll(self, spec: str, purpose: str) -> RollOutcome:
        count, sides, modifier = _parse(spec)
        rolls = [self._rand.randint(1, sides) for _ in range(count)]
        total = sum(rolls) + modifier
        outcome = RollOutcome(
            spec=spec, rolls=rolls, modifier=modifier, total=total, purpose=purpose
        )
        if self._record is not None:
            self._record(EventKind.ROLL, **outcome.model_dump())
        return outcome
