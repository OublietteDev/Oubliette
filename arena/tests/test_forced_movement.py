"""Tests for the forced movement system (push, pull, slide, shove)."""

from __future__ import annotations

from unittest.mock import patch

import pygame
import pytest

from arena.combat.manager import CombatManager, Combatant
from arena.combat.events import CombatEventType
from arena.combat.forced_movement import (
    calculate_push_path,
    calculate_pull_path,
    calculate_slide_path,
    resolve_forced_movement,
    resolve_shove_contest,
    ForcedMovementResult,
    _get_skill_modifier,
)
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action, ActionType, Attack, DamageRoll, DamageType,
    SavingThrowEffect, TargetType,
)
from arena.models.character import PlayerCharacter, CreatureSize
from arena.models.conditions import Condition
from arena.combat.conditions import has_condition
from arena.models.encounter import CombatantEntry, Encounter, TerrainType


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_fighter(
    name="Fighter",
    strength=16,
    dexterity=10,
    hp=40,
    actions=None,
    skill_proficiencies=None,
    is_player=True,
) -> PlayerCharacter:
    return PlayerCharacter(
        name=name,
        max_hit_points=hp,
        armor_class=15,
        ability_scores=AbilityScores(strength=strength, dexterity=dexterity),
        proficiency_bonus=3,
        is_player_controlled=is_player,
        character_class="Fighter",
        level=5,
        actions=actions or [],
        skill_proficiencies=skill_proficiencies or [],
    )


def _make_enemy(
    name="Goblin",
    hp=20,
    strength=10,
    dexterity=14,
    skill_proficiencies=None,
) -> PlayerCharacter:
    return PlayerCharacter(
        name=name,
        max_hit_points=hp,
        armor_class=13,
        ability_scores=AbilityScores(strength=strength, dexterity=dexterity),
        proficiency_bonus=2,
        is_player_controlled=False,
        character_class="Fighter",
        level=1,
        skill_proficiencies=skill_proficiencies or [],
    )


def _thunderwave() -> Action:
    """Thunderwave: push 10ft on failed CON save."""
    return Action(
        name="Thunderwave",
        description="Push creatures 10ft on failed save.",
        action_type=ActionType.ACTION,
        target_type=TargetType.AREA_CUBE,
        range=5,
        area_size=15,
        saving_throw=SavingThrowEffect(
            ability="constitution",
            dc=14,
            damage_on_fail=[DamageRoll(dice="2d8", damage_type=DamageType.THUNDER)],
            damage_on_success="half",
        ),
        forced_movement_type="push",
        forced_movement_distance=10,
    )


def _repelling_blast() -> Action:
    """Eldritch Blast with Repelling Blast: push 10ft on hit."""
    return Action(
        name="Eldritch Blast",
        description="Push target 10ft on hit.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=120,
        attack=Attack(
            name="Eldritch Blast",
            attack_type="ranged_spell",
            ability="charisma",
            reach=5,
            range_normal=120,
            damage=[DamageRoll(dice="1d10", damage_type=DamageType.FORCE)],
        ),
        forced_movement_type="push",
        forced_movement_distance=10,
    )


def _thorn_whip() -> Action:
    """Thorn Whip: pull 10ft on hit."""
    return Action(
        name="Thorn Whip",
        description="Pull target 10ft toward you.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=30,
        attack=Attack(
            name="Thorn Whip",
            attack_type="melee_spell",
            ability="wisdom",
            reach=30,
            damage=[DamageRoll(dice="1d6", damage_type=DamageType.PIERCING)],
        ),
        forced_movement_type="pull",
        forced_movement_distance=10,
    )


def _push_with_prone() -> Action:
    """Action that pushes 5ft and knocks prone."""
    return Action(
        name="Shield Bash",
        description="Push 5ft and knock prone.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=5,
        attack=Attack(
            name="Shield Bash",
            attack_type="melee_weapon",
            ability="strength",
            reach=5,
            damage=[DamageRoll(dice="1d6", damage_type=DamageType.BLUDGEONING)],
        ),
        forced_movement_type="push",
        forced_movement_distance=5,
        forced_movement_prone=True,
    )


