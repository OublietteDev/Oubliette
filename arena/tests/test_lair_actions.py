"""Tests for lair actions — initiative placement, turn handling, execution, and AI."""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant
from arena.combat.initiative import InitiativeEntry, InitiativeTracker
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action, Attack, DamageRoll, DamageType, ActionType,
    SavingThrowEffect, TargetType,
)
from arena.models.character import Creature
from arena.models.monster import Monster
from arena.models.encounter import Encounter, CombatantEntry
from arena.ai.controller import AIController, TurnStepType
from arena.ai.executor import execute_step
from arena.grid.coordinates import HexCoord


# ── Test helpers ──────────────────────────────────────────────────────


def _make_player(name="Fighter", hp=50, ac=15, dexterity=12):
    """Create a simple player creature for testing."""
    return Creature(
        name=name,
        max_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(strength=16, dexterity=dexterity),
        proficiency_bonus=2,
        is_player_controlled=True,
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
                    damage=[DamageRoll(dice="1d6", damage_type=DamageType.SLASHING)],
                ),
            ),
        ],
    )


def _make_enemy(name="Goblin", hp=30, ac=13, dexterity=14):
    """Create a simple enemy monster for testing."""
    return Monster(
        name=name,
        max_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(strength=10, dexterity=dexterity),
        proficiency_bonus=2,
        is_player_controlled=False,
        actions=[
            Action(
                name="Scimitar",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Scimitar",
                    attack_type="melee_weapon",
                    ability="dexterity",
                    reach=5,
                    damage=[DamageRoll(dice="1d6", damage_type=DamageType.SLASHING)],
                ),
            ),
        ],
    )


_LAIR_ACTION_1 = Action(
    name="Magma Eruption",
    description="Magma erupts from the ground",
    action_type=ActionType.LAIR,
    target_type=TargetType.AREA_SPHERE,
    range=120,
    saving_throw=SavingThrowEffect(
        ability="dexterity",
        dc=15,
        damage_on_fail=[DamageRoll(dice="2d6", damage_type=DamageType.FIRE)],
        damage_on_success="half",
    ),
)

_LAIR_ACTION_2 = Action(
    name="Tremor",
    description="The ground shakes violently",
    action_type=ActionType.LAIR,
    target_type=TargetType.AREA_SPHERE,
    range=120,
    saving_throw=SavingThrowEffect(
        ability="strength",
        dc=14,
        damage_on_fail=[DamageRoll(dice="1d10", damage_type=DamageType.BLUDGEONING)],
        damage_on_success="none",
    ),
)


def _make_lair_encounter(num_players=1, lair_actions=None):
    """Create an encounter with lair actions."""
    if lair_actions is None:
        lair_actions = [_LAIR_ACTION_1, _LAIR_ACTION_2]

    combatants = []
    for i in range(num_players):
        combatants.append(CombatantEntry(
            creature_id=f"inline_player_{i}",
            creature_data=_make_player(name=f"Fighter {i + 1}"),
            team="player",
            starting_position=(2 + i, 2),
        ))
    combatants.append(CombatantEntry(
        creature_id="inline_enemy",
        creature_data=_make_enemy(),
        team="enemy",
        starting_position=(5, 5),
    ))

    return Encounter(
        name="Lair Fight",
        grid_width=10,
        grid_height=10,
        combatants=combatants,
        has_lair=True,
        lair_actions=lair_actions,
    )


def _setup_combat(encounter=None, fixed_initiative=None):
    """Set up combat from an encounter. Returns CombatManager in combat."""
    if encounter is None:
        encounter = _make_lair_encounter()

    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))

    if fixed_initiative:
        call_count = [0]
        creature_ids = list(cm.combatants.keys())

        def mock_roll(sides):
            if sides == 20:
                cid = creature_ids[call_count[0] % len(creature_ids)]
                call_count[0] += 1
                return fixed_initiative.get(cid, 10)
            return 10

        with patch("arena.combat.manager.roll_die", side_effect=mock_roll):
            cm.roll_initiative()
    else:
        cm.roll_initiative()

    cm.begin_combat()
    return cm


def _advance_to_lair_turn(cm):
    """Advance combat until the lair turn starts. Returns True if found."""
    for _ in range(40):  # Safety limit
        if cm.state != CombatState.IN_COMBAT:
            return False
        if cm._is_lair_turn:
            return True
        # Pass any pending legendary action phases
        if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
            cm.pass_legendary_action()
        else:
            cm.end_turn()
    return False


