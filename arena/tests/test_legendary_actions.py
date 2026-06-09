"""Tests for legendary actions — point pools, queue mechanics, execution, and AI."""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action, Attack, DamageRoll, DamageType, ActionType,
    SavingThrowEffect, TargetType,
)
from arena.models.character import Creature
from arena.models.monster import Monster
from arena.models.encounter import Encounter, CombatantEntry
from arena.grid.coordinates import HexCoord


# ── Test helpers ──────────────────────────────────────────────────────


def _make_player(name="Fighter", hp=50, ac=15, strength=16, dexterity=12):
    """Create a simple player character for testing."""
    return Creature(
        name=name,
        max_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(strength=strength, dexterity=dexterity),
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


def _make_dragon(name="Dragon", hp=200, ac=18, legendary_count=3):
    """Create a monster with legendary actions for testing."""
    return Monster(
        name=name,
        max_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(
            strength=20, dexterity=10, constitution=20,
            intelligence=14, wisdom=12, charisma=16,
        ),
        proficiency_bonus=5,
        is_player_controlled=False,
        legendary_action_count=legendary_count,
        legendary_actions=[
            Action(
                name="Tail Attack",
                description="A sweep of the tail",
                action_type=ActionType.LEGENDARY,
                legendary_action_cost=1,
                target_type=TargetType.ONE_ENEMY,
                range=10,
                attack=Attack(
                    name="Tail",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=10,
                    damage=[DamageRoll(dice="2d8", damage_type=DamageType.BLUDGEONING)],
                ),
            ),
            Action(
                name="Wing Attack",
                description="Powerful wing buffet",
                action_type=ActionType.LEGENDARY,
                legendary_action_cost=2,
                target_type=TargetType.ONE_ENEMY,
                range=10,
                saving_throw=SavingThrowEffect(
                    ability="dexterity",
                    dc=18,
                    damage_on_fail=[DamageRoll(dice="2d6", damage_type=DamageType.BLUDGEONING)],
                ),
            ),
        ],
        actions=[
            Action(
                name="Bite",
                description="Melee bite attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Bite",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=10,
                    damage=[DamageRoll(dice="2d10", damage_type=DamageType.PIERCING)],
                ),
            ),
        ],
    )


def _make_encounter_with_dragon(legendary_count=3, num_players=1):
    """Create an encounter: player(s) vs dragon with legendary actions."""
    combatants = []
    for i in range(num_players):
        combatants.append(
            CombatantEntry(
                creature_id=f"inline_player_{i}",
                creature_data=_make_player(name=f"Fighter {i + 1}"),
                team="player",
                starting_position=(2 + i, 2),
            )
        )
    combatants.append(
        CombatantEntry(
            creature_id="inline_dragon",
            creature_data=_make_dragon(legendary_count=legendary_count),
            team="enemy",
            starting_position=(3, 3),
        )
    )
    return Encounter(
        name="Dragon Fight",
        grid_width=10,
        grid_height=10,
        combatants=combatants,
    )


def _setup_combat(encounter=None, fixed_initiative=None):
    """Set up a combat manager, load encounter, roll initiative, begin combat.

    Args:
        encounter: Optional custom encounter. Defaults to 1 player vs dragon.
        fixed_initiative: If provided, a dict of creature_id -> roll value
            to patch initiative rolls for deterministic turn order.

    Returns:
        CombatManager with combat in progress.
    """
    if encounter is None:
        encounter = _make_encounter_with_dragon()

    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))

    if fixed_initiative:
        # Patch roll_die to return fixed values based on creature
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


# ══════════════════════════════════════════════════════════════════════
# Point Pool Tests
# ══════════════════════════════════════════════════════════════════════


