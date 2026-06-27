"""Monster and NPC stat blocks."""

from pydantic import BaseModel, Field

from .character import Creature, Feature
from .actions import Action


class DeathBurst(BaseModel):
    """Death Burst (D-MON-4b): when the creature dies it detonates, forcing a
    save on every creature within `radius_ft` (mephits, magmin). Indiscriminate
    per RAW — allies and enemies alike. A burst deals damage (`damage_dice`),
    applies a condition on a failed save (`condition_on_fail`, e.g. dust mephit's
    blindness, which carries a per-turn re-save), or both."""

    radius_ft: int = 5
    save_ability: str = "dexterity"
    save_dc: int = 10
    damage_dice: str | None = None
    damage_type: str = "fire"
    half_on_save: bool = False
    condition_on_fail: str | None = None


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

    # Undead Fortitude (D-MON-4b): on dropping to 0 HP, a CON save (DC 5 + the
    # damage taken) unless the blow was radiant or a critical — on a success the
    # creature drops to 1 HP instead. False = lacks the trait. Wired in apply_damage.
    undead_fortitude: bool = False

    # Death Burst (D-MON-4b): detonates on death. None = no burst. The manager's
    # _reconcile_death_bursts fires it when the creature dies.
    death_burst: "DeathBurst | None" = None

    # Special Abilities (passive)
    special_abilities: list[Feature] = Field(default_factory=list)

    # For AI
    is_player_controlled: bool = False  # Default to AI-controlled
    ai_profile: str = "default_monster"
    # A resolved custom personality, baked on by the Oubliette bridge (a
    # Forge-authored AIProfile, serialized as a plain dict so this model needn't
    # import from arena.ai). When present it OVERRIDES the named `ai_profile`;
    # the AI controller builds an AIProfile from it. None = use the named profile.
    ai_profile_inline: dict | None = None

    # Source
    source_book: str | None = None  # e.g., "Monster Manual"
    source_page: int | None = None
