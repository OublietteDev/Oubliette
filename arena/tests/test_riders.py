"""Tests for the on-hit rider system."""

import pytest
from unittest.mock import patch

from arena.models.character import (
    Feature, OnHitRider, RiderTrigger, PlayerCharacter,
    Creature, CreatureSize,
)
from arena.models.actions import Action, Attack, DamageRoll, DamageType
from arena.combat.riders import (
    discover_riders,
    calculate_rider_damage,
    calculate_rider_save_dc,
    resolve_rider_save,
    deduct_rider_resource,
    resolve_rider,
    get_available_spell_slots,
    get_rider_dice_preview,
    RiderResult,
    RIDER_PRESETS,
)


# ── Fixtures ─────────────────────────────────────────────────────────

def _make_paladin(spell_slots=None, features=None):
    """Create a basic paladin with Divine Smite."""
    if spell_slots is None:
        spell_slots = {1: 3, 2: 2}
    if features is None:
        features = [Feature(name="Divine Smite", description="Smite on hit")]
    return PlayerCharacter(
        name="Paladin",
        max_hit_points=40,
        character_class="Paladin",
        spell_slots=spell_slots,
        features=features,
        actions=[
            Action(
                name="Longsword",
                description="Melee weapon attack",
                attack=Attack(
                    name="Longsword",
                    attack_type="melee_weapon",
                    ability="strength",
                    damage=[DamageRoll(dice="1d8", damage_type="slashing")],
                ),
            ),
        ],
    )


def _make_rogue(sneak_dice="3d6"):
    """Create a rogue with Sneak Attack."""
    return PlayerCharacter(
        name="Rogue",
        max_hit_points=30,
        character_class="Rogue",
        features=[
            Feature(
                name="Sneak Attack",
                description="Extra damage once per turn",
                on_hit_rider=OnHitRider(
                    trigger=RiderTrigger.AUTOMATIC,
                    once_per_turn=True,
                    damage_dice=sneak_dice,
                    damage_type="piercing",
                ),
            ),
        ],
        actions=[
            Action(
                name="Shortsword",
                description="Melee weapon attack",
                attack=Attack(
                    name="Shortsword",
                    attack_type="melee_weapon",
                    ability="dexterity",
                    damage=[DamageRoll(dice="1d6", damage_type="piercing")],
                ),
            ),
        ],
    )


def _make_monk():
    """Create a monk with Stunning Strike."""
    return PlayerCharacter(
        name="Monk",
        max_hit_points=35,
        character_class="Monk",
        class_resources={"ki_points": 4},
        ability_scores={"strength": 10, "dexterity": 16, "constitution": 14,
                        "intelligence": 10, "wisdom": 16, "charisma": 10},
        proficiency_bonus=3,
        features=[
            Feature(
                name="Stunning Strike",
                description="Stun on hit for 1 ki",
                on_hit_rider=OnHitRider(
                    trigger=RiderTrigger.POST_HIT,
                    resource_type="ki_points",
                    resource_cost=1,
                    save_ability="constitution",
                    save_dc_ability="wisdom",
                    condition_on_fail="stunned",
                    condition_duration="end_of_turn",
                    condition_save_to_end=False,
                    requires_melee=True,
                ),
            ),
        ],
        actions=[
            Action(
                name="Unarmed Strike",
                description="Melee weapon attack",
                attack=Attack(
                    name="Unarmed Strike",
                    attack_type="melee_weapon",
                    ability="dexterity",
                    damage=[DamageRoll(dice="1d6", damage_type="bludgeoning")],
                ),
            ),
        ],
    )


def _make_target():
    """Create a simple target creature."""
    return Creature(
        name="Goblin",
        max_hit_points=20,
        ability_scores={"strength": 8, "dexterity": 14, "constitution": 10,
                        "intelligence": 10, "wisdom": 8, "charisma": 8},
    )