def _setup_combat(
    grid_w=10, grid_h=10,
    player=None, enemy=None,
    player_pos=(2, 2), enemy_pos=(3, 2),
    terrain=None,
    extra_combatants=None,
) -> tuple[CombatManager, str, str]:
    """Set up a CombatManager with a player and enemy on a grid.

    Returns (manager, player_id, enemy_id).

    Note: CombatManager generates creature IDs from the creature's name
    (lowercased), so the returned IDs are based on creature names.
    """
    from pathlib import Path

    p = player or _make_fighter()
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
    if extra_combatants:
        combatants.extend(extra_combatants)

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

    # Roll initiative
    with patch("arena.combat.manager.roll_die", return_value=10):
        manager.roll_initiative()
    manager.begin_combat()

    # Derive actual IDs from creature names (load_encounter uses name-based IDs)
    ids = list(manager.combatants.keys())
    player_id = None
    enemy_id = None
    for cid, c in manager.combatants.items():
        if c.team == "player":
            player_id = cid
        elif c.team == "enemy":
            enemy_id = cid

    assert player_id is not None, f"No player found in {ids}"
    assert enemy_id is not None, f"No enemy found in {ids}"

    return manager, player_id, enemy_id


# ==================================================================
# 1. Push path calculation
# ==================================================================

class TestPushPath:
    """Test calculate_push_path direction and obstacle handling."""

    def test_basic_push_direction(self):
        """Push moves target away from source in the correct direction."""
        grid = HexGrid(10, 10)
        source = HexCoord(2, 2)
        target = HexCoord(3, 2)

        dest, stopped, pit = calculate_push_path(
            source, target, 10, grid, "t1",
        )
        # Should move 2 hexes (10ft / 5ft per hex) away from source
        assert dest != target
        assert dest.distance_to(source) > target.distance_to(source)
        assert not stopped
        assert not pit

    def test_push_zero_distance(self):
        """Push with distance=0 doesn't move."""
        grid = HexGrid(10, 10)
        dest, stopped, pit = calculate_push_path(
            HexCoord(2, 2), HexCoord(3, 2), 0, grid, "t1",
        )
        assert dest == HexCoord(3, 2)

    def test_push_same_position(self):
        """Push from same position doesn't move."""
        grid = HexGrid(10, 10)
        dest, stopped, pit = calculate_push_path(
            HexCoord(2, 2), HexCoord(2, 2), 10, grid, "t1",
        )
        assert dest == HexCoord(2, 2)

    def test_push_stopped_by_wall(self):
        """Push stops before a wall hex."""
        grid = HexGrid(10, 10)
        source = HexCoord(2, 2)
        target = HexCoord(3, 2)

        # Place a wall 2 hexes away in push direction
        # First find where the push would go
        dest_no_wall, _, _ = calculate_push_path(
            source, target, 10, grid, "t1",
        )

        # Place wall at destination
        cell = grid.get_cell(dest_no_wall)
        if cell:
            cell.terrain = TerrainType.WALL

        dest, stopped, pit = calculate_push_path(
            source, target, 10, grid, "t1",
        )
        assert dest != dest_no_wall
        assert stopped

    def test_push_stopped_by_grid_edge(self):
        """Push stops at grid boundary."""
        grid = HexGrid(5, 5)
        source = HexCoord(0, 2)
        target = HexCoord(1, 2)

        dest, stopped, pit = calculate_push_path(
            source, target, 60, grid, "t1",  # Very long push
        )
        # Should stop somewhere within grid bounds
        cell = grid.get_cell(dest)
        assert cell is not None

    def test_push_into_pit(self):
        """Push into a pit stops on the pit hex."""
        grid = HexGrid(10, 10)
        source = HexCoord(2, 2)
        target = HexCoord(3, 2)

        # First find push direction
        dest_no_pit, _, _ = calculate_push_path(
            source, target, 5, grid, "t1",
        )

        # Place pit at that destination
        cell = grid.get_cell(dest_no_pit)
        if cell:
            cell.terrain = TerrainType.PIT

        dest, stopped, pit = calculate_push_path(
            source, target, 5, grid, "t1",
        )
        assert pit
        assert dest == dest_no_pit  # Creature falls INTO the pit

    def test_push_stopped_by_occupied_hex(self):
        """Push stops before a hex occupied by another creature."""
        grid = HexGrid(10, 10)
        source = HexCoord(2, 2)
        target = HexCoord(3, 2)

        # Find push direction and place a blocker
        dest_free, _, _ = calculate_push_path(
            source, target, 5, grid, "t1",
        )
        grid.place_creature(dest_free, "blocker")

        dest, stopped, pit = calculate_push_path(
            source, target, 5, grid, "t1",
        )
        assert stopped
        assert dest != dest_free


# ==================================================================
# 2. Pull path calculation
# ==================================================================

