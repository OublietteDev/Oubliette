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
