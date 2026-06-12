"""Status conditions that can affect creatures."""

from enum import Enum

from pydantic import BaseModel, Field


class Condition(str, Enum):
    """Standard 5e conditions."""

    BLINDED = "blinded"
    CHARMED = "charmed"
    DEAFENED = "deafened"
    EXHAUSTION = "exhaustion"  # Has levels 1-6
    FRIGHTENED = "frightened"
    GRAPPLED = "grappled"
    INCAPACITATED = "incapacitated"
    INVISIBLE = "invisible"
    PARALYZED = "paralyzed"
    PETRIFIED = "petrified"
    POISONED = "poisoned"
    PRONE = "prone"
    RESTRAINED = "restrained"
    STUNNED = "stunned"
    UNCONSCIOUS = "unconscious"
    # Combat-specific pseudo-conditions
    CONCENTRATING = "concentrating"
    DODGING = "dodging"
    HELPED = "helped"  # Has advantage on next check
    HIDDEN = "hidden"  # Creature is hidden via stealth


class AppliedCondition(BaseModel):
    """A condition currently affecting a creature."""

    condition: Condition
    source: str  # Name of creature/effect that applied it
    duration_type: str = "indefinite"  # "indefinite", "rounds", "end_of_turn", "start_of_turn"
    duration_rounds: int | None = None
    save_to_end: str | None = None  # Ability to save, e.g., "wisdom"
    save_dc: int | None = None
    level: int = 1  # For exhaustion
    extra_data: dict = Field(default_factory=dict)  # e.g., {"frightened_of": "Dragon"}


class BuffEffect(BaseModel):
    """A single stat modification within a buff/debuff.

    Describes what stat is affected, how, and by how much.
    Used both as a "recipe" on Action.buff_effects and stored
    inside ActiveBuff.modifiers at runtime.
    """

    stat: str  # "ac", "attack_rolls", "saving_throws", "speed", "damage_resistance", or an ability name ("strength", ...)
    modifier_type: str  # "flat_bonus", "advantage", "disadvantage", "resistance", "immunity", "multiply", "set"
    # "set" uses FLOOR semantics (effective = max(normal, set value)) — that is the
    # SRD's actual wording for both families that need it: Mage Armor ("base AC
    # becomes 13 + Dex" — moot if you're already higher) and Giant Strength
    # ("your score is 21; no effect if it's already equal or higher").  An AC set
    # value may be an int or a "13+DEX" formula evaluated against the wearer.
    value: str | int | float | None = None  # 5, "1d4", 2.0, None, "fire", "13+DEX"
    scope: str = "all"  # "all", "dexterity", "fire", "melee", etc.
    target_grants_to_attacker: bool = False  # True = debuff on TARGET grants effect to ATTACKERS


class ActiveBuff(BaseModel):
    """A currently-active buff or debuff on a creature.

    Parallel to AppliedCondition — temporary state with duration tracking.
    Applied by spells/abilities, removed by duration expiry, save-to-end,
    or concentration loss.
    """

    name: str  # Spell/ability name, e.g., "Shield", "Bless"
    source_id: str  # Creature ID of the caster
    modifiers: list[BuffEffect] = Field(default_factory=list)
    duration_type: str = "indefinite"  # "indefinite", "rounds", "end_of_turn", "start_of_turn"
    duration_rounds: int | None = None
    save_to_end: str | None = None  # Ability to save, e.g., "wisdom"
    save_dc: int | None = None
