"""Tests for the Evasion feature (Rogue 7 / Monk 7).

Evasion modifies DEX save outcomes:
- On success: take 0 damage instead of half
- On fail: take half damage instead of full
- Only applies to DEX saves, not other abilities.

Tests cover:
- has_evasion() query function (no evasion, feature, feat)
- DEX save success with evasion → 0 damage
- DEX save fail with evasion → half damage
- WIS save with evasion → evasion does not apply
- No evasion → normal damage behavior
"""

import pytest
from unittest.mock import patch

from arena.models.character import Creature, PlayerCharacter, Feature
from arena.models.feats import Feat
from arena.models.actions import (
    Action, ActionType, TargetType,
    SavingThrowEffect, DamageRoll, DamageType,
)
from arena.combat.stat_modifiers import has_evasion
from arena.combat.actions import resolve_effect
from arena.combat.events import CombatEventType
from arena.grid.hexgrid import HexGrid
from arena.grid.coordinates import HexCoord


# ── Test Helpers ──────────────────────────────────────────────────────


def _make_creature(
    name: str = "Target",
    hp: int = 50,
    max_hp: int = 50,
    ac: int = 10,
    dexterity: int = 14,
) -> Creature:
    """Create a minimal creature (no evasion)."""
    return Creature(
        name=name,
        size="medium",
        creature_type="humanoid",
        ability_scores={
            "strength": 10, "dexterity": dexterity, "constitution": 10,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
        },
        armor_class=ac,
        max_hit_points=max_hp,
        current_hit_points=hp,
        speed={"walk": 30},
        proficiency_bonus=2,
    )


def _make_pc_with_evasion(
    name: str = "Rogue",
    hp: int = 50,
    max_hp: int = 50,
    dexterity: int = 14,
) -> PlayerCharacter:
    """Create a PlayerCharacter with the Evasion feature."""
    return PlayerCharacter(
        name=name,
        size="medium",
        creature_type="humanoid",
        ability_scores={
            "strength": 10, "dexterity": dexterity, "constitution": 10,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
        },
        armor_class=10,
        max_hit_points=max_hp,
        current_hit_points=hp,
        speed={"walk": 30},
        proficiency_bonus=3,
        features=[Feature(name="Evasion", description="DEX save evasion", has_evasion=True)],
        character_class="rogue",
        level=7,
    )


def _make_pc_with_evasion_feat(
    name: str = "Evader",
    hp: int = 50,
    max_hp: int = 50,
) -> PlayerCharacter:
    """Create a PlayerCharacter with evasion via feat."""
    return PlayerCharacter(
        name=name,
        size="medium",
        creature_type="humanoid",
        ability_scores={
            "strength": 10, "dexterity": 14, "constitution": 10,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
        },
        armor_class=10,
        max_hit_points=max_hp,
        current_hit_points=hp,
        speed={"walk": 30},
        proficiency_bonus=3,
        feats=[Feat(name="Evasion Feat", has_evasion=True)],
        character_class="fighter",
        level=7,
    )


def _make_grid() -> HexGrid:
    return HexGrid(10, 10)


def _fireball_action(dc: int = 15) -> Action:
    """DEX save, half on success."""
    return Action(
        name="Fireball",
        description="A bright streak...",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=150,
        saving_throw=SavingThrowEffect(
            ability="dexterity",
            dc=dc,
            damage_on_fail=[DamageRoll(dice="8d6", damage_type=DamageType.FIRE)],
            damage_on_success="half",
        ),
    )


def _wis_save_action(dc: int = 15) -> Action:
    """WIS save, half on success (for testing evasion doesn't apply)."""
    return Action(
        name="Psychic Blast",
        description="A wave of psychic energy.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=60,
        saving_throw=SavingThrowEffect(
            ability="wisdom",
            dc=dc,
            damage_on_fail=[DamageRoll(dice="8d6", damage_type=DamageType.PSYCHIC)],
            damage_on_success="half",
        ),
    )


# ── has_evasion() query tests ────────────────────────────────────────


class TestHasEvasionQuery:
    """Tests for the has_evasion() stat_modifiers function."""

    def test_creature_without_evasion(self):
        creature = _make_creature()
        assert has_evasion(creature) is False

    def test_pc_without_evasion(self):
        pc = PlayerCharacter(
            name="Fighter",
            size="medium",
            creature_type="humanoid",
            ability_scores={
                "strength": 10, "dexterity": 10, "constitution": 10,
                "intelligence": 10, "wisdom": 10, "charisma": 10,
            },
            armor_class=10,
            max_hit_points=50,
            current_hit_points=50,
            speed={"walk": 30},
            proficiency_bonus=2,
            character_class="fighter",
            level=5,
        )
        assert has_evasion(pc) is False

    def test_pc_with_evasion_feature(self):
        pc = _make_pc_with_evasion()
        assert has_evasion(pc) is True

    def test_pc_with_evasion_feat(self):
        pc = _make_pc_with_evasion_feat()
        assert has_evasion(pc) is True

    def test_evasion_feature_false_by_default(self):
        """Feature without has_evasion=True should not grant evasion."""
        pc = PlayerCharacter(
            name="Rogue",
            size="medium",
            creature_type="humanoid",
            ability_scores={
                "strength": 10, "dexterity": 10, "constitution": 10,
                "intelligence": 10, "wisdom": 10, "charisma": 10,
            },
            armor_class=10,
            max_hit_points=50,
            current_hit_points=50,
            speed={"walk": 30},
            proficiency_bonus=2,
            features=[Feature(name="Sneak Attack", description="Extra damage")],
            character_class="rogue",
            level=7,
        )
        assert has_evasion(pc) is False


# ── Integration tests: resolve_effect with evasion ───────────────────


