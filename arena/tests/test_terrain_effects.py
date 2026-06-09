"""Tests for the terrain modification system (terrain-altering spells)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from arena.combat.events import CombatEventType
from arena.combat.manager import CombatManager, Combatant
from arena.combat.terrain_effects import (
    TerrainModification,
    apply_terrain_modification,
    cleanup_terrain_modifications,
    get_terrain_mod_hexes,
    revert_terrain_modification,
)
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action,
    ActionType,
    DamageRoll,
    DamageType,
    SavingThrowEffect,
    TargetType,
)
from arena.models.character import CreatureSize, PlayerCharacter
from arena.models.conditions import Condition
from arena.combat.conditions import apply_condition, has_condition
from arena.models.encounter import CombatantEntry, Encounter, TerrainType


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_caster(
    name="Wizard",
    hp=30,
    actions=None,
) -> PlayerCharacter:
    return PlayerCharacter(
        name=name,
        max_hit_points=hp,
        armor_class=12,
        ability_scores=AbilityScores(
            strength=8, dexterity=14, constitution=12,
            intelligence=18, wisdom=14, charisma=10,
        ),
        proficiency_bonus=3,
        is_player_controlled=True,
        character_class="Wizard",
        level=5,
        actions=actions or [],
    )


def _make_enemy(
    name="Goblin",
    hp=20,
) -> PlayerCharacter:
    return PlayerCharacter(
        name=name,
        max_hit_points=hp,
        armor_class=13,
        ability_scores=AbilityScores(strength=10, dexterity=14),
        proficiency_bonus=2,
        is_player_controlled=False,
        character_class="Fighter",
        level=1,
    )


def _make_combatant(name, team, position, creature=None):
    """Create a minimal Combatant for pure-function tests."""
    c = creature or (_make_caster(name=name) if team == "player" else _make_enemy(name=name))
    return Combatant(
        creature_id=name.lower(),
        creature=c,
        team=team,
        position=HexCoord(*position) if position else None,
    )


def _setup_combat(
    grid_w=10, grid_h=10,
    player=None, enemy=None,
    player_pos=(2, 2), enemy_pos=(7, 7),
    terrain=None,
    player_actions=None,
) -> tuple[CombatManager, str, str]:
    """Set up a CombatManager with a player and enemy on a grid.

    Returns (manager, player_id, enemy_id).
    """
    from pathlib import Path

    p = player or _make_caster(actions=player_actions or [])
    e = enemy or _make_enemy()

    combatants = [
        CombatantEntry(
            creature_id="player_1",
            creature_data=p,
            team="player",
            starting_position=player_pos,
        ),
        CombatantEntry(
            creature_id="enemy_1",
            creature_data=e,
            team="enemy",
            starting_position=enemy_pos,
        ),
    ]

    encounter = Encounter(
        name="Test",
        combatants=combatants,
        grid_width=grid_w,
        grid_height=grid_h,
    )

    if terrain:
        encounter.terrain = terrain

    manager = CombatManager()
    manager.load_encounter(encounter, Path("."))

    # Roll initiative -- player first
    with patch("arena.combat.manager.roll_die", return_value=10):
        manager.roll_initiative()
    manager.begin_combat()

    # Find actual IDs
    player_id = None
    enemy_id = None
    for cid, c in manager.combatants.items():
        if c.team == "player":
            player_id = cid
        elif c.team == "enemy":
            enemy_id = cid

    assert player_id is not None
    assert enemy_id is not None

    return manager, player_id, enemy_id


# ==================================================================
# 1. get_terrain_mod_hexes
# ==================================================================

class TestGetTerrainModHexes:
    """Test hex calculation for terrain modification areas."""

    def test_single_hex_radius_zero(self):
        """radius_feet=0 returns only the center hex."""
        grid = HexGrid(10, 10)
        hexes = get_terrain_mod_hexes(HexCoord(5, 5), 0, grid)
        assert hexes == [HexCoord(5, 5)]

    def test_radius_five_feet(self):
        """radius_feet=5 returns center + neighbors (up to 7 hexes)."""
        grid = HexGrid(10, 10)
        hexes = get_terrain_mod_hexes(HexCoord(5, 5), 5, grid)
        # Center (dist 0) + 6 neighbors (dist 1)
        assert len(hexes) == 7
        assert HexCoord(5, 5) in hexes

    def test_radius_ten_feet(self):
        """radius_feet=10 returns 2-hex radius area."""
        grid = HexGrid(15, 15)
        hexes = get_terrain_mod_hexes(HexCoord(7, 7), 10, grid)
        # All hexes should be within distance 2 of center
        for h in hexes:
            assert HexCoord(7, 7).distance_to(h) <= 2

    def test_edge_of_grid(self):
        """Hexes outside grid bounds are excluded."""
        grid = HexGrid(5, 5)
        hexes = get_terrain_mod_hexes(HexCoord(0, 0), 10, grid)
        for h in hexes:
            assert 0 <= h.q < 5
            assert 0 <= h.r < 5

    def test_center_off_grid_returns_valid_hexes(self):
        """If center is at grid boundary, only valid hexes returned."""
        grid = HexGrid(5, 5)
        hexes = get_terrain_mod_hexes(HexCoord(4, 4), 5, grid)
        for h in hexes:
            cell = grid.get_cell(h)
            assert cell is not None


# ==================================================================
# 2. apply_terrain_modification
# ==================================================================

class TestApplyTerrainModification:
    """Test applying terrain changes to the grid."""

    def test_apply_difficult_terrain(self):
        """Applying difficult terrain changes hex terrain types."""
        grid = HexGrid(10, 10)
        combatants: dict[str, Combatant] = {}

        mod, events = apply_terrain_modification(
            grid=grid,
            center=HexCoord(5, 5),
            radius_feet=0,
            terrain_type=TerrainType.DIFFICULT,
            caster_id="wizard",
            spell_name="Entangle",
            concentration_linked=True,
            combatants=combatants,
        )

        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.DIFFICULT
        assert (5, 5) in mod.original_terrain
        assert mod.original_terrain[(5, 5)] == TerrainType.NORMAL
        assert mod.applied_type == TerrainType.DIFFICULT
        assert len(events) == 1
        assert events[0].event_type == CombatEventType.TERRAIN_MODIFICATION

    def test_apply_wall_terrain(self):
        """Applying wall terrain makes hexes impassable."""
        grid = HexGrid(10, 10)
        combatants: dict[str, Combatant] = {}

        mod, events = apply_terrain_modification(
            grid=grid,
            center=HexCoord(5, 5),
            radius_feet=5,
            terrain_type=TerrainType.WALL,
            caster_id="wizard",
            spell_name="Wall of Stone",
            concentration_linked=True,
            combatants=combatants,
        )

        # All 7 hexes should now be walls
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.WALL
        assert not grid.is_passable(HexCoord(5, 5))
        assert len(mod.original_terrain) == 7

    def test_apply_wall_skips_occupied_hexes(self):
        """Wall terrain is not placed on hexes occupied by living creatures."""
        grid = HexGrid(10, 10)
        combatants = {
            "fighter": _make_combatant("Fighter", "player", (5, 5)),
        }

        mod, events = apply_terrain_modification(
            grid=grid,
            center=HexCoord(5, 5),
            radius_feet=5,
            terrain_type=TerrainType.WALL,
            caster_id="wizard",
            spell_name="Wall of Stone",
            concentration_linked=True,
            combatants=combatants,
        )

        # The occupied hex should still be NORMAL
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.NORMAL
        assert (5, 5) not in mod.original_terrain
        # But neighboring hexes should be walls
        assert len(mod.original_terrain) == 6

    def test_apply_difficult_does_not_skip_occupied(self):
        """Difficult terrain CAN be placed on occupied hexes."""
        grid = HexGrid(10, 10)
        combatants = {
            "fighter": _make_combatant("Fighter", "player", (5, 5)),
        }

        mod, events = apply_terrain_modification(
            grid=grid,
            center=HexCoord(5, 5),
            radius_feet=0,
            terrain_type=TerrainType.DIFFICULT,
            caster_id="wizard",
            spell_name="Spike Growth",
            concentration_linked=True,
            combatants=combatants,
        )

        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.DIFFICULT
        assert (5, 5) in mod.original_terrain

    def test_apply_no_op_when_already_same_terrain(self):
        """No change recorded if hex already has the target terrain type."""
        grid = HexGrid(10, 10)
        grid.set_terrain(HexCoord(5, 5), TerrainType.DIFFICULT)
        combatants: dict[str, Combatant] = {}

        mod, events = apply_terrain_modification(
            grid=grid,
            center=HexCoord(5, 5),
            radius_feet=0,
            terrain_type=TerrainType.DIFFICULT,
            caster_id="wizard",
            spell_name="Entangle",
            concentration_linked=True,
            combatants=combatants,
        )

        # No change, no events
        assert len(mod.original_terrain) == 0
        assert len(events) == 0

    def test_apply_records_original_terrain(self):
        """Original terrain is preserved correctly for mixed terrains."""
        grid = HexGrid(10, 10)
        grid.set_terrain(HexCoord(5, 4), TerrainType.WATER)
        combatants: dict[str, Combatant] = {}

        mod, events = apply_terrain_modification(
            grid=grid,
            center=HexCoord(5, 5),
            radius_feet=5,
            terrain_type=TerrainType.DIFFICULT,
            caster_id="wizard",
            spell_name="Plant Growth",
            concentration_linked=False,
            combatants=combatants,
        )

        # Water hex should record WATER as original
        assert mod.original_terrain[(5, 4)] == TerrainType.WATER
        # Normal hexes should record NORMAL
        assert mod.original_terrain[(5, 5)] == TerrainType.NORMAL

    def test_apply_area_radius(self):
        """Terrain modification applies to all hexes within radius."""
        grid = HexGrid(15, 15)
        combatants: dict[str, Combatant] = {}

        mod, events = apply_terrain_modification(
            grid=grid,
            center=HexCoord(7, 7),
            radius_feet=10,
            terrain_type=TerrainType.DIFFICULT,
            caster_id="wizard",
            spell_name="Spike Growth",
            concentration_linked=True,
            combatants=combatants,
        )

        # Verify all modified hexes are within distance 2 of center
        for (q, r) in mod.original_terrain:
            assert HexCoord(7, 7).distance_to(HexCoord(q, r)) <= 2

        # Verify they're all now difficult
        for (q, r) in mod.original_terrain:
            assert grid.get_cell(HexCoord(q, r)).terrain == TerrainType.DIFFICULT

    def test_apply_terrain_removal(self):
        """Setting terrain to NORMAL effectively removes existing terrain."""
        grid = HexGrid(10, 10)
        grid.set_terrain(HexCoord(5, 5), TerrainType.DIFFICULT)
        combatants: dict[str, Combatant] = {}

        mod, events = apply_terrain_modification(
            grid=grid,
            center=HexCoord(5, 5),
            radius_feet=0,
            terrain_type=TerrainType.NORMAL,
            caster_id="wizard",
            spell_name="Mold Earth",
            concentration_linked=False,
            combatants=combatants,
        )

        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.NORMAL
        assert mod.original_terrain[(5, 5)] == TerrainType.DIFFICULT

    def test_event_contains_terrain_details(self):
        """Event details include terrain type, center, radius, hex count."""
        grid = HexGrid(10, 10)
        combatants: dict[str, Combatant] = {}

        mod, events = apply_terrain_modification(
            grid=grid,
            center=HexCoord(5, 5),
            radius_feet=5,
            terrain_type=TerrainType.WALL,
            caster_id="wizard",
            spell_name="Wall of Stone",
            concentration_linked=True,
            combatants=combatants,
        )

        assert len(events) == 1
        d = events[0].details
        assert d["terrain_modified"] is True
        assert d["terrain_type"] == "wall"
        assert d["center_hex"] == (5, 5)
        assert d["radius_feet"] == 5
        assert d["hex_count"] == 7

    def test_apply_concentration_flag(self):
        """Modification records concentration_linked flag correctly."""
        grid = HexGrid(10, 10)
        combatants: dict[str, Combatant] = {}

        mod_conc, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(3, 3), radius_feet=0,
            terrain_type=TerrainType.WALL, caster_id="wiz",
            spell_name="WoS", concentration_linked=True, combatants=combatants,
        )
        assert mod_conc.concentration_linked is True

        mod_perm, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(4, 4), radius_feet=0,
            terrain_type=TerrainType.DIFFICULT, caster_id="druid",
            spell_name="Plant Growth", concentration_linked=False,
            combatants=combatants,
        )
        assert mod_perm.concentration_linked is False


# ==================================================================
# 3. revert_terrain_modification
# ==================================================================

class TestRevertTerrainModification:
    """Test reverting terrain changes."""

    def test_basic_revert(self):
        """Revert restores original terrain types."""
        grid = HexGrid(10, 10)
        combatants: dict[str, Combatant] = {}

        mod, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(5, 5), radius_feet=0,
            terrain_type=TerrainType.WALL, caster_id="wizard",
            spell_name="Wall of Stone", concentration_linked=True,
            combatants=combatants,
        )
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.WALL

        events = revert_terrain_modification(grid, mod)

        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.NORMAL
        assert len(events) == 1
        assert events[0].event_type == CombatEventType.TERRAIN_MODIFICATION
        assert events[0].details["terrain_reverted"] is True

    def test_revert_preserves_hex_changed_by_another_source(self):
        """If another spell overwrote a hex, revert doesn't touch it."""
        grid = HexGrid(10, 10)
        combatants: dict[str, Combatant] = {}

        # Spell A: create wall
        mod_a, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(5, 5), radius_feet=0,
            terrain_type=TerrainType.WALL, caster_id="wizard_a",
            spell_name="Wall A", concentration_linked=True,
            combatants=combatants,
        )

        # Another effect changes the hex to something else
        grid.set_terrain(HexCoord(5, 5), TerrainType.DIFFICULT)

        # Reverting mod_a should NOT touch the hex (it's no longer WALL)
        events = revert_terrain_modification(grid, mod_a)
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.DIFFICULT
        assert len(events) == 0  # Nothing was reverted

    def test_revert_multi_hex_area(self):
        """Revert works correctly for multi-hex modifications."""
        grid = HexGrid(10, 10)
        combatants: dict[str, Combatant] = {}

        mod, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(5, 5), radius_feet=5,
            terrain_type=TerrainType.DIFFICULT, caster_id="druid",
            spell_name="Spike Growth", concentration_linked=True,
            combatants=combatants,
        )
        modified_count = len(mod.original_terrain)
        assert modified_count == 7

        events = revert_terrain_modification(grid, mod)

        # All hexes should be back to normal
        for (q, r) in mod.original_terrain:
            assert grid.get_cell(HexCoord(q, r)).terrain == TerrainType.NORMAL
        assert events[0].details["hex_count"] == 7

    def test_revert_mixed_originals(self):
        """Revert restores each hex to its specific original terrain."""
        grid = HexGrid(10, 10)
        grid.set_terrain(HexCoord(5, 4), TerrainType.WATER)
        grid.set_terrain(HexCoord(5, 6), TerrainType.HAZARD)
        combatants: dict[str, Combatant] = {}

        mod, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(5, 5), radius_feet=5,
            terrain_type=TerrainType.DIFFICULT, caster_id="druid",
            spell_name="Plant Growth", concentration_linked=True,
            combatants=combatants,
        )

        revert_terrain_modification(grid, mod)

        # Each hex should restore to its specific original
        assert grid.get_cell(HexCoord(5, 4)).terrain == TerrainType.WATER
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.NORMAL
        assert grid.get_cell(HexCoord(5, 6)).terrain == TerrainType.HAZARD