class TestPullPath:
    """Test calculate_pull_path."""

    def test_basic_pull_direction(self):
        """Pull moves target toward source."""
        grid = HexGrid(10, 10)
        source = HexCoord(2, 2)
        target = HexCoord(5, 2)

        dest, stopped, pit = calculate_pull_path(
            source, target, 10, grid, "t1",
        )
        # Should be closer to source
        assert dest.distance_to(source) < target.distance_to(source)
        assert not stopped
        assert not pit

    def test_pull_stops_before_source(self):
        """Pull doesn't land on source's hex."""
        grid = HexGrid(10, 10)
        source = HexCoord(2, 2)
        target = HexCoord(3, 2)  # Adjacent

        dest, stopped, pit = calculate_pull_path(
            source, target, 30, grid, "t1",
        )
        # Should not end up on source hex
        assert dest != source

    def test_pull_already_adjacent(self):
        """Pull on an already adjacent creature doesn't move past source."""
        grid = HexGrid(10, 10)
        source = HexCoord(2, 2)
        target = HexCoord(3, 2)

        dest, stopped, pit = calculate_pull_path(
            source, target, 5, grid, "t1",
        )
        assert dest != source

    def test_pull_zero_distance(self):
        """Pull with distance=0 doesn't move."""
        grid = HexGrid(10, 10)
        dest, _, _ = calculate_pull_path(
            HexCoord(2, 2), HexCoord(5, 2), 0, grid, "t1",
        )
        assert dest == HexCoord(5, 2)

    def test_pull_stopped_by_wall(self):
        """Pull stops before a wall between source and target."""
        grid = HexGrid(10, 10)
        source = HexCoord(2, 2)
        target = HexCoord(5, 2)

        # Place wall between them
        wall_pos = HexCoord(4, 2)
        cell = grid.get_cell(wall_pos)
        if cell:
            cell.terrain = TerrainType.WALL

        dest, stopped, pit = calculate_pull_path(
            source, target, 15, grid, "t1",
        )
        assert stopped
        # Should stop before the wall
        assert dest.distance_to(source) > wall_pos.distance_to(source)


# ==================================================================
# 3. Slide path calculation
# ==================================================================

class TestSlidePath:
    """Test calculate_slide_path."""

    def test_basic_slide(self):
        """Slide moves target to chosen destination."""
        grid = HexGrid(10, 10)
        target = HexCoord(5, 5)
        slide_dest = HexCoord(7, 5)

        dest, stopped, pit = calculate_slide_path(
            target, slide_dest, 10, grid, "t1",
        )
        assert dest.distance_to(target) > 0
        assert not stopped

    def test_slide_stopped_by_wall(self):
        """Slide stops before a wall."""
        grid = HexGrid(10, 10)
        target = HexCoord(5, 5)
        slide_dest = HexCoord(8, 5)

        # Place wall
        wall = HexCoord(7, 5)
        cell = grid.get_cell(wall)
        if cell:
            cell.terrain = TerrainType.WALL

        dest, stopped, pit = calculate_slide_path(
            target, slide_dest, 15, grid, "t1",
        )
        assert stopped

    def test_slide_zero_distance(self):
        """Slide with distance=0 doesn't move."""
        grid = HexGrid(10, 10)
        dest, _, _ = calculate_slide_path(
            HexCoord(5, 5), HexCoord(7, 5), 0, grid, "t1",
        )
        assert dest == HexCoord(5, 5)

    def test_slide_same_position(self):
        """Slide to same position doesn't move."""
        grid = HexGrid(10, 10)
        dest, _, _ = calculate_slide_path(
            HexCoord(5, 5), HexCoord(5, 5), 10, grid, "t1",
        )
        assert dest == HexCoord(5, 5)


# ==================================================================
# 4. resolve_forced_movement integration
# ==================================================================

