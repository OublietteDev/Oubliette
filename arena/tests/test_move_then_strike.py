"""D-MON-4c: move-then-strike riders — Charge / Pounce / Trampling Charge.

A charge rider only fires when the attacker moved at least its threshold toward
the target this turn (approximated as 'closed that distance straight in'). On a
qualifying hit it deals bonus damage and/or forces a STR save vs prone, using the
stat block's verbatim DC (Trampling Charge's DC is not 8+prof+mod).
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena.combat.manager import CombatManager
from arena.combat.riders import calculate_rider_save_dc, resolve_rider
from arena.grid.coordinates import HexCoord
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, ActionType, Attack, DamageRoll, DamageType
from arena.models.character import Creature, Feature, OnHitRider, RiderTrigger
from arena.models.encounter import CombatantEntry, Encounter
from arena.models.monster import Monster


def _charge_rider():
    return OnHitRider(
        trigger=RiderTrigger.AUTOMATIC, once_per_turn=True, requires_melee=True,
        requires_charge_ft=20, damage_dice="1d6", damage_type="slashing",
        save_ability="strength", save_dc_fixed=11, condition_on_fail="prone",
        condition_duration="indefinite", condition_save_to_end=False)


def _tusk():
    return Action(name="Tusk", description="x", action_type=ActionType.ACTION,
                  attack=Attack(name="Tusk", attack_type="melee_weapon", ability="strength",
                                reach=5,
                                damage=[DamageRoll(dice="1d6", damage_type=DamageType.SLASHING,
                                                   ability_modifier="strength")]))


def _boar():
    return Monster(name="Boar", max_hit_points=11, armor_class=11,
                   ability_scores=AbilityScores(strength=12), proficiency_bonus=2,
                   special_abilities=[Feature(name="Charge", description="x",
                                              on_hit_rider=_charge_rider())],
                   actions=[_tusk()])


# ── Fixed save DC (Trampling Charge doesn't use 8+prof+mod) ───────────────────

def test_fixed_dc_overrides_computed():
    rider = OnHitRider(save_ability="strength", save_dc_ability="strength",
                       save_dc_fixed=13, condition_on_fail="prone")
    beefy = Monster(name="Triceratops", max_hit_points=95,
                    ability_scores=AbilityScores(strength=22), proficiency_bonus=3)
    # 8 + 3 + 6 = 17 computed, but the block says 13.
    assert calculate_rider_save_dc(rider, beefy) == 13


# ── The movement gate ─────────────────────────────────────────────────────────

def _scene():
    boar, target = _boar(), Creature(name="Hero", max_hit_points=30, armor_class=10,
                                     ability_scores=AbilityScores(), is_player_controlled=True)
    enc = Encounter(name="charge", grid_width=20, grid_height=12, combatants=[
        CombatantEntry(creature_id="hero", creature_data=target, team="player",
                       starting_position=(0, 0)),
        CombatantEntry(creature_id="boar", creature_data=boar, team="enemy",
                       starting_position=(8, 0)),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10]):
        cm.roll_initiative()
    cm.begin_combat()
    boar_id = next(k for k, v in cm.combatants.items() if v.team == "enemy")
    hero_id = next(k for k, v in cm.combatants.items() if v.team == "player")
    return cm, boar_id, hero_id


def _hit_result(cm, boar_id, hero_id):
    boar = cm.combatants[boar_id]
    return SimpleNamespace(hit=True, attacker=boar.creature, attacker_id=boar_id,
                           target=cm.combatants[hero_id].creature, target_id=hero_id,
                           action=_tusk(), attack=_tusk().attack)


def test_charged_when_closed_the_distance():
    cm, boar_id, hero_id = _scene()
    cm.movement.reset(boar_id, 40, position=HexCoord(8, 0))
    cm.movement.has_moved = True
    cm.combatants[boar_id].position = HexCoord(1, 0)  # adjacent to hero at (0,0)
    assert cm._attacker_charged(_hit_result(cm, boar_id, hero_id), 20) is True


def test_not_charged_when_stationary():
    cm, boar_id, hero_id = _scene()
    cm.movement.reset(boar_id, 40, position=HexCoord(1, 0))  # already adjacent
    cm.movement.has_moved = False
    cm.combatants[boar_id].position = HexCoord(1, 0)
    assert cm._attacker_charged(_hit_result(cm, boar_id, hero_id), 20) is False


def test_get_applicable_riders_includes_charge_only_when_charged():
    cm, boar_id, hero_id = _scene()
    # Charged in:
    cm.movement.reset(boar_id, 40, position=HexCoord(8, 0))
    cm.movement.has_moved = True
    cm.combatants[boar_id].position = HexCoord(1, 0)
    names = [f.name for f, _ in cm.get_applicable_riders(_hit_result(cm, boar_id, hero_id))]
    assert "Charge" in names
    # Stood still:
    cm.movement.reset(boar_id, 40, position=HexCoord(1, 0))
    cm.movement.has_moved = False
    names = [f.name for f, _ in cm.get_applicable_riders(_hit_result(cm, boar_id, hero_id))]
    assert "Charge" not in names


# ── The rider effect (bonus damage + prone on a failed save) ──────────────────

def test_charge_rider_applies_damage_and_prone_on_failed_save():
    boar = _boar()
    target = Creature(name="Hero", max_hit_points=30, ability_scores=AbilityScores())
    feat = boar.special_abilities[0]
    with patch("arena.combat.riders.roll_die", return_value=1):  # save fails
        rr = resolve_rider(feat, feat.on_hit_rider, boar, target)
    assert rr.used
    assert rr.condition_to_apply == "prone"
    assert rr.bonus_damage and rr.bonus_damage[0].dice == "1d6"
    assert rr.save_dc == 11  # fixed DC from the block


def test_complete_attack_applies_charge_prone_on_failed_save():
    """End-to-end through complete_attack: a charge hit whose save fails leaves
    the target prone. Guards the rider condition-application fix (the old code
    passed a bool as save_to_end and an AppliedCondition where a Condition was
    expected, so no rider ever applied its condition)."""
    from arena.combat.actions import resolve_attack_hit
    from arena.combat.conditions import has_condition
    from arena.combat.riders import resolve_rider
    from arena.models.conditions import Condition

    boar = _boar()
    hero = Creature(name="Hero", max_hit_points=40, current_hit_points=40,
                    armor_class=1, ability_scores=AbilityScores(strength=6),
                    is_player_controlled=False)
    enc = Encounter(name="adj", grid_width=10, grid_height=10, combatants=[
        CombatantEntry(creature_id="hero", creature_data=hero, team="player",
                       starting_position=(0, 0)),
        CombatantEntry(creature_id="boar", creature_data=boar, team="enemy",
                       starting_position=(1, 0)),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10]):
        cm.roll_initiative()
    cm.begin_combat()
    boar_id = next(k for k, v in cm.combatants.items() if v.team == "enemy")
    hero_id = next(k for k, v in cm.combatants.items() if v.team == "player")

    with patch("arena.combat.actions.roll_die", return_value=20):  # guaranteed hit
        hr = resolve_attack_hit(
            boar, boar_id, cm.combatants[hero_id].creature, hero_id,
            boar.actions[0], cm.grid, combatants=cm.combatants,
            attacker_pos=cm.combatants[boar_id].position,
            target_pos=cm.combatants[hero_id].position)
    assert hr.hit
    feat = boar.special_abilities[0]
    with patch("arena.combat.riders.roll_die", return_value=1):  # save fails
        rr = resolve_rider(feat, feat.on_hit_rider, boar,
                           cm.combatants[hero_id].creature)
    cm.complete_attack(hr, rider_results=[rr])
    assert has_condition(cm.combatants[hero_id].creature, Condition.PRONE)


def test_charge_rider_no_prone_on_successful_save():
    boar = _boar()
    target = Creature(name="Hero", max_hit_points=30, ability_scores=AbilityScores())
    feat = boar.special_abilities[0]
    with patch("arena.combat.riders.roll_die", return_value=20):  # save succeeds
        rr = resolve_rider(feat, feat.on_hit_rider, boar, target)
    assert rr.condition_to_apply is None
    assert rr.bonus_damage  # damage still applies regardless of the save


# ── The GUI-facing charge marker (animation sequencing) ───────────────────────

def test_resolve_rider_marks_charge_riders():
    boar = _boar()
    target = Creature(name="Hero", max_hit_points=30, ability_scores=AbilityScores())
    feat = boar.special_abilities[0]
    with patch("arena.combat.riders.roll_die", return_value=20):
        rr = resolve_rider(feat, feat.on_hit_rider, boar, target)
    assert rr.from_charge is True

    plain = OnHitRider(trigger=RiderTrigger.AUTOMATIC, damage_dice="1d6",
                       damage_type="radiant")
    plain_feat = Feature(name="Smitey", description="x", on_hit_rider=plain)
    rr2 = resolve_rider(plain_feat, plain, boar, target)
    assert rr2.from_charge is False


def test_charge_hit_stamps_damage_event():
    """complete_attack stamps `charged: True` on the damage event when a
    move-then-strike rider fired, so the GUI can play the hit as a charge."""
    from arena.combat.actions import resolve_attack_hit
    from arena.combat.events import CombatEventType

    boar = _boar()
    hero = Creature(name="Hero", max_hit_points=40, current_hit_points=40,
                    armor_class=1, ability_scores=AbilityScores(strength=6),
                    is_player_controlled=False)
    enc = Encounter(name="adj", grid_width=10, grid_height=10, combatants=[
        CombatantEntry(creature_id="hero", creature_data=hero, team="player",
                       starting_position=(0, 0)),
        CombatantEntry(creature_id="boar", creature_data=boar, team="enemy",
                       starting_position=(1, 0)),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10]):
        cm.roll_initiative()
    cm.begin_combat()
    boar_id = next(k for k, v in cm.combatants.items() if v.team == "enemy")
    hero_id = next(k for k, v in cm.combatants.items() if v.team == "player")

    with patch("arena.combat.actions.roll_die", return_value=20):
        hr = resolve_attack_hit(
            boar, boar_id, cm.combatants[hero_id].creature, hero_id,
            boar.actions[0], cm.grid, combatants=cm.combatants,
            attacker_pos=cm.combatants[boar_id].position,
            target_pos=cm.combatants[hero_id].position)
    assert hr.hit
    feat = boar.special_abilities[0]
    with patch("arena.combat.riders.roll_die", return_value=1):
        rr = resolve_rider(feat, feat.on_hit_rider, boar,
                           cm.combatants[hero_id].creature)
    cm.complete_attack(hr, rider_results=[rr])

    dmg_events = [e for e in cm.log.events
                  if e.event_type == CombatEventType.DAMAGE
                  and e.target_id == hero_id]
    assert dmg_events and dmg_events[0].details.get("charged") is True


def test_plain_hit_does_not_stamp_charged():
    """No rider → no charge marker on the damage event."""
    from arena.combat.actions import resolve_attack_hit
    from arena.combat.events import CombatEventType

    boar = _boar()
    hero = Creature(name="Hero", max_hit_points=40, current_hit_points=40,
                    armor_class=1, ability_scores=AbilityScores(strength=6),
                    is_player_controlled=False)
    enc = Encounter(name="adj", grid_width=10, grid_height=10, combatants=[
        CombatantEntry(creature_id="hero", creature_data=hero, team="player",
                       starting_position=(0, 0)),
        CombatantEntry(creature_id="boar", creature_data=boar, team="enemy",
                       starting_position=(1, 0)),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10]):
        cm.roll_initiative()
    cm.begin_combat()
    boar_id = next(k for k, v in cm.combatants.items() if v.team == "enemy")
    hero_id = next(k for k, v in cm.combatants.items() if v.team == "player")

    with patch("arena.combat.actions.roll_die", return_value=20):
        hr = resolve_attack_hit(
            boar, boar_id, cm.combatants[hero_id].creature, hero_id,
            boar.actions[0], cm.grid, combatants=cm.combatants,
            attacker_pos=cm.combatants[boar_id].position,
            target_pos=cm.combatants[hero_id].position)
    assert hr.hit
    cm.complete_attack(hr)

    dmg_events = [e for e in cm.log.events
                  if e.event_type == CombatEventType.DAMAGE
                  and e.target_id == hero_id]
    assert dmg_events and "charged" not in dmg_events[0].details