# ==================================================================
# 4. cleanup_terrain_modifications
# ==================================================================

class TestCleanupTerrainModifications:
    """Test automatic cleanup when concentration breaks."""

    def test_cleanup_removes_concentration_linked_when_not_concentrating(self):
        """Mods are reverted when caster stops concentrating."""
        grid = HexGrid(10, 10)
        caster = _make_caster()
        combatants = {
            "wizard": Combatant(
                creature_id="wizard", creature=caster,
                team="player", position=HexCoord(2, 2),
            ),
        }

        mod, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(5, 5), radius_feet=0,
            terrain_type=TerrainType.WALL, caster_id="wizard",
            spell_name="Wall of Stone", concentration_linked=True,
            combatants=combatants,
        )
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.WALL

        # Caster is NOT concentrating
        remaining, events = cleanup_terrain_modifications(
            [mod], combatants, grid,
        )

        assert len(remaining) == 0
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.NORMAL
        assert len(events) == 1

    def test_cleanup_keeps_when_still_concentrating(self):
        """Mods are kept when caster is still concentrating on the SAME spell."""
        from arena.combat.concentration import start_concentrating

        grid = HexGrid(10, 10)
        caster = _make_caster()
        combatants = {
            "wizard": Combatant(
                creature_id="wizard", creature=caster,
                team="player", position=HexCoord(2, 2),
            ),
        }
        # Use start_concentrating so extra_data["spell"] is set
        start_concentrating(caster, "wizard", "Wall of Stone", combatants=combatants)

        mod, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(5, 5), radius_feet=0,
            terrain_type=TerrainType.WALL, caster_id="wizard",
            spell_name="Wall of Stone", concentration_linked=True,
            combatants=combatants,
        )

        remaining, events = cleanup_terrain_modifications(
            [mod], combatants, grid,
        )

        assert len(remaining) == 1
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.WALL
        assert len(events) == 0

    def test_cleanup_reverts_when_concentration_switched_to_different_spell(self):
        """Terrain reverts when caster switches concentration to a different spell.

        Reproduces the bug where casting Moonbeam after Spike Growth left
        the Spike Growth terrain active because the cleanup only checked
        whether the caster was concentrating (on anything), not on the
        specific spell that created the terrain.
        """
        from arena.combat.concentration import start_concentrating

        grid = HexGrid(10, 10)
        caster = _make_caster()
        combatants = {
            "wizard": Combatant(
                creature_id="wizard", creature=caster,
                team="player", position=HexCoord(2, 2),
            ),
        }

        # Cast Spike Growth: creates difficult terrain, starts concentration
        start_concentrating(caster, "wizard", "Spike Growth", combatants=combatants)
        mod, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(5, 5), radius_feet=5,
            terrain_type=TerrainType.DIFFICULT, caster_id="wizard",
            spell_name="Spike Growth", concentration_linked=True,
            combatants=combatants,
        )
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.DIFFICULT

        # Switch concentration to Moonbeam (ends Spike Growth concentration)
        start_concentrating(caster, "wizard", "Moonbeam", combatants=combatants)

        # Cleanup should detect the spell mismatch and revert Spike Growth terrain
        remaining, events = cleanup_terrain_modifications(
            [mod], combatants, grid,
        )

        assert len(remaining) == 0  # Spike Growth mod removed
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.NORMAL  # Reverted
        assert len(events) == 1  # Revert event emitted

    def test_cleanup_keeps_non_concentration_mods(self):
        """Non-concentration mods are always kept."""
        grid = HexGrid(10, 10)
        combatants: dict[str, Combatant] = {}

        mod, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(5, 5), radius_feet=0,
            terrain_type=TerrainType.DIFFICULT, caster_id="druid",
            spell_name="Plant Growth", concentration_linked=False,
            combatants=combatants,
        )

        remaining, events = cleanup_terrain_modifications(
            [mod], combatants, grid,
        )

        assert len(remaining) == 1
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.DIFFICULT

    def test_cleanup_removes_when_caster_gone(self):
        """Mods revert when caster is no longer in combatants dict."""
        grid = HexGrid(10, 10)
        combatants: dict[str, Combatant] = {}  # wizard removed

        mod = TerrainModification(
            mod_id="test_mod",
            caster_id="wizard",
            spell_name="Wall of Stone",
            applied_type=TerrainType.WALL,
            original_terrain={(5, 5): TerrainType.NORMAL},
            concentration_linked=True,
        )
        grid.set_terrain(HexCoord(5, 5), TerrainType.WALL)

        remaining, events = cleanup_terrain_modifications(
            [mod], combatants, grid,
        )

        assert len(remaining) == 0
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.NORMAL

    def test_cleanup_multiple_mods_mixed(self):
        """Cleanup correctly handles mix of concentration and permanent mods."""
        grid = HexGrid(10, 10)
        caster = _make_caster()
        # NOT concentrating
        combatants = {
            "wizard": Combatant(
                creature_id="wizard", creature=caster,
                team="player", position=HexCoord(2, 2),
            ),
        }

        mod_conc, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(5, 5), radius_feet=0,
            terrain_type=TerrainType.WALL, caster_id="wizard",
            spell_name="Wall of Stone", concentration_linked=True,
            combatants=combatants,
        )
        mod_perm, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(7, 7), radius_feet=0,
            terrain_type=TerrainType.DIFFICULT, caster_id="wizard",
            spell_name="Plant Growth", concentration_linked=False,
            combatants=combatants,
        )

        remaining, events = cleanup_terrain_modifications(
            [mod_conc, mod_perm], combatants, grid,
        )

        # Concentration mod reverted, permanent mod kept
        assert len(remaining) == 1
        assert remaining[0].spell_name == "Plant Growth"
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.NORMAL
        assert grid.get_cell(HexCoord(7, 7)).terrain == TerrainType.DIFFICULT


