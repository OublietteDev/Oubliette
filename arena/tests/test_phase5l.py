"""Tests for Phase 5l: Ready Action (Trigger System)."""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager
from arena.combat.ready_action import (
    ReadiedAction,
    TriggerType,
    set_ready_action,
    check_ready_triggers,
    expire_readied_actions,
)
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.encounter import Encounter, CombatantEntry
from arena.grid.coordinates import HexCoord


# ── Helpers ───────────────────────────────────────────────────────────

def _make_creature(name, hp=20, is_player=True):
    return Creature(
        name=name,
        max_hit_points=hp,
        ability_scores=AbilityScores(strength=14, dexterity=14),
        proficiency_bonus=2,
        speed={"walk": 30},
        is_player_controlled=is_player,
        actions=[
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
                        DamageRoll(dice="1d6", damage_type=DamageType.SLASHING,
                                   ability_modifier="strength")
                    ],
                ),
            )
        ],
    )


def _setup_combat():
    encounter = Encounter(
        name="Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="fighter",
                creature_data=_make_creature("Fighter", is_player=True),
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="goblin",
                creature_data=_make_creature("Goblin", is_player=False),
                team="enemy",
                starting_position=(5, 5),
            ),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    cm.roll_initiative()
    cm.begin_combat()
    return cm


def _skip_to_player(cm):
    for _ in range(20):
        active = cm.active_combatant
        if active and active.creature.is_player_controlled:
            return active
        cm.end_turn()
    return None


def _skip_to_enemy(cm):
    for _ in range(20):
        active = cm.active_combatant
        if active and not active.creature.is_player_controlled:
            return active
        cm.end_turn()
    return None


# ── TriggerType Tests ────────────────────────────────────────────────

class TestTriggerType:
    def test_trigger_types_exist(self):
        assert TriggerType.CREATURE_MOVES is not None
        assert TriggerType.CREATURE_ENTERS_RANGE is not None
        assert TriggerType.CREATURE_ATTACKS is not None
        assert TriggerType.CREATURE_CASTS is not None
        assert TriggerType.CUSTOM is not None


# ── ReadiedAction Tests ──────────────────────────────────────────────

class TestReadiedAction:
    def test_readied_action_creation(self):
        action = _make_creature("Test").actions[0]
        ra = ReadiedAction(
            creature_id="fighter",
            action=action,
            trigger_type=TriggerType.CREATURE_MOVES,
            trigger_target_id="goblin",
            description="When the goblin moves",
        )
        assert ra.creature_id == "fighter"
        assert ra.trigger_type == TriggerType.CREATURE_MOVES
        assert ra.trigger_target_id == "goblin"


# ── set_ready_action Tests ──────────────────────────────────────────

class TestSetReadyAction:
    def test_ready_action_uses_action(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        action = active.creature.actions[0]
        event = cm.execute_ready_action(
            action, TriggerType.CREATURE_MOVES, description="When enemy moves"
        )
        assert event is not None
        assert cm.turn_resources.has_used_action is True
        assert "readies" in event.message

    def test_ready_action_stored(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        action = active.creature.actions[0]
        cm.execute_ready_action(action, TriggerType.CREATURE_MOVES)
        assert active.creature_id in cm.readied_actions

    def test_ready_fails_if_action_used(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        cm.turn_resources.has_used_action = True
        action = active.creature.actions[0]
        event = cm.execute_ready_action(action, TriggerType.CREATURE_MOVES)
        assert event is None


# ── check_ready_triggers Tests ──────────────────────────────────────

class TestCheckReadyTriggers:
    def test_trigger_matches(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        # Get the enemy ID
        enemy_id = None
        for cid, c in cm.combatants.items():
            if c.team == "enemy":
                enemy_id = cid
                break

        action = active.creature.actions[0]
        cm.execute_ready_action(
            action, TriggerType.CREATURE_MOVES, trigger_target_id=enemy_id
        )

        # Simulate trigger
        events = check_ready_triggers(cm, TriggerType.CREATURE_MOVES, enemy_id)
        assert len(events) >= 1
        reaction_events = [e for e in events if e.event_type == CombatEventType.REACTION]
        assert len(reaction_events) == 1
        assert "readied action triggers" in reaction_events[0].message

    def test_trigger_wrong_type_no_match(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        action = active.creature.actions[0]
        cm.execute_ready_action(action, TriggerType.CREATURE_MOVES)

        # Wrong trigger type
        events = check_ready_triggers(cm, TriggerType.CREATURE_ATTACKS, "someone")
        assert len(events) == 0
        # Readied action should still be stored
        assert active.creature_id in cm.readied_actions

    def test_trigger_wrong_target_no_match(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        action = active.creature.actions[0]
        cm.execute_ready_action(
            action, TriggerType.CREATURE_MOVES, trigger_target_id="specific_enemy"
        )

        # Right trigger type but wrong creature
        events = check_ready_triggers(cm, TriggerType.CREATURE_MOVES, "different_enemy")
        assert len(events) == 0

    def test_trigger_uses_reaction(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        action = active.creature.actions[0]
        cm.execute_ready_action(action, TriggerType.CREATURE_MOVES)

        check_ready_triggers(cm, TriggerType.CREATURE_MOVES, "anyone")
        assert cm.reaction_used.get(active.creature_id, False) is True

    def test_trigger_removes_readied_action(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        action = active.creature.actions[0]
        cm.execute_ready_action(action, TriggerType.CREATURE_MOVES)
        assert active.creature_id in cm.readied_actions

        check_ready_triggers(cm, TriggerType.CREATURE_MOVES, "anyone")
        assert active.creature_id not in cm.readied_actions

    def test_no_trigger_if_reaction_used(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        action = active.creature.actions[0]
        cm.execute_ready_action(action, TriggerType.CREATURE_MOVES)
        cm.reaction_used[active.creature_id] = True

        events = check_ready_triggers(cm, TriggerType.CREATURE_MOVES, "anyone")
        assert len(events) == 0


# ── expire_readied_actions Tests ─────────────────────────────────────

class TestExpireReadiedActions:
    def test_readied_action_expires_on_turn_start(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        action = active.creature.actions[0]
        cm.execute_ready_action(action, TriggerType.CREATURE_MOVES)
        cid = active.creature_id

        # End turn and come back to this creature's turn
        cm.end_turn()  # Advance to next creature
        # Keep advancing until we get back to the same creature
        for _ in range(10):
            current = cm.active_combatant
            if current and current.creature_id == cid:
                break
            cm.end_turn()

        # The readied action should have expired
        assert cid not in cm.readied_actions

    def test_expire_logs_event(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        action = active.creature.actions[0]
        cm.execute_ready_action(action, TriggerType.CREATURE_MOVES)

        events = expire_readied_actions(cm, active.creature_id)
        assert len(events) == 1
        assert "expires unused" in events[0].message


# ── reset Tests ──────────────────────────────────────────────────────

class TestReadyActionReset:
    def test_readied_actions_cleared_on_reset(self):
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        action = active.creature.actions[0]
        cm.execute_ready_action(action, TriggerType.CREATURE_MOVES)
        assert len(cm.readied_actions) > 0

        cm.reset()
        assert cm.readied_actions == {}
