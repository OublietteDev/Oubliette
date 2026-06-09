"""Tests for the teleportation system."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pygame
import pytest

from arena.combat.manager import CombatManager, Combatant
from arena.combat.events import CombatEventType
from arena.combat.zones import ActiveZone
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action, ActionType, DamageRoll, DamageType,
    SavingThrowEffect, TargetType,
)
from arena.models.character import PlayerCharacter
from arena.models.encounter import CombatantEntry, Encounter


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_caster(
    actions=None, bonus_actions=None, class_resources=None,
) -> PlayerCharacter:
    return PlayerCharacter(
        name="Caster",
        max_hit_points=30,
        armor_class=12,
        ability_scores=AbilityScores(intelligence=16, dexterity=14),
        proficiency_bonus=3,
        is_player_controlled=True,
        character_class="Wizard",
        level=5,
        class_resources=class_resources or {"spell_slot_2": 3, "spell_slot_3": 2},
        actions=actions or [],
        bonus_actions=bonus_actions or [],
    )


def _make_enemy(hp=20) -> PlayerCharacter:
    return PlayerCharacter(
        name="Goblin",
        max_hit_points=hp,
        armor_class=13,
        ability_scores=AbilityScores(dexterity=14),
        proficiency_bonus=2,
        is_player_controlled=False,
        character_class="Fighter",
        level=1,
    )


def _make_ally() -> PlayerCharacter:
    return PlayerCharacter(
        name="Ally",
        max_hit_points=30,
        armor_class=14,
        ability_scores=AbilityScores(strength=16),
        proficiency_bonus=2,
        is_player_controlled=True,
        character_class="Fighter",
        level=5,
    )


def _misty_step() -> Action:
    """Misty Step: bonus action, teleport 30 ft."""
    return Action(
        name="Misty Step",
        description="Teleport up to 30 feet.",
        action_type=ActionType.BONUS_ACTION,
        target_type=TargetType.SELF,
        range=30,
        teleport_range=30,
        teleport_self=True,
        resource_cost={"spell_slot_2": 1},
    )


def _thunder_step() -> Action:
    """Thunder Step: action, teleport 90 ft, origin damage."""
    return Action(
        name="Thunder Step",
        description="Teleport up to 90 feet. Enemies near origin take 3d10 thunder damage.",
        action_type=ActionType.ACTION,
        target_type=TargetType.SELF,
        range=90,
        area_size=10,
        teleport_range=90,
        teleport_self=True,
        teleport_origin_effect="3d10",
        teleport_origin_damage_type="thunder",
        saving_throw=SavingThrowEffect(
            ability="constitution",
            dc=15,
            damage_on_success="half",
        ),
        resource_cost={"spell_slot_3": 1},
    )


def _dimension_door() -> Action:
    """Dimension Door: action, teleport 500 ft with passenger."""
    return Action(
        name="Dimension Door",
        description="Teleport up to 500 feet. One willing creature can come.",
        action_type=ActionType.ACTION,
        target_type=TargetType.SELF,
        range=500,
        teleport_range=500,
        teleport_self=True,
        teleport_passenger=True,
        resource_cost={"spell_slot_3": 1},
    )


def _setup_combat(
    player_actions=None,
    player_bonus_actions=None,
    enemy_pos=(5, 5),
    player_pos=(3, 3),
    extra_combatants=None,
):
    """Create a CombatManager with one player and one enemy."""
    caster = _make_caster(
        actions=player_actions or [],
        bonus_actions=player_bonus_actions or [],
    )
    enemy = _make_enemy()

    combatants = [
        CombatantEntry(
            creature_id="caster",
            creature_data=caster,
            team="player",
            starting_position=player_pos,
        ),
        CombatantEntry(
            creature_id="goblin",
            creature_data=enemy,
            team="enemy",
            starting_position=enemy_pos,
        ),
    ]
    if extra_combatants:
        combatants.extend(extra_combatants)

    enc = Encounter(
        name="Test",
        grid_width=20,
        grid_height=20,
        combatants=combatants,
    )
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    cm.roll_initiative()
    cm.begin_combat()

    # Advance to caster's turn
    while cm.active_combatant and cm.active_combatant.creature_id != "caster":
        cm.end_turn()

    return cm


# ------------------------------------------------------------------
# Core mechanics
# ------------------------------------------------------------------

class TestTeleportBasic:
    def test_teleport_moves_caster(self):
        """Caster position is updated to the destination."""
        cm = _setup_combat(player_bonus_actions=[_misty_step()])
        cm.select_action(cm.combatants["caster"].creature.bonus_actions[0])

        dest = HexCoord(7, 7)
        result = cm.execute_teleport(dest)

        assert result is not None
        assert result.success
        assert cm.combatants["caster"].position == dest

    def test_teleport_grid_updated(self):
        """Origin hex is cleared, destination hex is occupied."""
        cm = _setup_combat(player_bonus_actions=[_misty_step()])
        origin = cm.combatants["caster"].position
        cm.select_action(cm.combatants["caster"].creature.bonus_actions[0])

        dest = HexCoord(7, 7)
        cm.execute_teleport(dest)

        # Origin clear
        cell_origin = cm.grid.get_cell(origin)
        assert cell_origin.occupant_id is None
        # Destination occupied
        cell_dest = cm.grid.get_cell(dest)
        assert cell_dest.occupant_id == "caster"

    def test_teleport_no_opportunity_attacks(self):
        """Teleporting past an enemy does NOT trigger OAs."""
        # Place enemy adjacent to caster
        cm = _setup_combat(
            player_bonus_actions=[_misty_step()],
            enemy_pos=(3, 4),  # Adjacent to caster at (3,3)
        )
        initial_hp = cm.combatants["caster"].creature.current_hit_points

        cm.select_action(cm.combatants["caster"].creature.bonus_actions[0])
        cm.execute_teleport(HexCoord(8, 8))

        # Caster HP unchanged — no OA triggered
        assert cm.combatants["caster"].creature.current_hit_points == initial_hp

    def test_teleport_within_range_succeeds(self):
        """Teleport within teleport_range succeeds."""
        cm = _setup_combat(player_bonus_actions=[_misty_step()])
        cm.select_action(cm.combatants["caster"].creature.bonus_actions[0])

        # 30ft range = 6 hexes max
        dest = HexCoord(8, 3)  # within range
        result = cm.execute_teleport(dest)
        assert result is not None
        assert result.success

    def test_teleport_beyond_range_fails(self):
        """Teleport beyond teleport_range is rejected."""
        cm = _setup_combat(player_bonus_actions=[_misty_step()])
        cm.select_action(cm.combatants["caster"].creature.bonus_actions[0])

        # 30ft = 6 hexes; (15, 15) is way beyond
        dest = HexCoord(15, 15)
        result = cm.execute_teleport(dest)
        assert result is not None
        assert not result.success

    def test_teleport_to_occupied_hex_fails(self):
        """Cannot teleport into an occupied hex."""
        cm = _setup_combat(player_bonus_actions=[_misty_step()])
        cm.select_action(cm.combatants["caster"].creature.bonus_actions[0])

        # Goblin is at (5,5)
        result = cm.execute_teleport(HexCoord(5, 5))
        assert result is not None
        assert not result.success

    def test_teleport_to_wall_fails(self):
        """Cannot teleport into impassable terrain."""
        cm = _setup_combat(player_bonus_actions=[_misty_step()])
        from arena.models.encounter import TerrainType
        cm.grid.set_terrain(HexCoord(4, 4), TerrainType.WALL)

        cm.select_action(cm.combatants["caster"].creature.bonus_actions[0])
        result = cm.execute_teleport(HexCoord(4, 4))
        assert result is None  # Invalid destination returns None

    def test_teleport_to_pit_fails(self):
        """Cannot teleport into a pit."""
        cm = _setup_combat(player_bonus_actions=[_misty_step()])
        from arena.models.encounter import TerrainType
        cm.grid.set_terrain(HexCoord(4, 4), TerrainType.PIT)

        cm.select_action(cm.combatants["caster"].creature.bonus_actions[0])
        result = cm.execute_teleport(HexCoord(4, 4))
        assert result is None

    def test_teleport_consumes_bonus_action(self):
        """Misty Step (bonus action) consumes the bonus action slot."""
        cm = _setup_combat(player_bonus_actions=[_misty_step()])
        assert not cm.turn_resources.has_used_bonus_action

        cm.select_action(cm.combatants["caster"].creature.bonus_actions[0])
        cm.execute_teleport(HexCoord(5, 3))

        assert cm.turn_resources.has_used_bonus_action

    def test_teleport_consumes_action(self):
        """Thunder Step (action) consumes the action slot."""
        cm = _setup_combat(player_actions=[_thunder_step()])
        assert not cm.turn_resources.has_used_action

        cm.select_action(cm.combatants["caster"].creature.actions[0])
        cm.execute_teleport(HexCoord(10, 10))

        assert cm.turn_resources.has_used_action

    def test_teleport_deducts_resources(self):
        """Spell slot is consumed on teleport."""
        cm = _setup_combat(player_bonus_actions=[_misty_step()])
        initial_slots = cm.combatants["caster"].creature.class_resources.get("spell_slot_2", 0)

        cm.select_action(cm.combatants["caster"].creature.bonus_actions[0])
        cm.execute_teleport(HexCoord(5, 3))

        final_slots = cm.combatants["caster"].creature.class_resources.get("spell_slot_2", 0)
        assert final_slots == initial_slots - 1

    def test_teleport_event_generated(self):
        """TELEPORT event is generated with from/to details."""
        cm = _setup_combat(player_bonus_actions=[_misty_step()])
        origin = cm.combatants["caster"].position
        dest = HexCoord(5, 3)

        cm.select_action(cm.combatants["caster"].creature.bonus_actions[0])
        result = cm.execute_teleport(dest)

        teleport_events = [
            e for e in result.events
            if e.event_type == CombatEventType.TELEPORT
        ]
        assert len(teleport_events) == 1
        evt = teleport_events[0]
        assert evt.details["from_hex"] == (origin.q, origin.r)
        assert evt.details["to_hex"] == (dest.q, dest.r)
        assert evt.details["teleport"] is True


# ------------------------------------------------------------------
# Origin damage (Thunder Step)
# ------------------------------------------------------------------

class TestTeleportOriginDamage:
    @patch("arena.util.dice.roll_expression", return_value=(20, [7, 6, 7]))
    @patch("arena.combat.actions.resolve_saving_throw")
    def test_origin_damage_on_enemies(self, mock_save, mock_roll):
        """Enemies near origin take damage."""
        cm = _setup_combat(
            player_actions=[_thunder_step()],
            enemy_pos=(3, 4),  # Adjacent to caster at (3,3) — within 10ft
        )
        mock_save.return_value = (
            False,
            _make_save_event("goblin", False),
        )

        cm.select_action(cm.combatants["caster"].creature.actions[0])
        result = cm.execute_teleport(HexCoord(10, 10))

        assert result.success
        # Goblin should have taken damage
        assert cm.combatants["goblin"].creature.current_hit_points < 20

    @patch("arena.util.dice.roll_expression", return_value=(20, [7, 6, 7]))
    @patch("arena.combat.actions.resolve_saving_throw")
    def test_origin_damage_save_half(self, mock_save, mock_roll):
        """Successful save = half damage."""
        cm = _setup_combat(
            player_actions=[_thunder_step()],
            enemy_pos=(3, 4),
        )
        mock_save.return_value = (
            True,
            _make_save_event("goblin", True),
        )

        cm.select_action(cm.combatants["caster"].creature.actions[0])
        cm.execute_teleport(HexCoord(10, 10))

        # Half of 20 = 10 damage
        assert cm.combatants["goblin"].creature.current_hit_points == 10

    @patch("arena.util.dice.roll_expression", return_value=(20, [7, 6, 7]))
    @patch("arena.combat.actions.resolve_saving_throw")
    def test_origin_damage_out_of_range(self, mock_save, mock_roll):
        """Enemies far from origin are not affected."""
        cm = _setup_combat(
            player_actions=[_thunder_step()],
            enemy_pos=(10, 10),  # Far from caster at (3,3)
        )

        cm.select_action(cm.combatants["caster"].creature.actions[0])
        cm.execute_teleport(HexCoord(15, 15))

        # No saving throw attempted
        mock_save.assert_not_called()
        # Goblin HP unchanged
        assert cm.combatants["goblin"].creature.current_hit_points == 20


# ------------------------------------------------------------------
# Passenger (Dimension Door)
# ------------------------------------------------------------------

class TestTeleportPassenger:
    def test_passenger_moves_with_caster(self):
        """Adjacent ally teleports to a hex near the destination."""
        ally = _make_ally()
        cm = _setup_combat(
            player_actions=[_dimension_door()],
            extra_combatants=[
                CombatantEntry(
                    creature_id="ally",
                    creature_data=ally,
                    team="player",
                    starting_position=(3, 4),  # Adjacent to caster at (3,3)
                ),
            ],
        )

        cm.select_action(cm.combatants["caster"].creature.actions[0])
        dest = HexCoord(10, 10)
        result = cm.execute_teleport(dest, passenger_id="ally")

        assert result.success
        # Caster at destination
        assert cm.combatants["caster"].position == dest
        # Ally should be near destination (adjacent)
        ally_pos = cm.combatants["ally"].position
        assert ally_pos is not None
        assert dest.distance_to(ally_pos) <= 1

    def test_no_passenger_goes_solo(self):
        """Without passenger_id, caster teleports alone."""
        cm = _setup_combat(player_actions=[_dimension_door()])

        cm.select_action(cm.combatants["caster"].creature.actions[0])
        dest = HexCoord(10, 10)
        result = cm.execute_teleport(dest)

        assert result.success
        assert cm.combatants["caster"].position == dest

    def test_find_passenger_candidates(self):
        """_find_passenger_candidates returns adjacent allies."""
        ally = _make_ally()
        cm = _setup_combat(
            player_actions=[_dimension_door()],
            extra_combatants=[
                CombatantEntry(
                    creature_id="ally",
                    creature_data=ally,
                    team="player",
                    starting_position=(3, 4),  # Adjacent
                ),
            ],
        )
        caster_pos = cm.combatants["caster"].position
        candidates = cm._find_passenger_candidates("caster", caster_pos)
        assert "ally" in candidates


# ------------------------------------------------------------------
# Zone interactions
# ------------------------------------------------------------------

class TestTeleportZoneInteraction:
    def test_teleport_into_zone_triggers_entry(self):
        """Teleporting into an active zone triggers zone entry damage."""
        cm = _setup_combat(player_bonus_actions=[_misty_step()])

        # Create a zone at (6, 6)
        zone = ActiveZone(
            zone_id="spirit_guardians_enemy",
            caster_id="goblin",
            name="Spirit Guardians",
            radius_feet=15,
            follows_caster=False,
            center=HexCoord(6, 6),
            saving_throw_ability="wisdom",
            saving_throw_dc=15,
            damage_dice="3d8",
            damage_type="radiant",
            damage_on_save="half",
            affects_enemies_only=True,
            team="enemy",
        )
        cm.active_zones.append(zone)

        initial_hp = cm.combatants["caster"].creature.current_hit_points
        cm.select_action(cm.combatants["caster"].creature.bonus_actions[0])
        cm.execute_teleport(HexCoord(6, 6))

        # Caster should have taken zone entry damage (or at least had a save)
        info_events = [
            e for e in cm.log.events
            if "affected by Spirit Guardians" in e.message
        ]
        assert len(info_events) > 0

    def test_teleport_with_concentration(self):
        """Far Step (concentration) starts concentrating."""
        far_step = Action(
            name="Far Step",
            description="Teleport 60 ft each turn.",
            action_type=ActionType.BONUS_ACTION,
            target_type=TargetType.SELF,
            range=60,
            teleport_range=60,
            teleport_self=True,
            requires_concentration=True,
            resource_cost={"spell_slot_2": 1},
        )
        cm = _setup_combat(player_bonus_actions=[far_step])

        cm.select_action(cm.combatants["caster"].creature.bonus_actions[0])
        result = cm.execute_teleport(HexCoord(7, 7))

        assert result.success
        from arena.models.conditions import Condition
        from arena.combat.conditions import has_condition
        assert has_condition(cm.combatants["caster"].creature, Condition.CONCENTRATING)


# ------------------------------------------------------------------
# Serialization
# ------------------------------------------------------------------

class TestTeleportSerialization:
    def test_teleport_fields_serialize(self):
        """Action with teleport fields round-trips through JSON."""
        action = _misty_step()
        data = action.model_dump()

        assert data["teleport_range"] == 30
        assert data["teleport_self"] is True
        assert data["teleport_passenger"] is False
        assert data["teleport_origin_effect"] is None
        assert data["teleport_origin_damage_type"] is None

        # Round-trip
        rebuilt = Action(**data)
        assert rebuilt.teleport_range == 30
        assert rebuilt.teleport_self is True

    def test_thunder_step_fields_serialize(self):
        """Thunder Step with origin damage round-trips."""
        action = _thunder_step()
        data = action.model_dump()

        assert data["teleport_origin_effect"] == "3d10"
        assert data["teleport_origin_damage_type"] == "thunder"

        rebuilt = Action(**data)
        assert rebuilt.teleport_origin_effect == "3d10"


# ------------------------------------------------------------------
# Visual Effect
# ------------------------------------------------------------------

class TestTeleportEffect:
    def test_not_expired_before_duration(self):
        from arena.gui.visual_effects import TeleportEffect
        fx = TeleportEffect(
            origin_wx=100.0, origin_wy=200.0,
            dest_wx=300.0, dest_wy=400.0,
            spawn_time=1000, duration_ms=600,
        )
        assert not fx.is_expired(1000)
        assert not fx.is_expired(1500)
        assert not fx.is_expired(1599)

    def test_expired_at_duration(self):
        from arena.gui.visual_effects import TeleportEffect
        fx = TeleportEffect(
            origin_wx=100.0, origin_wy=200.0,
            dest_wx=300.0, dest_wy=400.0,
            spawn_time=1000, duration_ms=600,
        )
        assert fx.is_expired(1600)
        assert fx.is_expired(2000)

    def test_type_alias_includes_teleport(self):
        from arena.gui.visual_effects import VisualEffect, TeleportEffect
        # Verify TeleportEffect is in the union type
        fx = TeleportEffect(
            origin_wx=0, origin_wy=0, dest_wx=1, dest_wy=1, spawn_time=0,
        )
        # This should be a valid VisualEffect (no type error)
        effects: list[VisualEffect] = [fx]
        assert len(effects) == 1


# ------------------------------------------------------------------
# Passenger Popup
# ------------------------------------------------------------------

class TestPassengerPopup:
    """Tests for the PassengerPopup class."""

    def test_popup_creation_dimensions(self):
        """Popup initializes with correct dimensions."""
        from arena.gui.passenger_popup import PassengerPopup
        popup = PassengerPopup(
            candidates=[("ally", "Ally Fighter"), ("cleric", "Healer")],
            caster_name="Wizard",
        )
        assert popup.rect.width == PassengerPopup.WIDTH
        expected_h = (
            PassengerPopup.TITLE_HEIGHT
            + 2 * PassengerPopup.ROW_HEIGHT
            + PassengerPopup.SOLO_HEIGHT
            + PassengerPopup.PADDING * 2
        )
        assert popup.rect.height == expected_h

    def test_reposition_clamps_to_screen(self):
        """Popup rect stays within screen bounds."""
        from arena.gui.passenger_popup import PassengerPopup
        popup = PassengerPopup(
            candidates=[("ally", "Ally")],
            caster_name="Wizard",
            screen_width=300,
            screen_height=200,
        )
        popup.reposition((0, 0))
        assert popup.rect.left >= 4
        assert popup.rect.top >= 4

    def test_click_candidate_returns_id(self):
        """Clicking a candidate row returns its creature_id."""
        from arena.gui.passenger_popup import PassengerPopup
        popup = PassengerPopup(
            candidates=[("ally_1", "Ally")],
            caster_name="Wizard",
        )
        popup.reposition((400, 300))
        row_rect = popup._get_candidate_rect(0)
        event = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            button=1, pos=row_rect.center,
        )
        result = popup.handle_event(event)
        assert result == "ally_1"

    def test_click_solo_returns_solo(self):
        """Clicking the Solo button returns '__solo__'."""
        from arena.gui.passenger_popup import PassengerPopup
        popup = PassengerPopup(
            candidates=[("ally", "Ally")],
            caster_name="Wizard",
        )
        popup.reposition((400, 300))
        solo_rect = popup._get_solo_rect()
        event = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            button=1, pos=solo_rect.center,
        )
        result = popup.handle_event(event)
        assert result == "__solo__"

    def test_click_outside_returns_solo(self):
        """Clicking outside the popup returns '__solo__'."""
        from arena.gui.passenger_popup import PassengerPopup
        popup = PassengerPopup(
            candidates=[("ally", "Ally")],
            caster_name="Wizard",
        )
        popup.reposition((400, 300))
        event = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            button=1, pos=(1, 1),
        )
        result = popup.handle_event(event)
        assert result == "__solo__"

    def test_escape_returns_solo(self):
        """Pressing Escape returns '__solo__'."""
        from arena.gui.passenger_popup import PassengerPopup
        popup = PassengerPopup(
            candidates=[("ally", "Ally")],
            caster_name="Wizard",
        )
        popup.reposition((400, 300))
        event = pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_ESCAPE,
        )
        result = popup.handle_event(event)
        assert result == "__solo__"

    def test_mousemotion_sets_hover(self):
        """Mouse motion updates hovered_index."""
        from arena.gui.passenger_popup import PassengerPopup
        popup = PassengerPopup(
            candidates=[("ally1", "Ally"), ("cleric1", "Cleric")],
            caster_name="Wizard",
        )
        popup.reposition((400, 300))
        row_rect = popup._get_candidate_rect(1)
        event = pygame.event.Event(
            pygame.MOUSEMOTION, pos=row_rect.center,
        )
        popup.handle_event(event)
        assert popup.hovered_index == 1


# ------------------------------------------------------------------
# Passenger Integration
# ------------------------------------------------------------------

class TestPassengerIntegration:
    """Tests for passenger selection in the teleport flow."""

    def test_execute_teleport_with_passenger_id(self):
        """execute_teleport(dest, passenger_id) moves both creatures."""
        ally = _make_ally()
        cm = _setup_combat(
            player_actions=[_dimension_door()],
            extra_combatants=[
                CombatantEntry(
                    creature_id="ally",
                    creature_data=ally,
                    team="player",
                    starting_position=(3, 4),
                ),
            ],
        )
        cm.select_action(cm.combatants["caster"].creature.actions[0])
        dest = HexCoord(10, 10)
        result = cm.execute_teleport(dest, passenger_id="ally")

        assert result.success
        assert cm.combatants["caster"].position == dest
        ally_pos = cm.combatants["ally"].position
        assert ally_pos != HexCoord(3, 4)  # Moved from original
        assert dest.distance_to(ally_pos) <= 1  # Adjacent to destination

    def test_find_candidates_excludes_enemies(self):
        """_find_passenger_candidates only returns same-team allies."""
        ally = _make_ally()
        cm = _setup_combat(
            player_actions=[_dimension_door()],
            enemy_pos=(3, 4),  # Enemy adjacent to caster at (3,3)
            extra_combatants=[
                CombatantEntry(
                    creature_id="ally",
                    creature_data=ally,
                    team="player",
                    starting_position=(3, 2),  # Also adjacent
                ),
            ],
        )
        caster_pos = cm.combatants["caster"].position
        candidates = cm._find_passenger_candidates("caster", caster_pos)
        assert "ally" in candidates
        assert "goblin" not in candidates

    def test_find_candidates_excludes_distant(self):
        """_find_passenger_candidates excludes non-adjacent allies."""
        ally = _make_ally()
        cm = _setup_combat(
            player_actions=[_dimension_door()],
            extra_combatants=[
                CombatantEntry(
                    creature_id="ally",
                    creature_data=ally,
                    team="player",
                    starting_position=(10, 10),  # Far away
                ),
            ],
        )
        caster_pos = cm.combatants["caster"].position
        candidates = cm._find_passenger_candidates("caster", caster_pos)
        assert "ally" not in candidates

    def test_solo_teleport_no_passenger_moved(self):
        """Solo teleport with passenger_id=None doesn't move ally."""
        ally = _make_ally()
        cm = _setup_combat(
            player_actions=[_dimension_door()],
            extra_combatants=[
                CombatantEntry(
                    creature_id="ally",
                    creature_data=ally,
                    team="player",
                    starting_position=(3, 4),
                ),
            ],
        )
        ally_original = cm.combatants["ally"].position
        cm.select_action(cm.combatants["caster"].creature.actions[0])
        result = cm.execute_teleport(HexCoord(10, 10), passenger_id=None)

        assert result.success
        assert cm.combatants["ally"].position == ally_original


