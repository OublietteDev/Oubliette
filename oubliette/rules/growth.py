"""Creature-companion growth (companions S2): authored tiers, only.

A Forge author may give a creature's stat block `growth` stages — "pseudodragon
→ adolescent → drake" — each naming the NEXT form's stat block and the party
level that unlocks it. When the strongest HERO reaches a stage's threshold, the
engine applies the new form to the traveling companion (a COMPANION_EVOLVED
event carrying the rebuilt snapshot) and tells the DM to narrate the
transformation THAT turn — the story moment is the feature. Unauthored
creatures never grow; person companions level like heroes and never pass
through here.
"""

from __future__ import annotations

from ..enums import Ability
from ..state.models import Character


def eligible_stage(statblock, hero_level: int):
    """The first authored stage this form unlocks at `hero_level`, or None.
    Stages are checked in authored order; chains run one hop per form (the next
    form's own block carries the step after it)."""
    for stage in getattr(statblock, "growth", None) or ():
        if hero_level >= stage.at_party_level:
            return stage
    return None


def evolved_character(char: Character, new_sb) -> Character:
    """The companion rebuilt in its new form: the stat block's combat numbers on
    the SAME character — name, inventory, and history stay theirs. A new body
    wakes whole (full HP, conditions shed); level tracks the form's CR so the
    encounter budget feels the growth."""
    abilities = dict(char.abilities)
    for key, score in (new_sb.abilities or {}).items():
        try:
            abilities[Ability(key)] = score
        except ValueError:
            continue                       # an unknown ability key is display-only
    return char.model_copy(deep=True, update={
        "abilities": abilities,
        "hp": new_sb.hp, "max_hp": new_sb.hp,
        "armor_class": new_sb.armor_class,
        "attack_bonus": new_sb.attack_bonus,
        "damage": new_sb.damage,
        "level": max(1, round(new_sb.cr)) if new_sb.cr else char.level,
        "conditions": [],
    })
