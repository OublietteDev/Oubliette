"""Combat event system for logging and tracking combat actions."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class CombatEventType(Enum):
    """Types of events that can occur during combat."""

    COMBAT_START = auto()
    ROUND_START = auto()
    TURN_START = auto()
    TURN_END = auto()
    MOVEMENT = auto()
    ATTACK_ROLL = auto()
    DAMAGE = auto()
    CREATURE_DOWNED = auto()
    COMBAT_END = auto()
    INFO = auto()
    SAVING_THROW = auto()
    CONDITION_APPLIED = auto()
    CONDITION_REMOVED = auto()
    DEATH_SAVE = auto()
    HEALING = auto()
    REACTION = auto()
    TELEPORT = auto()
    FORCED_MOVEMENT = auto()
    TERRAIN_MODIFICATION = auto()
    AI_THINKING = auto()


@dataclass
class CombatEvent:
    """A single combat event for the log.

    Attributes:
        event_type: The type of event.
        message: Human-readable description for the combat log.
        source_id: creature_id of the acting creature (if applicable).
        target_id: creature_id of the target creature (if applicable).
        details: Additional structured data about the event.
    """

    event_type: CombatEventType
    message: str
    source_id: str | None = None
    target_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class CombatLog:
    """Append-only log of combat events."""

    def __init__(self) -> None:
        self.events: list[CombatEvent] = []

    def add(self, event: CombatEvent) -> None:
        """Append an event to the log."""
        self.events.append(event)

    def clear(self) -> None:
        """Clear all events."""
        self.events.clear()
