"""Living-world W4 — timed world events: the world moves whether the party
attends or not, decided by code against the campaign clock, styled by the DM.

The contract: an event fires once its day arrives AND its conditions hold
(late is fine — the schedule isn't consumed by waiting); one per turn, in
authored order; recurring events re-arm after their interval; the WORLD_EVENT
record IS the state — standing shifts, armed encounters, and quest offers all
derive from it (nothing applied on replay); an event's standing shift never
reveals a hidden faction; presence at the venue (or inside it) chooses
witnessed-live vs news-as-rumor; and the linter refuses an event-only
encounter no event ever arms.
"""

from __future__ import annotations

import asyncio

from oubliette.content.loader import (
    PlaceNode,
    _lint_world_events,
    load_pack,
)
from oubliette.content.schemas import (
    EventEncounter,
    EventEnvironment,
    EventStanding,
    Faction,
    KeyedEncounter,
    KeyedEnemy,
    KeyedTrigger,
    MinStanding,
    Place,
    WorldEvent,
)
from oubliette.dm.brain import Brain
from oubliette.dm.context import build_context
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.world.events import (
    armed_encounters,
    due_event,
    quest_overlay,
    standing_deltas,
)
from oubliette.world.factions import known_ids, standing_map
from oubliette.world.keyed import due_encounter


def _event(eid="omen", on_day=None, every=None, **kw):
    kw.setdefault("announce", "something stirs")
    return WorldEvent(id=eid, title=eid, on_day=on_day, every_days=every, **kw)


def _session() -> Session:
    return Session.open(InMemoryEventStore())


def _fire(s, eid, day, place=None, present=False):
    s.emit_log(EventKind.WORLD_EVENT, event_id=eid, day=day,
               place=place, present=present)


# --- the schedule ---------------------------------------------------------------

def test_one_shots_fire_on_or_after_their_day_and_only_once():
    s = _session()
    wev = {"omen": _event(on_day=3)}
    assert due_event(wev, s.store.read_all(), day=2) is None
    assert due_event(wev, s.store.read_all(), day=5).id == "omen"   # late is fine
    _fire(s, "omen", 5)
    assert due_event(wev, s.store.read_all(), day=9) is None        # told once


def test_recurring_events_rearm_after_their_interval():
    s = _session()
    wev = {"market": _event("market", every=3)}
    assert due_event(wev, s.store.read_all(), day=3) is None        # one interval first
    assert due_event(wev, s.store.read_all(), day=4).id == "market"
    _fire(s, "market", 4)
    assert due_event(wev, s.store.read_all(), day=6) is None
    assert due_event(wev, s.store.read_all(), day=7).id == "market"
    # on_day + every_days: first firing on the named day, then the rhythm.
    both = {"patrol": _event("patrol", on_day=1, every=5)}
    assert due_event(both, [], day=1).id == "patrol"


def test_conditions_hold_an_event_without_consuming_it():
    s = _session()
    gated = {"uprising": _event("uprising", on_day=1,
                                min_standing=MinStanding(faction="watch", tier="friendly"))}
    assert due_event(gated, s.store.read_all(), day=8,
                     standing_tiers={"watch": "neutral"}) is None
    got = due_event(gated, s.store.read_all(), day=8,
                    standing_tiers={"watch": "friendly"})
    assert got is not None and got.id == "uprising"    # fired late, not lost


def test_one_event_per_turn_in_authored_order():
    wev = {"first": _event("first", on_day=1), "second": _event("second", on_day=1)}
    assert due_event(wev, [], day=1).id == "first"


# --- composition: armed encounters ------------------------------------------------

def _mill(*encounters):
    return PlaceNode(id="mill", name="Mill", description="", parent=None,
                     exits=(), encounters=tuple(encounters))


def _dormant(enc_id="toughs", once=True):
    return KeyedEncounter(id=enc_id, enemies=[KeyedEnemy(ref="wolf")],
                          trigger=KeyedTrigger(when="event"), once=once)


def test_event_only_encounters_wait_for_their_arming():
    s = _session()
    s.start_location = "mill"
    node = _mill(_dormant())
    wev = {"omen": _event(on_day=1, encounter=EventEncounter(place="mill", encounter="toughs"))}
    kw = dict(start_location="mill", time_of_day="day", party_level=1)
    assert due_encounter(node, s.store.read_all(), **kw) is None          # dormant
    _fire(s, "omen", 1, place="mill")
    armed = armed_encounters(wev, s.store.read_all())
    assert armed == {("mill", "toughs")}
    assert due_encounter(node, s.store.read_all(), armed=armed, **kw).id == "toughs"
    # The fight fires → the arm is consumed; `once` keeps it down forever.
    s.emit_log(EventKind.KEYED_ENCOUNTER_TRIGGERED, place="mill", encounter_id="toughs")
    assert armed_encounters(wev, s.store.read_all()) == set()
    assert due_encounter(node, s.store.read_all(), **kw) is None


def test_arming_outranks_time_and_level_conditions():
    s = _session()
    night_only = KeyedEncounter(id="wolves", enemies=[KeyedEnemy(ref="wolf")],
                                trigger=KeyedTrigger(time_of_day="night",
                                                     min_party_level=10),
                                once=False)
    node = _mill(night_only)
    kw = dict(start_location="mill", time_of_day="day", party_level=1)
    assert due_encounter(node, s.store.read_all(), **kw) is None
    assert due_encounter(node, s.store.read_all(),
                         armed={("mill", "wolves")}, **kw).id == "wolves"


