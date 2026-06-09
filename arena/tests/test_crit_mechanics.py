"""Tests for crit range expansion and bonus crit dice mechanics.

Tests cover:
- get_effective_crit_range() with no features, one feature, stacking features, feats
- get_bonus_crit_dice() with no features, one feature, stacking, feats
- resolve_attack_hit() correctly crits on expanded range (19, 18)
- resolve_attack_hit() still only crits on 20 with no features
- Bonus crit dice increase damage on critical hits
- Floor at 2 for crit range (cannot guarantee crits)
"""

import pytest
from unittest.mock import patch

from arena.models.character import Creature, PlayerCharacter, Feature
from arena.models.feats import Feat
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.combat.stat_modifiers import get_effective_crit_range, get_bonus_crit_dice
from arena.combat.actions import resolve_attack_hit, resolve_attack_damage
from arena.combat.events import CombatEventType
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid


# ── Test Helpers ──────────────────────────────────────────────────────


def _make_pc(
    features: list[Feature] | None = None,
    feats: list[Feat] | None = None,
    strength: int = 16,
    proficiency: int = 2,
) -> PlayerCharacter:
    """Create a minimal PlayerCharacter for testing."""
    return PlayerCharacter(
        name="Champion",
        character_class="Fighter",
        max_hit_points=50,
        ability_scores=AbilityScores(strength=strength),
        proficiency_bonus=proficiency,
        features=features or [],
        feats=feats or [],
    )


def _make_creature() -> Creature:
    """Create a base creature with no features/feats."""
    return Creature(
        name="Goblin",
        max_hit_points=10,
        armor_class=12,
    )


def _make_target(ac: int = 15, hp: int = 50) -> Creature:
    return Creature(
        name="Target",
        max_hit_points=hp,
        armor_class=ac,
    )


def _make_melee_action() -> Action:
    return Action(
        name="Greataxe",
        description="Melee weapon attack",
        action_type=ActionType.ACTION,
        attack=Attack(
            name="Greataxe",
            attack_type="melee_weapon",
            ability="strength",
            reach=5,
            damage=[
                DamageRoll(
                    dice="1d12",
                    damage_type=DamageType.SLASHING,
                    ability_modifier="strength",
                )
            ],
        ),
    )


def _setup_grid():
    grid = HexGrid(20, 20)
    grid.place_creature(HexCoord(5, 5), "attacker")
    grid.place_creature(HexCoord(5, 6), "target")
    return grid


# ── get_effective_crit_range Tests ────────────────────────────────────


class TestGetEffectiveCritRange:
    def test_default_is_20(self):
        """Base creature with no features should crit only on 20."""
        creature = _make_creature()
        assert get_effective_crit_range(creature) == 20

    def test_pc_no_features_is_20(self):
        """PC with no crit features should crit only on 20."""
        pc = _make_pc()
        assert get_effective_crit_range(pc) == 20

    def test_improved_critical_19(self):
        """Champion Fighter with crit_range_reduction=1 crits on 19-20."""
        pc = _make_pc(features=[
            Feature(
                name="Improved Critical",
                description="Crit on 19-20",
                crit_range_reduction=1,
            )
        ])
        assert get_effective_crit_range(pc) == 19

    def test_superior_critical_18(self):
        """Champion Fighter with crit_range_reduction=2 crits on 18-20."""
        pc = _make_pc(features=[
            Feature(
                name="Superior Critical",
                description="Crit on 18-20",
                crit_range_reduction=2,
            )
        ])
        assert get_effective_crit_range(pc) == 18

    def test_stacking_features(self):
        """Multiple features with crit_range_reduction should stack."""
        pc = _make_pc(features=[
            Feature(
                name="Improved Critical",
                description="Crit on 19-20",
                crit_range_reduction=1,
            ),
            Feature(
                name="Magic Weapon Bonus",
                description="Extra crit range",
                crit_range_reduction=1,
            ),
        ])
        assert get_effective_crit_range(pc) == 18

    def test_feat_crit_range(self):
        """Feat with crit_range_reduction should reduce crit threshold."""
        pc = _make_pc(feats=[
            Feat(
                name="Keen Strike",
                description="Crit on 19-20",
                crit_range_reduction=1,
            )
        ])
        assert get_effective_crit_range(pc) == 19

    def test_feature_and_feat_stack(self):
        """Feature and feat crit_range_reduction should stack."""
        pc = _make_pc(
            features=[
                Feature(
                    name="Improved Critical",
                    description="Crit range",
                    crit_range_reduction=1,
                )
            ],
            feats=[
                Feat(
                    name="Keen Strike",
                    description="More crit range",
                    crit_range_reduction=1,
                )
            ],
        )
        assert get_effective_crit_range(pc) == 18

    def test_floor_at_2(self):
        """Crit range cannot go below 2 (cannot guarantee crits)."""
        pc = _make_pc(features=[
            Feature(
                name="Absurd Crit",
                description="Ridiculous crit range",
                crit_range_reduction=25,
            )
        ])
        assert get_effective_crit_range(pc) == 2