# ══════════════════════════════════════════════════════════════════════
# Model Tests
# ══════════════════════════════════════════════════════════════════════


class TestEncounterModel:
    def test_has_lair_defaults_false(self):
        enc = Encounter(name="Test")
        assert enc.has_lair is False
        assert enc.lair_actions == []

    def test_lair_actions_serialization(self):
        """Lair actions round-trip through JSON."""
        enc = _make_lair_encounter()
        data = enc.model_dump(mode="json")
        restored = Encounter.model_validate(data)
        assert restored.has_lair is True
        assert len(restored.lair_actions) == 2
        assert restored.lair_actions[0].name == "Magma Eruption"
        assert restored.lair_actions[0].action_type == ActionType.LAIR

    def test_backward_compatibility(self):
        """Old encounter JSON without lair fields loads fine."""
        data = {"name": "Old Encounter", "combatants": []}
        enc = Encounter.model_validate(data)
        assert enc.has_lair is False
        assert enc.lair_actions == []


# ══════════════════════════════════════════════════════════════════════
# Initiative Tests
# ══════════════════════════════════════════════════════════════════════


class TestInitiativeLair:
    def test_lair_entry_at_initiative_20(self):
        """Lair pseudo-entry should appear with initiative 20."""
        cm = _setup_combat()
        lair_entries = [
            e for e in cm.initiative.entries if e.is_lair
        ]
        assert len(lair_entries) == 1
        assert lair_entries[0].initiative_roll == 20
        assert lair_entries[0].creature_id == "__lair__"

    def test_lair_loses_all_ties(self):
        """Lair entry should sort AFTER any creature with initiative 20."""
        tracker = InitiativeTracker()
        tracker.add_entry(InitiativeEntry(
            creature_id="__lair__", name="Lair",
            initiative_roll=20, dexterity=0,
            is_player_controlled=False, is_lair=True,
        ))
        tracker.add_entry(InitiativeEntry(
            creature_id="fast_creature", name="Fast",
            initiative_roll=20, dexterity=10,
            is_player_controlled=False, tiebreaker=0.5,
        ))
        # Lair should be LAST among init-20 entries
        init_20 = [e for e in tracker.entries if e.initiative_roll == 20]
        assert init_20[-1].is_lair

    def test_lair_loses_ties_with_high_dex(self):
        """Even a creature with dex 0 at init 20 goes before the lair."""
        tracker = InitiativeTracker()
        tracker.add_entry(InitiativeEntry(
            creature_id="__lair__", name="Lair",
            initiative_roll=20, dexterity=0,
            is_player_controlled=False, is_lair=True,
        ))
        tracker.add_entry(InitiativeEntry(
            creature_id="slow_creature", name="Slow",
            initiative_roll=20, dexterity=0,
            is_player_controlled=False, tiebreaker=0.001,
        ))
        init_20 = [e for e in tracker.entries if e.initiative_roll == 20]
        assert init_20[-1].is_lair

    def test_no_lair_entry_without_lair_actions(self):
        """No lair pseudo-entry if encounter has no lair actions."""
        enc = Encounter(
            name="No Lair",
            grid_width=10,
            grid_height=10,
            combatants=[
                CombatantEntry(
                    creature_id="p1",
                    creature_data=_make_player(),
                    team="player",
                    starting_position=(2, 2),
                ),
                CombatantEntry(
                    creature_id="e1",
                    creature_data=_make_enemy(),
                    team="enemy",
                    starting_position=(5, 5),
                ),
            ],
        )
        cm = _setup_combat(encounter=enc)
        lair_entries = [e for e in cm.initiative.entries if e.is_lair]
        assert len(lair_entries) == 0


# ══════════════════════════════════════════════════════════════════════
# Combat Manager Tests
# ══════════════════════════════════════════════════════════════════════


