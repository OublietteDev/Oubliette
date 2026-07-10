"""Timed world events (living-world W4) — the arc's composition layer, and a
PURE derivation over the event log like everything before it.

An authored WorldEvent is a scheduled happening: the CODE decides it fires
(against the campaign clock from W3 plus optional quest/standing conditions),
records a WORLD_EVENT event, and hands the DM a directive — narrate it live
if the party stands at its place, or let the news arrive as rumor if they're
elsewhere. The world moves offscreen for the price of a log entry: there is
no simulation anywhere.

Effects are NEVER applied to state. They derive from the fired record plus
the authored definition, each read by the subsystem it belongs to:

  * standing shifts   → factions.standing_map (via `standing_deltas` here);
  * armed encounters  → keyed.due_encounter (via `armed_encounters` here);
  * quest offers      → the loop's offer computation (via `quest_overlay`);
  * environment       → the one exception: the loop emits a real
                        ENVIRONMENT_CHANGED, which was already replay-safe.

At most ONE event fires per turn (authored order breaks ties) — an overdue
backlog after a long journey trickles in turn by turn, as news does.
"""

from __future__ import annotations

from ..quest import offers
from ..record.events import Event, EventKind
from .factions import tier_at_least


def fired(events: list[Event]) -> list[tuple[str, int, int]]:
    """(event_id, day, seq) for every world event that has fired, oldest first."""
    return [(ev.payload.get("event_id"), int(ev.payload.get("day") or 1), ev.seq)
            for ev in sorted(events, key=lambda e: e.seq)
            if ev.kind == EventKind.WORLD_EVENT.value]


def due_event(world_events: dict, events: list[Event], *, day: int,
              standing_tiers: dict[str, str] | None = None, quests=None):
    """The one WorldEvent that fires THIS turn, or None. Checked in authored
    order: schedule first (one-shots fire once; a recurring event re-arms
    `every_days` after its last firing), then conditions ANDed on top. A
    condition that isn't met doesn't consume the schedule — the event fires
    late, the first turn everything holds."""
    if not world_events:
        return None
    log = fired(events)
    outcomes = offers.completed_outcomes(events) if quests is not None else {}
    tiers = standing_tiers or {}
    for eid, ev in world_events.items():
        mine = [d for fid, d, _ in log if fid == eid]
        if ev.every_days is None:
            if mine:                                   # a one-shot, already told
                continue
            if day < (ev.on_day or 1):
                continue
        else:
            if mine:
                if day - mine[-1] < ev.every_days:     # re-arms after the interval
                    continue
            elif day < (ev.on_day if ev.on_day is not None else 1 + ev.every_days):
                continue
        if ev.quest_done is not None and ev.quest_done not in outcomes:
            continue
        if ev.min_standing is not None and not tier_at_least(
                tiers.get(ev.min_standing.faction, ""), ev.min_standing.tier):
            continue
        return ev
    return None


def armed_encounters(world_events: dict, events: list[Event]) -> set[tuple[str, str]]:
    """(place, encounter id) pairs currently ARMED by a fired event: the event
    named the fight and no KEYED_ENCOUNTER_TRIGGERED for that pair has landed
    since. Each firing arms one triggering; a recurring event re-arms."""
    arm_seq: dict[tuple[str, str], int] = {}
    consumed: dict[tuple[str, str], int] = {}
    for ev in sorted(events, key=lambda e: e.seq):
        if ev.kind == EventKind.WORLD_EVENT.value:
            we = world_events.get(ev.payload.get("event_id"))
            if we is not None and we.encounter is not None:
                arm_seq[(we.encounter.place, we.encounter.encounter)] = ev.seq
        elif ev.kind == EventKind.KEYED_ENCOUNTER_TRIGGERED.value:
            key = (ev.payload.get("place"), ev.payload.get("encounter_id"))
            consumed[key] = ev.seq
    return {key for key, seq in arm_seq.items()
            if key not in consumed or consumed[key] < seq}


def standing_deltas(world_events: dict, factions: dict,
                    events: list[Event]) -> dict[str, int]:
    """{faction id: summed shift} from every FIRING (a recurring event's shift
    lands each time). Event shifts never reveal a faction — the world can turn
    against the party in the dark."""
    out: dict[str, int] = {}
    for eid, _day, _seq in fired(events):
        we = world_events.get(eid)
        for st in (we.standing if we is not None else ()):
            if st.faction in factions:
                out[st.faction] = out.get(st.faction, 0) + st.delta
    return out


def quest_overlay(world_events: dict,
                  events: list[Event]) -> tuple[set[str], set[str]]:
    """(unlocked, retired) authored-quest ids from fired events, folded in
    firing order — a later event can re-open what an earlier one withdrew."""
    unlocked: set[str] = set()
    retired: set[str] = set()
    for eid, _day, _seq in fired(events):
        we = world_events.get(eid)
        if we is None:
            continue
        if we.unlock_quest is not None:
            unlocked.add(we.unlock_quest)
            retired.discard(we.unlock_quest)
        if we.retire_quest is not None:
            retired.add(we.retire_quest)
            unlocked.discard(we.retire_quest)
    return unlocked, retired
