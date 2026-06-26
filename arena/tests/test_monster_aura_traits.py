"""D-MON (final batch): Blood Frenzy, Reckless Attack, Stench, Heated Body.

Closes the monster-trait package with the aura/retaliation/advantage traits that
weren't covered by the D-MON-4a primitives:

- Blood Frenzy (``attack_advantage_vs_damaged``) → advantage on a MELEE attack
  against a target below its hit-point maximum.
- Reckless Attack (``reckless_attacker`` → RECKLESS pseudo-condition) → the
  monster gains advantage on its own melee attacks, and attacks against it gain
  advantage until its next turn. Auto-applied at the start of an AI monster's
  turn.
- Stench (``aura_save_condition`` start-of-turn aura) → a creature starting its
  turn within range saves or is poisoned until its next turn; a success grants
  immunity for the rest of the fight.
- Heated Body (``retaliate_damage_dice``) → a creature that hits the monster with
  a melee attack takes fire damage back, no save.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena.combat.actions import resolve_attack_hit, AttackHitResult
from arena.combat.manager import CombatManager, Combatant
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, ActionType, Attack, DamageRoll, DamageType
from arena.models.character import Creature, Feature
from arena.models.conditions import AppliedCondition, Condition
from arena.models.encounter import CombatantEntry, Encounter
from arena.models.monster import Monster

DATA = Path(__file__).resolve().parent.parent / "data"


def _feat(name, **flags):
    return Feature(name=name, description="x", **flags)


def _melee(name="Bite", ability="strength"):
    return Action(name=name, description="x", action_type=ActionType.ACTION,
                  attack=Attack(name=name, attack_type="melee_weapon", ability=ability,
                                reach=5,
                                damage=[DamageRoll(dice="2d4", damage_type=DamageType.PIERCING,
                                                   ability_modifier=ability)]))


def _ranged(name="Spit", ability="dexterity"):
    return Action(name=name, description="x", action_type=ActionType.ACTION,
                  attack=Attack(name=name, attack_type="ranged_weapon", ability=ability,
                                reach=5, range_normal=80, range_long=120,
                                damage=[DamageRoll(dice="1d6", damage_type=DamageType.PIERCING,
                                                   ability_modifier=ability)]))


def _scene(attacker, target, *, melee=True):
    """attacker + target with a combatants+grid context, returning the
    AttackHitResult. Melee pairs are adjacent; ranged places the target a few
    hexes off (within normal range, NOT in melee) so the aura mechanic under
    test stays isolated from D-ACT-4's long-range / in-melee disadvantage."""
    tgt_pos = HexCoord(2, 3) if melee else HexCoord(2, 6)  # adjacent vs 20 ft
    grid = HexGrid(10, 10)
    grid.place_creature(HexCoord(2, 2), "atk")
    grid.place_creature(tgt_pos, "tgt")
    combatants = {
        "atk": Combatant(creature_id="atk", creature=attacker, team="enemy",
                         position=HexCoord(2, 2)),
        "tgt": Combatant(creature_id="tgt", creature=target, team="player",
                         position=tgt_pos),
    }
    action = _melee() if melee else _ranged()
    return resolve_attack_hit(attacker, "atk", target, "tgt", action, grid,
                              combatants=combatants,
                              attacker_pos=HexCoord(2, 2), target_pos=tgt_pos)


# ── Blood Frenzy ─────────────────────────────────────────────────────────────

def _frenzied():
    return Monster(name="Sahuagin", max_hit_points=22, armor_class=12,
                   ability_scores=AbilityScores(strength=13), proficiency_bonus=2,
                   special_abilities=[_feat("Blood Frenzy", attack_advantage_vs_damaged=True)])


def _victim(cur, mx=20):
    return Creature(name="Hero", max_hit_points=mx, current_hit_points=cur,
                    armor_class=14, ability_scores=AbilityScores())


def test_blood_frenzy_advantage_vs_damaged_target():
    res = _scene(_frenzied(), _victim(cur=10))
    assert res.effective_advantage == 1


def test_blood_frenzy_no_advantage_vs_full_hp_target():
    res = _scene(_frenzied(), _victim(cur=20))
    assert res.effective_advantage == 0


def test_blood_frenzy_no_advantage_on_ranged_attack():
    res = _scene(_frenzied(), _victim(cur=10), melee=False)
    assert res.effective_advantage == 0


def test_blood_frenzy_requires_the_trait():
    plain = Monster(name="Sahuagin", max_hit_points=22, armor_class=12,
                    ability_scores=AbilityScores(strength=13), proficiency_bonus=2)
    res = _scene(plain, _victim(cur=10))
    assert res.effective_advantage == 0