def _melee_weapon_action():
    return Action(
        name="Longsword",
        description="Melee attack",
        attack=Attack(
            name="Longsword",
            attack_type="melee_weapon",
            ability="strength",
            damage=[DamageRoll(dice="1d8", damage_type="slashing")],
        ),
    )


def _ranged_weapon_action():
    return Action(
        name="Longbow",
        description="Ranged attack",
        attack=Attack(
            name="Longbow",
            attack_type="ranged_weapon",
            ability="dexterity",
            damage=[DamageRoll(dice="1d8", damage_type="piercing")],
        ),
    )


def _melee_spell_action():
    return Action(
        name="Shocking Grasp",
        description="Spell attack",
        attack=Attack(
            name="Shocking Grasp",
            attack_type="melee_spell",
            ability="intelligence",
            damage=[DamageRoll(dice="1d8", damage_type="lightning")],
        ),
    )


# ── Model tests ──────────────────────────────────────────────────────

class TestOnHitRiderModel:
    def test_create_basic_rider(self):
        rider = OnHitRider(damage_dice="2d8", damage_type="radiant")
        assert rider.trigger == RiderTrigger.POST_HIT
        assert rider.damage_dice == "2d8"
        assert rider.once_per_turn is False

    def test_auto_upgrade_divine_smite(self):
        f = Feature(name="Divine Smite", description="Smite")
        assert f.on_hit_rider is not None
        assert f.on_hit_rider.trigger == RiderTrigger.POST_HIT
        assert f.on_hit_rider.resource_type == "spell_slot"
        assert f.on_hit_rider.damage_dice == "2d8"
        assert f.on_hit_rider.damage_type == "radiant"
        assert f.on_hit_rider.max_dice == 5

    def test_auto_upgrade_case_insensitive(self):
        f = Feature(name="divine smite", description="Smite")
        assert f.on_hit_rider is not None

    def test_no_auto_upgrade_other_features(self):
        f = Feature(name="Shield of Faith", description="AC bonus")
        assert f.on_hit_rider is None

    def test_no_auto_upgrade_if_rider_already_set(self):
        custom = OnHitRider(
            trigger=RiderTrigger.POST_HIT,
            damage_dice="1d6",
            damage_type="fire",
        )
        f = Feature(name="Divine Smite", description="Custom", on_hit_rider=custom)
        assert f.on_hit_rider.damage_dice == "1d6"  # Custom preserved

    def test_serialization_roundtrip(self):
        f = Feature(name="Divine Smite", description="Smite")
        data = f.model_dump()
        f2 = Feature(**data)
        assert f2.on_hit_rider is not None
        assert f2.on_hit_rider.damage_dice == "2d8"

    def test_rider_trigger_enum_values(self):
        assert RiderTrigger.POST_HIT.value == "post_hit"
        assert RiderTrigger.AUTOMATIC.value == "automatic"


# ── Discovery tests ──────────────────────────────────────────────────

