"""Tests for resolve_effect() and the execute_effect() combat flow.

Covers healing, saving throws, conditions, use tracking, self-targeting,
and the manager-level execute_effect() method.
"""

import pytest
from unittest.mock import patch

from arena.models.character import Creature
from arena.models.actions import (
    Action, ActionType, TargetType,
    SavingThrowEffect, DamageRoll, DamageType,
)
from arena.combat.actions import resolve_effect, ActionResult
from arena.combat.damage import DamagePacket
from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant
from arena.combat.events import CombatEventType
from arena.grid.hexgrid import HexGrid
from arena.grid.coordinates import HexCoord


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_creature(
    name: str = "Tester",
    hp: int = 20,
    max_hp: int = 20,
    ac: int = 10,
) -> Creature:
    """Create a minimal creature for testing."""
    return Creature(
        name=name,
        size="medium",
        creature_type="humanoid",
        ability_scores={
            "strength": 10, "dexterity": 10, "constitution": 10,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
        },
        armor_class=ac,
        max_hit_points=max_hp,
        current_hit_points=hp,
        speed={"walk": 30},
        proficiency_bonus=2,
    )


def _make_grid() -> HexGrid:
    grid = HexGrid(10, 10)
    return grid


def _healing_action(healing_expr: str = "2d4+2", uses: int | None = None) -> Action:
    return Action(
        name="Healing Potion",
        description="Drink a healing potion.",
        action_type=ActionType.BONUS_ACTION,
        target_type=TargetType.SELF,
        range=0,
        healing=healing_expr,
        uses_per_rest=uses,
        source_item="Healing Potion",
    )


def _save_damage_action(
    dc: int = 13,
    ability: str = "dexterity",
    damage_on_success: str = "half",
) -> Action:
    return Action(
        name="Fire Scroll",
        description="Unleash fire.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=30,
        saving_throw=SavingThrowEffect(
            ability=ability,
            dc=dc,
            damage_on_fail=[
                DamageRoll(dice="3d6", damage_type=DamageType.FIRE),
            ],
            damage_on_success=damage_on_success,
        ),
        uses_per_rest=1,
        source_item="Fire Scroll",
    )


def _condition_action() -> Action:
    return Action(
        name="Blinding Potion",
        description="Blinds the target.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=5,
        conditions_applied=["blinded"],
        source_item="Blinding Potion",
    )


def _condition_remove_action() -> Action:
    return Action(
        name="Lesser Restoration",
        description="Remove a condition.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=5,
        conditions_removed=["blinded"],
    )


def _save_with_conditions_action() -> Action:
    return Action(
        name="Hold Scroll",
        description="Paralyze on failed save.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=30,
        saving_throw=SavingThrowEffect(
            ability="wisdom",
            dc=15,
            conditions_on_fail=["paralyzed"],
        ),
        source_item="Hold Scroll",
    )


# ── resolve_effect tests ────────────────────────────────────────────


class TestResolveEffectHealing:
    """Tests for healing via resolve_effect."""

    def test_healing_restores_hp(self):
        creature = _make_creature(hp=10, max_hp=20)
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "user")
        action = _healing_action()

        with patch("arena.combat.actions.roll_expression", return_value=(8, [4, 4])):
            result = resolve_effect(
                creature, "user", creature, "user", action, grid,
            )

        assert result.success
        assert creature.current_hit_points == 18

    def test_healing_caps_at_max_hp(self):
        creature = _make_creature(hp=18, max_hp=20)
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "user")
        action = _healing_action()

        with patch("arena.combat.actions.roll_expression", return_value=(10, [5, 5])):
            result = resolve_effect(
                creature, "user", creature, "user", action, grid,
            )

        assert result.success
        assert creature.current_hit_points == 20

    def test_healing_on_another_creature(self):
        user = _make_creature(name="Healer", hp=20)
        target = _make_creature(name="Wounded", hp=5, max_hp=20)
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "healer")
        grid.place_creature(HexCoord(1, 0), "wounded")

        action = Action(
            name="Cure Wounds",
            description="Heal an ally.",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_CREATURE,
            range=5,
            healing="1d8+3",
        )

        with patch("arena.combat.actions.roll_expression", return_value=(7, [4])):
            result = resolve_effect(
                user, "healer", target, "wounded", action, grid,
            )

        assert result.success
        assert target.current_hit_points == 12


