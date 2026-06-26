"""Tests for the C5 prone movement penalty.

Standing up from prone costs half the creature's speed in movement and clears
the PRONE condition — but it is movement, not an action, so it never touches
the action economy. A creature that stays prone and crawls pays double for
every foot of movement (modeled as a per-hex cost multiplier of 2).
"""
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager
from arena.combat.conditions import apply_condition, has_condition
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.grid.pathfinding import get_reachable_hexes
from arena.models.abilities import AbilityScores
from arena.models.character import Creature, CreatureType
from arena.models.conditions import Condition
from arena.models.encounter import Encounter, CombatantEntry


def _combat(prone: bool = True):
    """A 2-creature fight where the player hero acts first (initiative 20)."""
    hero = Creature(name="Hero", max_hit_points=30,
                    ability_scores=AbilityScores(strength=14), proficiency_bonus=2,
                    is_player_controlled=True)
    dummy = Creature(name="Dummy", max_hit_points=20,
                     ability_scores=AbilityScores(), proficiency_bonus=2,
                     is_player_controlled=False, creature_type=CreatureType.HUMANOID)
    if prone:
        apply_condition(hero, "hero", Condition.PRONE, source="test",
                        duration_type="indefinite")
    enc = Encounter(name="t", grid_width=12, grid_height=12, combatants=[
        CombatantEntry(creature_id="hero", creature_data=hero, team="player",
                       starting_position=(4, 4)),
        CombatantEntry(creature_id="dummy", creature_data=dummy, team="enemy",
                       starting_position=(8, 8)),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
        cm.roll_initiative()
    cm.begin_combat()
    return cm


class TestStandUp:
    def test_costs_half_speed_and_clears_prone(self):
        cm = _combat()
        cm.movement.reset("hero", 30)
        cm.movement.cost_multiplier = 2
        ev = cm.execute_standard_action("stand_up")
        assert ev is not None
        assert not has_condition(cm.combatants["hero"].creature, Condition.PRONE)
        assert cm.movement.remaining_movement == 15  # spent half of 30
        assert cm.movement.cost_multiplier == 1      # crawl penalty cleared

    def test_blocked_when_not_enough_movement(self):
        cm = _combat()
        cm.movement.reset("hero", 30)
        cm.movement.remaining_movement = 10  # less than the 15 needed to stand
        cm.movement.cost_multiplier = 2
        ev = cm.execute_standard_action("stand_up")
        # Still prone, nothing spent, but a helpful info event came back.
        assert has_condition(cm.combatants["hero"].creature, Condition.PRONE)
        assert cm.movement.remaining_movement == 10
        assert ev is not None and "stand up" in ev.message.lower()

    def test_noop_when_not_prone(self):
        cm = _combat(prone=False)
        cm.movement.reset("hero", 30)
        assert cm.execute_standard_action("stand_up") is None

    def test_standing_is_not_an_action(self):
        cm = _combat()
        cm.movement.reset("hero", 30)
        # Pretend the hero already attacked this turn.
        cm.turn_resources.has_used_action = True
        ev = cm.execute_standard_action("stand_up")
        assert ev is not None
        assert not has_condition(cm.combatants["hero"].creature, Condition.PRONE)
        # The action slot is untouched — standing only cost movement.
        assert cm.turn_resources.has_used_action is True
        assert cm.movement.remaining_movement == 15


class TestProneTurnStart:
    def test_prone_creature_gets_full_budget_but_double_cost(self):
        # The active hero is prone at the start of combat: full movement budget,
        # but each hex costs double (the crawl penalty).
        cm = _combat()
        assert cm.active_combatant.creature_id == "hero"
        assert cm.movement.max_movement == 30
        assert cm.movement.cost_multiplier == 2


class TestCrawlReachability:
    def _grid(self):
        g = HexGrid(width=12, height=12)
        g.place_creature(HexCoord(4, 4), "hero")
        return g

    def test_crawl_halves_reach(self):
        g = self._grid()
        start = HexCoord(4, 4)
        walk = get_reachable_hexes(start, g, 30, creature_id="hero")
        crawl = get_reachable_hexes(start, g, 30, creature_id="hero",
                                    cost_multiplier=2)
        # Crawling reaches a strictly smaller set, and every crawl-reachable
        # hex costs twice what it would cost walking.
        assert len(crawl) < len(walk)
        for key, cost in crawl.items():
            assert cost == walk[key] * 2