# ── get_bonus_crit_dice Tests ────────────────────────────────────────


class TestGetBonusCritDice:
    def test_default_is_zero(self):
        """Base creature with no features should have 0 bonus crit dice."""
        creature = _make_creature()
        assert get_bonus_crit_dice(creature) == 0

    def test_pc_no_features_is_zero(self):
        """PC with no brutal critical should have 0 bonus crit dice."""
        pc = _make_pc()
        assert get_bonus_crit_dice(pc) == 0

    def test_brutal_critical_1(self):
        """Barbarian with Brutal Critical (+1 die)."""
        pc = _make_pc(features=[
            Feature(
                name="Brutal Critical",
                description="+1 weapon die on crit",
                bonus_crit_dice=1,
            )
        ])
        assert get_bonus_crit_dice(pc) == 1

    def test_brutal_critical_3(self):
        """Barbarian with max Brutal Critical (+3 dice)."""
        pc = _make_pc(features=[
            Feature(
                name="Brutal Critical",
                description="+3 weapon dice on crit",
                bonus_crit_dice=3,
            )
        ])
        assert get_bonus_crit_dice(pc) == 3

    def test_stacking_features(self):
        """Multiple features with bonus_crit_dice should stack."""
        pc = _make_pc(features=[
            Feature(
                name="Brutal Critical",
                description="+1 die",
                bonus_crit_dice=1,
            ),
            Feature(
                name="Savage Attacker",
                description="+1 die",
                bonus_crit_dice=1,
            ),
        ])
        assert get_bonus_crit_dice(pc) == 2

    def test_feat_bonus_crit_dice(self):
        """Feat with bonus_crit_dice."""
        pc = _make_pc(feats=[
            Feat(
                name="Devastating Crits",
                description="+1 die on crit",
                bonus_crit_dice=1,
            )
        ])
        assert get_bonus_crit_dice(pc) == 1

    def test_feature_and_feat_stack(self):
        """Feature and feat bonus_crit_dice should stack."""
        pc = _make_pc(
            features=[
                Feature(
                    name="Brutal Critical",
                    description="+2 dice",
                    bonus_crit_dice=2,
                )
            ],
            feats=[
                Feat(
                    name="Devastating Crits",
                    description="+1 die",
                    bonus_crit_dice=1,
                )
            ],
        )
        assert get_bonus_crit_dice(pc) == 3


# ── resolve_attack_hit Crit Range Integration ────────────────────────


