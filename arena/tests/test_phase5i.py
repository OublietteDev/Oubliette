"""Tests for Phase 5i: Concentration System."""

import pytest
from unittest.mock import patch

from arena.combat.concentration import (
    start_concentrating,
    check_concentration,
    end_concentration,
)
from arena.combat.conditions import has_condition, apply_condition
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.character import Creature
from arena.models.conditions import Condition


# ── Helpers ───────────────────────────────────────────────────────────

def _make_creature(hp=20, constitution=10):
    return Creature(
        name="Wizard",
        max_hit_points=hp,
        ability_scores=AbilityScores(constitution=constitution),
        proficiency_bonus=2,
    )


# ── start_concentrating Tests ────────────────────────────────────────

class TestStartConcentrating:
    def test_applies_concentrating_condition(self):
        c = _make_creature()
        events = start_concentrating(c, "wizard", "Hold Person")
        assert has_condition(c, Condition.CONCENTRATING)
        assert len(events) == 1
        assert events[0].event_type == CombatEventType.CONDITION_APPLIED
        assert "concentrating" in events[0].message

    def test_tracks_spell_source(self):
        c = _make_creature()
        events = start_concentrating(c, "wizard", "Hold Person")
        # The applied condition should have the spell name in extra_data
        ac = [a for a in c.active_conditions if a.condition == Condition.CONCENTRATING][0]
        assert ac.source == "Hold Person"
        assert ac.extra_data.get("spell") == "Hold Person"

    def test_replaces_existing_concentration(self):
        c = _make_creature()
        start_concentrating(c, "wizard", "Hold Person")
        assert has_condition(c, Condition.CONCENTRATING)

        events = start_concentrating(c, "wizard", "Bless")
        # Should have: removed old, applied new
        assert has_condition(c, Condition.CONCENTRATING)

        # Check the new concentration is Bless, not Hold Person
        ac = [a for a in c.active_conditions if a.condition == Condition.CONCENTRATING][0]
        assert ac.source == "Bless"

        # Events should include removal and application
        removed = [e for e in events if e.event_type == CombatEventType.CONDITION_REMOVED]
        applied = [e for e in events if e.event_type == CombatEventType.CONDITION_APPLIED]
        assert len(removed) == 1
        assert len(applied) == 1

    def test_only_one_concentration_at_a_time(self):
        c = _make_creature()
        start_concentrating(c, "wizard", "Hold Person")
        start_concentrating(c, "wizard", "Bless")
        start_concentrating(c, "wizard", "Haste")

        conc_conditions = [
            a for a in c.active_conditions if a.condition == Condition.CONCENTRATING
        ]
        assert len(conc_conditions) == 1
        assert conc_conditions[0].source == "Haste"


# ── end_concentration Tests ──────────────────────────────────────────

class TestEndConcentration:
    def test_removes_concentrating_condition(self):
        c = _make_creature()
        start_concentrating(c, "wizard", "Hold Person")
        assert has_condition(c, Condition.CONCENTRATING)

        events = end_concentration(c, "wizard")
        assert not has_condition(c, Condition.CONCENTRATING)
        assert len(events) == 1
        assert events[0].event_type == CombatEventType.CONDITION_REMOVED

    def test_end_when_not_concentrating(self):
        c = _make_creature()
        events = end_concentration(c, "wizard")
        assert len(events) == 0


# ── check_concentration Tests ────────────────────────────────────────

