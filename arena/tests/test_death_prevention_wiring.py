"""Tests for death prevention wiring into apply_damage()."""

import pytest
from unittest.mock import patch

from arena.models.character import Feature, PlayerCharacter, Creature
from arena.combat.damage import apply_damage
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


# ── Relentless Endurance wiring ─────────────────────────────────────


class TestRelentlessEnduranceWiring:
    """Relentless Endurance prevents dropping to 0 HP via apply_damage."""

    def test_creature_stays_at_1_hp(self):
        """Creature with Relentless Endurance drops to 1 HP instead of 0."""
        pc = _make_pc(
            features=[_relentless_endurance()],
            class_resources={"relentless_endurance": 1},
        )
        pc.current_hit_points = 10

        event, dp_events = apply_damage(pc, 50, "slashing", creature_id="pc_1")

        assert pc.current_hit_points == 1
        assert event.details["new_hp"] == 1
        assert event.details["knocked_out"] is False
        assert event.details["death_prevented"] is True
        assert "unconscious" not in event.message
        assert len(dp_events) == 1
        assert dp_events[0].event_type == CombatEventType.INFO
        assert "Relentless Endurance" in dp_events[0].message

    def test_resource_deducted(self):
        """Relentless Endurance resource is consumed."""
        pc = _make_pc(
            features=[_relentless_endurance()],
            class_resources={"relentless_endurance": 1},
        )
        pc.current_hit_points = 5

        apply_damage(pc, 10, "slashing", creature_id="pc_1")

        assert pc.class_resources["relentless_endurance"] == 0

    def test_not_triggered_when_not_dropping_to_zero(self):
        """Death prevention does not fire when HP stays above 0."""
        pc = _make_pc(
            features=[_relentless_endurance()],
            class_resources={"relentless_endurance": 1},
        )
        pc.current_hit_points = 20

        event, dp_events = apply_damage(pc, 5, "slashing", creature_id="pc_1")

        assert pc.current_hit_points == 15
        assert dp_events == []
        assert event.details.get("death_prevented") is False
        assert pc.class_resources["relentless_endurance"] == 1


# ── No death prevention ─────────────────────────────────────────────


class TestNoDeatPrevention:
    """Creatures without death prevention drop to 0 normally."""

    def test_creature_drops_to_zero_normally(self):
        """Creature without death prevention features falls unconscious."""
        creature = _make_creature()
        creature.current_hit_points = 5

        event, dp_events = apply_damage(creature, 10, "slashing")

        assert creature.current_hit_points == 0
        assert event.details["knocked_out"] is True
        assert event.details["death_prevented"] is False
        assert "unconscious" in event.message
        assert dp_events == []

    def test_pc_without_feature_drops_normally(self):
        """PC with features but none that are death prevention."""
        pc = _make_pc(
            features=[Feature(name="Tough", description="Extra HP")],
        )
        pc.current_hit_points = 3

        event, dp_events = apply_damage(pc, 10, "fire", creature_id="pc_1")

        assert pc.current_hit_points == 0
        assert event.details["knocked_out"] is True
        assert dp_events == []


# ── Resource-depleted ────────────────────────────────────────────────


class TestResourceDepleted:
    """Creature with depleted death prevention resource drops to 0."""

    def test_depleted_resource_no_prevention(self):
        """Relentless Endurance with 0 uses left does not prevent death."""
        pc = _make_pc(
            features=[_relentless_endurance()],
            class_resources={"relentless_endurance": 0},
        )
        pc.current_hit_points = 5

        event, dp_events = apply_damage(pc, 10, "slashing", creature_id="pc_1")

        assert pc.current_hit_points == 0
        assert event.details["knocked_out"] is True
        assert event.details["death_prevented"] is False
        assert dp_events == []

    def test_missing_resource_key_no_prevention(self):
        """Relentless Endurance with missing resource key does not prevent."""
        pc = _make_pc(
            features=[_relentless_endurance()],
            class_resources={},
        )
        pc.current_hit_points = 5

        event, dp_events = apply_damage(pc, 10, "slashing", creature_id="pc_1")

        assert pc.current_hit_points == 0
        assert event.details["knocked_out"] is True
        assert dp_events == []


# ── Relentless Rage wiring (save-required) ───────────────────────────


class TestRelentlessRageWiring:
    """Relentless Rage requires a CON save with escalating DC."""

    @patch("arena.combat.death_prevention.roll_die", return_value=15)
    def test_save_success_stays_at_1(self, mock_roll):
        """Successful CON save keeps creature at 1 HP."""
        pc = _make_pc(
            features=[_relentless_rage()],
            ability_scores={
                "strength": 10, "dexterity": 10, "constitution": 16,
                "intelligence": 10, "wisdom": 10, "charisma": 10,
            },
        )
        pc.current_hit_points = 5

        event, dp_events = apply_damage(pc, 10, "slashing", creature_id="pc_1")

        assert pc.current_hit_points == 1
        assert event.details["death_prevented"] is True
        assert event.details["knocked_out"] is False
        assert len(dp_events) == 1
        assert dp_events[0].details["success"] is True
        assert dp_events[0].details["dc"] == 10

    @patch("arena.combat.death_prevention.roll_die", return_value=2)
    def test_save_failure_drops_to_zero(self, mock_roll):
        """Failed CON save lets creature drop to 0 HP."""
        pc = _make_pc(
            features=[_relentless_rage()],
            ability_scores={
                "strength": 10, "dexterity": 10, "constitution": 10,
                "intelligence": 10, "wisdom": 10, "charisma": 10,
            },
        )
        pc.current_hit_points = 5

        event, dp_events = apply_damage(pc, 10, "slashing", creature_id="pc_1")

        assert pc.current_hit_points == 0
        assert event.details["knocked_out"] is True
        assert event.details["death_prevented"] is False
        assert len(dp_events) == 1
        assert dp_events[0].details["success"] is False

    @patch("arena.combat.death_prevention.roll_die", return_value=15)
    def test_escalating_dc_tracks_uses(self, mock_roll):
        """Each use of Relentless Rage increases the DC by 5."""
        pc = _make_pc(
            features=[_relentless_rage()],
            ability_scores={
                "strength": 10, "dexterity": 10, "constitution": 16,
                "intelligence": 10, "wisdom": 10, "charisma": 10,
            },
        )

        # First drop: DC 10, roll 15+3=18 >= 10 -> success
        pc.current_hit_points = 5
        event1, dp1 = apply_damage(pc, 10, "slashing", creature_id="pc_1")
        assert pc.current_hit_points == 1
        assert dp1[0].details["dc"] == 10

        # Second drop: DC 15, roll 15+3=18 >= 15 -> success
        pc.current_hit_points = 5
        event2, dp2 = apply_damage(pc, 10, "slashing", creature_id="pc_1")
        assert pc.current_hit_points == 1
        assert dp2[0].details["dc"] == 15

        # Third drop: DC 20, roll 15+3=18 < 20 -> failure
        pc.current_hit_points = 5
        event3, dp3 = apply_damage(pc, 10, "slashing", creature_id="pc_1")
        assert pc.current_hit_points == 0
        assert dp3[0].details["dc"] == 20
        assert dp3[0].details["success"] is False
