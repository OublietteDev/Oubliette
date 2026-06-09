"""Tests for recurring action wiring in CombatManager.

Covers: Witch Bolt (auto-hit recurring), Call Lightning (save-based recurring),
action economy enforcement, concentration-linked removal, duration expiry.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant
from arena.combat.events import CombatEventType
from arena.combat.recurring_actions import ActiveRecurringAction
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action, Attack, DamageRoll, DamageType, ActionType,
    SavingThrowEffect,
)
from arena.models.character import Creature
from arena.models.encounter import Encounter, CombatantEntry
from arena.grid.coordinates import HexCoord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_creature(name, hp, ac=10, strength=10, dexterity=10,
                   constitution=10, is_player=True, actions=None):
    """Create a simple creature for testing."""
    if actions is None:
        actions = [
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
        ]
    return Creature(
        name=name,
        max_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(
            strength=strength, dexterity=dexterity, constitution=constitution,
        ),
        proficiency_bonus=2,
        is_player_controlled=is_player,
        actions=actions,
    )


def _witch_bolt_action():
    """Create a Witch Bolt action with recurring auto-hit damage."""
    return Action(
        name="Witch Bolt",
        description="Ranged spell attack, recurring auto-hit lightning",
        action_type=ActionType.ACTION,
        attack=Attack(
            name="Witch Bolt",
            attack_type="ranged_spell",
            ability="intelligence",
            reach=30,
            damage=[
                DamageRoll(dice="1d12", damage_type=DamageType.LIGHTNING),
            ],
        ),
        range=30,
        requires_concentration=True,
        recurring_action_type="action",
        recurring_damage_dice="1d12",
        recurring_damage_type="lightning",
        recurring_auto_hit=True,
    )


def _call_lightning_action():
    """Create a Call Lightning action with recurring save-based damage."""
    return Action(
        name="Call Lightning",
        description="Conjure a storm cloud; call bolts each turn",
        action_type=ActionType.ACTION,
        saving_throw=SavingThrowEffect(
            ability="dexterity",
            dc=15,
            damage_on_fail=[
                DamageRoll(dice="3d10", damage_type=DamageType.LIGHTNING),
            ],
            damage_on_success="half",
        ),
        range=120,
        requires_concentration=True,
        recurring_action_type="action",
        recurring_damage_dice="3d10",
        recurring_damage_type="lightning",
    )


def _setup_combat(player_actions=None, enemy_hp=50):
    """Set up a 2-combatant combat and start it.

    Returns (cm, player_id, enemy_id).
    Initiative is rigged so the player always goes first.
    """
    player = _make_creature(
        "Wizard", hp=30, ac=12, strength=8, dexterity=14,
        constitution=14, is_player=True, actions=player_actions,
    )
    enemy = _make_creature(
        "Ogre", hp=enemy_hp, ac=11, dexterity=8,
        constitution=16, is_player=False,
    )

    encounter = Encounter(
        name="Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="inline_wizard",
                creature_data=player,
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="inline_ogre",
                creature_data=enemy,
                team="enemy",
                starting_position=(3, 2),
            ),
        ],
    )

    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))

    # Rig initiative: player first
    with patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
        cm.roll_initiative()
    cm.begin_combat()

    # Find actual IDs (load_encounter may mangle them)
    player_id = None
    enemy_id = None
    for cid, c in cm.combatants.items():
        if c.team == "player":
            player_id = cid
        else:
            enemy_id = cid

    assert cm.active_combatant.creature_id == player_id, (
        "Player should go first"
    )

    return cm, player_id, enemy_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWitchBoltRecurring:
    """Witch Bolt: attack-based spell with auto-hit recurring damage."""

    def test_witch_bolt_creates_recurring_action(self):
        """Casting Witch Bolt should register a recurring action."""
        wb = _witch_bolt_action()
        cm, player_id, enemy_id = _setup_combat(player_actions=[wb])

        # Cast Witch Bolt (attack roll hits)
        cm.select_action(wb)
        with patch("arena.combat.actions.roll_die", return_value=18):
            result = cm.execute_attack(enemy_id)
        assert result is not None and result.success

        # A recurring action should now be registered
        recurring = cm.get_recurring_action_for(player_id)
        assert recurring is not None
        assert recurring.action_name == "Witch Bolt"
        assert recurring.auto_hit is True
        assert recurring.linked_to_concentration is True

    def test_witch_bolt_recurring_deals_auto_hit_damage(self):
        """On subsequent turns, recurring Witch Bolt auto-hits."""
        wb = _witch_bolt_action()
        cm, player_id, enemy_id = _setup_combat(
            player_actions=[wb], enemy_hp=100,
        )

        # Cast Witch Bolt
        cm.select_action(wb)
        with patch("arena.combat.actions.roll_die", return_value=18):
            cm.execute_attack(enemy_id)

        # End player turn, enemy turn, back to player
        cm.end_turn()  # player ends
        cm.end_turn()  # enemy ends (or skip)
        # Now it's the player's turn again
        assert cm.active_combatant.creature_id == player_id

        enemy_hp_before = cm.combatants[enemy_id].creature.current_hit_points

        # Use recurring action (auto-hit, no attack roll needed)
        with patch("arena.util.dice.roll_die", return_value=8):
            result = cm.execute_recurring_action(enemy_id)

        assert result is not None
        assert result.success
        enemy_hp_after = cm.combatants[enemy_id].creature.current_hit_points
        assert enemy_hp_after < enemy_hp_before

    def test_witch_bolt_recurring_uses_action_economy(self):
        """Recurring action should consume the action slot."""
        wb = _witch_bolt_action()
        cm, player_id, enemy_id = _setup_combat(
            player_actions=[wb], enemy_hp=100,
        )

        # Cast, end turns, come back
        cm.select_action(wb)
        with patch("arena.combat.actions.roll_die", return_value=18):
            cm.execute_attack(enemy_id)
        cm.end_turn()
        cm.end_turn()

        # Use recurring action
        with patch("arena.util.dice.roll_die", return_value=6):
            result = cm.execute_recurring_action(enemy_id)
        assert result.success
        assert cm.turn_resources.has_used_action is True

        # Can't use it again (action already spent)
        with patch("arena.util.dice.roll_die", return_value=6):
            result2 = cm.execute_recurring_action(enemy_id)
        assert result2 is None


class TestRecurringActionConcentration:
    """Recurring actions linked to concentration end when concentration drops."""

    def test_recurring_removed_on_concentration_loss(self):
        """Breaking concentration should remove the recurring action."""
        wb = _witch_bolt_action()
        cm, player_id, enemy_id = _setup_combat(
            player_actions=[wb], enemy_hp=100,
        )

        # Cast Witch Bolt
        cm.select_action(wb)
        with patch("arena.combat.actions.roll_die", return_value=18):
            cm.execute_attack(enemy_id)
        assert cm.get_recurring_action_for(player_id) is not None

        # Break concentration manually
        from arena.combat.concentration import end_concentration
        player_creature = cm.combatants[player_id].creature
        end_concentration(player_creature, player_id, cm.combatants)

        # Trigger cleanup (normally happens after an attack)
        cm._cleanup_orphaned_recurring_actions()

        assert cm.get_recurring_action_for(player_id) is None

    def test_recurring_removed_when_damage_breaks_concentration(self):
        """Taking damage that breaks concentration should remove recurring action."""
        wb = _witch_bolt_action()
        cm, player_id, enemy_id = _setup_combat(
            player_actions=[wb], enemy_hp=100,
        )

        # Cast Witch Bolt
        cm.select_action(wb)
        with patch("arena.combat.actions.roll_die", return_value=18):
            cm.execute_attack(enemy_id)

        # End player turn, now enemy attacks player
        cm.end_turn()

        # Enemy's turn — attack the wizard
        assert cm.active_combatant.creature_id == enemy_id
        enemy_action = cm.combatants[enemy_id].creature.actions[0]
        cm.select_action(enemy_action)

        # Force a hit + massive damage so concentration fails
        # Roll 20 to hit, then roll high damage, then roll 1 on con save
        with patch("arena.combat.actions.roll_die", side_effect=[20, 6, 1]):
            result = cm.execute_attack(player_id)

        # The wizard should have lost concentration (failed save with roll of 1)
        # and the recurring action should be cleaned up
        recurring = cm.get_recurring_action_for(player_id)
        # If the wizard failed the save, recurring should be gone
        from arena.combat.conditions import has_condition
        from arena.models.conditions import Condition
        wizard = cm.combatants[player_id].creature
        if not has_condition(wizard, Condition.CONCENTRATING):
            assert recurring is None


class TestCallLightningRecurring:
    """Call Lightning: save-based recurring action."""

    def test_call_lightning_creates_recurring_action(self):
        """Casting Call Lightning should register a save-based recurring action."""
        cl = _call_lightning_action()
        cm, player_id, enemy_id = _setup_combat(
            player_actions=[cl], enemy_hp=100,
        )

        # Cast Call Lightning (save-based effect)
        cm.select_action(cl)
        # Target fails the save (roll 1)
        with patch("arena.combat.actions.roll_die", return_value=1):
            result = cm.execute_effect(enemy_id)
        assert result is not None and result.success

        recurring = cm.get_recurring_action_for(player_id)
        assert recurring is not None
        assert recurring.action_name == "Call Lightning"
        assert recurring.auto_hit is False
        assert recurring.damage_dice == "3d10"

    def test_call_lightning_recurring_resolves_save(self):
        """Recurring Call Lightning should prompt a saving throw."""
        cl = _call_lightning_action()
        cm, player_id, enemy_id = _setup_combat(
            player_actions=[cl], enemy_hp=100,
        )

        # Cast Call Lightning
        cm.select_action(cl)
        with patch("arena.combat.actions.roll_die", return_value=1):
            cm.execute_effect(enemy_id)

        # Advance turns
        cm.end_turn()
        cm.end_turn()

        enemy_hp_before = cm.combatants[enemy_id].creature.current_hit_points

        # Use recurring: target fails save (roll 1), damage rolls 5 each
        with patch("arena.util.dice.roll_die", return_value=5):
            result = cm.execute_recurring_action(enemy_id)

        assert result is not None
        assert result.success
        enemy_hp_after = cm.combatants[enemy_id].creature.current_hit_points
        assert enemy_hp_after < enemy_hp_before

        # Check a SAVING_THROW event was generated
        save_events = [
            e for e in result.events
            if e.event_type == CombatEventType.SAVING_THROW
        ]
        assert len(save_events) > 0


class TestRecurringActionDuration:
    """Recurring actions with remaining_rounds expire after N turns."""

    def test_duration_expires(self):
        """A recurring action with remaining_rounds=1 should expire after 1 turn tick."""
        wb = _witch_bolt_action()
        cm, player_id, enemy_id = _setup_combat(
            player_actions=[wb], enemy_hp=100,
        )

        # Cast Witch Bolt
        cm.select_action(wb)
        with patch("arena.combat.actions.roll_die", return_value=18):
            cm.execute_attack(enemy_id)

        # Manually set remaining_rounds to 1
        recurring = cm.get_recurring_action_for(player_id)
        assert recurring is not None
        recurring.remaining_rounds = 1

        # End turn cycle (player -> enemy -> player again)
        cm.end_turn()
        cm.end_turn()

        # The tick happens at start of player's turn — should expire
        assert cm.active_combatant.creature_id == player_id
        assert cm.get_recurring_action_for(player_id) is None

    def test_duration_ticks_down(self):
        """remaining_rounds decrements each turn start."""
        wb = _witch_bolt_action()
        cm, player_id, enemy_id = _setup_combat(
            player_actions=[wb], enemy_hp=100,
        )

        # Cast Witch Bolt
        cm.select_action(wb)
        with patch("arena.combat.actions.roll_die", return_value=18):
            cm.execute_attack(enemy_id)

        # Set 3 rounds remaining
        recurring = cm.get_recurring_action_for(player_id)
        recurring.remaining_rounds = 3

        # Advance one full round
        cm.end_turn()
        cm.end_turn()

        # After player's turn start, should be 2 remaining
        recurring = cm.get_recurring_action_for(player_id)
        assert recurring is not None
        assert recurring.remaining_rounds == 2


class TestRecurringActionEdgeCases:
    """Edge cases: no recurring action, wrong creature, etc."""

    def test_no_recurring_action_returns_none(self):
        """execute_recurring_action returns None when no recurring exists."""
        cm, player_id, enemy_id = _setup_combat(enemy_hp=100)
        assert cm.execute_recurring_action(enemy_id) is None

    def test_recurring_only_for_active_combatant(self):
        """Can only use recurring action on active combatant's turn."""
        wb = _witch_bolt_action()
        cm, player_id, enemy_id = _setup_combat(
            player_actions=[wb], enemy_hp=100,
        )

        # Cast Witch Bolt
        cm.select_action(wb)
        with patch("arena.combat.actions.roll_die", return_value=18):
            cm.execute_attack(enemy_id)

        # End player turn — now it's enemy's turn
        cm.end_turn()
        assert cm.active_combatant.creature_id == enemy_id

        # Enemy trying to use a recurring action (they don't have one)
        result = cm.execute_recurring_action(player_id)
        assert result is None

    def test_concentration_unlimited_duration(self):
        """Concentration-based recurring with no remaining_rounds persists until concentration drops."""
        wb = _witch_bolt_action()
        cm, player_id, enemy_id = _setup_combat(
            player_actions=[wb], enemy_hp=100,
        )

        # Cast Witch Bolt
        cm.select_action(wb)
        with patch("arena.combat.actions.roll_die", return_value=18):
            cm.execute_attack(enemy_id)

        recurring = cm.get_recurring_action_for(player_id)
        assert recurring is not None
        assert recurring.remaining_rounds is None  # unlimited

        # Advance several rounds — should still be there
        for _ in range(5):
            cm.end_turn()
            cm.end_turn()

        recurring = cm.get_recurring_action_for(player_id)
        assert recurring is not None  # still active
