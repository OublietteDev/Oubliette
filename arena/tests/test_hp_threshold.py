"""Tests for the HP threshold effect system (src/combat/hp_threshold.py).

Tests cover:
- Unit tests for check_hp_threshold(): below threshold, above threshold, no threshold
- Unit tests for check_damaged_threshold(): damaged target, full HP target, wrong effect type
- Unit tests for get_threshold_alt_dice()
- Integration: Power Word Kill on target with <=100 HP -> target killed
- Integration: Power Word Kill on target with >100 HP -> no effect
- Integration: Power Word Stun on target with <=150 HP -> target stunned
- Integration: Toll the Dead on damaged target -> uses d12 instead of d8
- Integration: Toll the Dead on full HP target -> uses d8
"""

import pytest
from unittest.mock import patch

from arena.models.character import Creature
from arena.models.actions import (
    Action, ActionType, TargetType, DamageRoll, DamageType, SavingThrowEffect,
)
from arena.models.conditions import Condition
from arena.combat.hp_threshold import (
    check_hp_threshold,
    check_damaged_threshold,
    get_threshold_alt_dice,
)
from arena.combat.actions import resolve_effect
from arena.combat.events import CombatEventType
from arena.combat.conditions import has_condition
from arena.grid.hexgrid import HexGrid
from arena.grid.coordinates import HexCoord


# ── Test Helpers ──────────────────────────────────────────────────────


def _make_creature(
    name: str = "Test",
    max_hp: int = 50,
    current_hp: int | None = None,
    armor_class: int = 10,
) -> Creature:
    """Create a minimal creature for testing."""
    from arena.models.abilities import AbilityScores
    c = Creature(
        name=name,
        max_hit_points=max_hp,
        armor_class=armor_class,
        ability_scores=AbilityScores(
            strength=10,
            dexterity=10,
            constitution=10,
            intelligence=10,
            wisdom=10,
            charisma=10,
        ),
        speed={"walk": 30},
        proficiency_bonus=2,
        saving_throw_proficiencies=[],
    )
    if current_hp is not None:
        c.current_hit_points = current_hp
    return c


def _power_word_kill() -> Action:
    """Power Word Kill: instant kill if target HP <= 100."""
    return Action(
        name="Power Word Kill",
        description="Instant kill if target has 100 HP or fewer.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=60,
        hp_threshold=100,
        hp_threshold_effect="kill",
    )


def _power_word_stun() -> Action:
    """Power Word Stun: stun if target HP <= 150."""
    return Action(
        name="Power Word Stun",
        description="Stun if target has 150 HP or fewer.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=60,
        hp_threshold=150,
        hp_threshold_effect="condition",
        hp_threshold_condition="stunned",
    )


def _toll_the_dead() -> Action:
    """Toll the Dead: d8 necrotic, or d12 if target is damaged."""
    return Action(
        name="Toll the Dead",
        description="Necrotic damage cantrip; d12 vs damaged targets.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=60,
        saving_throw=SavingThrowEffect(
            ability="wisdom",
            dc=15,
            damage_on_fail=[
                DamageRoll(dice="1d8", damage_type=DamageType.NECROTIC),
            ],
            damage_on_success="none",
        ),
        hp_threshold=0,  # Any threshold; the effect type handles the logic
        hp_threshold_effect="bonus_damage_die",
        hp_threshold_alt_dice="1d12",
    )


def _setup_grid_and_place(caster, target):
    """Create a grid and place caster + target."""
    grid = HexGrid(width=10, height=10)
    grid.place_creature(HexCoord(q=1, r=1), "caster_1")
    grid.place_creature(HexCoord(q=2, r=1), "target_1")
    return grid


# ══════════════════════════════════════════════════════════════════════
# UNIT TESTS — check_hp_threshold
# ══════════════════════════════════════════════════════════════════════


