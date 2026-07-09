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


def offerable_ids(authored: dict, events: list[Event], quests,
                  party_level: int = 1) -> set[str]:
    """The authored quest ids currently available to take up: roots plus branch-unlocked
    nodes, minus anything already started, minus anything the party is too low-level for.
    Chain-eligibility only — NOT yet location-gated.

    A quest with a SINGLE branch is a linear step — it advances on completion with no
    outcome needed (the lone next quest is unambiguous). Only a genuine FORK (>1 branch)
    requires the DM to report which outcome occurred.

    A quest's `min_party_level` HIDES it until `party_level` reaches it (difficulty S2):
    the gate applies to roots and unlocked nodes alike, so a chain can hold a step back
    until the party has grown into it."""
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

    def _level_ok(q) -> bool:
        return q.min_party_level is None or party_level >= q.min_party_level

    return {qid for qid in eligible
            if qid in authored and qid not in started and _level_ok(authored[qid])}


def earned_trinkets(authored: dict, events: list[Event], quests) -> list[dict]:
    """Every trinket the party has EARNED, a pure derivation like the offer set.
    Accepting an authored quest grants its "accepted" trinkets — kept even if the
    quest later fails (the map fragment is still in hand); completing it grants
    "completed" trinkets whose outcome filter matches ("" = any ending). Whether a
    trinket is TAPED into the journal is the journal's own business — the
    player-owned document is the only record of that, and the DM never sees any
    of this."""
    started = started_authored_ids(quests)
    outcomes = completed_outcomes(events)
    out: list[dict] = []
    for aid, q in authored.items():
        for t in getattr(q, "trinkets", []):
            granted = (t.when == "accepted" and aid in started) or (
                t.when == "completed" and aid in outcomes
                and (not t.outcome or t.outcome == outcomes[aid]))
            if granted:
                out.append({"key": f"{aid}:{t.id}", "quest": q.title,
                            "image": t.image, "caption": t.caption, "when": t.when})
    return out


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
