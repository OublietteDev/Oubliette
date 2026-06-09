"""Initiative tracking and turn order."""

from dataclasses import dataclass, field


@dataclass
class InitiativeEntry:
    """An entry in the initiative order."""

    creature_id: str
    name: str
    initiative_roll: int
    dexterity: int
    is_player_controlled: bool
    tiebreaker: float = 0.0  # Random tiebreaker
    is_lair: bool = False  # True for the lair pseudo-entry at initiative 20


@dataclass
class InitiativeTracker:
    """Tracks initiative order for combat."""

    entries: list[InitiativeEntry] = field(default_factory=list)
    current_index: int = 0
    round_number: int = 1

    def add_entry(self, entry: InitiativeEntry) -> None:
        """Add a creature to initiative and re-sort."""
        self.entries.append(entry)
        self._sort()

    def remove_entry(self, creature_id: str) -> None:
        """Remove a creature from initiative."""
        self.entries = [e for e in self.entries if e.creature_id != creature_id]

    def _sort(self) -> None:
        """Sort entries by initiative (descending), then dex, then player priority."""
        self.entries.sort(
            key=lambda e: (
                e.initiative_roll,
                0 if e.is_lair else 1,  # Lair loses all ties (0 < 1 in desc)
                e.dexterity,
                e.is_player_controlled,
                e.tiebreaker,
            ),
            reverse=True,
        )

    def next_turn(self) -> InitiativeEntry | None:
        """Advance to the next turn and return the active creature."""
        if not self.entries:
            return None

        self.current_index += 1
        if self.current_index >= len(self.entries):
            self.current_index = 0
            self.round_number += 1

        return self.current_entry

    @property
    def current_entry(self) -> InitiativeEntry | None:
        """Get the current active entry."""
        if not self.entries or self.current_index >= len(self.entries):
            return None
        return self.entries[self.current_index]

    def reset(self) -> None:
        """Reset the tracker for a new combat."""
        self.entries.clear()
        self.current_index = 0
        self.round_number = 1