class TestResolveEffectSavingThrow:
    """Tests for saving throw effects."""

    def test_save_fail_full_damage(self):
        user = _make_creature(name="Caster")
        target = _make_creature(name="Target", hp=20)
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "caster")
        grid.place_creature(HexCoord(1, 0), "target")

        action = _save_damage_action(dc=20)  # Very high DC = almost certain fail

        with patch("arena.combat.actions.roll_die", return_value=5):
            result = resolve_effect(
                user, "caster", target, "target", action, grid,
            )

        assert result.success
        # Should have saving throw event and damage event
        event_types = [e.event_type for e in result.events]
        assert CombatEventType.SAVING_THROW in event_types
        assert CombatEventType.DAMAGE in event_types
        assert target.current_hit_points < 20

    def test_save_success_half_damage(self):
        user = _make_creature(name="Caster")
        target = _make_creature(name="Target", hp=40, max_hp=40)
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "caster")
        grid.place_creature(HexCoord(1, 0), "target")

        action = _save_damage_action(dc=5, damage_on_success="half")

        # High roll = save success; control damage dice
        with patch("arena.combat.actions.roll_die", return_value=18):
            with patch("arena.combat.actions.roll_damage", side_effect=lambda *a, **k: [DamagePacket(amount=10, dtype="fire")]):
                result = resolve_effect(
                    user, "caster", target, "target", action, grid,
                )

        assert result.success
        # Half of 10 = 5
        assert target.current_hit_points == 35

    def test_save_success_none_damage(self):
        user = _make_creature(name="Caster")
        target = _make_creature(name="Target", hp=20)
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "caster")
        grid.place_creature(HexCoord(1, 0), "target")

        action = _save_damage_action(dc=5, damage_on_success="none")

        with patch("arena.combat.actions.roll_die", return_value=18):
            result = resolve_effect(
                user, "caster", target, "target", action, grid,
            )

        assert result.success
        # No damage on success with "none"
        assert target.current_hit_points == 20

    def test_save_fail_applies_condition(self):
        user = _make_creature(name="Caster")
        target = _make_creature(name="Target")
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "caster")
        grid.place_creature(HexCoord(1, 0), "target")

        action = _save_with_conditions_action()

        with patch("arena.combat.actions.roll_die", return_value=1):  # Fail
            result = resolve_effect(
                user, "caster", target, "target", action, grid,
            )

        assert result.success
        assert any(c.condition.value == "paralyzed" for c in target.active_conditions)


class TestResolveEffectConditions:
    """Tests for direct condition application/removal."""

    def test_apply_condition_no_save(self):
        user = _make_creature(name="User")
        target = _make_creature(name="Target")
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "user")
        grid.place_creature(HexCoord(1, 0), "target")

        action = _condition_action()
        result = resolve_effect(user, "user", target, "target", action, grid)

        assert result.success
        assert any(c.condition.value == "blinded" for c in target.active_conditions)

    def test_remove_condition(self):
        from arena.models.conditions import Condition, AppliedCondition
        user = _make_creature(name="Healer")
        target = _make_creature(name="Target")
        target.active_conditions.append(
            AppliedCondition(condition=Condition.BLINDED, source="test")
        )
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "healer")
        grid.place_creature(HexCoord(1, 0), "target")

        action = _condition_remove_action()
        result = resolve_effect(user, "healer", target, "target", action, grid)

        assert result.success
        assert not any(c.condition.value == "blinded" for c in target.active_conditions)


class TestResolveEffectSelfTarget:
    """Tests for self-targeting actions."""

    def test_self_target_always_in_range(self):
        """Self-targeting should always pass range check."""
        creature = _make_creature(hp=10)
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "user")

        action = _healing_action()

        with patch("arena.combat.actions.roll_expression", return_value=(5, [3, 2])):
            result = resolve_effect(
                creature, "user", creature, "user", action, grid,
            )

        assert result.success
        assert creature.current_hit_points == 15

    def test_self_target_not_on_grid(self):
        """Self-targeting should work even if not placed on grid."""
        creature = _make_creature(hp=10)
        grid = _make_grid()
        # Not placed on grid

        action = _healing_action()

        with patch("arena.combat.actions.roll_expression", return_value=(5, [3, 2])):
            result = resolve_effect(
                creature, "user", creature, "user", action, grid,
            )

        assert result.success
        assert creature.current_hit_points == 15


class TestResolveEffectUseTracking:
    """Tests for current_uses decrement."""

    def test_uses_decremented(self):
        creature = _make_creature(hp=10)
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "user")

        action = _healing_action(uses=3)
        action.current_uses = 3

        with patch("arena.combat.actions.roll_expression", return_value=(5, [3, 2])):
            resolve_effect(creature, "user", creature, "user", action, grid)

        assert action.current_uses == 2

    def test_uses_initialized_from_max(self):
        """current_uses should be initialized from uses_per_rest if None."""
        creature = _make_creature(hp=10)
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "user")

        action = _healing_action(uses=2)
        assert action.current_uses is None

        with patch("arena.combat.actions.roll_expression", return_value=(5, [3, 2])):
            resolve_effect(creature, "user", creature, "user", action, grid)

        assert action.current_uses == 1

    def test_uses_not_decremented_below_zero(self):
        creature = _make_creature(hp=10)
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "user")

        action = _healing_action(uses=1)
        action.current_uses = 0

        with patch("arena.combat.actions.roll_expression", return_value=(5, [3, 2])):
            resolve_effect(creature, "user", creature, "user", action, grid)

        assert action.current_uses == 0


