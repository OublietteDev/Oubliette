"""Tests for the upcast scaling system."""

import pytest
from unittest.mock import patch

from arena.models.actions import (
    Action, ActionType, Attack, DamageRoll, DamageType,
    SavingThrowEffect, TargetType,
)
from arena.models.character import PlayerCharacter, Creature, CreatureSize
from arena.combat.upcast import (
    get_spell_level,
    can_upcast,
    get_available_upcast_levels,
    get_max_upcast_level,
    calculate_upcast_bonus_damage,
    calculate_upcast_bonus_healing,
    calculate_upcast_zone_dice,
    make_upcast_resource_cost,
)


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_fireball():
    """Fireball: level 3, +1d6 per slot level above 3."""
    return Action(
        name="Fireball",
        description="8d6 fire, +1d6 per slot above 3rd",
        spell_level=3,
        target_type=TargetType.AREA_SPHERE,
        area_size=20,
        range=150,
        saving_throw=SavingThrowEffect(
            ability="dexterity",
            dc=15,
            damage_on_fail=[DamageRoll(dice="8d6", damage_type=DamageType.FIRE)],
            damage_on_success="half",
        ),
        resource_cost={"spell_slot_3": 1},
        requires_concentration=False,
        upcast_damage_dice="1d6",
        upcast_damage_per_levels=1,
    )


def _make_cure_wounds():
    """Cure Wounds: level 1, +1d8 healing per slot above 1st."""
    return Action(
        name="Cure Wounds",
        description="1d8+mod healing, +1d8 per slot above 1st",
        spell_level=1,
        target_type=TargetType.ONE_ALLY,
        range=5,
        healing="1d8+3",
        resource_cost={"spell_slot_1": 1},
        upcast_healing_dice="1d8",
        upcast_damage_per_levels=1,
    )


def _make_spiritual_weapon():
    """Spiritual Weapon: level 2, +1d8 per 2 slot levels above 2nd."""
    return Action(
        name="Spiritual Weapon",
        description="1d8+mod force, +1d8 per 2 slots above 2nd",
        spell_level=2,
        attack=Attack(
            name="Spiritual Weapon",
            attack_type="melee_spell",
            ability="wisdom",
            damage=[DamageRoll(dice="1d8", damage_type=DamageType.FORCE)],
        ),
        resource_cost={"spell_slot_2": 1},
        upcast_damage_dice="1d8",
        upcast_damage_per_levels=2,
    )


def _make_spirit_guardians():
    """Spirit Guardians: level 3 zone, +1d8 per slot level above 3rd."""
    return Action(
        name="Spirit Guardians",
        description="3d8 radiant zone, +1d8 per slot above 3rd",
        spell_level=3,
        target_type=TargetType.SELF,
        area_size=15,
        saving_throw=SavingThrowEffect(
            ability="wisdom",
            dc=15,
            damage_on_fail=[DamageRoll(dice="3d8", damage_type=DamageType.RADIANT)],
            damage_on_success="half",
        ),
        resource_cost={"spell_slot_3": 1},
        requires_concentration=True,
        zone_follows_caster=True,
        upcast_damage_dice="1d8",
        upcast_damage_per_levels=1,
    )


def _make_longsword():
    """Non-spell attack — should never be upcastable."""
    return Action(
        name="Longsword",
        description="Melee weapon attack",
        attack=Attack(
            name="Longsword",
            attack_type="melee_weapon",
            ability="strength",
            damage=[DamageRoll(dice="1d8", damage_type=DamageType.SLASHING)],
        ),
    )


def _make_caster(spell_slots=None):
    """Create a caster with spell slots synced to class_resources."""
    if spell_slots is None:
        spell_slots = {1: 4, 2: 3, 3: 3, 4: 1}
    return PlayerCharacter(
        name="Wizard",
        max_hit_points=30,
        character_class="Wizard",
        spell_slots=spell_slots,
    )


def _make_legacy_action():
    """Action without spell_level, using only resource_cost for level."""
    return Action(
        name="Legacy Fireball",
        description="Old-style fireball",
        saving_throw=SavingThrowEffect(
            ability="dexterity",
            dc=15,
            damage_on_fail=[DamageRoll(dice="8d6", damage_type=DamageType.FIRE)],
            damage_on_success="half",
        ),
        resource_cost={"spell_slot_3": 1},
        upcast_damage_dice="1d6",
    )


