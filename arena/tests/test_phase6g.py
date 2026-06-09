"""Tests for Phase 6g: AI Controller orchestrator."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from arena.ai.controller import (
    AIController,
    TurnPlan,
    TurnStep,
    TurnStepType,
)
from arena.ai.behavior import AIProfile, DEFAULT_PROFILES
from arena.ai.context import CreatureView, CombatContext
from arena.ai.scoring import ScoredAction
from arena.grid.coordinates import HexCoord
from arena.combat.manager import CombatManager, CombatState, Combatant
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.encounter import Encounter, CombatantEntry


# ── Helpers ─────────────────────────────────────────────────────────


def _view(cid="c1", team="enemy", pos=(5, 5), hp=1.0, max_hp=20):
    cur_hp = int(max_hp * hp)
    return CreatureView(
        creature_id=cid, team=team,
        position=HexCoord(*pos), hp_percent=hp, is_conscious=True,
        armor_class=10, has_concentration=False, is_spellcaster=False,
        condition_names=(), max_hit_points=max_hp, current_hit_points=cur_hp,
        speed=30, actions_count=1,
    )


def _context(me, enemies=(), allies=(), movement=30, action_used=False, bonus_used=False):
    all_c = (me,) + tuple(allies) + tuple(enemies)
    return CombatContext(
        me=me, allies=tuple(allies), enemies=tuple(enemies),
        all_combatants=all_c, grid_width=20, grid_height=15,
        round_number=1, remaining_movement=movement,
        has_used_action=action_used, has_used_bonus_action=bonus_used,
    )


def _make_creature(name, hp, ac=10, strength=10, dexterity=10, is_player=True,
                   ai_profile="default_monster"):
    return Creature(
        name=name,
        max_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(strength=strength, dexterity=dexterity),
        proficiency_bonus=2,
        is_player_controlled=is_player,
        ai_profile=ai_profile,
        actions=[
            Action(
                name="Sword",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Sword",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=5,
                    damage=[
                        DamageRoll(
                            dice="1d6",
                            damage_type=DamageType.SLASHING,
                            ability_modifier="strength",
                        )
                    ],
                ),
            )
        ],
    )


def _make_encounter(player_pos=(2, 2), enemy_pos=(3, 2), enemy_ai="default_monster"):
    return Encounter(
        name="Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="inline_player",
                creature_data=_make_creature("Fighter", hp=20, ac=15, strength=16,
                                             is_player=True),
                team="player",
                starting_position=player_pos,
            ),
            CombatantEntry(
                creature_id="inline_enemy",
                creature_data=_make_creature("Goblin", hp=7, ac=13, dexterity=14,
                                             is_player=False, ai_profile=enemy_ai),
                team="enemy",
                starting_position=enemy_pos,
            ),
        ],
    )


def _start_combat(encounter=None, seed=42):
    """Start combat and ensure the enemy goes first (for AI testing)."""
    if encounter is None:
        encounter = _make_encounter()
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))

    # Use deterministic initiative: force enemy first
    with patch("arena.combat.manager.roll_die", return_value=10):
        cm.roll_initiative()

    # Sort so enemy goes first by manipulating entries
    entries = cm.initiative.entries
    enemy_entry = None
    player_entry = None
    for e in entries:
        if cm.combatants[e.creature_id].team == "enemy":
            enemy_entry = e
        else:
            player_entry = e

    if enemy_entry and player_entry:
        # Force enemy to have higher initiative
        enemy_entry.initiative_roll = 20
        player_entry.initiative_roll = 5
        cm.initiative.entries.sort(
            key=lambda x: (-x.initiative_roll, -x.dexterity)
        )

    cm.begin_combat()
    return cm


# ── TurnPlan / TurnStep ────────────────────────────────────────────


class TestTurnPlanCreation:
    def test_empty_plan(self):
        plan = TurnPlan()
        assert plan.steps == []
        assert plan.thinking_log == []

    def test_plan_with_steps(self):
        plan = TurnPlan(steps=[
            TurnStep(step_type=TurnStepType.MOVE, target_hex=(3, 4)),
            TurnStep(step_type=TurnStepType.END_TURN),
        ])
        assert len(plan.steps) == 2
        assert plan.steps[0].step_type == TurnStepType.MOVE
        assert plan.steps[0].target_hex == (3, 4)

    def test_step_types(self):
        assert TurnStepType.MOVE.name == "MOVE"
        assert TurnStepType.SELECT_ACTION.name == "SELECT_ACTION"
        assert TurnStepType.EXECUTE_ATTACK.name == "EXECUTE_ATTACK"
        assert TurnStepType.STANDARD_ACTION.name == "STANDARD_ACTION"
        assert TurnStepType.BONUS_ATTACK.name == "BONUS_ATTACK"
        assert TurnStepType.END_TURN.name == "END_TURN"
        assert TurnStepType.LOG_THINKING.name == "LOG_THINKING"


# ── AIController basics ────────────────────────────────────────────


class TestAIControllerInit:
    def test_default_randomness(self):
        controller = AIController()
        assert controller.randomness == 0.1

    def test_custom_randomness(self):
        controller = AIController(randomness=0.0)
        assert controller.randomness == 0.0

    def test_deterministic_mode(self):
        controller = AIController(randomness=0.0)
        assert controller.randomness == 0.0


# ── Profile resolution ─────────────────────────────────────────────


class TestGetProfile:
    def test_resolves_default_monster(self):
        controller = AIController()
        creature = _make_creature("Goblin", hp=7, is_player=False,
                                  ai_profile="default_monster")
        combatant = Combatant(
            creature_id="goblin_1", creature=creature,
            team="enemy", position=HexCoord(3, 2),
        )
        profile = controller._get_profile(combatant)
        assert profile.name == "Default Monster"

    def test_resolves_berserker(self):
        controller = AIController()
        creature = _make_creature("Orc", hp=15, is_player=False,
                                  ai_profile="berserker")
        combatant = Combatant(
            creature_id="orc_1", creature=creature,
            team="enemy", position=HexCoord(3, 2),
        )
        profile = controller._get_profile(combatant)
        assert profile.name == "Berserker"

    def test_unknown_profile_falls_back(self):
        controller = AIController()
        creature = _make_creature("Mystery", hp=10, is_player=False,
                                  ai_profile="nonexistent_profile")
        combatant = Combatant(
            creature_id="mystery_1", creature=creature,
            team="enemy", position=HexCoord(3, 2),
        )
        profile = controller._get_profile(combatant)
        assert profile.name == "Default Monster"


# ── plan_turn integration ──────────────────────────────────────────


class TestPlanTurn:
    def test_returns_turn_plan(self):
        cm = _start_combat()
        controller = AIController(randomness=0.0)
        plan = controller.plan_turn(cm)
        assert isinstance(plan, TurnPlan)
        assert len(plan.steps) > 0

    def test_plan_ends_with_end_turn(self):
        cm = _start_combat()
        controller = AIController(randomness=0.0)
        plan = controller.plan_turn(cm)
        assert plan.steps[-1].step_type == TurnStepType.END_TURN

    def test_plan_has_thinking_log(self):
        cm = _start_combat()
        controller = AIController(randomness=0.0)
        plan = controller.plan_turn(cm)
        assert len(plan.thinking_log) > 0

    def test_plan_includes_attack_against_adjacent_enemy(self):
        """Enemy adjacent to player should plan an attack."""
        cm = _start_combat()
        controller = AIController(randomness=0.0)

        # Verify active combatant is enemy
        active = cm.active_combatant
        assert active is not None
        assert active.team == "enemy"

        plan = controller.plan_turn(cm)
        attack_steps = [
            s for s in plan.steps
            if s.step_type == TurnStepType.EXECUTE_ATTACK
        ]
        assert len(attack_steps) >= 1

    def test_plan_includes_select_action_before_attack(self):
        cm = _start_combat()
        controller = AIController(randomness=0.0)
        plan = controller.plan_turn(cm)

        # Find SELECT_ACTION and EXECUTE_ATTACK — SELECT should come first
        select_idx = None
        attack_idx = None
        for i, s in enumerate(plan.steps):
            if s.step_type == TurnStepType.SELECT_ACTION and select_idx is None:
                select_idx = i
            if s.step_type == TurnStepType.EXECUTE_ATTACK and attack_idx is None:
                attack_idx = i

        if select_idx is not None and attack_idx is not None:
            assert select_idx < attack_idx

    def test_no_active_combatant_returns_end_turn_only(self):
        cm = CombatManager()
        controller = AIController()
        plan = controller.plan_turn(cm)
        assert len(plan.steps) == 1
        assert plan.steps[0].step_type == TurnStepType.END_TURN


# ── Retreat planning ───────────────────────────────────────────────


class TestPlanRetreat:
    def test_coward_retreats_when_low_hp(self):
        """Coward profile should retreat when HP is low."""
        encounter = _make_encounter(
            player_pos=(2, 2),
            enemy_pos=(3, 2),
            enemy_ai="coward",
        )
        cm = _start_combat(encounter)
        controller = AIController(randomness=0.0)

        # Make the enemy (active combatant) very low HP
        active = cm.active_combatant
        assert active is not None
        active.creature.current_hit_points = 1  # Very low

        plan = controller.plan_turn(cm)

        # Should have a Disengage standard action
        disengage_steps = [
            s for s in plan.steps
            if s.step_type == TurnStepType.STANDARD_ACTION
            and s.action_name == "disengage"
        ]
        assert len(disengage_steps) >= 1

    def test_berserker_does_not_retreat_when_low_hp(self):
        """Berserker profile should never retreat."""
        encounter = _make_encounter(
            player_pos=(2, 2),
            enemy_pos=(3, 2),
            enemy_ai="berserker",
        )
        cm = _start_combat(encounter)
        controller = AIController(randomness=0.0)

        # Make berserker low HP
        active = cm.active_combatant
        assert active is not None
        active.creature.current_hit_points = 1

        plan = controller.plan_turn(cm)

        # Should NOT have a disengage for retreat
        disengage_steps = [
            s for s in plan.steps
            if s.step_type == TurnStepType.STANDARD_ACTION
            and s.action_name == "disengage"
        ]
        # Berserker has will_flee=False, so no retreat
        assert len(disengage_steps) == 0


# ── Distance map ───────────────────────────────────────────────────


class TestBuildDistanceMap:
    def test_builds_distances(self):
        controller = AIController()
        me = _view(cid="me", team="player", pos=(0, 0))
        e1 = _view(cid="e1", pos=(1, 0))
        e2 = _view(cid="e2", pos=(3, 0))
        ctx = _context(me, enemies=[e1, e2])
        distances = controller._build_distance_map(ctx)
        assert "e1" in distances
        assert "e2" in distances
        assert distances["e1"] < distances["e2"]

    def test_empty_enemies(self):
        controller = AIController()
        me = _view(cid="me", team="player", pos=(0, 0))
        ctx = _context(me, enemies=[])
        distances = controller._build_distance_map(ctx)
        assert distances == {}


# ── Noise application ──────────────────────────────────────────────


class TestApplyNoise:
    def test_zero_randomness_preserves_order(self):
        controller = AIController(randomness=0.0)
        scored = [
            ScoredAction("Sword", "e1", 80.0, "attack", "Sword -> e1"),
            ScoredAction("Bow", "e1", 40.0, "attack", "Bow -> e1"),
        ]
        result = controller._apply_noise(scored)
        assert result[0].score >= result[1].score
        # With zero randomness, scores should be unchanged
        assert result[0].score == 80.0
        assert result[1].score == 40.0

    def test_noise_still_sorts(self):
        controller = AIController(randomness=0.5)
        scored = [
            ScoredAction("A", "e1", 100.0, "attack", "A"),
            ScoredAction("B", "e1", 50.0, "attack", "B"),
            ScoredAction("C", "e1", 10.0, "attack", "C"),
        ]
        result = controller._apply_noise(scored)
        # Should still be sorted descending
        for i in range(len(result) - 1):
            assert result[i].score >= result[i + 1].score


# ── Focus fire boost ───────────────────────────────────────────────


class TestBoostFocusTarget:
    def test_boosts_focus_target_attacks(self):
        controller = AIController()
        scored = [
            ScoredAction("Sword", "e1", 80.0, "attack", "Sword -> e1"),
            ScoredAction("Sword", "e2", 70.0, "attack", "Sword -> e2"),
        ]
        result = controller._boost_focus_target(scored, "e2")
        # e2 should now be boosted above e1
        assert result[0].target_id == "e2"
        assert result[0].score == 120.0  # 70 + 50

    def test_no_boost_for_non_attack(self):
        controller = AIController()
        scored = [
            ScoredAction("dash", None, 30.0, "standard", "Dash"),
        ]
        result = controller._boost_focus_target(scored, "e1")
        assert result[0].score == 30.0


# ── Filter limited abilities ──────────────────────────────────────


class TestFilterLimited:
    def test_standard_actions_always_kept(self):
        controller = AIController()
        me = _view(cid="me", team="player", pos=(0, 0))
        ctx = _context(me)
        profile = AIProfile(name="test", uses_limited_abilities=0.0)
        creature = _make_creature("Test", hp=10)

        scored = [
            ScoredAction("dash", None, 30.0, "standard", "Dash"),
            ScoredAction("dodge", None, 10.0, "standard", "Dodge"),
        ]
        result = controller._filter_limited_abilities(
            scored, creature, profile, ctx
        )
        assert len(result) == 2

    def test_unlimited_actions_kept(self):
        controller = AIController()
        me = _view(cid="me", team="player", pos=(0, 0))
        ctx = _context(me)
        profile = AIProfile(name="test")
        creature = _make_creature("Test", hp=10)

        scored = [
            ScoredAction("Sword", "e1", 80.0, "attack", "Sword -> e1"),
        ]
        result = controller._filter_limited_abilities(
            scored, creature, profile, ctx
        )
        assert len(result) == 1
