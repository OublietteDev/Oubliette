"""Tests for forced save reroll wiring into CombatManager.

Verifies that creatures with Indomitable, Lucky, or Diamond Soul
can reroll failed saving throws through the execute_effect() pipeline.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action, Attack, DamageRoll, DamageType, ActionType, SavingThrowEffect,
)
from arena.models.character import Creature, PlayerCharacter, Feature
from arena.models.encounter import Encounter, CombatantEntry


# ── Helpers ──────────────────────────────────────────────────────────


def _indomitable_feature():
    """Fighter Indomitable: reroll a failed saving throw."""
    return Feature(
        name="Indomitable",
        description="Reroll a failed saving throw",
        forced_reroll_saves=True,
        forced_reroll_resource="indomitable_uses",
        forced_reroll_resource_cost=1,
    )


def _diamond_soul_feature():
    """Monk Diamond Soul: reroll a failed save for 1 ki point."""
    return Feature(
        name="Diamond Soul",
        description="Reroll a failed saving throw (1 ki)",
        forced_reroll_saves=True,
        forced_reroll_resource="ki_points",
        forced_reroll_resource_cost=1,
    )


_FIREBALL = Action(
    name="Fireball",
    description="8d6 fire damage, DEX save for half",
    action_type=ActionType.ACTION,
    target_type="one_creature",
    range=150,
    saving_throw=SavingThrowEffect(
        ability="dexterity",
        dc=15,
        damage_on_fail=[
            DamageRoll(dice="8d6", damage_type=DamageType.FIRE),
        ],
        damage_on_success="half",
    ),
)


_HOLD_PERSON = Action(
    name="Hold Person",
    description="WIS save or paralyzed",
    action_type=ActionType.ACTION,
    target_type="one_creature",
    range=60,
    saving_throw=SavingThrowEffect(
        ability="wisdom",
        dc=15,
        conditions_on_fail=["paralyzed"],
    ),
    requires_concentration=True,
)


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
            DamageRoll(dice="1d8", damage_type=DamageType.SLASHING,
                       ability_modifier="strength"),
        ],
    ),
)


def _make_caster():
    """Create an enemy spellcaster."""
    return Creature(
        name="Evil Mage",
        max_hit_points=50,
        armor_class=12,
        ability_scores=AbilityScores(intelligence=18, wisdom=16),
        proficiency_bonus=4,
        is_player_controlled=False,
        actions=[_FIREBALL, _HOLD_PERSON, _MELEE_ATTACK],
    )


def _make_fighter(features=None, class_resources=None):
    """Create a player-controlled Fighter with Indomitable."""
    return PlayerCharacter(
        name="Fighter",
        max_hit_points=80,
        armor_class=18,
        ability_scores=AbilityScores(
            strength=16, dexterity=10, constitution=14, wisdom=10,
        ),
        proficiency_bonus=4,
        is_player_controlled=True,
        character_class="Fighter",
        level=9,
        features=features or [_indomitable_feature()],
        class_resources=class_resources or {"indomitable_uses": 2},
        actions=[_MELEE_ATTACK],
    )


def _make_ai_fighter(features=None, class_resources=None):
    """Create an AI-controlled Fighter with Indomitable.

    Uses PlayerCharacter (not Creature) because features and class_resources
    are PlayerCharacter fields.
    """
    return PlayerCharacter(
        name="AI Fighter",
        max_hit_points=80,
        armor_class=18,
        ability_scores=AbilityScores(
            strength=16, dexterity=10, constitution=14, wisdom=10,
        ),
        proficiency_bonus=4,
        is_player_controlled=False,
        character_class="Fighter",
        level=9,
        features=features or [_indomitable_feature()],
        class_resources=class_resources or {"indomitable_uses": 2},
        actions=[_MELEE_ATTACK],
    )


def _make_encounter(target_creature, caster=None):
    """Create a 1v1 encounter: enemy caster vs player/ally target."""
    if caster is None:
        caster = _make_caster()
    return Encounter(
        name="Reroll Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="caster",
                creature_data=caster,
                team="enemy",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="target",
                creature_data=target_creature,
                team="player",
                starting_position=(3, 2),
            ),
        ],
    )


def _find_id_by_team(cm, team):
    """Find the first combatant ID belonging to the given team."""
    for cid, c in cm.combatants.items():
        if c.team == team:
            return cid
    return None


def _start_combat_caster_turn(target_creature, caster=None):
    """Set up combat and advance to the caster (enemy) turn.

    Returns (cm, caster_id, target_id).
    """
    cm = CombatManager()
    cm.load_encounter(_make_encounter(target_creature, caster), Path("."))
    cm.roll_initiative()
    cm.begin_combat()

    caster_id = _find_id_by_team(cm, "enemy")
    target_id = _find_id_by_team(cm, "player")

    # Advance to the caster's turn if not already active
    if cm.active_combatant and cm.active_combatant.creature_id != caster_id:
        cm.end_turn()
    assert cm.active_combatant.creature_id == caster_id
    return cm, caster_id, target_id


# ── AI auto-reroll tests ────────────────────────────────────────────


class TestAIForcedReroll:
    """AI-controlled creatures auto-reroll failed saves."""

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_ai_reroll_succeeds_takes_half_damage(
        self, mock_damage, mock_d20,
    ):
        """AI creature with Indomitable rerolls failed save; new roll succeeds."""
        roll_sequence = iter([5, 18])
        mock_d20.side_effect = lambda n: next(roll_sequence) if n == 20 else 1
        mock_damage.return_value = (28, [28])

        fighter = _make_ai_fighter()
        cm, caster_id, target_id = _start_combat_caster_turn(fighter)

        target = cm.combatants[target_id]
        hp_before = target.creature.current_hit_points

        cm.select_action(_FIREBALL)
        result = cm.execute_effect(target_id)

        assert result is not None
        reroll_events = [
            e for e in result.events
            if e.details.get("forced_reroll")
        ]
        assert len(reroll_events) == 1
        assert "Indomitable" in reroll_events[0].message

        hp_after = target.creature.current_hit_points
        damage_taken = hp_before - hp_after
        assert damage_taken == 14  # half of 28

        assert target.creature.class_resources["indomitable_uses"] == 1

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_ai_reroll_fails_again_takes_full_damage(
        self, mock_damage, mock_d20,
    ):
        """AI creature rerolls but new roll also fails; takes full damage."""
        roll_sequence = iter([5, 3])
        mock_d20.side_effect = lambda n: next(roll_sequence) if n == 20 else 1
        mock_damage.return_value = (28, [28])

        fighter = _make_ai_fighter()
        cm, caster_id, target_id = _start_combat_caster_turn(fighter)

        target = cm.combatants[target_id]
        hp_before = target.creature.current_hit_points

        cm.select_action(_FIREBALL)
        result = cm.execute_effect(target_id)

        assert result is not None
        reroll_events = [
            e for e in result.events
            if e.details.get("forced_reroll")
        ]
        assert len(reroll_events) == 1

        hp_after = target.creature.current_hit_points
        damage_taken = hp_before - hp_after
        assert damage_taken == 28

        assert target.creature.class_resources["indomitable_uses"] == 1

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_ai_no_reroll_when_resources_depleted(
        self, mock_damage, mock_d20,
    ):
        """No reroll offered when resource is depleted."""
        mock_d20.return_value = 5
        mock_damage.return_value = (28, [28])

        fighter = _make_ai_fighter(
            class_resources={"indomitable_uses": 0},
        )
        cm, caster_id, target_id = _start_combat_caster_turn(fighter)

        cm.select_action(_FIREBALL)
        result = cm.execute_effect(target_id)

        assert result is not None
        reroll_events = [
            e for e in result.events
            if e.details.get("forced_reroll")
        ]
        assert len(reroll_events) == 0

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_ai_no_reroll_when_save_succeeds(
        self, mock_damage, mock_d20,
    ):
        """No reroll when the initial save succeeds."""
        mock_d20.return_value = 18  # Success vs DC 15
        mock_damage.return_value = (28, [28])

        fighter = _make_ai_fighter()
        cm, caster_id, target_id = _start_combat_caster_turn(fighter)

        cm.select_action(_FIREBALL)
        result = cm.execute_effect(target_id)

        assert result is not None
        reroll_events = [
            e for e in result.events
            if e.details.get("forced_reroll")
        ]
        assert len(reroll_events) == 0
        assert cm.combatants[target_id].creature.class_resources["indomitable_uses"] == 2

    @patch("arena.combat.actions.roll_die")
    def test_ai_no_reroll_without_feature(self, mock_d20):
        """Creature without reroll feature: no reroll offered."""
        mock_d20.return_value = 5

        fighter = Creature(
            name="Plain Fighter",
            max_hit_points=80,
            armor_class=18,
            is_player_controlled=False,
            actions=[_MELEE_ATTACK],
        )
        cm, caster_id, target_id = _start_combat_caster_turn(fighter)

        cm.select_action(_HOLD_PERSON)
        result = cm.execute_effect(target_id)

        assert result is not None
        reroll_events = [
            e for e in result.events
            if e.details.get("forced_reroll")
        ]
        assert len(reroll_events) == 0


# ── Player pending reroll tests ─────────────────────────────────────


class TestPlayerForcedReroll:
    """Player-controlled creatures get a pending reroll state for popup."""

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_player_reroll_sets_pending_state(
        self, mock_damage, mock_d20,
    ):
        """Player creature failing save with reroll feature sets pending state."""
        mock_d20.return_value = 5
        mock_damage.return_value = (28, [28])

        fighter = _make_fighter()
        cm, caster_id, target_id = _start_combat_caster_turn(fighter)

        cm.select_action(_FIREBALL)
        cm.execute_effect(target_id)

        assert cm._pending_save_reroll is not None
        assert cm._pending_save_reroll.target_id == target_id
        assert cm._pending_save_reroll.save_ability == "dexterity"
        assert cm._pending_save_reroll.save_dc == 15
        assert cm._pending_save_reroll.original_roll == 5
        assert len(cm._pending_save_reroll.features) == 1
        assert cm._pending_save_reroll.features[0].name == "Indomitable"

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_player_reroll_used_succeeds(
        self, mock_damage, mock_d20,
    ):
        """Player uses reroll; new roll succeeds, half damage applied."""
        roll_sequence = iter([5, 18])
        mock_d20.side_effect = lambda n: next(roll_sequence) if n == 20 else 1
        mock_damage.return_value = (28, [28])

        fighter = _make_fighter()
        cm, caster_id, target_id = _start_combat_caster_turn(fighter)

        target = cm.combatants[target_id]
        hp_before = target.creature.current_hit_points

        cm.select_action(_FIREBALL)
        cm.execute_effect(target_id)

        assert cm._pending_save_reroll is not None
        result = cm.resolve_save_reroll_choice("Indomitable")

        assert result is not None
        assert cm._pending_save_reroll is None

        hp_after = target.creature.current_hit_points
        damage_taken = hp_before - hp_after
        assert damage_taken == 14  # half of 28

        assert target.creature.class_resources["indomitable_uses"] == 1
        assert cm.turn_phase == TurnPhase.AWAITING_ACTION

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_player_reroll_used_still_fails(
        self, mock_damage, mock_d20,
    ):
        """Player uses reroll; new roll also fails, full damage applied."""
        roll_sequence = iter([5, 3])
        mock_d20.side_effect = lambda n: next(roll_sequence) if n == 20 else 1
        mock_damage.return_value = (28, [28])

        fighter = _make_fighter()
        cm, caster_id, target_id = _start_combat_caster_turn(fighter)

        target = cm.combatants[target_id]
        hp_before = target.creature.current_hit_points

        cm.select_action(_FIREBALL)
        cm.execute_effect(target_id)

        assert cm._pending_save_reroll is not None
        result = cm.resolve_save_reroll_choice("Indomitable")

        assert result is not None
        hp_after = target.creature.current_hit_points
        damage_taken = hp_before - hp_after
        assert damage_taken == 28

        assert target.creature.class_resources["indomitable_uses"] == 1

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_player_skips_reroll(
        self, mock_damage, mock_d20,
    ):
        """Player skips the reroll; original failed save events applied."""
        mock_d20.return_value = 5
        mock_damage.return_value = (28, [28])

        fighter = _make_fighter()
        cm, caster_id, target_id = _start_combat_caster_turn(fighter)

        target = cm.combatants[target_id]
        hp_before = target.creature.current_hit_points

        cm.select_action(_FIREBALL)
        cm.execute_effect(target_id)

        assert cm._pending_save_reroll is not None
        result = cm.resolve_save_reroll_choice(None)  # Skip

        assert result is not None
        assert cm._pending_save_reroll is None

        hp_after = target.creature.current_hit_points
        damage_taken = hp_before - hp_after
        assert damage_taken == 28

        assert target.creature.class_resources["indomitable_uses"] == 2

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_player_no_pending_when_resources_depleted(
        self, mock_damage, mock_d20,
    ):
        """No pending reroll when resources are depleted."""
        mock_d20.return_value = 5
        mock_damage.return_value = (28, [28])

        fighter = _make_fighter(
            class_resources={"indomitable_uses": 0},
        )
        cm, caster_id, target_id = _start_combat_caster_turn(fighter)

        cm.select_action(_FIREBALL)
        cm.execute_effect(target_id)

        assert cm._pending_save_reroll is None

    @patch("arena.combat.actions.roll_die")
    def test_multiple_features_first_used(self, mock_d20):
        """Creature with multiple reroll features: only first is used per save."""
        mock_d20.return_value = 5

        fighter = _make_ai_fighter(
            features=[_indomitable_feature(), _diamond_soul_feature()],
            class_resources={"indomitable_uses": 2, "ki_points": 5},
        )
        cm, caster_id, target_id = _start_combat_caster_turn(fighter)

        cm.select_action(_HOLD_PERSON)
        result = cm.execute_effect(target_id)

        assert result is not None
        reroll_events = [
            e for e in result.events
            if e.details.get("forced_reroll")
        ]
        assert len(reroll_events) == 1
        assert reroll_events[0].details["feature_name"] == "Indomitable"