class TestResolveForcedMovement:
    """Test the resolve_forced_movement function."""

    def test_push_moves_creature_on_grid(self):
        """Push should update the grid occupancy."""
        grid = HexGrid(10, 10)
        target_pos = HexCoord(5, 5)
        source_pos = HexCoord(4, 5)
        grid.place_creature(target_pos, "target")

        creature = _make_enemy()
        result = resolve_forced_movement(
            source_id="source",
            source_pos=source_pos,
            target_id="target",
            target_pos=target_pos,
            movement_type="push",
            distance_feet=5,
            grid=grid,
            combatants={},
            target_creature=creature,
        )

        assert result.distance_moved > 0
        assert result.destination_hex != target_pos
        # Grid should reflect new position
        old_cell = grid.get_cell(target_pos)
        assert old_cell.occupant_id is None
        new_cell = grid.get_cell(result.destination_hex)
        assert new_cell.occupant_id == "target"

    def test_push_generates_event(self):
        """Push should generate a FORCED_MOVEMENT event."""
        grid = HexGrid(10, 10)
        target_pos = HexCoord(5, 5)
        source_pos = HexCoord(4, 5)
        grid.place_creature(target_pos, "target")

        creature = _make_enemy()
        result = resolve_forced_movement(
            source_id="source",
            source_pos=source_pos,
            target_id="target",
            target_pos=target_pos,
            movement_type="push",
            distance_feet=5,
            grid=grid,
            combatants={},
            target_creature=creature,
        )

        fm_events = [e for e in result.events
                     if e.event_type == CombatEventType.FORCED_MOVEMENT]
        assert len(fm_events) == 1
        assert "pushed" in fm_events[0].message

    def test_pull_generates_event(self):
        """Pull should generate a FORCED_MOVEMENT event."""
        grid = HexGrid(10, 10)
        target_pos = HexCoord(5, 5)
        source_pos = HexCoord(2, 5)
        grid.place_creature(target_pos, "target")

        creature = _make_enemy()
        result = resolve_forced_movement(
            source_id="source",
            source_pos=source_pos,
            target_id="target",
            target_pos=target_pos,
            movement_type="pull",
            distance_feet=10,
            grid=grid,
            combatants={},
            target_creature=creature,
        )

        fm_events = [e for e in result.events
                     if e.event_type == CombatEventType.FORCED_MOVEMENT]
        assert len(fm_events) == 1
        assert "pulled" in fm_events[0].message

    def test_push_with_prone(self):
        """Push with knock_prone should apply prone condition."""
        grid = HexGrid(10, 10)
        target_pos = HexCoord(5, 5)
        source_pos = HexCoord(4, 5)
        grid.place_creature(target_pos, "target")

        creature = _make_enemy()
        result = resolve_forced_movement(
            source_id="source",
            source_pos=source_pos,
            target_id="target",
            target_pos=target_pos,
            movement_type="push",
            distance_feet=5,
            grid=grid,
            combatants={},
            target_creature=creature,
            knock_prone=True,
        )

        assert result.knocked_prone
        assert has_condition(creature, Condition.PRONE)

    def test_no_movement_when_blocked(self):
        """If creature is completely blocked, distance_moved is 0."""
        grid = HexGrid(10, 10)
        target_pos = HexCoord(5, 5)
        source_pos = HexCoord(4, 5)
        grid.place_creature(target_pos, "target")

        # Wall all hexes around target in push direction
        # Push goes from source(4,5) through target(5,5) outward
        # Block the next hex
        for nb in target_pos.neighbors():
            if nb != source_pos:
                cell = grid.get_cell(nb)
                if cell:
                    cell.terrain = TerrainType.WALL

        creature = _make_enemy()
        result = resolve_forced_movement(
            source_id="source",
            source_pos=source_pos,
            target_id="target",
            target_pos=target_pos,
            movement_type="push",
            distance_feet=5,
            grid=grid,
            combatants={},
            target_creature=creature,
        )

        assert result.stopped_by_wall

    def test_unknown_type_returns_no_movement(self):
        """Unknown movement type returns target at original position."""
        grid = HexGrid(10, 10)
        target_pos = HexCoord(5, 5)
        source_pos = HexCoord(4, 5)

        creature = _make_enemy()
        result = resolve_forced_movement(
            source_id="source",
            source_pos=source_pos,
            target_id="target",
            target_pos=target_pos,
            movement_type="invalid",
            distance_feet=10,
            grid=grid,
            combatants={},
            target_creature=creature,
        )

        assert result.destination_hex == target_pos
        assert result.distance_moved == 0

    def test_slide_defaults_to_push_direction(self):
        """Slide with no explicit destination uses push direction."""
        grid = HexGrid(10, 10)
        target_pos = HexCoord(5, 5)
        source_pos = HexCoord(4, 5)
        grid.place_creature(target_pos, "target")

        creature = _make_enemy()
        result = resolve_forced_movement(
            source_id="source",
            source_pos=source_pos,
            target_id="target",
            target_pos=target_pos,
            movement_type="slide",
            distance_feet=5,
            grid=grid,
            combatants={},
            target_creature=creature,
        )

        # Should move in push direction (away from source)
        assert result.destination_hex != target_pos
        assert result.destination_hex.distance_to(source_pos) > target_pos.distance_to(source_pos)


# ==================================================================
# 5. Shove contest
# ==================================================================

