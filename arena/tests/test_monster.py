"""Tests for monster models."""

import pytest
from arena.models.monster import Monster
from arena.models.character import Feature, CreatureSize, CreatureType


class TestMonster:
    """Tests for the Monster model."""

    def test_monster_creation(self):
        """Basic monster creation should work."""
        monster = Monster(name="Goblin", max_hit_points=7)
        assert monster.name == "Goblin"
        assert monster.max_hit_points == 7

    def test_default_ai_controlled(self):
        """Monsters should be AI-controlled by default."""
        monster = Monster(name="Test", max_hit_points=10)
        assert monster.is_player_controlled is False

    def test_default_ai_profile(self):
        """Monsters should have a default AI profile."""
        monster = Monster(name="Test", max_hit_points=10)
        assert monster.ai_profile == "default_monster"

    def test_challenge_rating(self):
        """Challenge rating should be stored correctly."""
        monster = Monster(
            name="Young Dragon",
            max_hit_points=178,
            challenge_rating=10,
            experience_points=5900,
        )
        assert monster.challenge_rating == 10
        assert monster.experience_points == 5900

    def test_fractional_challenge_rating(self):
        """Fractional CR values should work."""
        monster = Monster(name="Goblin", max_hit_points=7, challenge_rating=0.25)
        assert monster.challenge_rating == 0.25

    def test_legendary_actions(self):
        """Legendary action tracking should work."""
        from arena.models.actions import Action, ActionType

        monster = Monster(
            name="Dragon",
            max_hit_points=200,
            legendary_action_count=3,
            legendary_actions=[
                Action(
                    name="Tail Attack",
                    description="The dragon makes a tail attack.",
                    action_type=ActionType.LEGENDARY,
                    legendary_action_cost=1,
                ),
                Action(
                    name="Wing Attack",
                    description="The dragon beats its wings.",
                    action_type=ActionType.LEGENDARY,
                    legendary_action_cost=2,
                ),
            ],
        )
        assert monster.legendary_action_count == 3
        assert len(monster.legendary_actions) == 2
        assert monster.legendary_actions[0].legendary_action_cost == 1
        assert monster.legendary_actions[1].legendary_action_cost == 2

    def test_special_abilities(self):
        """Special abilities should be stored correctly."""
        monster = Monster(
            name="Wolf",
            max_hit_points=11,
            special_abilities=[
                Feature(name="Pack Tactics", description="Advantage when ally is adjacent"),
                Feature(name="Keen Hearing and Smell", description="Advantage on Perception"),
            ],
        )
        assert len(monster.special_abilities) == 2
        assert monster.special_abilities[0].name == "Pack Tactics"

    def test_source_info(self):
        """Source book information should be stored."""
        monster = Monster(
            name="Goblin",
            max_hit_points=7,
            source_book="Monster Manual",
            source_page=166,
        )
        assert monster.source_book == "Monster Manual"
        assert monster.source_page == 166

    def test_monster_inherits_creature(self):
        """Monster should inherit all Creature properties."""
        monster = Monster(
            name="Ogre",
            max_hit_points=59,
            size=CreatureSize.LARGE,
            creature_type=CreatureType.GIANT,
            armor_class=11,
            speed={"walk": 40},
        )
        assert monster.size == CreatureSize.LARGE
        assert monster.creature_type == CreatureType.GIANT
        assert monster.armor_class == 11
        assert monster.speed["walk"] == 40
        assert monster.current_hit_points == 59  # Inherited auto-set