# ------------------------------------------------------------------
# AI teleport scoring and planning
# ------------------------------------------------------------------

from arena.ai.behavior import AIProfile, DEFAULT_PROFILES
from arena.ai.context import CreatureView, CombatContext
from arena.ai.scoring import (
    score_teleport_action,
    generate_scored_actions,
    _score_best_teleport,
    check_use_condition,
)
from arena.ai.controller import AIController, TurnStepType


def _ai_view(
    cid="c1", team="enemy", pos=(5, 5), hp=1.0, conscious=True, ac=10,
    max_hp=20, speed=30,
):
    cur_hp = int(max_hp * hp)
    return CreatureView(
        creature_id=cid, team=team, position=HexCoord(*pos) if pos else None,
        hp_percent=hp, is_conscious=conscious, armor_class=ac,
        has_concentration=False, is_spellcaster=True,
        condition_names=(), max_hit_points=max_hp, current_hit_points=cur_hp,
        speed=speed, actions_count=1,
    )


def _ai_context(me, enemies=(), allies=(), action_used=False, bonus_used=False):
    all_c = (me,) + tuple(allies) + tuple(enemies)
    return CombatContext(
        me=me, allies=tuple(allies), enemies=tuple(enemies),
        all_combatants=all_c, grid_width=20, grid_height=15,
        round_number=1, remaining_movement=30,
        has_used_action=action_used, has_used_bonus_action=bonus_used,
    )


