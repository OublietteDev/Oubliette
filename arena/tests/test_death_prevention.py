"""Tests for the death prevention system (Relentless Rage, Relentless Endurance, etc.)."""

import pytest
from unittest.mock import patch

from arena.models.character import Feature, PlayerCharacter, Creature, CreatureSize
from arena.combat.death_prevention import (
    get_death_prevention_features,
    can_use_death_prevention,
    resolve_death_prevention,
)
from arena.combat.events import CombatEventType


# ── Helpers ──────────────────────────────────────────────────────────


def _make_creature(**kwargs):
    """Create a minimal Creature for testing."""
    defaults = dict(
        name="TestCreature",
        max_hit_points=50,
    )
    defaults.update(kwargs)
    return Creature(**defaults)


def _make_pc(**kwargs):
    """Create a minimal PlayerCharacter for testing."""
    defaults = dict(
        name="TestPC",
        max_hit_points=50,
        character_class="Barbarian",
    )
    defaults.update(kwargs)
    return PlayerCharacter(**defaults)


def _relentless_endurance():
    """Create a Relentless Endurance feature (auto-succeed, once per rest)."""
    return Feature(
        name="Relentless Endurance",
        description="Drop to 1 HP instead of 0, once per long rest",
        death_prevention=True,
        death_prevention_hp=1,
        death_prevention_save_ability=None,
        death_prevention_resource="relentless_endurance",
    )


def _relentless_rage():
    """Create a Relentless Rage feature (CON save, escalating DC)."""
    return Feature(
        name="Relentless Rage",
        description="CON save to stay at 1 HP, DC increases each use",
        death_prevention=True,
        death_prevention_hp=1,
        death_prevention_save_ability="constitution",
        death_prevention_save_dc=10,
        death_prevention_dc_increment=5,
        death_prevention_resource=None,
    )


# ── get_death_prevention_features ────────────────────────────────────


class TestGetDeathPreventionFeatures:
    """Tests for get_death_prevention_features()."""

    def test_creature_with_death_prevention_feature(self):
        """Returns features that have death_prevention=True."""
        feat = _relentless_endurance()
        pc = _make_pc(
            features=[feat],
            class_resources={"relentless_endurance": 1},
        )
        result = get_death_prevention_features(pc)
        assert len(result) == 1
        assert result[0].name == "Relentless Endurance"

    def test_creature_without_death_prevention(self):
        """Returns empty list when no features have death_prevention."""
        pc = _make_pc(features=[
            Feature(name="Tough", description="Extra HP"),
        ])
        result = get_death_prevention_features(pc)
        assert result == []

    def test_creature_with_no_features(self):
        """Creature (monster) with no features returns empty list."""
        creature = _make_creature()
        result = get_death_prevention_features(creature)
        assert result == []

    def test_multiple_death_prevention_features(self):
        """Returns all death prevention features."""
        pc = _make_pc(features=[
            _relentless_endurance(),
            _relentless_rage(),
        ], class_resources={"relentless_endurance": 1})
        result = get_death_prevention_features(pc)
        assert len(result) == 2


# ── can_use_death_prevention ─────────────────────────────────────────


class TestCanUseDeathPrevention:
    """Tests for can_use_death_prevention()."""

    def test_with_available_resource(self):
        """Can use when resource is available."""
        feat = _relentless_endurance()
        pc = _make_pc(
            features=[feat],
            class_resources={"relentless_endurance": 1},
        )
        assert can_use_death_prevention(pc, feat) is True

    def test_with_depleted_resource(self):
        """Cannot use when required resource is 0."""
        feat = _relentless_endurance()
        pc = _make_pc(
            features=[feat],
            class_resources={"relentless_endurance": 0},
        )
        assert can_use_death_prevention(pc, feat) is False

    def test_with_missing_resource(self):
        """Cannot use when required resource key is absent."""
        feat = _relentless_endurance()
        pc = _make_pc(
            features=[feat],
            class_resources={},
        )
        assert can_use_death_prevention(pc, feat) is False

    def test_no_resource_required(self):
        """Can use when no resource is required (Relentless Rage)."""
        feat = _relentless_rage()
        pc = _make_pc(features=[feat])
        assert can_use_death_prevention(pc, feat) is True

    def test_feature_without_death_prevention(self):
        """Returns False for a feature that isn't death prevention."""
        feat = Feature(name="Tough", description="Extra HP")
        pc = _make_pc(features=[feat])
        assert can_use_death_prevention(pc, feat) is False