class TestDiscoverRiders:
    def test_discover_divine_smite(self):
        pc = _make_paladin()
        riders = discover_riders(pc, pc.actions[0])
        assert len(riders) == 1
        assert riders[0][0].name == "Divine Smite"

    def test_discover_no_riders(self):
        pc = PlayerCharacter(
            name="Fighter", max_hit_points=40,
            character_class="Fighter",
            actions=[_melee_weapon_action()],
        )
        riders = discover_riders(pc, pc.actions[0])
        assert len(riders) == 0

    def test_discover_respects_requires_melee(self):
        """Divine Smite requires melee — should not appear for ranged attacks."""
        pc = _make_paladin()
        ranged = _ranged_weapon_action()
        riders = discover_riders(pc, ranged)
        assert len(riders) == 0

    def test_discover_respects_requires_weapon(self):
        """Divine Smite requires weapon — should not appear for spell attacks."""
        pc = _make_paladin()
        spell = _melee_spell_action()
        riders = discover_riders(pc, spell)
        assert len(riders) == 0

    def test_discover_once_per_turn_filtering(self):
        rogue = _make_rogue()
        # First attack: rider available
        riders = discover_riders(rogue, rogue.actions[0])
        assert len(riders) == 1
        # Second attack: rider already used
        used = {"Sneak Attack"}
        riders2 = discover_riders(rogue, rogue.actions[0], used_this_turn=used)
        assert len(riders2) == 0

    def test_discover_no_resources(self):
        """Rider with resource cost should not appear if no resources."""
        pc = _make_paladin(spell_slots={})
        # Manually clear class_resources too
        pc.class_resources = {}
        riders = discover_riders(pc, pc.actions[0])
        assert len(riders) == 0

    def test_discover_action_without_attack(self):
        """Actions without attack blocks should find no riders."""
        pc = _make_paladin()
        heal = Action(name="Heal", description="Healing")
        riders = discover_riders(pc, heal)
        assert len(riders) == 0

    def test_discover_multiple_riders(self):
        """Creature with both Divine Smite and another rider."""
        pc = _make_paladin(features=[
            Feature(name="Divine Smite", description="Smite"),
            Feature(
                name="Searing Smite",
                description="Fire on hit",
                on_hit_rider=OnHitRider(
                    trigger=RiderTrigger.POST_HIT,
                    resource_type="spell_slot",
                    resource_cost=1,
                    damage_dice="1d6",
                    damage_type="fire",
                    requires_melee=True,
                ),
            ),
        ])
        riders = discover_riders(pc, pc.actions[0])
        assert len(riders) == 2


# ── Damage calculation tests ─────────────────────────────────────────

class TestCalculateRiderDamage:
    def test_basic_damage(self):
        rider = OnHitRider(damage_dice="2d6", damage_type="fire")
        rolls = calculate_rider_damage(rider)
        assert len(rolls) == 1
        assert rolls[0].dice == "2d6"
        assert rolls[0].damage_type == DamageType.FIRE

    def test_divine_smite_level_1(self):
        rider = OnHitRider(
            damage_dice="2d8", damage_type="radiant",
            damage_per_slot_level="1d8", max_dice=5,
        )
        rolls = calculate_rider_damage(rider, slot_level=1)
        assert rolls[0].dice == "2d8"

    def test_divine_smite_level_2(self):
        rider = OnHitRider(
            damage_dice="2d8", damage_type="radiant",
            damage_per_slot_level="1d8", max_dice=5,
        )
        rolls = calculate_rider_damage(rider, slot_level=2)
        assert rolls[0].dice == "3d8"

    def test_divine_smite_level_4(self):
        rider = OnHitRider(
            damage_dice="2d8", damage_type="radiant",
            damage_per_slot_level="1d8", max_dice=5,
        )
        rolls = calculate_rider_damage(rider, slot_level=4)
        assert rolls[0].dice == "5d8"

    def test_divine_smite_level_5_capped(self):
        rider = OnHitRider(
            damage_dice="2d8", damage_type="radiant",
            damage_per_slot_level="1d8", max_dice=5,
        )
        rolls = calculate_rider_damage(rider, slot_level=5)
        assert rolls[0].dice == "5d8"  # Capped at 5

    def test_no_damage_dice(self):
        rider = OnHitRider(
            save_ability="constitution",
            condition_on_fail="stunned",
        )
        rolls = calculate_rider_damage(rider)
        assert len(rolls) == 0

    def test_no_scaling_no_slot(self):
        """Flat damage rider without scaling."""
        rider = OnHitRider(damage_dice="3d6", damage_type="piercing")
        rolls = calculate_rider_damage(rider)
        assert rolls[0].dice == "3d6"


# ── Save resolution tests ────────────────────────────────────────────

