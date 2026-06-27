"""Brain Slice 3A: signature recharge abilities (breath weapons) get used.

A once-per-rest ability's use-willingness in should_use_limited_ability scales
with ai_priority. At the generated default (5) a breath weapon lands at 0.375 —
just under the 0.4 threshold — and never fires. Marking recharge abilities as
signature (ai_priority 9) makes the AI use them. These tests pin both the bug
(priority 5 -> unused) and the fix (priority 9 -> used).
"""

from pathlib import Path

import pytest

from arena.ai.controller import AIController, TurnStepType
from arena.combat.manager import CombatManager
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.monster import Monster
from arena.models.encounter import Encounter, CombatantEntry


def _bite():
    return Action(
        name="Bite", description="bite", action_type=ActionType.ACTION,
        attack=Attack(name="Bite", attack_type="melee_weapon", ability="strength",
                      reach=5, damage=[DamageRoll(dice="2d10", damage_type=DamageType.PIERCING,
                                                  ability_modifier="strength")]),
    )


def _breath(ai_priority: int):
    """A recharge breath weapon (limited save AoE)."""
    return Action.model_validate({
        "name": "Fire Breath", "description": "cone of fire", "action_type": "action",
        "target_type": "area_sphere", "range": 30, "area_size": 30,
        "recharge_min": 5, "uses_per_rest": 1, "current_uses": 1,
        "ai_priority": ai_priority,
        "saving_throw": {"ability": "dexterity", "dc": 17,
                         "damage_on_fail": [{"dice": "16d6", "damage_type": "fire"}],
                         "damage_on_success": "half"},
    })


def _dragon(breath_priority: int):
    return Monster(
        name="Wyrm", max_hit_points=178, armor_class=18,
        ability_scores=AbilityScores(strength=23, dexterity=10),
        proficiency_bonus=4, is_player_controlled=False, ai_profile="default_monster",
        actions=[_bite(), _breath(breath_priority)],
    )


def _hero(name):
    return Creature(
        name=name, max_hit_points=45, armor_class=18,
        ability_scores=AbilityScores(strength=14, dexterity=12),
        proficiency_bonus=2, is_player_controlled=True, actions=[_bite()],
    )


def _dragon_picks_breath(breath_priority: int) -> bool:
    """Set up the Wyrm adjacent to two clustered heroes; return whether its
    plan selects Fire Breath."""
    enc = Encounter(
        name="Breath", grid_width=14, grid_height=14,
        combatants=[
            CombatantEntry(creature_id="wyrm", creature_data=_dragon(breath_priority),
                           team="enemy", starting_position=(7, 7)),
            CombatantEntry(creature_id="h1", creature_data=_hero("H1"),
                           team="player", starting_position=(8, 7)),
            CombatantEntry(creature_id="h2", creature_data=_hero("H2"),
                           team="player", starting_position=(8, 8)),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    cm.roll_initiative()
    cm.begin_combat()
    for _ in range(len(cm.combatants) + 1):
        if cm.active_combatant and cm.active_combatant.creature_id == "wyrm":
            break
        cm.end_turn()
    plan = AIController(randomness=0.0).plan_turn(cm)
    return any(s.step_type == TurnStepType.SELECT_ACTION and s.action_name == "Fire Breath"
               for s in plan.steps)


def test_signature_breath_is_used():
    assert _dragon_picks_breath(9) is True


def test_default_priority_breath_is_not_used():
    # Regression: at the generated default (5) the breath sits below the
    # use-threshold and the dragon just bites — the bug this slice fixes.
    assert _dragon_picks_breath(5) is False
