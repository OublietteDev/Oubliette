"""Tests for aura effects system (Paladin Aura of Protection, Aura of Courage, etc.)."""

from unittest.mock import patch

import pytest

from arena.models.character import PlayerCharacter, Feature
from arena.models.abilities import AbilityScores
from arena.grid.coordinates import HexCoord
from arena.combat.auras import (
    get_aura_save_bonus,
    get_aura_condition_immunities,
    _get_aura_features,
)
from arena.combat.actions import resolve_saving_throw


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_paladin(
    name: str = "Paladin",
    charisma: int = 16,
    hp: int = 40,
    aura_range: int = 10,
    is_player: bool = True,
) -> PlayerCharacter:
    """Create a paladin with Aura of Protection."""
    return PlayerCharacter(
        name=name,
        character_class="Paladin",
        level=6,
        max_hit_points=hp,
        current_hit_points=hp,
        ability_scores=AbilityScores(
            strength=16, dexterity=10, constitution=14,
            intelligence=10, wisdom=12, charisma=charisma,
        ),
        is_player_controlled=is_player,
        features=[
            Feature(
                name="Aura of Protection",
                description="Allies within range add CHA mod to saves.",
                aura_range=aura_range,
                aura_save_bonus_ability="charisma",
                aura_requires_conscious=True,
            ),
        ],
    )


def _make_paladin_courage(
    name: str = "Paladin",
    hp: int = 40,
    aura_range: int = 10,
    is_player: bool = True,
) -> PlayerCharacter:
    """Create a paladin with Aura of Courage."""
    return PlayerCharacter(
        name=name,
        character_class="Paladin",
        level=10,
        max_hit_points=hp,
        current_hit_points=hp,
        ability_scores=AbilityScores(
            strength=16, dexterity=10, constitution=14,
            intelligence=10, wisdom=12, charisma=16,
        ),
        is_player_controlled=is_player,
        features=[
            Feature(
                name="Aura of Courage",
                description="Allies within range are immune to frightened.",
                aura_range=aura_range,
                aura_condition_immunity=["frightened"],
                aura_requires_conscious=True,
            ),
        ],
    )


def _make_fighter(
    name: str = "Fighter",
    hp: int = 40,
    is_player: bool = True,
) -> PlayerCharacter:
    """Create a simple fighter with no aura."""
    return PlayerCharacter(
        name=name,
        character_class="Fighter",
        level=5,
        max_hit_points=hp,
        current_hit_points=hp,
        ability_scores=AbilityScores(
            strength=16, dexterity=14, constitution=14,
            intelligence=10, wisdom=12, charisma=8,
        ),
        is_player_controlled=is_player,
    )


# ---------------------------------------------------------------------------
# get_aura_save_bonus tests
# ---------------------------------------------------------------------------

class TestGetAuraSaveBonus:
    """Tests for get_aura_save_bonus()."""

    def test_ally_within_range_grants_bonus(self):
        """Paladin with CHA 16 (+3) within 10ft grants +3 to ally saves."""
        paladin = _make_paladin(charisma=16)
        fighter = _make_fighter()

        combatants = {"paladin_1": paladin, "fighter_1": fighter}
        # 1 hex apart = 5 ft, within 10ft aura
        positions = {"paladin_1": HexCoord(3, 3), "fighter_1": HexCoord(3, 4)}

        bonus = get_aura_save_bonus(
            fighter, "fighter_1", combatants, positions, "wisdom",
        )
        assert bonus == 3

    def test_ally_out_of_range_no_bonus(self):
        """Paladin more than 10ft (2 hexes) away grants no bonus."""
        paladin = _make_paladin(charisma=16, aura_range=10)
        fighter = _make_fighter()

        combatants = {"paladin_1": paladin, "fighter_1": fighter}
        # 3 hexes apart = 15 ft, outside 10ft aura
        positions = {"paladin_1": HexCoord(3, 3), "fighter_1": HexCoord(3, 6)}

        bonus = get_aura_save_bonus(
            fighter, "fighter_1", combatants, positions, "wisdom",
        )
        assert bonus == 0

    def test_unconscious_paladin_no_bonus(self):
        """Unconscious paladin (HP 0) with aura_requires_conscious grants no bonus."""
        paladin = _make_paladin(charisma=16, hp=40)
        paladin.current_hit_points = 0  # KO the paladin
        fighter = _make_fighter()

        combatants = {"paladin_1": paladin, "fighter_1": fighter}
        positions = {"paladin_1": HexCoord(3, 3), "fighter_1": HexCoord(3, 4)}

        bonus = get_aura_save_bonus(
            fighter, "fighter_1", combatants, positions, "wisdom",
        )
        assert bonus == 0

    def test_creature_benefits_from_own_aura(self):
        """A paladin benefits from their own Aura of Protection."""
        paladin = _make_paladin(charisma=16)

        combatants = {"paladin_1": paladin}
        positions = {"paladin_1": HexCoord(3, 3)}

        bonus = get_aura_save_bonus(
            paladin, "paladin_1", combatants, positions, "dexterity",
        )
        assert bonus == 3

    def test_enemy_aura_does_not_apply(self):
        """Enemy paladin's aura doesn't help creatures on the other side."""
        enemy_paladin = _make_paladin(charisma=20, is_player=False)
        fighter = _make_fighter(is_player=True)

        combatants = {"enemy_paladin": enemy_paladin, "fighter_1": fighter}
        positions = {"enemy_paladin": HexCoord(3, 3), "fighter_1": HexCoord(3, 4)}

        bonus = get_aura_save_bonus(
            fighter, "fighter_1", combatants, positions, "wisdom",
        )
        assert bonus == 0

    def test_negative_charisma_gives_zero_bonus(self):
        """Paladin with negative CHA mod gives minimum 0 bonus, not negative."""
        paladin = _make_paladin(charisma=6)  # -2 mod
        fighter = _make_fighter()

        combatants = {"paladin_1": paladin, "fighter_1": fighter}
        positions = {"paladin_1": HexCoord(3, 3), "fighter_1": HexCoord(3, 4)}

        bonus = get_aura_save_bonus(
            fighter, "fighter_1", combatants, positions, "wisdom",
        )
        assert bonus == 0

    def test_creature_not_in_positions_returns_zero(self):
        """Creature not in positions dict gets 0 bonus."""
        paladin = _make_paladin()
        fighter = _make_fighter()

        combatants = {"paladin_1": paladin, "fighter_1": fighter}
        positions = {"paladin_1": HexCoord(3, 3)}  # fighter not positioned

        bonus = get_aura_save_bonus(
            fighter, "fighter_1", combatants, positions, "wisdom",
        )
        assert bonus == 0

    def test_extended_aura_range(self):
        """30ft aura (18th level paladin) reaches 6 hexes."""
        paladin = _make_paladin(charisma=16, aura_range=30)
        fighter = _make_fighter()

        combatants = {"paladin_1": paladin, "fighter_1": fighter}
        # 5 hexes = 25ft, within 30ft aura
        positions = {"paladin_1": HexCoord(3, 3), "fighter_1": HexCoord(3, 8)}

        bonus = get_aura_save_bonus(
            fighter, "fighter_1", combatants, positions, "wisdom",
        )
        assert bonus == 3


