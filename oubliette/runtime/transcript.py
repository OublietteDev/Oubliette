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
                turns.append({"role": "player", "text": text})
        elif ev.kind == EventKind.NARRATION_RECORDED.value:
            text = ev.payload.get("narration", "")
            if text:
                turns.append({"role": "dm", "text": text})
    return turns


def recent_beats(events: list[Event], limit: int) -> list[str]:
    """The last `limit` continuity beats from the session in progress — rehydrates the
    DM's short-term memory (`TurnLoop.history`) so a reload doesn't wipe recent context.
    Draws only from the current session: past sessions reach the DM as notes, not beats."""
    beats = [ev.payload.get("beat", "")
             for ev in current_session_events(events)
             if ev.kind == EventKind.NARRATION_RECORDED.value]
    beats = [b for b in beats if b]
    return beats[-limit:] if limit >= 0 else beats