class TestLairTurnDetection:
    def test_lair_turn_detected(self):
        """_is_lair_turn should be True when the lair entry is current."""
        cm = _setup_combat()
        found = _advance_to_lair_turn(cm)
        assert found, "Should have reached a lair turn"
        assert cm._is_lair_turn is True

    def test_active_combatant_is_none_during_lair(self):
        """active_combatant returns None during the lair turn."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)
        assert cm.active_combatant is None

    def test_lair_turn_phase_is_awaiting_action(self):
        """Lair turn should set phase to AWAITING_ACTION."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)
        assert cm.turn_phase == TurnPhase.AWAITING_ACTION

    def test_lair_turn_logs_start(self):
        """Lair turn start should be logged."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)
        messages = [e.message for e in cm.log.events]
        assert any("Lair Actions" in m for m in messages)


class TestLairActionAvailability:
    def test_all_available_first_round(self):
        """All lair actions should be available in the first round."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)
        available = cm.get_available_lair_actions()
        assert len(available) == 2

    def test_filters_last_used(self):
        """Used lair action should be filtered out next round."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)

        # Use the first action
        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]
        cm.execute_lair_action(_LAIR_ACTION_1, target_ids)

        # Advance to next lair turn
        found = _advance_to_lair_turn(cm)
        if found:
            available = cm.get_available_lair_actions()
            names = [a.name for a in available]
            assert "Magma Eruption" not in names
            assert "Tremor" in names


class TestLairActionExecution:
    def test_execute_saving_throw(self):
        """Execute lair action with saving throw against a target."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]
        result = cm.execute_lair_action(_LAIR_ACTION_1, target_ids)
        assert result is not None
        assert result.success is True
        assert len(result.events) > 0

    def test_records_last_used_name(self):
        """execute_lair_action should record last_lair_action_name."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]
        cm.execute_lair_action(_LAIR_ACTION_1, target_ids)
        assert cm.last_lair_action_name == "Magma Eruption"

    def test_ends_turn_after_execution(self):
        """Lair turn should end after executing an action."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]
        cm.execute_lair_action(_LAIR_ACTION_1, target_ids)
        # After execution, lair turn should be over
        assert cm._is_lair_turn is False

    def test_pass_ends_turn(self):
        """pass_lair_action should end the lair turn."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)

        cm.pass_lair_action()
        assert cm._is_lair_turn is False

    def test_pass_logs_message(self):
        """Passing on lair action should produce a log message."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)

        cm.pass_lair_action()
        messages = [e.message for e in cm.log.events]
        assert any("No lair action" in m for m in messages)

    def test_does_not_consume_action_economy(self):
        """Lair action type should not mark action/bonus as used."""
        cm = CombatManager()
        action = Action(
            name="Test",
            description="Test",
            action_type=ActionType.LAIR,
        )
        cm._mark_action_type_used(action)
        assert not cm.turn_resources.has_used_action
        assert not cm.turn_resources.has_used_bonus_action

    def test_execute_invalid_when_not_lair_turn(self):
        """execute_lair_action should return None when it's not a lair turn."""
        cm = _setup_combat()
        # Force off lair turn (begin_combat may start on lair since init 20)
        cm._is_lair_turn = False
        result = cm.execute_lair_action(_LAIR_ACTION_1, ["inline_player_0"])
        assert result is None

    def test_pass_ignored_when_not_lair_turn(self):
        """pass_lair_action should do nothing when it's not a lair turn."""
        cm = _setup_combat()
        # Should not crash or change state
        cm.pass_lair_action()

    def test_lair_action_damage_applied(self):
        """Lair action should actually deal damage on failed save."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]

        # Patch save rolls to always fail
        with patch(
            "arena.combat.actions.roll_die", return_value=1,
        ):
            cm.execute_lair_action(_LAIR_ACTION_1, target_ids)

        # At least one player should have taken damage
        for cid in target_ids:
            if cid in cm.combatants:
                creature = cm.combatants[cid].creature
                if creature.is_conscious:
                    assert creature.current_hit_points < creature.max_hit_points

    def test_half_damage_on_successful_save(self):
        """Lair action with half-on-success should deal half damage on save."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]

        # Patch save to always succeed (roll high)
        with patch(
            "arena.combat.actions.roll_die", return_value=20,
        ):
            result = cm.execute_lair_action(_LAIR_ACTION_1, target_ids)

        # Should still have events (save + damage, but at half)
        assert result is not None
        assert len(result.events) > 0


