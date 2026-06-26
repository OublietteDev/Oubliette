"""Tests for player-initiated Grapple (D-ACT-2).

Grapple mirrors Shove (contested Athletics) but applies GRAPPLED — speed 0,
held until the target escapes (execute_escape_grapple, contested vs the
grappler's Athletics since no fixed DC is stored) or the grappler goes down
(_reconcile_grapples).
"""

from __future__ import annotations

from unittest.mock import patch

import pygame
import pytest

from arena.combat.conditions import has_condition
from arena.combat.condition_effects import get_movement_multiplier
from arena.models.character import CreatureSize
from arena.models.conditions import Condition

from arena.tests.test_forced_movement import (
    _make_fighter, _make_enemy, _setup_combat,
)


class TestExecuteGrapple:
    """CombatManager.execute_grapple()."""

    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        pygame.display.set_mode((1, 1))
        yield
        pygame.quit()

    def _advance_to(self, manager, creature_id):
        for _ in range(20):
            if (manager.active_combatant is None
                    or manager.active_combatant.creature_id == creature_id):
                break
            manager.end_turn()

    def test_grapple_success_applies_grappled(self):
        player = _make_fighter(strength=20, skill_proficiencies=["athletics"])
        enemy = _make_enemy(strength=8)
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(5, 4),
        )
        self._advance_to(manager, pid)

        with patch("arena.combat.forced_movement.roll_die", side_effect=[18, 3]):
            result = manager.execute_grapple(eid)

        assert result is not None
        assert result.success
        assert has_condition(manager.combatants[eid].creature, Condition.GRAPPLED)
        assert manager.turn_resources.has_used_action

    def test_grapple_sets_speed_zero(self):
        player = _make_fighter(strength=20, skill_proficiencies=["athletics"])
        enemy = _make_enemy(strength=8)
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(5, 4),
        )
        self._advance_to(manager, pid)

        with patch("arena.combat.forced_movement.roll_die", side_effect=[18, 3]):
            manager.execute_grapple(eid)

        assert get_movement_multiplier(manager.combatants[eid].creature) == 0.0

    def test_grapple_failure_no_condition(self):
        player = _make_fighter(strength=8)
        enemy = _make_enemy(strength=18, skill_proficiencies=["athletics"])
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(5, 4),
        )
        self._advance_to(manager, pid)

        with patch("arena.combat.forced_movement.roll_die", side_effect=[3, 18]):
            result = manager.execute_grapple(eid)

        assert result is not None
        assert not result.success
        assert not has_condition(
            manager.combatants[eid].creature, Condition.GRAPPLED)
        # Action is still spent on a failed grapple
        assert manager.turn_resources.has_used_action

    def test_grapple_out_of_range(self):
        player = _make_fighter()
        enemy = _make_enemy()
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(2, 2), enemy_pos=(5, 5),
        )
        self._advance_to(manager, pid)

        result = manager.execute_grapple(eid)
        assert result is None
        assert not manager.turn_resources.has_used_action

    def test_grapple_requires_action(self):
        player = _make_fighter()
        enemy = _make_enemy()
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(5, 4),
        )
        self._advance_to(manager, pid)
        manager.turn_resources.has_used_action = True

        assert manager.execute_grapple(eid) is None

    def test_grapple_cannot_target_self(self):
        player = _make_fighter()
        enemy = _make_enemy()
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(5, 4),
        )
        self._advance_to(manager, pid)

        assert manager.execute_grapple(pid) is None

    def test_grapple_size_limit(self):
        """A creature can't grapple something >1 size larger; action preserved."""
        player = _make_fighter()  # medium
        player.size = CreatureSize.TINY  # tiny vs medium = 2 sizes over
        enemy = _make_enemy()
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(5, 4),
        )
        self._advance_to(manager, pid)

        result = manager.execute_grapple(eid)
        assert result is not None
        assert not result.success
        assert not has_condition(
            manager.combatants[eid].creature, Condition.GRAPPLED)
        # Too-large grapple is a non-starter — the action is NOT consumed
        assert not manager.turn_resources.has_used_action

    def test_escape_after_player_grapple(self):
        """A player-applied grapple (no fixed DC) is escapable by contesting
        the grappler's Athletics."""
        player = _make_fighter(strength=20, skill_proficiencies=["athletics"])
        enemy = _make_enemy(strength=18, skill_proficiencies=["athletics"])
        manager, pid, eid = _setup_combat(
            player=player, enemy=enemy,
            player_pos=(4, 4), enemy_pos=(5, 4),
        )
        self._advance_to(manager, pid)

        with patch("arena.combat.forced_movement.roll_die", side_effect=[18, 3]):
            manager.execute_grapple(eid)
        assert has_condition(manager.combatants[eid].creature, Condition.GRAPPLED)

        # The enemy's turn: it rolls high, grappler rolls low → escapes.
        self._advance_to(manager, eid)
        with patch("arena.combat.manager.roll_die", side_effect=[19, 2]):
            esc = manager.execute_escape_grapple()

        assert esc is not None
        assert esc.success
        assert not has_condition(
            manager.combatants[eid].creature, Condition.GRAPPLED)