# --- composition: standing + offers -------------------------------------------------

def test_event_shifts_move_standing_but_never_reveal():
    s = _session()
    factions = {"hand": Faction(id="hand", name="The Gray Hand")}
    wev = {"buyout": _event("buyout", on_day=1,
                            standing=[EventStanding(faction="hand", delta=-10)],
                            every=4)}
    _fire(s, "buyout", 1)
    _fire(s, "buyout", 5)                              # a recurring shift lands each time
    extra = standing_deltas(wev, factions, s.store.read_all())
    assert extra == {"hand": -20}
    scores = standing_map(factions, {}, s.store.read_all(), s.quests, extra=extra)
    assert scores == {"hand": -20}
    assert known_ids(factions, {}, s.store.read_all(), s.quests) == set()   # still ???


def test_quest_overlay_folds_in_firing_order():
    s = _session()
    wev = {"open": _event("open", on_day=1, unlock_quest="vault"),
           "close": _event("close", on_day=2, retire_quest="vault")}
    _fire(s, "open", 1)
    assert quest_overlay(wev, s.store.read_all()) == ({"vault"}, set())
    _fire(s, "close", 2)
    assert quest_overlay(wev, s.store.read_all()) == (set(), {"vault"})


# --- the loop end-to-end --------------------------------------------------------------

def _loop(session: Session) -> TurnLoop:
    return TurnLoop(session, Rng(seed=11, record=session.emit_log),
                    Brain(ScriptedLLMClient()))


def test_the_loop_fires_records_and_never_refires():
    s = _session()
    s.start_location = "mill"
    s.location = "mill"
    s.places = {"mill": _mill()}
    s.world_events = {"storm": _event("storm", on_day=1,
                                      environment=EventEnvironment(weather="storm"))}
    loop = _loop(s)
    asyncio.run(loop.take_turn("We look at the sky."))
    fired = [e for e in s.store.read_all() if e.kind == EventKind.WORLD_EVENT.value]
    assert [(e.payload["event_id"], e.payload["present"]) for e in fired] == [("storm", False)]
    assert s.weather == "storm"                        # the authored turn of the sky
    asyncio.run(loop.take_turn("We press on."))
    fired = [e for e in s.store.read_all() if e.kind == EventKind.WORLD_EVENT.value]
    assert len(fired) == 1                             # a one-shot never refires


def test_presence_walks_the_parent_chain():
    s = _session()
    s.start_location = "inn"
    s.location = "inn"
    town = PlaceNode(id="town", name="Town", description="", parent=None, exits=())
    inn = PlaceNode(id="inn", name="Inn", description="", parent="town", exits=())
    s.places = {"town": town, "inn": inn}
    s.world_events = {"parade": _event("parade", on_day=1, place="town")}
    loop = _loop(s)
    asyncio.run(loop.take_turn("We sip our drinks."))
    ev = [e for e in s.store.read_all() if e.kind == EventKind.WORLD_EVENT.value][0]
    assert ev.payload["present"] is True               # inside the town = witnessed


def test_context_frames_live_vs_rumor():
    s = _session()
    live = build_context(s.repo, scene="the square",
                         world_event={"announce": "The mill has sold.",
                                      "briefing": "It was the Hand.",
                                      "place_name": "The Old Mill", "present": True,
                                      "effects": ["a fight now lies in wait (secret — never announce it)"]})
    assert "WORLD EVENT — IT HAS JUST HAPPENED at The Old Mill" in live
    assert "The party is THERE" in live and "It was the Hand." in live
    away = build_context(s.repo, scene="the square",
                         world_event={"announce": "The mill has sold.", "briefing": "",
                                      "place_name": "The Old Mill", "present": False,
                                      "effects": []})
    assert "AWAY from the party" in away and "rumor" in away


# --- the linter -------------------------------------------------------------------------

def test_lint_catches_dangling_refs_and_unarmed_event_encounters():
    errors: list[str] = []
    place = Place(id="mill", name="Mill", description="d",
                  encounters=[KeyedEncounter(id="toughs", enemies=[KeyedEnemy(ref="wolf")],
                                             trigger=KeyedTrigger(when="event"))])
    ev = _event(on_day=1, place="ghost_town",
                encounter=EventEncounter(place="mill", encounter="no_such"))
    _lint_world_events([ev], [place], [], [], errors)
    assert any("ghost_town" in e for e in errors)
    assert any("no_such" in e for e in errors)
    assert any("no event arms it" in e for e in errors)     # 'toughs' is unreachable
    # Armed properly → both complaints vanish.
    ok = _event(on_day=1, encounter=EventEncounter(place="mill", encounter="toughs"))
    errors2: list[str] = []
    _lint_world_events([ok], [place], [], [], errors2)
    assert errors2 == []


def test_brightvale_testbed_events_load_and_arm_the_mill():
    world = load_pack("brightvale")
    ids = {e.id for e in world.world_events}
    assert ids == {"gray_hand_moves_in", "market_day"}
    mill = world.places["brightvale_old_mill"]
    toughs = next(e for e in mill.encounters if e.id == "mill_toughs")
    assert toughs.trigger.when == "event"
