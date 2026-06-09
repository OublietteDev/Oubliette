"""Tests for death save integration with combat manager.

Verifies that process_death_save is called during _start_current_turn
when a PC is unconscious (0 HP), and that the various outcomes
(success, failure, nat 20, stabilization, death) are handled correctly.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager, CombatState, TurnPhase
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import PlayerCharacter, Creature
from arena.models.encounter import Encounter, CombatantEntry


# ── Helpers ───────────────────────────────────────────────────────────

def _make_pc(name="Hero", hp=20, current_hp=None):
    """Create a PlayerCharacter with optional current HP override."""
    pc = PlayerCharacter(
        name=name,
        max_hit_points=hp,
        character_class="Fighter",
        ability_scores=AbilityScores(strength=14, dexterity=14),
        proficiency_bonus=2,
        speed={"walk": 30},
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
    if current_hp is not None:
        pc.current_hit_points = current_hp
    return pc


def _make_enemy(name="Goblin", hp=10):
    return Creature(
        name=name,
        max_hit_points=hp,
        ability_scores=AbilityScores(dexterity=14),
        proficiency_bonus=2,
        speed={"walk": 30},
        is_player_controlled=False,
        ai_profile="default_monster",
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
                    damage=[
                        DamageRoll(
                            dice="1d6",
                            damage_type=DamageType.SLASHING,
                            ability_modifier="dexterity",
                        )
                    ],
                ),
            )
        ],
    )


def _setup_dying_pc_combat():
    """Set up combat where the PC is at 0 HP (dying).

    Returns the CombatManager (already initialized, initiative rolled,
    combat begun — the first turn's death save may have been processed).
    """
    dying_pc = _make_pc("Dying Hero", hp=20, current_hp=0)
    enemy = _make_enemy()

    encounter = Encounter(
        name="Death Save Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="hero",
                creature_data=dying_pc,
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="goblin",
                creature_data=enemy,
                team="enemy",
                starting_position=(5, 5),
            ),
        ],
    )

    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    cm.roll_initiative()
    cm.begin_combat()
    return cm


def _run_turns(cm, max_turns=10):
    """Run turns until combat ends or max turns reached."""
    for _ in range(max_turns):
        if cm.state == CombatState.COMBAT_ENDED:
            break
        cm.end_turn()


def _get_hero(cm):
    """Find the hero combatant regardless of ID slugification."""
    for cid, c in cm.combatants.items():
        if c.creature.name == "Dying Hero":
            return c
    return None


# ── Tests ─────────────────────────────────────────────────────────────

class TestDeathSaveIntegration:
    """Test that death saves are processed during turn management."""

    @patch("arena.combat.death_saves.roll_die")
    def test_death_save_processed_on_unconscious_pc_turn(self, mock_d20):
        """When an unconscious PC's turn starts, a death save should roll."""
        mock_d20.return_value = 12  # Success
        cm = _setup_dying_pc_combat()

        # Run a few turns to ensure the hero's turn processes
        _run_turns(cm, 6)

        # Check the combat log for death save events
        ds_events = [
            e for e in cm.log.events
            if e.event_type == CombatEventType.DEATH_SAVE
        ]
        assert len(ds_events) >= 1, "Death save should have been processed"
        assert "SUCCESS" in ds_events[0].message

    @patch("arena.combat.death_saves.roll_die")
    def test_nat20_restores_consciousness(self, mock_d20):
        """A natural 20 on death save should restore the PC to 1 HP."""
        mock_d20.return_value = 20  # Nat 20

        cm = _setup_dying_pc_combat()
        hero = _get_hero(cm)
        assert hero is not None

        # Run a few turns
        _run_turns(cm, 6)

        # After nat 20, hero should be conscious with 1 HP
        assert hero.creature.current_hit_points == 1
        assert hero.creature.is_conscious
        # Death saves should be reset
        assert hero.creature.death_save_successes == 0
        assert hero.creature.death_save_failures == 0

    @patch("arena.combat.death_saves.roll_die")
    def test_failure_accumulates(self, mock_d20):
        """Failed death saves should accumulate on the creature."""
        mock_d20.return_value = 5  # Failure

        cm = _setup_dying_pc_combat()
        hero = _get_hero(cm)
        assert hero is not None

        # Run enough turns for at least one hero turn
        _run_turns(cm, 3)

        # Hero should have accumulated failures
        assert hero.creature.death_save_failures >= 1
        assert hero.creature.current_hit_points == 0

    @patch("arena.combat.death_saves.roll_die")
    def test_three_failures_causes_death(self, mock_d20):
        """Three death save failures should kill the creature and end combat."""
        mock_d20.return_value = 3  # Failure

        cm = _setup_dying_pc_combat()
        hero = _get_hero(cm)
        assert hero is not None

        # Run until combat ends
        _run_turns(cm, 20)

        # Hero should have 3 failures and combat should have ended
        assert hero.creature.death_save_failures == 3
        assert cm.state == CombatState.COMBAT_ENDED
        assert cm.winner == "enemy"
        death_events = [
            e for e in cm.log.events
            if "died" in e.message.lower()
        ]
        assert len(death_events) >= 1

    @patch("arena.combat.death_saves.roll_die")
    def test_three_failures_with_preexisting(self, mock_d20):
        """Pre-existing failures + new failure should trigger death."""
        mock_d20.return_value = 4  # Failure

        cm = _setup_dying_pc_combat()
        hero = _get_hero(cm)
        assert hero is not None

        # Set 2 existing failures
        hero.creature.death_save_failures = 2

        # Run turns - next failure should kill
        _run_turns(cm, 10)

        assert hero.creature.death_save_failures == 3
        assert cm.state == CombatState.COMBAT_ENDED

    @patch("arena.combat.death_saves.roll_die")
    def test_dying_pc_does_not_immediately_lose(self, mock_d20):
        """A PC at 0 HP should NOT cause immediate defeat (they're still dying)."""
        mock_d20.return_value = 15  # Success on death saves

        cm = _setup_dying_pc_combat()
        hero = _get_hero(cm)
        assert hero is not None

        # Hero at 0 HP with 0 failures should not end combat
        assert hero.creature.current_hit_points == 0
        assert cm.state == CombatState.IN_COMBAT  # NOT ended

    @patch("arena.combat.death_saves.roll_die")
    def test_stabilization_after_three_successes(self, mock_d20):
        """Three successful death saves should stabilize the creature."""
        mock_d20.return_value = 15  # Success

        cm = _setup_dying_pc_combat()
        hero = _get_hero(cm)
        assert hero is not None

        # Run enough turns for 3 successes (each hero turn = 1 success)
        _run_turns(cm, 20)

        # Check that stabilization event occurred
        stabilize_events = [
            e for e in cm.log.events
            if "stabilized" in e.message.lower()
        ]
        assert len(stabilize_events) >= 1

        # Creature should be marked as stabilized
        assert hero.creature.is_stabilized is True

        # Stabilization should only happen ONCE (no repeated death saves)
        assert len(stabilize_events) == 1

    @patch("arena.combat.death_saves.roll_die")
    def test_stabilized_creature_stops_rolling(self, mock_d20):
        """A stabilized creature should not make further death saves."""
        mock_d20.return_value = 15  # Success

        cm = _setup_dying_pc_combat()
        hero = _get_hero(cm)
        assert hero is not None

        # Run many turns
        _run_turns(cm, 20)

        # Count total death save events — should be exactly 3 (one per success)
        ds_events = [
            e for e in cm.log.events
            if e.event_type == CombatEventType.DEATH_SAVE
        ]
        assert len(ds_events) == 3, (
            f"Expected exactly 3 death save rolls, got {len(ds_events)}"
        )

        # After that, should see "unconscious but stable" messages
        stable_msgs = [
            e for e in cm.log.events
            if "unconscious but stable" in e.message.lower()
        ]
        assert len(stable_msgs) >= 1


class TestActionSurge:
    """Test Action Surge standard action."""

    def _make_fighter_combat(self):
        """Set up combat with a Fighter who has action_surge resource."""
        fighter = PlayerCharacter(
            name="Fighter",
            max_hit_points=30,
            character_class="Fighter",
            ability_scores=AbilityScores(strength=16, dexterity=14),
            proficiency_bonus=2,
            speed={"walk": 30},
            is_player_controlled=True,
            class_resources={"action_surge": 1, "second_wind": 1},
            actions=[
                Action(
                    name="Longsword",
                    description="Melee weapon attack",
                    action_type=ActionType.ACTION,
                    attack=Attack(
                        name="Longsword",
                        attack_type="melee_weapon",
                        ability="strength",
                        reach=5,
                        damage=[
                            DamageRoll(
                                dice="1d8",
                                damage_type=DamageType.SLASHING,
                                ability_modifier="strength",
                            )
                        ],
                    ),
                )
            ],
        )

        enemy = _make_enemy()

        encounter = Encounter(
            name="Action Surge Test",
            grid_width=10,
            grid_height=10,
            combatants=[
                CombatantEntry(
                    creature_id="fighter",
                    creature_data=fighter,
                    team="player",
                    starting_position=(2, 2),
                ),
                CombatantEntry(
                    creature_id="goblin",
                    creature_data=enemy,
                    team="enemy",
                    starting_position=(5, 5),
                ),
            ],
        )

        cm = CombatManager()
        cm.load_encounter(encounter, Path("."))
        cm.roll_initiative()
        cm.begin_combat()
        return cm

    def _skip_to_fighter(self, cm):
        """Skip turns until the Fighter is active."""
        for _ in range(10):
            active = cm.active_combatant
            if active and active.creature.name == "Fighter":
                return active
            cm.end_turn()
        return None

    def test_action_surge_resets_action(self):
        """Action Surge should reset the action slot after it's been used."""
        cm = self._make_fighter_combat()
        fighter = self._skip_to_fighter(cm)
        assert fighter is not None

        # Use the action (e.g., Dash)
        cm.execute_standard_action("dash")
        assert cm.turn_resources.has_used_action is True

        # Use Action Surge
        event = cm.execute_standard_action("action_surge")
        assert event is not None
        assert "Action Surge" in event.message

        # Action slot should be reset
        assert cm.turn_resources.has_used_action is False

        # Resource should be decremented
        assert fighter.creature.class_resources["action_surge"] == 0

    def test_action_surge_no_resource_fails(self):
        """Action Surge should fail if no uses remain."""
        cm = self._make_fighter_combat()
        fighter = self._skip_to_fighter(cm)
        assert fighter is not None

        # Deplete the resource
        fighter.creature.class_resources["action_surge"] = 0

        # Try to use Action Surge
        event = cm.execute_standard_action("action_surge")
        assert event is None  # Should fail

    def test_action_surge_allows_second_action(self):
        """After Action Surge, the fighter should be able to use an action again."""
        cm = self._make_fighter_combat()
        fighter = self._skip_to_fighter(cm)
        assert fighter is not None

        # Use action
        cm.execute_standard_action("dash")
        assert cm.turn_resources.has_used_action is True

        # Action Surge
        cm.execute_standard_action("action_surge")
        assert cm.turn_resources.has_used_action is False

        # Use action again (Dodge this time)
        event = cm.execute_standard_action("dodge")
        assert event is not None
        assert "Dodge" in event.message
        assert cm.turn_resources.has_used_action is True

    def test_action_surge_without_action_no_resource(self):
        """A creature without action_surge resource can't use it."""
        cm = self._make_fighter_combat()
        fighter = self._skip_to_fighter(cm)
        assert fighter is not None

        # Remove the resource entirely
        del fighter.creature.class_resources["action_surge"]

        event = cm.execute_standard_action("action_surge")
        assert event is None
