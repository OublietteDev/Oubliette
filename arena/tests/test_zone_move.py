"""Tests for movable zone feature (Moonbeam/Flaming Sphere style)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant
from arena.combat.events import CombatEventType
from arena.combat.zones import ActiveZone, get_zone_hexes, is_in_zone
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action,
    ActionType,
    DamageRoll,
    DamageType,
    SavingThrowEffect,
    TargetType,
)
from arena.models.character import Creature, PlayerCharacter
from arena.models.encounter import CombatantEntry, Encounter


# ── Helpers ──────────────────────────────────────────────────────────


def _moonbeam_action() -> Action:
    """Moonbeam: concentration AoE, zone movable as action."""
    return Action(
        name="Moonbeam",
        description="A silvery beam.",
        action_type=ActionType.ACTION,
        target_type=TargetType.AREA_CYLINDER,
        range=120,
        area_size=5,
        requires_concentration=True,
        zone_move_cost="action",
        saving_throw=SavingThrowEffect(
            ability="constitution",
            dc=15,
            damage_on_fail=[DamageRoll(dice="2d10", damage_type=DamageType.RADIANT)],
            damage_on_success="half",
        ),
        resource_cost={"spell_slot_2": 1},
    )


def _flaming_sphere_action() -> Action:
    """Flaming Sphere: concentration AoE, zone movable as bonus action."""
    return Action(
        name="Flaming Sphere",
        description="A ball of fire.",
        action_type=ActionType.ACTION,
        target_type=TargetType.AREA_SPHERE,
        range=60,
        area_size=5,
        requires_concentration=True,
        zone_move_cost="bonus_action",
        saving_throw=SavingThrowEffect(
            ability="dexterity",
            dc=14,
            damage_on_fail=[DamageRoll(dice="2d6", damage_type=DamageType.FIRE)],
            damage_on_success="half",
        ),
        resource_cost={"spell_slot_2": 1},
    )


def _make_player(actions=None) -> PlayerCharacter:
    return PlayerCharacter(
        name="Druid",
        max_hit_points=40,
        armor_class=14,
        ability_scores=AbilityScores(wisdom=16),
        proficiency_bonus=3,
        is_player_controlled=True,
        character_class="Druid",
        level=5,
        class_resources={"spell_slot_2": 3},
        actions=actions or [],
    )


def _make_enemy(name="Goblin", hp=15) -> Creature:
    return Creature(
        name=name,
        max_hit_points=hp,
        armor_class=13,
        ability_scores=AbilityScores(dexterity=14),
        proficiency_bonus=2,
        is_player_controlled=False,
        ai_profile="default_monster",
    )


def _setup_combat(player_actions=None, enemy_pos=(7, 5)):
    """Create combat with druid + enemy, druid's turn active."""
    enc = Encounter(
        name="Zone Move Test",
        grid_width=20,
        grid_height=15,
        combatants=[
            CombatantEntry(
                creature_id="druid_inline",
                creature_data=_make_player(player_actions),
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="goblin_inline",
                creature_data=_make_enemy(),
                team="enemy",
                starting_position=enemy_pos,
            ),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    cm.roll_initiative()
    cm.begin_combat()

    druid_id = None
    for cid, c in cm.combatants.items():
        if c.team == "player":
            druid_id = cid
            break

    while cm.active_combatant and cm.active_combatant.creature_id != druid_id:
        cm.end_turn()

    return cm, druid_id


def _cast_moonbeam(cm, druid_id, target_hex):
    """Cast Moonbeam at target_hex, creating a fixed-center zone."""
    cm.select_action(cm.combatants[druid_id].creature.actions[0])
    result = cm.execute_effect_at_hex(target_hex)
    return result


# ── Tests ────────────────────────────────────────────────────────────


class TestMoveZone:
    def test_move_zone_updates_center(self):
        """move_zone() should update the zone center to the target hex."""
        cm, druid_id = _setup_combat(player_actions=[_moonbeam_action()])
        _cast_moonbeam(cm, druid_id, HexCoord(5, 5))

        assert len(cm.active_zones) == 1
        assert cm.active_zones[0].center == HexCoord(5, 5)

        # Advance to druid's next turn (casting consumed the action)
        cm.end_turn()
        while cm.active_combatant and cm.active_combatant.creature_id != druid_id:
            cm.end_turn()

        # Move the zone
        result = cm.move_zone(HexCoord(8, 8), "action")

        assert result is not None
        assert result.success
        assert cm.active_zones[0].center == HexCoord(8, 8)
        assert cm.active_zones[0].follows_caster is False

    def test_move_zone_costs_action(self):
        """Moving a zone with zone_move_cost='action' should consume the action."""
        cm, druid_id = _setup_combat(player_actions=[_moonbeam_action()])
        _cast_moonbeam(cm, druid_id, HexCoord(5, 5))

        # Advance to next turn so action economy resets
        cm.end_turn()
        while cm.active_combatant and cm.active_combatant.creature_id != druid_id:
            cm.end_turn()

        assert cm.turn_resources.has_used_action is False
        cm.move_zone(HexCoord(8, 8), "action")
        assert cm.turn_resources.has_used_action is True

    def test_move_zone_costs_bonus_action(self):
        """Moving with zone_move_cost='bonus_action' consumes the bonus action."""
        cm, druid_id = _setup_combat(player_actions=[_flaming_sphere_action()])
        cm.select_action(cm.combatants[druid_id].creature.actions[0])
        cm.execute_effect_at_hex(HexCoord(5, 5))

        # Advance to next turn
        cm.end_turn()
        while cm.active_combatant and cm.active_combatant.creature_id != druid_id:
            cm.end_turn()

        assert cm.turn_resources.has_used_bonus_action is False
        cm.move_zone(HexCoord(8, 8), "bonus_action")
        assert cm.turn_resources.has_used_bonus_action is True

    def test_move_zone_blocked_when_action_used(self):
        """Cannot move zone if the required action economy slot is spent."""
        cm, druid_id = _setup_combat(player_actions=[_moonbeam_action()])
        _cast_moonbeam(cm, druid_id, HexCoord(5, 5))

        # Advance to next turn
        cm.end_turn()
        while cm.active_combatant and cm.active_combatant.creature_id != druid_id:
            cm.end_turn()

        # Spend the action
        cm.turn_resources.has_used_action = True

        result = cm.move_zone(HexCoord(8, 8), "action")
        assert result is None

    def test_move_zone_no_zone_returns_none(self):
        """Cannot move a zone if no zone exists."""
        cm, druid_id = _setup_combat(player_actions=[_moonbeam_action()])
        # Don't cast any zone spell
        result = cm.move_zone(HexCoord(5, 5), "action")
        assert result is None

    def test_move_zone_no_immediate_damage(self):
        """Moving a zone onto an enemy should NOT deal immediate damage.

        Per 5e rules, moving a zone (e.g. Moonbeam) onto a creature
        is not the creature "entering" the zone.  Damage happens when
        the creature starts its turn inside, or moves in on its own.
        """
        cm, druid_id = _setup_combat(
            player_actions=[_moonbeam_action()],
            enemy_pos=(8, 8),
        )
        _cast_moonbeam(cm, druid_id, HexCoord(3, 3))

        # Advance to next turn
        cm.end_turn()
        while cm.active_combatant and cm.active_combatant.creature_id != druid_id:
            cm.end_turn()

        # Record enemy HP before zone move
        enemy_id = [k for k, v in cm.combatants.items() if v.team == "enemy"][0]
        hp_before = cm.combatants[enemy_id].creature.current_hit_points

        # Move zone to overlap with enemy at (8,8)
        result = cm.move_zone(HexCoord(8, 8), "action")

        assert result is not None
        assert result.success
        # Enemy HP should be unchanged — no immediate damage
        assert cm.combatants[enemy_id].creature.current_hit_points == hp_before


class TestZoneMoveWithoutCost:
    def test_no_zone_move_cost_means_not_movable(self):
        """A spell without zone_move_cost should not allow zone movement."""
        # Spirit Guardians has no zone_move_cost
        spirit_action = Action(
            name="Spirit Guardians",
            description="Spirits swirl.",
            action_type=ActionType.ACTION,
            target_type=TargetType.AREA_SPHERE,
            range=15,
            area_size=15,
            requires_concentration=True,
            zone_follows_caster=True,
            saving_throw=SavingThrowEffect(
                ability="wisdom",
                dc=15,
                damage_on_fail=[DamageRoll(dice="3d8", damage_type=DamageType.RADIANT)],
                damage_on_success="half",
            ),
            resource_cost={"spell_slot_3": 1},
        )
        player = _make_player([spirit_action])
        player.class_resources["spell_slot_3"] = 2
        enc = Encounter(
            name="Test",
            grid_width=10,
            grid_height=10,
            combatants=[
                CombatantEntry(
                    creature_id="cleric",
                    creature_data=player,
                    team="player",
                    starting_position=(3, 3),
                ),
                CombatantEntry(
                    creature_id="goblin",
                    creature_data=_make_enemy(),
                    team="enemy",
                    starting_position=(4, 3),
                ),
            ],
        )
        cm = CombatManager()
        cm.load_encounter(enc, Path("."))
        cm.roll_initiative()
        cm.begin_combat()

        while cm.active_combatant and cm.active_combatant.team != "player":
            cm.end_turn()

        # Cast Spirit Guardians (follows caster, no zone_move_cost)
        cm.select_action(cm.active_combatant.creature.actions[0])
        cm.execute_effect("goblin")

        assert len(cm.active_zones) == 1
        assert cm.active_zones[0].follows_caster is True
        assert spirit_action.zone_move_cost is None
