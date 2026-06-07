"""The quest store: holds Quests + a replay-stable id counter. Rebuilt by
replaying QUEST_STARTED / QUEST_UPDATED events, so it's byte-identical on reload
like protected state and canon.
"""

from __future__ import annotations

import re

from .models import Quest, QuestStatus


class QuestStore:
    def __init__(self) -> None:
        self._quests: dict[str, Quest] = {}
        self._counter = 0

    def next_id(self) -> str:
        return f"quest-{self._counter}"

    def add(self, quest: Quest) -> None:
        self._quests[quest.id] = quest
        # Keep the counter ahead of any id seen, so live and replay assign the same.
        m = re.fullmatch(r"quest-(\d+)", quest.id)
        if m:
            self._counter = max(self._counter, int(m.group(1)) + 1)

    def get(self, quest_id: str) -> Quest | None:
        return self._quests.get(quest_id)

    def update(self, quest_id: str, status: QuestStatus | None = None,
               note: str | None = None) -> None:
        quest = self._quests.get(quest_id)
        if quest is None:
            return
        if status is not None:
            quest.status = status
        if note:
            quest.notes.append(note)

    def all(self) -> list[Quest]:
        return list(self._quests.values())

    def active(self) -> list[Quest]:
        return [q for q in self._quests.values() if q.status == "active"]