# ==================================================================
# 5. Stacking / edge cases
# ==================================================================

class TestStackingAndEdgeCases:
    """Test stacking behavior when multiple mods affect the same hexes."""

    def test_two_mods_on_same_hex_revert_independently(self):
        """Two mods on the same hex: reverting first doesn't break second."""
        grid = HexGrid(10, 10)
        combatants: dict[str, Combatant] = {}

        # Mod A: normal -> difficult
        mod_a, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(5, 5), radius_feet=0,
            terrain_type=TerrainType.DIFFICULT, caster_id="druid_a",
            spell_name="Entangle", concentration_linked=True,
            combatants=combatants,
        )

        # Mod B: difficult -> wall  (overwrites A)
        mod_b, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(5, 5), radius_feet=0,
            terrain_type=TerrainType.WALL, caster_id="wizard_b",
            spell_name="Wall of Stone", concentration_linked=True,
            combatants=combatants,
        )
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.WALL

        # Revert A: hex is WALL (not DIFFICULT), so A's revert is skipped
        events_a = revert_terrain_modification(grid, mod_a)
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.WALL
        assert len(events_a) == 0

        # Revert B: hex IS WALL, so B's revert restores to DIFFICULT (B's original)
        events_b = revert_terrain_modification(grid, mod_b)
        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.DIFFICULT

    def test_pit_terrain_skips_occupied(self):
        """PIT terrain also skips occupied hexes (like WALL)."""
        grid = HexGrid(10, 10)
        combatants = {
            "fighter": _make_combatant("Fighter", "player", (5, 5)),
        }

        mod, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(5, 5), radius_feet=0,
            terrain_type=TerrainType.PIT, caster_id="wizard",
            spell_name="Create Pit", concentration_linked=False,
            combatants=combatants,
        )

        assert grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.NORMAL
        assert len(mod.original_terrain) == 0

    def test_mod_id_is_unique(self):
        """Each modification gets a unique ID."""
        grid = HexGrid(10, 10)
        combatants: dict[str, Combatant] = {}

        mod1, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(3, 3), radius_feet=0,
            terrain_type=TerrainType.WALL, caster_id="wiz",
            spell_name="Wall 1", concentration_linked=False,
            combatants=combatants,
        )
        mod2, _ = apply_terrain_modification(
            grid=grid, center=HexCoord(4, 4), radius_feet=0,
            terrain_type=TerrainType.WALL, caster_id="wiz",
            spell_name="Wall 2", concentration_linked=False,
            combatants=combatants,
        )
        assert mod1.mod_id != mod2.mod_id


