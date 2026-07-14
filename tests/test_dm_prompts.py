"""Guard tests for the DM prompt — the resolve system prompt must keep covering
the rough edges the model flagged in interview #2 (so they aren't silently lost):
the out-of-character `meta` verb, that the transact number IS the price, and the
create-a-new-place-then-let-the-player-travel timing. Plus the playtest-flagged
player-agency rule: never voice a hero; companions are the DM's to voice.
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


def test_player_agency_heroes_are_not_the_dms_to_voice():
    """Brett's playtest note: the DM sometimes had heroes speaking or acting
    unprompted. The rule — hands off the heroes, companions are fair game."""
    assert "PLAYER AGENCY" in RESOLVE_SYSTEM
    assert "never invent a hero's dialogue" in RESOLVE_SYSTEM
    assert "COMPANIONS are the exception" in RESOLVE_SYSTEM
