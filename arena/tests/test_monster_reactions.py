"""D-MON-5: monster reactions — Parry.

Parry is a +X-AC reaction against one melee attack that would hit. A monster
defender auto-uses it when the bonus would turn the incoming hit into a miss
(it can't save a roll that still clears the raised AC, and never on a crit).
"""

import json
from pathlib import Path
from types import SimpleNamespace

from arena.combat.actions import AttackHitResult
from arena.combat.manager import CombatManager
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, ActionType, Attack, DamageRoll, DamageType
from arena.models.character import Creature
from arena.models.encounter import CombatantEntry, Encounter
from arena.models.monster import Monster

DATA = Path(__file__).resolve().parent.parent / "data"


def _knight():
    return Monster.model_validate(
        json.loads((DATA / "monsters/srd/knight.json").read_text(encoding="utf-8")))


def _melee_action():
    return Action(name="Sword", description="x", action_type=ActionType.ACTION,
                  attack=Attack(name="Sword", attack_type="melee_weapon", ability="strength",
                                reach=5,
                                damage=[DamageRoll(dice="1d8", damage_type=DamageType.SLASHING,
                                                   ability_modifier="strength")]))


def _scene():
    knight = _knight()
    hero = Creature(name="Hero", max_hit_points=30, current_hit_points=30,
                    ability_scores=AbilityScores(strength=16), proficiency_bonus=3,
                    is_player_controlled=True, actions=[_melee_action()])
    enc = Encounter(name="parry", grid_width=10, grid_height=10, combatants=[
        CombatantEntry(creature_id="hero", creature_data=hero, team="player",
                       starting_position=(1, 1)),
        CombatantEntry(creature_id="knight", creature_data=knight, team="enemy",
                       starting_position=(1, 2)),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    from unittest.mock import patch
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10]):
        cm.roll_initiative()
    cm.begin_combat()
    kid = next(k for k, v in cm.combatants.items() if v.team == "enemy")
    hid = next(k for k, v in cm.combatants.items() if v.team == "player")
    return cm, kid, hid


def _hr(cm, kid, hid, total_roll, ac, crit=False, melee=True):
    return SimpleNamespace(
        hit=True, critical=crit, total_roll=total_roll, target_ac=ac,
        target_id=kid, attacker_id=hid,
        attack=SimpleNamespace(
            attack_type="melee_weapon" if melee else "ranged_weapon"))


# ── Generator wiring ─────────────────────────────────────────────────────────

def test_knight_has_parry_reaction():
    knight = _knight()
    parry = next((r for r in knight.reactions if r.name == "Parry"), None)
    assert parry is not None
    assert parry.action_type == ActionType.REACTION
    assert cm_ac_bonus(parry) == 2


def cm_ac_bonus(action):
    return CombatManager._ac_reaction_bonus(action)


# ── The parry gate ───────────────────────────────────────────────────────────

def test_parry_negates_a_marginal_hit():
    cm, kid, hid = _scene()
    ac = cm.combatants[kid].creature.armor_class
    hr = _hr(cm, kid, hid, total_roll=ac, ac=ac)  # hit by exactly AC; +2 negates
    assert cm._evaluate_monster_parry(hr) is True
    assert hr.hit is False
    assert cm.reaction_used.get(kid) is True


def test_parry_skipped_when_hit_is_too_strong():
    cm, kid, hid = _scene()
    ac = cm.combatants[kid].creature.armor_class
    hr = _hr(cm, kid, hid, total_roll=ac + 5, ac=ac)  # +2 won't negate
    assert cm._evaluate_monster_parry(hr) is False
    assert hr.hit is True


def test_parry_not_used_on_crit():
    cm, kid, hid = _scene()
    ac = cm.combatants[kid].creature.armor_class
    hr = _hr(cm, kid, hid, total_roll=ac, ac=ac, crit=True)
    assert cm._evaluate_monster_parry(hr) is False


def test_parry_is_melee_only():
    cm, kid, hid = _scene()
    ac = cm.combatants[kid].creature.armor_class
    hr = _hr(cm, kid, hid, total_roll=ac, ac=ac, melee=False)
    assert cm._evaluate_monster_parry(hr) is False


def test_parry_once_per_round():
    cm, kid, hid = _scene()
    ac = cm.combatants[kid].creature.armor_class
    cm.reaction_used[kid] = True
    hr = _hr(cm, kid, hid, total_roll=ac, ac=ac)
    assert cm._evaluate_monster_parry(hr) is False


def test_plain_monster_has_no_parry():
    cm, kid, hid = _scene()
    goblin = Monster(name="Goblin", max_hit_points=7, armor_class=15,
                     ability_scores=AbilityScores())
    cm.combatants[kid].creature = goblin
    hr = _hr(cm, kid, hid, total_roll=15, ac=15)
    assert cm._evaluate_monster_parry(hr) is False


# ── End-to-end through complete_attack ───────────────────────────────────────

def test_parry_negates_damage_through_complete_attack():
    cm, kid, hid = _scene()
    knight = cm.combatants[kid].creature
    ac = knight.armor_class
    start_hp = knight.current_hit_points
    action = _melee_action()
    hr = AttackHitResult(
        hit=True, critical=False, natural_roll=15, modifier=ac - 15,
        total_roll=ac, target_ac=ac, effective_advantage=0, events=[],
        attacker=cm.combatants[hid].creature, attacker_id=hid,
        target=knight, target_id=kid, action=action, attack=action.attack,
        combatants=cm.combatants)
    cm.complete_attack(hr)
    assert knight.current_hit_points == start_hp  # parried → no damage
    assert cm.reaction_used.get(kid) is True
