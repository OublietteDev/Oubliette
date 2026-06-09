"""Tests for the buff/debuff system (src/combat/buff_effects.py).

Tests cover:
- BuffEffect / ActiveBuff model creation and serialization
- Query functions: AC bonus, speed bonus/multiplier, attack/save modifiers,
  attack/save advantage, damage resistances/immunities
- Target-side debuffs (Faerie Fire pattern)
- Lifecycle: apply_buff, remove_buff
- Duration ticking (rounds decrement, removal at 0)
- Save-to-end processing
- Concentration link + cleanup removes buffs
- Integration: resolve_effect applies buffs, attack/save rolls include buff bonuses
"""

import pytest
from unittest.mock import patch

from arena.models.character import Creature
from arena.models.actions import Action, ActionType, TargetType, SavingThrowEffect
from arena.models.conditions import BuffEffect, ActiveBuff, Condition
from arena.combat.buff_effects import (
    get_buff_ac_bonus,
    get_buff_speed_bonus,
    get_buff_speed_multiplier,
    get_buff_attack_modifiers,
    get_buff_save_modifiers,
    get_buff_attack_advantage,
    get_buff_save_advantage,
    get_buff_damage_resistances,
    get_buff_damage_immunities,
    apply_buff,
    remove_buff,
    process_buff_start_of_turn,
    process_buff_end_of_turn,
)
from arena.combat.stat_modifiers import (
    get_effective_armor_class,
    get_effective_speed,
    get_effective_damage_resistances,
    get_effective_damage_immunities,
)
from arena.combat.condition_effects import get_attack_advantage, get_save_advantage
from arena.combat.concentration import (
    start_concentrating,
    add_concentration_buff_link,
    end_concentration,
)
from arena.combat.conditions import has_condition
from arena.combat.actions import resolve_effect
from arena.grid.hexgrid import HexGrid
from arena.grid.coordinates import HexCoord


# ── Test Helpers ──────────────────────────────────────────────────────


def _make_creature(
    name: str = "Test",
    armor_class: int = 10,
    dexterity: int = 10,
    strength: int = 10,
    max_hp: int = 50,
    speed: dict | None = None,
    proficiency_bonus: int = 2,
    saving_throw_proficiencies: list | None = None,
) -> Creature:
    """Create a minimal creature for testing."""
    from arena.models.abilities import AbilityScores
    return Creature(
        name=name,
        max_hit_points=max_hp,
        armor_class=armor_class,
        ability_scores=AbilityScores(
            strength=strength,
            dexterity=dexterity,
            constitution=10,
            intelligence=10,
            wisdom=10,
            charisma=10,
        ),
        speed=speed or {"walk": 30},
        proficiency_bonus=proficiency_bonus,
        saving_throw_proficiencies=saving_throw_proficiencies or [],
    )


def _shield_buff(source_id: str = "caster_1") -> ActiveBuff:
    """Shield: +5 AC for 1 round."""
    return ActiveBuff(
        name="Shield",
        source_id=source_id,
        modifiers=[BuffEffect(stat="ac", modifier_type="flat_bonus", value=5)],
        duration_type="rounds",
        duration_rounds=1,
    )


def _bless_buff(source_id: str = "caster_1") -> ActiveBuff:
    """Bless: +1d4 to attack rolls and saving throws (concentration)."""
    return ActiveBuff(
        name="Bless",
        source_id=source_id,
        modifiers=[
            BuffEffect(stat="attack_rolls", modifier_type="flat_bonus", value="1d4"),
            BuffEffect(stat="saving_throws", modifier_type="flat_bonus", value="1d4"),
        ],
    )


def _haste_buff(source_id: str = "caster_1") -> ActiveBuff:
    """Haste: +2 AC, speed x2, advantage on DEX saves (concentration)."""
    return ActiveBuff(
        name="Haste",
        source_id=source_id,
        modifiers=[
            BuffEffect(stat="ac", modifier_type="flat_bonus", value=2),
            BuffEffect(stat="speed", modifier_type="multiply", value=2.0),
            BuffEffect(stat="saving_throws", modifier_type="advantage", scope="dexterity"),
        ],
    )


