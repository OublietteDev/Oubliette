"""Tests for Phase 5j: Bonus Action Attacks (Two-Weapon Fighting)."""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.encounter import Encounter, CombatantEntry


# ── Helpers ───────────────────────────────────────────────────────────

def _make_twf_creature(name, hp=20, is_player=True):
    """Create a creature with a light melee weapon (eligible for TWF)."""
    return Creature(
        name=name,
        max_hit_points=hp,
        ability_scores=AbilityScores(strength=14, dexterity=14),
        proficiency_bonus=2,
        speed={"walk": 30},
        is_player_controlled=is_player,
        actions=[
            Action(
                name="Shortsword",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Shortsword",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=5,
                    damage=[
                        DamageRoll(dice="1d6", damage_type=DamageType.PIERCING,
                                   ability_modifier="strength")
                    ],
                    properties=["light", "finesse"],
                ),
            )
        ],
    )


def _make_non_light_creature(name, hp=20, is_player=True):
    """Create a creature with a non-light melee weapon (no TWF)."""
    return Creature(
        name=name,
        max_hit_points=hp,
        ability_scores=AbilityScores(strength=16),
        proficiency_bonus=2,
        speed={"walk": 30},
        is_player_controlled=is_player,
        actions=[
            Action(
                name="Greatsword",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Greatsword",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=5,
                    damage=[
                        DamageRoll(dice="2d6", damage_type=DamageType.SLASHING,
                                   ability_modifier="strength")
                    ],
                    properties=["heavy", "two-handed"],
                ),
            )
        ],
    )


def _setup_combat(player_creature=None, enemy_creature=None):
    """Start combat with given creatures adjacent to each other."""
    if player_creature is None:
        player_creature = _make_twf_creature("Rogue", is_player=True)
    if enemy_creature is None:
        enemy_creature = _make_twf_creature("Goblin", is_player=False)

    encounter = Encounter(
        name="Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="player",
                creature_data=player_creature,
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="enemy",
                creature_data=enemy_creature,
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


def _skip_to_player(cm):
    """Skip turns until a player-controlled combatant is active."""
    for _ in range(20):
        active = cm.active_combatant
        if active and active.creature.is_player_controlled:
            return active
        cm.end_turn()
    return None


def _get_enemy_id(cm):
    """Find the ID of the first enemy combatant."""
    for cid, c in cm.combatants.items():
        if c.team == "enemy":
            return cid
    return None


# ── Attack model properties Tests ────────────────────────────────────

class TestAttackProperties:
    def test_properties_field_exists(self):
        attack = Attack(
            name="Dagger",
            attack_type="melee_weapon",
            ability="dexterity",
            properties=["light", "finesse", "thrown"],
        )
        assert "light" in attack.properties
        assert "finesse" in attack.properties

    def test_properties_default_empty(self):
        attack = Attack(
            name="Longsword",
            attack_type="melee_weapon",
            ability="strength",
        )
        assert attack.properties == []


# ── can_two_weapon_fight Tests ───────────────────────────────────────

class TestCanTwoWeaponFight:
    def test_not_available_before_action(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")
        # No action used yet
        assert cm.can_two_weapon_fight() is False

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_available_after_melee_attack(self, mock_dmg, mock_d20):
        mock_d20.return_value = 15
        mock_dmg.return_value = (5, [5])

        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        # Use main action attack
        enemy_id = _get_enemy_id(cm)
        cm.selected_action = active.creature.actions[0]
        cm.execute_attack(enemy_id)

        # Now TWF should be available
        assert cm.can_two_weapon_fight() is True

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_not_available_with_non_light_weapon(self, mock_dmg, mock_d20):
        mock_d20.return_value = 15
        mock_dmg.return_value = (5, [5])

        player = _make_non_light_creature("Fighter", is_player=True)
        cm = _setup_combat(player_creature=player)
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        # Use main action
        enemy_id = _get_enemy_id(cm)
        cm.selected_action = active.creature.actions[0]
        cm.execute_attack(enemy_id)

        # No light weapon -> no TWF
        assert cm.can_two_weapon_fight() is False

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_not_available_if_bonus_action_used(self, mock_dmg, mock_d20):
        mock_d20.return_value = 15
        mock_dmg.return_value = (5, [5])

        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        enemy_id = _get_enemy_id(cm)
        cm.selected_action = active.creature.actions[0]
        cm.execute_attack(enemy_id)
        cm.turn_resources.has_used_bonus_action = True

        assert cm.can_two_weapon_fight() is False


# ── execute_bonus_action_attack Tests ────────────────────────────────

class TestExecuteBonusActionAttack:
    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_twf_attack_resolves(self, mock_dmg, mock_d20):
        mock_d20.return_value = 18
        mock_dmg.return_value = (4, [4])

        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        # Main action attack
        enemy_id = _get_enemy_id(cm)
        cm.selected_action = active.creature.actions[0]
        cm.execute_attack(enemy_id)

        # TWF bonus attack
        result = cm.execute_bonus_action_attack(enemy_id)
        assert result is not None
        assert result.success is True

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_twf_consumes_bonus_action(self, mock_dmg, mock_d20):
        mock_d20.return_value = 18
        mock_dmg.return_value = (4, [4])

        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        enemy_id = _get_enemy_id(cm)
        cm.selected_action = active.creature.actions[0]
        cm.execute_attack(enemy_id)

        cm.execute_bonus_action_attack(enemy_id)
        assert cm.turn_resources.has_used_bonus_action is True

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_twf_no_ability_mod_on_damage(self, mock_dmg, mock_d20):
        mock_d20.return_value = 18
        mock_dmg.return_value = (4, [4])

        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        enemy_id = _get_enemy_id(cm)
        cm.selected_action = active.creature.actions[0]
        cm.execute_attack(enemy_id)

        # The TWF attack should not add ability modifier to damage
        result = cm.execute_bonus_action_attack(enemy_id)
        assert result is not None
        # The damage event should reflect dice-only damage (no +2 str mod)
        # mock returns (4, [4]) so damage should be 4 (no modifier added)
        dmg_events = [e for e in result.events if e.event_type == CombatEventType.DAMAGE]
        if dmg_events:
            # Damage should be exactly what the mock returned (4),
            # not 4 + 2 (strength mod)
            assert dmg_events[0].details["raw_damage"] == 4

    def test_twf_fails_without_main_action(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        # No main action used
        enemy_id = _get_enemy_id(cm)
        result = cm.execute_bonus_action_attack(enemy_id)
        assert result is None

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_twf_cant_use_twice(self, mock_dmg, mock_d20):
        mock_d20.return_value = 18
        mock_dmg.return_value = (4, [4])

        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        enemy_id = _get_enemy_id(cm)
        cm.selected_action = active.creature.actions[0]
        cm.execute_attack(enemy_id)

        # First TWF attack succeeds
        result1 = cm.execute_bonus_action_attack(enemy_id)
        assert result1 is not None

        # Second TWF attack fails (bonus action used)
        result2 = cm.execute_bonus_action_attack(enemy_id)
        assert result2 is None
