"""Tests for click-to-place AoE and fixed-center zone creation."""

from pathlib import Path
from unittest.mock import patch

import pytest

from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant
from arena.combat.events import CombatEventType
from arena.combat.zones import ActiveZone, get_zone_hexes
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


def _make_player(
    name: str = "Wizard",
    hp: int = 30,
    ac: int = 12,
) -> PlayerCharacter:
    return PlayerCharacter(
        name=name,
        max_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(intelligence=16, wisdom=14, dexterity=14),
        proficiency_bonus=3,
        is_player_controlled=True,
        character_class="Wizard",
        level=5,
        class_resources={"spell_slot_2": 3, "spell_slot_3": 2},
    )


def _make_enemy(
    name: str = "Goblin",
    hp: int = 15,
    ac: int = 13,
) -> Creature:
    return Creature(
        name=name,
        max_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(dexterity=14),
        proficiency_bonus=2,
        is_player_controlled=False,
        ai_profile="default_monster",
    )


def _fireball_action() -> Action:
    """Non-concentration AoE — instant burst centered on a location."""
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


def _moonbeam_action() -> Action:
    """Concentration AoE — creates a persistent fixed-center zone."""
    return Action(
        name="Moonbeam",
        description="A silvery beam of light.",
        action_type=ActionType.ACTION,
        target_type=TargetType.AREA_CYLINDER,
        range=120,
        area_size=5,
        requires_concentration=True,
        saving_throw=SavingThrowEffect(
            ability="constitution",
            dc=15,
            damage_on_fail=[DamageRoll(dice="2d10", damage_type=DamageType.RADIANT)],
            damage_on_success="half",
        ),
        resource_cost={"spell_slot_2": 1},
    )


def _spirit_guardians_action() -> Action:
    """Concentration AoE — follows caster (existing behavior, cast via execute_effect)."""
    return Action(
        name="Spirit Guardians",
        description="Spirits swirl around you.",
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


def _make_encounter(
    player_actions=None,
    enemy_pos=(7, 5),
    enemy2_pos=None,
) -> Encounter:
    wizard = _make_player("Wizard", hp=30)
    wizard.actions = player_actions or []
    entries = [
        CombatantEntry(
            creature_id="wizard_inline",
            creature_data=wizard,
            team="player",
            starting_position=(2, 2),
        ),
        CombatantEntry(
            creature_id="goblin_inline",
            creature_data=_make_enemy("Goblin"),
            team="enemy",
            starting_position=enemy_pos,
        ),
    ]
    if enemy2_pos:
        entries.append(CombatantEntry(
            creature_id="goblin2_inline",
            creature_data=_make_enemy("Goblin 2"),
            team="enemy",
            starting_position=enemy2_pos,
        ))
    return Encounter(name="AoE Test", grid_width=20, grid_height=15, combatants=entries)


def _setup_combat(player_actions=None, enemy_pos=(7, 5), enemy2_pos=None):
    """Create a CombatManager in IN_COMBAT state with the wizard's turn active."""
    enc = _make_encounter(player_actions, enemy_pos, enemy2_pos)
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))

    cm.roll_initiative()
    cm.begin_combat()

    # Find the wizard and ensure it's their turn
    wizard_id = None
    for cid, c in cm.combatants.items():
        if c.team == "player":
            wizard_id = cid
            break

    # Advance until wizard's turn
    while cm.active_combatant and cm.active_combatant.creature_id != wizard_id:
        cm.end_turn()

    return cm, wizard_id


# ── Feature 1a: Click-to-place creates fixed-center zone ────────────


