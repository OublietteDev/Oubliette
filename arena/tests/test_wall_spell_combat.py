"""D-WALL-1 — wall spells as real barriers, end-to-end through the manager.

These exercise the live behaviour the GUI/labs drive: casting an ``is_wall``
spell as a line (``execute_wall_line``), the resulting barrier blocking
movement/LOS, and damaging walls (Wall of Fire) burning a creature on entry,
on start-of-turn, and on appearing atop it. The model-layer (panels, blocking
flags, concentration cleanup) is covered by test_wall_spell_wiring; this is the
manager wiring.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager
from arena.combat.events import CombatEventType
from arena.grid.coordinates import HexCoord
from arena.grid.pathfinding import find_path
from arena.models.actions import Action
from arena.models.character import Creature
from arena.models.encounter import Encounter, CombatantEntry
from arena.paths import DATA_DIR


def _spell(spell_id: str) -> Action:
    p = DATA_DIR / "spells" / "srd" / f"{spell_id}.json"
    # Drop the slot cost so the caster can fire it without a spell-slot pool.
    return Action.model_validate(json.loads(p.read_text())).model_copy(
        update={"resource_cost": {}}
    )


def _combat(caster_spells, caster_pos=(3, 5), foe_pos=(10, 5), foe_hp=200):
    caster = Creature(
        name="Warden", max_hit_points=60, is_player_controlled=True,
        actions=[_spell(s) for s in caster_spells],
    )
    foe = Creature(name="Brute", max_hit_points=foe_hp, is_player_controlled=False)
    enc = Encounter(
        name="WallTest", grid_width=22, grid_height=12,
        combatants=[
            CombatantEntry(creature_id="w", creature_data=caster,
                           team="player", starting_position=caster_pos),
            CombatantEntry(creature_id="b", creature_data=foe,
                           team="enemy", starting_position=foe_pos),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20] + [1] * 80):
        cm.roll_initiative()
    cm.begin_combat()
    wid = next(i for i, c in cm.combatants.items() if c.team == "player")
    bid = next(i for i, c in cm.combatants.items() if c.team == "enemy")
    for _ in range(20):
        if cm.active_combatant.creature_id == wid:
            break
        cm.end_turn()
    return cm, wid, bid


def _cast_wall(cm, wid, spell_name, start, end):
    action = next(a for a in cm.combatants[wid].creature.actions
                  if a.name == spell_name)
    cm.select_action(action)
    return cm.execute_wall_line(start, end)


# ── Routing ────────────────────────────────────────────────────────────

def test_wall_is_never_a_zone_spell():
    """A wall spell (concentration + area + ... ) is excluded from the zone
    path so it routes as a barrier, not a lingering cloud."""
    cm, wid, _ = _combat(["wall_of_fire"])
    wof = next(a for a in cm.combatants[wid].creature.actions
               if a.name == "Wall of Fire")
    assert wof.is_wall
    assert cm._is_zone_creating_spell(wof) is False


def test_execute_wall_line_creates_active_wall():
    cm, wid, _ = _combat(["wall_of_force"])
    assert cm.active_walls == []
    _cast_wall(cm, wid, "Wall of Force", HexCoord(6, 2), HexCoord(6, 8))
    assert len(cm.active_walls) == 1
    wall = cm.active_walls[0]
    assert wall.name == "Wall of Force"
    # The hex line from (6,2)→(6,8) is the wall's span.
    assert {(h.q, h.r) for h in wall.get_wall_hexes()} == {(6, r) for r in range(2, 9)}


def test_execute_wall_line_caps_at_length():
    """A wall is capped at the spell's wall_length (hex COUNT = length/5), even
    when the two clicks are farther apart. Wall of Force = 100 ft = 20 hexes,
    NOT 21 (the off-by-one fencepost OublietteDev caught as '105 ft')."""
    cm, wid, _ = _combat(["wall_of_force"])
    # Clicks 21 hexes apart on a 22-wide grid; cap must clip to 20 hexes.
    _cast_wall(cm, wid, "Wall of Force", HexCoord(0, 5), HexCoord(21, 5))
    wall = cm.active_walls[0]
    assert len(wall.get_wall_hexes()) == 20  # 20 * 5 ft = 100 ft, RAW


def test_wall_line_hexes_caps_count_not_gaps():
    """The shared geometry helper caps the hex COUNT at length/5."""
    cm, wid, _ = _combat(["wall_of_force"])
    action = next(a for a in cm.combatants[wid].creature.actions
                  if a.name == "Wall of Force")
    # Far apart → exactly 20 hexes (100 ft).
    hexes = cm.wall_line_hexes(HexCoord(0, 5), HexCoord(21, 5), action)
    assert len(hexes) == 20
    # A short drag stays short (you can make a smaller wall).
    short = cm.wall_line_hexes(HexCoord(5, 5), HexCoord(8, 5), action)
    assert len(short) == 4


# ── Blocking ───────────────────────────────────────────────────────────

def test_wall_of_force_blocks_movement():
    cm, wid, bid = _combat(["wall_of_force"])
    _cast_wall(cm, wid, "Wall of Force", HexCoord(6, 2), HexCoord(6, 8))
    blocked = cm._get_wall_blocked_hexes()
    assert (6, 5) in blocked
    # A path from the foe to the caster cannot cross the wall hexes.
    path = find_path(HexCoord(10, 5), HexCoord(4, 5), cm.grid, blocked_hexes=blocked)
    assert path is not None  # tall grid → detour exists
    assert all((h.q, h.r) not in blocked for h in path)


def test_wall_of_fire_does_not_block_movement():
    """Wall of Fire is opaque but passable — you can walk through (and burn)."""
    cm, wid, _ = _combat(["wall_of_fire"])
    _cast_wall(cm, wid, "Wall of Fire", HexCoord(6, 2), HexCoord(6, 8))
    assert cm._get_wall_blocked_hexes() == set()
    # ...but it does block line of sight (opaque).
    assert cm._get_wall_los_blocked_hexes()


# ── Entry damage ───────────────────────────────────────────────────────

def test_wall_of_fire_burns_on_step_in():
    cm, wid, bid = _combat(["wall_of_fire"])
    _cast_wall(cm, wid, "Wall of Fire", HexCoord(6, 3), HexCoord(6, 7))
    foe = cm.combatants[bid]
    foe.position = HexCoord(7, 5)
    hp0 = foe.creature.current_hit_points
    cm._commit_move(foe, HexCoord(6, 5), HexCoord(7, 5))
    assert foe.creature.current_hit_points < hp0


def test_wall_of_fire_burns_on_start_of_turn():
    cm, wid, bid = _combat(["wall_of_fire"])
    _cast_wall(cm, wid, "Wall of Fire", HexCoord(6, 3), HexCoord(6, 7))
    foe = cm.combatants[bid]
    # Stand the foe inside the wall, then bring its turn around.
    foe.position = HexCoord(6, 5)
    hp0 = foe.creature.current_hit_points
    for _ in range(20):
        if cm.active_combatant.creature_id == bid:
            break
        cm.end_turn()
    assert foe.creature.current_hit_points < hp0


def test_wall_appears_on_creature_burns_it():
    """Casting Wall of Fire onto an occupied hex burns the occupant at once."""
    cm, wid, bid = _combat(["wall_of_fire"], foe_pos=(6, 5))
    foe = cm.combatants[bid]
    hp0 = foe.creature.current_hit_points
    _cast_wall(cm, wid, "Wall of Fire", HexCoord(6, 3), HexCoord(6, 7))
    assert foe.creature.current_hit_points < hp0


def test_caster_is_spared_by_own_wall():
    """The wall's caster doesn't burn standing in their own Wall of Fire."""
    cm, wid, _ = _combat(["wall_of_fire"])
    caster = cm.combatants[wid]
    caster.position = HexCoord(6, 5)
    hp0 = caster.creature.current_hit_points
    _cast_wall(cm, wid, "Wall of Fire", HexCoord(6, 3), HexCoord(6, 7))
    assert caster.creature.current_hit_points == hp0


def test_pure_barrier_deals_no_entry_damage():
    """Wall of Force has no damage_on_enter — walking into it is harmless
    (it is impassable, but if forced onto it, no burn)."""
    cm, wid, bid = _combat(["wall_of_force"])
    _cast_wall(cm, wid, "Wall of Force", HexCoord(6, 3), HexCoord(6, 7))
    foe = cm.combatants[bid]
    foe.position = HexCoord(6, 5)
    hp0 = foe.creature.current_hit_points
    cm.combatants[bid]  # start-of-turn would be the damaging hook
    for _ in range(20):
        if cm.active_combatant.creature_id == bid:
            break
        cm.end_turn()
    assert foe.creature.current_hit_points == hp0


# ── Render style mapping (so a rename can't silently lose a wall's color) ──

def test_each_wall_has_a_distinct_render_style():
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from arena.gui.screens.combat import CombatScreen
    from arena.combat.wall_spells import create_wall

    spell_ids = ["wall_of_force", "wall_of_stone", "wall_of_fire",
                 "wall_of_ice", "wall_of_thorns", "blade_barrier"]
    colors = []
    for sid in spell_ids:
        wall = create_wall(_spell(sid), "c", [HexCoord(0, 0)])
        color, alpha = CombatScreen._wall_render_style(wall)
        assert len(color) == 3 and 0 < alpha <= 200
        colors.append(color)
    # Every named wall maps to its own color (no two walls look identical).
    assert len(set(colors)) == len(spell_ids)


# ── Concentration cleanup (routing-level) ──────────────────────────────

def test_wall_drops_when_concentration_ends():
    cm, wid, _ = _combat(["wall_of_force"])
    _cast_wall(cm, wid, "Wall of Force", HexCoord(6, 2), HexCoord(6, 8))
    assert len(cm.active_walls) == 1
    from arena.combat.concentration import end_concentration
    caster = cm.combatants[wid]
    end_concentration(caster.creature, wid, combatants=cm.combatants)
    cm._cleanup_orphaned_zones()
    assert cm.active_walls == []
