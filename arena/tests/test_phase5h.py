"""Tests for Phase 5h: Reaction System and Opportunity Attacks."""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager, CombatState, TurnPhase
from arena.combat.reactions import (
    check_opportunity_attacks,
    execute_opportunity_attack,
    _get_melee_attack,
)
from arena.combat.events import CombatEventType
from arena.combat.condition_effects import can_take_actions
from arena.combat.conditions import apply_condition
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.models.encounter import Encounter, CombatantEntry
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid


# ── Helpers ───────────────────────────────────────────────────────────

def _make_creature(name, hp=20, speed=30, is_player=True, strength=14):
    return Creature(
        name=name,
        max_hit_points=hp,
        ability_scores=AbilityScores(strength=strength, dexterity=14),
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


def _make_creature_no_melee(name, hp=20, is_player=False):
    """Create a creature with no melee attacks (ranged only)."""
    return Creature(
        name=name,
        max_hit_points=hp,
        ability_scores=AbilityScores(dexterity=14),
        proficiency_bonus=2,
        speed={"walk": 30},
        is_player_controlled=is_player,
        actions=[
            Action(
                name="Bow",
                description="Ranged weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Bow",
                    attack_type="ranged_weapon",
                    ability="dexterity",
                    range_normal=80,
                    damage=[
                        DamageRoll(dice="1d6", damage_type=DamageType.PIERCING)
                    ],
                ),
            )
        ],
    )