def _faerie_fire_debuff(source_id: str = "caster_1") -> ActiveBuff:
    """Faerie Fire: advantage on attacks against target (concentration)."""
    return ActiveBuff(
        name="Faerie Fire",
        source_id=source_id,
        modifiers=[
            BuffEffect(
                stat="attack_rolls",
                modifier_type="advantage",
                target_grants_to_attacker=True,
            ),
        ],
    )


def _absorb_elements_buff(damage_type: str = "fire", source_id: str = "caster_1") -> ActiveBuff:
    """Absorb Elements: resistance to a damage type for 1 round."""
    return ActiveBuff(
        name="Absorb Elements",
        source_id=source_id,
        modifiers=[
            BuffEffect(stat="damage_resistance", modifier_type="resistance", value=damage_type),
        ],
        duration_type="rounds",
        duration_rounds=1,
    )


def _bane_debuff(source_id: str = "caster_1") -> ActiveBuff:
    """Bane: -1d4 to attack rolls and saving throws (save-to-end)."""
    return ActiveBuff(
        name="Bane",
        source_id=source_id,
        modifiers=[
            BuffEffect(stat="attack_rolls", modifier_type="flat_bonus", value="-1d4"),
            BuffEffect(stat="saving_throws", modifier_type="flat_bonus", value="-1d4"),
        ],
        duration_type="end_of_turn",
        save_to_end="charisma",
        save_dc=13,
    )


# ── Model Tests ───────────────────────────────────────────────────────


class TestBuffModels:
    def test_buff_effect_creation(self):
        mod = BuffEffect(stat="ac", modifier_type="flat_bonus", value=5)
        assert mod.stat == "ac"
        assert mod.modifier_type == "flat_bonus"
        assert mod.value == 5
        assert mod.scope == "all"
        assert mod.target_grants_to_attacker is False

    def test_buff_effect_with_scope(self):
        mod = BuffEffect(stat="saving_throws", modifier_type="advantage", scope="dexterity")
        assert mod.scope == "dexterity"

    def test_buff_effect_target_grants_to_attacker(self):
        mod = BuffEffect(
            stat="attack_rolls", modifier_type="advantage", target_grants_to_attacker=True,
        )
        assert mod.target_grants_to_attacker is True

    def test_active_buff_creation(self):
        buff = _shield_buff()
        assert buff.name == "Shield"
        assert buff.source_id == "caster_1"
        assert len(buff.modifiers) == 1
        assert buff.duration_type == "rounds"
        assert buff.duration_rounds == 1

    def test_active_buff_serialization(self):
        buff = _bless_buff()
        data = buff.model_dump()
        restored = ActiveBuff(**data)
        assert restored.name == "Bless"
        assert len(restored.modifiers) == 2

    def test_creature_has_active_buffs_field(self):
        c = _make_creature()
        assert c.active_buffs == []


# ── Query Function Tests ─────────────────────────────────────────────


class TestACBonus:
    def test_no_buffs(self):
        c = _make_creature()
        assert get_buff_ac_bonus(c) == 0

    def test_shield_ac_bonus(self):
        c = _make_creature()
        c.active_buffs.append(_shield_buff())
        assert get_buff_ac_bonus(c) == 5

    def test_haste_ac_bonus(self):
        c = _make_creature()
        c.active_buffs.append(_haste_buff())
        assert get_buff_ac_bonus(c) == 2

    def test_stacking_ac_bonuses(self):
        c = _make_creature()
        c.active_buffs.append(_shield_buff())
        c.active_buffs.append(_haste_buff())
        assert get_buff_ac_bonus(c) == 7

    def test_negative_ac_bonus(self):
        c = _make_creature()
        c.active_buffs.append(ActiveBuff(
            name="Slow", source_id="enemy_1",
            modifiers=[BuffEffect(stat="ac", modifier_type="flat_bonus", value=-2)],
        ))
        assert get_buff_ac_bonus(c) == -2

    def test_integrated_with_stat_modifiers(self):
        """get_effective_armor_class should include buff AC bonus."""
        c = _make_creature(dexterity=10)
        base_ac = get_effective_armor_class(c)
        c.active_buffs.append(_shield_buff())
        buffed_ac = get_effective_armor_class(c)
        assert buffed_ac == base_ac + 5


