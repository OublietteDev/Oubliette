"""The event store: durable, append-only, ordered by `seq`.

`SqliteEventStore` is the Phase 2 persistence (decision D1) — append-then-commit
so a crash mid-turn replays cleanly. `InMemoryEventStore` is the same contract
for tests and ephemeral sessions. Both assign `seq` centrally so it stays
monotonic and gap-free.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Protocol, runtime_checkable

from .events import Event, EventKind


def _kind_str(kind: "str | EventKind") -> str:
    return kind.value if isinstance(kind, EventKind) else str(kind)


@runtime_checkable
class EventStore(Protocol):
    def append(self, kind: "str | EventKind", payload: dict, caused_by: int | None = ...) -> Event: ...
    def read_all(self) -> list[Event]: ...
    def of_kind(self, kind: "str | EventKind") -> list[Event]: ...
    def peek_seq(self) -> int: ...
    def close(self) -> None: ...


class InMemoryEventStore:
    def __init__(self) -> None:
        self._events: list[Event] = []
        self._next = 0

    def append(self, kind, payload, caused_by=None) -> Event:
        ev = Event(seq=self._next, kind=_kind_str(kind), payload=payload, caused_by=caused_by)
        self._next += 1
        self._events.append(ev)
        return ev

    def read_all(self) -> list[Event]:
        return list(self._events)

    def of_kind(self, kind) -> list[Event]:
        k = _kind_str(kind)
        return [e for e in self._events if e.kind == k]

    def peek_seq(self) -> int:
        return self._next

    def close(self) -> None:
        pass


class SqliteEventStore:
    def __init__(self, path: str) -> None:
        # check_same_thread=False: the web server touches the connection from
        # worker threads; turns are serialized by a lock so this stays safe.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            " seq INTEGER PRIMARY KEY,"
            " kind TEXT NOT NULL,"
            " payload TEXT NOT NULL,"
            " caused_by INTEGER)"
        )
        self._conn.commit()
        row = self._conn.execute("SELECT COALESCE(MAX(seq), -1) FROM events").fetchone()
        self._next = int(row[0]) + 1

    def append(self, kind, payload, caused_by=None) -> Event:
        seq = self._next
        self._next += 1
        k = _kind_str(kind)
        self._conn.execute(
            "INSERT INTO events (seq, kind, payload, caused_by) VALUES (?, ?, ?, ?)",
            (seq, k, json.dumps(payload), caused_by),
        )
        self._conn.commit()  # durable before the change takes effect (append-then-commit)
        return Event(seq=seq, kind=k, payload=payload, caused_by=caused_by)

    def read_all(self) -> list[Event]:
        rows = self._conn.execute(
            "SELECT seq, kind, payload, caused_by FROM events ORDER BY seq"
        ).fetchall()
        return [Event(seq=r[0], kind=r[1], payload=json.loads(r[2]), caused_by=r[3]) for r in rows]

    def of_kind(self, kind) -> list[Event]:
        k = _kind_str(kind)
        rows = self._conn.execute(
            "SELECT seq, kind, payload, caused_by FROM events WHERE kind = ? ORDER BY seq", (k,)
        ).fetchall()
        return [Event(seq=r[0], kind=r[1], payload=json.loads(r[2]), caused_by=r[3]) for r in rows]

    def peek_seq(self) -> int:
        return self._next

    def close(self) -> None:
        self._conn.close()
