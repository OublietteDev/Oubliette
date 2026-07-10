"""Faction standing (living-world W2) — a PURE derivation over the event log +
the pack's authored Factions, mirroring quest offers.

The party's standing with each faction is a code-owned score the LLM never
holds: it starts at the faction's authored default, moves in big steps when
authored quests say so (accepted/completed deltas, read back from the quest
log exactly like branch outcomes), and moves in small bounded nudges when the
DM's adjust_standing tool fires (FACTION_STANDING_CHANGED events). Reload
reproduces every score byte-for-byte.

Everything player- and DM-facing speaks in five TIERS; the raw numbers live
here, in one tunable block, like the encounter-budget bands.
"""

from __future__ import annotations

from ..quest import offers
from ..record.events import Event, EventKind

# --- the tunables (playtest numbers, one place) --------------------------------
SCORE_MIN, SCORE_MAX = -50, 50
TIER_ORDER = ("hostile", "unfriendly", "neutral", "friendly", "allied")
# A tier is 20 points wide; neutral straddles zero.
TIER_FLOORS = {"hostile": -50, "unfriendly": -30, "neutral": -10,
               "friendly": 10, "allied": 30}
# The DM's per-call nudge cap (a quarter tier): consequences, not power.
DM_DELTA_CAP = 5


def tier_for(score: int) -> str:
    """The tier word a score lands in."""
    out = TIER_ORDER[0]
    for name in TIER_ORDER:
        if score >= TIER_FLOORS[name]:
            out = name
    return out


def tier_at_least(tier: str, threshold: str) -> bool:
    """True when `tier` is `threshold` or warmer (unknown names never pass)."""
    order = {name: i for i, name in enumerate(TIER_ORDER)}
    return tier in order and threshold in order and order[tier] >= order[threshold]


def clamp_dm_delta(delta: int) -> int:
    """The bounded nudge the adjust_standing tool is allowed (±DM_DELTA_CAP)."""
    return max(-DM_DELTA_CAP, min(DM_DELTA_CAP, delta))


def _quest_deltas(factions: dict, authored: dict, events: list[Event],
                  quests) -> dict[str, int]:
    """{faction id: summed authored delta} from the quest log: accepted deltas
    for every taken quest (kept even if it later fails — the deed of joining is
    done), completion deltas whose outcome filter matches. The same derivation
    trinkets use."""
    started = offers.started_authored_ids(quests)
    outcomes = offers.completed_outcomes(events)
    out: dict[str, int] = {}
    for aid, q in authored.items():
        for st in getattr(q, "standing", []):
            if st.faction not in factions:
                continue
            earned = (st.when == "accepted" and aid in started) or (
                st.when == "completed" and aid in outcomes
                and (not st.outcome or st.outcome == outcomes[aid]))
            if earned:
                out[st.faction] = out.get(st.faction, 0) + st.delta
    return out


def standing_map(factions: dict, authored: dict, events: list[Event],
                 quests) -> dict[str, int]:
    """{faction id: current score} for every authored faction: default + quest
    deltas + the DM's recorded nudges, clamped to the score range."""
    if not factions:
        return {}
    scores = {fid: f.default_standing for fid, f in factions.items()}
    for fid, d in _quest_deltas(factions, authored, events, quests).items():
        scores[fid] = scores.get(fid, 0) + d
    for ev in events:
        if ev.kind == EventKind.FACTION_STANDING_CHANGED.value:
            fid = ev.payload.get("faction")
            if fid in scores:
                scores[fid] += int(ev.payload.get("delta") or 0)
    return {fid: max(SCORE_MIN, min(SCORE_MAX, s)) for fid, s in scores.items()}


def filter_offerable(eligible: set, authored: dict,
                     tiers: dict[str, str]) -> set:
    """Drop quests gated behind a standing tier the party hasn't reached
    (min_standing). Applied by the LOOP after chain/level eligibility so the
    quest module stays faction-blind — the modularity contract: rip factions
    out and quest offers run exactly as before."""
    out: set = set()
    for qid in eligible:
        q = authored.get(qid)
        ms = getattr(q, "min_standing", None) if q is not None else None
        if ms is None or tier_at_least(tiers.get(ms.faction, ""), ms.tier):
            out.add(qid)
    return out


def known_ids(factions: dict, authored: dict, events: list[Event],
              quests) -> set[str]:
    """The factions the PARTY knows exist: flagged known_from_start, touched by
    any recorded standing nudge (including the DM's delta-0 reveal), or owed an
    EARNED authored quest delta — you cannot gain a guild's gratitude without
    learning the guild exists. Everything else renders as ??? in the panel."""
    known = {fid for fid, f in factions.items() if f.known_from_start}
    known |= set(_quest_deltas(factions, authored, events, quests))
    for ev in events:
        if ev.kind == EventKind.FACTION_STANDING_CHANGED.value:
            fid = ev.payload.get("faction")
            if fid in factions:
                known.add(fid)
    return known
