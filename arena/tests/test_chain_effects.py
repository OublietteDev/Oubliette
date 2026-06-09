"""Tests for chain effect mechanics (Chain Lightning, etc.)."""

from __future__ import annotations

import pytest

from arena.combat.chain_effects import get_chain_targets, has_chain_effect
from arena.grid.coordinates import HexCoord
from arena.models.actions import Action, ActionType, DamageRoll, DamageType, TargetType
from arena.models.character import Creature


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_creature(name: str = "Target", hp: int = 50) -> Creature:
    return Creature(name=name, max_hit_points=hp)


def _make_chain_action(
    chain_count: int = 3,
    chain_range: int = 30,
) -> Action:
    return Action(
        name="Chain Lightning",
        description="Lightning arcs between targets",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        chain_target_count=chain_count,
        chain_range=chain_range,
    )


# ------------------------------------------------------------------
# has_chain_effect
# ------------------------------------------------------------------

class TestHasChainEffect:
    def test_action_with_chain(self):
        action = _make_chain_action(chain_count=3)
        assert has_chain_effect(action) is True

    def test_action_without_chain(self):
        action = Action(
            name="Fireball",
            description="Boom",
            chain_target_count=0,
        )
        assert has_chain_effect(action) is False

    def test_default_action_no_chain(self):
        action = Action(name="Attack", description="Hit")
        assert has_chain_effect(action) is False


# ------------------------------------------------------------------
# get_chain_targets
# ------------------------------------------------------------------