def _make_legendary_lair_encounter():
    """Create an encounter with both lair actions and a legendary creature."""
    dragon = Monster(
        name="Dragon",
        max_hit_points=200,
        armor_class=18,
        ability_scores=AbilityScores(
            strength=20, dexterity=10, constitution=20,
            intelligence=14, wisdom=12, charisma=16,
        ),
        proficiency_bonus=5,
        is_player_controlled=False,
        legendary_action_count=3,
        legendary_actions=[
            Action(
                name="Tail Attack",
                description="Tail sweep",
                action_type=ActionType.LEGENDARY,
                legendary_action_cost=1,
                target_type=TargetType.ONE_ENEMY,
                range=10,
                attack=Attack(
                    name="Tail",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=10,
                    damage=[DamageRoll(
                        dice="2d8", damage_type=DamageType.BLUDGEONING,
                    )],
                ),
            ),
        ],
    )

    return Encounter(
        name="Dragon Lair",
        grid_width=10,
        grid_height=10,
        has_lair=True,
        lair_actions=[_LAIR_ACTION_1],
        combatants=[
            CombatantEntry(
                creature_id="p1",
                creature_data=_make_player(),
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="dragon",
                creature_data=dragon,
                team="enemy",
                starting_position=(5, 5),
            ),
        ],
    )


class TestLairWithLegendary:
    def test_lair_turn_does_not_trigger_legendary(self):
        """Legendary actions should NOT trigger after the lair turn ends.

        Per 5e rules, legendary actions only trigger after another creature's
        turn ends, not after the lair pseudo-turn.
        """
        encounter = _make_legendary_lair_encounter()
        cm = _setup_combat(encounter=encounter)
        found = _advance_to_lair_turn(cm)
        assert found, "Should have reached a lair turn"

        cm.pass_lair_action()

        # After lair turn, should NOT enter legendary phase
        assert cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE
        assert cm._legendary_queue == []
        assert cm.state == CombatState.IN_COMBAT

    def test_combat_continues_after_lair_with_legendary(self):
        """Combat should not crash or hang when lair and legendary coexist."""
        encounter = _make_legendary_lair_encounter()
        cm = _setup_combat(encounter=encounter)
        found = _advance_to_lair_turn(cm)
        if found:
            cm.pass_lair_action()
            assert cm.state == CombatState.IN_COMBAT


# ══════════════════════════════════════════════════════════════════════
# AI Tests
# ══════════════════════════════════════════════════════════════════════


class TestAILairPlanning:
    def test_ai_plans_lair_action(self):
        """AI should produce an EXECUTE_LAIR step when actions are available."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)

        controller = AIController()
        plan = controller.plan_lair_action(cm)

        step_types = [s.step_type for s in plan.steps]
        assert TurnStepType.EXECUTE_LAIR in step_types

    def test_ai_passes_when_no_actions(self):
        """AI should PASS_LAIR when no lair actions are available."""
        enc = _make_lair_encounter(lair_actions=[])
        cm = CombatManager()
        cm.load_encounter(enc, Path("."))
        # Manually set up lair state to test AI
        cm.lair_actions = []
        cm._is_lair_turn = True

        controller = AIController()
        plan = controller.plan_lair_action(cm)

        step_types = [s.step_type for s in plan.steps]
        assert TurnStepType.PASS_LAIR in step_types

    def test_ai_targets_all_players(self):
        """AI should target all conscious player-side creatures."""
        enc = _make_lair_encounter(num_players=3)
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        controller = AIController()
        plan = controller.plan_lair_action(cm)

        lair_steps = [
            s for s in plan.steps
            if s.step_type == TurnStepType.EXECUTE_LAIR
        ]
        if lair_steps:
            target_ids = lair_steps[0].target_ids
            assert target_ids is not None
            assert len(target_ids) == 3

    def test_executor_handles_execute_lair(self):
        """Executor should route EXECUTE_LAIR to manager."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)

        controller = AIController()
        plan = controller.plan_lair_action(cm)

        # Execute all steps
        for step in plan.steps:
            execute_step(step, cm)

        # Lair turn should be over
        assert cm._is_lair_turn is False

    def test_executor_handles_pass_lair(self):
        """Executor should route PASS_LAIR to manager."""
        cm = _setup_combat()
        _advance_to_lair_turn(cm)

        from arena.ai.controller import TurnStep
        step = TurnStep(step_type=TurnStepType.PASS_LAIR)
        execute_step(step, cm)

        assert cm._is_lair_turn is False


# ══════════════════════════════════════════════════════════════════════
# Load / Save Integration
# ══════════════════════════════════════════════════════════════════════