class TestSpeedBonus:
    def test_no_buffs(self):
        c = _make_creature()
        assert get_buff_speed_bonus(c) == 0
        assert get_buff_speed_multiplier(c) == 1.0

    def test_flat_speed_bonus(self):
        c = _make_creature()
        c.active_buffs.append(ActiveBuff(
            name="Longstrider", source_id="caster_1",
            modifiers=[BuffEffect(stat="speed", modifier_type="flat_bonus", value=10)],
        ))
        assert get_buff_speed_bonus(c) == 10

    def test_speed_multiplier(self):
        c = _make_creature()
        c.active_buffs.append(_haste_buff())
        assert get_buff_speed_multiplier(c) == 2.0

    def test_speed_multiplier_slow(self):
        c = _make_creature()
        c.active_buffs.append(ActiveBuff(
            name="Slow", source_id="enemy_1",
            modifiers=[BuffEffect(stat="speed", modifier_type="multiply", value=0.5)],
        ))
        assert get_buff_speed_multiplier(c) == 0.5

    def test_haste_and_slow_cancel(self):
        c = _make_creature()
        c.active_buffs.append(_haste_buff())
        c.active_buffs.append(ActiveBuff(
            name="Slow", source_id="enemy_1",
            modifiers=[BuffEffect(stat="speed", modifier_type="multiply", value=0.5)],
        ))
        assert get_buff_speed_multiplier(c) == 1.0

    def test_integrated_speed_with_multiplier(self):
        """get_effective_speed should include buff multiplier."""
        c = _make_creature(speed={"walk": 30})
        assert get_effective_speed(c) == 30
        c.active_buffs.append(_haste_buff())
        assert get_effective_speed(c) == 60  # 30 * 2.0

    def test_speed_minimum_zero(self):
        c = _make_creature(speed={"walk": 30})
        c.active_buffs.append(ActiveBuff(
            name="Slowdown", source_id="enemy_1",
            modifiers=[BuffEffect(stat="speed", modifier_type="flat_bonus", value=-50)],
        ))
        assert get_effective_speed(c) == 0


class TestAttackModifiers:
    def test_no_buffs(self):
        c = _make_creature()
        flat, dice = get_buff_attack_modifiers(c)
        assert flat == 0
        assert dice == []

    def test_bless_attack_dice(self):
        c = _make_creature()
        c.active_buffs.append(_bless_buff())
        flat, dice = get_buff_attack_modifiers(c)
        assert flat == 0
        assert dice == ["1d4"]

    def test_bane_attack_dice(self):
        c = _make_creature()
        c.active_buffs.append(_bane_debuff())
        flat, dice = get_buff_attack_modifiers(c)
        assert flat == 0
        assert dice == ["-1d4"]

    def test_flat_attack_bonus(self):
        c = _make_creature()
        c.active_buffs.append(ActiveBuff(
            name="Magic Weapon", source_id="caster_1",
            modifiers=[BuffEffect(stat="attack_rolls", modifier_type="flat_bonus", value=2)],
        ))
        flat, dice = get_buff_attack_modifiers(c)
        assert flat == 2
        assert dice == []

    def test_target_grants_to_attacker_excluded(self):
        """Faerie Fire on the creature should NOT give it an attack bonus."""
        c = _make_creature()
        c.active_buffs.append(_faerie_fire_debuff())
        flat, dice = get_buff_attack_modifiers(c)
        assert flat == 0
        assert dice == []