class TestTeleportScoring:
    """Tests for score_teleport_action improvements."""

    def test_melee_escape_bonus_for_ranged_profile(self):
        """Non-melee profiles stuck in melee get a big score boost for
        teleporting to a safe position."""
        profile = AIProfile(name="ranged", prefers_melee=False)
        me = _ai_view(cid="me", team="player", pos=(5, 5))
        enemy = _ai_view(cid="e1", team="enemy", pos=(5, 6))  # adjacent
        ctx = _ai_context(me, enemies=[enemy])

        # Destination far from enemy
        far_dest = (5, 0)  # 6 hexes away
        score_far = score_teleport_action(_misty_step(), profile, ctx, far_dest)

        # Destination still adjacent to enemy
        near_dest = (4, 5)  # still close
        score_near = score_teleport_action(_misty_step(), profile, ctx, near_dest)

        # Far destination should score much higher due to melee escape bonus
        assert score_far > score_near + 20

    def test_no_melee_escape_bonus_for_melee_profile(self):
        """Melee profiles do NOT get the escape bonus when in melee."""
        profile = AIProfile(name="melee", prefers_melee=True)
        me = _ai_view(cid="me", team="player", pos=(5, 5))
        enemy = _ai_view(cid="e1", team="enemy", pos=(5, 6))  # adjacent
        ctx = _ai_context(me, enemies=[enemy])

        far_dest = (5, 0)
        score = score_teleport_action(_misty_step(), profile, ctx, far_dest)
        # Should NOT include the 40-point melee escape bonus
        assert score < 50  # base (7*5=35) + minor repositioning

    def test_melee_escape_bonus_only_when_actually_in_melee(self):
        """No escape bonus when the creature is already far from enemies."""
        profile = AIProfile(name="ranged", prefers_melee=False)
        me = _ai_view(cid="me", team="player", pos=(0, 0))
        enemy = _ai_view(cid="e1", team="enemy", pos=(10, 10))  # very far
        ctx = _ai_context(me, enemies=[enemy])

        # Compare: score when NOT in melee (already safe) vs when in melee
        dest = (0, 5)
        score_safe = score_teleport_action(_misty_step(), profile, ctx, dest)

        # Now create context where creature IS in melee
        me_melee = _ai_view(cid="me", team="player", pos=(10, 9))
        ctx_melee = _ai_context(me_melee, enemies=[enemy])
        score_melee = score_teleport_action(_misty_step(), profile, ctx_melee, dest)

        # In-melee score should be significantly higher due to escape bonus
        assert score_melee > score_safe + 30

    def test_spellcaster_profile_is_ranged(self):
        """The spellcaster profile should have prefers_melee=False."""
        profile = DEFAULT_PROFILES["spellcaster"]
        assert profile.prefers_melee is False