class TestGetChainTargets:
    """Tests for finding secondary chain targets."""

    def test_returns_up_to_chain_target_count(self):
        """3 creatures within range, chain_target_count=3 -> returns all 3."""
        action = _make_chain_action(chain_count=3, chain_range=30)
        combatants = {
            "caster": _make_creature("Caster"),
            "primary": _make_creature("Primary"),
            "sec1": _make_creature("Sec1"),
            "sec2": _make_creature("Sec2"),
            "sec3": _make_creature("Sec3"),
        }
        # Primary at center, secondaries within 6 hexes (30ft)
        positions = {
            "caster": HexCoord(0, 0),
            "primary": HexCoord(4, 4),
            "sec1": HexCoord(4, 5),   # 1 hex = 5ft
            "sec2": HexCoord(4, 6),   # 2 hexes = 10ft
            "sec3": HexCoord(6, 4),   # within range
        }
        result = get_chain_targets(
            action, "primary", combatants, positions, "caster"
        )
        assert len(result) == 3
        assert "sec1" in result
        assert "sec2" in result
        assert "sec3" in result

    def test_excludes_primary_and_caster(self):
        """Primary target and caster never appear in chain targets."""
        action = _make_chain_action(chain_count=5)
        combatants = {
            "caster": _make_creature("Caster"),
            "primary": _make_creature("Primary"),
            "sec1": _make_creature("Sec1"),
        }
        positions = {
            "caster": HexCoord(4, 3),   # Near primary
            "primary": HexCoord(4, 4),
            "sec1": HexCoord(4, 5),
        }
        result = get_chain_targets(
            action, "primary", combatants, positions, "caster"
        )
        assert "caster" not in result
        assert "primary" not in result
        assert result == ["sec1"]

    def test_excludes_already_chained(self):
        """excluded_ids are skipped."""
        action = _make_chain_action(chain_count=3)
        combatants = {
            "caster": _make_creature("Caster"),
            "primary": _make_creature("Primary"),
            "sec1": _make_creature("Sec1"),
            "sec2": _make_creature("Sec2"),
        }
        positions = {
            "caster": HexCoord(0, 0),
            "primary": HexCoord(4, 4),
            "sec1": HexCoord(4, 5),
            "sec2": HexCoord(4, 6),
        }
        result = get_chain_targets(
            action, "primary", combatants, positions, "caster",
            excluded_ids=["sec1"],
        )
        assert "sec1" not in result
        assert result == ["sec2"]

    def test_out_of_range_excluded(self):
        """Creatures beyond chain_range are not included."""
        action = _make_chain_action(chain_count=3, chain_range=10)
        combatants = {
            "caster": _make_creature("Caster"),
            "primary": _make_creature("Primary"),
            "close": _make_creature("Close"),
            "far": _make_creature("Far"),
        }
        positions = {
            "caster": HexCoord(0, 0),
            "primary": HexCoord(4, 4),
            "close": HexCoord(4, 5),    # 1 hex = 5ft, within 10ft
            "far": HexCoord(4, 10),     # well beyond 10ft
        }
        result = get_chain_targets(
            action, "primary", combatants, positions, "caster"
        )
        assert "close" in result
        assert "far" not in result

    def test_sorted_by_distance_closest_first(self):
        """Chain targets are returned closest-first."""
        action = _make_chain_action(chain_count=3, chain_range=30)
        combatants = {
            "caster": _make_creature("Caster"),
            "primary": _make_creature("Primary"),
            "near": _make_creature("Near"),
            "mid": _make_creature("Mid"),
            "far_ish": _make_creature("FarIsh"),
        }
        positions = {
            "caster": HexCoord(0, 0),
            "primary": HexCoord(4, 4),
            "near": HexCoord(4, 5),     # 1 hex
            "mid": HexCoord(4, 6),      # 2 hexes
            "far_ish": HexCoord(4, 7),  # 3 hexes
        }
        result = get_chain_targets(
            action, "primary", combatants, positions, "caster"
        )
        assert result == ["near", "mid", "far_ish"]

    def test_unconscious_excluded(self):
        """Unconscious creatures are not valid chain targets."""
        action = _make_chain_action(chain_count=3)
        alive = _make_creature("Alive", hp=50)
        downed = Creature(name="Downed", max_hit_points=50, current_hit_points=0)

        combatants = {
            "caster": _make_creature("Caster"),
            "primary": _make_creature("Primary"),
            "alive": alive,
            "downed": downed,
        }
        positions = {
            "caster": HexCoord(0, 0),
            "primary": HexCoord(4, 4),
            "alive": HexCoord(4, 5),
            "downed": HexCoord(4, 6),
        }
        result = get_chain_targets(
            action, "primary", combatants, positions, "caster"
        )
        assert "alive" in result
        assert "downed" not in result

    def test_no_chain_effect_returns_empty(self):
        """chain_target_count=0 returns empty list."""
        action = Action(name="Firebolt", description="Zap", chain_target_count=0)
        combatants = {
            "caster": _make_creature("Caster"),
            "primary": _make_creature("Primary"),
            "other": _make_creature("Other"),
        }
        positions = {
            "caster": HexCoord(0, 0),
            "primary": HexCoord(4, 4),
            "other": HexCoord(4, 5),
        }
        result = get_chain_targets(
            action, "primary", combatants, positions, "caster"
        )
        assert result == []

    def test_fewer_available_than_chain_count(self):
        """Only 1 creature nearby but chain_target_count=3 -> returns 1."""
        action = _make_chain_action(chain_count=3, chain_range=30)
        combatants = {
            "caster": _make_creature("Caster"),
            "primary": _make_creature("Primary"),
            "only_one": _make_creature("OnlyOne"),
        }
        positions = {
            "caster": HexCoord(0, 0),
            "primary": HexCoord(4, 4),
            "only_one": HexCoord(4, 5),
        }
        result = get_chain_targets(
            action, "primary", combatants, positions, "caster"
        )
        assert result == ["only_one"]

    def test_chain_lightning_scenario(self):
        """Full Chain Lightning scenario: 3 arcs from primary, within 30ft."""
        action = _make_chain_action(chain_count=3, chain_range=30)
        combatants = {
            "wizard": _make_creature("Wizard"),
            "ogre": _make_creature("Ogre"),
            "goblin1": _make_creature("Goblin1"),
            "goblin2": _make_creature("Goblin2"),
            "goblin3": _make_creature("Goblin3"),
            "goblin4": _make_creature("Goblin4"),  # 4th, won't be picked
        }
        # Ogre is primary; goblins clustered nearby
        positions = {
            "wizard": HexCoord(0, 0),
            "ogre": HexCoord(6, 6),
            "goblin1": HexCoord(6, 7),   # 1 hex
            "goblin2": HexCoord(6, 8),   # 2 hexes
            "goblin3": HexCoord(7, 6),   # 1 hex
            "goblin4": HexCoord(6, 10),  # 4 hexes = 20ft, still in range
        }
        result = get_chain_targets(
            action, "ogre", combatants, positions, "wizard"
        )
        # Should pick 3 closest
        assert len(result) == 3
        assert "ogre" not in result
        assert "wizard" not in result

    def test_primary_not_in_positions(self):
        """If primary has no position, return empty."""
        action = _make_chain_action(chain_count=3)
        combatants = {
            "caster": _make_creature("Caster"),
            "primary": _make_creature("Primary"),
            "other": _make_creature("Other"),
        }
        positions = {
            "caster": HexCoord(0, 0),
            # primary NOT in positions
            "other": HexCoord(4, 5),
        }
        result = get_chain_targets(
            action, "primary", combatants, positions, "caster"
        )
        assert result == []