class TestSaveModifiers:
    def test_no_buffs(self):
        c = _make_creature()
        flat, dice = get_buff_save_modifiers(c, "dexterity")
        assert flat == 0
        assert dice == []

    def test_bless_save_dice(self):
        c = _make_creature()
        c.active_buffs.append(_bless_buff())
        flat, dice = get_buff_save_modifiers(c, "wisdom")
        assert dice == ["1d4"]

    def test_bless_scope_all(self):
        """Bless applies to all saves."""
        c = _make_creature()
        c.active_buffs.append(_bless_buff())
        for ability in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
            _, dice = get_buff_save_modifiers(c, ability)
            assert dice == ["1d4"], f"Expected Bless on {ability}"

    def test_scoped_save_modifier(self):
        """A scoped save modifier only applies to the matching ability."""
        c = _make_creature()
        c.active_buffs.append(ActiveBuff(
            name="Custom", source_id="caster_1",
            modifiers=[BuffEffect(stat="saving_throws", modifier_type="flat_bonus", value="1d6", scope="constitution")],
        ))
        _, dice_con = get_buff_save_modifiers(c, "constitution")
        assert dice_con == ["1d6"]
        _, dice_dex = get_buff_save_modifiers(c, "dexterity")
        assert dice_dex == []


class TestAttackAdvantage:
    def test_no_buffs(self):
        attacker = _make_creature(name="Attacker")
        target = _make_creature(name="Target")
        assert get_buff_attack_advantage(attacker, target) == 0

    def test_faerie_fire_on_target(self):
        """Faerie Fire on target grants advantage to attackers."""
        attacker = _make_creature(name="Attacker")
        target = _make_creature(name="Target")
        target.active_buffs.append(_faerie_fire_debuff())
        assert get_buff_attack_advantage(attacker, target) == 1

    def test_attacker_advantage_buff(self):
        attacker = _make_creature(name="Attacker")
        target = _make_creature(name="Target")
        attacker.active_buffs.append(ActiveBuff(
            name="Greater Invisibility", source_id="caster_1",
            modifiers=[BuffEffect(stat="attack_rolls", modifier_type="advantage")],
        ))
        assert get_buff_attack_advantage(attacker, target) == 1

    def test_attacker_disadvantage_buff(self):
        attacker = _make_creature(name="Attacker")
        target = _make_creature(name="Target")
        attacker.active_buffs.append(ActiveBuff(
            name="Hex Debuff", source_id="enemy_1",
            modifiers=[BuffEffect(stat="attack_rolls", modifier_type="disadvantage")],
        ))
        assert get_buff_attack_advantage(attacker, target) == -1

    def test_advantage_and_disadvantage_cancel(self):
        attacker = _make_creature(name="Attacker")
        target = _make_creature(name="Target")
        attacker.active_buffs.append(ActiveBuff(
            name="Buff", source_id="ally",
            modifiers=[BuffEffect(stat="attack_rolls", modifier_type="advantage")],
        ))
        target.active_buffs.append(ActiveBuff(
            name="Debuff", source_id="enemy",
            modifiers=[
                BuffEffect(stat="attack_rolls", modifier_type="disadvantage", target_grants_to_attacker=True),
            ],
        ))
        assert get_buff_attack_advantage(attacker, target) == 0

    def test_integrated_with_condition_effects(self):
        """get_attack_advantage should include buff-based advantage."""
        attacker = _make_creature(name="Attacker")
        target = _make_creature(name="Target")
        target.active_buffs.append(_faerie_fire_debuff())
        # condition_effects.get_attack_advantage should now include buff advantage
        result = get_attack_advantage(attacker, target, is_melee=True)
        assert result == 1


class TestSaveAdvantage:
    def test_haste_dex_save_advantage(self):
        c = _make_creature()
        c.active_buffs.append(_haste_buff())
        assert get_buff_save_advantage(c, "dexterity") == 1
        assert get_buff_save_advantage(c, "wisdom") == 0  # Not scoped

    def test_integrated_save_advantage(self):
        """get_save_advantage should include buff advantage."""
        c = _make_creature()
        c.active_buffs.append(_haste_buff())
        result = get_save_advantage(c, "dexterity")
        assert result == 1