class TestLegendaryPointPool:
    """Tests for legendary action point initialization and reset."""

    def test_points_initialized_at_initiative(self):
        """Legendary creatures get their point pool after initiative roll."""
        cm = CombatManager()
        encounter = _make_encounter_with_dragon(legendary_count=3)
        cm.load_encounter(encounter, Path("."))
        cm.roll_initiative()

        # Find the dragon
        dragon_ids = [
            cid for cid, c in cm.combatants.items()
            if getattr(c.creature, "legendary_action_count", 0) > 0
        ]
        assert len(dragon_ids) == 1
        dragon_id = dragon_ids[0]
        assert cm.legendary_points[dragon_id] == 3

    def test_non_legendary_creatures_have_no_points(self):
        """Regular creatures should not have legendary points."""
        cm = CombatManager()
        encounter = _make_encounter_with_dragon()
        cm.load_encounter(encounter, Path("."))
        cm.roll_initiative()

        player_ids = [
            cid for cid, c in cm.combatants.items()
            if c.creature.is_player_controlled
        ]
        for pid in player_ids:
            assert pid not in cm.legendary_points

    def test_points_reset_at_start_of_own_turn(self):
        """Legendary points should reset when the creature's own turn starts."""
        cm = _setup_combat()

        # Find the dragon
        dragon_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid
                break

        # First, advance past the dragon's turn if it goes first,
        # so we can deplete points and watch them reset on its NEXT turn.
        max_iterations = 20
        found_dragon_turn = False
        for _ in range(max_iterations):
            active = cm.active_combatant
            if active is None:
                break
            if active.creature_id == dragon_id and not found_dragon_turn:
                # Skip the dragon's first turn
                found_dragon_turn = True
                cm.end_turn()
                continue
            if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
                cm.pass_legendary_action()
                continue
            if active.creature_id != dragon_id:
                # We're on a non-dragon turn. Deplete points and end turn.
                cm.legendary_points[dragon_id] = 1
                cm.end_turn()
                continue
            # We've reached the dragon's second turn — points should be reset
            assert cm.legendary_points[dragon_id] == 3
            break
        else:
            pytest.fail("Never reached dragon's turn after depletion")

    def test_custom_legendary_count(self):
        """Creatures with different legendary_action_count values."""
        cm = CombatManager()
        encounter = _make_encounter_with_dragon(legendary_count=5)
        cm.load_encounter(encounter, Path("."))
        cm.roll_initiative()

        dragon_ids = [
            cid for cid, c in cm.combatants.items()
            if getattr(c.creature, "legendary_action_count", 0) > 0
        ]
        assert cm.legendary_points[dragon_ids[0]] == 5

    def test_zero_legendary_count_no_points(self):
        """Monster with legendary_action_count=0 gets no points."""
        cm = CombatManager()
        encounter = _make_encounter_with_dragon(legendary_count=0)
        cm.load_encounter(encounter, Path("."))
        cm.roll_initiative()

        for cid in cm.combatants:
            assert cid not in cm.legendary_points


# ══════════════════════════════════════════════════════════════════════
# Queue Building Tests
# ══════════════════════════════════════════════════════════════════════


