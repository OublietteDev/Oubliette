"""The DM's PRESENT list is scoped to the party's current location.

As a world grows to dozens of NPCs, listing every one in the prompt each turn is
noisy and invites the DM to reference someone who isn't here. Only NPCs whose
home is the party's current location are "present"; the rest stay offstage (but
remain retrievable via canon search).
"""

from __future__ import annotations

from oubliette.dm.context import build_context
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.session import Session
from oubliette.state.models import Character
from oubliette.state.repository import InMemoryRepository


def _repo():
    pc = Character(id="pc", name="You", kind="pc")
    here = Character(id="here", name="Local Lily", kind="npc", home_location="market")
    away = Character(id="away", name="Gate Gareth", kind="npc", home_location="gate")
    nowhere = Character(id="amb", name="Driftwood Dan", kind="npc")   # no home
    return InMemoryRepository([pc, here, away, nowhere], [], "pc")


def test_present_list_scoped_to_location():
    ctx = build_context(_repo(), "a scene", location="market")
    assert "Local Lily" in ctx           # homed here → present
    assert "Gate Gareth" not in ctx      # homed elsewhere → offstage
    assert "Driftwood Dan" not in ctx     # unplaced → not in any scene


def test_no_location_shows_all_npcs():
    # back-compat: a custom seed with no pack location lists everyone
    ctx = build_context(_repo(), "a scene")
    for name in ("Local Lily", "Gate Gareth", "Driftwood Dan"):
        assert name in ctx


def test_session_carries_start_location():
    session = Session.open(InMemoryEventStore())
    assert session.location == "brightvale_market"
    # Thom is homed at the market, so he's present at the start
    ctx = build_context(session.repo, session.scene, location=session.location)
    assert "Thom" in ctx