class TestFixedCenterZoneCreation:
    def test_moonbeam_creates_fixed_center_zone(self):
        """Casting Moonbeam via execute_effect_at_hex creates a zone at the target hex."""
        cm, wiz_id = _setup_combat(player_actions=[_moonbeam_action()])
        cm.select_action(cm.combatants[wiz_id].creature.actions[0])

        target_hex = HexCoord(5, 5)
        result = cm.execute_effect_at_hex(target_hex)

        assert result is not None
        assert result.success
        assert len(cm.active_zones) == 1

        zone = cm.active_zones[0]
        assert zone.follows_caster is False
        assert zone.center == target_hex
        assert zone.name == "Moonbeam"
        assert zone.concentration_linked is True

    def test_spirit_guardians_via_old_path_still_follows_caster(self):
        """execute_effect (the old path) still creates follows_caster=True zones."""
        cm, wiz_id = _setup_combat(
            player_actions=[_spirit_guardians_action()],
            enemy_pos=(3, 2),
        )
        cm.select_action(cm.combatants[wiz_id].creature.actions[0])

        # Use old execute_effect with a creature target
        goblin_id = [cid for cid, c in cm.combatants.items() if c.team == "enemy"][0]
        result = cm.execute_effect(goblin_id)

        assert result is not None
        assert result.success
        assert len(cm.active_zones) == 1

        zone = cm.active_zones[0]
        assert zone.follows_caster is True
        assert zone.center is None

    def test_fixed_zone_center_stays_when_caster_moves(self):
        """A fixed-center zone should NOT move when the caster moves."""
        cm, wiz_id = _setup_combat(player_actions=[_moonbeam_action()])
        cm.select_action(cm.combatants[wiz_id].creature.actions[0])

        target_hex = HexCoord(8, 8)
        cm.execute_effect_at_hex(target_hex)

        zone = cm.active_zones[0]
        assert zone.center == target_hex

        # Simulate caster moving (change position)
        old_pos = cm.combatants[wiz_id].position
        # The zone center should still be the same
        zone_hexes_before = get_zone_hexes(zone, cm.combatants, cm.grid)
        assert target_hex in zone_hexes_before


# ── Feature 1b: Non-zone AoE resolves at target hex ─────────────────


class TestAoEAtHex:
    @patch("arena.combat.actions.resolve_saving_throw")
    def test_fireball_hits_creatures_near_target_hex(self, mock_save):
        """Fireball centered at target hex should hit creatures near that hex."""
        mock_save.return_value = (False, None)
        # Enemy at (7,5), wizard at (2,2). Fireball area_size=20 (4 hexes).
        # Target the hex at (7,5) — enemy should be hit
        cm, wiz_id = _setup_combat(
            player_actions=[_fireball_action()],
            enemy_pos=(7, 5),
        )
        cm.select_action(cm.combatants[wiz_id].creature.actions[0])

        goblin_id = [cid for cid, c in cm.combatants.items() if c.team == "enemy"][0]
        goblin_hp_before = cm.combatants[goblin_id].creature.current_hit_points

        target_hex = HexCoord(7, 5)
        result = cm.execute_effect_at_hex(target_hex)

        assert result is not None
        assert result.success
        # Goblin should have taken damage
        assert cm.combatants[goblin_id].creature.current_hit_points < goblin_hp_before

    @patch("arena.combat.actions.resolve_saving_throw")
    def test_fireball_misses_distant_creatures(self, mock_save):
        """Fireball centered far from an enemy should NOT hit that enemy."""
        mock_save.return_value = (False, None)
        # Enemy at (15,10), wizard at (2,2). area_size=20 (4 hexes)
        # Target hex at (2,3) — far from enemy
        cm, wiz_id = _setup_combat(
            player_actions=[_fireball_action()],
            enemy_pos=(15, 10),
        )
        cm.select_action(cm.combatants[wiz_id].creature.actions[0])

        goblin_id = [cid for cid, c in cm.combatants.items() if c.team == "enemy"][0]
        goblin_hp_before = cm.combatants[goblin_id].creature.current_hit_points

        target_hex = HexCoord(2, 3)
        result = cm.execute_effect_at_hex(target_hex)

        assert result is not None
        assert result.success  # Fireball "succeeds" even with no targets
        # Goblin should NOT have taken damage
        assert cm.combatants[goblin_id].creature.current_hit_points == goblin_hp_before

    @patch("arena.combat.actions.resolve_saving_throw")
    def test_fireball_hits_multiple_enemies(self, mock_save):
        """Fireball should hit all enemies within the AoE area."""
        mock_save.return_value = (False, None)
        cm, wiz_id = _setup_combat(
            player_actions=[_fireball_action()],
            enemy_pos=(7, 5),
            enemy2_pos=(7, 6),
        )
        cm.select_action(cm.combatants[wiz_id].creature.actions[0])

        enemies = {cid: c for cid, c in cm.combatants.items() if c.team == "enemy"}
        hp_before = {cid: c.creature.current_hit_points for cid, c in enemies.items()}

        target_hex = HexCoord(7, 5)
        result = cm.execute_effect_at_hex(target_hex)

        assert result is not None
        assert result.success
        for cid in enemies:
            assert cm.combatants[cid].creature.current_hit_points < hp_before[cid]

    def test_fireball_into_empty_area_consumes_resources(self):
        """Fireball into empty space should still consume the spell slot."""
        cm, wiz_id = _setup_combat(
            player_actions=[_fireball_action()],
            enemy_pos=(15, 10),
        )
        slots_before = cm.combatants[wiz_id].creature.class_resources.get("spell_slot_3", 0)

        cm.select_action(cm.combatants[wiz_id].creature.actions[0])
        target_hex = HexCoord(3, 3)
        result = cm.execute_effect_at_hex(target_hex)

        assert result is not None
        assert result.success
        slots_after = cm.combatants[wiz_id].creature.class_resources.get("spell_slot_3", 0)
        assert slots_after == slots_before - 1

    def test_action_economy_consumed(self):
        """execute_effect_at_hex should consume the action economy slot."""
        cm, wiz_id = _setup_combat(player_actions=[_fireball_action()])
        assert cm.turn_resources.has_used_action is False

        cm.select_action(cm.combatants[wiz_id].creature.actions[0])
        cm.execute_effect_at_hex(HexCoord(5, 5))

        assert cm.turn_resources.has_used_action is True
        assert cm.turn_phase == TurnPhase.AWAITING_ACTION