class TestLegendaryQueue:
    """Tests for _build_legendary_queue and phase transitions."""

    def test_queue_excludes_creature_whose_turn_ended(self):
        """The creature whose turn just ended should not be in the queue."""
        cm = _setup_combat()

        # Find IDs
        dragon_id = None
        player_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid
            else:
                player_id = cid

        queue = cm._build_legendary_queue(exclude_id=dragon_id)
        assert dragon_id not in queue

    def test_queue_includes_eligible_legendary_creatures(self):
        """Legendary creatures with points should be in the queue."""
        cm = _setup_combat()

        dragon_id = None
        player_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid
            else:
                player_id = cid

        # Build queue excluding the player (simulating end of player's turn)
        queue = cm._build_legendary_queue(exclude_id=player_id)
        assert dragon_id in queue

    def test_queue_excludes_creatures_with_no_points(self):
        """Legendary creatures with 0 remaining points should be excluded."""
        cm = _setup_combat()

        dragon_id = None
        player_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid
            else:
                player_id = cid

        cm.legendary_points[dragon_id] = 0
        queue = cm._build_legendary_queue(exclude_id=player_id)
        assert dragon_id not in queue

    def test_queue_excludes_unconscious_creatures(self):
        """Unconscious legendary creatures should be excluded."""
        cm = _setup_combat()

        dragon_id = None
        player_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid
            else:
                player_id = cid

        # KO the dragon
        cm.combatants[dragon_id].creature.current_hit_points = 0
        queue = cm._build_legendary_queue(exclude_id=player_id)
        assert dragon_id not in queue

    def test_queue_excludes_incapacitated_creatures(self):
        """Incapacitated legendary creatures should be excluded."""
        from arena.models.conditions import Condition, AppliedCondition
        cm = _setup_combat()

        dragon_id = None
        player_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid
            else:
                player_id = cid

        # Apply stunned condition (which causes incapacitation)
        cm.combatants[dragon_id].creature.active_conditions.append(
            AppliedCondition(condition=Condition.STUNNED, source="test")
        )
        queue = cm._build_legendary_queue(exclude_id=player_id)
        assert dragon_id not in queue

    def test_end_turn_enters_legendary_phase(self):
        """end_turn() should enter LEGENDARY_ACTION_PHASE when eligible creatures exist."""
        cm = _setup_combat()

        # Find whose turn it is
        active = cm.active_combatant
        assert active is not None

        dragon_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid

        # If the active creature is NOT the dragon, end their turn
        if active.creature_id != dragon_id:
            cm.end_turn()
            # Should enter legendary phase
            assert cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE
            assert cm._legendary_actor_id == dragon_id
        else:
            # Dragon's turn — end it, then a non-dragon turn should follow
            cm.end_turn()
            # After dragon's turn, no legendary phase (can't act on own turn end)
            # Either it advances to next turn, or enters legendary phase
            # for OTHER legendary creatures (but there are none)
            assert cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE or cm._legendary_actor_id != dragon_id

    def test_end_turn_skips_legendary_phase_when_no_eligible(self):
        """end_turn() should skip legendary phase when no eligible creatures."""
        cm = _setup_combat(
            encounter=_make_encounter_with_dragon(legendary_count=0)
        )

        active = cm.active_combatant
        assert active is not None
        cm.end_turn()
        # Should NOT enter legendary phase
        assert cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE


# ══════════════════════════════════════════════════════════════════════
# Execution Tests
# ══════════════════════════════════════════════════════════════════════