class TestCheckHpThreshold:
    """Unit tests for check_hp_threshold()."""

    def test_below_threshold_returns_effect(self):
        """Target at 80 HP with threshold 100 -> returns 'kill'."""
        action = _power_word_kill()
        target = _make_creature(max_hp=200, current_hp=80)
        assert check_hp_threshold(action, target) == "kill"

    def test_at_threshold_returns_effect(self):
        """Target at exactly 100 HP with threshold 100 -> returns 'kill'."""
        action = _power_word_kill()
        target = _make_creature(max_hp=200, current_hp=100)
        assert check_hp_threshold(action, target) == "kill"

    def test_above_threshold_returns_none(self):
        """Target at 101 HP with threshold 100 -> returns None."""
        action = _power_word_kill()
        target = _make_creature(max_hp=200, current_hp=101)
        assert check_hp_threshold(action, target) is None

    def test_no_threshold_returns_none(self):
        """Action without hp_threshold -> returns None."""
        action = Action(name="Fireball", description="Fire", range=60)
        target = _make_creature(max_hp=50, current_hp=10)
        assert check_hp_threshold(action, target) is None

    def test_condition_effect_type(self):
        """Power Word Stun: target at 120 HP with threshold 150 -> 'condition'."""
        action = _power_word_stun()
        target = _make_creature(max_hp=200, current_hp=120)
        assert check_hp_threshold(action, target) == "condition"

    def test_bonus_damage_die_effect_type(self):
        """Toll the Dead-style: target at 0 HP threshold -> 'bonus_damage_die'."""
        action = _toll_the_dead()
        target = _make_creature(max_hp=50, current_hp=0)
        assert check_hp_threshold(action, target) == "bonus_damage_die"


# ══════════════════════════════════════════════════════════════════════
# UNIT TESTS — check_damaged_threshold
# ══════════════════════════════════════════════════════════════════════


class TestCheckDamagedThreshold:
    """Unit tests for check_damaged_threshold()."""

    def test_damaged_target_returns_true(self):
        """Target below max HP with bonus_damage_die -> True."""
        action = _toll_the_dead()
        target = _make_creature(max_hp=50, current_hp=30)
        assert check_damaged_threshold(action, target) is True

    def test_full_hp_target_returns_false(self):
        """Target at full HP with bonus_damage_die -> False."""
        action = _toll_the_dead()
        target = _make_creature(max_hp=50, current_hp=50)
        assert check_damaged_threshold(action, target) is False

    def test_wrong_effect_type_returns_false(self):
        """Action with 'kill' effect type -> always False for damaged check."""
        action = _power_word_kill()
        target = _make_creature(max_hp=200, current_hp=50)
        assert check_damaged_threshold(action, target) is False

    def test_no_alt_dice_returns_false(self):
        """bonus_damage_die without alt_dice -> False."""
        action = Action(
            name="Test",
            description="Test",
            hp_threshold=0,
            hp_threshold_effect="bonus_damage_die",
            hp_threshold_alt_dice=None,
        )
        target = _make_creature(max_hp=50, current_hp=30)
        assert check_damaged_threshold(action, target) is False


# ══════════════════════════════════════════════════════════════════════
# UNIT TESTS — get_threshold_alt_dice
# ══════════════════════════════════════════════════════════════════════


class TestGetThresholdAltDice:
    """Unit tests for get_threshold_alt_dice()."""

    def test_returns_alt_dice(self):
        action = _toll_the_dead()
        assert get_threshold_alt_dice(action) == "1d12"

    def test_returns_none_when_no_alt(self):
        action = _power_word_kill()
        assert get_threshold_alt_dice(action) is None


# ══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Power Word Kill
# ══════════════════════════════════════════════════════════════════════


class TestPowerWordKillIntegration:
    """Integration tests for Power Word Kill via resolve_effect()."""

    def test_kills_target_below_threshold(self):
        """Power Word Kill on target with 80 HP -> target killed (HP = 0)."""
        caster = _make_creature(name="Wizard", max_hp=50)

        target = _make_creature(name="Goblin", max_hp=200, current_hp=80)
        grid = _setup_grid_and_place(caster, target)

        result = resolve_effect(
            caster, "caster_1", target, "target_1",
            _power_word_kill(), grid,
        )

        assert result.success is True
        assert target.current_hit_points == 0
        # Should have DAMAGE and CREATURE_DOWNED events
        damage_events = [
            e for e in result.events
            if e.event_type == CombatEventType.DAMAGE
        ]
        assert len(damage_events) == 1
        assert damage_events[0].details["damage"] == 80
        downed_events = [
            e for e in result.events
            if e.event_type == CombatEventType.CREATURE_DOWNED
        ]
        assert len(downed_events) == 1

    def test_kills_target_at_exactly_threshold(self):
        """Power Word Kill on target with exactly 100 HP -> killed."""
        caster = _make_creature(name="Wizard", max_hp=50)

        target = _make_creature(name="Guard", max_hp=200, current_hp=100)
        grid = _setup_grid_and_place(caster, target)

        result = resolve_effect(
            caster, "caster_1", target, "target_1",
            _power_word_kill(), grid,
        )

        assert result.success is True
        assert target.current_hit_points == 0

    def test_no_effect_above_threshold(self):
        """Power Word Kill on target with 101 HP -> no effect."""
        caster = _make_creature(name="Wizard", max_hp=50)

        target = _make_creature(name="Dragon", max_hp=200, current_hp=101)
        grid = _setup_grid_and_place(caster, target)

        result = resolve_effect(
            caster, "caster_1", target, "target_1",
            _power_word_kill(), grid,
        )

        assert result.success is True
        assert target.current_hit_points == 101
        # Should have an INFO event saying no effect
        info_events = [
            e for e in result.events
            if e.event_type == CombatEventType.INFO
            and "no effect" in e.message
        ]
        assert len(info_events) == 1


