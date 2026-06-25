"""Tests for Bardic Inspiration & Cutting Words (the reaction-modify-roll mechanic).

A banked Bardic Inspiration die nudges a d20 roll: the inspired creature adds it
to flip its own miss into a hit / a failed save into a success / a lost contest
into a win; a Lore bard subtracts it (Cutting Words) to flip an enemy's hit into a
miss, blunt a would-be downing blow, or spoil a winning contest. Auto-optimal use
(spent only when it can flip the outcome; on damage, only when the blow is lethal).
Covers attack rolls, saving throws, contested checks, and damage. A player-choice
prompt for the cleanest pause points (attack + save) is the remaining follow-up.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena.combat.actions import resolve_attack_hit, resolve_saving_throw
from arena.combat.bardic import (
    grant_inspiration, inspiration_die_size, find_cutting_words_bard,
    apply_bardic_inspiration_to_roll, apply_bard_dice_to_contest,
    apply_cutting_words_to_damage,
)
from arena.combat.damage import DamagePacket
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


def _cb(creature, team):
    """A minimal Combatant stand-in for the pure bard helpers (they read only
    .creature and .team; the dict key is the id)."""
    return SimpleNamespace(creature=creature, team=team, creature_id=creature.name)


def _lore_bard(pool=2, die=8):
    bard = PlayerCharacter(name="Lorebard", character_class="Bard", max_hit_points=18,
                           ability_scores=AbilityScores(charisma=16), proficiency_bonus=3,
                           features=[Feature(name="Cutting Words", description="x", cutting_words=True)])
    bard.class_resources = {"bardic_inspiration": pool, "bardic_inspiration_die": die}
    return bard


class TestBardicInspirationOnSaves:
    def test_rescues_a_failed_save(self):
        c = Creature(name="C", max_hit_points=10, ability_scores=AbilityScores())
        grant_inspiration(c, "c", 8, "bard")
        with patch("arena.combat.bardic.roll_die", return_value=5):
            total, ok, det = apply_bardic_inspiration_to_roll(c, total=10, target=13)
        assert ok is True and total == 15 and "SUCCESS" in det
        assert inspiration_die_size(c) is None              # die consumed

    def test_not_spent_when_save_already_passed(self):
        c = Creature(name="C", max_hit_points=10, ability_scores=AbilityScores())
        grant_inspiration(c, "c", 8, "bard")
        total, ok, det = apply_bardic_inspiration_to_roll(c, total=15, target=13)
        assert ok is True and det is None and inspiration_die_size(c) == 8

    def test_not_spent_when_gap_exceeds_die(self):
        c = Creature(name="C", max_hit_points=10, ability_scores=AbilityScores())
        grant_inspiration(c, "c", 8, "bard")
        total, ok, det = apply_bardic_inspiration_to_roll(c, total=2, target=13)  # gap 11 > d8
        assert ok is False and det is None and inspiration_die_size(c) == 8

    def test_resolve_saving_throw_threads_the_die(self):
        c = Creature(name="C", max_hit_points=10, ability_scores=AbilityScores())  # +0 WIS
        grant_inspiration(c, "c", 8, "bard")
        with patch("arena.combat.actions.roll_die", return_value=10):  # 10 vs DC 13 → fail by 3
            with patch("arena.combat.bardic.roll_die", return_value=5):  # +5 → 15 → pass
                ok, ev = resolve_saving_throw(c, "c", "wisdom", 13)
        assert ok is True
        assert ev.details["success"] is True
        assert inspiration_die_size(c) is None


class TestCuttingWordsOnDamage:
    def test_blunts_a_lethal_blow(self):
        ally = Creature(name="Ally", max_hit_points=20, ability_scores=AbilityScores())
        ally.current_hit_points = 8
        bard = _lore_bard()
        combatants = {"ally": _cb(ally, "player"), "bard": _cb(bard, "player")}
        packets = [DamagePacket(amount=10, dtype="slashing")]
        with patch("arena.combat.bardic.roll_die", return_value=6):
            evs = apply_cutting_words_to_damage(ally, "ally", packets, combatants)
        assert packets[0].amount == 4                       # 10 - 6
        assert bard.class_resources["bardic_inspiration"] == 1
        assert evs

    def test_skips_non_lethal_damage(self):
        ally = Creature(name="Ally", max_hit_points=20, ability_scores=AbilityScores())
        ally.current_hit_points = 20
        bard = _lore_bard()
        combatants = {"ally": _cb(ally, "player"), "bard": _cb(bard, "player")}
        packets = [DamagePacket(amount=5, dtype="slashing")]
        evs = apply_cutting_words_to_damage(ally, "ally", packets, combatants)
        assert packets[0].amount == 5 and evs == []
        assert bard.class_resources["bardic_inspiration"] == 2  # die preserved


class TestBardicAttackPrompt:
    """Player-choice prompt: a player attacker who misses but holds a flippable
    die is offered the spend (NPCs still auto-spend)."""

    def _combat(self, attacker_player=True):
        if attacker_player:
            atk = PlayerCharacter(name="Fighter", character_class="Fighter", max_hit_points=30,
                                  ability_scores=AbilityScores(strength=14), proficiency_bonus=2)
        else:
            atk = Creature(name="Fighter", max_hit_points=30,
                           ability_scores=AbilityScores(strength=14), proficiency_bonus=2,
                           is_player_controlled=False)
        atk.actions = [_weapon()]
        grant_inspiration(atk, "atk", 8, "bard")
        orc = Creature(name="Orc", max_hit_points=20, armor_class=16,
                       ability_scores=AbilityScores(), is_player_controlled=False)
        enc = Encounter(name="t", grid_width=8, grid_height=8, combatants=[
            CombatantEntry(creature_id="atk", creature_data=atk, team="player", starting_position=(2, 2)),
            CombatantEntry(creature_id="orc", creature_data=orc, team="enemy", starting_position=(2, 3)),
        ])
        cm = CombatManager(); cm.load_encounter(enc, Path("."))
        with patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
            cm.roll_initiative()
        cm.begin_combat()
        ids = {c.creature.name: cid for cid, c in cm.combatants.items()}
        cm.selected_action = cm.combatants[ids["Fighter"]].creature.actions[0]
        return cm, ids

    def _miss(self, cm, ids):
        # nat 10 + STR 2 + prof 2 = 14 vs AC 16 → miss by 2 (≤ d8)
        with patch("arena.combat.actions.roll_die", return_value=10):
            return cm.execute_attack(ids["Orc"])

    def test_player_miss_defers_for_prompt(self):
        cm, ids = self._combat(attacker_player=True)
        res = self._miss(cm, ids)
        assert res is None                                   # deferred, no popup-less resolution
        assert cm._pending_bardic_choice is not None
        assert inspiration_die_size(cm.combatants[ids["Fighter"]].creature) == 8  # not yet spent

    def test_resolve_use_flips_to_hit_and_consumes_die(self):
        cm, ids = self._combat(attacker_player=True)
        self._miss(cm, ids)
        fighter = cm.combatants[ids["Fighter"]].creature
        with patch("arena.combat.manager.roll_die", return_value=5):  # d8=5 → 14+5=19 ≥ 16
            cm.resolve_bardic_choice(use=True)
        assert cm._pending_bardic_choice is None
        assert inspiration_die_size(fighter) is None         # die consumed
        assert cm.combatants[ids["Orc"]].creature.current_hit_points < 20  # the hit landed

    def test_resolve_skip_keeps_miss_and_die(self):
        cm, ids = self._combat(attacker_player=True)
        self._miss(cm, ids)
        fighter = cm.combatants[ids["Fighter"]].creature
        cm.resolve_bardic_choice(use=False)
        assert cm._pending_bardic_choice is None
        assert inspiration_die_size(fighter) == 8            # die kept for later
        assert cm.combatants[ids["Orc"]].creature.current_hit_points == 20  # still a miss

    def test_npc_attacker_auto_spends_without_a_prompt(self):
        cm, ids = self._combat(attacker_player=False)
        with patch("arena.combat.actions.roll_die", return_value=10):
            with patch("arena.combat.bardic.roll_die", return_value=5):  # auto d8=5 → hit
                cm.execute_attack(ids["Orc"])
        assert cm._pending_bardic_choice is None             # never deferred
        assert inspiration_die_size(cm.combatants[ids["Fighter"]].creature) is None  # auto-spent


class TestBardDiceOnContests:
    def test_roller_adds_own_die_to_win(self):
        roller = Creature(name="Esc", max_hit_points=10, ability_scores=AbilityScores())
        grant_inspiration(roller, "esc", 8, "bard")
        with patch("arena.combat.bardic.roll_die", return_value=4):  # 12 +4 = 16 ≥ 14
            total, win, evs = apply_bard_dice_to_contest(roller, "esc", "grap", 12, 14, {})
        assert win is True and total == 16 and evs
        assert inspiration_die_size(roller) is None

    def test_enemy_cutting_words_flips_a_winning_roll(self):
        roller = Creature(name="Esc", max_hit_points=10, ability_scores=AbilityScores())
        grappler = Creature(name="Grap", max_hit_points=20, ability_scores=AbilityScores())
        bard = _lore_bard()
        combatants = {"esc": _cb(roller, "player"), "grap": _cb(grappler, "enemy"),
                      "bard": _cb(bard, "enemy")}
        # roller 15 vs 14 → winning by 1; CW d8=6 → 9 < 14 → loses
        with patch("arena.combat.bardic.roll_die", return_value=6):
            total, win, evs = apply_bard_dice_to_contest(roller, "esc", "grap", 15, 14, combatants)
        assert win is False and evs
        assert bard.class_resources["bardic_inspiration"] == 1