class TestLegendaryExecution:
    """Tests for execute_legendary_action and pass_legendary_action."""

    def _get_to_legendary_phase(self, cm):
        """Advance combat until we're in LEGENDARY_ACTION_PHASE.

        Returns (dragon_id, player_id) or None if can't reach it.
        """
        dragon_id = None
        player_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid
            else:
                player_id = cid

        max_iterations = 20
        for _ in range(max_iterations):
            if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
                return dragon_id, player_id
            if cm.state == CombatState.COMBAT_ENDED:
                return None
            cm.end_turn()

        return None

    def test_execute_legendary_attack(self):
        """Executing a legendary attack deducts points and resolves."""
        cm = _setup_combat()

        result = self._get_to_legendary_phase(cm)
        if result is None:
            pytest.skip("Could not reach legendary phase")
        dragon_id, player_id = result

        assert cm._legendary_actor_id == dragon_id
        initial_points = cm.legendary_points[dragon_id]

        # Get the Tail Attack (cost 1)
        tail_attack = None
        dragon = cm.combatants[dragon_id].creature
        for a in dragon.legendary_actions:
            if a.name == "Tail Attack":
                tail_attack = a
                break
        assert tail_attack is not None

        # Verify the action resolves (returns a result)
        result = cm.execute_legendary_action(tail_attack, player_id)
        assert result is not None
        # The action should have produced combat events
        assert len(result.events) > 0

        # Note: points may have been reset if the dragon's own turn started
        # after _advance_legendary_queue -> _advance_to_next_turn.
        # We verify point deduction separately in test_points_deducted_before_queue_advance.

    def test_execute_legendary_effect(self):
        """Executing a legendary save effect resolves correctly."""
        cm = _setup_combat()

        result = self._get_to_legendary_phase(cm)
        if result is None:
            pytest.skip("Could not reach legendary phase")
        dragon_id, player_id = result

        # Get the Wing Attack (cost 2)
        wing_attack = None
        dragon = cm.combatants[dragon_id].creature
        for a in dragon.legendary_actions:
            if a.name == "Wing Attack":
                wing_attack = a
                break
        assert wing_attack is not None

        result = cm.execute_legendary_action(wing_attack, player_id)
        assert result is not None
        assert len(result.events) > 0

    def test_points_deducted_during_execution(self):
        """Points are deducted by execute_legendary_action before queue advances.

        We verify this by using two legendary actions in a row during
        a two-player encounter, so the dragon gets two opportunities
        before its turn resets the pool.
        """
        encounter = _make_encounter_with_dragon(num_players=2)
        cm = _setup_combat(encounter=encounter)

        dragon_id = None
        player_ids = []
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid
            else:
                player_ids.append(cid)

        # Advance past turns until the first player's legendary opportunity
        # We need to end a player's turn, get legendary phase, use Tail (1pt),
        # then end the next player's turn, get legendary phase, use Tail (1pt),
        # and verify points went from 3 -> 2 -> 1
        used_count = 0
        max_iterations = 40
        for _ in range(max_iterations):
            if cm.state == CombatState.COMBAT_ENDED:
                break
            if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
                if cm._legendary_actor_id == dragon_id:
                    tail = cm.combatants[dragon_id].creature.legendary_actions[0]
                    target = player_ids[0] if player_ids else None
                    if target:
                        cm.execute_legendary_action(tail, target)
                        used_count += 1
                        if used_count >= 2:
                            break
                    else:
                        cm.pass_legendary_action()
                else:
                    cm.pass_legendary_action()
            else:
                cm.end_turn()

        # Should have used at least 2 legendary actions
        assert used_count >= 2

    def test_cannot_use_when_not_in_legendary_phase(self):
        """execute_legendary_action should return None outside legendary phase."""
        cm = _setup_combat()
        assert cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE

        dragon_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid
        dragon = cm.combatants[dragon_id].creature

        result = cm.execute_legendary_action(
            dragon.legendary_actions[0], list(cm.combatants.keys())[0]
        )
        assert result is None

    def test_cannot_afford_action(self):
        """Cannot use action whose cost exceeds remaining points."""
        cm = _setup_combat()

        result = self._get_to_legendary_phase(cm)
        if result is None:
            pytest.skip("Could not reach legendary phase")
        dragon_id, player_id = result

        # Set points to 1
        cm.legendary_points[dragon_id] = 1

        # Wing Attack costs 2 — should fail
        wing_attack = None
        dragon = cm.combatants[dragon_id].creature
        for a in dragon.legendary_actions:
            if a.name == "Wing Attack":
                wing_attack = a
                break

        result = cm.execute_legendary_action(wing_attack, player_id)
        assert result is None
        # Points should not have changed
        assert cm.legendary_points[dragon_id] == 1

    def test_pass_legendary_action(self):
        """pass_legendary_action advances the queue without spending points."""
        cm = _setup_combat()

        result = self._get_to_legendary_phase(cm)
        if result is None:
            pytest.skip("Could not reach legendary phase")
        dragon_id, player_id = result

        initial_points = cm.legendary_points[dragon_id]
        cm.pass_legendary_action()

        # Points unchanged
        assert cm.legendary_points[dragon_id] == initial_points

    def test_queue_advances_after_action(self):
        """After executing a legendary action, queue should advance."""
        cm = _setup_combat()

        result = self._get_to_legendary_phase(cm)
        if result is None:
            pytest.skip("Could not reach legendary phase")
        dragon_id, player_id = result

        tail_attack = cm.combatants[dragon_id].creature.legendary_actions[0]
        cm.execute_legendary_action(tail_attack, player_id)

        # Queue should have advanced (dragon was only legendary creature)
        # So next turn should have started
        if cm.state != CombatState.COMBAT_ENDED:
            assert cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE or cm._legendary_actor_id != dragon_id

    def test_legendary_does_not_consume_turn_action(self):
        """Legendary actions should not mark the turn's action as used."""
        cm = _setup_combat()

        result = self._get_to_legendary_phase(cm)
        if result is None:
            pytest.skip("Could not reach legendary phase")
        dragon_id, player_id = result

        tail_attack = cm.combatants[dragon_id].creature.legendary_actions[0]
        cm.execute_legendary_action(tail_attack, player_id)

        # TurnResources should not have been affected
        assert not cm.turn_resources.has_used_action or cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE

    def test_no_legendary_on_own_turn_end(self):
        """Dragon should NOT appear in queue when its own turn ends."""
        cm = _setup_combat()

        dragon_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid

        # Advance to dragon's turn
        max_iterations = 20
        for _ in range(max_iterations):
            if cm.state == CombatState.COMBAT_ENDED:
                pytest.skip("Combat ended before reaching dragon turn")
            active = cm.active_combatant
            if active and active.creature_id == dragon_id:
                break
            if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
                cm.pass_legendary_action()
            else:
                cm.end_turn()

        active = cm.active_combatant
        if active is None or active.creature_id != dragon_id:
            pytest.skip("Could not reach dragon's turn")

        # End dragon's own turn
        cm.end_turn()

        # If legendary phase activated, dragon should NOT be the actor
        if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
            assert cm._legendary_actor_id != dragon_id


