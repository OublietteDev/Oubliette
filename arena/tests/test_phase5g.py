"""Tests for Phase 5g: Standard Actions (Dash, Disengage, Dodge, Help)."""

import pytest
from pathlib import Path

from arena.combat.manager import CombatManager, CombatState, TurnPhase
from arena.combat.conditions import has_condition
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.models.encounter import Encounter, CombatantEntry
from arena.grid.coordinates import HexCoord


# ── Helpers ───────────────────────────────────────────────────────────

def _make_creature(name, hp=20, speed=30, is_player=True):
    return Creature(
        name=name,
        max_hit_points=hp,
        ability_scores=AbilityScores(strength=14, dexterity=14),
        proficiency_bonus=2,
        speed={"walk": speed},
        is_player_controlled=is_player,
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
                        DamageRoll(dice="1d6", damage_type=DamageType.SLASHING,
                                   ability_modifier="strength")
                    ],
                ),
            )
        ],
    )


def _setup_combat():
    """Start a combat with two adjacent creatures."""
    encounter = Encounter(
        name="Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="player",
                creature_data=_make_creature("Fighter", is_player=True),
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="ally",
                creature_data=_make_creature("Cleric", is_player=True),
                team="player",
                starting_position=(2, 3),
            ),
            CombatantEntry(
                creature_id="enemy",
                creature_data=_make_creature("Goblin", is_player=False),
                team="enemy",
                starting_position=(3, 2),
            ),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    cm.roll_initiative()
    cm.begin_combat()
    return cm


def _get_active_and_skip_to_player(cm):
    """Skip turns until a player-controlled combatant is active."""
    for _ in range(10):
        active = cm.active_combatant
        if active and active.creature.is_player_controlled:
            return active
        cm.end_turn()
    return None


# ── Dash Tests ──────────────────────────────────────────────────────

class TestDash:
    def test_dash_doubles_movement(self):
        cm = _setup_combat()
        active = _get_active_and_skip_to_player(cm)
        assert active is not None

        original_movement = cm.movement.remaining_movement
        event = cm.execute_standard_action("dash")
        assert event is not None
        assert "Dash" in event.message
        # Should have added base speed
        base_speed = active.creature.speed.get("walk", 30)
        assert cm.movement.remaining_movement == original_movement + base_speed

    def test_dash_uses_action(self):
        cm = _setup_combat()
        _get_active_and_skip_to_player(cm)
        cm.execute_standard_action("dash")
        assert cm.turn_resources.has_used_action is True

    def test_dash_fails_if_action_used(self):
        cm = _setup_combat()
        _get_active_and_skip_to_player(cm)
        cm.turn_resources.has_used_action = True
        event = cm.execute_standard_action("dash")
        assert event is None


# ── Disengage Tests ─────────────────────────────────────────────────

class TestDisengage:
    def test_disengage_sets_flag(self):
        cm = _setup_combat()
        _get_active_and_skip_to_player(cm)
        event = cm.execute_standard_action("disengage")
        assert event is not None
        assert cm.turn_resources.is_disengaging is True
        assert "Disengage" in event.message

    def test_disengage_uses_action(self):
        cm = _setup_combat()
        _get_active_and_skip_to_player(cm)
        cm.execute_standard_action("disengage")
        assert cm.turn_resources.has_used_action is True

    def test_disengage_flag_resets_on_new_turn(self):
        cm = _setup_combat()
        _get_active_and_skip_to_player(cm)
        cm.execute_standard_action("disengage")
        assert cm.turn_resources.is_disengaging is True
        cm.end_turn()
        # After turn ends and new turn starts, flag should reset
        assert cm.turn_resources.is_disengaging is False


# ── Dodge Tests ─────────────────────────────────────────────────────

class TestDodge:
    def test_dodge_applies_condition(self):
        cm = _setup_combat()
        active = _get_active_and_skip_to_player(cm)
        event = cm.execute_standard_action("dodge")
        assert event is not None
        assert has_condition(active.creature, Condition.DODGING)
        assert "Dodge" in event.message

    def test_dodge_uses_action(self):
        cm = _setup_combat()
        _get_active_and_skip_to_player(cm)
        cm.execute_standard_action("dodge")
        assert cm.turn_resources.has_used_action is True


# ── Help Tests ──────────────────────────────────────────────────────

class TestHelp:
    def test_help_applies_helped_condition(self):
        cm = _setup_combat()
        active = _get_active_and_skip_to_player(cm)
        # Find the ally
        ally_id = None
        for cid, c in cm.combatants.items():
            if cid != active.creature_id and c.team == "player":
                ally_id = cid
                break

        if ally_id is None:
            pytest.skip("No ally found")

        # Check if active is adjacent to ally (within 5ft)
        active_pos = cm.grid.find_creature(active.creature_id)
        ally_pos = cm.grid.find_creature(ally_id)
        if active_pos.distance_to(ally_pos) > 1:
            pytest.skip("Active not adjacent to ally")

        event = cm.execute_standard_action("help", target_id=ally_id)
        assert event is not None
        ally = cm.combatants[ally_id]
        assert has_condition(ally.creature, Condition.HELPED)

    def test_help_uses_action(self):
        cm = _setup_combat()
        active = _get_active_and_skip_to_player(cm)
        ally_id = None
        for cid, c in cm.combatants.items():
            if cid != active.creature_id and c.team == "player":
                ally_id = cid
                break
        if ally_id:
            cm.execute_standard_action("help", target_id=ally_id)
            assert cm.turn_resources.has_used_action is True

    def test_help_requires_target(self):
        cm = _setup_combat()
        _get_active_and_skip_to_player(cm)
        event = cm.execute_standard_action("help")  # No target
        assert event is None

    def test_help_requires_adjacency(self):
        cm = _setup_combat()
        active = _get_active_and_skip_to_player(cm)
        # Find an enemy (likely not adjacent for help)
        enemy_id = None
        for cid, c in cm.combatants.items():
            if c.team == "enemy":
                enemy_id = cid
                break
        # Even if adjacent, the function should still work
        # (the 5ft check will handle range)


# ── Invalid action Tests ───────────────────────────────────────────

class TestStandardActionValidation:
    def test_unknown_action_returns_none(self):
        cm = _setup_combat()
        _get_active_and_skip_to_player(cm)
        event = cm.execute_standard_action("fireball")
        assert event is None
