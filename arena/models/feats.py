"""Feats — passive bonuses and special abilities from character advancement."""

from pydantic import BaseModel, Field


class Feat(BaseModel):
    """A feat that grants passive bonuses and/or special abilities.

    Passive bonus fields mirror the Item model so stat_modifiers.py
    can aggregate both uniformly.
    """

    name: str
    description: str = ""

    # Passive stat bonuses (same pattern as Item model)
    bonus_ability_scores: dict[str, int] = Field(default_factory=dict)
    bonus_speed: int = 0
    bonus_ac: int = 0
    bonus_initiative: int = 0
    grants_damage_resistances: list[str] = Field(default_factory=list)
    grants_damage_immunities: list[str] = Field(default_factory=list)
    grants_condition_immunities: list[str] = Field(default_factory=list)
    grants_saving_throw_proficiencies: list[str] = Field(default_factory=list)

    # Critical hit modifications
    crit_range_reduction: int = 0  # How many below 20 also crit (1 = 19-20, 2 = 18-20)
    bonus_crit_dice: int = 0  # Extra weapon damage dice on crit (Brutal Critical)

    # Evasion
    has_evasion: bool = False

    # Extra Attack
    extra_attack_count: int = 0

    # Forced reroll
    forced_reroll_saves: bool = False
    forced_reroll_resource: str | None = None
    forced_reroll_resource_cost: int = 1
