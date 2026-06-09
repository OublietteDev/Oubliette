"""Tests for Phase 6c: Action scoring system."""

import pytest

from arena.ai.scoring import (
    ScoredAction,
    score_attack_action,
    score_healing_action,
    score_standard_action,
    generate_scored_actions,
    check_use_condition,
    estimate_damage,
)
from arena.ai.behavior import AIProfile
from arena.ai.context import CreatureView, CombatContext
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.grid.coordinates import HexCoord


def _view(
    cid="c1", team="enemy", pos=(5, 5), hp=1.0, conscious=True, ac=10,
    concentration=False, caster=False, max_hp=20, speed=30, actions=1,
):
    cur_hp = int(max_hp * hp)
    return CreatureView(
        creature_id=cid, team=team, position=HexCoord(*pos) if pos else None,
        hp_percent=hp, is_conscious=conscious, armor_class=ac,
        has_concentration=concentration, is_spellcaster=caster,
        condition_names=(), max_hit_points=max_hp, current_hit_points=cur_hp,
        speed=speed, actions_count=actions,
    )


def _context(me, enemies=(), allies=(), movement=30, action_used=False, bonus_used=False):
    all_c = (me,) + tuple(allies) + tuple(enemies)
    return CombatContext(
        me=me, allies=tuple(allies), enemies=tuple(enemies),
        all_combatants=all_c, grid_width=20, grid_height=15,
        round_number=1, remaining_movement=movement,
        has_used_action=action_used, has_used_bonus_action=bonus_used,
    )


def _melee_action(name="Sword", priority=5, dice="1d6", damage_type=DamageType.SLASHING):
    return Action(
        name=name, description="Melee attack", action_type=ActionType.ACTION,
        attack=Attack(
            name=name, attack_type="melee_weapon", ability="strength", reach=5,
            damage=[DamageRoll(dice=dice, damage_type=damage_type, ability_modifier="strength")],
        ),
        ai_priority=priority,
    )


def _ranged_action(name="Bow", priority=5, dice="1d8", range_normal=80):
    return Action(
        name=name, description="Ranged attack", action_type=ActionType.ACTION,
        attack=Attack(
            name=name, attack_type="ranged_weapon", ability="dexterity",
            range_normal=range_normal,
            damage=[DamageRoll(dice=dice, damage_type=DamageType.PIERCING, ability_modifier="dexterity")],
        ),
        ai_priority=priority,
    )


def _healing_action(name="Heal", priority=5, healing="2d8+3"):
    return Action(
        name=name, description="Healing", action_type=ActionType.ACTION,
        healing=healing, ai_priority=priority,
    )


# ── score_attack_action ─────────────────────────────────────────────

