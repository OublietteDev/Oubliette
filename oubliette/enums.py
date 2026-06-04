"""Closed vocabularies from the spec: abilities, the 18 SRD skills, verbs, tiers.

The verb enum is intentionally CLOSED (spec §6 / v0.1 §5). Do not widen it
speculatively — anything that fits no verb is the signal to route `freestyle`.
"""

from __future__ import annotations

from enum import Enum


class Ability(str, Enum):
    STR = "str"
    DEX = "dex"
    CON = "con"
    INT = "int"
    WIS = "wis"
    CHA = "cha"


class Skill(str, Enum):
    ACROBATICS = "acrobatics"
    ANIMAL_HANDLING = "animal_handling"
    ARCANA = "arcana"
    ATHLETICS = "athletics"
    DECEPTION = "deception"
    HISTORY = "history"
    INSIGHT = "insight"
    INTIMIDATION = "intimidation"
    INVESTIGATION = "investigation"
    MEDICINE = "medicine"
    NATURE = "nature"
    PERCEPTION = "perception"
    PERFORMANCE = "performance"
    PERSUASION = "persuasion"
    RELIGION = "religion"
    SLEIGHT_OF_HAND = "sleight_of_hand"
    STEALTH = "stealth"
    SURVIVAL = "survival"


# Which ability governs each skill. Code owns this mapping (a state-number concern);
# the DC that the skill is checked against is model-set (D8).
SKILL_ABILITY: dict[Skill, Ability] = {
    Skill.ACROBATICS: Ability.DEX,
    Skill.ANIMAL_HANDLING: Ability.WIS,
    Skill.ARCANA: Ability.INT,
    Skill.ATHLETICS: Ability.STR,
    Skill.DECEPTION: Ability.CHA,
    Skill.HISTORY: Ability.INT,
    Skill.INSIGHT: Ability.WIS,
    Skill.INTIMIDATION: Ability.CHA,
    Skill.INVESTIGATION: Ability.INT,
    Skill.MEDICINE: Ability.WIS,
    Skill.NATURE: Ability.INT,
    Skill.PERCEPTION: Ability.WIS,
    Skill.PERFORMANCE: Ability.CHA,
    Skill.PERSUASION: Ability.CHA,
    Skill.RELIGION: Ability.INT,
    Skill.SLEIGHT_OF_HAND: Ability.DEX,
    Skill.STEALTH: Ability.DEX,
    Skill.SURVIVAL: Ability.WIS,
}


class Verb(str, Enum):
    MOVE = "move"
    ATTACK = "attack"
    CAST = "cast"
    USE_ITEM = "use_item"
    TRADE = "trade"
    REST = "rest"
    SKILL_CHECK = "skill_check"
    META = "meta"


class Tier(str, Enum):
    AUTHORED = "authored"        # may_canonize = False
    RECOMBINED = "recombined"    # may_canonize = True
    FREESTYLE = "freestyle"      # may_canonize = True
    DENIED = "denied"            # may_canonize = False


def may_canonize(tier: Tier) -> bool:
    return tier in (Tier.RECOMBINED, Tier.FREESTYLE)