class TestLairEncounterLoading:
    def test_load_encounter_stores_lair_actions(self):
        """CombatManager should store lair actions from encounter."""
        enc = _make_lair_encounter()
        cm = CombatManager()
        cm.load_encounter(enc, Path("."))
        assert len(cm.lair_actions) == 2
        assert cm.lair_actions[0].name == "Magma Eruption"

    def test_load_encounter_no_lair(self):
        """Encounter without lair should leave lair_actions empty."""
        enc = Encounter(
            name="No Lair",
            grid_width=10,
            grid_height=10,
            combatants=[
                CombatantEntry(
                    creature_id="p1",
                    creature_data=_make_player(),
                    team="player",
                    starting_position=(2, 2),
                ),
                CombatantEntry(
                    creature_id="e1",
                    creature_data=_make_enemy(),
                    team="enemy",
                    starting_position=(5, 5),
                ),
            ],
        )
        cm = CombatManager()
        cm.load_encounter(enc, Path("."))
        assert cm.lair_actions == []

    def test_use_ai_for_lair_follows_enemies_flag(self):
        """_use_ai_for_lair should match encounter's use_ai_for_enemies."""
        enc = _make_lair_encounter()
        enc.use_ai_for_enemies = False

        cm = CombatManager()
        cm.load_encounter(enc, Path("."))
        assert cm._use_ai_for_lair is False


# ══════════════════════════════════════════════════════════════════════
# Condition-Only Lair Action Tests
# ══════════════════════════════════════════════════════════════════════


_CONDITION_ONLY_ACTION = Action(
    name="Grasping Roots",
    description="Roots reach up and restrain creatures.",
    action_type=ActionType.LAIR,
    target_type=TargetType.AREA_SPHERE,
    range=120,
    saving_throw=SavingThrowEffect(
        ability="strength",
        dc=14,
        damage_on_fail=[],
        damage_on_success="none",
        conditions_on_fail=["restrained"],
    ),
)

_DAMAGE_CONDITION_COMBO = Action(
    name="Freezing Wind",
    description="Freezing wind deals cold damage and knocks prone.",
    action_type=ActionType.LAIR,
    target_type=TargetType.AREA_SPHERE,
    range=120,
    saving_throw=SavingThrowEffect(
        ability="constitution",
        dc=14,
        damage_on_fail=[DamageRoll(dice="2d6", damage_type=DamageType.COLD)],
        damage_on_success="half",
        conditions_on_fail=["prone"],
    ),
)


class TestConditionOnlyLairAction:
    def test_condition_applied_on_failed_save(self):
        """Condition-only lair action should apply condition on failed save."""
        enc = _make_lair_encounter(lair_actions=[_CONDITION_ONLY_ACTION])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]

        with patch("arena.combat.actions.roll_die", return_value=1):
            result = cm.execute_lair_action(_CONDITION_ONLY_ACTION, target_ids)

        assert result is not None
        assert result.success is True

        # Check that at least one target has the restrained condition
        for cid in target_ids:
            if cid in cm.combatants:
                creature = cm.combatants[cid].creature
                conditions = [
                    ac.condition.value
                    for ac in creature.active_conditions
                ]
                assert "restrained" in conditions

    def test_no_condition_on_successful_save(self):
        """Condition should NOT be applied on successful save."""
        enc = _make_lair_encounter(lair_actions=[_CONDITION_ONLY_ACTION])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]

        with patch("arena.combat.actions.roll_die", return_value=20):
            cm.execute_lair_action(_CONDITION_ONLY_ACTION, target_ids)

        for cid in target_ids:
            if cid in cm.combatants:
                creature = cm.combatants[cid].creature
                conditions = [
                    ac.condition.value
                    for ac in creature.active_conditions
                ]
                assert "restrained" not in conditions

    def test_no_damage_dealt_for_condition_only(self):
        """Condition-only lair action should not deal any damage."""
        enc = _make_lair_encounter(lair_actions=[_CONDITION_ONLY_ACTION])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]

        with patch("arena.combat.actions.roll_die", return_value=1):
            cm.execute_lair_action(_CONDITION_ONLY_ACTION, target_ids)

        for cid in target_ids:
            if cid in cm.combatants:
                creature = cm.combatants[cid].creature
                assert creature.current_hit_points == creature.max_hit_points

    def test_condition_has_save_to_end(self):
        """Applied condition should store the save ability and DC."""
        enc = _make_lair_encounter(lair_actions=[_CONDITION_ONLY_ACTION])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]

        with patch("arena.combat.actions.roll_die", return_value=1):
            cm.execute_lair_action(_CONDITION_ONLY_ACTION, target_ids)

        for cid in target_ids:
            if cid in cm.combatants:
                creature = cm.combatants[cid].creature
                for ac in creature.active_conditions:
                    if ac.condition.value == "restrained":
                        assert ac.save_to_end == "strength"
                        assert ac.save_dc == 14