# ==================================================================
# 6. CombatManager integration tests
# ==================================================================

class TestCombatManagerIntegration:
    """Test terrain modification wired through CombatManager."""

    def _make_terrain_action(
        self,
        name="Wall of Stone",
        terrain_mod="wall",
        target_type=TargetType.AREA_SPHERE,
        area_size=5,
        spell_range=60,
        concentration=True,
        action_type=ActionType.ACTION,
        saving_throw=None,
    ):
        return Action(
            name=name,
            description=f"Creates {terrain_mod} terrain",
            action_type=action_type,
            target_type=target_type,
            range=spell_range,
            area_size=area_size,
            requires_concentration=concentration,
            terrain_modification=terrain_mod,
            saving_throw=saving_throw,
        )

    def test_execute_effect_at_hex_applies_terrain(self):
        """execute_effect_at_hex applies terrain modification to grid."""
        wall_action = self._make_terrain_action()
        manager, pid, eid = _setup_combat(player_actions=[wall_action])

        # Navigate to player's turn and select the action
        combatant = manager.combatants[pid]
        manager.selected_action = wall_action

        target_hex = HexCoord(5, 5)
        result = manager.execute_effect_at_hex(target_hex)

        assert result is not None
        assert result.success

        # Verify terrain was modified
        assert manager.grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.WALL

        # Verify terrain mod was tracked
        assert len(manager.active_terrain_mods) == 1
        assert manager.active_terrain_mods[0].applied_type == TerrainType.WALL

    def test_execute_effect_at_hex_no_targets_still_applies_terrain(self):
        """Terrain mod applies even when no creatures are in the AoE."""
        wall_action = self._make_terrain_action(area_size=5)
        manager, pid, eid = _setup_combat(
            player_actions=[wall_action],
            enemy_pos=(9, 9),  # Far away
        )

        manager.selected_action = wall_action
        target_hex = HexCoord(5, 5)
        result = manager.execute_effect_at_hex(target_hex)

        assert result is not None
        assert result.success
        assert manager.grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.WALL
        assert len(manager.active_terrain_mods) == 1

    def test_concentration_loss_reverts_terrain(self):
        """Breaking concentration reverts terrain modification."""
        wall_action = self._make_terrain_action()
        manager, pid, eid = _setup_combat(player_actions=[wall_action])

        manager.selected_action = wall_action
        result = manager.execute_effect_at_hex(HexCoord(5, 5))
        assert manager.grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.WALL

        # Break concentration by removing the condition
        from arena.combat.conditions import remove_condition
        combatant = manager.combatants[pid]
        remove_condition(combatant.creature, pid, Condition.CONCENTRATING)

        # Trigger cleanup
        manager._cleanup_orphaned_zones()

        # Terrain should be reverted
        assert manager.grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.NORMAL
        assert len(manager.active_terrain_mods) == 0

    def test_non_concentration_terrain_persists_through_cleanup(self):
        """Non-concentration terrain mods are not reverted by cleanup."""
        mold_earth = self._make_terrain_action(
            name="Mold Earth",
            terrain_mod="normal",
            area_size=0,
            concentration=False,
        )
        manager, pid, eid = _setup_combat(player_actions=[mold_earth])

        # First, set some difficult terrain manually
        manager.grid.set_terrain(HexCoord(5, 5), TerrainType.DIFFICULT)

        manager.selected_action = mold_earth
        result = manager.execute_effect_at_hex(HexCoord(5, 5))
        assert manager.grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.NORMAL

        # Cleanup should keep the mod (not concentration-linked)
        manager._cleanup_orphaned_zones()
        assert len(manager.active_terrain_mods) == 1
        assert manager.grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.NORMAL

    def test_zone_spell_with_terrain_modification(self):
        """Spike Growth pattern: zone AND terrain modification together."""
        spike_growth = Action(
            name="Spike Growth",
            description="Creates thorny terrain",
            action_type=ActionType.ACTION,
            target_type=TargetType.AREA_SPHERE,
            range=150,
            area_size=20,
            requires_concentration=True,
            terrain_modification="difficult",
            saving_throw=SavingThrowEffect(
                ability="dexterity",
                dc=15,
                damage_on_fail=[DamageRoll(dice="2d4", damage_type=DamageType.PIERCING)],
                damage_on_success="none",
            ),
        )
        manager, pid, eid = _setup_combat(player_actions=[spike_growth])

        manager.selected_action = spike_growth
        target_hex = HexCoord(5, 5)
        result = manager.execute_effect_at_hex(target_hex)

        assert result is not None
        assert result.success

        # Both zone AND terrain should exist
        assert len(manager.active_zones) == 1
        assert len(manager.active_terrain_mods) == 1
        assert manager.grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.DIFFICULT

    def test_zone_spell_terrain_both_revert_on_concentration_loss(self):
        """Both zone and terrain revert when concentration breaks."""
        spike_growth = Action(
            name="Spike Growth",
            description="Creates thorny terrain",
            action_type=ActionType.ACTION,
            target_type=TargetType.AREA_SPHERE,
            range=150,
            area_size=20,
            requires_concentration=True,
            terrain_modification="difficult",
            saving_throw=SavingThrowEffect(
                ability="dexterity",
                dc=15,
                damage_on_fail=[DamageRoll(dice="2d4", damage_type=DamageType.PIERCING)],
                damage_on_success="none",
            ),
        )
        manager, pid, eid = _setup_combat(player_actions=[spike_growth])

        manager.selected_action = spike_growth
        manager.execute_effect_at_hex(HexCoord(5, 5))

        assert len(manager.active_zones) == 1
        assert len(manager.active_terrain_mods) == 1

        # Break concentration
        from arena.combat.conditions import remove_condition
        combatant = manager.combatants[pid]
        remove_condition(combatant.creature, pid, Condition.CONCENTRATING)

        manager._cleanup_orphaned_zones()

        # Both should be cleaned up
        assert len(manager.active_zones) == 0
        assert len(manager.active_terrain_mods) == 0
        assert manager.grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.NORMAL

    def test_execute_effect_self_centered_terrain(self):
        """Self-centered AoE terrain mod uses caster position as center."""
        spirit_wall = self._make_terrain_action(
            name="Spirit Wall",
            terrain_mod="difficult",
            target_type=TargetType.AREA_SPHERE,
            area_size=5,
            concentration=True,
        )
        manager, pid, eid = _setup_combat(
            player_actions=[spirit_wall],
            player_pos=(5, 5),
        )

        # Ensure the player is the active combatant
        active = manager.active_combatant
        if active is None or active.creature_id != pid:
            manager.end_turn()

        manager.selected_action = spirit_wall
        # Self-centered AoE uses caster's position as center
        caster_pos = manager.combatants[pid].position
        result = manager.execute_effect_at_hex(caster_pos)

        assert result is not None
        assert result.success
        # Terrain should be centered on caster's position
        assert manager.grid.get_cell(HexCoord(5, 5)).terrain == TerrainType.DIFFICULT
        assert len(manager.active_terrain_mods) == 1

    def test_terrain_events_logged(self):
        """Terrain modification events are written to combat log."""
        wall_action = self._make_terrain_action()
        manager, pid, eid = _setup_combat(player_actions=[wall_action])

        manager.selected_action = wall_action
        manager.execute_effect_at_hex(HexCoord(5, 5))

        terrain_events = [
            e for e in manager.log.events
            if e.event_type == CombatEventType.TERRAIN_MODIFICATION
        ]
        assert len(terrain_events) >= 1
        assert "Wall of Stone" in terrain_events[0].message