class TestShoveContest:
    """Test resolve_shove_contest."""

    def test_shove_success_high_roll(self):
        """Shove succeeds when attacker rolls higher."""
        attacker = _make_fighter(strength=18, skill_proficiencies=["athletics"])
        target = _make_enemy(strength=8, dexterity=10)

        # Mock: attacker rolls 15, defender rolls 5
        with patch("arena.combat.forced_movement.roll_die", side_effect=[15, 5]):
            success, events = resolve_shove_contest(
                attacker, "att", target, "def",
            )

        assert success
        assert len(events) == 1
        assert "SUCCESS" in events[0].message

    def test_shove_failure_low_roll(self):
        """Shove fails when defender rolls higher."""
        attacker = _make_fighter(strength=10)
        target = _make_enemy(strength=18, skill_proficiencies=["athletics"])

        # Mock: attacker rolls 5, defender rolls 15
        with patch("arena.combat.forced_movement.roll_die", side_effect=[5, 15]):
            success, events = resolve_shove_contest(
                attacker, "att", target, "def",
            )

        assert not success
        assert "FAILURE" in events[0].message

    def test_shove_tie_goes_to_attacker(self):
        """Ties go to the attacker in shove contests."""
        attacker = _make_fighter(strength=14)
        target = _make_enemy(strength=14)

        # Mock: both roll 10, same modifier → tie
        with patch("arena.combat.forced_movement.roll_die", side_effect=[10, 10]):
            success, events = resolve_shove_contest(
                attacker, "att", target, "def",
            )

        assert success

    def test_shove_defender_uses_acrobatics(self):
        """Defender uses Acrobatics when it's higher than Athletics."""
        attacker = _make_fighter(strength=14)
        target = _make_enemy(
            strength=8, dexterity=18,
            skill_proficiencies=["acrobatics"],
        )

        with patch("arena.combat.forced_movement.roll_die", side_effect=[10, 10]):
            success, events = resolve_shove_contest(
                attacker, "att", target, "def",
            )

        # DEX 18 → +4, +2 prof = +6 Acrobatics vs STR 14 → +2 Athletics
        # 10+2=12 vs 10+6=16 → FAILURE
        assert not success
        assert "Acrobatics" in events[0].message

    def test_shove_contest_event_details(self):
        """Contest event contains all expected detail fields."""
        attacker = _make_fighter(strength=16)
        target = _make_enemy()

        with patch("arena.combat.forced_movement.roll_die", side_effect=[15, 8]):
            success, events = resolve_shove_contest(
                attacker, "att", target, "def",
            )

        details = events[0].details
        assert details["contest"] is True
        assert "attacker_roll" in details
        assert "defender_roll" in details
        assert "defender_skill" in details
        assert "success" in details


# ==================================================================
# 6. Skill modifier helper
# ==================================================================

class TestGetSkillModifier:
    """Test _get_skill_modifier."""

    def test_athletics_with_proficiency(self):
        """Athletics mod = STR mod + proficiency."""
        creature = _make_fighter(
            strength=16, skill_proficiencies=["athletics"],
        )
        mod = _get_skill_modifier(creature, "athletics")
        # STR 16 → +3, prof bonus 3 → total 6
        assert mod == 6

    def test_athletics_without_proficiency(self):
        """Athletics without proficiency = just STR mod."""
        creature = _make_fighter(strength=16)
        mod = _get_skill_modifier(creature, "athletics")
        assert mod == 3

    def test_acrobatics_with_proficiency(self):
        """Acrobatics mod = DEX mod + proficiency."""
        creature = _make_fighter(
            dexterity=16, skill_proficiencies=["acrobatics"],
        )
        mod = _get_skill_modifier(creature, "acrobatics")
        # DEX 16 → +3, prof bonus 3 → total 6
        assert mod == 6


# ==================================================================
# 7. CombatManager execute_shove
# ==================================================================

