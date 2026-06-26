"""Monster and NPC stat blocks."""

from pydantic import Field

from .character import Creature, Feature
from .actions import Action


class Monster(Creature):
    """A monster or NPC stat block."""

    # Challenge Rating
    challenge_rating: float = Field(ge=0, default=1)  # 0, 0.125, 0.25, 0.5, 1-30
    experience_points: int = 0

    # Monster-specific
    legendary_actions: list[Action] = Field(default_factory=list)
    legendary_action_count: int = 0
    lair_actions: list[Action] = Field(default_factory=list)

    # Legendary Resistance: N times per encounter, a failed save may be turned
    # into a success. 0 = the creature doesn't have it. (D-MON-1 wires the hook
    # in resolve_saving_throw; this field is the per-encounter pool.)
    legendary_resistance_count: int = 0

    # Regeneration: heal `regeneration_amount` HP at the start of the creature's
    # turn, unless it took damage of a `regeneration_negated_by` type since its
    # last turn. 0 = no regeneration. (D-MON-3 wires the start-of-turn heal.)
    regeneration_amount: int = 0
    regeneration_negated_by: list[str] = Field(default_factory=list)

    # Special Abilities (passive)
    special_abilities: list[Feature] = Field(default_factory=list)

    # For AI
    is_player_controlled: bool = False  # Default to AI-controlled
    ai_profile: str = "default_monster"

    # Source
    source_book: str | None = None  # e.g., "Monster Manual"
    source_page: int | None = None
