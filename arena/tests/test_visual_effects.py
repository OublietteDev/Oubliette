"""Tests for the programmatic visual effects system."""

import math

import pytest

from arena.gui.visual_effects import (
    AoEBlastEffect,
    ZoneCreationPulse,
    ZoneDamageFlash,
    ZoneShimmerState,
    SpawnEffect,
    get_damage_color,
    get_zone_shimmer_alpha,
    get_zone_flash_boost,
    render_visual_effects,
    DAMAGE_TYPE_COLORS,
)


# ------------------------------------------------------------------
# get_damage_color
# ------------------------------------------------------------------

class TestGetDamageColor:
    def test_known_damage_types(self):
        assert get_damage_color("fire") == (255, 100, 30)
        assert get_damage_color("cold") == (80, 160, 255)
        assert get_damage_color("necrotic") == (100, 40, 120)
        assert get_damage_color("radiant") == (255, 230, 140)

    def test_all_types_in_map(self):
        for dtype, color in DAMAGE_TYPE_COLORS.items():
            assert get_damage_color(dtype) == color

    def test_unknown_type_returns_fallback(self):
        assert get_damage_color("unknown") == (200, 200, 200)
        assert get_damage_color("") == (200, 200, 200)


# ------------------------------------------------------------------
# AoEBlastEffect
# ------------------------------------------------------------------

class TestAoEBlastEffect:
    def _make(self, spawn_time=0, duration_ms=700):
        return AoEBlastEffect(
            center_wx=100.0,
            center_wy=200.0,
            radius_feet=20.0,
            color=(255, 100, 30),
            spawn_time=spawn_time,
            duration_ms=duration_ms,
        )

    def test_not_expired_before_duration(self):
        fx = self._make(spawn_time=1000, duration_ms=700)
        assert not fx.is_expired(1000)
        assert not fx.is_expired(1500)
        assert not fx.is_expired(1699)

    def test_expired_at_duration(self):
        fx = self._make(spawn_time=1000, duration_ms=700)
        assert fx.is_expired(1700)

    def test_expired_after_duration(self):
        fx = self._make(spawn_time=1000, duration_ms=700)
        assert fx.is_expired(2000)

    def test_default_duration(self):
        fx = self._make()
        assert fx.duration_ms == 700


# ------------------------------------------------------------------
# ZoneCreationPulse
# ------------------------------------------------------------------

class TestZoneCreationPulse:
    def test_not_expired_before_duration(self):
        fx = ZoneCreationPulse(
            center_wx=50.0, center_wy=50.0,
            radius_feet=15.0, color=(255, 230, 140),
            spawn_time=500, duration_ms=800,
        )
        assert not fx.is_expired(500)
        assert not fx.is_expired(1299)

    def test_expired_at_duration(self):
        fx = ZoneCreationPulse(
            center_wx=50.0, center_wy=50.0,
            radius_feet=15.0, color=(255, 230, 140),
            spawn_time=500, duration_ms=800,
        )
        assert fx.is_expired(1300)

    def test_default_duration(self):
        fx = ZoneCreationPulse(
            center_wx=0, center_wy=0, radius_feet=10,
            color=(0, 0, 0), spawn_time=0,
        )
        assert fx.duration_ms == 800


# ------------------------------------------------------------------
# SpawnEffect
# ------------------------------------------------------------------

class TestSpawnEffect:
    def test_not_expired_before_duration(self):
        fx = SpawnEffect(
            center_wx=0, center_wy=0, color=(100, 255, 180),
            spawn_time=100, duration_ms=800,
        )
        assert not fx.is_expired(100)
        assert not fx.is_expired(899)

    def test_expired_at_duration(self):
        fx = SpawnEffect(
            center_wx=0, center_wy=0, color=(100, 255, 180),
            spawn_time=100, duration_ms=800,
        )
        assert fx.is_expired(900)

    def test_default_duration_and_wild_shape(self):
        fx = SpawnEffect(
            center_wx=0, center_wy=0, color=(100, 255, 180),
            spawn_time=0,
        )
        assert fx.duration_ms == 800
        assert fx.is_wild_shape is False


# ------------------------------------------------------------------
# ZoneDamageFlash
# ------------------------------------------------------------------

class TestZoneDamageFlash:
    def test_not_expired_before_duration(self):
        flash = ZoneDamageFlash(zone_id="z1", spawn_time=200, duration_ms=400)
        assert not flash.is_expired(200)
        assert not flash.is_expired(599)

    def test_expired_at_duration(self):
        flash = ZoneDamageFlash(zone_id="z1", spawn_time=200, duration_ms=400)
        assert flash.is_expired(600)

    def test_default_duration(self):
        flash = ZoneDamageFlash(zone_id="z1", spawn_time=0)
        assert flash.duration_ms == 400


