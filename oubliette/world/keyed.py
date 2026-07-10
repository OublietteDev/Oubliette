"""Keyed-encounter triggers (living-world W1) — a PURE derivation over the
event log + the current Place's authored encounters, mirroring quest offers.

The firewall owns the FACT that an authored fight fires: the trigger is
evaluated in code at the top of every in-character turn, the DM is handed a
hard directive to narrate the approach, and the fight is staged by the engine
regardless of what the model does. Nothing here is stored mutably:

  * visit boundaries derive from the session start + LOCATION_CHANGED events
    (the same record the map's discovery redaction reads);
  * fired-state derives from KEYED_ENCOUNTER_TRIGGERED events, so `once`
    survives reload and a replayed session never re-fires a spent ambush.

An encounter fires at most once per VISIT (standing in the haunted mill all
night is one ambush, not one per message); `once` tightens that to once per
campaign, and `when: first_visit` to the first visit only.
"""

from __future__ import annotations

from ..record.events import Event, EventKind

# Session start counts as an arrival with a seq BELOW any real event's.
_START_SEQ = -1


def _arrivals(events: list[Event], start_location: str | None,
              place_id: str) -> list[int]:
    """Event seqs at which the party ARRIVED at `place_id`, oldest first. The
    session start is arrival seq -1 when the campaign opens there. A travel
    event that names the place the party already stands in is NOT a new
    arrival (re-emitted travel must not re-arm a per-visit ambush)."""
    out: list[int] = []
    here = start_location
    if start_location == place_id:
        out.append(_START_SEQ)
    for ev in sorted(events, key=lambda e: e.seq):
        if ev.kind != EventKind.LOCATION_CHANGED.value:
            continue
        to = ev.payload.get("to")
        if to == place_id and here != place_id:
            out.append(ev.seq)
        if to:
            here = to
    return out


def _fired(events: list[Event], place_id: str) -> list[tuple[str, int]]:
    """(encounter id, event seq) for every keyed encounter that has FIRED at
    this place, from the durable record."""
    return [(ev.payload.get("encounter_id"), ev.seq) for ev in events
            if ev.kind == EventKind.KEYED_ENCOUNTER_TRIGGERED.value
            and ev.payload.get("place") == place_id]


def due_encounter(node, events: list[Event], *, start_location: str | None,
                  time_of_day: str, party_level: int,
                  armed: set | None = None):
    """The one keyed encounter that fires THIS turn at `node` (the party's
    current PlaceNode), or None. Encounters are checked in authored order and
    at most one fires per turn — a second eligible ambush waits its turn.

    Predicates are ANDed, one per trigger field, so later arcs bolt on quest/
    faction conditions here without touching the callers.

    `armed` (living-world W4) is the set of (place, encounter id) pairs a
    world event has ARMED: an armed encounter skips its when/time/level
    conditions entirely — the event outranks them — and a `when: "event"`
    encounter fires ONLY this way. Once-per-visit and once-per-campaign
    still hold."""
    encounters = getattr(node, "encounters", ()) or ()
    if not encounters:
        return None
    arrivals = _arrivals(events, start_location, node.id)
    # The party stands here, so an arrival must exist; a log that lost its
    # travel record (hand-edited saves) counts as a lifelong first visit.
    visit_start = arrivals[-1] if arrivals else _START_SEQ
    first_visit = len(arrivals) <= 1
    fired = _fired(events, node.id)
    fired_ever = {enc_id for enc_id, _ in fired}
    fired_this_visit = {enc_id for enc_id, seq in fired if seq > visit_start}
    for enc in encounters:
        if enc.id in fired_this_visit:
            continue
        if enc.once and enc.id in fired_ever:
            continue
        if (node.id, enc.id) in (armed or ()):
            return enc                                  # the event said NOW
        trig = enc.trigger
        if trig.when == "event":
            continue                                    # dormant until armed
        if trig.when == "first_visit" and not first_visit:
            continue
        if trig.time_of_day != "any" and trig.time_of_day != time_of_day:
            continue
        if trig.min_party_level is not None and party_level < trig.min_party_level:
            continue
        return enc
    return None
