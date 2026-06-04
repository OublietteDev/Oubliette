"""Append-only debug log. A monotonic `seq` foreshadows the event log's ordering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LogEntry:
    seq: int
    kind: str               # "player_message" | "assessment" | "roll" | "tool_applied" | "anomaly" | "narration"
    data: dict[str, Any] = field(default_factory=dict)


class DebugLog:
    def __init__(self) -> None:
        self._entries: list[LogEntry] = []
        self._next = 0

    def append(self, kind: str, **data: Any) -> LogEntry:
        entry = LogEntry(seq=self._next, kind=kind, data=data)
        self._next += 1
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> list[LogEntry]:
        return list(self._entries)

    def of_kind(self, kind: str) -> list[LogEntry]:
        return [e for e in self._entries if e.kind == kind]