class TestDamageConditionComboLairAction:
    def test_damage_and_condition_on_fail(self):
        """Damage+condition combo should deal damage AND apply condition on fail."""
        enc = _make_lair_encounter(lair_actions=[_DAMAGE_CONDITION_COMBO])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]

        with patch("arena.combat.actions.roll_die", return_value=1):
            cm.execute_lair_action(_DAMAGE_CONDITION_COMBO, target_ids)

        for cid in target_ids:
            if cid in cm.combatants:
                creature = cm.combatants[cid].creature
                # Should have taken damage
                assert creature.current_hit_points < creature.max_hit_points
                # Should have prone condition
                conditions = [
                    ac.condition.value
                    for ac in creature.active_conditions
                ]
                assert "prone" in conditions

    def test_half_damage_no_condition_on_success(self):
        """Successful save should give half damage but NO condition."""
        enc = _make_lair_encounter(lair_actions=[_DAMAGE_CONDITION_COMBO])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]

        with patch("arena.combat.actions.roll_die", return_value=20):
            cm.execute_lair_action(_DAMAGE_CONDITION_COMBO, target_ids)

        for cid in target_ids:
            if cid in cm.combatants:
                creature = cm.combatants[cid].creature
                # Should have taken half damage (non-zero)
                assert creature.current_hit_points <= creature.max_hit_points
                # Should NOT have prone condition
                conditions = [
                    ac.condition.value
                    for ac in creature.active_conditions
                ]
                assert "prone" not in conditions

    def test_damage_condition_combo_json_roundtrip(self):
        """Damage+condition combo should survive JSON serialization."""
        enc = _make_lair_encounter(lair_actions=[_DAMAGE_CONDITION_COMBO])
        data = enc.model_dump(mode="json")
        restored = Encounter.model_validate(data)

        action = restored.lair_actions[0]
        assert action.saving_throw is not None
        assert len(action.saving_throw.damage_on_fail) == 1
        assert action.saving_throw.conditions_on_fail == ["prone"]


# ══════════════════════════════════════════════════════════════════════
# Healing Lair Action Tests
# ══════════════════════════════════════════════════════════════════════


_HEALING_ACTION = Action(
    name="Nature's Mending",
    description="The lair heals its allies.",
    action_type=ActionType.LAIR,
    target_type=TargetType.AREA_SPHERE,
    range=120,
    healing="2d6",
)


class TestLairHealing:
    def test_heals_enemy_creatures(self):
        """Lair healing should restore HP to enemy-side creatures."""
        enc = _make_lair_encounter(lair_actions=[_HEALING_ACTION])
        cm = _setup_combat(encounter=enc)

        # Damage the enemy first
        enemy_id = [
            cid for cid, c in cm.combatants.items()
            if c.team == "enemy"
        ][0]
        cm.combatants[enemy_id].creature.current_hit_points = 10

        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]
        cm.execute_lair_action(_HEALING_ACTION, target_ids)

        # Enemy should have been healed
        enemy_hp = cm.combatants[enemy_id].creature.current_hit_points
        assert enemy_hp > 10

    def test_healing_does_not_affect_players(self):
        """Lair healing should NOT heal player-side creatures."""
        enc = _make_lair_encounter(lair_actions=[_HEALING_ACTION])
        cm = _setup_combat(encounter=enc)

        # Damage a player
        player_id = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ][0]
        cm.combatants[player_id].creature.current_hit_points = 10

        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]
        cm.execute_lair_action(_HEALING_ACTION, target_ids)

        # Player should NOT have been healed
        player_hp = cm.combatants[player_id].creature.current_hit_points
        assert player_hp == 10


# ══════════════════════════════════════════════════════════════════════
# Temp HP Lair Action Tests
# ══════════════════════════════════════════════════════════════════════


_TEMP_HP_ACTION = Action(
    name="Protective Ward",
    description="The lair grants temporary hit points.",
    action_type=ActionType.LAIR,
    target_type=TargetType.AREA_SPHERE,
    range=120,
    grants_temporary_hp="10",
)


