"""D-MON-4b: death-triggered traits — Undead Fortitude & Death Burst.

Undead Fortitude (zombies): a CON save (DC 5 + damage) drags the creature back
to 1 HP on a 0-HP hit, unless that hit was radiant or a critical.

Death Burst (mephits, magmin): on death the creature detonates, forcing a save
on every creature within its radius (indiscriminate).
"""

from pathlib import Path
from unittest.mock import patch

from arena.combat.damage import apply_damage
from arena.combat.manager import CombatManager
from arena.models.abilities import AbilityScores
from arena.models.character import Creature
from arena.models.encounter import CombatantEntry, Encounter
from arena.models.monster import DeathBurst, Monster


# ── Undead Fortitude ─────────────────────────────────────────────────────────

def _zombie(hp=5, con=16):
    return Monster(name="Zombie", max_hit_points=22, current_hit_points=hp,
                   ability_scores=AbilityScores(constitution=con),
                   undead_fortitude=True)


def test_undead_fortitude_survives_on_successful_save():
    z = _zombie()  # CON +3
    with patch("arena.combat.death_prevention.roll_die", return_value=20):
        apply_damage(z, 10, "bludgeoning", "z1")  # drops to 0, DC 15, 20+3 >= 15
    assert z.current_hit_points == 1


def test_undead_fortitude_falls_on_failed_save():
    z = _zombie()
    with patch("arena.combat.death_prevention.roll_die", return_value=1):
        apply_damage(z, 10, "bludgeoning", "z1")  # 1+3 < 15
    assert z.current_hit_points == 0


def test_undead_fortitude_negated_by_radiant():
    z = _zombie()
    with patch("arena.combat.death_prevention.roll_die", return_value=20):
        _, extra = apply_damage(z, 10, "radiant", "z1")
    assert z.current_hit_points == 0  # radiant ignores the save entirely
    assert any(e.details.get("negated") == "radiant damage" for e in extra)


def test_undead_fortitude_negated_by_critical():
    z = _zombie()
    with patch("arena.combat.death_prevention.roll_die", return_value=20):
        _, extra = apply_damage(z, 10, "bludgeoning", "z1", is_critical=True)
    assert z.current_hit_points == 0
    assert any(e.details.get("negated") == "a critical hit" for e in extra)


def test_undead_fortitude_dc_scales_with_damage():
    """DC = 5 + damage: a big hit can outrun even a good save."""
    z = _zombie(con=16)  # +3
    with patch("arena.combat.death_prevention.roll_die", return_value=18):
        apply_damage(z, 30, "bludgeoning", "z1")  # DC 35, 18+3=21 < 35
    assert z.current_hit_points == 0


def test_plain_creature_has_no_fortitude():
    c = Creature(name="Guard", max_hit_points=11, current_hit_points=4,
                 ability_scores=AbilityScores())
    apply_damage(c, 10, "bludgeoning", "g1")
    assert c.current_hit_points == 0


# ── Death Burst ──────────────────────────────────────────────────────────────

def _mephit(half_on_save=False):
    return Monster(
        name="Steam Mephit", max_hit_points=21, current_hit_points=21,
        ability_scores=AbilityScores(),
        death_burst=DeathBurst(radius_ft=5, save_ability="dexterity", save_dc=10,
                               damage_dice="2d8", damage_type="fire",
                               half_on_save=half_on_save))


def _burst_scene(half_on_save=False, target_far=False):
    mephit = _mephit(half_on_save=half_on_save)
    target = Creature(name="Hero", max_hit_points=30, current_hit_points=30,
                      armor_class=12, ability_scores=AbilityScores(),
                      is_player_controlled=True)
    tgt_pos = (9, 9) if target_far else (5, 6)
    enc = Encounter(name="burst", grid_width=12, grid_height=12, combatants=[
        CombatantEntry(creature_id="hero", creature_data=target, team="player",
                       starting_position=tgt_pos),
        CombatantEntry(creature_id="mephit", creature_data=mephit, team="enemy",
                       starting_position=(5, 5)),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10]):
        cm.roll_initiative()
    cm.begin_combat()
    hero_id = next(k for k, v in cm.combatants.items() if v.team == "player")
    mephit_id = next(k for k, v in cm.combatants.items() if v.team == "enemy")
    return cm, hero_id, mephit_id