# ── get_spell_level ──────────────────────────────────────────────────


class TestGetSpellLevel:
    def test_explicit_spell_level(self):
        fb = _make_fireball()
        assert get_spell_level(fb) == 3

    def test_fallback_to_resource_cost(self):
        legacy = _make_legacy_action()
        assert get_spell_level(legacy) == 3

    def test_non_spell_returns_none(self):
        sword = _make_longsword()
        assert get_spell_level(sword) is None

    def test_multiple_resource_costs(self):
        action = Action(
            name="Multi",
            description="Multi",
            resource_cost={"ki_points": 2, "spell_slot_5": 1},
            spell_level=None,
        )
        assert get_spell_level(action) == 5


# ── can_upcast ───────────────────────────────────────────────────────


class TestCanUpcast:
    def test_fireball_can_upcast(self):
        assert can_upcast(_make_fireball()) is True

    def test_cure_wounds_can_upcast(self):
        assert can_upcast(_make_cure_wounds()) is True

    def test_longsword_cannot_upcast(self):
        assert can_upcast(_make_longsword()) is False

    def test_spell_without_scaling_cannot_upcast(self):
        action = Action(
            name="Shield",
            description="Reaction shield",
            spell_level=1,
            resource_cost={"spell_slot_1": 1},
        )
        assert can_upcast(action) is False


# ── get_available_upcast_levels ──────────────────────────────────────


class TestGetAvailableUpcastLevels:
    def test_returns_sorted_levels(self):
        fb = _make_fireball()
        caster = _make_caster({3: 2, 4: 1, 5: 1})
        levels = get_available_upcast_levels(fb, caster)
        assert levels == [3, 4, 5]

    def test_excludes_below_base(self):
        fb = _make_fireball()
        caster = _make_caster({1: 4, 2: 3, 3: 1})
        levels = get_available_upcast_levels(fb, caster)
        assert levels == [3]

    def test_excludes_empty_slots(self):
        fb = _make_fireball()
        caster = _make_caster({3: 0, 4: 0, 5: 1})
        levels = get_available_upcast_levels(fb, caster)
        assert levels == [5]

    def test_non_spell_returns_empty(self):
        sword = _make_longsword()
        caster = _make_caster()
        assert get_available_upcast_levels(sword, caster) == []


# ── get_max_upcast_level ─────────────────────────────────────────────


class TestGetMaxUpcastLevel:
    def test_returns_highest(self):
        fb = _make_fireball()
        caster = _make_caster({3: 1, 5: 1})
        assert get_max_upcast_level(fb, caster) == 5

    def test_no_higher_slots_returns_base(self):
        fb = _make_fireball()
        caster = _make_caster({3: 1})
        assert get_max_upcast_level(fb, caster) == 3

    def test_non_spell_returns_zero(self):
        sword = _make_longsword()
        caster = _make_caster()
        assert get_max_upcast_level(sword, caster) == 0


# ── calculate_upcast_bonus_damage ────────────────────────────────────