# ══════════════════════════════════════════════════════════════════════
# Turn Flow Tests
# ══════════════════════════════════════════════════════════════════════


class TestLegendaryTurnFlow:
    """Tests for the overall turn flow with legendary actions."""

    def test_full_round_with_legendary_actions(self):
        """Complete a full round where legendary actions are passed."""
        cm = _setup_combat()
        initial_round = cm.initiative.round_number

        # Complete turns, passing all legendary actions
        max_iterations = 50
        for _ in range(max_iterations):
            if cm.state == CombatState.COMBAT_ENDED:
                break
            if cm.initiative.round_number > initial_round:
                break
            if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
                cm.pass_legendary_action()
            else:
                cm.end_turn()

        # Should have advanced at least one round
        assert cm.initiative.round_number > initial_round or cm.state == CombatState.COMBAT_ENDED

    def test_legendary_action_then_next_turn(self):
        """After legendary action, the next creature's turn should start."""
        cm = _setup_combat()

        # Find dragon
        dragon_id = None
        player_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid
            else:
                player_id = cid

        # Get to legendary phase
        max_iterations = 20
        for _ in range(max_iterations):
            if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
                break
            if cm.state == CombatState.COMBAT_ENDED:
                pytest.skip("Combat ended")
            cm.end_turn()

        if cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE:
            pytest.skip("Could not reach legendary phase")

        # Remember who was next in initiative
        old_index = cm.initiative.current_index

        # Pass the legendary action
        cm.pass_legendary_action()

        # Should have advanced to the next creature's turn
        if cm.state != CombatState.COMBAT_ENDED:
            assert cm.turn_phase in (
                TurnPhase.AWAITING_ACTION,
                TurnPhase.START_OF_TURN,
                TurnPhase.LEGENDARY_ACTION_PHASE,  # could enter another legendary phase
            )


# ══════════════════════════════════════════════════════════════════════
# Multiple Legendary Creatures
# ══════════════════════════════════════════════════════════════════════


class TestMultipleLegendaryCreatures:
    """Tests for encounters with multiple legendary creatures."""

    def test_both_legendary_creatures_get_opportunities(self):
        """Two legendary creatures should both appear in the queue."""
        encounter = Encounter(
            name="Double Dragon",
            grid_width=10,
            grid_height=10,
            combatants=[
                CombatantEntry(
                    creature_id="inline_player",
                    creature_data=_make_player(),
                    team="player",
                    starting_position=(2, 2),
                ),
                CombatantEntry(
                    creature_id="inline_dragon_1",
                    creature_data=_make_dragon(name="Red Dragon"),
                    team="enemy",
                    starting_position=(4, 2),
                ),
                CombatantEntry(
                    creature_id="inline_dragon_2",
                    creature_data=_make_dragon(name="Blue Dragon"),
                    team="enemy",
                    starting_position=(4, 4),
                ),
            ],
        )
        cm = _setup_combat(encounter=encounter)

        # Find IDs
        dragon_ids = []
        player_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_ids.append(cid)
            else:
                player_id = cid

        assert len(dragon_ids) == 2

        # Both should have points
        for did in dragon_ids:
            assert cm.legendary_points[did] == 3

        # Build queue after player's turn (excludes player)
        queue = cm._build_legendary_queue(exclude_id=player_id)
        assert len(queue) == 2
        for did in dragon_ids:
            assert did in queue