class TestBonusTeleportScoring:
    """Tests for bonus action teleport in generate_scored_actions."""

    def test_bonus_teleport_scored_when_available(self):
        """Misty Step (bonus action) should appear in scored actions."""
        profile = AIProfile(name="ranged", prefers_melee=False)
        me = _ai_view(cid="me", team="player", pos=(5, 5))
        enemy = _ai_view(cid="e1", team="enemy", pos=(5, 6))  # adjacent
        ctx = _ai_context(me, enemies=[enemy])

        misty = _misty_step()
        scored = generate_scored_actions(
            profile, ctx,
            actions=[], bonus_actions=[misty],
            can_use_action=True, can_use_bonus_action=True,
            can_twf=False, reachable_enemies={"e1": 1},
        )

        bonus_tps = [s for s in scored if s.action_category == "bonus_teleport"]
        assert len(bonus_tps) == 1
        assert bonus_tps[0].action_name == "Misty Step"
        assert bonus_tps[0].target_hex is not None

    def test_bonus_teleport_not_scored_when_bonus_used(self):
        """Misty Step should NOT be scored when bonus action is consumed."""
        profile = AIProfile(name="ranged", prefers_melee=False)
        me = _ai_view(cid="me", team="player", pos=(5, 5))
        enemy = _ai_view(cid="e1", team="enemy", pos=(5, 6))
        ctx = _ai_context(me, enemies=[enemy], bonus_used=True)

        scored = generate_scored_actions(
            profile, ctx,
            actions=[], bonus_actions=[_misty_step()],
            can_use_action=True, can_use_bonus_action=False,
            can_twf=False, reachable_enemies={"e1": 1},
        )

        bonus_tps = [s for s in scored if s.action_category == "bonus_teleport"]
        assert len(bonus_tps) == 0

    def test_regular_teleport_uses_teleport_category(self):
        """Thunder Step (action) should use 'teleport' category, not bonus."""
        profile = AIProfile(name="ranged", prefers_melee=False)
        me = _ai_view(cid="me", team="player", pos=(5, 5))
        enemy = _ai_view(cid="e1", team="enemy", pos=(5, 6))
        ctx = _ai_context(me, enemies=[enemy])

        scored = generate_scored_actions(
            profile, ctx,
            actions=[_thunder_step()], bonus_actions=[],
            can_use_action=True, can_use_bonus_action=True,
            can_twf=False, reachable_enemies={"e1": 1},
        )

        tp_actions = [s for s in scored if s.action_category == "teleport"]
        assert len(tp_actions) == 1
        assert tp_actions[0].action_name == "Thunder Step"

    def test_score_best_teleport_escape_candidates(self):
        """_score_best_teleport generates escape-direction candidates for
        non-melee profiles that score well."""
        profile = AIProfile(name="ranged", prefers_melee=False)
        me = _ai_view(cid="me", team="player", pos=(5, 5))
        enemy = _ai_view(cid="e1", team="enemy", pos=(5, 6))  # south of me
        ctx = _ai_context(me, enemies=[enemy])

        result = _score_best_teleport(_misty_step(), profile, ctx, "bonus_teleport")
        assert result is not None
        # Best destination should be AWAY from the enemy (north-ish)
        dest = HexCoord(*result.target_hex)
        me_pos = HexCoord(5, 5)
        enemy_pos = HexCoord(5, 6)
        assert dest.distance_to(enemy_pos) > me_pos.distance_to(enemy_pos)