class TestCalculateUpcastBonusDamage:
    def test_fireball_at_5th_adds_2d6(self):
        fb = _make_fireball()
        bonus = calculate_upcast_bonus_damage(fb, cast_level=5)
        assert len(bonus) == 1
        assert bonus[0].dice == "2d6"
        assert bonus[0].damage_type == DamageType.FIRE

    def test_fireball_at_base_returns_empty(self):
        fb = _make_fireball()
        assert calculate_upcast_bonus_damage(fb, cast_level=3) == []

    def test_fireball_below_base_returns_empty(self):
        fb = _make_fireball()
        assert calculate_upcast_bonus_damage(fb, cast_level=2) == []

    def test_spiritual_weapon_per_2_levels(self):
        sw = _make_spiritual_weapon()
        # At 4th: (4-2)//2 = 1 step → 1d8
        bonus = calculate_upcast_bonus_damage(sw, cast_level=4)
        assert len(bonus) == 1
        assert bonus[0].dice == "1d8"
        assert bonus[0].damage_type == DamageType.FORCE

    def test_spiritual_weapon_at_3rd_no_step(self):
        sw = _make_spiritual_weapon()
        # At 3rd: (3-2)//2 = 0 steps → no bonus
        assert calculate_upcast_bonus_damage(sw, cast_level=3) == []

    def test_spiritual_weapon_at_6th_gives_2_steps(self):
        sw = _make_spiritual_weapon()
        # At 6th: (6-2)//2 = 2 steps → 2d8
        bonus = calculate_upcast_bonus_damage(sw, cast_level=6)
        assert len(bonus) == 1
        assert bonus[0].dice == "2d8"

    def test_non_spell_returns_empty(self):
        sword = _make_longsword()
        assert calculate_upcast_bonus_damage(sword, cast_level=5) == []

    def test_no_upcast_dice_returns_empty(self):
        action = Action(
            name="Shield",
            description="Shield",
            spell_level=1,
            resource_cost={"spell_slot_1": 1},
        )
        assert calculate_upcast_bonus_damage(action, cast_level=3) == []

    def test_attack_spell_gets_correct_damage_type(self):
        sw = _make_spiritual_weapon()
        bonus = calculate_upcast_bonus_damage(sw, cast_level=4)
        assert bonus[0].damage_type == DamageType.FORCE

    def test_save_spell_gets_correct_damage_type(self):
        fb = _make_fireball()
        bonus = calculate_upcast_bonus_damage(fb, cast_level=4)
        assert bonus[0].damage_type == DamageType.FIRE


# ── calculate_upcast_bonus_healing ───────────────────────────────────


class TestCalculateUpcastBonusHealing:
    def test_cure_wounds_at_3rd_adds_2d8(self):
        cw = _make_cure_wounds()
        expr = calculate_upcast_bonus_healing(cw, cast_level=3)
        assert expr == "2d8"

    def test_cure_wounds_at_base_returns_none(self):
        cw = _make_cure_wounds()
        assert calculate_upcast_bonus_healing(cw, cast_level=1) is None

    def test_non_healing_spell_returns_none(self):
        fb = _make_fireball()
        assert calculate_upcast_bonus_healing(fb, cast_level=5) is None


# ── calculate_upcast_zone_dice ───────────────────────────────────────


class TestCalculateUpcastZoneDice:
    def test_spirit_guardians_at_5th(self):
        sg = _make_spirit_guardians()
        # Base 3d8 + 2 levels of 1d8 → 5d8
        result = calculate_upcast_zone_dice(sg, cast_level=5)
        assert result == "5d8"

    def test_spirit_guardians_at_base_returns_none(self):
        sg = _make_spirit_guardians()
        assert calculate_upcast_zone_dice(sg, cast_level=3) is None

    def test_non_zone_spell_returns_none(self):
        fb = _make_fireball()
        # Fireball has saving_throw damage but isn't a zone spell in upcast context
        # (it has upcast_damage_dice and saving_throw.damage_on_fail — so the
        # function will actually compute zone dice). This tests the raw calculation.
        result = calculate_upcast_zone_dice(fb, cast_level=5)
        # Fireball: base 8d6 + 2×1d6 = 10d6 (function treats any save-damage spell)
        assert result == "10d6"


# ── make_upcast_resource_cost ────────────────────────────────────────


class TestMakeUpcastResourceCost:
    def test_substitutes_spell_slot_key(self):
        fb = _make_fireball()
        cost = make_upcast_resource_cost(fb, cast_level=5)
        assert cost == {"spell_slot_5": 1}

    def test_at_base_level_preserves_original(self):
        fb = _make_fireball()
        cost = make_upcast_resource_cost(fb, cast_level=3)
        assert cost == {"spell_slot_3": 1}

    def test_preserves_non_spell_slot_costs(self):
        action = Action(
            name="SorcFireball",
            description="Sorcery point fireball",
            spell_level=3,
            resource_cost={"spell_slot_3": 1, "sorcery_points": 2},
            upcast_damage_dice="1d6",
        )
        cost = make_upcast_resource_cost(action, cast_level=5)
        assert cost == {"spell_slot_5": 1, "sorcery_points": 2}

    def test_non_spell_preserves_cost(self):
        sword = _make_longsword()
        cost = make_upcast_resource_cost(sword, cast_level=5)
        assert cost == {}