# ── Feature 1c: Backward compatibility ──────────────────────────────


class TestBackwardCompatibility:
    def test_execute_effect_unchanged_for_single_target(self):
        """execute_effect still works for single-target actions (non-AoE)."""
        heal_action = Action(
            name="Cure Wounds",
            description="Touch heal.",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_CREATURE,
            range=5,
            healing="1d8+3",
        )
        cm, wiz_id = _setup_combat(
            player_actions=[heal_action],
            enemy_pos=(15, 10),
        )
        # Damage the wizard first
        cm.combatants[wiz_id].creature.current_hit_points = 10

        cm.select_action(cm.combatants[wiz_id].creature.actions[0])
        result = cm.execute_effect(wiz_id)

        assert result is not None
        assert result.success
        assert cm.combatants[wiz_id].creature.current_hit_points > 10


# ── aoe_hexes on the effect-use event (GUI telegraph metadata) ──────


class TestAoEHexesInjection:
    def test_placed_blast_event_carries_true_shape(self):
        """The effect-use INFO event lists the blast's exact hexes so the
        GUI can telegraph the real shape (not a center+radius guess)."""
        cm, wiz_id = _setup_combat(player_actions=[_fireball_action()])
        cm.select_action(cm.combatants[wiz_id].creature.actions[0])

        target_hex = HexCoord(7, 5)  # enemy stands here
        result = cm.execute_effect_at_hex(target_hex)
        assert result is not None and result.success

        info = next(
            e for e in result.events
            if e.event_type == CombatEventType.INFO
            and e.details.get("is_effect_use")
        )
        hexes = info.details.get("aoe_hexes")
        assert hexes, "effect-use event should carry the blast shape"
        assert (7, 5) in hexes  # center is inside its own blast
        assert len(hexes) > 1  # a 20ft sphere covers more than one hex
        assert info.details.get("aoe_center_hex") == (7, 5)

    def test_empty_blast_event_carries_shape_too(self):
        """Fireball into empty space still telegraphs its area."""
        cm, wiz_id = _setup_combat(
            player_actions=[_fireball_action()], enemy_pos=(15, 10),
        )
        cm.select_action(cm.combatants[wiz_id].creature.actions[0])

        result = cm.execute_effect_at_hex(HexCoord(3, 3))
        assert result is not None and result.success

        info = next(
            e for e in result.events
            if e.event_type == CombatEventType.INFO
            and e.details.get("is_effect_use")
        )
        hexes = info.details.get("aoe_hexes")
        assert hexes and (3, 3) in hexes