class TestExecuteShove:
    """Test CombatManager.execute_shove()."""

    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        pygame.display.set_mode((1, 1))
        yield
        pygame.quit()

    def _advance_to(self, manager, creature_id):
        """Advance initiative to the given creature's turn."""
        for _ in range(20):
            if (manager.active_combatant is None
                    or manager.active_combatant.creature_id == creature_id):
                break
            manager.end_turn()

    def test_shove_push_success(self):
        """Successful shove-push moves the target 5ft away."""
        player = _make_fighter(strength=20, skill_proficiencies=["athletics"])
        enemy = _make_enemy(strength=8)
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(5, 4),
        )
        self._advance_to(manager, pid)

        original_pos = manager.combatants[eid].position

        with patch("arena.combat.forced_movement.roll_die", side_effect=[18, 3]):
            result = manager.execute_shove(eid, "push")

        assert result is not None
        new_pos = manager.combatants[eid].position
        assert new_pos != original_pos
        assert manager.turn_resources.has_used_action

    def test_shove_prone_success(self):
        """Successful shove-prone applies prone condition."""
        player = _make_fighter(strength=20, skill_proficiencies=["athletics"])
        enemy = _make_enemy(strength=8)
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(5, 4),
        )
        self._advance_to(manager, pid)

        with patch("arena.combat.forced_movement.roll_die", side_effect=[18, 3]):
            result = manager.execute_shove(eid, "prone")

        assert result is not None
        assert has_condition(manager.combatants[eid].creature, Condition.PRONE)
        assert manager.turn_resources.has_used_action

    def test_shove_failure(self):
        """Failed shove doesn't move or prone the target."""
        player = _make_fighter(strength=8)
        enemy = _make_enemy(strength=18, skill_proficiencies=["athletics"])
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(5, 4),
        )
        self._advance_to(manager, pid)

        original_pos = manager.combatants[eid].position

        with patch("arena.combat.forced_movement.roll_die", side_effect=[3, 18]):
            result = manager.execute_shove(eid, "push")

        assert result is not None
        # Target didn't move
        assert manager.combatants[eid].position == original_pos
        # Action was still used
        assert manager.turn_resources.has_used_action

    def test_shove_out_of_range(self):
        """Shove fails if target is not adjacent."""
        player = _make_fighter()
        enemy = _make_enemy()
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(2, 2), enemy_pos=(5, 5),  # Far apart
        )
        self._advance_to(manager, pid)

        result = manager.execute_shove(eid, "push")
        assert result is None
        assert not manager.turn_resources.has_used_action

    def test_shove_requires_action(self):
        """Shove fails if action already used."""
        player = _make_fighter()
        enemy = _make_enemy()
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(5, 4),
        )
        self._advance_to(manager, pid)
        manager.turn_resources.has_used_action = True

        result = manager.execute_shove(eid, "push")
        assert result is None


# ==================================================================
# 8. Attack + Forced Movement integration
# ==================================================================

class TestAttackForcedMovement:
    """Test forced movement triggered by attacks (e.g. Repelling Blast)."""

    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        pygame.display.set_mode((1, 1))
        yield
        pygame.quit()

    def _advance_to(self, manager, creature_id):
        for _ in range(20):
            if (manager.active_combatant is None
                    or manager.active_combatant.creature_id == creature_id):
                break
            manager.end_turn()

    def test_push_on_hit(self):
        """Attack with forced_movement_type pushes target on hit."""
        blast = _repelling_blast()
        player = _make_fighter(actions=[blast])
        enemy = _make_enemy()
        # Enemy two hexes away (10 ft): a ranged blast from melee range would
        # roll at disadvantage (D-ACT-4), which routes through dice the
        # actions.roll_die patch doesn't reach — keep it a clean straight shot.
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(6, 4),
        )
        self._advance_to(manager, pid)

        manager.select_action(blast)

        # Force hit (high attack roll)
        with patch("arena.combat.actions.roll_die", return_value=19):
            result = manager.execute_attack(eid)

        assert result is not None
        # Check for forced movement events
        fm_events = [e for e in result.events
                     if e.event_type == CombatEventType.FORCED_MOVEMENT]
        assert len(fm_events) >= 1

    def test_no_push_on_miss(self):
        """Attack with forced_movement_type does NOT push on miss."""
        blast = _repelling_blast()
        player = _make_fighter(actions=[blast])
        enemy = _make_enemy()
        # Two hexes away: a clean straight shot so the forced low roll lands
        # (a point-blank ranged blast would roll at disadvantage — D-ACT-4).
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(6, 4),
        )
        self._advance_to(manager, pid)

        manager.select_action(blast)

        # Force miss (low attack roll)
        with patch("arena.combat.actions.roll_die", return_value=1):
            result = manager.execute_attack(eid)

        assert result is not None
        fm_events = [e for e in result.events
                     if e.event_type == CombatEventType.FORCED_MOVEMENT]
        assert len(fm_events) == 0


# ==================================================================
# 9. Effect + Forced Movement integration (save-based)
# ==================================================================

