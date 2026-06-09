"""Tests for Phase 6b: Target evaluation."""

import pytest

from arena.ai.evaluation import evaluate_target, rank_targets, evaluate_threat
from arena.ai.behavior import AIProfile
from arena.ai.context import CreatureView, CombatContext
from arena.grid.coordinates import HexCoord


def _view(
    cid="c1",
    team="enemy",
    pos=(5, 5),
    hp=1.0,
    conscious=True,
    ac=10,
    concentration=False,
    caster=False,
    max_hp=20,
    cur_hp=None,
    speed=30,
    actions=1,
):
    """Create a CreatureView for testing."""
    if cur_hp is None:
        cur_hp = int(max_hp * hp)
    return CreatureView(
        creature_id=cid,
        team=team,
        position=HexCoord(*pos) if pos else None,
        hp_percent=hp,
        is_conscious=conscious,
        armor_class=ac,
        has_concentration=concentration,
        is_spellcaster=caster,
        condition_names=(),
        max_hit_points=max_hp,
        current_hit_points=cur_hp,
        speed=speed,
        actions_count=actions,
    )


def _context(me, enemies=(), allies=(), round_num=1, movement=30):
    """Create a CombatContext for testing."""
    all_c = (me,) + tuple(allies) + tuple(enemies)
    return CombatContext(
        me=me,
        allies=tuple(allies),
        enemies=tuple(enemies),
        all_combatants=all_c,
        grid_width=20,
        grid_height=15,
        round_number=round_num,
        remaining_movement=movement,
        has_used_action=False,
        has_used_bonus_action=False,
    )


# ── evaluate_target ─────────────────────────────────────────────────

class TestEvaluateTarget:
    def test_nearest_priority_prefers_closer(self):
        profile = AIProfile(name="test", target_priority="nearest", prefers_melee=True)
        me = _view(cid="me", team="player", pos=(0, 0))
        close = _view(cid="close", pos=(1, 0))
        far = _view(cid="far", pos=(5, 5))
        score_close = evaluate_target(profile, me, close)
        score_far = evaluate_target(profile, me, far)
        assert score_close > score_far

    def test_weakest_priority_prefers_low_hp(self):
        profile = AIProfile(name="test", target_priority="weakest")
        me = _view(cid="me", team="player", pos=(0, 0))
        wounded = _view(cid="wounded", pos=(2, 0), hp=0.2)
        healthy = _view(cid="healthy", pos=(2, 0), hp=1.0)
        score_wounded = evaluate_target(profile, me, wounded)
        score_healthy = evaluate_target(profile, me, healthy)
        assert score_wounded > score_healthy

    def test_strongest_priority_prefers_high_hp(self):
        profile = AIProfile(name="test", target_priority="strongest")
        me = _view(cid="me", team="player", pos=(0, 0))
        wounded = _view(cid="wounded", pos=(2, 0), hp=0.2)
        healthy = _view(cid="healthy", pos=(2, 0), hp=1.0)
        score_wounded = evaluate_target(profile, me, wounded)
        score_healthy = evaluate_target(profile, me, healthy)
        assert score_healthy > score_wounded

    def test_threatening_priority_uses_threat(self):
        profile = AIProfile(name="test", target_priority="threatening")
        me = _view(cid="me", team="player", pos=(0, 0))
        # High-threat: full HP, close, many actions
        high_threat = _view(cid="ht", pos=(1, 0), hp=1.0, actions=3)
        # Low-threat: low HP, far, few actions
        low_threat = _view(cid="lt", pos=(5, 5), hp=0.2, actions=1)
        score_high = evaluate_target(profile, me, high_threat)
        score_low = evaluate_target(profile, me, low_threat)
        assert score_high > score_low

    def test_random_priority_gives_similar_scores(self):
        profile = AIProfile(name="test", target_priority="random")
        me = _view(cid="me", team="player", pos=(0, 0))
        t1 = _view(cid="t1", pos=(1, 0), hp=1.0)
        t2 = _view(cid="t2", pos=(5, 5), hp=0.3)
        score1 = evaluate_target(profile, me, t1)
        score2 = evaluate_target(profile, me, t2)
        # Both should be ~50
        assert score1 == pytest.approx(50.0)
        assert score2 == pytest.approx(50.0)

    def test_spellcaster_focus_bonus(self):
        profile = AIProfile(name="test", focuses_spellcasters=True)
        me = _view(cid="me", team="player", pos=(0, 0))
        caster = _view(cid="caster", pos=(2, 0), caster=True)
        fighter = _view(cid="fighter", pos=(2, 0), caster=False)
        score_caster = evaluate_target(profile, me, caster)
        score_fighter = evaluate_target(profile, me, fighter)
        assert score_caster > score_fighter
        assert score_caster - score_fighter == pytest.approx(30.0)

    def test_concentration_bonus(self):
        profile = AIProfile(name="test")
        me = _view(cid="me", team="player", pos=(0, 0))
        conc = _view(cid="conc", pos=(2, 0), concentration=True)
        normal = _view(cid="normal", pos=(2, 0), concentration=False)
        score_conc = evaluate_target(profile, me, conc)
        score_normal = evaluate_target(profile, me, normal)
        assert score_conc > score_normal
        assert score_conc - score_normal == pytest.approx(25.0)

    def test_melee_preference_penalizes_distance(self):
        profile = AIProfile(name="test", prefers_melee=True)
        me = _view(cid="me", team="player", pos=(0, 0))
        near = _view(cid="near", pos=(1, 0))
        far = _view(cid="far", pos=(8, 0))
        score_near = evaluate_target(profile, me, near)
        score_far = evaluate_target(profile, me, far)
        # Near should be much higher
        assert score_near - score_far > 20

    def test_ranged_prefers_optimal_range(self):
        profile = AIProfile(name="test", prefers_melee=False, maintains_distance=30)
        me = _view(cid="me", team="player", pos=(0, 0))
        # Optimal is 30ft = 6 hexes
        at_optimal = _view(cid="opt", pos=(6, 0))
        too_close = _view(cid="close", pos=(1, 0))
        score_opt = evaluate_target(profile, me, at_optimal)
        score_close = evaluate_target(profile, me, too_close)
        assert score_opt > score_close

    def test_low_hp_kill_bonus(self):
        profile = AIProfile(name="test")
        me = _view(cid="me", team="player", pos=(0, 0))
        dying = _view(cid="dying", pos=(2, 0), hp=0.2)
        healthy = _view(cid="healthy", pos=(2, 0), hp=0.5)
        score_dying = evaluate_target(profile, me, dying)
        score_healthy = evaluate_target(profile, me, healthy)
        assert score_dying > score_healthy

    def test_no_position_returns_zero(self):
        profile = AIProfile(name="test")
        me = _view(cid="me", team="player", pos=None)
        target = _view(cid="t", pos=(2, 0))
        assert evaluate_target(profile, me, target) == 0.0

    def test_target_no_position_returns_zero(self):
        profile = AIProfile(name="test")
        me = _view(cid="me", team="player", pos=(0, 0))
        target = _view(cid="t", pos=None)
        assert evaluate_target(profile, me, target) == 0.0


