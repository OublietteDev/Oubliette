"""Tests for Phase 6d: Movement decision making."""

import pytest

from arena.ai.pathfinding import (
    MovementGoal,
    evaluate_position,
    find_best_movement,
    find_retreat_destination,
    get_adjacent_hexes_to_target,
    check_flanking,
)
from arena.ai.behavior import AIProfile
from arena.ai.context import CreatureView, CombatContext
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.encounter import TerrainType


def _view(cid="c1", team="enemy", pos=(5, 5), hp=1.0, speed=30, actions=1):
    return CreatureView(
        creature_id=cid, team=team,
        position=HexCoord(*pos) if pos else None,
        hp_percent=hp, is_conscious=True, armor_class=10,
        has_concentration=False, is_spellcaster=False,
        condition_names=(), max_hit_points=20, current_hit_points=int(20 * hp),
        speed=speed, actions_count=actions,
    )


def _context(me, enemies=(), allies=(), movement=30):
    all_c = (me,) + tuple(allies) + tuple(enemies)
    return CombatContext(
        me=me, allies=tuple(allies), enemies=tuple(enemies),
        all_combatants=all_c, grid_width=10, grid_height=10,
        round_number=1, remaining_movement=movement,
        has_used_action=False, has_used_bonus_action=False,
    )


# ── evaluate_position ────────────────────────────────────────────────

class TestEvaluatePosition:
    def test_melee_prefers_adjacent_to_target(self):
        profile = AIProfile(name="melee", prefers_melee=True)
        grid = HexGrid(10, 10)
        target = _view(cid="enemy", pos=(5, 5))
        me = _view(cid="me", team="player", pos=(3, 3))
        ctx = _context(me, enemies=[target])
        adjacent = HexCoord(5, 4)  # 1 hex from (5,5)
        far = HexCoord(2, 2)
        score_adj = evaluate_position(adjacent, profile, ctx, grid, target)
        score_far = evaluate_position(far, profile, ctx, grid, target)
        assert score_adj > score_far

    def test_ranged_prefers_optimal_distance(self):
        profile = AIProfile(name="archer", prefers_melee=False, maintains_distance=30)
        grid = HexGrid(20, 20)
        target = _view(cid="enemy", pos=(10, 10))
        me = _view(cid="me", team="player", pos=(4, 10))
        ctx = _context(me, enemies=[target])
        optimal = HexCoord(4, 10)  # 6 hexes from target (30ft)
        too_close = HexCoord(9, 10)  # 1 hex from target
        score_opt = evaluate_position(optimal, profile, ctx, grid, target)
        score_close = evaluate_position(too_close, profile, ctx, grid, target)
        assert score_opt > score_close

    def test_ranged_penalized_adjacent_enemies(self):
        profile = AIProfile(name="archer", prefers_melee=False, maintains_distance=30)
        grid = HexGrid(10, 10)
        enemy = _view(cid="enemy", pos=(5, 5))
        me = _view(cid="me", team="player", pos=(4, 5))
        ctx = _context(me, enemies=[enemy])
        # Adjacent to enemy
        adjacent = HexCoord(4, 5)
        # Far from enemy
        far = HexCoord(1, 1)
        score_adj = evaluate_position(adjacent, profile, ctx, grid, enemy)
        score_far = evaluate_position(far, profile, ctx, grid, enemy)
        # Far should be better for ranged (less adjacent enemy penalty)
        assert score_far > score_adj

    def test_no_target_gives_baseline(self):
        profile = AIProfile(name="test")
        grid = HexGrid(10, 10)
        me = _view(cid="me", team="player", pos=(0, 0))
        ctx = _context(me)
        score = evaluate_position(HexCoord(3, 3), profile, ctx, grid, None)
        assert score == pytest.approx(50.0, abs=5)  # near baseline


# ── find_best_movement ───────────────────────────────────────────────