# ── Reckless Attack: the advantage effect ────────────────────────────────────

def _reckless_cond():
    return AppliedCondition(condition=Condition.RECKLESS, source="test",
                            duration_type="rounds", duration_rounds=1)


def test_reckless_attacker_has_advantage_on_its_melee():
    atk = Monster(name="Minotaur", max_hit_points=76, armor_class=14,
                  ability_scores=AbilityScores(strength=18), proficiency_bonus=2)
    atk.active_conditions.append(_reckless_cond())
    res = _scene(atk, _victim(cur=20))
    assert res.effective_advantage == 1


def test_reckless_attacker_no_self_advantage_on_ranged():
    atk = Monster(name="Minotaur", max_hit_points=76, armor_class=14,
                  ability_scores=AbilityScores(strength=18, dexterity=12),
                  proficiency_bonus=2)
    atk.active_conditions.append(_reckless_cond())
    res = _scene(atk, _victim(cur=20), melee=False)
    assert res.effective_advantage == 0


def test_attacks_against_reckless_target_have_advantage():
    target = _victim(cur=20)
    target.active_conditions.append(_reckless_cond())
    plain = Monster(name="Orc", max_hit_points=15, armor_class=13,
                    ability_scores=AbilityScores(strength=16), proficiency_bonus=2)
    res = _scene(plain, target)
    assert res.effective_advantage == 1


def test_advantage_against_reckless_target_even_at_range():
    target = _victim(cur=20)
    target.active_conditions.append(_reckless_cond())
    plain = Monster(name="Archer", max_hit_points=15, armor_class=13,
                    ability_scores=AbilityScores(dexterity=16), proficiency_bonus=2)
    res = _scene(plain, target, melee=False)
    assert res.effective_advantage == 1


# ── Reckless Attack: the start-of-turn auto-apply ────────────────────────────

