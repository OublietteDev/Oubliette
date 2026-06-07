"""Guard tests for the DM prompt — the resolve system prompt must keep covering
the rough edges the model flagged in interview #2 (so they aren't silently lost):
the out-of-character `meta` verb, that the transact number IS the price, and the
create-a-new-place-then-let-the-player-travel timing.
"""

from __future__ import annotations

from oubliette.dm.brain import RESOLVE_SYSTEM


def test_meta_verb_is_documented():
    assert "META" in RESOLVE_SYSTEM
    assert "out-of-character" in RESOLVE_SYSTEM


def test_pricing_clarifies_the_number_is_the_price():
    assert "no separate price field" in RESOLVE_SYSTEM


def test_new_place_is_not_travelled_same_turn():
    assert "do NOT travel them there" in RESOLVE_SYSTEM
    assert "let the player choose to go" in RESOLVE_SYSTEM