class TestAITeleportPlanning:
    """Integration tests for AI teleport planning via AIController."""

    def _make_spellcaster_encounter(self, enemy_adjacent=True):
        """Create encounter with a spellcaster that has Misty Step."""
        from arena.models.actions import Attack, DamageRoll
        from arena.models.character import Creature

        fire_bolt = Action(
            name="Fire Bolt",
            description="Ranged spell attack.",
            action_type=ActionType.ACTION,
            attack=Attack(
                name="Fire Bolt",
                attack_type="ranged_spell",
                ability="intelligence",
                range_normal=120,
                damage=[DamageRoll(dice="2d10", damage_type=DamageType.FIRE,
                                   ability_modifier="none")],
            ),
            ai_priority=7,
        )
        misty = _misty_step()
        misty.ai_priority = 7
        # Remove condition gate so AI always considers it
        misty.ai_use_condition = None

        mage = Creature(
            name="Mage",
            max_hit_points=40,
            armor_class=12,
            ability_scores=AbilityScores(intelligence=16, dexterity=14),
            proficiency_bonus=3,
            is_player_controlled=False,
            ai_profile="spellcaster",
            actions=[fire_bolt],
            bonus_actions=[misty],
        )

        enemy_pos = (3, 4) if enemy_adjacent else (10, 10)
        enc = Encounter(
            name="Test AI Teleport",
            grid_width=20,
            grid_height=15,
            combatants=[
                CombatantEntry(
                    creature_id="mage",
                    creature_data=mage,
                    team="enemy",
                    starting_position=(3, 3),
                ),
                CombatantEntry(
                    creature_id="hero",
                    creature_data=_make_caster(
                        actions=[Action(
                            name="Sword", description="Melee",
                            action_type=ActionType.ACTION,
                            attack=Attack(
                                name="Sword", attack_type="melee_weapon",
                                ability="strength", reach=5,
                                damage=[DamageRoll(dice="1d8",
                                                   damage_type=DamageType.SLASHING,
                                                   ability_modifier="strength")],
                            ),
                        )],
                    ),
                    team="player",
                    starting_position=enemy_pos,
                ),
            ],
        )
        cm = CombatManager()
        cm.load_encounter(enc, Path("."))

        with patch("arena.combat.manager.roll_die", return_value=10):
            cm.roll_initiative()

        # Force mage to go first
        for entry in cm.initiative.entries:
            if cm.combatants[entry.creature_id].team == "enemy":
                entry.initiative_roll = 20
            else:
                entry.initiative_roll = 5
        cm.initiative.entries.sort(
            key=lambda x: (-x.initiative_roll, -x.dexterity)
        )
        cm.begin_combat()
        return cm

    @patch("arena.combat.actions.roll_die", return_value=15)
    @patch("arena.combat.damage.roll_expression", return_value=(10, [5, 5]))
    def test_ai_plans_bonus_teleport_in_melee(self, mock_dmg, mock_d20):
        """AI mage in melee should plan Misty Step as bonus action."""
        cm = self._make_spellcaster_encounter(enemy_adjacent=True)
        assert cm.active_combatant.creature_id == "mage"

        controller = AIController(randomness=0.0)
        plan = controller.plan_turn(cm)

        step_types = [s.step_type for s in plan.steps]
        # Should have both a SELECT_ACTION and EXECUTE_TELEPORT for Misty Step
        teleport_steps = [s for s in plan.steps
                         if s.step_type == TurnStepType.EXECUTE_TELEPORT]
        assert len(teleport_steps) >= 1, (
            f"Expected teleport step, got: {step_types}"
        )

    @patch("arena.combat.actions.roll_die", return_value=15)
    @patch("arena.combat.damage.roll_expression", return_value=(10, [5, 5]))
    def test_ai_skips_bonus_teleport_when_safe(self, mock_dmg, mock_d20):
        """AI mage far from enemies should NOT use Misty Step."""
        cm = self._make_spellcaster_encounter(enemy_adjacent=False)
        assert cm.active_combatant.creature_id == "mage"

        controller = AIController(randomness=0.0)
        plan = controller.plan_turn(cm)

        step_types = [s.step_type for s in plan.steps]
        teleport_steps = [s for s in plan.steps
                         if s.step_type == TurnStepType.EXECUTE_TELEPORT]
        # Should NOT teleport when already safe
        assert len(teleport_steps) == 0, (
            f"Unexpected teleport step when safe: {step_types}"
        )

    def test_ai_retreat_prefers_teleport(self):
        """AI in retreat mode should prefer teleporting over Disengage."""
        cm = self._make_spellcaster_encounter(enemy_adjacent=True)
        mage = cm.combatants["mage"]
        # Damage the mage to trigger retreat (below 25% HP)
        mage.creature.current_hit_points = 5  # 12.5% of 40

        controller = AIController(randomness=0.0)
        plan = controller.plan_turn(cm)

        step_types = [s.step_type for s in plan.steps]
        # Should have teleport, NOT disengage
        has_teleport = TurnStepType.EXECUTE_TELEPORT in step_types
        has_disengage = any(
            s.step_type == TurnStepType.STANDARD_ACTION
            and s.action_name == "disengage"
            for s in plan.steps
        )
        assert has_teleport, f"Expected teleport in retreat plan: {step_types}"
        assert not has_disengage, (
            f"Should use teleport instead of disengage: {step_types}"
        )