# ------------------------------------------------------------------
# get_zone_shimmer_alpha
# ------------------------------------------------------------------

class TestGetZoneShimmerAlpha:
    def test_fallback_for_unknown_zone(self):
        result = get_zone_shimmer_alpha("unknown_zone", 1000, {})
        assert result == 80

    def test_returns_value_in_range(self):
        states = {"z1": ZoneShimmerState(zone_id="z1", phase_offset=0.0)}
        for t in range(0, 5000, 100):
            alpha = get_zone_shimmer_alpha("z1", t, states)
            assert 50 <= alpha <= 100, f"alpha={alpha} at t={t}"

    def test_different_offsets_produce_different_values(self):
        s1 = {"z1": ZoneShimmerState(zone_id="z1", phase_offset=0.0)}
        s2 = {"z1": ZoneShimmerState(zone_id="z1", phase_offset=0.5)}
        # At most points in the cycle, different offsets produce different values
        # Test at a specific time where sine values diverge
        a1 = get_zone_shimmer_alpha("z1", 500, s1)
        a2 = get_zone_shimmer_alpha("z1", 500, s2)
        assert a1 != a2

    def test_periodic_returns_to_same_value(self):
        states = {"z1": ZoneShimmerState(zone_id="z1", phase_offset=0.0)}
        a1 = get_zone_shimmer_alpha("z1", 0, states)
        a2 = get_zone_shimmer_alpha("z1", 2000, states)  # One full cycle
        assert a1 == a2


# ------------------------------------------------------------------
# get_zone_flash_boost
# ------------------------------------------------------------------

class TestGetZoneFlashBoost:
    def test_no_flash_returns_zero(self):
        assert get_zone_flash_boost("z1", 1000, []) == 0

    def test_wrong_zone_returns_zero(self):
        flashes = [ZoneDamageFlash(zone_id="z2", spawn_time=900)]
        assert get_zone_flash_boost("z1", 1000, flashes) == 0

    def test_active_flash_returns_positive(self):
        flashes = [ZoneDamageFlash(zone_id="z1", spawn_time=900, duration_ms=400)]
        boost = get_zone_flash_boost("z1", 1000, flashes)
        assert boost > 0
        assert boost <= 100

    def test_flash_at_spawn_returns_max(self):
        flashes = [ZoneDamageFlash(zone_id="z1", spawn_time=1000, duration_ms=400)]
        boost = get_zone_flash_boost("z1", 1000, flashes)
        assert boost == 100

    def test_flash_fades_over_time(self):
        flashes = [ZoneDamageFlash(zone_id="z1", spawn_time=1000, duration_ms=400)]
        early = get_zone_flash_boost("z1", 1050, flashes)
        late = get_zone_flash_boost("z1", 1300, flashes)
        assert early > late

    def test_expired_flash_returns_zero(self):
        flashes = [ZoneDamageFlash(zone_id="z1", spawn_time=500, duration_ms=400)]
        assert get_zone_flash_boost("z1", 1000, flashes) == 0


# ------------------------------------------------------------------
# render_visual_effects (pruning logic only — no Pygame surface)
# ------------------------------------------------------------------

class TestRenderVisualEffectsPruning:
    """Test that expired effects are pruned from the list.

    We can't easily test actual rendering without Pygame initialized,
    but we can verify the pruning logic by using is_expired directly.
    """

    def test_expired_effects_removed(self):
        fx1 = AoEBlastEffect(
            center_wx=0, center_wy=0, radius_feet=20,
            color=(255, 0, 0), spawn_time=0, duration_ms=100,
        )
        fx2 = AoEBlastEffect(
            center_wx=0, center_wy=0, radius_feet=20,
            color=(0, 0, 255), spawn_time=500, duration_ms=100,
        )
        # At t=200, fx1 is expired, fx2 is not
        effects = [fx1, fx2]
        alive = [fx for fx in effects if not fx.is_expired(200)]
        assert len(alive) == 1
        assert alive[0] is fx2

    def test_all_expired(self):
        effects = [
            AoEBlastEffect(
                center_wx=0, center_wy=0, radius_feet=10,
                color=(0, 0, 0), spawn_time=0, duration_ms=50,
            ),
        ]
        alive = [fx for fx in effects if not fx.is_expired(100)]
        assert len(alive) == 0

    def test_none_expired(self):
        effects = [
            SpawnEffect(
                center_wx=0, center_wy=0, color=(0, 255, 0),
                spawn_time=1000, duration_ms=800,
            ),
        ]
        alive = [fx for fx in effects if not fx.is_expired(1100)]
        assert len(alive) == 1