class TestFindBestMovement:
    def test_approaches_enemy_for_melee(self):
        profile = AIProfile(name="melee", prefers_melee=True)
        grid = HexGrid(10, 10)
        enemy = _view(cid="enemy", pos=(5, 5))
        me = _view(cid="me", team="player", pos=(2, 5))
        ctx = _context(me, enemies=[enemy])
        grid.place_creature(HexCoord(2, 5), "me")
        grid.place_creature(HexCoord(5, 5), "enemy")
        result = find_best_movement(
            profile, ctx, grid, HexCoord(2, 5), 30, preferred_target=enemy
        )
        assert isinstance(result, MovementGoal)
        # Should move closer to enemy
        new_dist = result.target_hex.distance_to(HexCoord(5, 5))
        old_dist = HexCoord(2, 5).distance_to(HexCoord(5, 5))
        assert new_dist < old_dist

    def test_stay_when_already_optimal(self):
        profile = AIProfile(name="melee", prefers_melee=True)
        grid = HexGrid(10, 10)
        enemy = _view(cid="enemy", pos=(3, 5))
        me = _view(cid="me", team="player", pos=(2, 5))  # adjacent
        ctx = _context(me, enemies=[enemy])
        grid.place_creature(HexCoord(2, 5), "me")
        grid.place_creature(HexCoord(3, 5), "enemy")
        result = find_best_movement(
            profile, ctx, grid, HexCoord(2, 5), 30, preferred_target=enemy
        )
        # Already adjacent — may stay or move to another adjacent hex
        new_dist = result.target_hex.distance_to(HexCoord(3, 5))
        assert new_dist <= 1

    def test_returns_movement_goal(self):
        profile = AIProfile(name="test")
        grid = HexGrid(10, 10)
        me = _view(cid="me", team="player", pos=(5, 5))
        ctx = _context(me)
        grid.place_creature(HexCoord(5, 5), "me")
        result = find_best_movement(profile, ctx, grid, HexCoord(5, 5), 30)
        assert isinstance(result, MovementGoal)
        assert result.target_hex is not None


# ── find_retreat_destination ─────────────────────────────────────────

class TestFindRetreatDestination:
    def test_moves_away_from_enemies(self):
        grid = HexGrid(10, 10)
        enemy = _view(cid="enemy", pos=(5, 5))
        me = _view(cid="me", team="player", pos=(4, 5))
        ctx = _context(me, enemies=[enemy])
        grid.place_creature(HexCoord(4, 5), "me")
        grid.place_creature(HexCoord(5, 5), "enemy")
        result = find_retreat_destination(ctx, grid, HexCoord(4, 5), 30)
        if result is not None:
            new_dist = result.distance_to(HexCoord(5, 5))
            old_dist = HexCoord(4, 5).distance_to(HexCoord(5, 5))
            assert new_dist >= old_dist

    def test_returns_none_when_no_enemies(self):
        grid = HexGrid(10, 10)
        me = _view(cid="me", team="player", pos=(5, 5))
        ctx = _context(me, enemies=[])
        result = find_retreat_destination(ctx, grid, HexCoord(5, 5), 30)
        assert result is None


# ── get_adjacent_hexes_to_target ─────────────────────────────────────

class TestGetAdjacentHexes:
    def test_returns_unoccupied_neighbors(self):
        grid = HexGrid(10, 10)
        target_pos = HexCoord(5, 5)
        grid.place_creature(target_pos, "target")
        result = get_adjacent_hexes_to_target(target_pos, grid)
        assert len(result) > 0
        for hex_coord in result:
            assert hex_coord.distance_to(target_pos) == 1
            assert not grid.is_occupied(hex_coord)

    def test_excludes_occupied_hexes(self):
        grid = HexGrid(10, 10)
        target_pos = HexCoord(5, 5)
        grid.place_creature(target_pos, "target")
        neighbor = target_pos.neighbors()[0]
        grid.place_creature(neighbor, "blocker")
        result = get_adjacent_hexes_to_target(target_pos, grid)
        assert neighbor not in result

    def test_respects_reach(self):
        grid = HexGrid(10, 10)
        target_pos = HexCoord(5, 5)
        result = get_adjacent_hexes_to_target(target_pos, grid, reach=2)
        # Should include hexes at distance 1 and 2
        distances = {h.distance_to(target_pos) for h in result}
        assert 1 in distances
        assert 2 in distances


# ── check_flanking ───────────────────────────────────────────────────

class TestCheckFlanking:
    def test_flanking_with_ally_opposite(self):
        target = HexCoord(5, 5)
        attacker = HexCoord(4, 5)
        # Opposite of attacker relative to target
        opposite = HexCoord(6, 5)
        assert check_flanking(attacker, target, [opposite]) is True

    def test_no_flanking_without_ally(self):
        target = HexCoord(5, 5)
        attacker = HexCoord(4, 5)
        assert check_flanking(attacker, target, []) is False

    def test_no_flanking_when_not_adjacent(self):
        target = HexCoord(5, 5)
        attacker = HexCoord(3, 5)  # distance 2
        opposite = HexCoord(7, 5)
        assert check_flanking(attacker, target, [opposite]) is False

    def test_no_flanking_ally_not_opposite(self):
        target = HexCoord(5, 5)
        attacker = HexCoord(4, 5)
        # Ally is beside, not opposite
        not_opposite = HexCoord(5, 4)
        assert check_flanking(attacker, target, [not_opposite]) is False
