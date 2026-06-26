"""D-AOE-1 — AoE shape geometry (sphere / cube / line / cone)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from arena.grid.aoe_shapes import (
    aoe_hexes, hexes_in_sphere, hexes_in_cube, hexes_in_line, hexes_in_cone,
    is_emanating,
)
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.combat.manager import CombatManager
from arena.combat.events import CombatEventType
from arena.models.actions import Action, TargetType
from arena.models.character import Creature
from arena.models.encounter import CombatantEntry, Encounter


def _grid(w=24, h=24) -> HexGrid:
    return HexGrid(w, h)


# ── Sphere ────────────────────────────────────────────────────────────


class TestSphere:
    def test_radius_includes_center_and_within(self):
        g = _grid()
        hexes = hexes_in_sphere(HexCoord(10, 10), 10, g)  # radius 2 hexes
        assert HexCoord(10, 10) in hexes
        assert HexCoord(12, 10) in hexes      # 2 hexes away
        assert HexCoord(13, 10) not in hexes  # 3 hexes away (15 ft)


# ── Cube ──────────────────────────────────────────────────────────────


class TestCube:
    def test_15ft_cube_is_3x3(self):
        g = _grid()
        hexes = hexes_in_cube(HexCoord(10, 10), 15, g)  # side 3 -> half 1.5
        # Square of q,r within 1 of center -> 9 hexes.
        assert HexCoord(10, 10) in hexes
        assert HexCoord(9, 9) in hexes
        assert HexCoord(11, 11) in hexes
        assert HexCoord(12, 10) not in hexes  # 2 out — beyond the cube
        assert len(hexes) == 9


# ── Line ──────────────────────────────────────────────────────────────


class TestLine:
    def test_line_runs_full_length_in_aim_direction(self):
        g = _grid()
        origin = HexCoord(2, 10)
        # Aim east (increasing q); a 100-ft line = 20 hexes.
        hexes = hexes_in_line(origin, HexCoord(5, 10), 100, g)
        assert origin not in hexes                 # caster's own hex excluded
        assert HexCoord(3, 10) in hexes            # first step
        # Reaches far along the aim direction (clipped to the grid edge).
        assert any(h.q >= 20 for h in hexes)

    def test_line_is_narrow(self):
        g = _grid()
        origin = HexCoord(2, 10)
        hexes = hexes_in_line(origin, HexCoord(10, 10), 50, g)
        # A 5-ft line is one hex wide: at most ~length hexes, not a blob.
        assert len(hexes) <= 12

    def test_zero_direction_is_empty(self):
        g = _grid()
        assert hexes_in_line(HexCoord(5, 5), HexCoord(5, 5), 50, g) == set()


# ── Cone ──────────────────────────────────────────────────────────────


class TestCone:
    def test_cone_points_toward_aim_not_backward(self):
        g = _grid()
        origin = HexCoord(10, 10)
        hexes = hexes_in_cone(origin, HexCoord(16, 10), 30, g)  # aim east, 6 hexes
        assert hexes                                   # non-empty
        assert all(h.q >= origin.q for h in hexes)     # nothing behind the caster
        assert HexCoord(6, 10) not in hexes            # the opposite direction
        assert max(origin.distance_to(h) for h in hexes) <= 6  # within length

    def test_cone_widens_with_distance(self):
        g = _grid()
        origin = HexCoord(10, 10)
        hexes = hexes_in_cone(origin, HexCoord(16, 10), 30, g)
        near = {h for h in hexes if origin.distance_to(h) == 1}
        far = {h for h in hexes if origin.distance_to(h) == 5}
        assert len(far) >= len(near)  # wider at the far end


# ── Dispatcher ────────────────────────────────────────────────────────


class TestDispatcher:
    def _action(self, tt: TargetType, size: int) -> Action:
        return Action(name="X", description="x", target_type=tt, area_size=size)

    def test_dispatch_line_emanates_from_origin(self):
        g = _grid()
        a = self._action(TargetType.AREA_LINE, 50)
        hexes = aoe_hexes(a, HexCoord(2, 10), HexCoord(8, 10), g)
        assert HexCoord(2, 10) not in hexes
        assert HexCoord(3, 10) in hexes

    def test_dispatch_sphere_centers_on_aim(self):
        g = _grid()
        a = self._action(TargetType.AREA_SPHERE, 10)
        hexes = aoe_hexes(a, HexCoord(2, 10), HexCoord(15, 10), g)
        assert HexCoord(15, 10) in hexes      # centered on the aim, not the caster
        assert HexCoord(2, 10) not in hexes


# ── Emanating vs placed (the range-0 aiming contract) ─────────────────


class TestEmanating:
    def test_line_and_cone_emanate(self):
        assert is_emanating(Action(name="LB", description="x", target_type=TargetType.AREA_LINE))
        assert is_emanating(Action(name="CC", description="x", target_type=TargetType.AREA_CONE))

    def test_sphere_and_cube_are_placed(self):
        assert not is_emanating(Action(name="FB", description="x", target_type=TargetType.AREA_SPHERE))
        assert not is_emanating(Action(name="TW", description="x", target_type=TargetType.AREA_CUBE))

    def test_self_centered_emanating_collapses_to_nothing(self):
        """Why the GUI must AIM line/cone instead of casting them caster-centered:
        with aim == origin a line/cone covers no hexes (the old range-0 bug)."""
        g = _grid()
        line = Action(name="LB", description="x", target_type=TargetType.AREA_LINE, area_size=100)
        assert aoe_hexes(line, HexCoord(5, 5), HexCoord(5, 5), g) == set()


# ── End-to-end: Lightning Bolt is a line, not a sphere ────────────────


def _load_spell(spell_id: str) -> Action:
    from arena.paths import DATA_DIR
    p = DATA_DIR / "spells" / "srd" / f"{spell_id}.json"
    return Action.model_validate(json.loads(p.read_text())).model_copy(
        update={"resource_cost": {}}
    )


class TestLightningBoltInCombat:
    def test_bolt_hits_the_line_spares_the_flank(self):
        wizard = Creature(name="Wizard", max_hit_points=60)
        wizard.actions = [_load_spell("lightning_bolt")]
        # On-line target straight east of the caster; off-line target the same
        # distance away but one row down — a sphere would catch both.
        entries = [
            CombatantEntry(creature_id="wiz", creature_data=wizard,
                           team="player", starting_position=(2, 10)),
            CombatantEntry(creature_id="online", creature_data=Creature(name="OnLine", max_hit_points=80),
                           team="enemy", starting_position=(8, 10)),
            CombatantEntry(creature_id="flank", creature_data=Creature(name="Flank", max_hit_points=80),
                           team="enemy", starting_position=(8, 13)),
        ]
        enc = Encounter(name="Bolt", grid_width=24, grid_height=20, combatants=entries)
        cm = CombatManager()
        cm.load_encounter(enc, Path("."))
        with patch("arena.combat.manager.roll_die", side_effect=[20, 1, 1]):
            cm.roll_initiative()
        cm.begin_combat()
        wiz = next(i for i, c in cm.combatants.items() if c.team == "player")
        while cm.active_combatant.creature_id != wiz:
            cm.end_turn()
        online = next(i for i, c in cm.combatants.items() if "OnLine" in c.creature.name)
        flank = next(i for i, c in cm.combatants.items() if "Flank" in c.creature.name)

        cm.select_action(cm.combatants[wiz].creature.actions[0])
        with patch("arena.combat.actions.roll_die", return_value=1):  # targets fail
            res = cm.execute_effect_at_hex(HexCoord(14, 10))  # aim east, along row 10
        damaged = {e.target_id for e in res.events if e.event_type == CombatEventType.DAMAGE}
        assert online in damaged       # caught by the bolt's line
        assert flank not in damaged    # three rows off the line — a sphere would have hit it


# ── Forced movement into Spike Growth (D-AOE-1 consumer) ──────────────


class TestForcedSpikeGrowth:
    def test_shoved_through_spikes_takes_damage_per_hex(self):
        """Pushing a creature THROUGH Spike Growth deals 2d4 per 5 ft of the
        shoved path (forced movement teleports, so the path is reconstructed)."""
        from arena.combat.zones import (
            ActiveZone, process_zone_movement_path, get_zone_hexes,
        )
        from arena.grid.line_of_sight import hex_line
        from arena.combat.manager import Combatant

        g = _grid(24, 16)
        victim = Creature(name="Shoved", max_hit_points=80)
        victim.current_hit_points = 80
        comb = Combatant(creature_id="v", creature=victim, team="enemy")
        comb.position = HexCoord(15, 8)  # already shoved to the far side
        g.place_creature(HexCoord(15, 8), "v", victim.size)
        combatants = {"v": comb}

        zone = ActiveZone(
            zone_id="spike", caster_id="druid", name="Spike Growth",
            radius_feet=20, follows_caster=False, center=HexCoord(10, 8),
            movement_hazard_dice="2d4", affects_enemies_only=False,
        )
        from_hex, to_hex = HexCoord(5, 8), HexCoord(15, 8)
        zone_hexes = {(h.q, h.r) for h in get_zone_hexes(zone, combatants, g)}
        expected = sum(
            1 for h in hex_line(from_hex, to_hex)[1:] if (h.q, h.r) in zone_hexes
        )
        assert expected >= 3  # genuinely shoved across the patch

        with patch("arena.util.dice.roll_expression", return_value=(2, [2])):
            process_zone_movement_path([zone], "v", from_hex, to_hex, combatants, g)
        assert victim.current_hit_points == 80 - 2 * expected