# ── rank_targets ─────────────────────────────────────────────────────

class TestRankTargets:
    def test_returns_sorted_descending(self):
        profile = AIProfile(name="test", target_priority="nearest", prefers_melee=True)
        me = _view(cid="me", team="player", pos=(0, 0))
        enemies = [
            _view(cid="far", pos=(8, 0)),
            _view(cid="near", pos=(1, 0)),
            _view(cid="mid", pos=(4, 0)),
        ]
        ctx = _context(me, enemies=enemies)
        ranked = rank_targets(profile, ctx)
        assert len(ranked) == 3
        assert ranked[0][0] == "near"
        assert ranked[-1][0] == "far"
        # Scores should be descending
        for i in range(len(ranked) - 1):
            assert ranked[i][1] >= ranked[i + 1][1]

    def test_no_enemies_returns_empty(self):
        profile = AIProfile(name="test")
        me = _view(cid="me", team="player", pos=(0, 0))
        ctx = _context(me, enemies=[])
        assert rank_targets(profile, ctx) == []

    def test_one_enemy(self):
        profile = AIProfile(name="test")
        me = _view(cid="me", team="player", pos=(0, 0))
        enemy = _view(cid="goblin", pos=(3, 0))
        ctx = _context(me, enemies=[enemy])
        ranked = rank_targets(profile, ctx)
        assert len(ranked) == 1
        assert ranked[0][0] == "goblin"


# ── evaluate_threat ──────────────────────────────────────────────────

class TestEvaluateThreat:
    def test_closer_is_more_threatening(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        close = _view(cid="close", pos=(1, 0))
        far = _view(cid="far", pos=(8, 0))
        assert evaluate_threat(close, me) > evaluate_threat(far, me)

    def test_healthier_is_more_threatening(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        healthy = _view(cid="healthy", pos=(3, 0), hp=1.0)
        wounded = _view(cid="wounded", pos=(3, 0), hp=0.2)
        assert evaluate_threat(healthy, me) > evaluate_threat(wounded, me)

    def test_more_actions_more_threatening(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        multi = _view(cid="multi", pos=(3, 0), actions=4)
        single = _view(cid="single", pos=(3, 0), actions=1)
        assert evaluate_threat(multi, me) > evaluate_threat(single, me)

    def test_spellcaster_more_threatening(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        caster = _view(cid="caster", pos=(3, 0), caster=True)
        fighter = _view(cid="fighter", pos=(3, 0), caster=False)
        assert evaluate_threat(caster, me) > evaluate_threat(fighter, me)
