"""Behavior trees and AI profiles."""

from pydantic import BaseModel


class AIProfile(BaseModel):
    """Defines AI behavior tendencies."""

    name: str

    # Weights (0.0 to 2.0, where 1.0 is neutral)
    aggression: float = 1.0  # Preference for attacking vs. defending
    self_preservation: float = 1.0  # Willingness to risk self
    target_priority: str = "nearest"  # "nearest", "weakest", "strongest", "random", "threatening"

    # Tactical preferences
    prefers_melee: bool = True
    uses_area_attacks: bool = True
    protects_allies: bool = False
    focuses_spellcasters: bool = False

    # Positioning
    maintains_distance: int = 0  # Preferred distance from enemies (0 = melee)
    flanks_when_possible: bool = True
    avoids_opportunity_attacks: bool = True

    # Resource usage
    uses_limited_abilities: float = 0.5  # 0 = never, 1 = freely

    # Retreat behavior
    retreat_threshold: float = 0.25  # HP percentage to consider fleeing
    will_flee: bool = False


# Default AI profiles
DEFAULT_PROFILES: dict[str, AIProfile] = {
    "default_monster": AIProfile(name="Default Monster"),
    "berserker": AIProfile(
        name="Berserker",
        aggression=1.8,
        self_preservation=0.3,
        target_priority="nearest",
        prefers_melee=True,
        will_flee=False,
    ),
    "archer": AIProfile(
        name="Archer",
        aggression=1.0,
        maintains_distance=60,
        avoids_opportunity_attacks=True,
        prefers_melee=False,
    ),
    "spellcaster": AIProfile(
        name="Spellcaster",
        aggression=0.8,
        prefers_melee=False,
        maintains_distance=30,
        uses_limited_abilities=0.8,
        uses_area_attacks=True,
        focuses_spellcasters=True,
    ),
    "coward": AIProfile(
        name="Coward",
        aggression=0.5,
        self_preservation=1.5,
        retreat_threshold=0.5,
        will_flee=True,
    ),
    "protector": AIProfile(
        name="Protector",
        aggression=0.7,
        protects_allies=True,
        target_priority="threatening",
    ),
}