class TestResolveRiderSave:
    def test_calculate_dc(self):
        monk = _make_monk()
        rider = monk.features[0].on_hit_rider
        dc = calculate_rider_save_dc(rider, monk)
        # DC = 8 + prof(3) + WIS mod(+3) = 14
        assert dc == 14

    def test_no_save_returns_none(self):
        rider = OnHitRider(damage_dice="2d8")
        dc = calculate_rider_save_dc(rider, _make_target())
        assert dc is None

    @patch("arena.combat.riders.roll_die")
    def test_save_success(self, mock_roll):
        mock_roll.return_value = 20  # Auto-pass
        monk = _make_monk()
        rider = monk.features[0].on_hit_rider
        target = _make_target()
        saved, dc = resolve_rider_save(rider, monk, target)
        assert saved is True
        assert dc == 14

    @patch("arena.combat.riders.roll_die")
    def test_save_failure(self, mock_roll):
        mock_roll.return_value = 1  # Very likely fail
        monk = _make_monk()
        rider = monk.features[0].on_hit_rider
        target = _make_target()
        saved, dc = resolve_rider_save(rider, monk, target)
        assert saved is False


# ── Resource deduction tests ─────────────────────────────────────────

class TestDeductRiderResource:
    def test_deduct_spell_slot(self):
        pc = _make_paladin()
        rider = pc.features[0].on_hit_rider
        assert pc.class_resources["spell_slot_1"] == 3
        success = deduct_rider_resource(pc, rider, slot_level=1)
        assert success is True
        assert pc.class_resources["spell_slot_1"] == 2

    def test_deduct_spell_slot_exhausted(self):
        pc = _make_paladin(spell_slots={1: 0})
        pc.class_resources["spell_slot_1"] = 0
        rider = pc.features[0].on_hit_rider
        success = deduct_rider_resource(pc, rider, slot_level=1)
        assert success is False

    def test_deduct_ki_points(self):
        monk = _make_monk()
        rider = monk.features[0].on_hit_rider
        assert monk.class_resources["ki_points"] == 4
        success = deduct_rider_resource(monk, rider)
        assert success is True
        assert monk.class_resources["ki_points"] == 3

    def test_deduct_no_cost(self):
        rider = OnHitRider(damage_dice="3d6", damage_type="piercing")
        pc = _make_rogue()
        success = deduct_rider_resource(pc, rider)
        assert success is True

    def test_deduct_spell_slot_no_level_specified(self):
        pc = _make_paladin()
        rider = pc.features[0].on_hit_rider
        success = deduct_rider_resource(pc, rider, slot_level=None)
        assert success is False

    def test_deduct_insufficient_flat_resource(self):
        monk = _make_monk()
        monk.class_resources["ki_points"] = 0
        rider = monk.features[0].on_hit_rider
        success = deduct_rider_resource(monk, rider)
        assert success is False


# ── Full resolution tests ────────────────────────────────────────────

class TestResolveRider:
    def test_resolve_divine_smite(self):
        pc = _make_paladin()
        target = _make_target()
        feature = pc.features[0]
        rider = feature.on_hit_rider
        result = resolve_rider(feature, rider, pc, target, slot_level=2)
        assert result.used is True
        assert result.slot_level == 2
        assert len(result.bonus_damage) == 1
        assert result.bonus_damage[0].dice == "3d8"
        assert pc.class_resources["spell_slot_2"] == 1  # Deducted

    def test_resolve_sneak_attack(self):
        rogue = _make_rogue()
        target = _make_target()
        feature = rogue.features[0]
        rider = feature.on_hit_rider
        result = resolve_rider(feature, rider, rogue, target)
        assert result.used is True
        assert len(result.bonus_damage) == 1
        assert result.bonus_damage[0].dice == "3d6"

    @patch("arena.combat.riders.roll_die")
    def test_resolve_stunning_strike_fail_save(self, mock_roll):
        mock_roll.return_value = 1
        monk = _make_monk()
        target = _make_target()
        feature = monk.features[0]
        rider = feature.on_hit_rider
        result = resolve_rider(feature, rider, monk, target)
        assert result.used is True
        assert result.condition_to_apply == "stunned"
        assert monk.class_resources["ki_points"] == 3

    @patch("arena.combat.riders.roll_die")
    def test_resolve_stunning_strike_pass_save(self, mock_roll):
        mock_roll.return_value = 20
        monk = _make_monk()
        target = _make_target()
        feature = monk.features[0]
        rider = feature.on_hit_rider
        result = resolve_rider(feature, rider, monk, target)
        assert result.used is True
        assert result.condition_to_apply is None
        assert monk.class_resources["ki_points"] == 3  # Still deducted

    def test_resolve_insufficient_resources(self):
        monk = _make_monk()
        monk.class_resources["ki_points"] = 0
        target = _make_target()
        feature = monk.features[0]
        rider = feature.on_hit_rider
        result = resolve_rider(feature, rider, monk, target)
        assert result.used is False


