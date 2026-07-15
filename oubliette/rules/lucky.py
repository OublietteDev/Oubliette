"""Halfling Lucky, story side: when the d20 of a skill check or save lands on
a natural 1 and the roller carries the racial Lucky trait, roll once more and
the new roll stands (RAW — even a second 1 stands; Lucky rerolls once).

Both rolls go through the seeded, logged `Rng`, so each is a durable ROLL
event and replay never re-rolls — the reroll is as replay-stable as the
original. The Arena applies the same trait at its own d20 seams."""

from __future__ import annotations


def is_lucky(char) -> bool:
    """Whether this character carries the RACIAL Lucky trait (halfling).
    Gated to race/subrace source so the Lucky FEAT keeps its own meaning."""
    sheet = getattr(char, "sheet", None)
    if sheet is None:
        return False
    return any(f.name.strip().lower() == "lucky"
               and f.source in ("race", "subrace")
               for f in sheet.features)


def lucky_reroll(rng, char, spec: str, purpose: str, outcome):
    """Apply Lucky to a just-made story roll: on a natural 1 (the first die of
    the spec) by a Lucky roller, roll the same spec again — logged with its own
    purpose so the transcript shows the fortune at work — and return the new
    outcome. Any other roll passes through untouched."""
    if char is None or not outcome.rolls or outcome.rolls[0] != 1:
        return outcome
    if not is_lucky(char):
        return outcome
    return rng.roll(spec, f"{purpose} — Lucky reroll (natural 1)")
