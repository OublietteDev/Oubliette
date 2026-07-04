"""Authored hazard terrain deals its damage on entry (location-battles rider).

A battle map's hazard hexes carry ``extra_data: {"damage": "1d6 fire"}``. The
engine reads the spec at load and burns any creature that ENTERS the hex —
walking, walking THROUGH (per step, the Spike-Growth convention), or being
shoved in. Mundane damage: immunities apply. An unrollable authored spec is
ignored, never fatal.
"""

from __future__ import annotations

from unittest.mock import patch

from arena.grid.coordinates import HexCoord
from arena.models.encounter import TerrainHex, TerrainType

from arena.tests.test_forced_movement import (
    _make_enemy, _make_fighter, _setup_combat,
)


def _hazard(pos, damage="1d6 fire"):
    extra = {"damage": damage} if damage else {}
    return TerrainHex(position=pos, terrain_type=TerrainType.HAZARD,
                      extra_data=extra)


def _active_setup(**kw):
    """A combat where the PLAYER acts first (dex 18 beats the goblin's 14)."""
    kw.setdefault("player", _make_fighter(dexterity=18))
    kw.setdefault("enemy_pos", (8, 8))     # far away: no OAs in movement tests
    return _setup_combat(**kw)


def test_load_encounter_maps_hazard_specs():
    mgr, _, _ = _setup_combat(terrain=[
        _hazard((4, 4), "2d6 fire"),
        _hazard((5, 5), damage=None),          # authored without damage: cosmetic
        TerrainHex(position=(6, 6), terrain_type=TerrainType.WALL),
    ])
    assert mgr.terrain_hazards == {(4, 4): "2d6 fire"}


def test_walking_into_a_hazard_burns():
    mgr, pid, _ = _active_setup()
    mover = mgr.combatants[pid]
    step = mover.position.neighbors()[0]
    mgr.grid.set_terrain(step, TerrainType.HAZARD)
    mgr.terrain_hazards[(step.q, step.r)] = "1d6 fire"

    hp_before = mover.creature.current_hit_points
    with patch("arena.util.dice.roll_expression", return_value=(4, [4])):
        assert mgr.try_move(step) is True
    assert mover.creature.current_hit_points == hp_before - 4
    assert any("hazardous terrain" in (e.message or "")
               for e in mgr.log.events)


def test_walking_through_fire_burns_per_step():
    mgr, pid, _ = _active_setup()
    mover = mgr.combatants[pid]
    first = mover.position.neighbors()[0]
    second = first.neighbors()[0]
    for h in (first, second):
        mgr.grid.set_terrain(h, TerrainType.HAZARD)
        mgr.terrain_hazards[(h.q, h.r)] = "1d6 fire"

    hp_before = mover.creature.current_hit_points
    with patch("arena.util.dice.roll_expression", return_value=(3, [3])):
        assert mgr.try_move(first) is True
        assert mgr.try_move(second) is True
    assert mover.creature.current_hit_points == hp_before - 6


def test_fire_immunity_shrugs_the_hearth_off():
    fighter = _make_fighter(dexterity=18)
    fighter.damage_immunities = ["fire"]
    mgr, pid, _ = _active_setup(player=fighter)
    mover = mgr.combatants[pid]
    step = mover.position.neighbors()[0]
    mgr.grid.set_terrain(step, TerrainType.HAZARD)
    mgr.terrain_hazards[(step.q, step.r)] = "1d6 fire"

    hp_before = mover.creature.current_hit_points
    with patch("arena.util.dice.roll_expression", return_value=(6, [6])):
        mgr.try_move(step)
    assert mover.creature.current_hit_points == hp_before


def test_shoved_into_the_hearth_burns():
    """The whole point: Shove-push a goblin into the fire and it takes the
    hex's damage on landing."""
    from arena.combat.forced_movement import calculate_push_path

    mgr, pid, eid = _setup_combat(
        player=_make_fighter(strength=20, dexterity=18),
        enemy=_make_enemy(strength=1),
        player_pos=(2, 2), enemy_pos=(3, 2),
    )
    goblin = mgr.combatants[eid]
    # The hearth sits exactly where a 5-ft push away from the fighter lands.
    dest, _, _ = calculate_push_path(
        HexCoord(2, 2), HexCoord(3, 2), 5, mgr.grid, eid, goblin.creature.size,
    )
    mgr.grid.set_terrain(dest, TerrainType.HAZARD)
    mgr.terrain_hazards[(dest.q, dest.r)] = "1d6 fire"
    hp_before = goblin.creature.current_hit_points

    with patch("arena.combat.forced_movement.roll_die", return_value=10), \
         patch("arena.util.dice.roll_expression", return_value=(5, [5])):
        mgr.execute_shove(eid, shove_choice="push")

    assert (goblin.position.q, goblin.position.r) == (dest.q, dest.r)
    assert goblin.creature.current_hit_points == hp_before - 5
    assert any("hazardous terrain" in (e.message or "")
               for e in mgr.log.events)


def test_unrollable_spec_is_ignored_not_fatal():
    mgr, pid, _ = _active_setup()
    mover = mgr.combatants[pid]
    step = mover.position.neighbors()[0]
    mgr.grid.set_terrain(step, TerrainType.HAZARD)
    mgr.terrain_hazards[(step.q, step.r)] = "searing agony"   # not a dice spec

    hp_before = mover.creature.current_hit_points
    assert mgr.try_move(step) is True
    assert mover.creature.current_hit_points == hp_before