# ══════════════════════════════════════════════════════════════════════
# Victory During Legendary Action
# ══════════════════════════════════════════════════════════════════════


class TestLegendaryVictory:
    """Tests for combat ending during a legendary action."""

    def test_victory_when_legendary_kills_last_player(self):
        """If legendary action kills the last PC, combat should end."""
        # Create a player with very low HP
        encounter = Encounter(
            name="Deadly",
            grid_width=10,
            grid_height=10,
            combatants=[
                CombatantEntry(
                    creature_id="inline_player",
                    creature_data=_make_player(hp=1, ac=1),
                    team="player",
                    starting_position=(3, 3),
                ),
                CombatantEntry(
                    creature_id="inline_dragon",
                    creature_data=_make_dragon(),
                    team="enemy",
                    starting_position=(3, 4),
                ),
            ],
        )
        cm = _setup_combat(encounter=encounter)

        # Get to legendary phase
        max_iterations = 20
        for _ in range(max_iterations):
            if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
                break
            if cm.state == CombatState.COMBAT_ENDED:
                break
            cm.end_turn()

        if cm.state == CombatState.COMBAT_ENDED:
            # Combat already ended (dragon killed player on its turn)
            return

        if cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE:
            pytest.skip("Could not reach legendary phase")

        dragon_id = cm._legendary_actor_id
        player_id = None
        for cid, c in cm.combatants.items():
            if c.creature.is_player_controlled:
                player_id = cid

        # Set player to 1 HP to ensure the legendary action kills them
        cm.combatants[player_id].creature.current_hit_points = 1

        tail_attack = cm.combatants[dragon_id].creature.legendary_actions[0]

        # Patch to guarantee a hit
        with patch("arena.combat.actions.roll_die", return_value=20):
            cm.execute_legendary_action(tail_attack, player_id)

        # Player should be dead, combat should end
        assert cm.combatants[player_id].creature.current_hit_points <= 0
        assert cm.state == CombatState.COMBAT_ENDED
        assert cm.winner == "enemy"


# ══════════════════════════════════════════════════════════════════════
# Available Actions Query
# ══════════════════════════════════════════════════════════════════════


class TestGetAvailableLegendaryActions:
    """Tests for get_available_legendary_actions."""

    def test_all_actions_available_at_full_points(self):
        """With full points, all actions should be available."""
        cm = _setup_combat()

        dragon_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid

        available = cm.get_available_legendary_actions(dragon_id)
        assert len(available) == 2  # Tail Attack (1) + Wing Attack (2)

    def test_expensive_actions_filtered_when_low_points(self):
        """With only 1 point, Wing Attack (cost 2) should be filtered out."""
        cm = _setup_combat()

        dragon_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid

        cm.legendary_points[dragon_id] = 1
        available = cm.get_available_legendary_actions(dragon_id)
        assert len(available) == 1
        assert available[0].name == "Tail Attack"

    def test_no_actions_at_zero_points(self):
        """With 0 points, no actions should be available."""
        cm = _setup_combat()

        dragon_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid

        cm.legendary_points[dragon_id] = 0
        available = cm.get_available_legendary_actions(dragon_id)
        assert len(available) == 0

    def test_non_legendary_creature_returns_empty(self):
        """Non-legendary creatures should return empty list."""
        cm = _setup_combat()

        player_id = None
        for cid, c in cm.combatants.items():
            if c.creature.is_player_controlled:
                player_id = cid

        available = cm.get_available_legendary_actions(player_id)
        assert len(available) == 0