class TestScoreAttackAction:
    def test_higher_priority_gives_higher_score(self):
        profile = AIProfile(name="test")
        me = _view(cid="me", team="player", pos=(0, 0))
        target = _view(cid="t", pos=(1, 0))
        ctx = _context(me, enemies=[target])
        low = _melee_action("Low", priority=2)
        high = _melee_action("High", priority=8)
        assert score_attack_action(high, profile, ctx, target, 1) > \
               score_attack_action(low, profile, ctx, target, 1)

    def test_aggression_multiplier(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        target = _view(cid="t", pos=(1, 0))
        ctx = _context(me, enemies=[target])
        action = _melee_action()
        aggressive = AIProfile(name="agg", aggression=1.8)
        passive = AIProfile(name="pas", aggression=0.5)
        assert score_attack_action(action, aggressive, ctx, target, 1) > \
               score_attack_action(action, passive, ctx, target, 1)

    def test_out_of_range_penalty(self):
        profile = AIProfile(name="test")
        me = _view(cid="me", team="player", pos=(0, 0))
        close = _view(cid="close", pos=(1, 0))
        far = _view(cid="far", pos=(8, 0))
        ctx = _context(me, enemies=[close, far])
        action = _melee_action()  # reach 5ft = 1 hex
        score_close = score_attack_action(action, profile, ctx, close, 1)
        score_far = score_attack_action(action, profile, ctx, far, 8)
        assert score_close > score_far

    def test_melee_profile_prefers_melee_action(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        target = _view(cid="t", pos=(1, 0))
        ctx = _context(me, enemies=[target])
        melee_prof = AIProfile(name="melee", prefers_melee=True)
        melee_act = _melee_action()
        ranged_act = _ranged_action()
        # Melee profile should prefer melee when adjacent
        s_melee = score_attack_action(melee_act, melee_prof, ctx, target, 1)
        s_ranged = score_attack_action(ranged_act, melee_prof, ctx, target, 1)
        assert s_melee > s_ranged


# ── score_healing_action ─────────────────────────────────────────────

class TestScoreHealingAction:
    def test_lower_ally_hp_gives_higher_score(self):
        profile = AIProfile(name="test", protects_allies=True)
        me = _view(cid="me", team="player", pos=(0, 0))
        wounded = _view(cid="ally", team="player", pos=(1, 0), hp=0.2)
        healthy = _view(cid="ally2", team="player", pos=(1, 0), hp=0.9)
        ctx = _context(me, allies=[wounded, healthy])
        action = _healing_action()
        assert score_healing_action(action, profile, ctx, wounded) > \
               score_healing_action(action, profile, ctx, healthy)

    def test_protects_allies_weight(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        wounded = _view(cid="ally", team="player", pos=(1, 0), hp=0.3)
        ctx = _context(me, allies=[wounded])
        action = _healing_action()
        protector = AIProfile(name="prot", protects_allies=True)
        selfish = AIProfile(name="self", protects_allies=False)
        assert score_healing_action(action, protector, ctx, wounded) > \
               score_healing_action(action, selfish, ctx, wounded)

    def test_self_healing_uses_self_preservation(self):
        me = _view(cid="me", team="player", pos=(0, 0), hp=0.3)
        ctx = _context(me)
        action = _healing_action()
        cautious = AIProfile(name="caut", self_preservation=1.5)
        reckless = AIProfile(name="reck", self_preservation=0.3)
        assert score_healing_action(action, cautious, ctx, me) > \
               score_healing_action(action, reckless, ctx, me)


# ── score_standard_action ───────────────────────────────────────────

class TestScoreStandardAction:
    def test_dash_high_when_melee_far_from_enemies(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        enemy = _view(cid="e", pos=(8, 0))
        ctx = _context(me, enemies=[enemy])
        profile = AIProfile(name="melee", prefers_melee=True)
        score = score_standard_action("dash", profile, ctx)
        assert score > 30  # should be significant

    def test_dodge_high_when_low_hp(self):
        me = _view(cid="me", team="player", pos=(0, 0), hp=0.2)
        ctx = _context(me)
        profile = AIProfile(name="cautious", self_preservation=1.5)
        score = score_standard_action("dodge", profile, ctx)
        assert score > 15

    def test_dodge_low_when_full_hp(self):
        me = _view(cid="me", team="player", pos=(0, 0), hp=1.0)
        ctx = _context(me)
        profile = AIProfile(name="test")
        score = score_standard_action("dodge", profile, ctx)
        assert score < 5

    def test_disengage_high_when_in_melee_for_ranged(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        enemy = _view(cid="e", pos=(1, 0))  # adjacent
        ctx = _context(me, enemies=[enemy])
        profile = AIProfile(name="archer", prefers_melee=False, avoids_opportunity_attacks=True,
                            maintains_distance=60)
        score = score_standard_action("disengage", profile, ctx)
        assert score > 20

    def test_disengage_zero_when_not_in_melee(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        enemy = _view(cid="e", pos=(5, 5))
        ctx = _context(me, enemies=[enemy])
        profile = AIProfile(name="test", avoids_opportunity_attacks=True)
        score = score_standard_action("disengage", profile, ctx)
        assert score == 0.0


# ── generate_scored_actions ──────────────────────────────────────────

class TestGenerateScoredActions:
    def test_returns_sorted_by_score(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        enemy = _view(cid="e", pos=(1, 0))
        ctx = _context(me, enemies=[enemy])
        profile = AIProfile(name="test")
        actions = [_melee_action()]
        scored = generate_scored_actions(
            profile, ctx, actions, [], True, False, False, {"e": 1}
        )
        for i in range(len(scored) - 1):
            assert scored[i].score >= scored[i + 1].score

    def test_includes_standard_actions(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        ctx = _context(me)
        profile = AIProfile(name="test")
        scored = generate_scored_actions(
            profile, ctx, [], [], True, False, False, {}
        )
        names = [s.action_name for s in scored]
        assert "dash" in names
        assert "dodge" in names

    def test_skips_when_action_slot_used(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        enemy = _view(cid="e", pos=(1, 0))
        ctx = _context(me, enemies=[enemy])
        profile = AIProfile(name="test")
        actions = [_melee_action()]
        scored = generate_scored_actions(
            profile, ctx, actions, [], False, False, False, {"e": 1}
        )
        attack_actions = [s for s in scored if s.action_category == "attack"]
        assert len(attack_actions) == 0

    def test_includes_twf_when_eligible(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        enemy = _view(cid="e", pos=(1, 0))
        ctx = _context(me, enemies=[enemy])
        profile = AIProfile(name="test")
        scored = generate_scored_actions(
            profile, ctx, [], [], False, True, True, {"e": 1}
        )
        bonus = [s for s in scored if s.action_category == "bonus_attack"]
        assert len(bonus) == 1

    def test_respects_ai_use_condition(self):
        me = _view(cid="me", team="player", pos=(0, 0), hp=0.8)
        enemy = _view(cid="e", pos=(1, 0))
        ctx = _context(me, enemies=[enemy])
        profile = AIProfile(name="test")
        action = _melee_action()
        action.ai_use_condition = "self.hp_percent < 50"
        scored = generate_scored_actions(
            profile, ctx, [action], [], True, False, False, {"e": 1}
        )
        attack_actions = [s for s in scored if s.action_category == "attack"]
        assert len(attack_actions) == 0  # condition not met (hp=80%)


# ── check_use_condition ──────────────────────────────────────────────

class TestCheckUseCondition:
    def test_returns_true_when_no_condition(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        ctx = _context(me)
        assert check_use_condition(None, ctx) is True

    def test_evaluates_hp_percent_met(self):
        me = _view(cid="me", team="player", pos=(0, 0), hp=0.3)
        ctx = _context(me)
        assert check_use_condition("self.hp_percent < 50", ctx) is True

    def test_evaluates_hp_percent_not_met(self):
        me = _view(cid="me", team="player", pos=(0, 0), hp=0.8)
        ctx = _context(me)
        assert check_use_condition("self.hp_percent < 50", ctx) is False

    def test_handles_malformed_gracefully(self):
        me = _view(cid="me", team="player", pos=(0, 0))
        ctx = _context(me)
        # Malformed should return True (default allow)
        assert check_use_condition("invalid_gibberish!!!", ctx) is True


# ── estimate_damage ──────────────────────────────────────────────────

class TestEstimateDamage:
    def test_1d6_averages_3_5(self):
        action = _melee_action(dice="1d6")
        assert estimate_damage(action) == pytest.approx(3.5)

    def test_2d8_plus_3_averages_12(self):
        action = Action(
            name="Big Hit", description="test", action_type=ActionType.ACTION,
            attack=Attack(
                name="Big Hit", attack_type="melee_weapon", ability="strength",
                damage=[DamageRoll(dice="2d8", damage_type=DamageType.BLUDGEONING, bonus=3)],
            ),
        )
        assert estimate_damage(action) == pytest.approx(12.0)

    def test_no_attack_returns_zero(self):
        action = _healing_action()
        assert estimate_damage(action) == 0.0

    def test_multiple_damage_rolls(self):
        action = Action(
            name="Multi", description="test", action_type=ActionType.ACTION,
            attack=Attack(
                name="Multi", attack_type="melee_weapon", ability="strength",
                damage=[
                    DamageRoll(dice="1d6", damage_type=DamageType.SLASHING),
                    DamageRoll(dice="1d6", damage_type=DamageType.FIRE, bonus=2),
                ],
            ),
        )
        assert estimate_damage(action) == pytest.approx(9.0)  # 3.5 + 3.5 + 2