# ---------------------------------------------------------------------------
# get_aura_condition_immunities tests
# ---------------------------------------------------------------------------

class TestGetAuraConditionImmunities:
    """Tests for get_aura_condition_immunities()."""

    def test_ally_within_range_grants_immunity(self):
        """Paladin with Aura of Courage within range grants frightened immunity."""
        paladin = _make_paladin_courage()
        fighter = _make_fighter()

        combatants = {"paladin_1": paladin, "fighter_1": fighter}
        positions = {"paladin_1": HexCoord(3, 3), "fighter_1": HexCoord(3, 4)}

        immunities = get_aura_condition_immunities(
            fighter, "fighter_1", combatants, positions,
        )
        assert "frightened" in immunities

    def test_ally_out_of_range_no_immunity(self):
        """Paladin outside aura range grants no immunity."""
        paladin = _make_paladin_courage(aura_range=10)
        fighter = _make_fighter()

        combatants = {"paladin_1": paladin, "fighter_1": fighter}
        # 4 hexes = 20ft, outside 10ft aura
        positions = {"paladin_1": HexCoord(3, 3), "fighter_1": HexCoord(3, 7)}

        immunities = get_aura_condition_immunities(
            fighter, "fighter_1", combatants, positions,
        )
        assert immunities == []

    def test_unconscious_paladin_no_immunity(self):
        """Unconscious paladin grants no condition immunity."""
        paladin = _make_paladin_courage(hp=40)
        paladin.current_hit_points = 0  # KO the paladin
        fighter = _make_fighter()

        combatants = {"paladin_1": paladin, "fighter_1": fighter}
        positions = {"paladin_1": HexCoord(3, 3), "fighter_1": HexCoord(3, 4)}

        immunities = get_aura_condition_immunities(
            fighter, "fighter_1", combatants, positions,
        )
        assert immunities == []


# ---------------------------------------------------------------------------
# _get_aura_features tests
# ---------------------------------------------------------------------------

class TestGetAuraFeatures:
    """Tests for _get_aura_features()."""

    def test_returns_features_with_aura_range(self):
        paladin = _make_paladin()
        features = _get_aura_features(paladin)
        assert len(features) == 1
        assert features[0].name == "Aura of Protection"

    def test_returns_empty_for_no_aura(self):
        fighter = _make_fighter()
        features = _get_aura_features(fighter)
        assert features == []


# ---------------------------------------------------------------------------
# Integration: resolve_saving_throw with aura bonus
# ---------------------------------------------------------------------------

class TestResolveSavingThrowAuraIntegration:
    """Integration tests for aura bonus in resolve_saving_throw()."""

    @patch("arena.combat.actions.roll_die", return_value=10)
    def test_aura_bonus_applied_when_params_provided(self, mock_roll):
        """resolve_saving_throw includes aura bonus when combatants/positions given."""
        paladin = _make_paladin(charisma=16)  # +3 CHA mod
        fighter = _make_fighter()

        combatants = {"paladin_1": paladin, "fighter_1": fighter}
        positions = {"paladin_1": HexCoord(3, 3), "fighter_1": HexCoord(3, 4)}

        # Fighter: WIS mod = +1, no proficiency, +3 aura = +4 total
        # Roll 10 + 4 = 14 vs DC 15 => fail
        success, event = resolve_saving_throw(
            fighter, "fighter_1", "wisdom", dc=15,
            combatants=combatants, positions=positions,
        )
        assert not success
        assert "[aura: +3]" in event.message

        # Same roll vs DC 14 => success (10 + 1 + 3 = 14 >= 14)
        success2, event2 = resolve_saving_throw(
            fighter, "fighter_1", "wisdom", dc=14,
            combatants=combatants, positions=positions,
        )
        assert success2

    @patch("arena.combat.actions.roll_die", return_value=10)
    def test_no_aura_when_params_omitted(self, mock_roll):
        """resolve_saving_throw works normally without combatants/positions (backward compat)."""
        fighter = _make_fighter()

        # Fighter: WIS mod = +1, no proficiency
        # Roll 10 + 1 = 11 vs DC 12 => fail
        success, event = resolve_saving_throw(
            fighter, "fighter_1", "wisdom", dc=12,
        )
        assert not success
        assert "[aura:" not in event.message