class TestCritRangeIntegration:
    @patch("arena.combat.actions.roll_die")
    def test_normal_creature_crits_only_on_20(self, mock_d20):
        """Without crit range features, only natural 20 is a crit."""
        mock_d20.return_value = 19
        grid = _setup_grid()
        attacker = _make_pc()  # No crit features
        target = _make_target(ac=10)  # Low AC so 19 hits but shouldn't crit
        action = _make_melee_action()

        result = resolve_attack_hit(
            attacker, "attacker", target, "target", action, grid
        )
        assert result.hit is True
        assert result.critical is False

    @patch("arena.combat.actions.roll_die")
    def test_natural_20_always_crits(self, mock_d20):
        """Natural 20 should always crit regardless of features."""
        mock_d20.return_value = 20
        grid = _setup_grid()
        attacker = _make_pc()
        target = _make_target(ac=25)
        action = _make_melee_action()

        result = resolve_attack_hit(
            attacker, "attacker", target, "target", action, grid
        )
        assert result.hit is True
        assert result.critical is True

    @patch("arena.combat.actions.roll_die")
    def test_improved_critical_crits_on_19(self, mock_d20):
        """Champion with Improved Critical should crit on 19."""
        mock_d20.return_value = 19
        grid = _setup_grid()
        attacker = _make_pc(features=[
            Feature(
                name="Improved Critical",
                description="Crit on 19-20",
                crit_range_reduction=1,
            )
        ])
        target = _make_target(ac=10)
        action = _make_melee_action()

        result = resolve_attack_hit(
            attacker, "attacker", target, "target", action, grid
        )
        assert result.hit is True
        assert result.critical is True

    @patch("arena.combat.actions.roll_die")
    def test_superior_critical_crits_on_18(self, mock_d20):
        """Champion with Superior Critical should crit on 18."""
        mock_d20.return_value = 18
        grid = _setup_grid()
        attacker = _make_pc(features=[
            Feature(
                name="Superior Critical",
                description="Crit on 18-20",
                crit_range_reduction=2,
            )
        ])
        target = _make_target(ac=10)
        action = _make_melee_action()

        result = resolve_attack_hit(
            attacker, "attacker", target, "target", action, grid
        )
        assert result.hit is True
        assert result.critical is True

    @patch("arena.combat.actions.roll_die")
    def test_expanded_crit_range_17_not_crit(self, mock_d20):
        """Rolling 17 with crit_range_reduction=2 (threshold 18) should NOT crit."""
        mock_d20.return_value = 17
        grid = _setup_grid()
        attacker = _make_pc(features=[
            Feature(
                name="Superior Critical",
                description="Crit on 18-20",
                crit_range_reduction=2,
            )
        ])
        target = _make_target(ac=10)
        action = _make_melee_action()

        result = resolve_attack_hit(
            attacker, "attacker", target, "target", action, grid
        )
        assert result.hit is True
        assert result.critical is False

    @patch("arena.combat.actions.roll_die")
    def test_natural_1_still_misses_with_expanded_crit(self, mock_d20):
        """Natural 1 is always a critical miss, even with expanded crit range."""
        mock_d20.return_value = 1
        grid = _setup_grid()
        attacker = _make_pc(features=[
            Feature(
                name="Absurd Crit",
                description="Huge crit range",
                crit_range_reduction=19,  # threshold = 2, but nat 1 still misses
            )
        ])
        target = _make_target(ac=5)
        action = _make_melee_action()

        result = resolve_attack_hit(
            attacker, "attacker", target, "target", action, grid
        )
        assert result.hit is False
        assert result.critical is False


# ── Bonus Crit Dice Damage Integration ────────────────────────────────