class TestEffectForcedMovement:
    """Test forced movement triggered by effects (e.g. Thunderwave)."""

    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        pygame.display.set_mode((1, 1))
        yield
        pygame.quit()

    def _advance_to(self, manager, creature_id):
        for _ in range(20):
            if (manager.active_combatant is None
                    or manager.active_combatant.creature_id == creature_id):
                break
            manager.end_turn()

    def test_push_on_failed_save(self):
        """Effect with FM pushes target when save fails."""
        tw = _thunderwave()
        player = _make_fighter(actions=[tw])
        enemy = _make_enemy()
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(5, 4),
        )
        self._advance_to(manager, pid)

        manager.select_action(tw)

        # Force failed save (low roll)
        with patch("arena.combat.actions.roll_die", return_value=2):
            result = manager.execute_effect(eid)

        assert result is not None
        fm_events = [e for e in result.events
                     if e.event_type == CombatEventType.FORCED_MOVEMENT]
        assert len(fm_events) >= 1

    def test_no_push_on_successful_save(self):
        """Effect with FM does NOT push when save succeeds."""
        tw = _thunderwave()
        player = _make_fighter(actions=[tw])
        enemy = _make_enemy()
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(5, 4),
        )
        self._advance_to(manager, pid)

        manager.select_action(tw)

        # Force successful save (high roll)
        with patch("arena.combat.actions.roll_die", return_value=20):
            result = manager.execute_effect(eid)

        assert result is not None
        fm_events = [e for e in result.events
                     if e.event_type == CombatEventType.FORCED_MOVEMENT]
        assert len(fm_events) == 0


# ==================================================================
# 10. AI shove scoring
# ==================================================================

class TestAIShoveScoring:
    """Test AI scoring for shove actions."""

    def _make_view(self, cid, team, pos):
        from arena.ai.context import CreatureView
        return CreatureView(
            creature_id=cid,
            team=team,
            hp_percent=1.0,
            position=HexCoord(pos[0], pos[1]),
            is_conscious=True,
            armor_class=13,
            has_concentration=False,
            is_spellcaster=False,
            condition_names=(),
            max_hit_points=20,
            current_hit_points=20,
            speed=30,
            actions_count=1,
            size=CreatureSize.MEDIUM,
        )

    def _make_context(self, me, enemies, allies=()):
        from arena.ai.context import CombatContext
        return CombatContext(
            me=me,
            allies=tuple(allies),
            enemies=tuple(enemies),
            all_combatants=tuple([me] + list(allies) + list(enemies)),
            has_used_action=False,
            has_used_bonus_action=False,
            remaining_movement=30,
            grid_width=10,
            grid_height=10,
            round_number=1,
        )

    def test_score_shove_requires_adjacency(self):
        """Shove scores 0 when target is not adjacent."""
        from arena.ai.scoring import score_shove_action
        from arena.ai.behavior import DEFAULT_PROFILES

        profile = DEFAULT_PROFILES["default_monster"]
        me = self._make_view("me", "enemy", (5, 5))
        target = self._make_view("enemy", "player", (8, 8))
        context = self._make_context(me, [target])

        score, choice = score_shove_action(profile, context, target, 5)
        assert score == 0.0

    def test_score_shove_adjacent_target(self):
        """Shove scores > 0 when target is adjacent."""
        from arena.ai.scoring import score_shove_action
        from arena.ai.behavior import DEFAULT_PROFILES

        profile = DEFAULT_PROFILES["default_monster"]
        me = self._make_view("me", "enemy", (5, 5))
        target = self._make_view("enemy", "player", (6, 5))
        context = self._make_context(me, [target])

        score, choice = score_shove_action(profile, context, target, 1)
        assert score > 0

    def test_shove_prone_preferred_with_allies(self):
        """Prone is preferred when allies are adjacent to target."""
        from arena.ai.scoring import score_shove_action
        from arena.ai.behavior import DEFAULT_PROFILES

        profile = DEFAULT_PROFILES["default_monster"]
        me = self._make_view("me", "enemy", (5, 5))
        ally = self._make_view("ally", "enemy", (5, 4))
        target = self._make_view("foe", "player", (6, 5))
        context = self._make_context(me, [target], [ally])

        score, choice = score_shove_action(profile, context, target, 1)
        assert choice == "prone"


# ==================================================================
# 11. Visual effects
# ==================================================================

class TestForcedMovementVisualEffects:
    """Test ForcedMovementEffect visual effect."""

    def _make_effect(self, fm_type="push"):
        from arena.gui.visual_effects import ForcedMovementEffect, _FM_COLORS
        return ForcedMovementEffect(
            origin_wx=100.0,
            origin_wy=100.0,
            dest_wx=200.0,
            dest_wy=200.0,
            color=_FM_COLORS.get(fm_type, (255, 140, 60)),
        )

    def test_effect_creation(self):
        """ForcedMovementEffect can be created."""
        import pygame
        pygame.init()
        pygame.display.set_mode((1, 1))
        effect = self._make_effect("push")
        now = pygame.time.get_ticks()
        assert not effect.is_expired(now)
        pygame.quit()

    def test_effect_expires(self):
        """ForcedMovementEffect expires after duration."""
        effect = self._make_effect("push")
        # Set spawn_time far in the past
        effect.spawn_time = 0
        assert effect.is_expired(effect.duration_ms + 1)

    def test_effect_color_push(self):
        """Push effect uses orange color."""
        from arena.gui.visual_effects import _FM_COLORS
        effect = self._make_effect("push")
        assert effect.color == _FM_COLORS["push"]

    def test_effect_color_pull(self):
        """Pull effect uses blue color."""
        from arena.gui.visual_effects import _FM_COLORS
        effect = self._make_effect("pull")
        assert effect.color == _FM_COLORS["pull"]

    def test_effect_color_slide(self):
        """Slide effect uses green color."""
        from arena.gui.visual_effects import _FM_COLORS
        effect = self._make_effect("slide")
        assert effect.color == _FM_COLORS["slide"]