class TestEvasionIntegration:
    """Integration tests for Evasion modifying save damage in resolve_effect()."""

    def test_dex_save_success_with_evasion_takes_zero_damage(self):
        """DEX save success + evasion → 0 damage (normally half)."""
        caster = _make_creature(name="Mage", hp=30, max_hp=30)
        target = _make_pc_with_evasion(hp=50, max_hp=50)
        grid = _make_grid()
        grid.place_creature(HexCoord(2, 2), "mage")
        grid.place_creature(HexCoord(4, 4), "rogue")

        action = _fireball_action(dc=15)

        # Save: d20 roll of 18 + DEX mod (+2) = 20 >= DC 15 → success
        # Damage: 24
        with patch("arena.combat.actions.roll_die", return_value=18), \
             patch("arena.combat.actions.roll_damage", return_value=(24, [{"dice": "8d6", "total": 24}])):
            result = resolve_effect(
                action=action,
                user=caster,
                user_id="mage",
                target=target,
                target_id="rogue",
                grid=grid,
            )

        # Evasion: save success → 0 damage
        assert target.current_hit_points == 50
        # Check for evasion info event
        evasion_msgs = [
            e for e in result.events
            if e.event_type == CombatEventType.INFO
            and "Evasion negates" in e.message
        ]
        assert len(evasion_msgs) == 1

    def test_dex_save_fail_with_evasion_takes_half_damage(self):
        """DEX save fail + evasion → half damage (normally full)."""
        caster = _make_creature(name="Mage", hp=30, max_hp=30)
        target = _make_pc_with_evasion(hp=50, max_hp=50)
        grid = _make_grid()
        grid.place_creature(HexCoord(2, 2), "mage")
        grid.place_creature(HexCoord(4, 4), "rogue")

        action = _fireball_action(dc=15)

        # Save: d20 roll of 2 + DEX mod (+2) = 4 < DC 15 → fail
        # Damage: 24
        with patch("arena.combat.actions.roll_die", return_value=2), \
             patch("arena.combat.actions.roll_damage", return_value=(24, [{"dice": "8d6", "total": 24}])):
            result = resolve_effect(
                action=action,
                user=caster,
                user_id="mage",
                target=target,
                target_id="rogue",
                grid=grid,
            )

        # Evasion: save fail → half damage = 24 // 2 = 12
        assert target.current_hit_points == 50 - 12
        # Check for evasion info event
        evasion_msgs = [
            e for e in result.events
            if e.event_type == CombatEventType.INFO
            and "Evasion halves" in e.message
        ]
        assert len(evasion_msgs) == 1

    def test_wis_save_with_evasion_does_not_apply(self):
        """WIS save + evasion → evasion does NOT apply (only DEX)."""
        caster = _make_creature(name="Mage", hp=30, max_hp=30)
        target = _make_pc_with_evasion(hp=50, max_hp=50)
        grid = _make_grid()
        grid.place_creature(HexCoord(2, 2), "mage")
        grid.place_creature(HexCoord(4, 4), "rogue")

        action = _wis_save_action(dc=15)

        # Save: d20 roll of 2 + WIS mod (+0) = 2 < DC 15 → fail
        # Damage: 24 → full damage (no evasion for WIS)
        with patch("arena.combat.actions.roll_die", return_value=2), \
             patch("arena.combat.actions.roll_damage", return_value=(24, [{"dice": "8d6", "total": 24}])):
            result = resolve_effect(
                action=action,
                user=caster,
                user_id="mage",
                target=target,
                target_id="rogue",
                grid=grid,
            )

        # No evasion: full 24 damage
        assert target.current_hit_points == 50 - 24
        # No evasion event
        evasion_msgs = [
            e for e in result.events
            if e.event_type == CombatEventType.INFO
            and "Evasion" in e.message
        ]
        assert len(evasion_msgs) == 0

    def test_no_evasion_normal_damage(self):
        """No evasion + DEX save fail → full damage."""
        caster = _make_creature(name="Mage", hp=30, max_hp=30)
        target = _make_creature(name="Commoner", hp=50, max_hp=50)
        grid = _make_grid()
        grid.place_creature(HexCoord(2, 2), "mage")
        grid.place_creature(HexCoord(4, 4), "commoner")

        action = _fireball_action(dc=15)

        # Save: fail, Damage: 24 → full
        with patch("arena.combat.actions.roll_die", return_value=2), \
             patch("arena.combat.actions.roll_damage", return_value=(24, [{"dice": "8d6", "total": 24}])):
            result = resolve_effect(
                action=action,
                user=caster,
                user_id="mage",
                target=target,
                target_id="commoner",
                grid=grid,
            )

        assert target.current_hit_points == 50 - 24

    def test_no_evasion_dex_save_success_half_damage(self):
        """No evasion + DEX save success → half damage (normal behavior)."""
        caster = _make_creature(name="Mage", hp=30, max_hp=30)
        target = _make_creature(name="Commoner", hp=50, max_hp=50)
        grid = _make_grid()
        grid.place_creature(HexCoord(2, 2), "mage")
        grid.place_creature(HexCoord(4, 4), "commoner")

        action = _fireball_action(dc=15)

        # Save: d20 roll of 18 + DEX mod (+2) = 20 >= DC 15 → success
        # Damage: 24, half = 12
        with patch("arena.combat.actions.roll_die", return_value=18), \
             patch("arena.combat.actions.roll_damage", return_value=(24, [{"dice": "8d6", "total": 24}])):
            result = resolve_effect(
                action=action,
                user=caster,
                user_id="mage",
                target=target,
                target_id="commoner",
                grid=grid,
            )

        assert target.current_hit_points == 50 - 12
