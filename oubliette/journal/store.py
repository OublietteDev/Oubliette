"""Journal data model + a tiny SQLite-backed store (one JSON document per save).

NOT event-sourced and NOT part of authoritative state — it's personal notes, so a
whole-document read/write is the right simplicity. Lives in its own table in the
save db; wiped with the save on New Game.
"""

from __future__ import annotations

import sqlite3

from pydantic import BaseModel, Field


class JournalEntry(BaseModel):
    id: str
    title: str = ""
    status: str = ""        # optional free-text label the UI groups by (e.g. "In-Progress")
    body: str = ""          # markdown notes


class JournalSection(BaseModel):
    id: str
    name: str
    entries: list[JournalEntry] = Field(default_factory=list)


class Journal(BaseModel):
    sections: list[JournalSection] = Field(default_factory=list)


class JournalStore:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)"
        )
        self._conn.commit()

    def get(self) -> Journal:
        row = self._conn.execute("SELECT data FROM journal WHERE id = 1").fetchone()
        return Journal.model_validate_json(row[0]) if row else Journal()

    def put(self, journal: Journal) -> None:
        self._conn.execute(
            "INSERT INTO journal (id, data) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (journal.model_dump_json(),),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