# ── Spell slot helpers tests ─────────────────────────────────────────

class TestSpellSlotHelpers:
    def test_get_available_spell_slots(self):
        pc = _make_paladin()
        slots = get_available_spell_slots(pc)
        assert slots == {1: 3, 2: 2}

    def test_get_available_spell_slots_empty(self):
        pc = PlayerCharacter(
            name="Fighter", max_hit_points=40,
            character_class="Fighter",
        )
        slots = get_available_spell_slots(pc)
        assert slots == {}

    def test_dice_preview_level_1(self):
        rider = OnHitRider(
            damage_dice="2d8", damage_type="radiant",
            damage_per_slot_level="1d8", max_dice=5,
        )
        preview = get_rider_dice_preview(rider, 1)
        assert preview == "2d8 radiant"

    def test_dice_preview_level_3(self):
        rider = OnHitRider(
            damage_dice="2d8", damage_type="radiant",
            damage_per_slot_level="1d8", max_dice=5,
        )
        preview = get_rider_dice_preview(rider, 3)
        assert preview == "4d8 radiant"


# ── Presets tests ────────────────────────────────────────────────────

class TestRiderPresets:
    def test_divine_smite_preset_exists(self):
        assert "divine_smite" in RIDER_PRESETS
        p = RIDER_PRESETS["divine_smite"]
        assert p["trigger"] == "post_hit"
        assert p["damage_dice"] == "2d8"

    def test_sneak_attack_preset_exists(self):
        assert "sneak_attack" in RIDER_PRESETS
        p = RIDER_PRESETS["sneak_attack"]
        assert p["trigger"] == "automatic"
        assert p["once_per_turn"] is True

    def test_stunning_strike_preset_exists(self):
        assert "stunning_strike" in RIDER_PRESETS
        p = RIDER_PRESETS["stunning_strike"]
        assert p["condition_on_fail"] == "stunned"

    def test_preset_creates_valid_rider(self):
        for name, data in RIDER_PRESETS.items():
            rider = OnHitRider(**data)
            assert rider.trigger in (RiderTrigger.POST_HIT, RiderTrigger.AUTOMATIC)


# ── TurnResources integration ────────────────────────────────────────

class TestTurnResourcesRiders:
    def test_used_riders_starts_none(self):
        from arena.combat.manager import TurnResources
        tr = TurnResources()
        assert tr.used_riders is None

    def test_used_riders_resets_on_new_turn(self):
        from arena.combat.manager import TurnResources
        tr = TurnResources()
        tr.used_riders = {"Sneak Attack"}
        tr.reset_for_new_turn()
        assert tr.used_riders is None


# ── CombatManager integration tests ─────────────────────────────────