# ------------------------------------------------------------------
# Integration: event details in combat manager
# ------------------------------------------------------------------

from pathlib import Path

from arena.combat.manager import CombatManager, Combatant
from arena.combat.events import CombatEventType
from arena.combat.zones import ActiveZone, process_zone_start_of_turn
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action, ActionType, DamageRoll, DamageType,
    SavingThrowEffect, TargetType,
)
from arena.models.character import Creature, PlayerCharacter
from arena.models.encounter import CombatantEntry, Encounter


def _make_wizard(actions=None) -> PlayerCharacter:
    return PlayerCharacter(
        name="Wizard",
        max_hit_points=30,
        armor_class=12,
        ability_scores=AbilityScores(intelligence=16, dexterity=14),
        proficiency_bonus=3,
        is_player_controlled=True,
        character_class="Wizard",
        level=5,
        class_resources={"spell_slot_3": 2},
        actions=actions or [],
    )


def _make_cleric(actions=None) -> PlayerCharacter:
    return PlayerCharacter(
        name="Cleric",
        max_hit_points=40,
        armor_class=16,
        ability_scores=AbilityScores(wisdom=18),
        proficiency_bonus=3,
        is_player_controlled=True,
        character_class="Cleric",
        level=5,
        class_resources={"spell_slot_3": 2},
        actions=actions or [],
    )


def _make_goblin() -> Creature:
    return Creature(
        name="Goblin",
        max_hit_points=15,
        armor_class=13,
        ability_scores=AbilityScores(dexterity=14),
        proficiency_bonus=2,
        is_player_controlled=False,
        ai_profile="default_monster",
    )


def _fireball_action() -> Action:
    return Action(
        name="Fireball",
        description="A bright streak of fire.",
        action_type=ActionType.ACTION,
        target_type=TargetType.AREA_SPHERE,
        range=150,
        area_size=20,
        saving_throw=SavingThrowEffect(
            ability="dexterity",
            dc=15,
            damage_on_fail=[DamageRoll(dice="8d6", damage_type=DamageType.FIRE)],
            damage_on_success="half",
        ),
        resource_cost={"spell_slot_3": 1},
    )


def _spirit_guardians_action() -> Action:
    return Action(
        name="Spirit Guardians",
        description="Spirits swirl around you.",
        action_type=ActionType.ACTION,
        target_type=TargetType.AREA_SPHERE,
        range=15,
        area_size=15,
        requires_concentration=True,
        saving_throw=SavingThrowEffect(
            ability="wisdom",
            dc=15,
            damage_on_fail=[DamageRoll(dice="3d8", damage_type=DamageType.RADIANT)],
            damage_on_success="half",
        ),
        resource_cost={"spell_slot_3": 1},
    )