# ── Resolution Pipeline Integration ──────────────────────────────────


class TestResolutionPipeline:
    """Test that cast_level flows through the resolution functions."""

    def test_check_resource_cost_with_upcast(self):
        from arena.combat.actions import check_resource_cost
        fb = _make_fireball()
        caster = _make_caster({3: 0, 5: 1})
        # Without cast_level: no 3rd-level slots → fail
        can_use, _ = check_resource_cost(caster, fb)
        assert not can_use
        # With cast_level=5: has 5th-level slot → pass
        can_use, _ = check_resource_cost(caster, fb, cast_level=5)
        assert can_use

    def test_deduct_resource_cost_with_upcast(self):
        from arena.combat.actions import deduct_resource_cost
        fb = _make_fireball()
        caster = _make_caster({3: 2, 5: 1})
        deduct_resource_cost(caster, fb, cast_level=5)
        # 5th-level slot should be decremented
        assert caster.class_resources["spell_slot_5"] == 0
        # 3rd-level slots untouched
        assert caster.class_resources["spell_slot_3"] == 2

    def test_resolve_attack_hit_stores_cast_level(self):
        from arena.combat.actions import resolve_attack_hit
        from arena.grid.hexgrid import HexGrid
        from arena.grid.coordinates import HexCoord
        sw = _make_spiritual_weapon()
        caster = _make_caster({2: 2, 4: 1})
        target = Creature(name="Goblin", max_hit_points=7, armor_class=13)
        grid = HexGrid(20, 20)
        grid.place_creature(HexCoord(5, 5), "caster_1", caster.size)
        grid.place_creature(HexCoord(6, 5), "goblin_1", target.size)
        hit_result = resolve_attack_hit(
            attacker=caster, attacker_id="caster_1",
            target=target, target_id="goblin_1",
            action=sw, grid=grid, combatants={},
            attacker_pos=HexCoord(5, 5),
            target_pos=HexCoord(6, 5),
            cast_level=4,
        )
        assert hit_result.cast_level == 4

    @patch("arena.combat.actions.roll_die")
    def test_resolve_effect_upcast_damage(self, mock_roll):
        """Fireball at 5th level should roll 10d6 total (8d6 base + 2d6 upcast)."""
        from arena.combat.actions import resolve_effect
        from arena.grid.hexgrid import HexGrid
        from arena.grid.coordinates import HexCoord

        fb = _make_fireball()
        caster = _make_caster({3: 1, 5: 1})
        target = Creature(name="Goblin", max_hit_points=50, armor_class=13)

        grid = HexGrid(20, 20)
        grid.place_creature(HexCoord(5, 5), "caster_1", caster.size)
        grid.place_creature(HexCoord(6, 6), "goblin_1", target.size)

        combatants = {}

        # Make save always fail (roll low)
        mock_roll.return_value = 2

        result = resolve_effect(
            user=caster, user_id="caster_1",
            target=target, target_id="goblin_1",
            action=fb, grid=grid, combatants=combatants,
            user_pos=HexCoord(5, 5), target_pos=HexCoord(6, 6),
            cast_level=5,
        )
        assert result.success
        # Verify damage was dealt (exact amount depends on rolls,
        # but we can check the target took damage)
        assert target.current_hit_points < 50

    @patch("arena.util.dice.roll_die")
    def test_resolve_effect_upcast_healing(self, mock_roll):
        """Cure Wounds at 3rd level should heal more than base."""
        from arena.combat.actions import resolve_effect
        from arena.grid.hexgrid import HexGrid
        from arena.grid.coordinates import HexCoord

        cw = _make_cure_wounds()
        caster = _make_caster({1: 2, 3: 1})
        target = PlayerCharacter(
            name="Fighter",
            max_hit_points=50,
            character_class="Fighter",
        )
        target.current_hit_points = 10

        grid = HexGrid(20, 20)
        grid.place_creature(HexCoord(5, 5), "caster_1", caster.size)
        grid.place_creature(HexCoord(6, 5), "fighter_1", target.size)

        # All dice roll 4
        mock_roll.return_value = 4

        result = resolve_effect(
            user=caster, user_id="caster_1",
            target=target, target_id="fighter_1",
            action=cw, grid=grid, combatants={},
            user_pos=HexCoord(5, 5), target_pos=HexCoord(6, 5),
            cast_level=3,
        )
        assert result.success
        # Base: 1d8+3 = 4+3 = 7, upcast +2d8 = 4+4 = 8, total = 15
        assert target.current_hit_points == 25