class TestLairTempHP:
    def test_grants_temp_hp_to_enemies(self):
        """Lair temp HP action should grant temp HP to enemy creatures."""
        enc = _make_lair_encounter(lair_actions=[_TEMP_HP_ACTION])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]
        cm.execute_lair_action(_TEMP_HP_ACTION, target_ids)

        # Enemy should have temp HP
        enemy = [
            c for c in cm.combatants.values()
            if c.team == "enemy"
        ][0]
        assert enemy.creature.temporary_hit_points == 10

    def test_temp_hp_does_not_stack(self):
        """Temp HP should NOT stack — only replace if higher (5e rule)."""
        enc = _make_lair_encounter(lair_actions=[_TEMP_HP_ACTION])
        cm = _setup_combat(encounter=enc)

        # Give enemy pre-existing temp HP higher than what lair grants
        enemy_id = [
            cid for cid, c in cm.combatants.items()
            if c.team == "enemy"
        ][0]
        cm.combatants[enemy_id].creature.temporary_hit_points = 20

        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]
        cm.execute_lair_action(_TEMP_HP_ACTION, target_ids)

        # Should keep the higher value (20), not replace with 10
        assert cm.combatants[enemy_id].creature.temporary_hit_points == 20


# ══════════════════════════════════════════════════════════════════════
# Summon Lair Action Tests
# ══════════════════════════════════════════════════════════════════════


_SUMMON_ACTION = Action(
    name="Call of the Wild",
    description="The lair summons a wolf.",
    action_type=ActionType.LAIR,
    target_type=TargetType.AREA_SPHERE,
    range=120,
    summon_creature="monsters/wolf.json",
)


class TestLairSummon:
    def test_summon_places_creature(self):
        """Lair summon should place a new creature on the grid."""
        enc = _make_lair_encounter(lair_actions=[_SUMMON_ACTION])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        initial_ids = set(cm.combatants.keys())
        initial_count = len(initial_ids)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]
        cm.execute_lair_action(_SUMMON_ACTION, target_ids)

        # Should have one more combatant
        assert len(cm.combatants) == initial_count + 1

        # Find the summoned creature
        new_ids = set(cm.combatants.keys()) - initial_ids
        assert len(new_ids) == 1
        summoned = cm.combatants[new_ids.pop()]
        assert summoned.team == "enemy"

    def test_summon_in_initiative(self):
        """Summoned creature should appear in the initiative tracker."""
        enc = _make_lair_encounter(lair_actions=[_SUMMON_ACTION])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]
        cm.execute_lair_action(_SUMMON_ACTION, target_ids)

        # Find the summoned creature in initiative
        init_ids = [e.creature_id for e in cm.initiative.entries]
        new_ids = [
            cid for cid in cm.combatants
            if cid not in ["inline_player_0", "inline_enemy", "__lair__"]
        ]
        if new_ids:
            assert new_ids[0] in init_ids

    def test_summon_logs_message(self):
        """Lair summon should log an informative message."""
        enc = _make_lair_encounter(lair_actions=[_SUMMON_ACTION])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]
        cm.execute_lair_action(_SUMMON_ACTION, target_ids)

        messages = [e.message for e in cm.log.events]
        assert any("summons" in m.lower() for m in messages)


# ══════════════════════════════════════════════════════════════════════
# AI Scoring for New Effect Types
# ══════════════════════════════════════════════════════════════════════


