"""Tests for Phase 6f: Tactical overrides (retreat, focus fire, protect)."""

import pytest

from arena.ai.tactics import (
    TacticalDecision,
    check_retreat,
    check_focus_fire,
    check_protect_ally,
)
from arena.ai.behavior import AIProfile
from arena.ai.context import CreatureView, CombatContext
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


# ── check_retreat ────────────────────────────────────────────────────

class TestCheckRetreat:
    def test_triggers_below_threshold_with_will_flee(self):
        profile = AIProfile(name="coward", will_flee=True, retreat_threshold=0.5)
        me = _view(cid="me", team="player", hp=0.3)
        ctx = _context(me)
        result = check_retreat(profile, ctx)
        assert result is not None
        assert result.decision_type == "retreat"
        assert result.forced_action == "disengage"

    def test_does_not_trigger_above_threshold(self):
        profile = AIProfile(name="coward", will_flee=True, retreat_threshold=0.25)
        me = _view(cid="me", team="player", hp=0.5)
        ctx = _context(me)
        assert check_retreat(profile, ctx) is None

    def test_does_not_trigger_when_will_flee_false(self):
        profile = AIProfile(name="berserker", will_flee=False, retreat_threshold=0.25)
        me = _view(cid="me", team="player", hp=0.1)
        ctx = _context(me)
        assert check_retreat(profile, ctx) is None

    def test_retreat_reason_contains_hp(self):
        profile = AIProfile(name="coward", will_flee=True, retreat_threshold=0.5)
        me = _view(cid="me", team="player", hp=0.2)
        ctx = _context(me)
        result = check_retreat(profile, ctx)
        assert "20%" in result.reason


# ── check_focus_fire ─────────────────────────────────────────────────

class TestCheckFocusFire:
    def test_identifies_nearly_dead_enemy(self):
        profile = AIProfile(name="test")
        me = _view(cid="me", team="player")
        dying = _view(cid="dying", hp=0.15)
        healthy = _view(cid="healthy", hp=0.8)
        ctx = _context(me, enemies=[dying, healthy])
        result = check_focus_fire(profile, ctx)
        assert result == "dying"

    def test_no_trigger_when_no_low_enemy(self):
        profile = AIProfile(name="test")
        me = _view(cid="me", team="player")
        ctx = _context(me, enemies=[_view(cid="e", hp=0.5)])
        assert check_focus_fire(profile, ctx) is None

    def test_prefers_lowest_hp(self):
        profile = AIProfile(name="test")
        me = _view(cid="me", team="player")
        low = _view(cid="low", hp=0.1)
        lower = _view(cid="lower", hp=0.05)
        ctx = _context(me, enemies=[low, lower])
        assert check_focus_fire(profile, ctx) == "lower"

    def test_no_enemies_returns_none(self):
        profile = AIProfile(name="test")
        me = _view(cid="me", team="player")
        ctx = _context(me, enemies=[])
        assert check_focus_fire(profile, ctx) is None


# ── check_protect_ally ───────────────────────────────────────────────

class TestCheckProtectAlly:
    def test_triggers_when_protects_allies_and_ally_low(self):
        profile = AIProfile(name="protector", protects_allies=True)
        me = _view(cid="me", team="player")
        wounded_ally = _view(cid="ally", team="player", hp=0.2)
        ctx = _context(me, allies=[wounded_ally])
        result = check_protect_ally(profile, ctx)
        assert result == "ally"

    def test_no_trigger_when_protects_allies_false(self):
        profile = AIProfile(name="selfish", protects_allies=False)
        me = _view(cid="me", team="player")
        wounded = _view(cid="ally", team="player", hp=0.1)
        ctx = _context(me, allies=[wounded])
        assert check_protect_ally(profile, ctx) is None

    def test_no_trigger_when_allies_healthy(self):
        profile = AIProfile(name="protector", protects_allies=True)
        me = _view(cid="me", team="player")
        healthy = _view(cid="ally", team="player", hp=0.8)
        ctx = _context(me, allies=[healthy])
        assert check_protect_ally(profile, ctx) is None

    def test_no_trigger_when_no_allies(self):
        profile = AIProfile(name="protector", protects_allies=True)
        me = _view(cid="me", team="player")
        ctx = _context(me, allies=[])
        assert check_protect_ally(profile, ctx) is None

    def test_returns_most_wounded_ally(self):
        profile = AIProfile(name="protector", protects_allies=True)
        me = _view(cid="me", team="player")
        low = _view(cid="low", team="player", hp=0.2)
        lower = _view(cid="lower", team="player", hp=0.1)
        ctx = _context(me, allies=[low, lower])
        assert check_protect_ally(profile, ctx) == "lower"