class TestBonusCritDiceDamage:
    @patch("arena.combat.actions.roll_expression")
    @patch("arena.combat.damage.roll_expression")
    @patch("arena.combat.actions.roll_die")
    def test_bonus_crit_dice_adds_damage(
        self, mock_d20, mock_damage_roll, mock_actions_roll_expr
    ):
        """Brutal Critical should add extra weapon dice on a crit."""
        mock_d20.return_value = 20  # Critical hit
        # roll_damage calls roll_expression for "1d12" twice (normal + crit doubling)
        # Each call: (dice_total, [individual_rolls])
        mock_damage_roll.return_value = (6, [6])
        # The bonus crit dice roll via roll_expression in actions.py
        mock_actions_roll_expr.return_value = (8, [8])

        grid = _setup_grid()
        attacker = _make_pc(features=[
            Feature(
                name="Brutal Critical",
                description="+1 weapon die on crit",
                bonus_crit_dice=1,
            )
        ])
        target = _make_target(ac=15, hp=100)
        action = _make_melee_action()

        hit_result = resolve_attack_hit(
            attacker, "attacker", target, "target", action, grid
        )
        assert hit_result.critical is True

        damage_result = resolve_attack_damage(hit_result)
        # Find the damage event
        damage_events = [
            e for e in damage_result.events
            if e.event_type == CombatEventType.DAMAGE
        ]
        assert len(damage_events) == 1
        # Damage should be: 6 (normal) + 6 (crit double) + 3 (STR) + 8 (brutal critical) = 23
        assert damage_events[0].details["damage"] == 23

    @patch("arena.combat.actions.roll_expression")
    @patch("arena.combat.damage.roll_expression")
    @patch("arena.combat.actions.roll_die")
    def test_no_bonus_crit_dice_on_normal_hit(
        self, mock_d20, mock_damage_roll, mock_actions_roll_expr
    ):
        """Brutal Critical should NOT add extra dice on a normal (non-crit) hit."""
        mock_d20.return_value = 15  # Normal hit (15 + 5 = 20 vs AC 15)
        mock_damage_roll.return_value = (6, [6])

        grid = _setup_grid()
        attacker = _make_pc(features=[
            Feature(
                name="Brutal Critical",
                description="+1 weapon die on crit",
                bonus_crit_dice=1,
            )
        ])
        target = _make_target(ac=15, hp=100)
        action = _make_melee_action()

        hit_result = resolve_attack_hit(
            attacker, "attacker", target, "target", action, grid
        )
        assert hit_result.hit is True
        assert hit_result.critical is False

        damage_result = resolve_attack_damage(hit_result)
        damage_events = [
            e for e in damage_result.events
            if e.event_type == CombatEventType.DAMAGE
        ]
        assert len(damage_events) == 1
        # Normal hit: 6 (dice) + 3 (STR) = 9, no bonus crit dice
        assert damage_events[0].details["damage"] == 9
        # roll_expression in actions.py should NOT have been called (no bonus dice)
        mock_actions_roll_expr.assert_not_called()

    @patch("arena.combat.actions.roll_expression")
    @patch("arena.combat.damage.roll_expression")
    @patch("arena.combat.actions.roll_die")
    def test_no_bonus_dice_without_feature(
        self, mock_d20, mock_damage_roll, mock_actions_roll_expr
    ):
        """Creature without Brutal Critical should not get extra crit dice."""
        mock_d20.return_value = 20  # Critical hit
        mock_damage_roll.return_value = (6, [6])

        grid = _setup_grid()
        attacker = _make_pc()  # No bonus crit dice
        target = _make_target(ac=15, hp=100)
        action = _make_melee_action()

        hit_result = resolve_attack_hit(
            attacker, "attacker", target, "target", action, grid
        )
        assert hit_result.critical is True

        damage_result = resolve_attack_damage(hit_result)
        damage_events = [
            e for e in damage_result.events
            if e.event_type == CombatEventType.DAMAGE
        ]
        assert len(damage_events) == 1
        # Crit without brutal critical: 6 (normal) + 6 (crit double) + 3 (STR) = 15
        assert damage_events[0].details["damage"] == 15
        # roll_expression in actions.py should NOT have been called
        mock_actions_roll_expr.assert_not_called()

    @patch("arena.combat.actions.roll_expression")
    @patch("arena.combat.damage.roll_expression")
    @patch("arena.combat.actions.roll_die")
    def test_multiple_bonus_crit_dice(
        self, mock_d20, mock_damage_roll, mock_actions_roll_expr
    ):
        """Brutal Critical +3 should add 3 extra weapon dice on crit."""
        mock_d20.return_value = 20  # Critical hit
        mock_damage_roll.return_value = (6, [6])
        # 3d12 bonus from brutal critical
        mock_actions_roll_expr.return_value = (24, [8, 8, 8])

        grid = _setup_grid()
        attacker = _make_pc(features=[
            Feature(
                name="Brutal Critical",
                description="+3 weapon dice on crit",
                bonus_crit_dice=3,
            )
        ])
        target = _make_target(ac=15, hp=100)
        action = _make_melee_action()

        hit_result = resolve_attack_hit(
            attacker, "attacker", target, "target", action, grid
        )
        assert hit_result.critical is True

        damage_result = resolve_attack_damage(hit_result)
        damage_events = [
            e for e in damage_result.events
            if e.event_type == CombatEventType.DAMAGE
        ]
        assert len(damage_events) == 1
        # 6 (normal) + 6 (crit double) + 3 (STR) + 24 (3d12 brutal) = 39
        assert damage_events[0].details["damage"] == 39
        # Should have called roll_expression with "3d12"
        mock_actions_roll_expr.assert_called_once_with("3d12")
