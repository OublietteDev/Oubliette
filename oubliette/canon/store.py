"""The canon store: holds CanonRecords + a replay-stable id counter, plus simple
keyword retrieval. Rebuilt by replaying CREATE_ENTITY / CANON_PROMOTED events, so
it's byte-identical on reload like protected state.
"""

from __future__ import annotations

import re

from .models import CanonRecord

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "i", "to", "of", "and", "is", "it", "you", "he", "she",
    "they", "at", "in", "on", "for", "with", "my", "me", "this", "that", "his",
    "her", "their", "him", "them", "we", "are", "as", "by", "be", "do", "ask",
}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP}


class CanonStore:
    def __init__(self) -> None:
        self._records: dict[str, CanonRecord] = {}
        self._counter = 0

    def next_id(self) -> str:
        return f"canon-{self._counter}"

    def add(self, record: CanonRecord) -> None:
        self._records[record.id] = record
        # Keep the counter ahead of any id we've seen, so live and replay agree.
        m = re.fullmatch(r"canon-(\d+)", record.id)
        if m:
            self._counter = max(self._counter, int(m.group(1)) + 1)

    def get(self, entity_id: str) -> CanonRecord | None:
        return self._records.get(entity_id)

    def promote(self, entity_id: str) -> None:
        rec = self._records.get(entity_id)
        if rec is not None:
            rec.status = "confirmed"

    def all(self) -> list[CanonRecord]:
        return list(self._records.values())

    def search(self, query: str, limit: int = 5) -> list[CanonRecord]:
        """Keyword retrieval over name + text. Name matches weigh double; ties
        break toward confirmed canon (more dependable) then insertion order."""
        q = _tokens(query)
        if not q:
            return []
        scored: list[tuple[int, int, CanonRecord]] = []
        for i, rec in enumerate(self._records.values()):
            name_t = _tokens(rec.name)
            text_t = _tokens(rec.text)
            score = 2 * len(q & name_t) + len(q & text_t)
            if score > 0:
                confirmed_rank = 1 if rec.status == "confirmed" else 0
                scored.append((score, confirmed_rank, rec))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [rec for _, _, rec in scored[:limit]]
