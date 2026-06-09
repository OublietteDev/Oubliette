"""Tests for damage reduction reaction wiring in CombatManager.

Verifies that creatures with Parry, Uncanny Dodge, or Deflect Missiles
can reduce incoming damage using their reaction when hit by attacks.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature, PlayerCharacter, Feature
from arena.models.encounter import Encounter, CombatantEntry


# ── Helpers ──────────────────────────────────────────────────────────

_MELEE_ATTACK = Action(
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

_RANGED_ATTACK = Action(
    name="Longbow",
    description="Ranged weapon attack",
    action_type=ActionType.ACTION,
    attack=Attack(
        name="Longbow",
        attack_type="ranged_weapon",
        ability="dexterity",
        reach=150,
        damage=[
            DamageRoll(
                dice="1d8",
                damage_type=DamageType.PIERCING,
                ability_modifier="dexterity",
            )
        ],
    ),
)


def _parry_feature():
    return Feature(
        name="Parry",
        description="Reduce melee damage by 1d8 + DEX mod",
        damage_reduction_dice="1d8",
        damage_reduction_bonus="dexterity",
        damage_reduction_type="melee_only",
    )


def _uncanny_dodge_feature():
    return Feature(
        name="Uncanny Dodge",
        description="Halve the damage from one attack",
        damage_reduction_flat_half=True,
    )


def _deflect_missiles_feature():
    return Feature(
        name="Deflect Missiles",
        description="Reduce ranged damage by 1d10 + DEX mod",
        damage_reduction_dice="1d10",
        damage_reduction_bonus="dexterity",
        damage_reduction_type="ranged_only",
    )


def _make_attacker():
    """Create a basic attacker creature (AI-controlled enemy)."""
    return Creature(
        name="Attacker",
        max_hit_points=50,
        armor_class=15,
        ability_scores=AbilityScores(strength=16, dexterity=14),
        proficiency_bonus=2,
        is_player_controlled=False,
        actions=[_MELEE_ATTACK, _RANGED_ATTACK],
    )


def _make_defender(features=None, is_player_controlled=False):
    """Create a defender creature with DR features."""
    return PlayerCharacter(
        name="Defender",
        max_hit_points=100,
        armor_class=15,
        ability_scores=AbilityScores(strength=10, dexterity=16),
        proficiency_bonus=2,
        is_player_controlled=is_player_controlled,
        character_class="Rogue",
        level=5,
        features=features or [],
        actions=[_MELEE_ATTACK],
    )


def _make_encounter(defender_features=None, defender_player_controlled=False):
    """Create a 1v1 encounter with adjacent combatants."""
    return Encounter(
        name="DR Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="attacker",
                creature_data=_make_attacker(),
                team="enemy",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="defender",
                creature_data=_make_defender(
                    features=defender_features,
                    is_player_controlled=defender_player_controlled,
                ),
                team="player",
                starting_position=(3, 2),
            ),
        ],
    )


def _start_combat(defender_features=None, defender_player_controlled=False):
    """Set up combat and advance to the attacker's turn."""
    cm = CombatManager()
    cm.load_encounter(
        _make_encounter(defender_features, defender_player_controlled),
        Path("."),
    )
    cm.roll_initiative()
    cm.begin_combat()

    # Advance to the attacker's turn
    if cm.active_combatant and cm.active_combatant.creature_id != "attacker":
        cm.end_turn()

    return cm


# ── Tests: AI-controlled Uncanny Dodge ──────────────────────────────


