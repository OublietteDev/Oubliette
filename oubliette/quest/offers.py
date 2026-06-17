"""Authored-quest offer availability — a PURE derivation over the event log + the
pack's authored quest defs. Nothing here is stored mutably: the offerable set is
recomputed from `store.read_all()` every turn, so a reload reproduces it byte-for-byte
(the same guarantee protected state + canon + quests already have).

Two facts come out of the log:
  * which authored quest a runtime quest came from — `Quest.authored_id`, recorded
    inside the QUEST_STARTED record;
  * the OUTCOME chosen when an authored quest was completed — recorded on the
    QUEST_UPDATED payload (metadata only; replay never applies it).

From those, `offerable_ids` yields the authored quests currently available to take up:
the roots plus anything unlocked by a completed branch, minus anything already started.
`offered_here` further narrows that to quests whose source is present in the scene.
"""

from __future__ import annotations

from ..record.events import Event, EventKind


def _runtime_to_authored(events: list[Event]) -> dict[str, str]:
    """{runtime quest_id -> authored_id} for runtime quests activated from an authored
    quest (emergent quests carry no authored_id and are skipped)."""
    out: dict[str, str] = {}
    for ev in events:
        if ev.kind == EventKind.QUEST_STARTED.value:
            rec = ev.payload.get("record", {})
            aid = rec.get("authored_id")
            if aid is not None and rec.get("id") is not None:
                out[rec["id"]] = aid
    return out


def completed_outcomes(events: list[Event]) -> dict[str, str]:
    """{authored_id -> chosen outcome label} for every authored quest COMPLETED. The
    outcome is "" when the quest had no branches / the DM reported none. Last write wins
    (a quest is completed once); failed quests are NOT included — only completion unlocks."""
    link = _runtime_to_authored(events)
    out: dict[str, str] = {}
    for ev in events:
        if ev.kind == EventKind.QUEST_UPDATED.value and ev.payload.get("status") == "completed":
            aid = link.get(ev.payload.get("quest_id"))
            if aid is not None:
                out[aid] = ev.payload.get("outcome") or ""
    return out


def started_authored_ids(quests) -> set[str]:
    """authored_ids that already have a runtime quest of ANY status (active/completed/
    failed) — so a taken quest (even a failed one) is never re-offered."""
    return {q.authored_id for q in quests.all() if q.authored_id}


def offerable_ids(authored: dict, events: list[Event], quests) -> set[str]:
    """The authored quest ids currently available to take up: roots plus branch-unlocked
    nodes, minus anything already started. Chain-eligibility only — NOT yet location-gated.

    A quest with a SINGLE branch is a linear step — it advances on completion with no
    outcome needed (the lone next quest is unambiguous). Only a genuine FORK (>1 branch)
    requires the DM to report which outcome occurred."""
    started = started_authored_ids(quests)
    outcomes = completed_outcomes(events)
    unlocked: set[str] = set()
    for aid, outcome in outcomes.items():
        q = authored.get(aid)
        if q is None:
            continue
        if len(q.branches) == 1:
            unlocked.add(q.branches[0].to)              # linear step: outcome optional
        else:
            for b in q.branches:                        # fork: match the reported outcome
                if b.outcome == outcome:
                    unlocked.add(b.to)
    eligible = {qid for qid, q in authored.items() if q.root} | unlocked
    return {qid for qid in eligible if qid in authored and qid not in started}


def offered_here(eligible: set[str], authored: dict, location: str | None,
                 present_npc_ids: set[str]) -> set[str]:
    """Narrow an eligible set to quests whose SOURCE is present right now: a giver NPC
    among the present cast, or a place-given quest whose place is the party's location.
    This is the set the DM may actually `accept_quest` (and the Tier-2 'offered here' view)."""
    here: set[str] = set()
    for qid in eligible:
        q = authored.get(qid)
        if q is None:
            continue
        if q.giver_npc is not None and q.giver_npc in present_npc_ids:
            here.add(qid)
        elif q.giver_place is not None and q.giver_place == location:
            here.add(qid)
    return here
