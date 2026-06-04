"""Session lifecycle: the durable event store + the materialized authoritative
state, kept in agreement.

`Session.open` rebuilds state by seeding the authored baseline and replaying the
log (a no-op append on a fresh store writes the start marker). During play,
`emit_state` is the single record-then-apply point: it appends the event FIRST
(durable), then applies the ops to the materialized repo. So a reload always
reproduces the live state byte-for-byte (D9).
"""

from __future__ import annotations

from typing import Callable

from ..record.events import Event, EventKind, StateOp, apply_ops, replay
from ..record.store import EventStore
from ..seed import seed_world
from ..state.repository import Repository


class Session:
    def __init__(self, store: EventStore, repo: Repository) -> None:
        self.store = store
        self.repo = repo

    @classmethod
    def open(cls, store: EventStore, seed: Callable[[], Repository] = seed_world) -> "Session":
        repo = seed()                       # authored baseline (deterministic)
        events = store.read_all()
        session = cls(store, repo)
        if events:
            replay(events, repo)            # existing session: rebuild to current
        else:
            session.emit_log(EventKind.SESSION_MARKER, marker="start")
        return session

    def emit_log(self, kind: "str | EventKind", **payload) -> Event:
        """Append a non-state event (player message, roll, marker). No ops."""
        return self.store.append(kind, payload)

    def emit_state(self, kind: "str | EventKind", ops: list[StateOp], **payload) -> Event:
        """Append a state-changing event carrying its replayable ops, THEN apply
        them to the materialized repo (append-then-commit, spec §5)."""
        full = {**payload, "ops": [op.model_dump() for op in ops]}
        event = self.store.append(kind, full)
        apply_ops(ops, self.repo)
        return event