# ── resolve_death_prevention: auto-succeed ───────────────────────────


class TestResolveAutoSucceed:
    """Tests for resolve_death_prevention() with auto-succeed features."""

    def test_auto_succeed_sets_hp(self):
        """Relentless Endurance: creature HP set to 1."""
        feat = _relentless_endurance()
        pc = _make_pc(
            features=[feat],
            class_resources={"relentless_endurance": 1},
        )
        pc.current_hit_points = 0

        success, events = resolve_death_prevention(pc, "pc_1", feat)

        assert success is True
        assert pc.current_hit_points == 1
        assert len(events) == 1
        assert events[0].event_type == CombatEventType.INFO
        assert "Relentless Endurance" in events[0].message
        assert events[0].details["death_prevention"] is True
        assert events[0].details["new_hp"] == 1

    def test_auto_succeed_deducts_resource(self):
        """Resource is deducted on auto-succeed."""
        feat = _relentless_endurance()
        pc = _make_pc(
            features=[feat],
            class_resources={"relentless_endurance": 1},
        )
        pc.current_hit_points = 0

        resolve_death_prevention(pc, "pc_1", feat)

        assert pc.class_resources["relentless_endurance"] == 0

    def test_auto_succeed_no_resource_needed(self):
        """Feature with no resource requirement still succeeds."""
        feat = Feature(
            name="Undying",
            description="Always drop to 1 instead of 0",
            death_prevention=True,
            death_prevention_hp=1,
            death_prevention_save_ability=None,
            death_prevention_resource=None,
        )
        pc = _make_pc(features=[feat])
        pc.current_hit_points = 0

        success, events = resolve_death_prevention(pc, "pc_1", feat)

        assert success is True
        assert pc.current_hit_points == 1


# ── resolve_death_prevention: save required ──────────────────────────


class TestResolveSaveRequired:
    """Tests for resolve_death_prevention() with saving throw."""

    @patch("arena.combat.death_prevention.roll_die", return_value=15)
    def test_save_success(self, mock_roll):
        """High roll succeeds the save, HP set to 1."""
        feat = _relentless_rage()
        pc = _make_pc(
            features=[feat],
            ability_scores={"strength": 10, "dexterity": 10, "constitution": 16,
                            "intelligence": 10, "wisdom": 10, "charisma": 10},
        )
        pc.current_hit_points = 0

        success, events = resolve_death_prevention(pc, "pc_1", feat, use_count=0)

        assert success is True
        assert pc.current_hit_points == 1
        assert events[0].details["success"] is True
        assert events[0].details["dc"] == 10
        # Roll 15 + CON mod 3 = 18 >= DC 10
        assert events[0].details["roll"] == 18

    @patch("arena.combat.death_prevention.roll_die", return_value=2)
    def test_save_failure(self, mock_roll):
        """Low roll fails the save, HP stays at 0."""
        feat = _relentless_rage()
        pc = _make_pc(
            features=[feat],
            ability_scores={"strength": 10, "dexterity": 10, "constitution": 10,
                            "intelligence": 10, "wisdom": 10, "charisma": 10},
        )
        pc.current_hit_points = 0

        success, events = resolve_death_prevention(pc, "pc_1", feat, use_count=0)

        assert success is False
        assert pc.current_hit_points == 0
        assert events[0].details["success"] is False
        # Roll 2 + CON mod 0 = 2 < DC 10
        assert events[0].details["roll"] == 2

    @patch("arena.combat.death_prevention.roll_die", return_value=10)
    def test_save_exact_dc(self, mock_roll):
        """Rolling exactly the DC succeeds (total >= dc)."""
        feat = _relentless_rage()
        pc = _make_pc(
            features=[feat],
            ability_scores={"strength": 10, "dexterity": 10, "constitution": 10,
                            "intelligence": 10, "wisdom": 10, "charisma": 10},
        )
        pc.current_hit_points = 0

        success, events = resolve_death_prevention(pc, "pc_1", feat, use_count=0)

        assert success is True
        assert pc.current_hit_points == 1
        # Roll 10 + CON mod 0 = 10 >= DC 10
        assert events[0].details["roll"] == 10


# ── Escalating DC ────────────────────────────────────────────────────