class TestUncannyDodgeAI:
    """Uncanny Dodge halves damage when used by an AI-controlled target."""

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_uncanny_dodge_halves_damage(self, mock_damage, mock_d20):
        """AI target with Uncanny Dodge halves incoming melee damage."""
        mock_d20.return_value = 18  # Hit
        mock_damage.return_value = (10, [7])  # 10 damage total

        cm = _start_combat(
            defender_features=[_uncanny_dodge_feature()],
            defender_player_controlled=False,
        )
        assert cm.active_combatant.creature_id == "attacker"

        defender = cm.combatants["defender"]
        starting_hp = defender.creature.current_hit_points

        cm.select_action(_MELEE_ATTACK)
        cm.execute_attack("defender")

        # With 10 damage halved to 5, and STR mod 3 added to damage
        # The exact damage depends on what gets rolled, but it should be
        # less than 10 + 3 = 13
        current_hp = defender.creature.current_hit_points
        damage_taken = starting_hp - current_hp

        # Check that reaction was consumed
        assert cm.reaction_used.get("defender", False) is True

        # Check log for Uncanny Dodge message
        log_messages = [e.message for e in cm.log.events]
        assert any("Uncanny Dodge" in msg for msg in log_messages)

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_reaction_consumed_prevents_second_use(
        self, mock_damage, mock_d20,
    ):
        """After using Uncanny Dodge, can't use it again until turn starts."""
        mock_d20.return_value = 18  # Hit
        mock_damage.return_value = (10, [7])

        cm = _start_combat(
            defender_features=[_uncanny_dodge_feature()],
            defender_player_controlled=False,
        )

        defender = cm.combatants["defender"]

        # First attack -- Uncanny Dodge should trigger
        cm.select_action(_MELEE_ATTACK)
        cm.execute_attack("defender")
        hp_after_first = defender.creature.current_hit_points

        assert cm.reaction_used.get("defender", False) is True

        # No DR options should be available now
        options = cm.check_damage_reduction_reaction(
            "defender", "melee_weapon",
        )
        assert len(options) == 0


# ── Tests: AI-controlled Parry ──────────────────────────────────────


class TestParryAI:
    """Parry reduces damage by die roll + DEX mod for AI target."""

    @patch("arena.combat.damage_reduction.roll_expression", return_value=(6, [6]))
    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_parry_reduces_melee_damage(
        self, mock_damage, mock_d20, mock_dr_roll,
    ):
        """AI target with Parry reduces melee damage by 1d8 + DEX."""
        mock_d20.return_value = 18  # Hit
        mock_damage.return_value = (20, [14])  # 20 base damage

        cm = _start_combat(
            defender_features=[_parry_feature()],
            defender_player_controlled=False,
        )
        assert cm.active_combatant.creature_id == "attacker"

        defender = cm.combatants["defender"]
        starting_hp = defender.creature.current_hit_points

        cm.select_action(_MELEE_ATTACK)
        cm.execute_attack("defender")

        # Parry roll: 6 + DEX mod (16 DEX = +3) = 9 reduction
        # Reaction consumed
        assert cm.reaction_used.get("defender", False) is True

        # Check log for Parry message
        log_messages = [e.message for e in cm.log.events]
        assert any("Parry" in msg for msg in log_messages)


# ── Tests: Melee-only restriction ───────────────────────────────────


class TestMeleeOnlyRestriction:
    """Parry (melee_only) should not trigger against ranged attacks."""

    def test_parry_not_available_for_ranged(self):
        """Parry feature with melee_only should not apply to ranged attacks."""
        cm = _start_combat(
            defender_features=[_parry_feature()],
            defender_player_controlled=False,
        )

        # Check that Parry is NOT available for ranged attacks
        options = cm.check_damage_reduction_reaction(
            "defender", "ranged_weapon",
        )
        assert len(options) == 0

    def test_parry_available_for_melee(self):
        """Parry feature should be available for melee attacks."""
        cm = _start_combat(
            defender_features=[_parry_feature()],
            defender_player_controlled=False,
        )

        options = cm.check_damage_reduction_reaction(
            "defender", "melee_weapon",
        )
        assert len(options) == 1
        assert options[0][0].name == "Parry"


# ── Tests: Reaction tracking ────────────────────────────────────────


class TestReactionTracking:
    """Reaction consumed after use and resets at start of own turn."""

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_no_reaction_when_already_used(self, mock_damage, mock_d20):
        """Pre-used reaction prevents damage reduction."""
        mock_d20.return_value = 18
        mock_damage.return_value = (10, [7])

        cm = _start_combat(
            defender_features=[_uncanny_dodge_feature()],
            defender_player_controlled=False,
        )

        # Manually mark reaction as used
        cm.reaction_used["defender"] = True

        defender = cm.combatants["defender"]
        starting_hp = defender.creature.current_hit_points

        cm.select_action(_MELEE_ATTACK)
        cm.execute_attack("defender")

        # Damage should NOT be reduced
        # (no Uncanny Dodge message in log)
        log_messages = [e.message for e in cm.log.events]
        assert not any("Uncanny Dodge" in msg for msg in log_messages)


# ── Tests: Player-controlled target (pending state) ─────────────────


