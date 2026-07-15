"""Session segmentation + transcript reconstruction over the durable event log (W3).

The event log is one continuous *campaign*; a "session" is a span within it. An
ordinary session wrap-up (W5) drops a `SESSION_MARKER` with `marker == "wrap"`; the
span since the last such marker is the **session in progress**. These readers rebuild,
from the durable record W2 made, the two things a reload used to lose: the player's
chat transcript and the DM's short-term memory. This is the segmentation primitive
both W3 (replay the current session) and W5 (per-session notes) stand on.

Force-ends (`marker == "end"`) are terminal and orthogonal — they close the whole
game, not a session, so they don't segment anything here.
"""

from __future__ import annotations

from ..record.events import Event, EventKind

WRAP_MARKER = "wrap"   # SESSION_MARKER payload value for an ordinary session wrap-up (W5)


def _ordered(events: list[Event]) -> list[Event]:
    return sorted(events, key=lambda e: e.seq)


def current_session_events(events: list[Event]) -> list[Event]:
    """The events of the session in progress: everything after the last wrap marker
    (all events if the campaign hasn't wrapped a session yet)."""
    ordered = _ordered(events)
    start = 0
    for i, ev in enumerate(ordered):
        if ev.kind == EventKind.SESSION_MARKER.value and ev.payload.get("marker") == WRAP_MARKER:
            start = i + 1
    return ordered[start:]


def transcript_turns(events: list[Event]) -> list[dict]:
    """Ordered chat bubbles for the session in progress — each player message and each
    DM narration, in log order. Rebuilds the player's chat log on reload (the client-side
    DOM was the only prior record). Returns `[{"role": "player"|"dm", "text": ...}, ...]`."""
    turns: list[dict] = []
    for ev in current_session_events(events):
        if ev.kind == EventKind.PLAYER_MESSAGE.value:
            text = ev.payload.get("text", "")
            if text:
                turn = {"role": "player", "text": text}
                if ev.payload.get("speaker"):     # hosted-table attribution (multiplayer S1)
                    turn["who"] = ev.payload["speaker"]
                turns.append(turn)
        elif ev.kind == EventKind.NARRATION_RECORDED.value:
            text = ev.payload.get("narration", "")
            if text:
                turns.append({"role": "dm", "text": text})
    return turns


def session_notes(events: list[Event]) -> list[dict]:
    """The two-faced notes from each WRAPPED (ended) session, oldest first, 1-indexed. The
    DM's cumulative long-term memory: `dm_private` feeds its context every turn (§W5),
    `player_facing` becomes the player's spoiler-free chronicle. The session in progress
    has no note yet — it reaches the DM as beats (`recent_beats`), not notes."""
    out: list[dict] = []
    for ev in _ordered(events):
        if ev.kind == EventKind.SESSION_MARKER.value and ev.payload.get("marker") == WRAP_MARKER:
            out.append({"index": len(out) + 1,
                        "player_facing": ev.payload.get("player_facing", ""),
                        "dm_private": ev.payload.get("dm_private", "")})
    return out


def notebook_notes(events: list[Event]) -> list[str]:
    """The DM's private notebook entries for the session in progress, oldest first (the
    `dm_note` tool, W4). Working memory the DM feeds into its own context every turn — plans,
    NPC true intentions, foreshadowing. Current-session only: a past session's threads are
    carried forward by its wrap note (STORY SO FAR), so the notebook resets at wrap like beats.
    Players never see these; prose only, never protected state."""
    return [ev.payload.get("note", "")
            for ev in current_session_events(events)
            if ev.kind == EventKind.NOTEBOOK_NOTE.value and ev.payload.get("note")]


def recent_beats(events: list[Event], limit: int) -> list[str]:
    """The last `limit` continuity beats from the session in progress — rehydrates the
    DM's short-term memory (`TurnLoop.history`) so a reload doesn't wipe recent context.
    Draws only from the current session: past sessions reach the DM as notes, not beats."""
    beats = [ev.payload.get("beat", "")
             for ev in current_session_events(events)
             if ev.kind == EventKind.NARRATION_RECORDED.value]
    beats = [b for b in beats if b]
    return beats[-limit:] if limit >= 0 else beats