class TestResolveEffectOutOfRange:
    """Tests for out-of-range failures."""

    def test_out_of_range_fails(self):
        user = _make_creature(name="User")
        target = _make_creature(name="Target")
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "user")
        grid.place_creature(HexCoord(9, 0), "target")  # Far away

        action = Action(
            name="Touch Heal",
            description="Heal on touch.",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_CREATURE,
            range=5,
            healing="1d8",
        )

        result = resolve_effect(user, "user", target, "target", action, grid)
        assert not result.success


class TestResolveEffectKnockout:
    """Test that unconscious event is emitted on knockout."""

    def test_damage_knocks_out_target(self):
        user = _make_creature(name="Caster")
        target = _make_creature(name="Target", hp=1)
        grid = _make_grid()
        grid.place_creature(HexCoord(0, 0), "caster")
        grid.place_creature(HexCoord(1, 0), "target")

        action = _save_damage_action(dc=20)

        with patch("arena.combat.actions.roll_die", return_value=1):
            result = resolve_effect(
                user, "caster", target, "target", action, grid,
            )

        assert result.success
        event_types = [e.event_type for e in result.events]
        assert CombatEventType.CREATURE_DOWNED in event_types


# ── execute_effect (CombatManager) tests ────────────────────────────


def _setup_combat(
    grid_w: int = 10,
    grid_h: int = 10,
) -> tuple[CombatManager, str, str]:
    """Set up a minimal combat with two combatants.

    Returns (manager, player_id, enemy_id).
    """
    mgr = CombatManager()
    mgr.grid = HexGrid(grid_w, grid_h)

    player = _make_creature(name="Player", hp=15, max_hp=30)
    enemy = _make_creature(name="Enemy", hp=20)

    mgr.combatants["player"] = Combatant(
        creature_id="player",
        creature=player,
        team="player",
        position=HexCoord(0, 0),
    )
    mgr.combatants["enemy"] = Combatant(
        creature_id="enemy",
        creature=enemy,
        team="enemy",
        position=HexCoord(1, 0),
    )
    mgr.grid.place_creature(HexCoord(0, 0), "player")
    mgr.grid.place_creature(HexCoord(1, 0), "enemy")

    # Simulate active combatant setup
    from arena.combat.initiative import InitiativeEntry
    mgr.initiative.add_entry(InitiativeEntry(
        creature_id="player", name="Player",
        initiative_roll=20, dexterity=10,
        is_player_controlled=True, tiebreaker=0.5,
    ))
    mgr.initiative.add_entry(InitiativeEntry(
        creature_id="enemy", name="Enemy",
        initiative_roll=10, dexterity=10,
        is_player_controlled=False, tiebreaker=0.3,
    ))
    mgr.state = CombatState.IN_COMBAT
    mgr.turn_phase = TurnPhase.AWAITING_ACTION

    return mgr, "player", "enemy"