def _setup_combat(player_creature, player_actions, enemy_pos=(7, 5)):
    """Create a CombatManager with player + enemy, player's turn active."""
    player_creature_with_actions = player_creature
    if player_actions:
        player_creature_with_actions.actions = player_actions

    enc = Encounter(
        name="VFX Test",
        grid_width=20,
        grid_height=15,
        combatants=[
            CombatantEntry(
                creature_id="player_inline",
                creature_data=player_creature_with_actions,
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="goblin_inline",
                creature_data=_make_goblin(),
                team="enemy",
                starting_position=enemy_pos,
            ),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    cm.roll_initiative()
    cm.begin_combat()

    player_id = None
    for cid, c in cm.combatants.items():
        if c.team == "player":
            player_id = cid
            break

    while cm.active_combatant and cm.active_combatant.creature_id != player_id:
        cm.end_turn()

    return cm, player_id


class TestAoEEventDetails:
    """Verify that execute_effect_at_hex injects aoe_center_hex."""

    def test_aoe_center_in_event(self):
        fireball = _fireball_action()
        cm, wiz_id = _setup_combat(_make_wizard([fireball]), [fireball])
        cm.select_action(cm.combatants[wiz_id].creature.actions[0])

        target_hex = HexCoord(7, 5)
        result = cm.execute_effect_at_hex(target_hex)
        assert result is not None
        assert result.success

        aoe_event = None
        for evt in result.events:
            if evt.event_type == CombatEventType.INFO and evt.details.get("is_effect_use"):
                aoe_event = evt
                break

        assert aoe_event is not None
        assert aoe_event.details.get("aoe_center_hex") == (7, 5)
        assert aoe_event.details.get("area_size") == 20
        assert aoe_event.details.get("aoe_damage_type") == "fire"


class TestZoneCreationEventDetails:
    """Verify that _execute_zone_spell injects zone_created details."""

    def test_zone_created_in_event(self):
        sg = _spirit_guardians_action()
        cm, cleric_id = _setup_combat(_make_cleric([sg]), [sg])
        cm.select_action(cm.combatants[cleric_id].creature.actions[0])

        result = cm.execute_effect(cleric_id)
        assert result is not None
        assert result.success

        zone_event = None
        for evt in result.events:
            if evt.event_type == CombatEventType.INFO and evt.details.get("zone_created"):
                zone_event = evt
                break

        assert zone_event is not None
        assert zone_event.details["zone_created"] is True
        assert zone_event.details["zone_center_hex"] == (2, 2)  # cleric's position
        assert zone_event.details["zone_radius_feet"] == 15
        assert zone_event.details["zone_damage_type"] == "radiant"


class TestZoneDamageEventDetails:
    """Verify that _resolve_zone_damage injects zone_damage detail."""

    def test_zone_damage_in_event(self):
        grid = HexGrid(10, 10)

        cleric = Creature(
            name="Cleric", max_hit_points=40,
            ability_scores=AbilityScores(wisdom=18),
            proficiency_bonus=3,
        )
        enemy = Creature(
            name="Goblin", max_hit_points=10,
            ability_scores=AbilityScores(wisdom=8),
            proficiency_bonus=2,
        )

        combatants = {
            "cleric_1": Combatant(
                creature_id="cleric_1", creature=cleric,
                team="player", position=HexCoord(3, 3),
            ),
            "goblin_1": Combatant(
                creature_id="goblin_1", creature=enemy,
                team="enemy", position=HexCoord(3, 4),
            ),
        }

        zone = ActiveZone(
            zone_id="spirit_guardians_cleric_1",
            caster_id="cleric_1",
            name="Spirit Guardians",
            radius_feet=15,
            follows_caster=True,
            center=None,
            saving_throw_ability="wisdom",
            saving_throw_dc=15,
            damage_dice="3d8",
            damage_type="radiant",
            damage_on_save="half",
            affects_enemies_only=True,
            team="player",
            concentration_linked=True,
            already_damaged=set(),
        )

        events = process_zone_start_of_turn(
            [zone], "goblin_1", combatants, grid,
        )
        assert len(events) > 0

        info_event = events[0]
        assert info_event.event_type == CombatEventType.INFO
        assert info_event.details.get("zone_damage") == "spirit_guardians_cleric_1"


class TestSummonEventDetails:
    """Verify that execute_summon injects summon_hex and is_wild_shape."""

    def test_summon_hex_in_event(self):
        from unittest.mock import patch

        summon_action = Action(
            name="Conjure Wolf",
            description="Summon a wolf.",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_CREATURE,
            range=30,
            summon_creature="monsters/wolf.json",
            is_wild_shape=False,
        )
        cm, druid_id = _setup_combat(
            PlayerCharacter(
                name="Druid", max_hit_points=40, armor_class=14,
                ability_scores=AbilityScores(wisdom=16),
                proficiency_bonus=3, is_player_controlled=True,
                character_class="Druid", level=5,
                actions=[summon_action],
            ),
            [summon_action],
        )

        wolf = Creature(
            name="Wolf", max_hit_points=11, armor_class=13,
            ability_scores=AbilityScores(strength=12, dexterity=15, constitution=12),
            proficiency_bonus=2,
        )

        with patch.object(
            CombatManager, "_load_creature",
            side_effect=lambda entry, data_dir: (
                entry.creature_data.model_copy(deep=True) if entry.creature_data
                else wolf.model_copy(deep=True)
            ),
        ):
            cm.select_action(cm.combatants[druid_id].creature.actions[0])
            result = cm.execute_summon(HexCoord(4, 4))

        assert result is not None
        assert result.success

        summon_event = None
        for evt in result.events:
            if (
                evt.event_type == CombatEventType.INFO
                and evt.details.get("summon_hex") is not None
            ):
                summon_event = evt
                break

        assert summon_event is not None
        assert summon_event.details["summon_hex"] == (4, 4)
        assert summon_event.details["is_wild_shape"] is False