def test_death_burst_damages_adjacent_on_failed_save():
    cm, hero_id, mephit_id = _burst_scene()
    cm.combatants[mephit_id].creature.current_hit_points = 0  # kill it
    with patch("arena.combat.actions.roll_die", return_value=1):      # save fails
        with patch("arena.util.dice.roll_expression", return_value=(13, [])):
            cm._check_victory()
    assert cm.combatants[hero_id].creature.current_hit_points == 30 - 13


def test_death_burst_no_damage_on_save_when_not_half():
    cm, hero_id, mephit_id = _burst_scene(half_on_save=False)
    cm.combatants[mephit_id].creature.current_hit_points = 0
    with patch("arena.combat.actions.roll_die", return_value=20):     # save succeeds
        with patch("arena.util.dice.roll_expression", return_value=(13, [])):
            cm._check_victory()
    assert cm.combatants[hero_id].creature.current_hit_points == 30


def test_death_burst_half_on_save():
    cm, hero_id, mephit_id = _burst_scene(half_on_save=True)
    cm.combatants[mephit_id].creature.current_hit_points = 0
    with patch("arena.combat.actions.roll_die", return_value=20):     # save succeeds
        with patch("arena.util.dice.roll_expression", return_value=(12, [])):
            cm._check_victory()
    assert cm.combatants[hero_id].creature.current_hit_points == 30 - 6  # half of 12


def test_death_burst_spares_creatures_outside_radius():
    cm, hero_id, mephit_id = _burst_scene(target_far=True)
    cm.combatants[mephit_id].creature.current_hit_points = 0
    with patch("arena.combat.actions.roll_die", return_value=1):
        with patch("arena.util.dice.roll_expression", return_value=(13, [])):
            cm._check_victory()
    assert cm.combatants[hero_id].creature.current_hit_points == 30


def test_death_burst_fires_only_once():
    cm, hero_id, mephit_id = _burst_scene()
    cm.combatants[mephit_id].creature.current_hit_points = 0
    with patch("arena.combat.actions.roll_die", return_value=1):
        with patch("arena.util.dice.roll_expression", return_value=(5, [])):
            cm._check_victory()
            cm._check_victory()  # second check must not re-burst
    assert cm.combatants[hero_id].creature.current_hit_points == 30 - 5


def test_condition_death_burst_blinds_on_failed_save():
    """Dust mephit's burst applies a condition (blinded) rather than damage."""
    from arena.combat.conditions import has_condition
    from arena.models.conditions import Condition

    mephit = Monster(
        name="Dust Mephit", max_hit_points=17, current_hit_points=17,
        ability_scores=AbilityScores(),
        death_burst=DeathBurst(radius_ft=5, save_ability="constitution", save_dc=10,
                               condition_on_fail="blinded"))
    target = Creature(name="Hero", max_hit_points=30, current_hit_points=30,
                      ability_scores=AbilityScores(), is_player_controlled=True)
    enc = Encounter(name="dust", grid_width=12, grid_height=12, combatants=[
        CombatantEntry(creature_id="hero", creature_data=target, team="player",
                       starting_position=(5, 6)),
        CombatantEntry(creature_id="mephit", creature_data=mephit, team="enemy",
                       starting_position=(5, 5)),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10]):
        cm.roll_initiative()
    cm.begin_combat()
    hero_id = next(k for k, v in cm.combatants.items() if v.team == "player")
    mephit_id = next(k for k, v in cm.combatants.items() if v.team == "enemy")
    cm.combatants[mephit_id].creature.current_hit_points = 0
    with patch("arena.combat.actions.roll_die", return_value=1):  # save fails
        cm._check_victory()
    assert has_condition(cm.combatants[hero_id].creature, Condition.BLINDED)
    assert cm.combatants[hero_id].creature.current_hit_points == 30  # no damage
