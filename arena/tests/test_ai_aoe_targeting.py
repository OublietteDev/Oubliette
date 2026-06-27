"""Regression: AI area-burst spells must be centered on the enemy, not the caster.

`execute_effect(target_id)` expands an AoE around the CASTER, so an AI area spell
planned without a center hex lands on the caster's own square (a damage+terrain
spell like Ice Storm even dumps its difficult terrain there). Area BURST spells
(Fireball, Ice Storm, Cone of Cold — non-concentration) must therefore carry a
target_hex on the enemy so the executor routes them through execute_effect_at_hex.
Self-centered auras (Spirit Guardians — concentration) and single-target effects
(Hold Person) must NOT get a center hex; they stay on the caster-centered path.
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


def _hero(name, pos_hp=40):
    return Creature(
        name=name, max_hit_points=pos_hp, armor_class=14,
        ability_scores=AbilityScores(strength=12, dexterity=12),
        proficiency_bonus=2, is_player_controlled=True,
        actions=[Action(
            name="Club", description="hit", action_type=ActionType.ACTION,
            attack=Attack(name="Club", attack_type="melee_weapon", ability="strength",
                          reach=5, damage=[DamageRoll(dice="1d4", damage_type=DamageType.BLUDGEONING)]),
        )],
    )


def _stormcaller(spell: dict):
    """A caster whose only offensive option is the given spell action dict."""
    return Monster(
        name="Stormcaller", max_hit_points=40, armor_class=12,
        ability_scores=AbilityScores(intelligence=17, dexterity=14),
        proficiency_bonus=3, is_player_controlled=False, ai_profile="spellcaster",
        actions=[Action.model_validate(spell)],
    )


ICE_STORM = {
    "name": "Ice Storm", "description": "hail", "action_type": "action",
    "range": 300, "target_type": "area_sphere", "area_size": 20,
    "requires_concentration": False, "terrain_modification": "difficult",
    "saving_throw": {"ability": "dexterity", "dc": 14,
                     "damage_on_fail": [{"dice": "2d8", "damage_type": "cold"}],
                     "damage_on_success": "half"},
}
SPIRIT_GUARDIANS = {
    "name": "Spirit Guardians", "description": "aura", "action_type": "action",
    "range": 0, "target_type": "area_sphere", "area_size": 15,
    "requires_concentration": True,
    "saving_throw": {"ability": "wisdom", "dc": 14,
                     "damage_on_fail": [{"dice": "3d8", "damage_type": "radiant"}],
                     "damage_on_success": "half"},
}
HOLD_PERSON = {
    "name": "Hold Person", "description": "paralyze", "action_type": "action",
    "range": 60, "target_type": "one_enemy", "requires_concentration": True,
    "saving_throw": {"ability": "wisdom", "dc": 14, "conditions_on_fail": ["paralyzed"]},
}


def _plan_first_effect(spell: dict, hero_positions=((5, 7), (5, 8))):
    """Set up Stormcaller vs two clustered heroes, return the (action_name,
    target_hex, caster_pos) of the first EXECUTE_EFFECT it plans. Heroes default
    to range (for burst spells); pass adjacent positions for self-auras."""
    enc = Encounter(
        name="AoE", grid_width=20, grid_height=15,
        combatants=[
            CombatantEntry(creature_id="caster", creature_data=_stormcaller(spell),
                           team="enemy", starting_position=(15, 7)),
            CombatantEntry(creature_id="h1", creature_data=_hero("H1"),
                           team="player", starting_position=hero_positions[0]),
            CombatantEntry(creature_id="h2", creature_data=_hero("H2"),
                           team="player", starting_position=hero_positions[1]),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    cm.roll_initiative()
    cm.begin_combat()
    # Runtime combatant ids are slugged from the creature *name*, not the
    # encounter's creature_id, so the Stormcaller's id is "stormcaller".
    for _ in range(len(cm.combatants) + 1):
        if cm.active_combatant and cm.active_combatant.creature_id == "stormcaller":
            break
        cm.end_turn()
    caster_pos = (cm.active_combatant.position.q, cm.active_combatant.position.r)
    plan = AIController(randomness=0.0).plan_turn(cm)
    for s in plan.steps:
        if s.step_type == TurnStepType.EXECUTE_EFFECT:
            name = next((p.action_name for p in plan.steps
                         if p.step_type == TurnStepType.SELECT_ACTION), None)
            return name, s.target_hex, caster_pos
    return None, None, caster_pos


def test_area_burst_centers_on_enemy_not_caster():
    name, target_hex, caster_pos = _plan_first_effect(ICE_STORM)
    assert name == "Ice Storm"
    assert target_hex is not None                 # placed, not caster-centered
    assert target_hex != caster_pos               # not on the caster's own square


def test_concentration_aura_stays_caster_centered():
    # A self-aura only matters with enemies adjacent to the caster.
    name, target_hex, _ = _plan_first_effect(SPIRIT_GUARDIANS, hero_positions=((14, 7), (14, 8)))
    assert name == "Spirit Guardians"
    assert target_hex is None                      # aura -> caster-centered path


def test_single_target_effect_has_no_center_hex():
    name, target_hex, _ = _plan_first_effect(HOLD_PERSON)
    assert name == "Hold Person"
    assert target_hex is None
