"""Tests for Phase 5b: Saving Throws and Damage Processing."""

import pytest
from unittest.mock import patch

from arena.combat.actions import resolve_saving_throw
from arena.combat.damage import apply_damage, apply_healing, _apply_damage_modifiers
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.character import Creature


# ── Helpers ───────────────────────────────────────────────────────────

def _make_creature(
    hp=20, ac=10, constitution=10, dexterity=10, wisdom=10,
    save_profs=None, resistances=None, immunities=None, vulnerabilities=None,
    temp_hp=0,
):
    c = Creature(
        name="Test",
        max_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(
            constitution=constitution,
            dexterity=dexterity,
            wisdom=wisdom,
        ),
        proficiency_bonus=2,
        saving_throw_proficiencies=save_profs or [],
        damage_resistances=resistances or [],
        damage_immunities=immunities or [],
        damage_vulnerabilities=vulnerabilities or [],
        temporary_hit_points=temp_hp,
    )
    return c


# ── Saving Throw Tests ───────────────────────────────────────────────

class TestResolveSavingThrow:
    @patch("arena.combat.actions.roll_die")
    def test_basic_success(self, mock_d20):
        mock_d20.return_value = 15
        creature = _make_creature(dexterity=14)  # +2 mod
        success, event = resolve_saving_throw(creature, "test", "dexterity", dc=15)
        # 15 + 2 = 17 >= 15
        assert success is True
        assert event.event_type == CombatEventType.SAVING_THROW
        assert event.details["success"] is True
        assert "SUCCESS" in event.message

    @patch("arena.combat.actions.roll_die")
    def test_basic_failure(self, mock_d20):
        mock_d20.return_value = 5
        creature = _make_creature(dexterity=10)  # +0 mod
        success, event = resolve_saving_throw(creature, "test", "dexterity", dc=15)
        # 5 + 0 = 5 < 15
        assert success is False
        assert event.details["success"] is False
        assert "FAILURE" in event.message

    @patch("arena.combat.actions.roll_die")
    def test_proficiency_applies(self, mock_d20):
        mock_d20.return_value = 10
        creature = _make_creature(constitution=12, save_profs=["constitution"])
        # CON 12 = +1 mod, +2 prof = +3 total
        success, event = resolve_saving_throw(creature, "test", "constitution", dc=13)
        # 10 + 3 = 13 >= 13
        assert success is True
        assert event.details["modifier"] == 3

    @patch("arena.combat.actions.roll_die")
    def test_non_proficient_save(self, mock_d20):
        mock_d20.return_value = 10
        creature = _make_creature(wisdom=10)  # +0 mod, no prof
        success, event = resolve_saving_throw(creature, "test", "wisdom", dc=11)
        # 10 + 0 = 10 < 11
        assert success is False
        assert event.details["modifier"] == 0

    @patch("arena.combat.actions.roll_with_advantage")
    def test_advantage_on_save(self, mock_adv):
        mock_adv.return_value = (18, 8, 18)
        creature = _make_creature(dexterity=10)
        success, event = resolve_saving_throw(
            creature, "test", "dexterity", dc=15, advantage=1
        )
        # 18 + 0 = 18 >= 15
        assert success is True
        assert event.details["advantage"] == 1
        assert "[advantage:" in event.message

    @patch("arena.combat.actions.roll_with_disadvantage")
    def test_disadvantage_on_save(self, mock_dis):
        mock_dis.return_value = (5, 5, 18)
        creature = _make_creature(dexterity=10)
        success, event = resolve_saving_throw(
            creature, "test", "dexterity", dc=15, advantage=-1
        )
        # 5 + 0 = 5 < 15
        assert success is False
        assert event.details["advantage"] == -1
        assert "[disadvantage:" in event.message

    @patch("arena.combat.actions.roll_die")
    def test_event_details_complete(self, mock_d20):
        mock_d20.return_value = 12
        creature = _make_creature(dexterity=14)
        _, event = resolve_saving_throw(creature, "test_id", "dexterity", dc=13)
        assert event.details["ability"] == "dexterity"
        assert event.details["natural"] == 12
        assert event.details["dc"] == 13
        assert event.source_id == "test_id"


# ── Damage Modifier Tests ───────────────────────────────────────────

