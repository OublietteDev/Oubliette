"""Quest data model (simple shape: a goal + status + running notes)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

QuestStatus = Literal["active", "completed", "failed"]


class Quest(BaseModel):
    id: str
    title: str
    text: str = ""                              # what the goal is / current understanding
    status: QuestStatus = "active"
    notes: list[str] = Field(default_factory=list)   # running beats the DM appends
    reward_settled: bool = False                # once a quest completes, its reward stays in
                                                # the DM's context (REWARDS PENDING) until the
                                                # DM explicitly confirms the party has been
                                                # justly compensated — a matching give/transact
                                                # can't close the loop because rewards are
                                                # renegotiable (they may take gold instead of
                                                # the promised sword). Event-sourced like status.
    authored_id: str | None = None              # the AuthoredQuest this was activated from
                                                # (None = an emergent, DM-invented quest).
                                                # Rides inside the QUEST_STARTED record, so it
                                                # rebuilds byte-identically on reload.
