"""Session lifecycle: the durable event store + the materialized authoritative
state (character repo + canon store), kept in agreement.

`Session.open` rebuilds everything by seeding the authored baseline and replaying
the log. During play, `emit_state`/`emit_create_entity`/`emit_promote` are the
record-then-apply points: append the event FIRST (durable), then apply. So a
reload always reproduces the live state — protected state AND canon — byte-for-
byte (D9).
"""

from __future__ import annotations

from typing import Callable

from ..canon.models import CanonDraft, CanonRecord
from ..canon.store import CanonStore
from ..record.events import Event, EventKind, StateOp, apply_ops, replay
from ..record.store import EventStore
from ..seed import seed_world
from ..state.repository import Repository


class Session:
    def __init__(self, store: EventStore, repo: Repository, canon: CanonStore) -> None:
        self.store = store
        self.repo = repo
        self.canon = canon

    @classmethod
    def open(cls, store: EventStore, seed: Callable[[], Repository] = seed_world) -> "Session":
        repo = seed()                       # authored baseline (deterministic)
        canon = CanonStore()
        events = store.read_all()
        session = cls(store, repo, canon)
        if events:
            replay(events, repo, canon)     # existing session: rebuild to current
        else:
            session.emit_log(EventKind.SESSION_MARKER, marker="start")
        return session

    def emit_log(self, kind: "str | EventKind", **payload) -> Event:
        """Append a non-state event (player message, roll, marker). No ops."""
        return self.store.append(kind, payload)

    def emit_state(self, kind: "str | EventKind", ops: list[StateOp], **payload) -> Event:
        """Append a protected-state event carrying its replayable ops, THEN apply
        them to the materialized repo (append-then-commit, spec §5)."""
        full = {**payload, "ops": [op.model_dump() for op in ops]}
        event = self.store.append(kind, full)
        apply_ops(ops, self.repo)
        return event

    def emit_create_entity(self, draft: CanonDraft, reason: str) -> CanonRecord:
        """Create provisional canon (spec §7/§11). The id + creating-event seq are
        assigned now and recorded, so replay reproduces them exactly (§4.4)."""
        record = CanonRecord(
            id=self.canon.next_id(),
            entity_type=draft.entity_type, name=draft.name, text=draft.text,
            origin=draft.origin, status="provisional",
            created_by_event=self.store.peek_seq(), load_bearing=False,
        )
        self.store.append(EventKind.CREATE_ENTITY, {"record": record.model_dump(), "reason": reason})
        self.canon.add(record)
        return record

    def emit_promote(self, entity_id: str, reason: str) -> None:
        """Promote provisional → confirmed canon (spec §11)."""
        self.store.append(EventKind.CANON_PROMOTED, {"entity_id": entity_id, "reason": reason})
        self.canon.promote(entity_id)
