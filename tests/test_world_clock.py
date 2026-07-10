"""Living-world W3 — the world clock: a campaign day number derived purely
from the event log.

The contract: campaigns start on Day 1; a long rest — or a night interrupted
trying — snaps the clock to the next morning; travel on the calibrated map
adds its journey time, computed at emit time and stored ON the LOCATION_CHANGED
event (replay-identical even if the map changes later); short rests and moves
on uncalibrated maps cost nothing; every failure path degrades to zero cost —
the clock must never block travel. Existing saves get a correct retroactive
day count from the nights they already slept.
"""

from __future__ import annotations

from types import SimpleNamespace

from oubliette.content.loader import PlaceNode, load_pack
from oubliette.content.schemas import TravelScale
from oubliette.dm.context import build_context
from oubliette.record.events import EventKind
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.session import Session
from oubliette.world.clock import current_day, travel_days


def _session() -> Session:
    return Session.open(InMemoryEventStore())


def _rest(s, rest="long", interrupted=False):
    s.emit_state(EventKind.REST_TAKEN, [], rest=rest, interrupted=interrupted)


def _hop(s, to, days=None):
    payload = {"to": to, "reason": "test"}
    if days is not None:
        payload["days"] = days
    s.store.append(EventKind.LOCATION_CHANGED, payload)


# --- the day number -------------------------------------------------------------

def test_campaigns_start_on_day_one_and_nights_advance_it():
    s = _session()
    assert current_day(s.store.read_all()) == 1
    _rest(s)                                     # night one
    assert current_day(s.store.read_all()) == 2
    _rest(s, rest="short")                       # a breather moves no clock
    assert current_day(s.store.read_all()) == 2
    _rest(s, rest="short", interrupted=True)     # a ruined night still PASSED
    assert current_day(s.store.read_all()) == 3


def test_travel_accumulates_and_a_rest_snaps_to_next_morning():
    s = _session()
    _hop(s, "a", days=0.5)
    assert current_day(s.store.read_all()) == 1      # half a day in: still Day 1
    _hop(s, "b", days=0.5)
    assert current_day(s.store.read_all()) == 2      # a full day on the road
    _hop(s, "c", days=0.5)
    _rest(s)                                         # sleep off the half day
    assert current_day(s.store.read_all()) == 3      # next MORNING, not 2.5+1
    legacy = [e for e in s.store.read_all() if e.kind == EventKind.LOCATION_CHANGED.value]
    assert all("days" in e.payload for e in legacy)


def test_legacy_travel_events_cost_nothing():
    s = _session()
    _hop(s, "somewhere")                             # no `days` field (pre-W3 save)
    assert current_day(s.store.read_all()) == 1


# --- journey time (two-pin calibration) --------------------------------------------

def _world():
    """Three pinned top-level places (gate–mill calibrated at 1 day) plus a
    town with an unpinned sublocation."""
    mk = lambda pid, pos=None, parent=None: PlaceNode(
        id=pid, name=pid, description="", parent=parent, exits=(), position=pos)
    return {
        "market": mk("market", {"x": 50, "y": 60}),
        "gate": mk("gate", {"x": 52, "y": 40}),
        "mill": mk("mill", {"x": 15, "y": 35}),
        "stall": mk("stall", parent="market"),       # inside the market, unpinned
        "nowhere": mk("nowhere"),                    # top-level, unpinned
    }


SCALE = TravelScale(a="gate", b="mill", days=1)


def test_calibrated_distances_quantize_to_half_days():
    places = _world()
    assert travel_days(places, SCALE, "gate", "mill") == 1.0     # the pair itself
    assert travel_days(places, SCALE, "market", "gate") == 0.5   # a shorter hop
    assert travel_days(places, SCALE, "market", "mill") == 1.0
    assert travel_days(places, SCALE, "mill", "gate") == 1.0     # symmetric


def test_sublocations_ride_their_areas_pin_and_local_moves_are_free():
    places = _world()
    # From a stall INSIDE the market to the mill: the market's pin carries it.
    assert travel_days(places, SCALE, "stall", "mill") == 1.0
    # Moving within the town costs nothing (no sibling pair on the calibrated map).
    assert travel_days(places, SCALE, "market", "stall") == 0.0


def test_every_failure_path_degrades_to_free():
    places = _world()
    assert travel_days(places, None, "gate", "mill") == 0.0        # no calibration
    assert travel_days(places, SCALE, "gate", "gate") == 0.0       # going nowhere
    assert travel_days(places, SCALE, "gate", "nowhere") == 0.0    # unpinned target
    assert travel_days(places, SCALE, None, "mill") == 0.0         # no origin
    broken = TravelScale(a="gate", b="ghost", days=1)              # dangling pair
    assert travel_days(places, broken, "gate", "mill") == 0.0


def test_emit_travel_records_the_journey_on_the_event():
    s = _session()
    s.places = _world()
    s.travel_scale = SCALE
    s.location = "gate"
    s.emit_travel("mill", "west along the stream")
    ev = [e for e in s.store.read_all()
          if e.kind == EventKind.LOCATION_CHANGED.value][-1]
    assert ev.payload["days"] == 1.0
    s.emit_travel("stall", "back to the market stalls")   # cross-map leg: mill → market pin
    ev2 = [e for e in s.store.read_all()
           if e.kind == EventKind.LOCATION_CHANGED.value][-1]
    assert ev2.payload["days"] == 1.0
    assert current_day(s.store.read_all()) == 3           # two full days on the road


# --- surfacing ------------------------------------------------------------------------

def test_context_environment_line_carries_the_day():
    s = _session()
    ctx = build_context(s.repo, scene="camp", time_of_day="night",
                        weather="storm", day=12)
    assert "ENVIRONMENT: Day 12 — it is night, weather storm" in ctx
    assert "advances by itself" in ctx


def test_brightvale_ships_a_calibrated_map():
    world = load_pack("brightvale")
    assert world.travel_scale is not None
    assert travel_days(world.places, world.travel_scale,
                       "brightvale_gate", "brightvale_old_mill") == 1.0
    assert travel_days(world.places, world.travel_scale,
                       "brightvale_market", "brightvale_gate") == 0.5
