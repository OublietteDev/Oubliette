"""Canon data model (spec §3.2, §11)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EntityType = Literal["npc", "place", "lore", "item", "quest", "faction"]


class CanonDraft(BaseModel):
    """What the DM proposes via `create_entity` — no id/status yet (the session
    assigns those). Origin is recombined/freestyle; authored content isn't created
    at runtime (spec §7)."""

    entity_type: EntityType
    name: str
    text: str = ""
    origin: Literal["recombined", "freestyle"] = "freestyle"


class CanonRecord(BaseModel):
    """A persisted piece of world content with its lifecycle status."""

    id: str
    entity_type: EntityType
    name: str
    text: str = ""
    origin: Literal["authored", "recombined", "freestyle"]
    status: Literal["provisional", "confirmed"]
    created_by_event: int | None = None
    load_bearing: bool = False
    # Extra search terms that surface this record without cluttering its text — e.g.
    # a lore entry's "about" subjects (Brightvale, Alden, Seraphel).
    keywords: list[str] = Field(default_factory=list)
