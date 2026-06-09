"""Tests that apply_condition() checks active and aura condition immunities."""

import unittest

from arena.models.character import Creature, PlayerCharacter, Feature
from arena.models.conditions import Condition
from arena.combat.conditions import apply_condition
from arena.grid.coordinates import HexCoord


def _make_creature(name: str = "Target", hp: int = 50, **kwargs) -> Creature:
    return Creature(name=name, max_hit_points=hp, **kwargs)


def _make_pc(name: str = "Target", hp: int = 50, **kwargs) -> PlayerCharacter:
    """Create a PlayerCharacter (has features/feats/class_resources)."""
    kwargs.setdefault("character_class", "Barbarian")
    kwargs.setdefault("level", 6)
    kwargs.setdefault("is_player_controlled", True)
    return PlayerCharacter(name=name, max_hit_points=hp, **kwargs)


class TestActiveConditionImmunityWiring(unittest.TestCase):
    """apply_condition() should block conditions via active feature immunities."""

    def test_active_immunity_blocks_condition(self):
        """A creature with active_condition_immunities should be immune."""
        creature = _make_pc(
            features=[
                Feature(
                    name="Mindless Rage",
                    description="Immune to charmed/frightened while raging",
                    active_condition_immunities=["charmed", "frightened"],
                    active_condition_resource=None,  # passive = always active
                )
            ]
        )
        result = apply_condition(creature, "target_1", Condition.CHARMED, source="spell")
        self.assertIsNone(result, "Should return None for active-immune condition")
        self.assertFalse(
            any(ac.condition == Condition.CHARMED for ac in creature.active_conditions),
            "Condition should not be applied",
        )

    def test_resource_gated_immunity_blocks_when_resource_active(self):
        """Resource-gated immunity blocks when the resource is > 0."""
        creature = _make_pc(
            features=[
                Feature(
                    name="Mindless Rage",
                    description="Immune to charmed/frightened while raging",
                    active_condition_immunities=["charmed"],
                    active_condition_resource="rage",
                )
            ],
            class_resources={"rage": 2},
        )
        result = apply_condition(creature, "target_1", Condition.CHARMED, source="spell")
        self.assertIsNone(result)

    def test_resource_gated_immunity_allows_when_resource_empty(self):
        """Resource-gated immunity does NOT block when resource is 0."""
        creature = _make_pc(
            features=[
                Feature(
                    name="Mindless Rage",
                    description="Immune to charmed/frightened while raging",
                    active_condition_immunities=["charmed"],
                    active_condition_resource="rage",
                )
            ],
            class_resources={"rage": 0},
        )
        result = apply_condition(creature, "target_1", Condition.CHARMED, source="spell")
        self.assertIsNotNone(result, "Should apply condition when resource is depleted")
        self.assertTrue(
            any(ac.condition == Condition.CHARMED for ac in creature.active_conditions),
        )

    def test_no_active_immunity_allows_condition(self):
        """A creature without active immunities gets the condition normally."""
        creature = _make_creature()
        result = apply_condition(creature, "target_1", Condition.STUNNED, source="spell")
        self.assertIsNotNone(result)
        self.assertTrue(
            any(ac.condition == Condition.STUNNED for ac in creature.active_conditions),
        )


class TestStaticImmunityRegression(unittest.TestCase):
    """Static condition immunities should still work after the wiring change."""

    def test_static_immunity_still_blocks(self):
        """creature.condition_immunities should still block conditions."""
        creature = _make_creature(condition_immunities=["prone"])
        result = apply_condition(creature, "target_1", Condition.PRONE, source="shove")
        self.assertIsNone(result, "Static immunity should still block")
        self.assertFalse(
            any(ac.condition == Condition.PRONE for ac in creature.active_conditions),
        )

    def test_non_immune_condition_still_applies(self):
        """A condition not in the immunity list should still apply."""
        creature = _make_creature(condition_immunities=["prone"])
        result = apply_condition(creature, "target_1", Condition.RESTRAINED, source="web")
        self.assertIsNotNone(result)


class TestAuraConditionImmunityWiring(unittest.TestCase):
    """apply_condition() should check aura-based condition immunities when given combatants/positions."""

    def _make_paladin_courage(self):
        """Paladin with Aura of Courage (frightened immunity in 10ft)."""
        return _make_pc(
            name="Paladin",
            hp=80,
            character_class="Paladin",
            level=10,
            is_player_controlled=True,
            features=[
                Feature(
                    name="Aura of Courage",
                    description="Allies within aura immune to frightened",
                    aura_range=10,
                    aura_condition_immunity=["frightened"],
                    aura_requires_conscious=True,
                )
            ],
        )

    def test_aura_immunity_blocks_condition(self):
        """Creature within aura range should be immune to the aura's condition."""
        paladin = self._make_paladin_courage()
        ally = _make_creature(name="Fighter", is_player_controlled=True)

        combatants = {"paladin_1": paladin, "fighter_1": ally}
        positions = {
            "paladin_1": HexCoord(0, 0),
            "fighter_1": HexCoord(1, 0),  # distance=1 hex = 5ft, within 10ft aura
        }

        result = apply_condition(
            ally, "fighter_1", Condition.FRIGHTENED, source="dragon_fear",
            combatants=combatants, positions=positions,
        )
        self.assertIsNone(result, "Aura immunity should block frightened")

    def test_aura_immunity_no_effect_without_combatants(self):
        """Without combatants/positions, aura check is skipped (backward compat)."""
        ally = _make_creature(name="Fighter", is_player_controlled=True)

        # Don't pass combatants/positions -- aura check should be skipped
        result = apply_condition(
            ally, "fighter_1", Condition.FRIGHTENED, source="dragon_fear",
        )
        self.assertIsNotNone(result, "Without combatants, condition should apply")

    def test_aura_immunity_out_of_range(self):
        """Creature outside aura range should NOT be immune."""
        paladin = self._make_paladin_courage()
        ally = _make_creature(name="Fighter", is_player_controlled=True)

        combatants = {"paladin_1": paladin, "fighter_1": ally}
        positions = {
            "paladin_1": HexCoord(0, 0),
            "fighter_1": HexCoord(5, 5),  # far away, outside 10ft aura
        }

        result = apply_condition(
            ally, "fighter_1", Condition.FRIGHTENED, source="dragon_fear",
            combatants=combatants, positions=positions,
        )
        self.assertIsNotNone(result, "Out-of-range creature should not be immune")

    def test_aura_does_not_block_non_listed_condition(self):
        """Aura of Courage blocks frightened but not stunned."""
        paladin = self._make_paladin_courage()
        ally = _make_creature(name="Fighter", is_player_controlled=True)

        combatants = {"paladin_1": paladin, "fighter_1": ally}
        positions = {
            "paladin_1": HexCoord(0, 0),
            "fighter_1": HexCoord(1, 0),
        }

        result = apply_condition(
            ally, "fighter_1", Condition.STUNNED, source="monk",
            combatants=combatants, positions=positions,
        )
        self.assertIsNotNone(result, "Aura should not block non-listed conditions")


if __name__ == "__main__":
    unittest.main()