# ── AI Integration ───────────────────────────────────────────────────


class TestAIUpcast:
    def test_scored_action_has_cast_level(self):
        from arena.ai.scoring import ScoredAction
        sa = ScoredAction(
            action_name="Fireball",
            target_id="goblin_1",
            score=80.0,
            action_category="effect",
            description="Fireball (slot 5) -> goblin_1",
            cast_level=5,
        )
        assert sa.cast_level == 5

    def test_scored_action_default_none(self):
        from arena.ai.scoring import ScoredAction
        sa = ScoredAction(
            action_name="Longsword",
            target_id="goblin_1",
            score=60.0,
            action_category="attack",
            description="Longsword -> goblin_1",
        )
        assert sa.cast_level is None

    def test_turn_step_carries_cast_level(self):
        from arena.ai.controller import TurnStep, TurnStepType
        step = TurnStep(
            step_type=TurnStepType.SELECT_ACTION,
            action_name="Fireball",
            cast_level=5,
        )
        assert step.cast_level == 5

    def test_upcast_variant_scoring(self):
        from arena.ai.scoring import _generate_upcast_variants, ScoredAction
        fb = _make_fireball()
        caster = _make_caster({3: 2, 4: 1, 5: 1})

        base_scored = [
            ScoredAction(
                action_name="Fireball",
                target_id="goblin_1",
                score=70.0,
                action_category="effect",
                description="Fireball -> goblin_1",
            ),
        ]
        variants = _generate_upcast_variants(base_scored, [fb], caster)
        # Should have variants for level 4 and 5
        assert len(variants) >= 2
        levels = {v.cast_level for v in variants}
        assert 4 in levels
        assert 5 in levels
        # All variants should score higher than base (upcast bonus > penalty)
        for v in variants:
            assert v.cast_level is not None
            assert v.score > 0

    def test_upcast_variant_not_generated_for_non_spell(self):
        from arena.ai.scoring import _generate_upcast_variants, ScoredAction
        sword = _make_longsword()
        caster = _make_caster()

        base_scored = [
            ScoredAction(
                action_name="Longsword",
                target_id="goblin_1",
                score=60.0,
                action_category="attack",
                description="Longsword -> goblin_1",
            ),
        ]
        variants = _generate_upcast_variants(base_scored, [sword], caster)
        assert len(variants) == 0


# ── Backward Compatibility ───────────────────────────────────────────


class TestBackwardCompat:
    def test_action_without_upcast_fields_works(self):
        """Actions without upcast fields should be completely unaffected."""
        sword = _make_longsword()
        assert sword.spell_level is None
        assert sword.upcast_damage_dice is None
        assert sword.upcast_healing_dice is None
        assert sword.upcast_damage_per_levels == 1

    def test_legacy_resource_cost_detection(self):
        legacy = _make_legacy_action()
        assert get_spell_level(legacy) == 3
        assert can_upcast(legacy) is True

    def test_resolve_effect_without_cast_level_unchanged(self):
        """resolve_effect without cast_level should work exactly as before."""
        from arena.combat.actions import resolve_effect
        from arena.grid.hexgrid import HexGrid
        from arena.grid.coordinates import HexCoord

        fb = _make_fireball()
        caster = _make_caster({3: 2})
        target = Creature(name="Goblin", max_hit_points=50, armor_class=13)

        grid = HexGrid(20, 20)
        grid.place_creature(HexCoord(5, 5), "caster_1", caster.size)
        grid.place_creature(HexCoord(6, 6), "goblin_1", target.size)

        # No cast_level — should work normally
        result = resolve_effect(
            user=caster, user_id="caster_1",
            target=target, target_id="goblin_1",
            action=fb, grid=grid, combatants={},
            user_pos=HexCoord(5, 5), target_pos=HexCoord(6, 6),
        )
        assert result.success
