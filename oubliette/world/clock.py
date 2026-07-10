"""The world clock (living-world W3) — a PURE derivation over the event log,
mirroring quest offers and faction standing.

There was no clock before this: time-of-day was a flag the DM flipped when
the fiction called for it, and nothing counted the days. Now the campaign has
a day number, derived from two things that already cost the party something:

  * a LONG rest (or a night that got interrupted trying — the night still
    passed) snaps the clock to the NEXT MORNING;
  * TRAVEL on a calibrated map adds its journey time, recorded on the
    LOCATION_CHANGED event itself at emit time so replay is byte-identical.

Because the derivation reads the whole log, existing campaigns get a correct
day count retroactively — every night they ever slept was already recorded.

Internally the clock is `accum`, fractional days since campaign start. The
displayed day is `1 + floor(accum)` (campaigns start on Day 1). A long rest
sets `accum = floor(accum) + 1`: whatever fraction of the day travel ate, the
party wakes at the top of the next one.
"""

from __future__ import annotations

import math

from ..record.events import Event, EventKind


def _rested_through_the_night(payload: dict) -> bool:
    """True for a rest that consumed a NIGHT: a long rest, or an attempted long
    rest that was interrupted (dangerous tables) — the recovery was short but
    the hours were spent either way. Plain short rests move no clock."""
    return payload.get("rest") == "long" or bool(payload.get("interrupted"))


def accumulated_days(events: list[Event]) -> float:
    a = 0.0
    for ev in sorted(events, key=lambda e: e.seq):
        if ev.kind == EventKind.LOCATION_CHANGED.value:
            a += float(ev.payload.get("days") or 0.0)
        elif ev.kind == EventKind.REST_TAKEN.value and _rested_through_the_night(ev.payload):
            a = math.floor(a) + 1
    return a


def current_day(events: list[Event]) -> int:
    """The campaign's day number, 1-based."""
    return 1 + math.floor(accumulated_days(events))


# --- travel time (two-pin calibration) ------------------------------------------

def _chain(places: dict, start: str | None) -> list:
    """start and its ancestors, innermost first."""
    out, cur, seen = [], start, set()
    while cur in places and cur not in seen:
        seen.add(cur)
        out.append(places[cur])
        cur = places[cur].parent
    return out


def _pin(node) -> tuple[float, float] | None:
    p = getattr(node, "position", None)
    if isinstance(p, dict) and isinstance(p.get("x"), (int, float)) \
            and isinstance(p.get("y"), (int, float)):
        return float(p["x"]), float(p["y"])
    return None


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def travel_days(places: dict, scale, frm: str | None, to: str | None) -> float:
    """The journey time from `frm` to `to`, in days quantized to halves — or 0.

    Calibration covers ONE map: the one holding the author's two chosen pins
    (usually the world map, so area-to-area journeys cost days while moves
    inside a town stay free). The travelled 'legs' are the two places' nearest
    ancestors that sit as pinned siblings on that same map; anything that never
    crosses the calibrated map is free. Every failure path degrades to 0 —
    a clock must never block travel."""
    if scale is None or not frm or not to or frm == to:
        return 0.0
    pa, pb = places.get(scale.a), places.get(scale.b)
    ref_a, ref_b = (_pin(pa) if pa else None), (_pin(pb) if pb else None)
    if ref_a is None or ref_b is None or pa.parent != pb.parent:
        return 0.0
    ref_dist = _dist(ref_a, ref_b)
    if ref_dist <= 0:
        return 0.0
    days_per_unit = scale.days / ref_dist
    cal_parent = pa.parent
    for a in _chain(places, frm):
        for b in _chain(places, to):
            if a.id == b.id or a.parent != cal_parent or b.parent != cal_parent:
                continue
            qa, qb = _pin(a), _pin(b)
            if qa is None or qb is None:
                continue
            return round(_dist(qa, qb) * days_per_unit * 2) / 2
    return 0.0
