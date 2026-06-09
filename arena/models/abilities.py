"""Ability scores and skills."""

from pydantic import BaseModel, Field


class AbilityScores(BaseModel):
    """The six core ability scores for a creature."""

    strength: int = Field(ge=1, le=30, default=10)
    dexterity: int = Field(ge=1, le=30, default=10)
    constitution: int = Field(ge=1, le=30, default=10)
    intelligence: int = Field(ge=1, le=30, default=10)
    wisdom: int = Field(ge=1, le=30, default=10)
    charisma: int = Field(ge=1, le=30, default=10)

    def get_modifier(self, ability: str) -> int:
        """Calculate the modifier for a given ability score."""
        score = getattr(self, ability.lower())
        return (score - 10) // 2

    def get_score(self, ability: str) -> int:
        """Get the raw score for a given ability."""
        return getattr(self, ability.lower())