class TestExecuteEffect:
    """Tests for CombatManager.execute_effect()."""

    def test_execute_effect_marks_action_used(self):
        mgr, player_id, _ = _setup_combat()
        action = _healing_action()
        action.action_type = ActionType.ACTION  # Override to action

        mgr.select_action(action)
        assert mgr.turn_phase == TurnPhase.SELECTING_TARGET

        with patch("arena.combat.actions.roll_expression", return_value=(5, [3, 2])):
            result = mgr.execute_effect(player_id)

        assert result is not None
        assert result.success
        assert mgr.turn_resources.has_used_action
        assert not mgr.turn_resources.has_used_bonus_action
        assert mgr.turn_phase == TurnPhase.AWAITING_ACTION

    def test_execute_effect_marks_bonus_action_used(self):
        mgr, player_id, _ = _setup_combat()
        action = _healing_action()
        assert action.action_type == ActionType.BONUS_ACTION

        mgr.select_action(action)

        with patch("arena.combat.actions.roll_expression", return_value=(5, [3, 2])):
            result = mgr.execute_effect(player_id)

        assert result is not None
        assert result.success
        assert mgr.turn_resources.has_used_bonus_action
        assert not mgr.turn_resources.has_used_action

    def test_execute_effect_self_target(self):
        mgr, player_id, _ = _setup_combat()
        player = mgr.combatants[player_id].creature
        assert player.current_hit_points == 15

        action = _healing_action()
        mgr.select_action(action)

        with patch("arena.combat.actions.roll_expression", return_value=(8, [4, 4])):
            result = mgr.execute_effect(player_id)

        assert result is not None
        assert result.success
        assert player.current_hit_points == 23

    def test_execute_effect_on_enemy(self):
        mgr, _, enemy_id = _setup_combat()
        enemy = mgr.combatants[enemy_id].creature

        action = _save_damage_action(dc=20)
        mgr.select_action(action)

        with patch("arena.combat.actions.roll_die", return_value=2):
            result = mgr.execute_effect(enemy_id)

        assert result is not None
        assert result.success
        assert enemy.current_hit_points < 20

    def test_execute_effect_clears_selected_action(self):
        mgr, player_id, _ = _setup_combat()
        action = _healing_action()
        mgr.select_action(action)
        assert mgr.selected_action is not None

        with patch("arena.combat.actions.roll_expression", return_value=(3, [2, 1])):
            mgr.execute_effect(player_id)

        assert mgr.selected_action is None

    def test_execute_effect_returns_none_without_selection(self):
        mgr, player_id, _ = _setup_combat()
        # Don't select any action
        result = mgr.execute_effect(player_id)
        assert result is None


# ── AI executor EXECUTE_EFFECT test ─────────────────────────────────


class TestAIExecuteEffect:
    """Test the AI executor EXECUTE_EFFECT step."""

    def test_executor_handles_effect_step(self):
        from arena.ai.controller import TurnStep, TurnStepType
        from arena.ai.executor import execute_step

        mgr, player_id, _ = _setup_combat()
        action = _healing_action()
        mgr.select_action(action)

        step = TurnStep(
            step_type=TurnStepType.EXECUTE_EFFECT,
            target_id=player_id,
        )

        with patch("arena.combat.actions.roll_expression", return_value=(5, [3, 2])):
            event = execute_step(step, mgr)

        assert mgr.turn_resources.has_used_bonus_action
        assert mgr.combatants[player_id].creature.current_hit_points == 20


# ── Radial menu item categorization test ────────────────────────────


class TestRadialMenuItems:
    """Test that item actions are correctly categorized."""

    def test_get_item_actions_excludes_weapons(self):
        from arena.gui.radial_menu import RadialMenu
        from arena.models.actions import Attack

        creature = _make_creature()
        creature.actions = [
            Action(
                name="Longsword Attack",
                description="Slash.",
                attack=Attack(
                    name="Longsword",
                    attack_type="melee_weapon",
                    ability="strength",
                    damage=[],
                ),
            ),
            Action(
                name="Use Healing Potion",
                description="Drink.",
                healing="2d4+2",
                source_item="Healing Potion",
                uses_per_rest=1,
            ),
        ]

        items = RadialMenu._get_item_actions(creature)
        assert len(items) == 1
        assert items[0].name == "Use Healing Potion"

    def test_get_item_actions_excludes_cantrips(self):
        from arena.gui.radial_menu import RadialMenu
        from arena.models.actions import Attack

        creature = _make_creature()
        creature.actions = [
            Action(
                name="Fire Bolt",
                description="Ranged spell attack.",
                attack=Attack(
                    name="Fire Bolt",
                    attack_type="ranged_spell",
                    ability="intelligence",
                    damage=[],
                ),
            ),
            Action(
                name="Use Scroll",
                description="Read scroll.",
                source_item="Scroll of Fire",
                saving_throw=SavingThrowEffect(
                    ability="dexterity",
                    dc=13,
                    damage_on_fail=[
                        DamageRoll(dice="2d6", damage_type=DamageType.FIRE),
                    ],
                ),
                uses_per_rest=1,
            ),
        ]

        items = RadialMenu._get_item_actions(creature)
        assert len(items) == 1
        assert items[0].name == "Use Scroll"

    def test_get_item_actions_excludes_leveled_spells(self):
        from arena.gui.radial_menu import RadialMenu

        creature = _make_creature()
        creature.actions = [
            Action(
                name="Fireball",
                description="Big boom.",
                resource_cost={"spell_slot_3": 1},
                saving_throw=SavingThrowEffect(
                    ability="dexterity",
                    dc=15,
                ),
            ),
            Action(
                name="Use Potion",
                description="Drink.",
                healing="2d4",
                source_item="Potion",
                uses_per_rest=1,
            ),
        ]

        items = RadialMenu._get_item_actions(creature)
        assert len(items) == 1
        assert items[0].name == "Use Potion"
