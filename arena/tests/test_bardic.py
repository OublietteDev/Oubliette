"""Tests for Bardic Inspiration & Cutting Words (the reaction-modify-roll mechanic).

A banked Bardic Inspiration die nudges an attack roll: the inspired creature adds
it to flip its own miss into a hit; a defending bard subtracts it (Cutting Words)
to flip an enemy's hit into a miss. Auto-optimal use (spent only when it can flip
the outcome). Applied here to attack rolls; saves/checks/damage + a player-choice
prompt are noted follow-ups.
"""
from pathlib import Path
from unittest.mock import patch

from arena.combat.actions import resolve_attack_hit
from arena.combat.bardic import (
    grant_inspiration, inspiration_die_size, find_cutting_words_bard,
)
from arena.combat.manager import CombatManager
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.character import Creature, PlayerCharacter, Feature
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType, TargetType
from arena.models.encounter import Encounter, CombatantEntry


def _weapon():
    return Action(name="Sword", description="x", action_type=ActionType.ACTION,
        attack=Attack(name="Sword", attack_type="melee_weapon", ability="strength", reach=5,
        damage=[DamageRoll(dice="1d8", damage_type=DamageType.SLASHING, ability_modifier="strength")]))


def _atkr(ac_target=16):
    atk = Creature(name="Fighter", max_hit_points=20,
                   ability_scores=AbilityScores(strength=14), proficiency_bonus=2)
    tgt = Creature(name="Dummy", max_hit_points=20, armor_class=ac_target,
                   ability_scores=AbilityScores())
    g = HexGrid(10, 10); g.place_creature(HexCoord(2, 2), "atk"); g.place_creature(HexCoord(2, 3), "tgt")
    return atk, tgt, g


def _attack(atk, tgt, g, nat, bard_roll=0):
    with patch("arena.combat.actions.roll_die", return_value=nat):
        with patch("arena.combat.bardic.roll_die", return_value=bard_roll):
            return resolve_attack_hit(atk, "atk", tgt, "tgt", _weapon(), g, combatants={},
                                      attacker_pos=HexCoord(2, 2), target_pos=HexCoord(2, 3))


class TestBardicInspirationGrantAndUse:
    def test_grant_banks_a_die(self):
        c = Creature(name="C", max_hit_points=10, ability_scores=AbilityScores())
        grant_inspiration(c, "c", 8, "bard")
        assert inspiration_die_size(c) == 8

    def test_inspiration_flips_close_miss_to_hit(self):
        atk, tgt, g = _atkr(ac_target=16)   # nat10+2=12, miss by 4
        grant_inspiration(atk, "atk", 8, "bard")
        res = _attack(atk, tgt, g, nat=10, bard_roll=5)  # +5 → 17 ≥ 16
        assert res.hit is True
        assert inspiration_die_size(atk) is None         # die consumed

    def test_inspiration_not_spent_when_gap_too_large(self):
        atk, tgt, g = _atkr(ac_target=25)   # nat10+2=12, miss by 13 > d8
        grant_inspiration(atk, "atk", 8, "bard")
        res = _attack(atk, tgt, g, nat=10, bard_roll=8)
        assert res.hit is False
        assert inspiration_die_size(atk) == 8            # not wasted

    def test_inspiration_not_spent_on_a_hit(self):
        atk, tgt, g = _atkr(ac_target=10)   # nat10+2=12 ≥ 10 → already hits
        grant_inspiration(atk, "atk", 8, "bard")
        res = _attack(atk, tgt, g, nat=10, bard_roll=8)
        assert res.hit is True
        assert inspiration_die_size(atk) == 8            # kept for later

    def test_grant_action_through_manager_spends_pool(self):
        bard = PlayerCharacter(name="Bard", character_class="Bard", max_hit_points=18,
                               ability_scores=AbilityScores(charisma=16), proficiency_bonus=3)
        bard.class_resources = {"bardic_inspiration": 2}
        ally = Creature(name="Ally", max_hit_points=20, ability_scores=AbilityScores())
        grant = Action(name="Bardic Inspiration", description="x",
                       action_type=ActionType.BONUS_ACTION, target_type=TargetType.ONE_ALLY,
                       grants_inspiration_die=8, resource_cost={"bardic_inspiration": 1})
        bard.actions = [grant]
        enc = Encounter(name="t", grid_width=8, grid_height=8, combatants=[
            CombatantEntry(creature_id="bard", creature_data=bard, team="player", starting_position=(1, 1)),
            CombatantEntry(creature_id="ally", creature_data=ally, team="player", starting_position=(1, 2)),
        ])
        cm = CombatManager(); cm.load_encounter(enc, Path("."))
        with patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
            cm.roll_initiative()
        cm.begin_combat()
        ids = {c.creature.name: cid for cid, c in cm.combatants.items()}
        cm.selected_action = grant
        cm.execute_effect(ids["Ally"])
        assert inspiration_die_size(cm.combatants[ids["Ally"]].creature) == 8
        assert cm.combatants[ids["Bard"]].creature.class_resources["bardic_inspiration"] == 1