# ==================================================================
# 12. Action model fields
# ==================================================================

class TestActionModelFields:
    """Test forced movement fields on the Action model."""

    def test_default_values(self):
        """Action defaults have no forced movement."""
        action = Action(name="Test", description="Test")
        assert action.forced_movement_type is None
        assert action.forced_movement_distance == 0
        assert action.forced_movement_prone is False

    def test_push_action(self):
        """Action with push fields."""
        action = Action(
            name="Thunderwave",
            description="Push",
            forced_movement_type="push",
            forced_movement_distance=10,
        )
        assert action.forced_movement_type == "push"
        assert action.forced_movement_distance == 10
        assert action.forced_movement_prone is False

    def test_push_with_prone(self):
        """Action with push and prone."""
        action = Action(
            name="Shield Bash",
            description="Push and prone",
            forced_movement_type="push",
            forced_movement_distance=5,
            forced_movement_prone=True,
        )
        assert action.forced_movement_prone is True

    def test_serialization(self):
        """Forced movement fields serialize and deserialize."""
        action = Action(
            name="Test",
            description="Test",
            forced_movement_type="pull",
            forced_movement_distance=15,
            forced_movement_prone=True,
        )
        data = action.model_dump()
        assert data["forced_movement_type"] == "pull"
        assert data["forced_movement_distance"] == 15
        assert data["forced_movement_prone"] is True

        restored = Action.model_validate(data)
        assert restored.forced_movement_type == "pull"
        assert restored.forced_movement_distance == 15
        assert restored.forced_movement_prone is True


# ==================================================================
# 13. AI Controller integration
# ==================================================================

class TestAIControllerShove:
    """Test that TurnStepType.EXECUTE_SHOVE exists and TurnStep has shove_choice."""

    def test_execute_shove_step_type_exists(self):
        """EXECUTE_SHOVE is a valid TurnStepType."""
        from arena.ai.controller import TurnStepType
        assert hasattr(TurnStepType, "EXECUTE_SHOVE")

    def test_turn_step_shove_choice(self):
        """TurnStep can hold a shove_choice field."""
        from arena.ai.controller import TurnStep, TurnStepType
        step = TurnStep(
            step_type=TurnStepType.EXECUTE_SHOVE,
            target_id="enemy_1",
            shove_choice="prone",
        )
        assert step.shove_choice == "prone"


# ==================================================================
# 14. Edge cases
# ==================================================================

class TestEdgeCases:
    """Test edge cases and unusual scenarios."""

    def test_push_5ft(self):
        """Push 5ft moves exactly 1 hex."""
        grid = HexGrid(10, 10)
        source = HexCoord(5, 5)
        target = HexCoord(6, 5)

        dest, _, _ = calculate_push_path(source, target, 5, grid, "t1")
        assert target.distance_to(dest) == 1

    def test_push_10ft(self):
        """Push 10ft moves exactly 2 hexes."""
        grid = HexGrid(10, 10)
        source = HexCoord(3, 5)
        target = HexCoord(4, 5)

        dest, stopped, _ = calculate_push_path(source, target, 10, grid, "t1")
        if not stopped:
            assert target.distance_to(dest) == 2

    def test_forced_movement_event_details(self):
        """FORCED_MOVEMENT event has correct detail fields."""
        grid = HexGrid(10, 10)
        target_pos = HexCoord(5, 5)
        source_pos = HexCoord(4, 5)
        grid.place_creature(target_pos, "target")

        creature = _make_enemy()
        result = resolve_forced_movement(
            source_id="source",
            source_pos=source_pos,
            target_id="target",
            target_pos=target_pos,
            movement_type="push",
            distance_feet=5,
            grid=grid,
            combatants={},
            target_creature=creature,
        )

        fm_events = [e for e in result.events
                     if e.event_type == CombatEventType.FORCED_MOVEMENT]
        assert len(fm_events) == 1
        details = fm_events[0].details
        assert details["fm_type"] == "push"
        assert details["from_hex"] == (5, 5)
        assert "to_hex" in details
        assert "distance_moved" in details