def _setup_combat(player_pos=(2, 2), enemy_pos=(3, 2), ally_pos=None):
    """Start a combat with a player and enemy at given positions."""
    combatants = [
        CombatantEntry(
            creature_id="player",
            creature_data=_make_creature("Fighter", is_player=True),
            team="player",
            starting_position=player_pos,
        ),
        CombatantEntry(
            creature_id="enemy",
            creature_data=_make_creature("Goblin", is_player=False),
            team="enemy",
            starting_position=enemy_pos,
        ),
    ]
    if ally_pos:
        combatants.append(
            CombatantEntry(
                creature_id="ally",
                creature_data=_make_creature("Cleric", is_player=True),
                team="player",
                starting_position=ally_pos,
            )
        )

    encounter = Encounter(
        name="Test",
        grid_width=10,
        grid_height=10,
        combatants=combatants,
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    cm.roll_initiative()
    cm.begin_combat()
    return cm


def _skip_to_creature(cm, creature_id):
    """Skip turns until the given creature is active."""
    for _ in range(20):
        active = cm.active_combatant
        if active and active.creature_id == creature_id:
            return active
        cm.end_turn()
    return None


# ── _get_melee_attack Tests ──────────────────────────────────────────

class TestGetMeleeAttack:
    def test_finds_melee_action(self):
        creature = _make_creature("Test")
        action = _get_melee_attack(creature)
        assert action is not None
        assert action.attack.attack_type == "melee_weapon"

    def test_returns_none_for_ranged_only(self):
        creature = _make_creature_no_melee("Archer")
        action = _get_melee_attack(creature)
        assert action is None


# ── check_opportunity_attacks Tests ──────────────────────────────────

class TestCheckOpportunityAttacks:
    def _make_combatants(self):
        """Set up combatants dict for unit testing check_opportunity_attacks."""
        from arena.combat.manager import Combatant
        player = Combatant(
            creature_id="player",
            creature=_make_creature("Fighter", is_player=True),
            team="player",
            position=HexCoord(2, 2),
        )
        enemy = Combatant(
            creature_id="enemy",
            creature=_make_creature("Goblin", is_player=False),
            team="enemy",
            position=HexCoord(3, 2),
        )
        return {"player": player, "enemy": enemy}

    def test_triggers_when_leaving_reach(self):
        combatants = self._make_combatants()
        reaction_used = {"player": False, "enemy": False}

        # Player at (2,2), enemy at (3,2) — adjacent (distance 1)
        # Moving to (2, 0) — far from enemy
        from_pos = HexCoord(2, 2)
        to_pos = HexCoord(2, 0)

        attackers = check_opportunity_attacks(
            "player", from_pos, to_pos, combatants, reaction_used, False
        )
        assert len(attackers) == 1
        assert attackers[0][0] == "enemy"

    def test_no_trigger_moving_within_reach(self):
        combatants = self._make_combatants()
        reaction_used = {"player": False, "enemy": False}

        # Move to another hex still adjacent to enemy
        from_pos = HexCoord(2, 2)
        # (2, 3) is also adjacent to (3, 2) — distance 1
        to_pos = HexCoord(2, 3)

        # Check if to_pos is still within reach of enemy
        enemy_pos = combatants["enemy"].position
        if enemy_pos.distance_to(to_pos) <= 1:
            attackers = check_opportunity_attacks(
                "player", from_pos, to_pos, combatants, reaction_used, False
            )
            assert len(attackers) == 0

    def test_disengage_prevents_oa(self):
        combatants = self._make_combatants()
        reaction_used = {"player": False, "enemy": False}

        from_pos = HexCoord(2, 2)
        to_pos = HexCoord(2, 0)

        attackers = check_opportunity_attacks(
            "player", from_pos, to_pos, combatants, reaction_used,
            is_disengaging=True,
        )
        assert len(attackers) == 0

    def test_reaction_already_used(self):
        combatants = self._make_combatants()
        reaction_used = {"player": False, "enemy": True}  # Enemy used reaction

        from_pos = HexCoord(2, 2)
        to_pos = HexCoord(2, 0)

        attackers = check_opportunity_attacks(
            "player", from_pos, to_pos, combatants, reaction_used, False
        )
        assert len(attackers) == 0

    def test_same_team_no_oa(self):
        from arena.combat.manager import Combatant
        player1 = Combatant(
            creature_id="player1",
            creature=_make_creature("Fighter", is_player=True),
            team="player",
            position=HexCoord(2, 2),
        )
        player2 = Combatant(
            creature_id="player2",
            creature=_make_creature("Cleric", is_player=True),
            team="player",
            position=HexCoord(3, 2),
        )
        combatants = {"player1": player1, "player2": player2}
        reaction_used = {"player1": False, "player2": False}

        attackers = check_opportunity_attacks(
            "player1", HexCoord(2, 2), HexCoord(2, 0),
            combatants, reaction_used, False,
        )
        assert len(attackers) == 0

    def test_incapacitated_cant_make_oa(self):
        combatants = self._make_combatants()
        reaction_used = {"player": False, "enemy": False}

        # Stun the enemy
        apply_condition(combatants["enemy"].creature, "enemy", Condition.STUNNED, "test")

        from_pos = HexCoord(2, 2)
        to_pos = HexCoord(2, 0)

        attackers = check_opportunity_attacks(
            "player", from_pos, to_pos, combatants, reaction_used, False
        )
        assert len(attackers) == 0

    def test_unconscious_cant_make_oa(self):
        combatants = self._make_combatants()
        reaction_used = {"player": False, "enemy": False}

        # Knock enemy unconscious
        combatants["enemy"].creature.current_hit_points = 0

        from_pos = HexCoord(2, 2)
        to_pos = HexCoord(2, 0)

        attackers = check_opportunity_attacks(
            "player", from_pos, to_pos, combatants, reaction_used, False
        )
        assert len(attackers) == 0

    def test_no_melee_attack_no_oa(self):
        from arena.combat.manager import Combatant
        player = Combatant(
            creature_id="player",
            creature=_make_creature("Fighter", is_player=True),
            team="player",
            position=HexCoord(2, 2),
        )
        archer = Combatant(
            creature_id="archer",
            creature=_make_creature_no_melee("Archer"),
            team="enemy",
            position=HexCoord(3, 2),
        )
        combatants = {"player": player, "archer": archer}
        reaction_used = {"player": False, "archer": False}

        attackers = check_opportunity_attacks(
            "player", HexCoord(2, 2), HexCoord(2, 0),
            combatants, reaction_used, False,
        )
        assert len(attackers) == 0


# ── execute_opportunity_attack Tests ─────────────────────────────────

class TestExecuteOpportunityAttack:
    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_oa_resolves_and_uses_reaction(self, mock_damage, mock_d20):
        from arena.combat.manager import Combatant
        mock_d20.return_value = 15
        mock_damage.return_value = (5, [5])

        grid = HexGrid(10, 10)
        grid.place_creature(HexCoord(3, 2), "enemy")
        grid.place_creature(HexCoord(2, 2), "player")

        enemy = Combatant(
            creature_id="enemy",
            creature=_make_creature("Goblin", is_player=False),
            team="enemy",
            position=HexCoord(3, 2),
        )
        player = Combatant(
            creature_id="player",
            creature=_make_creature("Fighter", is_player=True),
            team="player",
            position=HexCoord(2, 2),
        )

        melee_action = _get_melee_attack(enemy.creature)
        reaction_used = {"enemy": False, "player": False}

        result = execute_opportunity_attack(
            "enemy", enemy, "player", player, melee_action,
            grid, reaction_used,
        )

        # Reaction should be consumed
        assert reaction_used["enemy"] is True

        # Should have announcement event
        assert result.events[0].event_type == CombatEventType.REACTION
        assert "opportunity attack" in result.events[0].message

        # Attack event follows
        assert len(result.events) >= 2
        assert result.events[1].event_type == CombatEventType.ATTACK_ROLL


# ── Integration: try_move with OA Tests ──────────────────────────────

class TestTryMoveOpportunityAttack:
    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_oa_triggers_on_move_away(self, mock_damage, mock_d20):
        """Moving away from an enemy triggers an opportunity attack."""
        mock_d20.return_value = 10  # Will miss AC 10+
        mock_damage.return_value = (3, [3])

        cm = _setup_combat(player_pos=(2, 2), enemy_pos=(3, 2))
        active = _skip_to_creature(cm, "player")
        if active is None:
            # Player might not go first; skip to them
            pytest.skip("Could not get player turn")

        # The player is at (2,2), enemy at (3,2). Move player away.
        # Find an empty neighbor hex that's farther from enemy
        target = HexCoord(2, 0)  # Far from enemy

        # Check that there's an OA logged
        log_before = len(cm.log.events)
        cm.try_move(target)

        # Look for reaction event in the log
        reaction_events = [
            e for e in cm.log.events[log_before:]
            if e.event_type == CombatEventType.REACTION
        ]
        assert len(reaction_events) >= 1
        assert "opportunity attack" in reaction_events[0].message

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_disengage_prevents_oa_on_move(self, mock_damage, mock_d20):
        """Using Disengage prevents OA when moving away."""
        mock_d20.return_value = 18
        mock_damage.return_value = (10, [10])

        cm = _setup_combat(player_pos=(2, 2), enemy_pos=(3, 2))
        active = _skip_to_creature(cm, "player")
        if active is None:
            pytest.skip("Could not get player turn")

        # Use Disengage first
        cm.execute_standard_action("disengage")

        # Now move away
        log_before = len(cm.log.events)
        cm.try_move(HexCoord(2, 0))

        # No reaction event should be logged
        reaction_events = [
            e for e in cm.log.events[log_before:]
            if e.event_type == CombatEventType.REACTION
        ]
        assert len(reaction_events) == 0

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_oa_knockout_cancels_move(self, mock_damage, mock_d20):
        """If the opportunity attack knocks out the mover, the move is cancelled."""
        mock_d20.return_value = 20  # Crit
        mock_damage.return_value = (50, [50])  # Lethal damage

        cm = _setup_combat(player_pos=(2, 2), enemy_pos=(3, 2))
        active = _skip_to_creature(cm, "player")
        if active is None:
            pytest.skip("Could not get player turn")

        original_pos = active.position
        result = cm.try_move(HexCoord(2, 0))

        # Move should fail because creature was knocked out
        assert result is False
        # Creature should still be at original position
        assert active.position == original_pos

    def test_reaction_resets_at_turn_start(self):
        """A creature's reaction should reset at the start of their turn."""
        cm = _setup_combat(player_pos=(2, 2), enemy_pos=(3, 2))

        # Mark enemy's reaction as used
        cm.reaction_used["enemy"] = True
        assert cm.reaction_used["enemy"] is True

        # Skip to enemy's turn
        enemy = _skip_to_creature(cm, "enemy")
        if enemy is None:
            pytest.skip("Could not get enemy turn")

        # Reaction should be reset
        assert cm.reaction_used["enemy"] is False

    def test_reaction_used_cleared_on_reset(self):
        """Reset should clear all reaction tracking."""
        cm = _setup_combat()
        cm.reaction_used["player"] = True
        cm.reaction_used["enemy"] = True
        cm.reset()
        assert cm.reaction_used == {}


# ── Edge Cases ───────────────────────────────────────────────────────

class TestOpportunityAttackEdgeCases:
    def test_no_oa_when_not_in_reach(self):
        """Enemy far away should not trigger OA."""
        from arena.combat.manager import Combatant
        player = Combatant(
            creature_id="player",
            creature=_make_creature("Fighter", is_player=True),
            team="player",
            position=HexCoord(2, 2),
        )
        enemy = Combatant(
            creature_id="enemy",
            creature=_make_creature("Goblin", is_player=False),
            team="enemy",
            position=HexCoord(8, 8),  # Far away
        )
        combatants = {"player": player, "enemy": enemy}
        reaction_used = {"player": False, "enemy": False}

        attackers = check_opportunity_attacks(
            "player", HexCoord(2, 2), HexCoord(2, 3),
            combatants, reaction_used, False,
        )
        assert len(attackers) == 0

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_only_one_oa_per_reaction(self, mock_damage, mock_d20):
        """Each creature can only make one OA per round (reaction limit)."""
        mock_d20.return_value = 10
        mock_damage.return_value = (3, [3])

        from arena.combat.manager import Combatant
        player = Combatant(
            creature_id="player",
            creature=_make_creature("Fighter", is_player=True),
            team="player",
            position=HexCoord(2, 2),
        )
        enemy = Combatant(
            creature_id="enemy",
            creature=_make_creature("Goblin", is_player=False),
            team="enemy",
            position=HexCoord(3, 2),
        )
        combatants = {"player": player, "enemy": enemy}
        reaction_used = {"player": False, "enemy": False}

        # First check — should trigger
        attackers1 = check_opportunity_attacks(
            "player", HexCoord(2, 2), HexCoord(2, 0),
            combatants, reaction_used, False,
        )
        assert len(attackers1) == 1

        # Execute the OA (marks reaction as used)
        grid = HexGrid(10, 10)
        grid.place_creature(HexCoord(3, 2), "enemy")
        grid.place_creature(HexCoord(2, 2), "player")
        execute_opportunity_attack(
            "enemy", enemy, "player", player, attackers1[0][2],
            grid, reaction_used,
        )

        # Second check — should not trigger (reaction used)
        attackers2 = check_opportunity_attacks(
            "player", HexCoord(2, 0), HexCoord(2, 2),
            combatants, reaction_used, False,
        )
        assert len(attackers2) == 0