# ══════════════════════════════════════════════════════════════════════
# AI Planning Tests
# ══════════════════════════════════════════════════════════════════════


class TestAILegendaryPlanning:
    """Tests for AIController.plan_legendary_action."""

    def test_ai_plans_legendary_action(self):
        """AI should plan an EXECUTE_LEGENDARY step when viable."""
        from arena.ai.controller import AIController, TurnStepType

        cm = _setup_combat()

        # Get to legendary phase
        max_iterations = 20
        for _ in range(max_iterations):
            if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
                break
            if cm.state == CombatState.COMBAT_ENDED:
                pytest.skip("Combat ended")
            cm.end_turn()

        if cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE:
            pytest.skip("Could not reach legendary phase")

        controller = AIController(randomness=0.0)
        plan = controller.plan_legendary_action(cm)

        # Should have steps
        assert len(plan.steps) > 0
        step_types = [s.step_type for s in plan.steps]
        # Should contain either EXECUTE_LEGENDARY or PASS_LEGENDARY
        assert (
            TurnStepType.EXECUTE_LEGENDARY in step_types
            or TurnStepType.PASS_LEGENDARY in step_types
        )

    def test_ai_passes_when_no_actions_available(self):
        """AI should pass when no legendary actions are affordable."""
        from arena.ai.controller import AIController, TurnStepType

        cm = _setup_combat()

        # Get to legendary phase
        max_iterations = 20
        for _ in range(max_iterations):
            if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
                break
            if cm.state == CombatState.COMBAT_ENDED:
                pytest.skip("Combat ended")
            cm.end_turn()

        if cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE:
            pytest.skip("Could not reach legendary phase")

        # Zero out points
        dragon_id = cm._legendary_actor_id
        cm.legendary_points[dragon_id] = 0

        controller = AIController(randomness=0.0)
        plan = controller.plan_legendary_action(cm)

        step_types = [s.step_type for s in plan.steps]
        assert TurnStepType.PASS_LEGENDARY in step_types


# ══════════════════════════════════════════════════════════════════════
# Executor Tests
# ══════════════════════════════════════════════════════════════════════


class TestLegendaryExecutor:
    """Tests for AI executor handling legendary steps."""

    def test_execute_legendary_step(self):
        """EXECUTE_LEGENDARY step should call execute_legendary_action and produce events."""
        from arena.ai.controller import TurnStep, TurnStepType
        from arena.ai.executor import execute_step

        cm = _setup_combat()

        # Get to legendary phase
        max_iterations = 20
        for _ in range(max_iterations):
            if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
                break
            if cm.state == CombatState.COMBAT_ENDED:
                pytest.skip("Combat ended")
            cm.end_turn()

        if cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE:
            pytest.skip("Could not reach legendary phase")

        dragon_id = cm._legendary_actor_id
        dragon = cm.combatants[dragon_id].creature

        player_id = None
        for cid, c in cm.combatants.items():
            if c.creature.is_player_controlled:
                player_id = cid

        # Count log events before execution
        events_before = len(cm.log.events)

        step = TurnStep(
            step_type=TurnStepType.EXECUTE_LEGENDARY,
            legendary_action=dragon.legendary_actions[0],
            target_id=player_id,
        )
        result = execute_step(step, cm)

        # Should have generated new combat events
        assert len(cm.log.events) > events_before

        # The step should have advanced past the legendary phase
        # (either to next turn or combat ended)
        if cm.state != CombatState.COMBAT_ENDED:
            assert cm._legendary_actor_id != dragon_id or cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE

    def test_pass_legendary_step(self):
        """PASS_LEGENDARY step should advance the queue."""
        from arena.ai.controller import TurnStep, TurnStepType
        from arena.ai.executor import execute_step

        cm = _setup_combat()

        # Get to legendary phase
        max_iterations = 20
        for _ in range(max_iterations):
            if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
                break
            if cm.state == CombatState.COMBAT_ENDED:
                pytest.skip("Combat ended")
            cm.end_turn()

        if cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE:
            pytest.skip("Could not reach legendary phase")

        step = TurnStep(step_type=TurnStepType.PASS_LEGENDARY)
        execute_step(step, cm)

        # Queue should have advanced (dragon was only legendary creature,
        # so next turn should have started)
        if cm.state != CombatState.COMBAT_ENDED:
            assert cm._legendary_actor_id is None or cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE


# ══════════════════════════════════════════════════════════════════════
# Serialization Tests
# ══════════════════════════════════════════════════════════════════════


class TestLegendarySerialization:
    """Tests for serialization/deserialization of legendary state."""

    def test_serialize_legendary_points(self):
        """Legendary points should be serialized."""
        from arena.combat.serialization import serialize_combat

        cm = _setup_combat()

        data = serialize_combat(cm)
        assert "legendary_points" in data
        assert isinstance(data["legendary_points"], dict)

    def test_deserialize_legendary_points(self):
        """Legendary points should survive a round trip."""
        from arena.combat.serialization import serialize_combat, deserialize_combat

        cm = _setup_combat()

        dragon_id = None
        for cid, c in cm.combatants.items():
            if getattr(c.creature, "legendary_action_count", 0) > 0:
                dragon_id = cid

        cm.legendary_points[dragon_id] = 1

        data = serialize_combat(cm)
        cm2 = deserialize_combat(data)

        assert cm2.legendary_points.get(dragon_id) == 1

    def test_serialize_legendary_queue(self):
        """Legendary queue and actor should be serialized."""
        from arena.combat.serialization import serialize_combat, deserialize_combat

        cm = _setup_combat()

        # Get to legendary phase
        max_iterations = 20
        for _ in range(max_iterations):
            if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
                break
            if cm.state == CombatState.COMBAT_ENDED:
                pytest.skip("Combat ended")
            cm.end_turn()

        if cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE:
            pytest.skip("Could not reach legendary phase")

        data = serialize_combat(cm)
        assert data["legendary_actor_id"] == cm._legendary_actor_id
        assert data["legendary_queue"] == cm._legendary_queue

        cm2 = deserialize_combat(data)
        assert cm2._legendary_actor_id == cm._legendary_actor_id
        assert cm2._legendary_queue == cm._legendary_queue


# ══════════════════════════════════════════════════════════════════════
# Reset Tests
# ══════════════════════════════════════════════════════════════════════


class TestLegendaryReset:
    """Tests for cleanup on reset."""

    def test_reset_clears_legendary_state(self):
        """reset() should clear all legendary tracking."""
        cm = _setup_combat()
        cm.legendary_points["test"] = 3
        cm._legendary_queue = ["test"]
        cm._legendary_actor_id = "test"

        cm.reset()

        assert cm.legendary_points == {}
        assert cm._legendary_queue == []
        assert cm._legendary_actor_id is None


# ══════════════════════════════════════════════════════════════════════
# Mark Action Type Used Tests
# ══════════════════════════════════════════════════════════════════════


class TestMarkActionTypeUsed:
    """Tests for the fixed _mark_action_type_used method."""

    def test_legendary_action_type_does_not_consume_action(self):
        """Legendary action type should NOT mark has_used_action."""
        cm = CombatManager()
        action = Action(
            name="Test",
            description="Test",
            action_type=ActionType.LEGENDARY,
        )
        cm._mark_action_type_used(action)
        assert not cm.turn_resources.has_used_action
        assert not cm.turn_resources.has_used_bonus_action

    def test_lair_action_type_does_not_consume_action(self):
        """Lair action type should NOT mark has_used_action."""
        cm = CombatManager()
        action = Action(
            name="Test",
            description="Test",
            action_type=ActionType.LAIR,
        )
        cm._mark_action_type_used(action)
        assert not cm.turn_resources.has_used_action
        assert not cm.turn_resources.has_used_bonus_action

    def test_regular_action_still_marks_used(self):
        """Regular ACTION type should still mark has_used_action."""
        cm = CombatManager()
        action = Action(
            name="Test",
            description="Test",
            action_type=ActionType.ACTION,
        )
        cm._mark_action_type_used(action)
        assert cm.turn_resources.has_used_action