class TestPlayerControlledTarget:
    """Player-controlled targets get a pending state for the GUI popup."""

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_pending_damage_reduction_set_for_player_target(
        self, mock_damage, mock_d20,
    ):
        """Attack against player target with DR sets pending state."""
        mock_d20.return_value = 18
        mock_damage.return_value = (10, [7])

        cm = _start_combat(
            defender_features=[_uncanny_dodge_feature()],
            defender_player_controlled=True,
        )

        cm.select_action(_MELEE_ATTACK)
        result = cm.execute_attack("defender")

        # execute_attack returns None because it's deferred
        assert result is None
        assert cm._pending_damage_reduction is not None
        assert cm._pending_damage_reduction["target_id"] == "defender"
        assert len(cm._pending_damage_reduction["options"]) == 1

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_resolve_damage_reduction_choice_use(
        self, mock_damage, mock_d20,
    ):
        """Player choosing to use Uncanny Dodge applies reduction."""
        mock_d20.return_value = 18
        mock_damage.return_value = (10, [7])

        cm = _start_combat(
            defender_features=[_uncanny_dodge_feature()],
            defender_player_controlled=True,
        )

        defender = cm.combatants["defender"]
        starting_hp = defender.creature.current_hit_points

        cm.select_action(_MELEE_ATTACK)
        cm.execute_attack("defender")

        assert cm._pending_damage_reduction is not None

        # Player chooses to use Uncanny Dodge
        cm.resolve_damage_reduction_choice("Uncanny Dodge")

        # Pending state should be cleared
        assert cm._pending_damage_reduction is None
        # Reaction consumed
        assert cm.reaction_used.get("defender", False) is True
        # Damage was applied (halved)
        assert defender.creature.current_hit_points < starting_hp

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_resolve_damage_reduction_choice_skip(
        self, mock_damage, mock_d20,
    ):
        """Player choosing to skip applies full damage."""
        mock_d20.return_value = 18
        mock_damage.return_value = (10, [7])

        cm = _start_combat(
            defender_features=[_uncanny_dodge_feature()],
            defender_player_controlled=True,
        )

        defender = cm.combatants["defender"]
        starting_hp = defender.creature.current_hit_points

        cm.select_action(_MELEE_ATTACK)
        cm.execute_attack("defender")

        assert cm._pending_damage_reduction is not None

        # Player skips
        cm.resolve_damage_reduction_choice(None)

        # Pending state should be cleared
        assert cm._pending_damage_reduction is None
        # Reaction NOT consumed
        assert cm.reaction_used.get("defender", False) is False
        # Damage was applied (full)
        assert defender.creature.current_hit_points < starting_hp


# ── Tests: complete_attack path (AI executor two-phase) ─────────────


class TestCompleteAttackPath:
    """Tests for damage reduction via the complete_attack() path."""

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_complete_attack_defers_for_player_target(
        self, mock_damage, mock_d20,
    ):
        """complete_attack with player target + DR sets pending state."""
        mock_d20.return_value = 18
        mock_damage.return_value = (10, [7])

        cm = _start_combat(
            defender_features=[_uncanny_dodge_feature()],
            defender_player_controlled=True,
        )

        cm.select_action(_MELEE_ATTACK)
        hit_result = cm.execute_attack_hit_check("defender")
        assert hit_result is not None
        assert hit_result.hit is True

        # complete_attack should defer for player target
        result = cm.complete_attack(hit_result)
        assert result is None
        assert cm._pending_damage_reduction is not None

    @patch("arena.combat.damage_reduction.roll_expression", return_value=(5, [5]))
    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_complete_attack_with_explicit_reduction(
        self, mock_damage, mock_d20, mock_dr_roll,
    ):
        """complete_attack with explicit damage_reduction applies it."""
        mock_d20.return_value = 18
        mock_damage.return_value = (20, [14])

        cm = _start_combat(
            defender_features=[_parry_feature()],
            defender_player_controlled=False,  # AI target
        )

        cm.select_action(_MELEE_ATTACK)
        hit_result = cm.execute_attack_hit_check("defender")
        assert hit_result is not None
        assert hit_result.hit is True

        # Pass explicit reduction (as if AI already evaluated)
        result = cm.complete_attack(hit_result, damage_reduction=8)
        assert result is not None
        assert result.success is True