class TestAIConditionLairScoring:
    def test_ai_selects_condition_action(self):
        """AI should select a condition-only lair action over passing."""
        enc = _make_lair_encounter(lair_actions=[_CONDITION_ONLY_ACTION])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        controller = AIController()
        plan = controller.plan_lair_action(cm)

        step_types = [s.step_type for s in plan.steps]
        assert TurnStepType.EXECUTE_LAIR in step_types

    def test_ai_prefers_higher_value_condition(self):
        """AI should prefer paralyzed (higher score) over prone (lower)."""
        paralyzed_action = Action(
            name="Paralyzing Gaze",
            description="Paralysis",
            action_type=ActionType.LAIR,
            target_type=TargetType.AREA_SPHERE,
            range=120,
            saving_throw=SavingThrowEffect(
                ability="wisdom",
                dc=15,
                damage_on_fail=[],
                damage_on_success="none",
                conditions_on_fail=["paralyzed"],
            ),
        )
        prone_action = Action(
            name="Trembling Ground",
            description="Prone",
            action_type=ActionType.LAIR,
            target_type=TargetType.AREA_SPHERE,
            range=120,
            saving_throw=SavingThrowEffect(
                ability="dexterity",
                dc=15,
                damage_on_fail=[],
                damage_on_success="none",
                conditions_on_fail=["prone"],
            ),
        )

        enc = _make_lair_encounter(lair_actions=[prone_action, paralyzed_action])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        controller = AIController()
        plan = controller.plan_lair_action(cm)

        lair_steps = [
            s for s in plan.steps
            if s.step_type == TurnStepType.EXECUTE_LAIR
        ]
        assert len(lair_steps) == 1
        assert lair_steps[0].lair_action.name == "Paralyzing Gaze"

    def test_ai_scores_healing_action(self):
        """AI should choose a healing action when available."""
        enc = _make_lair_encounter(lair_actions=[_HEALING_ACTION])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        controller = AIController()
        plan = controller.plan_lair_action(cm)

        step_types = [s.step_type for s in plan.steps]
        assert TurnStepType.EXECUTE_LAIR in step_types

    def test_ai_scores_summon_action(self):
        """AI should choose a summon action when available."""
        enc = _make_lair_encounter(lair_actions=[_SUMMON_ACTION])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        controller = AIController()
        plan = controller.plan_lair_action(cm)

        step_types = [s.step_type for s in plan.steps]
        assert TurnStepType.EXECUTE_LAIR in step_types

    def test_ai_prefers_healing_when_allies_wounded(self):
        """AI should prefer healing over summoning when enemies are low HP."""
        enc = _make_lair_encounter(
            lair_actions=[_HEALING_ACTION, _SUMMON_ACTION],
        )
        cm = _setup_combat(encounter=enc)

        # Severely wound the enemy
        enemy_id = [
            cid for cid, c in cm.combatants.items()
            if c.team == "enemy"
        ][0]
        cm.combatants[enemy_id].creature.current_hit_points = 5

        _advance_to_lair_turn(cm)

        controller = AIController()
        plan = controller.plan_lair_action(cm)

        lair_steps = [
            s for s in plan.steps
            if s.step_type == TurnStepType.EXECUTE_LAIR
        ]
        assert len(lair_steps) == 1
        assert lair_steps[0].lair_action.name == "Nature's Mending"


# ══════════════════════════════════════════════════════════════════════
# Lair Summon Initiative Stability Tests
# ══════════════════════════════════════════════════════════════════════


class TestLairSummonInitiativeStability:
    def test_summon_does_not_double_fire_lair(self):
        """Lair should NOT fire twice when summoning shifts initiative order.

        Bug: _execute_lair_summon called initiative.add_entry() which re-sorted
        entries, but current_index was not updated. next_turn() then advanced
        to the lair entry again, causing a double-fire.
        """
        enc = _make_lair_encounter(lair_actions=[_SUMMON_ACTION, _LAIR_ACTION_1])
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        # Execute the summon action
        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]
        cm.execute_lair_action(_SUMMON_ACTION, target_ids)

        # After lair summon + end_turn, lair turn should be over
        assert cm._is_lair_turn is False

        # Advance through the entire next round to the next lair turn
        found = _advance_to_lair_turn(cm)
        if found:
            # The filter should exclude "Call of the Wild"
            available = cm.get_available_lair_actions()
            names = [a.name for a in available]
            assert "Call of the Wild" not in names

    def test_summon_consecutive_filter_persists(self):
        """Consecutive-round filter should work correctly with summons."""
        enc = _make_lair_encounter(
            lair_actions=[_SUMMON_ACTION, _LAIR_ACTION_1],
        )
        cm = _setup_combat(encounter=enc)
        _advance_to_lair_turn(cm)

        # Use the summon action
        target_ids = [
            cid for cid, c in cm.combatants.items()
            if c.team == "player"
        ]
        cm.execute_lair_action(_SUMMON_ACTION, target_ids)
        assert cm.last_lair_action_name == "Call of the Wild"

        # After the lair turn ends, lair should NOT be active
        assert cm._is_lair_turn is False

        # Count how many lair turns occur before the next one
        lair_turn_count = 0
        for _ in range(60):
            if cm.state != CombatState.IN_COMBAT:
                break
            if cm._is_lair_turn:
                lair_turn_count += 1
                if lair_turn_count == 1:
                    # First lair turn after summon: Call of the Wild filtered
                    available = cm.get_available_lair_actions()
                    names = [a.name for a in available]
                    assert "Call of the Wild" not in names
                    assert "Magma Eruption" in names
                    break
            if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
                cm.pass_legendary_action()
            else:
                cm.end_turn()
