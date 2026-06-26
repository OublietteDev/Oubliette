"""D-MON-3: Regeneration.

A creature heals regeneration_amount at the start of its turn, unless it took a
negating damage type (acid/fire) since its last turn. apply_damage sets the
suppression flag; the start-of-turn hook reads and clears it.
"""

from pathlib import Path
from unittest.mock import patch

from arena.combat.damage import DamagePacket, apply_damage
from arena.combat.manager import CombatManager
from arena.combat.regeneration import process_regeneration_start_of_turn
from arena.models.abilities import AbilityScores
from arena.models.character import Creature
from arena.models.encounter import CombatantEntry, Encounter
from arena.models.monster import Monster


def _troll(hp: int = 50, amount: int = 10) -> Monster:
    return Monster(
        name="Troll", max_hit_points=84, current_hit_points=hp,
        ability_scores=AbilityScores(),
        regeneration_amount=amount, regeneration_negated_by=["acid", "fire"])


def test_heals_at_start_of_turn():
    troll = _troll(hp=50)
    events = process_regeneration_start_of_turn(troll, "t1")
    assert troll.current_hit_points == 60
    assert any(e.details.get("regeneration") for e in events)


def test_heal_capped_at_max_hp():
    troll = _troll(hp=80)  # max 84, +10 would overshoot
    process_regeneration_start_of_turn(troll, "t1")
    assert troll.current_hit_points == 84


def test_no_heal_at_full_hp():
    troll = _troll(hp=84)
    events = process_regeneration_start_of_turn(troll, "t1")
    assert troll.current_hit_points == 84
    assert events == []


def test_no_regen_from_zero():
    troll = _troll(hp=0)
    events = process_regeneration_start_of_turn(troll, "t1")
    assert troll.current_hit_points == 0  # defeated — stays down
    assert events == []


def test_creature_without_trait_unaffected():
    plain = Monster(name="Ogre", max_hit_points=59, current_hit_points=30,
                    ability_scores=AbilityScores())
    events = process_regeneration_start_of_turn(plain, "o1")
    assert plain.current_hit_points == 30
    assert events == []


def test_fire_damage_sets_suppression_flag():
    troll = _troll(hp=50)
    apply_damage(troll, [DamagePacket(amount=12, dtype="fire")], creature_id="t1")
    assert getattr(troll, "_regeneration_negated", False) is True


def test_non_negating_damage_does_not_set_flag():
    troll = _troll(hp=50)
    apply_damage(troll, [DamagePacket(amount=12, dtype="cold")], creature_id="t1")
    assert getattr(troll, "_regeneration_negated", False) is False


def test_suppressed_after_negating_damage_then_resumes():
    troll = _troll(hp=50)
    apply_damage(troll, [DamagePacket(amount=12, dtype="acid")], creature_id="t1")
    # current HP after the acid hit:
    after_hit = troll.current_hit_points
    # First turn: suppressed (no heal), flag consumed.
    events = process_regeneration_start_of_turn(troll, "t1")
    assert troll.current_hit_points == after_hit
    assert any(e.details.get("regeneration_suppressed") for e in events)
    # Next turn (no new acid/fire): heals again.
    process_regeneration_start_of_turn(troll, "t1")
    assert troll.current_hit_points == after_hit + 10


def test_regen_fires_at_turn_start_through_manager():
    caster = Creature(
        name="Caster", max_hit_points=30, current_hit_points=30,
        ability_scores=AbilityScores(), is_player_controlled=True, actions=[])
    troll = Monster(
        name="Troll", max_hit_points=84, current_hit_points=50,
        ability_scores=AbilityScores(), is_player_controlled=False,
        regeneration_amount=10, regeneration_negated_by=["acid", "fire"])
    encounter = Encounter(
        name="Regen", grid_width=10, grid_height=10, combatants=[
            CombatantEntry(creature_id="caster", creature_data=caster,
                           team="player", starting_position=(4, 4)),
            CombatantEntry(creature_id="troll", creature_data=troll,
                           team="enemy", starting_position=(6, 6)),
        ])
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10]):
        cm.roll_initiative()
    cm.begin_combat()  # caster first
    cm.end_turn()      # troll's turn begins → regeneration fires
    troll_key = next(k for k, v in cm.combatants.items() if v.team == "enemy")
    assert cm.combatants[troll_key].creature.current_hit_points == 60