class TestDamageResistances:
    def test_absorb_elements_fire(self):
        c = _make_creature()
        c.active_buffs.append(_absorb_elements_buff("fire"))
        assert "fire" in get_buff_damage_resistances(c)

    def test_integrated_with_stat_modifiers(self):
        c = _make_creature()
        c.active_buffs.append(_absorb_elements_buff("cold"))
        resistances = get_effective_damage_resistances(c)
        assert "cold" in resistances

    def test_buff_immunities(self):
        c = _make_creature()
        c.active_buffs.append(ActiveBuff(
            name="Invulnerability", source_id="caster_1",
            modifiers=[BuffEffect(stat="damage_resistance", modifier_type="immunity", value="all")],
        ))
        assert "all" in get_buff_damage_immunities(c)


# ── Lifecycle Tests ──────────────────────────────────────────────────


class TestApplyRemoveBuff:
    def test_apply_buff(self):
        c = _make_creature()
        event = apply_buff(c, "creature_1", _shield_buff())
        assert len(c.active_buffs) == 1
        assert c.active_buffs[0].name == "Shield"
        assert "Shield" in event.message

    def test_apply_replaces_duplicate(self):
        """Same name + source replaces, doesn't stack."""
        c = _make_creature()
        apply_buff(c, "c1", _shield_buff())
        apply_buff(c, "c1", _shield_buff())
        assert len(c.active_buffs) == 1

    def test_different_sources_stack(self):
        """Different sources of same-named buff do stack."""
        c = _make_creature()
        apply_buff(c, "c1", _shield_buff("caster_1"))
        apply_buff(c, "c1", _shield_buff("caster_2"))
        assert len(c.active_buffs) == 2

    def test_remove_buff_by_name(self):
        c = _make_creature()
        apply_buff(c, "c1", _shield_buff())
        event = remove_buff(c, "c1", "Shield")
        assert len(c.active_buffs) == 0
        assert event is not None
        assert "Shield" in event.message

    def test_remove_nonexistent_returns_none(self):
        c = _make_creature()
        event = remove_buff(c, "c1", "Nonexistent")
        assert event is None

    def test_remove_by_name_and_source(self):
        c = _make_creature()
        apply_buff(c, "c1", _shield_buff("caster_1"))
        apply_buff(c, "c1", _shield_buff("caster_2"))
        remove_buff(c, "c1", "Shield", source_id="caster_1")
        assert len(c.active_buffs) == 1
        assert c.active_buffs[0].source_id == "caster_2"


class TestDurationTicking:
    def test_rounds_decrement(self):
        c = _make_creature()
        c.active_buffs.append(_shield_buff())
        assert c.active_buffs[0].duration_rounds == 1
        events = process_buff_start_of_turn(c, "c1")
        assert len(c.active_buffs) == 0
        assert any("expired" in e.message for e in events)

    def test_rounds_multi_turn(self):
        """A buff lasting 3 rounds should survive 2 turns."""
        c = _make_creature()
        c.active_buffs.append(ActiveBuff(
            name="Mage Armor", source_id="caster_1",
            modifiers=[BuffEffect(stat="ac", modifier_type="flat_bonus", value=3)],
            duration_type="rounds", duration_rounds=3,
        ))
        # Turn 1: 3 -> 2
        process_buff_start_of_turn(c, "c1")
        assert len(c.active_buffs) == 1
        assert c.active_buffs[0].duration_rounds == 2
        # Turn 2: 2 -> 1
        process_buff_start_of_turn(c, "c1")
        assert len(c.active_buffs) == 1
        assert c.active_buffs[0].duration_rounds == 1
        # Turn 3: 1 -> 0 (removed)
        process_buff_start_of_turn(c, "c1")
        assert len(c.active_buffs) == 0

    def test_indefinite_not_ticked(self):
        c = _make_creature()
        c.active_buffs.append(_bless_buff())  # indefinite (concentration)
        process_buff_start_of_turn(c, "c1")
        assert len(c.active_buffs) == 1  # Not removed