class TestCheckUseCondition:
    """Tests for check_use_condition() regex/eval fix."""

    def test_is_in_melee_true(self):
        """'is_in_melee' should return True when adjacent to enemy."""
        me = _ai_view(cid="me", team="player", pos=(5, 5))
        enemy = _ai_view(cid="e1", team="enemy", pos=(5, 6))  # adjacent
        ctx = _ai_context(me, enemies=[enemy])
        assert check_use_condition("is_in_melee", ctx) is True

    def test_is_in_melee_false(self):
        """'is_in_melee' should return False when far from enemies."""
        me = _ai_view(cid="me", team="player", pos=(0, 0))
        enemy = _ai_view(cid="e1", team="enemy", pos=(10, 10))  # far away
        ctx = _ai_context(me, enemies=[enemy])
        assert check_use_condition("is_in_melee", ctx) is False

    def test_hp_percent_condition(self):
        """'self.hp_percent < 50' should gate on HP."""
        me_full = _ai_view(cid="me", team="player", pos=(5, 5), hp=1.0)
        me_hurt = _ai_view(cid="me", team="player", pos=(5, 5), hp=0.3)
        enemy = _ai_view(cid="e1", team="enemy", pos=(10, 10))
        ctx_full = _ai_context(me_full, enemies=[enemy])
        ctx_hurt = _ai_context(me_hurt, enemies=[enemy])

        assert check_use_condition("self.hp_percent < 50", ctx_full) is False
        assert check_use_condition("self.hp_percent < 50", ctx_hurt) is True

    def test_combined_condition(self):
        """'is_in_melee and self.hp_percent < 75' should require both."""
        me = _ai_view(cid="me", team="player", pos=(5, 5), hp=0.5)
        enemy_near = _ai_view(cid="e1", team="enemy", pos=(5, 6))
        enemy_far = _ai_view(cid="e1", team="enemy", pos=(10, 10))

        ctx_melee = _ai_context(me, enemies=[enemy_near])
        ctx_ranged = _ai_context(me, enemies=[enemy_far])

        assert check_use_condition("is_in_melee and self.hp_percent < 75", ctx_melee) is True
        assert check_use_condition("is_in_melee and self.hp_percent < 75", ctx_ranged) is False

    def test_null_condition_always_true(self):
        """Null/empty conditions should return True."""
        me = _ai_view(cid="me", team="player", pos=(5, 5))
        ctx = _ai_context(me, enemies=[])
        assert check_use_condition(None, ctx) is True
        assert check_use_condition("", ctx) is True

    def test_not_is_in_melee(self):
        """'not is_in_melee' should invert the check."""
        me = _ai_view(cid="me", team="player", pos=(5, 5))
        enemy_near = _ai_view(cid="e1", team="enemy", pos=(5, 6))
        enemy_far = _ai_view(cid="e1", team="enemy", pos=(10, 10))

        ctx_melee = _ai_context(me, enemies=[enemy_near])
        ctx_ranged = _ai_context(me, enemies=[enemy_far])

        assert check_use_condition("not is_in_melee", ctx_melee) is False
        assert check_use_condition("not is_in_melee", ctx_ranged) is True


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

from arena.combat.events import CombatEvent


def _make_save_event(creature_id: str, success: bool) -> CombatEvent:
    return CombatEvent(
        event_type=CombatEventType.SAVING_THROW,
        message=f"{creature_id} {'succeeds' if success else 'fails'} save.",
        target_id=creature_id,
        details={"success": success},
    )