class TestEscalatingDC:
    """Tests for escalating DC mechanic (Relentless Rage)."""

    @patch("arena.combat.death_prevention.roll_die", return_value=10)
    def test_dc_at_use_count_0(self, mock_roll):
        """First use: DC 10."""
        feat = _relentless_rage()
        pc = _make_pc(
            features=[feat],
            ability_scores={"strength": 10, "dexterity": 10, "constitution": 10,
                            "intelligence": 10, "wisdom": 10, "charisma": 10},
        )
        pc.current_hit_points = 0

        _, events = resolve_death_prevention(pc, "pc_1", feat, use_count=0)
        assert events[0].details["dc"] == 10

    @patch("arena.combat.death_prevention.roll_die", return_value=10)
    def test_dc_at_use_count_1(self, mock_roll):
        """Second use: DC 15."""
        feat = _relentless_rage()
        pc = _make_pc(
            features=[feat],
            ability_scores={"strength": 10, "dexterity": 10, "constitution": 10,
                            "intelligence": 10, "wisdom": 10, "charisma": 10},
        )
        pc.current_hit_points = 0

        _, events = resolve_death_prevention(pc, "pc_1", feat, use_count=1)
        assert events[0].details["dc"] == 15

    @patch("arena.combat.death_prevention.roll_die", return_value=10)
    def test_dc_at_use_count_2(self, mock_roll):
        """Third use: DC 20."""
        feat = _relentless_rage()
        pc = _make_pc(
            features=[feat],
            ability_scores={"strength": 10, "dexterity": 10, "constitution": 10,
                            "intelligence": 10, "wisdom": 10, "charisma": 10},
        )
        pc.current_hit_points = 0

        _, events = resolve_death_prevention(pc, "pc_1", feat, use_count=2)
        assert events[0].details["dc"] == 20

    @patch("arena.combat.death_prevention.roll_die", return_value=10)
    def test_escalating_dc_causes_failure(self, mock_roll):
        """High enough use_count makes the DC unbeatable."""
        feat = _relentless_rage()
        pc = _make_pc(
            features=[feat],
            ability_scores={"strength": 10, "dexterity": 10, "constitution": 10,
                            "intelligence": 10, "wisdom": 10, "charisma": 10},
        )
        pc.current_hit_points = 0

        # use_count=3 → DC 25, roll 10 + 0 mod = 10 < 25
        success, events = resolve_death_prevention(pc, "pc_1", feat, use_count=3)
        assert success is False
        assert events[0].details["dc"] == 25


# ── Resource deduction on save ───────────────────────────────────────


class TestResourceDeduction:
    """Tests for resource deduction on successful save."""

    @patch("arena.combat.death_prevention.roll_die", return_value=20)
    def test_resource_deducted_on_save_success(self, mock_roll):
        """Resource is deducted when save succeeds."""
        feat = Feature(
            name="Gritty Resolve",
            description="CON save to stay up, costs resolve",
            death_prevention=True,
            death_prevention_hp=1,
            death_prevention_save_ability="constitution",
            death_prevention_save_dc=10,
            death_prevention_dc_increment=0,
            death_prevention_resource="resolve",
        )
        pc = _make_pc(
            features=[feat],
            class_resources={"resolve": 2},
            ability_scores={"strength": 10, "dexterity": 10, "constitution": 10,
                            "intelligence": 10, "wisdom": 10, "charisma": 10},
        )
        pc.current_hit_points = 0

        success, _ = resolve_death_prevention(pc, "pc_1", feat, use_count=0)

        assert success is True
        assert pc.class_resources["resolve"] == 1

    @patch("arena.combat.death_prevention.roll_die", return_value=1)
    def test_resource_not_deducted_on_save_failure(self, mock_roll):
        """Resource is NOT deducted when save fails."""
        feat = Feature(
            name="Gritty Resolve",
            description="CON save to stay up, costs resolve",
            death_prevention=True,
            death_prevention_hp=1,
            death_prevention_save_ability="constitution",
            death_prevention_save_dc=10,
            death_prevention_dc_increment=0,
            death_prevention_resource="resolve",
        )
        pc = _make_pc(
            features=[feat],
            class_resources={"resolve": 2},
            ability_scores={"strength": 10, "dexterity": 10, "constitution": 10,
                            "intelligence": 10, "wisdom": 10, "charisma": 10},
        )
        pc.current_hit_points = 0

        success, _ = resolve_death_prevention(pc, "pc_1", feat, use_count=0)

        assert success is False
        assert pc.class_resources["resolve"] == 2