class TestSaveToEnd:
    @patch("arena.combat.actions.resolve_saving_throw")
    def test_save_success_removes_debuff(self, mock_save):
        from arena.combat.events import CombatEvent, CombatEventType
        mock_save.return_value = (True, CombatEvent(
            event_type=CombatEventType.SAVING_THROW,
            message="Test saves: SUCCESS",
            source_id="c1",
        ))
        c = _make_creature()
        c.active_buffs.append(_bane_debuff())
        events = process_buff_end_of_turn(c, "c1")
        assert len(c.active_buffs) == 0
        assert any("shakes off" in e.message for e in events)

    @patch("arena.combat.actions.resolve_saving_throw")
    def test_save_failure_keeps_debuff(self, mock_save):
        from arena.combat.events import CombatEvent, CombatEventType
        mock_save.return_value = (False, CombatEvent(
            event_type=CombatEventType.SAVING_THROW,
            message="Test saves: FAILURE",
            source_id="c1",
        ))
        c = _make_creature()
        c.active_buffs.append(_bane_debuff())
        events = process_buff_end_of_turn(c, "c1")
        assert len(c.active_buffs) == 1  # Still active


# ── Concentration Integration Tests ─────────────────────────────────


class TestConcentrationIntegration:
    def test_concentration_tracks_linked_buffs(self):
        caster = _make_creature(name="Caster")
        target = _make_creature(name="Target")
        start_concentrating(caster, "caster_1", "Bless")
        add_concentration_buff_link(caster, "target_1", "Bless")

        # Verify the link exists
        for ac in caster.active_conditions:
            if ac.condition == Condition.CONCENTRATING:
                assert ["target_1", "Bless"] in ac.extra_data["linked_buffs"]

    def test_end_concentration_removes_buffs(self):
        caster = _make_creature(name="Caster")
        target = _make_creature(name="Target")
        target.active_buffs.append(_bless_buff("caster_1"))

        start_concentrating(caster, "caster_1", "Bless")
        add_concentration_buff_link(caster, "target_1", "Bless")

        combatants = {
            "caster_1": type("C", (), {"creature": caster})(),
            "target_1": type("C", (), {"creature": target})(),
        }

        events = end_concentration(caster, "caster_1", combatants)
        assert len(target.active_buffs) == 0
        assert any("Bless" in e.message for e in events)

    def test_new_concentration_ends_old_buffs(self):
        """Starting a new concentration spell should end the old one's buffs."""
        caster = _make_creature(name="Caster")
        target = _make_creature(name="Target")
        target.active_buffs.append(_bless_buff("caster_1"))

        start_concentrating(caster, "caster_1", "Bless")
        add_concentration_buff_link(caster, "target_1", "Bless")

        combatants = {
            "caster_1": type("C", (), {"creature": caster})(),
            "target_1": type("C", (), {"creature": target})(),
        }

        # Start new concentration → should end Bless and remove its buff
        start_concentrating(caster, "caster_1", "Hold Person", combatants)
        assert len(target.active_buffs) == 0


# ── Integration: resolve_effect applies buffs ─────────────────────────