class TestCheckConcentration:
    def test_no_check_if_not_concentrating(self):
        c = _make_creature()
        events = check_concentration(c, "wizard", 10)
        assert len(events) == 0

    @patch("arena.combat.actions.roll_die")
    def test_concentration_maintained_on_save_success(self, mock_d20):
        mock_d20.return_value = 15
        c = _make_creature(constitution=14)  # +2 mod => 17 total >= DC 10
        start_concentrating(c, "wizard", "Hold Person")

        events = check_concentration(c, "wizard", 10)
        assert has_condition(c, Condition.CONCENTRATING)
        # Should have a saving throw event
        save_events = [e for e in events if e.event_type == CombatEventType.SAVING_THROW]
        assert len(save_events) == 1
        assert save_events[0].details["success"] is True
        assert "Concentration check" in save_events[0].message

    @patch("arena.combat.actions.roll_die")
    def test_concentration_lost_on_save_failure(self, mock_d20):
        mock_d20.return_value = 3
        c = _make_creature(constitution=10)  # +0 mod => 3 total < DC 10
        start_concentrating(c, "wizard", "Hold Person")

        events = check_concentration(c, "wizard", 10)
        assert not has_condition(c, Condition.CONCENTRATING)
        # Should have save event and condition removed event
        save_events = [e for e in events if e.event_type == CombatEventType.SAVING_THROW]
        removed_events = [e for e in events if e.event_type == CombatEventType.CONDITION_REMOVED]
        assert len(save_events) == 1
        assert save_events[0].details["success"] is False
        assert len(removed_events) == 1

    @patch("arena.combat.actions.roll_die")
    def test_dc_is_half_damage_when_higher_than_10(self, mock_d20):
        mock_d20.return_value = 12
        c = _make_creature(constitution=10)  # +0 mod => 12 total
        start_concentrating(c, "wizard", "Hold Person")

        # 30 damage => DC 15, so 12 < 15 should fail
        events = check_concentration(c, "wizard", 30)
        assert not has_condition(c, Condition.CONCENTRATING)
        save_events = [e for e in events if e.event_type == CombatEventType.SAVING_THROW]
        assert save_events[0].details["dc"] == 15

    @patch("arena.combat.actions.roll_die")
    def test_dc_minimum_is_10(self, mock_d20):
        mock_d20.return_value = 11
        c = _make_creature(constitution=10)  # +0 mod => 11 total
        start_concentrating(c, "wizard", "Hold Person")

        # 5 damage => DC 10 (not 2), so 11 >= 10 should succeed
        events = check_concentration(c, "wizard", 5)
        assert has_condition(c, Condition.CONCENTRATING)
        save_events = [e for e in events if e.event_type == CombatEventType.SAVING_THROW]
        assert save_events[0].details["dc"] == 10

    @patch("arena.combat.actions.roll_die")
    def test_concentration_check_details(self, mock_d20):
        mock_d20.return_value = 15
        c = _make_creature(constitution=14)
        start_concentrating(c, "wizard", "Bless")

        events = check_concentration(c, "wizard", 20)
        save_events = [e for e in events if e.event_type == CombatEventType.SAVING_THROW]
        assert save_events[0].details["concentration_check"] is True
        assert save_events[0].details["damage_taken"] == 20


# ── Integration: attack triggers concentration check ─────────────────

class TestConcentrationInAttack:
    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_attack_damage_triggers_concentration_check(self, mock_dmg, mock_d20):
        from arena.combat.actions import resolve_attack
        from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
        from arena.grid.hexgrid import HexGrid
        from arena.grid.coordinates import HexCoord

        mock_d20.return_value = 18  # Hits
        mock_dmg.return_value = (8, [8])

        grid = HexGrid(10, 10)
        grid.place_creature(HexCoord(2, 2), "fighter")
        grid.place_creature(HexCoord(2, 3), "wizard")

        attacker = Creature(
            name="Fighter", max_hit_points=30,
            ability_scores=AbilityScores(strength=16), proficiency_bonus=2,
        )
        target = Creature(
            name="Wizard", max_hit_points=30, armor_class=10,
            ability_scores=AbilityScores(constitution=10), proficiency_bonus=2,
        )

        # Target is concentrating
        start_concentrating(target, "wizard", "Hold Person")

        action = Action(
            name="Sword", description="Melee", action_type=ActionType.ACTION,
            attack=Attack(
                name="Sword", attack_type="melee_weapon", ability="strength",
                reach=5,
                damage=[DamageRoll(dice="1d6", damage_type=DamageType.SLASHING,
                                   ability_modifier="strength")],
            ),
        )

        result = resolve_attack(attacker, "fighter", target, "wizard", action, grid)

        # Should have concentration check event in the results
        conc_events = [
            e for e in result.events
            if e.event_type == CombatEventType.SAVING_THROW
            and e.details.get("concentration_check")
        ]
        assert len(conc_events) == 1

    @patch("arena.combat.actions.roll_die")
    def test_no_concentration_check_on_miss(self, mock_d20):
        from arena.combat.actions import resolve_attack
        from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
        from arena.grid.hexgrid import HexGrid
        from arena.grid.coordinates import HexCoord

        mock_d20.return_value = 2  # Misses

        grid = HexGrid(10, 10)
        grid.place_creature(HexCoord(2, 2), "fighter")
        grid.place_creature(HexCoord(2, 3), "wizard")

        attacker = Creature(
            name="Fighter", max_hit_points=30,
            ability_scores=AbilityScores(strength=16), proficiency_bonus=2,
        )
        target = Creature(
            name="Wizard", max_hit_points=30, armor_class=15,
            ability_scores=AbilityScores(constitution=10), proficiency_bonus=2,
        )

        start_concentrating(target, "wizard", "Hold Person")

        action = Action(
            name="Sword", description="Melee", action_type=ActionType.ACTION,
            attack=Attack(
                name="Sword", attack_type="melee_weapon", ability="strength",
                reach=5,
                damage=[DamageRoll(dice="1d6", damage_type=DamageType.SLASHING)],
            ),
        )

        result = resolve_attack(attacker, "fighter", target, "wizard", action, grid)

        # No concentration check on a miss
        conc_events = [
            e for e in result.events
            if e.event_type == CombatEventType.SAVING_THROW
            and e.details.get("concentration_check")
        ]
        assert len(conc_events) == 0
        # Target should still be concentrating
        assert has_condition(target, Condition.CONCENTRATING)
