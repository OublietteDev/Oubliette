"""Tests for combat event system."""

import pytest
from arena.combat.events import CombatEvent, CombatEventType, CombatLog


class TestCombatEvent:
    """Tests for CombatEvent creation."""

    def test_create_basic_event(self):
        event = CombatEvent(
            event_type=CombatEventType.INFO,
            message="Something happened",
        )
        assert event.event_type == CombatEventType.INFO
        assert event.message == "Something happened"
        assert event.source_id is None
        assert event.target_id is None
        assert event.details == {}

    def test_create_event_with_details(self):
        event = CombatEvent(
            event_type=CombatEventType.ATTACK_ROLL,
            message="Fighter attacks Goblin",
            source_id="fighter_1",
            target_id="goblin_1",
            details={"roll": 18, "hit": True},
        )
        assert event.source_id == "fighter_1"
        assert event.target_id == "goblin_1"
        assert event.details["roll"] == 18

    def test_all_event_types_exist(self):
        expected = [
            "COMBAT_START", "ROUND_START", "TURN_START", "TURN_END",
            "MOVEMENT", "ATTACK_ROLL", "DAMAGE", "CREATURE_DOWNED",
            "COMBAT_END", "INFO",
        ]
        for name in expected:
            assert hasattr(CombatEventType, name)


class TestCombatLog:
    """Tests for CombatLog."""

    def test_empty_log(self):
        log = CombatLog()
        assert len(log.events) == 0

    def test_add_event(self):
        log = CombatLog()
        event = CombatEvent(
            event_type=CombatEventType.INFO,
            message="Test",
        )
        log.add(event)
        assert len(log.events) == 1
        assert log.events[0].message == "Test"

    def test_add_multiple_events(self):
        log = CombatLog()
        for i in range(5):
            log.add(CombatEvent(
                event_type=CombatEventType.INFO,
                message=f"Event {i}",
            ))
        assert len(log.events) == 5
        assert log.events[0].message == "Event 0"
        assert log.events[4].message == "Event 4"

    def test_clear(self):
        log = CombatLog()
        log.add(CombatEvent(event_type=CombatEventType.INFO, message="Test"))
        log.clear()
        assert len(log.events) == 0

    def test_events_ordered_chronologically(self):
        log = CombatLog()
        log.add(CombatEvent(event_type=CombatEventType.COMBAT_START, message="Start"))
        log.add(CombatEvent(event_type=CombatEventType.TURN_START, message="Turn 1"))
        log.add(CombatEvent(event_type=CombatEventType.ATTACK_ROLL, message="Attack"))
        assert log.events[0].event_type == CombatEventType.COMBAT_START
        assert log.events[2].event_type == CombatEventType.ATTACK_ROLL