class TestDamageModifiers:
    def test_no_modifiers(self):
        creature = _make_creature()
        dmg, text = _apply_damage_modifiers(creature, 10, "slashing")
        assert dmg == 10
        assert text == ""

    def test_resistance_halves(self):
        creature = _make_creature(resistances=["fire"])
        dmg, text = _apply_damage_modifiers(creature, 10, "fire")
        assert dmg == 5
        assert "RESISTANT" in text

    def test_immunity_negates(self):
        creature = _make_creature(immunities=["poison"])
        dmg, text = _apply_damage_modifiers(creature, 10, "poison")
        assert dmg == 0
        assert "IMMUNE" in text

    def test_vulnerability_doubles(self):
        creature = _make_creature(vulnerabilities=["fire"])
        dmg, text = _apply_damage_modifiers(creature, 10, "fire")
        assert dmg == 20
        assert "VULNERABLE" in text

    def test_resistance_and_vulnerability_cancel(self):
        creature = _make_creature(resistances=["fire"], vulnerabilities=["fire"])
        dmg, text = _apply_damage_modifiers(creature, 10, "fire")
        assert dmg == 10
        assert text == ""

    def test_immunity_takes_precedence_over_vulnerability(self):
        creature = _make_creature(immunities=["fire"], vulnerabilities=["fire"])
        dmg, text = _apply_damage_modifiers(creature, 10, "fire")
        assert dmg == 0
        assert "IMMUNE" in text

    def test_case_insensitive(self):
        creature = _make_creature(resistances=["Fire"])
        dmg, text = _apply_damage_modifiers(creature, 10, "fire")
        assert dmg == 5


# ── apply_damage with Defenses Tests ────────────────────────────────

class TestApplyDamageWithDefenses:
    def test_basic_damage_unchanged(self):
        creature = _make_creature(hp=20)
        event, _ = apply_damage(creature, 5, "slashing")
        assert creature.current_hit_points == 15
        assert event.details["damage"] == 5

    def test_resistance_applied(self):
        creature = _make_creature(hp=20, resistances=["fire"])
        event, _ = apply_damage(creature, 10, "fire")
        assert creature.current_hit_points == 15  # 10 / 2 = 5 damage
        assert event.details["damage"] == 5
        assert "RESISTANT" in event.message

    def test_immunity_applied(self):
        creature = _make_creature(hp=20, immunities=["poison"])
        event, _ = apply_damage(creature, 10, "poison")
        assert creature.current_hit_points == 20  # No damage
        assert event.details["damage"] == 0
        assert "IMMUNE" in event.message

    def test_vulnerability_applied(self):
        creature = _make_creature(hp=40, vulnerabilities=["fire"])
        event, _ = apply_damage(creature, 10, "fire")
        assert creature.current_hit_points == 20  # 10 * 2 = 20 damage
        assert event.details["damage"] == 20

    def test_temp_hp_absorbs_damage(self):
        creature = _make_creature(hp=20, temp_hp=5)
        event, _ = apply_damage(creature, 8, "slashing")
        # 5 temp absorbed, 3 remaining hits real HP
        assert creature.temporary_hit_points == 0
        assert creature.current_hit_points == 17
        assert event.details["temp_absorbed"] == 5

    def test_temp_hp_fully_absorbs(self):
        creature = _make_creature(hp=20, temp_hp=10)
        event, _ = apply_damage(creature, 5, "slashing")
        # All 5 absorbed by temp HP
        assert creature.temporary_hit_points == 5
        assert creature.current_hit_points == 20
        assert event.details["temp_absorbed"] == 5

    def test_temp_hp_and_resistance(self):
        creature = _make_creature(hp=20, temp_hp=5, resistances=["fire"])
        event, _ = apply_damage(creature, 10, "fire")
        # Resistance first: 10 -> 5, then temp absorbs 5
        assert creature.temporary_hit_points == 0
        assert creature.current_hit_points == 20
        assert event.details["damage"] == 5

    def test_knockout_tracked(self):
        creature = _make_creature(hp=5)
        event, _ = apply_damage(creature, 10, "slashing")
        assert creature.current_hit_points == 0
        assert event.details["knocked_out"] is True

    def test_raw_damage_tracked(self):
        creature = _make_creature(hp=20, resistances=["fire"])
        event, _ = apply_damage(creature, 10, "fire")
        assert event.details["raw_damage"] == 10
        assert event.details["damage"] == 5


# ── Healing Tests ────────────────────────────────────────────────────

class TestApplyHealing:
    def test_basic_healing(self):
        creature = _make_creature(hp=20)
        creature.current_hit_points = 10
        event = apply_healing(creature, 5)
        assert creature.current_hit_points == 15
        assert event.event_type == CombatEventType.HEALING
        assert event.details["healing"] == 5

    def test_healing_caps_at_max(self):
        creature = _make_creature(hp=20)
        creature.current_hit_points = 18
        event = apply_healing(creature, 10)
        assert creature.current_hit_points == 20
        assert event.details["healing"] == 2

    def test_healing_unconscious_creature(self):
        creature = _make_creature(hp=20)
        creature.current_hit_points = 0
        event = apply_healing(creature, 5)
        assert creature.current_hit_points == 5
        assert event.details["regained_consciousness"] is True
        assert "regains consciousness" in event.message

    def test_healing_at_max_hp(self):
        creature = _make_creature(hp=20)
        event = apply_healing(creature, 5)
        assert creature.current_hit_points == 20
        assert event.details["healing"] == 0

    def test_healing_event_details(self):
        creature = _make_creature(hp=20)
        creature.current_hit_points = 10
        event = apply_healing(creature, 5)
        assert event.details["old_hp"] == 10
        assert event.details["new_hp"] == 15
