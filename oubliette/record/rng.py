"""The single source of dice. Every roll flows through here and is logged, so that
in Phase 2 these become replayable `ROLL` events and the rules engine stays pure."""

from __future__ import annotations

import random
import re

from pydantic import BaseModel

from .log import DebugLog

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
    """Seeded so Phase 0 play and tests are reproducible (D9 prefigured)."""

    def __init__(self, seed: int, log: DebugLog) -> None:
        self._rand = random.Random(seed)
        self._log = log

    def roll(self, spec: str, purpose: str) -> RollOutcome:
        count, sides, modifier = _parse(spec)
        rolls = [self._rand.randint(1, sides) for _ in range(count)]
        total = sum(rolls) + modifier
        outcome = RollOutcome(
            spec=spec, rolls=rolls, modifier=modifier, total=total, purpose=purpose
        )
        # In Phase 2 this append becomes a real ROLL event (spec §4.3).
        self._log.append("roll", **outcome.model_dump())
        return outcome
