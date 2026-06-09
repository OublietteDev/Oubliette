"""Tests for Phase 6e: Resource management."""

import pytest

from arena.ai.resources import (
    should_use_limited_ability,
    get_remaining_uses,
    estimate_battle_progress,
)
from arena.ai.behavior import AIProfile
from arena.ai.context import CreatureView, CombatContext
from arena.models.actions import Action, ActionType
from arena.grid.coordinates import HexCoord


def _view(cid="c1", team="enemy", pos=(5, 5), hp=1.0, max_hp=20):
    cur_hp = int(max_hp * hp)
    return CreatureView(
        creature_id=cid, team=team,
        position=HexCoord(*pos), hp_percent=hp, is_conscious=True,
        armor_class=10, has_concentration=False, is_spellcaster=False,
        condition_names=(), max_hit_points=max_hp, current_hit_points=cur_hp,
        speed=30, actions_count=1,
    )


def _context(me, enemies=(), allies=()):
    all_c = (me,) + tuple(allies) + tuple(enemies)
    return CombatContext(
        me=me, allies=tuple(allies), enemies=tuple(enemies),
        all_combatants=all_c, grid_width=20, grid_height=15,
        round_number=1, remaining_movement=30,
        has_used_action=False, has_used_bonus_action=False,
    )


def _limited_action(name="Ability", uses=2, current=2, priority=5):
    return Action(
        name=name, description="test", action_type=ActionType.ACTION,
        uses_per_rest=uses, current_uses=current, ai_priority=priority,
    )


def _unlimited_action():
    return Action(
        name="Unlimited", description="test", action_type=ActionType.ACTION,
    )


class TestShouldUseLimited:
    def test_unlimited_always_true(self):
        profile = AIProfile(name="test")
        me = _view(cid="me", team="player")
        ctx = _context(me)
        assert should_use_limited_ability(_unlimited_action(), profile, ctx) is True

    def test_no_uses_remaining(self):
        profile = AIProfile(name="test", uses_limited_abilities=1.0)
        me = _view(cid="me", team="player")
        ctx = _context(me)
        action = _limited_action(current=0)
        assert should_use_limited_ability(action, profile, ctx) is False

    def test_uses_limited_zero_never_uses(self):
        profile = AIProfile(name="test", uses_limited_abilities=0.0)
        me = _view(cid="me", team="player")
        ctx = _context(me)
        action = _limited_action()
        assert should_use_limited_ability(action, profile, ctx) is False

    def test_uses_limited_one_freely_uses(self):
        profile = AIProfile(name="test", uses_limited_abilities=1.0)
        me = _view(cid="me", team="player")
        ctx = _context(me, enemies=[_view(cid="e")])
        action = _limited_action(priority=8)
        assert should_use_limited_ability(action, profile, ctx) is True

    def test_desperate_more_willing(self):
        profile = AIProfile(name="test", uses_limited_abilities=0.5)
        me_desperate = _view(cid="me", team="player", hp=0.2)
        ctx = _context(me_desperate, enemies=[_view(cid="e")])
        action = _limited_action(priority=5)
        assert should_use_limited_ability(action, profile, ctx) is True

    def test_high_priority_more_willing(self):
        profile = AIProfile(name="test", uses_limited_abilities=0.6)
        me = _view(cid="me", team="player")
        ctx = _context(me, enemies=[_view(cid="e")])
        high = _limited_action(priority=10)
        low = _limited_action(priority=1)
        # High priority should be more willing than low
        assert should_use_limited_ability(high, profile, ctx) is True


class TestGetRemainingUses:
    def test_unlimited_returns_none(self):
        assert get_remaining_uses(_unlimited_action()) is None

    def test_limited_returns_current(self):
        action = _limited_action(uses=3, current=1)
        assert get_remaining_uses(action) == 1

    def test_limited_no_current_returns_max(self):
        action = Action(
            name="test", description="test", action_type=ActionType.ACTION,
            uses_per_rest=3,
        )
        assert get_remaining_uses(action) == 3


class TestEstimateBattleProgress:
    def test_no_enemies_returns_1(self):
        me = _view(cid="me", team="player")
        ctx = _context(me, enemies=[])
        assert estimate_battle_progress(ctx) == 1.0

    def test_all_full_hp_returns_0(self):
        me = _view(cid="me", team="player")
        enemies = [_view(cid="e1", hp=1.0), _view(cid="e2", hp=1.0)]
        ctx = _context(me, enemies=enemies)
        assert estimate_battle_progress(ctx) == pytest.approx(0.0)

    def test_half_damage_returns_half(self):
        me = _view(cid="me", team="player")
        # Both enemies at 50% HP
        enemies = [_view(cid="e1", hp=0.5, max_hp=20), _view(cid="e2", hp=0.5, max_hp=20)]
        ctx = _context(me, enemies=enemies)
        assert estimate_battle_progress(ctx) == pytest.approx(0.5, abs=0.05)