def _solo_manager(creature, *, team="enemy"):
    enc = Encounter(name="t", grid_width=10, grid_height=10, combatants=[
        CombatantEntry(creature_id="m", creature_data=creature, team=team,
                       starting_position=(1, 1)),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    cid = next(iter(cm.combatants))
    return cm, cid


def _minotaur():
    return Monster.model_validate(
        json.loads((DATA / "monsters/srd/minotaur.json").read_text(encoding="utf-8")))


def test_minotaur_goes_reckless_at_start_of_turn():
    cm, cid = _solo_manager(_minotaur())
    cm._process_reckless_start_of_turn(cm.combatants[cid])
    assert any(ac.condition == Condition.RECKLESS
               for ac in cm.combatants[cid].creature.active_conditions)


def test_plain_monster_does_not_go_reckless():
    goblin = Monster(name="Goblin", max_hit_points=7, armor_class=15,
                     ability_scores=AbilityScores(), actions=[_melee()])
    cm, cid = _solo_manager(goblin)
    cm._process_reckless_start_of_turn(cm.combatants[cid])
    assert not any(ac.condition == Condition.RECKLESS
                   for ac in cm.combatants[cid].creature.active_conditions)


def test_player_controlled_reckless_monster_is_not_auto_applied():
    # Reckless auto-activation is a monster-AI behavior; PCs choose for themselves.
    pc = Creature(name="Barb", max_hit_points=30, armor_class=14,
                  ability_scores=AbilityScores(strength=16), is_player_controlled=True,
                  actions=[_melee()],
                  features=[_feat("Reckless Attack", reckless_attacker=True)])
    cm, cid = _solo_manager(pc, team="player")
    cm._process_reckless_start_of_turn(cm.combatants[cid])
    assert not any(ac.condition == Condition.RECKLESS
                   for ac in cm.combatants[cid].creature.active_conditions)


# ── Stench (start-of-turn aura save → poisoned) ──────────────────────────────

def _ghast():
    return Monster.model_validate(
        json.loads((DATA / "monsters/srd/ghast.json").read_text(encoding="utf-8")))


def _stench_scene(*, adjacent=True):
    ghast = _ghast()
    hero = Creature(name="Hero", max_hit_points=30, current_hit_points=30,
                    ability_scores=AbilityScores(), proficiency_bonus=2)
    hero_pos = (1, 2) if adjacent else (8, 8)
    enc = Encounter(name="stench", grid_width=12, grid_height=12, combatants=[
        CombatantEntry(creature_id="ghast", creature_data=ghast, team="enemy",
                       starting_position=(1, 1)),
        CombatantEntry(creature_id="hero", creature_data=hero, team="player",
                       starting_position=hero_pos),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    gid = next(k for k, v in cm.combatants.items() if v.team == "enemy")
    hid = next(k for k, v in cm.combatants.items() if v.team == "player")
    return cm, gid, hid


def _hero_poisoned(cm, hid):
    return any(ac.condition == Condition.POISONED
               for ac in cm.combatants[hid].creature.active_conditions)


def test_stench_poisons_on_failed_save():
    cm, gid, hid = _stench_scene()
    with patch("arena.combat.actions.roll_die", return_value=1):
        cm._process_stench_start_of_turn(cm.combatants[hid])
    assert _hero_poisoned(cm, hid)


def test_stench_success_grants_fight_immunity():
    cm, gid, hid = _stench_scene()
    with patch("arena.combat.actions.roll_die", return_value=20):
        cm._process_stench_start_of_turn(cm.combatants[hid])
    assert not _hero_poisoned(cm, hid)
    assert (hid, gid) in cm._stench_immune
    # A later turn: even a nat-1 must NOT re-roll (immune for the fight).
    with patch("arena.combat.actions.roll_die", return_value=1):
        cm._process_stench_start_of_turn(cm.combatants[hid])
    assert not _hero_poisoned(cm, hid)


def test_stench_no_save_when_out_of_range():
    cm, gid, hid = _stench_scene(adjacent=False)
    with patch("arena.combat.actions.roll_die", return_value=1):
        events = cm._process_stench_start_of_turn(cm.combatants[hid])
    assert events == []
    assert not _hero_poisoned(cm, hid)


# ── Heated Body (fire damage back to a melee attacker) ───────────────────────

def _salamander():
    return Monster.model_validate(
        json.loads((DATA / "monsters/srd/salamander.json").read_text(encoding="utf-8")))


def _heated_scene():
    sal = _salamander()
    hero = Creature(name="Hero", max_hit_points=40, current_hit_points=40,
                    ability_scores=AbilityScores(strength=16), proficiency_bonus=3,
                    is_player_controlled=True, actions=[_melee("Sword")])
    enc = Encounter(name="heat", grid_width=10, grid_height=10, combatants=[
        CombatantEntry(creature_id="sal", creature_data=sal, team="enemy",
                       starting_position=(1, 1)),
        CombatantEntry(creature_id="hero", creature_data=hero, team="player",
                       starting_position=(1, 2)),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    sid = next(k for k, v in cm.combatants.items() if v.team == "enemy")
    hid = next(k for k, v in cm.combatants.items() if v.team == "player")
    return cm, sid, hid


def _hr(target_id, attacker_id, *, hit=True, melee=True):
    return SimpleNamespace(
        hit=hit, critical=False, target_id=target_id, attacker_id=attacker_id,
        attack=SimpleNamespace(
            attack_type="melee_weapon" if melee else "ranged_weapon"))


def test_heated_body_burns_a_melee_attacker():
    cm, sid, hid = _heated_scene()
    start = cm.combatants[hid].creature.current_hit_points
    cm._apply_heated_body(_hr(sid, hid))
    assert cm.combatants[hid].creature.current_hit_points < start


def test_heated_body_ignores_ranged_attacks():
    cm, sid, hid = _heated_scene()
    start = cm.combatants[hid].creature.current_hit_points
    cm._apply_heated_body(_hr(sid, hid, melee=False))
    assert cm.combatants[hid].creature.current_hit_points == start


def test_heated_body_ignores_a_miss():
    cm, sid, hid = _heated_scene()
    start = cm.combatants[hid].creature.current_hit_points
    cm._apply_heated_body(_hr(sid, hid, hit=False))
    assert cm.combatants[hid].creature.current_hit_points == start


def test_non_heated_body_monster_does_not_retaliate():
    cm, sid, hid = _heated_scene()
    cm.combatants[sid].creature = Monster(name="Goblin", max_hit_points=7,
                                          armor_class=15, ability_scores=AbilityScores())
    start = cm.combatants[hid].creature.current_hit_points
    cm._apply_heated_body(_hr(sid, hid))
    assert cm.combatants[hid].creature.current_hit_points == start


def test_heated_body_fires_end_to_end_through_complete_attack():
    """Guards the wiring: a real melee hit resolved via complete_attack must
    leave the attacker burned by the salamander's Heated Body."""
    cm, sid, hid = _heated_scene()
    sal = cm.combatants[sid].creature
    hero = cm.combatants[hid].creature
    start = hero.current_hit_points
    action = _melee("Sword")
    hr = AttackHitResult(
        hit=True, critical=False, natural_roll=18, modifier=5,
        total_roll=23, target_ac=sal.armor_class, effective_advantage=0, events=[],
        attacker=hero, attacker_id=hid, target=sal, target_id=sid,
        action=action, attack=action.attack, combatants=cm.combatants)
    cm.complete_attack(hr)
    assert hero.current_hit_points < start  # took Heated Body fire