class TestCuttingWords:
    def _combat(self, pool=2, die=8, with_feature=True):
        feats = [Feature(name="Cutting Words", description="x", cutting_words=True)] if with_feature else []
        bard = PlayerCharacter(name="Lorebard", character_class="Bard", max_hit_points=18,
                               ability_scores=AbilityScores(charisma=16), proficiency_bonus=3,
                               features=feats)
        bard.class_resources = {"bardic_inspiration": pool, "bardic_inspiration_die": die}
        ally = Creature(name="Ally", max_hit_points=20, armor_class=14, ability_scores=AbilityScores())
        orc = Creature(name="Orc", max_hit_points=20, ability_scores=AbilityScores(strength=14),
                       proficiency_bonus=2, is_player_controlled=False)
        enc = Encounter(name="t", grid_width=8, grid_height=8, combatants=[
            CombatantEntry(creature_id="ally", creature_data=ally, team="player", starting_position=(2, 2)),
            CombatantEntry(creature_id="bard", creature_data=bard, team="player", starting_position=(2, 1)),
            CombatantEntry(creature_id="orc", creature_data=orc, team="enemy", starting_position=(2, 3)),
        ])
        cm = CombatManager(); cm.load_encounter(enc, Path("."))
        with patch("arena.combat.manager.roll_die", side_effect=[20, 10, 1]):
            cm.roll_initiative()
        cm.begin_combat()
        return cm, {c.creature.name: cid for cid, c in cm.combatants.items()}

    def _orc_hits_ally(self, cm, ids, nat, bard_roll):
        with patch("arena.combat.actions.roll_die", return_value=nat):
            with patch("arena.combat.bardic.roll_die", return_value=bard_roll):
                return resolve_attack_hit(
                    cm.combatants[ids["Orc"]].creature, ids["Orc"],
                    cm.combatants[ids["Ally"]].creature, ids["Ally"],
                    _weapon(), cm.grid, combatants=cm.combatants,
                    attacker_pos=HexCoord(2, 3), target_pos=HexCoord(2, 2))

    def test_cutting_words_flips_hit_to_miss(self):
        cm, ids = self._combat()
        res = self._orc_hits_ally(cm, ids, nat=12, bard_roll=4)  # 14 hit → -4 → 10 miss
        assert res.hit is False
        assert cm.combatants[ids["Lorebard"]].creature.class_resources["bardic_inspiration"] == 1

    def test_cutting_words_not_used_when_cannot_flip(self):
        cm, ids = self._combat(die=8)
        res = self._orc_hits_ally(cm, ids, nat=20, bard_roll=8)  # nat20 crit-ish big margin
        # margin >= die → can't flip → not spent
        assert cm.combatants[ids["Lorebard"]].creature.class_resources["bardic_inspiration"] == 2

    def test_no_bard_no_cutting_words(self):
        cm, ids = self._combat(with_feature=False)
        bard, bid = find_cutting_words_bard(ids["Ally"], cm.combatants)
        assert bard is None

    def test_empty_pool_no_cutting_words(self):
        cm, ids = self._combat(pool=0)
        bard, bid = find_cutting_words_bard(ids["Ally"], cm.combatants)
        assert bard is None