class TestResolveEffectBuffs:
    def _make_grid(self):
        grid = HexGrid(20, 20)
        return grid

    def test_resolve_effect_applies_buff(self):
        """An action with buff_effects should apply the buff to the target."""
        caster = _make_creature(name="Cleric")
        target = _make_creature(name="Fighter")
        grid = self._make_grid()
        grid.place_creature(HexCoord(5, 5), "caster_1", caster.size)
        grid.place_creature(HexCoord(5, 6), "target_1", target.size)

        shield_action = Action(
            name="Shield of Faith",
            description="+2 AC",
            action_type=ActionType.BONUS_ACTION,
            target_type=TargetType.ONE_ALLY,
            range=60,
            requires_concentration=True,
            buff_effects=[
                BuffEffect(stat="ac", modifier_type="flat_bonus", value=2),
            ],
        )

        result = resolve_effect(
            caster, "caster_1", target, "target_1",
            shield_action, grid, combatants={
                "caster_1": type("C", (), {"creature": caster})(),
                "target_1": type("C", (), {"creature": target})(),
            },
        )

        assert len(target.active_buffs) == 1
        assert target.active_buffs[0].name == "Shield of Faith"
        assert get_buff_ac_bonus(target) == 2
        # Caster should be concentrating
        assert has_condition(caster, Condition.CONCENTRATING)

    def test_resolve_effect_debuff_on_failed_save(self):
        """A debuff with a saving throw should only apply on failed save."""
        caster = _make_creature(name="Bard")
        target = _make_creature(name="Orc", dexterity=10)
        grid = self._make_grid()
        grid.place_creature(HexCoord(5, 5), "caster_1", caster.size)
        grid.place_creature(HexCoord(5, 6), "target_1", target.size)

        bane_action = Action(
            name="Bane",
            description="-1d4 attacks and saves",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_ENEMY,
            range=30,
            requires_concentration=True,
            saving_throw=SavingThrowEffect(
                ability="charisma",
                dc=13,
            ),
            buff_effects=[
                BuffEffect(stat="attack_rolls", modifier_type="flat_bonus", value="-1d4"),
                BuffEffect(stat="saving_throws", modifier_type="flat_bonus", value="-1d4"),
            ],
        )

        # Force a failed save
        with patch("arena.combat.actions.roll_die", return_value=1):
            result = resolve_effect(
                caster, "caster_1", target, "target_1",
                bane_action, grid, combatants={
                    "caster_1": type("C", (), {"creature": caster})(),
                    "target_1": type("C", (), {"creature": target})(),
                },
            )

        assert len(target.active_buffs) == 1
        assert target.active_buffs[0].name == "Bane"
        assert target.active_buffs[0].save_to_end == "charisma"

    def test_resolve_effect_no_debuff_on_passed_save(self):
        """A debuff with a saving throw should NOT apply on successful save."""
        caster = _make_creature(name="Bard")
        target = _make_creature(name="Orc")
        grid = self._make_grid()
        grid.place_creature(HexCoord(5, 5), "caster_1", caster.size)
        grid.place_creature(HexCoord(5, 6), "target_1", target.size)

        bane_action = Action(
            name="Bane",
            description="-1d4 attacks and saves",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_ENEMY,
            range=30,
            requires_concentration=True,
            saving_throw=SavingThrowEffect(
                ability="charisma",
                dc=5,  # Very low DC
            ),
            buff_effects=[
                BuffEffect(stat="attack_rolls", modifier_type="flat_bonus", value="-1d4"),
                BuffEffect(stat="saving_throws", modifier_type="flat_bonus", value="-1d4"),
            ],
        )

        # Force a successful save
        with patch("arena.combat.actions.roll_die", return_value=20):
            result = resolve_effect(
                caster, "caster_1", target, "target_1",
                bane_action, grid, combatants={
                    "caster_1": type("C", (), {"creature": caster})(),
                    "target_1": type("C", (), {"creature": target})(),
                },
            )

        assert len(target.active_buffs) == 0

    def test_non_concentration_timed_buff(self):
        """Shield-like buff with duration_rounds should work without concentration."""
        caster = _make_creature(name="Wizard")
        grid = self._make_grid()
        grid.place_creature(HexCoord(5, 5), "caster_1", caster.size)

        shield_action = Action(
            name="Shield",
            description="+5 AC",
            action_type=ActionType.REACTION,
            target_type=TargetType.SELF,
            range=0,
            requires_concentration=False,
            buff_effects=[
                BuffEffect(stat="ac", modifier_type="flat_bonus", value=5),
            ],
            buff_duration_rounds=1,
        )

        result = resolve_effect(
            caster, "caster_1", caster, "caster_1",
            shield_action, grid,
        )

        assert len(caster.active_buffs) == 1
        assert caster.active_buffs[0].duration_type == "rounds"
        assert caster.active_buffs[0].duration_rounds == 1
        # Not concentrating
        assert not has_condition(caster, Condition.CONCENTRATING)
        # AC should be +5
        assert get_buff_ac_bonus(caster) == 5