# ══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Power Word Stun
# ══════════════════════════════════════════════════════════════════════


class TestPowerWordStunIntegration:
    """Integration tests for Power Word Stun via resolve_effect()."""

    def test_stuns_target_below_threshold(self):
        """Power Word Stun on target with 120 HP -> stunned."""
        caster = _make_creature(name="Wizard", max_hp=50)

        target = _make_creature(name="Ogre", max_hp=200, current_hp=120)
        grid = _setup_grid_and_place(caster, target)

        result = resolve_effect(
            caster, "caster_1", target, "target_1",
            _power_word_stun(), grid,
        )

        assert result.success is True
        assert has_condition(target, Condition.STUNNED)

    def test_no_effect_above_threshold(self):
        """Power Word Stun on target with 151 HP -> no effect, not stunned."""
        caster = _make_creature(name="Wizard", max_hp=50)

        target = _make_creature(name="Dragon", max_hp=300, current_hp=151)
        grid = _setup_grid_and_place(caster, target)

        result = resolve_effect(
            caster, "caster_1", target, "target_1",
            _power_word_stun(), grid,
        )

        assert result.success is True
        assert not has_condition(target, Condition.STUNNED)
        info_events = [
            e for e in result.events
            if e.event_type == CombatEventType.INFO
            and "no effect" in e.message
        ]
        assert len(info_events) == 1


# ══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Toll the Dead
# ══════════════════════════════════════════════════════════════════════


class TestTollTheDeadIntegration:
    """Integration tests for Toll the Dead dice upgrade via resolve_effect()."""

    @patch("arena.util.dice.roll_die", return_value=4)
    def test_damaged_target_uses_d12(self, mock_roll):
        """Toll the Dead on damaged target -> rolls d12 (alt dice)."""
        caster = _make_creature(name="Cleric", max_hp=50)
        target = _make_creature(name="Zombie", max_hp=30, current_hp=20)
        grid = _setup_grid_and_place(caster, target)

        # Force failed save
        with patch("arena.combat.actions.resolve_saving_throw") as mock_save:
            mock_save.return_value = (False, _make_save_event("target_1"))
            result = resolve_effect(
                caster, "caster_1", target, "target_1",
                _toll_the_dead(), grid,
            )

        assert result.success is True
        # Check that d12 was rolled (mock_roll called with 12)
        roll_calls = [c for c in mock_roll.call_args_list if c[0] == (12,)]
        assert len(roll_calls) > 0, (
            f"Expected roll_die(12) call for d12, got: {mock_roll.call_args_list}"
        )

    @patch("arena.util.dice.roll_die", return_value=4)
    def test_full_hp_target_uses_d8(self, mock_roll):
        """Toll the Dead on full HP target -> rolls d8 (base dice)."""
        caster = _make_creature(name="Cleric", max_hp=50)
        target = _make_creature(name="Zombie", max_hp=30, current_hp=30)
        grid = _setup_grid_and_place(caster, target)

        # Force failed save
        with patch("arena.combat.actions.resolve_saving_throw") as mock_save:
            mock_save.return_value = (False, _make_save_event("target_1"))
            result = resolve_effect(
                caster, "caster_1", target, "target_1",
                _toll_the_dead(), grid,
            )

        assert result.success is True
        # Check that d8 was rolled (mock_roll called with 8)
        roll_calls = [c for c in mock_roll.call_args_list if c[0] == (8,)]
        assert len(roll_calls) > 0, (
            f"Expected roll_die(8) call for d8, got: {mock_roll.call_args_list}"
        )
        # d12 should NOT have been rolled
        d12_calls = [c for c in mock_roll.call_args_list if c[0] == (12,)]
        assert len(d12_calls) == 0, "Should not roll d12 for full HP target"


# ── Helper for mocked saving throw ───────────────────────────────────

def _make_save_event(target_id: str):
    """Create a mock saving throw event."""
    from arena.combat.events import CombatEvent, CombatEventType
    return CombatEvent(
        event_type=CombatEventType.SAVING_THROW,
        message="Failed save",
        target_id=target_id,
        details={"ability": "wisdom", "roll": 5, "dc": 15, "success": False},
    )
