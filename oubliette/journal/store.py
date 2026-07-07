"""Journal data model + a tiny SQLite-backed store (one JSON document per save).

NOT event-sourced and NOT part of authoritative state — it's personal notes, so a
whole-document read/write is the right simplicity. Lives in its own table in the
save db; wiped with the save on New Game.
"""

from __future__ import annotations

import sqlite3

from pydantic import BaseModel, Field


class JournalStyle(BaseModel):
    """The player's binding choices — how THEIR book looks. Per-save on purpose:
    a new journey means a new journal."""
    hand: str = "caveat"      # handwriting font key (see HANDS in the UI)
    ink: str = "iron"         # ink color key
    cover: str = "umber"      # leather color key
    emblem: str = ""          # emblem art filename ("" = plain cover)
    paper: str = "clean"      # page style: clean | weathered | stained


class JournalEntry(BaseModel):
    id: str
    title: str = ""
    status: str = ""        # free-text label; the UI renders it as a stamped seal
    body: str = ""
    # format tells the UI how to read `body`: "md" (legacy markdown) or "html"
    # (rich ink — sanitized client-side). Old entries default to "md" and convert
    # the first time they're edited.
    format: str = "md"
    # kind reserves the trinket slot: "note" today; a future "trinket" renders as
    # a thing affixed to the page (image + caption) rather than written on it.
    kind: str = "note"
    image: str = ""
    caption: str = ""


class JournalSection(BaseModel):
    id: str
    name: str
    color: str = ""         # optional tab tint key; "" lets the UI pick by position
    entries: list[JournalEntry] = Field(default_factory=list)


class Journal(BaseModel):
    style: JournalStyle = Field(default_factory=JournalStyle)
    sections: list[JournalSection] = Field(default_factory=list)


def starter_journal() -> Journal:
    """The blank-page fix: a never-written journal opens with tabs already waiting
    for ink. Only used when NO row exists — a player who deletes every section has
    a row, and their emptiness is respected."""
    return Journal(sections=[
        JournalSection(id="seed-quests", name="Quests"),
        JournalSection(id="seed-people", name="People"),
        JournalSection(id="seed-places", name="Places"),
        JournalSection(id="seed-creatures", name="Creatures"),
    ])


class JournalStore:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)"
        )
        self._conn.commit()

    def get(self) -> Journal:
        row = self._conn.execute("SELECT data FROM journal WHERE id = 1").fetchone()
        return Journal.model_validate_json(row[0]) if row else starter_journal()

    def put(self, journal: Journal) -> None:
        self._conn.execute(
            "INSERT INTO journal (id, data) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (journal.model_dump_json(),),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