class TestManagerRiderIntegration:
    """Test that riders flow through the CombatManager correctly."""

    def _setup_combat(self, attacker, target):
        """Set up a simple combat scenario.

        Returns (manager, attacker_id, target_id) where IDs are the
        manager-generated creature IDs (based on creature name).
        """
        from pathlib import Path
        from arena.combat.manager import CombatManager
        from arena.models.encounter import Encounter, CombatantEntry

        encounter = Encounter(
            name="Test",
            map_width=10,
            map_height=10,
            combatants=[
                CombatantEntry(
                    creature_id="attacker",
                    creature_data=attacker,
                    team="player",
                    starting_position=(2, 2),
                ),
                CombatantEntry(
                    creature_id="target",
                    creature_data=target,
                    team="enemy",
                    starting_position=(3, 2),
                ),
            ],
        )
        manager = CombatManager()
        manager.load_encounter(encounter, Path("."))

        # Discover actual IDs (load_encounter generates from creature name)
        attacker_id = target_id = None
        for cid, c in manager.combatants.items():
            if c.team == "player":
                attacker_id = cid
            else:
                target_id = cid
        return manager, attacker_id, target_id

    def _start_attacker_turn(self, manager, attacker_id):
        """Navigate initiative to the attacker and start their turn."""
        for entry in manager.initiative.entries:
            if entry.creature_id == attacker_id:
                manager.initiative.current_index = (
                    manager.initiative.entries.index(entry)
                )
                break
        manager._start_current_turn()

    @patch("arena.combat.actions.roll_die")
    def test_complete_attack_with_rider_damage(self, mock_roll):
        """Rider damage is included in the attack."""
        mock_roll.return_value = 20  # Always hit
        pc = _make_paladin()
        target = _make_target()
        manager, att_id, tgt_id = self._setup_combat(pc, target)
        manager.roll_initiative()
        self._start_attacker_turn(manager, att_id)

        # Select longsword from the manager's combatant (not the original model)
        att_creature = manager.combatants[att_id].creature
        manager.select_action(att_creature.actions[0])

        # Phase 1: hit check
        hit_result = manager.execute_attack_hit_check(tgt_id)
        assert hit_result is not None
        assert hit_result.hit is True

        # Get riders
        riders = manager.get_applicable_riders(hit_result)
        assert len(riders) == 1  # Divine Smite

        # Create a smite result
        feature, rider = riders[0]
        tgt_creature = manager.combatants[tgt_id].creature
        rr = resolve_rider(feature, rider, att_creature, tgt_creature, slot_level=1)

        # Phase 2: complete with rider
        result = manager.complete_attack(hit_result, rider_results=[rr])
        assert result is not None
        assert result.success is True

        # Rider was tracked
        assert "Divine Smite" in (manager.turn_resources.used_riders or set())

    @patch("arena.combat.actions.roll_die")
    def test_complete_attack_no_riders(self, mock_roll):
        """Attack completes normally without riders."""
        mock_roll.return_value = 20
        pc = PlayerCharacter(
            name="Fighter", max_hit_points=40,
            character_class="Fighter",
            actions=[_melee_weapon_action()],
        )
        target = _make_target()
        manager, att_id, tgt_id = self._setup_combat(pc, target)
        manager.roll_initiative()
        self._start_attacker_turn(manager, att_id)

        att_creature = manager.combatants[att_id].creature
        manager.select_action(att_creature.actions[0])
        hit_result = manager.execute_attack_hit_check(tgt_id)
        assert hit_result is not None
        riders = manager.get_applicable_riders(hit_result)
        assert len(riders) == 0

        result = manager.complete_attack(hit_result)
        assert result is not None

    @patch("arena.combat.actions.roll_die")
    def test_miss_returns_no_riders(self, mock_roll):
        """On a miss, get_applicable_riders returns empty."""
        mock_roll.return_value = 1  # Miss
        pc = _make_paladin()
        target = Creature(
            name="Dragon", max_hit_points=200, armor_class=25,
        )
        manager, att_id, tgt_id = self._setup_combat(pc, target)
        manager.roll_initiative()
        self._start_attacker_turn(manager, att_id)

        att_creature = manager.combatants[att_id].creature
        manager.select_action(att_creature.actions[0])
        hit_result = manager.execute_attack_hit_check(tgt_id)
        if hit_result and not hit_result.hit:
            riders = manager.get_applicable_riders(hit_result)
            assert len(riders) == 0
