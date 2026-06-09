"""Tests for counterspell wiring into CombatManager.

Verifies that creatures with Counterspell can use their reaction to
interrupt enemy spell casts through execute_effect() and execute_attack().
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action, Attack, DamageRoll, DamageType, ActionType, SavingThrowEffect,
)
from arena.models.character import Creature, PlayerCharacter
from arena.models.encounter import Encounter, CombatantEntry


# ── Action factories ─────────────────────────────────────────────────

_CS_ACTION = Action(
    name="Counterspell",
    description="Counter a spell being cast.",
    action_type=ActionType.REACTION,
    is_counterspell=True,
    spell_level=3,
    counterspell_auto_level=None,
    counterspell_check_dc_base=10,
    range=60,
    resource_cost={"spell_slot_3": 1},
)

_FIREBALL = Action(
    name="Fireball",
    description="8d6 fire damage, DEX save for half",
    action_type=ActionType.ACTION,
    target_type="one_creature",
    range=150,
    spell_level=3,
    saving_throw=SavingThrowEffect(
        ability="dexterity",
        dc=15,
        damage_on_fail=[DamageRoll(dice="8d6", damage_type=DamageType.FIRE)],
        damage_on_success="half",
    ),
    resource_cost={"spell_slot_3": 1},
)

_CONE_OF_COLD = Action(
    name="Cone of Cold",
    description="8d8 cold damage, CON save for half",
    action_type=ActionType.ACTION,
    target_type="one_creature",
    range=60,
    spell_level=5,
    saving_throw=SavingThrowEffect(
        ability="constitution",
        dc=17,
        damage_on_fail=[DamageRoll(dice="8d8", damage_type=DamageType.COLD)],
        damage_on_success="half",
    ),
    resource_cost={"spell_slot_5": 1},
)

_LONGSWORD = Action(
    name="Longsword",
    description="Melee weapon attack",
    action_type=ActionType.ACTION,
    attack=Attack(
        name="Longsword",
        attack_type="melee_weapon",
        ability="strength",
        reach=5,
        damage=[DamageRoll(dice="1d8", damage_type=DamageType.SLASHING,
                           ability_modifier="strength")],
    ),
)

_SCORCHING_RAY = Action(
    name="Scorching Ray",
    description="Ranged spell attack",
    action_type=ActionType.ACTION,
    spell_level=2,
    range=120,
    attack=Attack(
        name="Scorching Ray",
        attack_type="ranged_spell",
        ability="intelligence",
        reach=120,
        damage=[DamageRoll(dice="2d6", damage_type=DamageType.FIRE)],
    ),
    resource_cost={"spell_slot_2": 1},
)


# ── Setup ────────────────────────────────────────────────────────────


def _setup(
    cs_is_player=False,
    caster_actions=None,
    cs_slots=None,
    caster_pos=(2, 2),
    cs_pos=(4, 2),
    target_pos=(3, 2),
    cs_team="player",
):
    """Build a 3-creature combat (enemy caster, counterspeller, target).

    Returns (manager, caster_id, cs_id, target_id) with the caster's
    turn active.
    """
    # Use PlayerCharacter so class_resources field is available
    caster = PlayerCharacter(
        name="Evil Mage",
        max_hit_points=50,
        armor_class=12,
        ability_scores=AbilityScores(intelligence=18, wisdom=16),
        proficiency_bonus=4,
        is_player_controlled=False,
        character_class="Wizard",
        level=9,
        actions=caster_actions or [_FIREBALL, _LONGSWORD],
        class_resources={"spell_slot_2": 3, "spell_slot_3": 3, "spell_slot_5": 1},
    )

    # Always use PlayerCharacter so class_resources is available
    cs_creature = PlayerCharacter(
        name="Abjurer",
        max_hit_points=60,
        armor_class=15,
        ability_scores=AbilityScores(intelligence=18, wisdom=14),
        proficiency_bonus=4,
        is_player_controlled=cs_is_player,
        character_class="Wizard",
        level=9,
        spellcasting_ability="intelligence",
        actions=[_CS_ACTION, _LONGSWORD],
        class_resources=cs_slots or {
            "spell_slot_3": 3, "spell_slot_4": 2, "spell_slot_5": 1,
        },
    )

    target = PlayerCharacter(
        name="Fighter",
        max_hit_points=80,
        armor_class=18,
        ability_scores=AbilityScores(strength=16, dexterity=14, constitution=14),
        proficiency_bonus=4,
        is_player_controlled=True,
        character_class="Fighter",
        level=9,
        actions=[_LONGSWORD],
    )

    encounter = Encounter(
        name="CS Test",
        grid_width=20,
        grid_height=20,
        combatants=[
            CombatantEntry(
                creature_id="caster", creature_data=caster,
                team="enemy", starting_position=caster_pos,
            ),
            CombatantEntry(
                creature_id="cs", creature_data=cs_creature,
                team=cs_team, starting_position=cs_pos,
            ),
            CombatantEntry(
                creature_id="target", creature_data=target,
                team="player", starting_position=target_pos,
            ),
        ],
    )

    mgr = CombatManager()
    mgr.load_encounter(encounter, Path("."))
    mgr.roll_initiative()
    mgr.begin_combat()

    # Map display names -> IDs
    ids = {}
    for cid, c in mgr.combatants.items():
        if c.creature.name == "Evil Mage":
            ids["caster"] = cid
        elif c.creature.name == "Abjurer":
            ids["cs"] = cid
        elif c.creature.name == "Fighter":
            ids["target"] = cid

    caster_id = ids["caster"]

    # Advance to caster's turn
    for _ in range(4):
        ac = mgr.active_combatant
        if ac and ac.creature_id == caster_id:
            break
        mgr.end_turn()

    assert mgr.active_combatant.creature_id == caster_id
    return mgr, ids["caster"], ids["cs"], ids["target"]


def _c(mgr, cid):
    """Shortcut to get the creature object for a combatant ID."""
    return mgr.combatants[cid].creature


# ── Tests ────────────────────────────────────────────────────────────


class TestAICounterspellEffect:
    """AI counterspeller interrupts enemy spell via execute_effect."""

    def test_auto_counter_same_level(self):
        mgr, cast, cs, tgt = _setup()
        mgr.select_action(_c(mgr, cast).actions[0])  # Fireball
        hp_before = _c(mgr, tgt).current_hit_points
        result = mgr.execute_effect(tgt)

        assert result is not None and result.success is False
        assert mgr.reaction_used.get(cs, False) is True
        assert _c(mgr, tgt).current_hit_points == hp_before
        assert _c(mgr, cs).class_resources["spell_slot_3"] == 2
        msgs = [e.message for e in mgr.log.events]
        assert any("Counterspell" in m for m in msgs)

    @patch("arena.combat.counterspell.roll_die")
    def test_fails_ability_check(self, mock_roll):
        mock_roll.return_value = 1
        mgr, cast, cs, tgt = _setup(
            caster_actions=[_CONE_OF_COLD, _LONGSWORD],
            cs_slots={"spell_slot_3": 2},
        )
        mgr.select_action(_c(mgr, cast).actions[0])
        result = mgr.execute_effect(tgt)

        assert mgr.reaction_used.get(cs, False) is True
        assert result is not None  # spell goes through
        assert _c(mgr, cs).class_resources["spell_slot_3"] == 1

    def test_uses_matching_slot(self):
        mgr, cast, cs, tgt = _setup(
            caster_actions=[_CONE_OF_COLD, _LONGSWORD],
        )
        mgr.select_action(_c(mgr, cast).actions[0])
        result = mgr.execute_effect(tgt)

        assert result is not None and result.success is False
        assert _c(mgr, cs).class_resources["spell_slot_5"] == 0


class TestNoCounterspellOnNonSpell:

    def test_melee_no_counterspell(self):
        mgr, cast, cs, tgt = _setup()
        mgr.select_action(_c(mgr, cast).actions[1])  # Longsword
        mgr.execute_attack(tgt)

        assert mgr.reaction_used.get(cs, False) is False
        assert _c(mgr, cs).class_resources["spell_slot_3"] == 3


class TestReactionAvailability:

    def test_reaction_already_used(self):
        mgr, cast, cs, tgt = _setup()
        mgr.reaction_used[cs] = True

        mgr.select_action(_c(mgr, cast).actions[0])
        mgr.execute_effect(tgt)

        assert _c(mgr, cs).class_resources["spell_slot_3"] == 3


class TestRangeCheck:

    def test_out_of_range(self):
        mgr, cast, cs, tgt = _setup(
            caster_pos=(2, 2), cs_pos=(16, 2), target_pos=(3, 2),
        )
        mgr.select_action(_c(mgr, cast).actions[0])
        mgr.execute_effect(tgt)

        assert mgr.reaction_used.get(cs, False) is False


class TestCantripCounterspell:

    def test_cantrip_counterable(self):
        cantrip = Action(
            name="Sacred Flame",
            description="DEX save",
            action_type=ActionType.ACTION,
            spell_level=0,
            target_type="one_creature",
            range=60,
            saving_throw=SavingThrowEffect(
                ability="dexterity", dc=15,
                damage_on_fail=[DamageRoll(dice="2d8", damage_type=DamageType.RADIANT)],
            ),
        )
        mgr, cast, cs, tgt = _setup(caster_actions=[cantrip, _LONGSWORD])
        mgr.select_action(_c(mgr, cast).actions[0])
        result = mgr.execute_effect(tgt)

        assert result is not None and result.success is False
        assert mgr.reaction_used.get(cs, False) is True


class TestSpellSlotRequired:

    def test_no_slots(self):
        mgr, cast, cs, tgt = _setup(cs_slots={"no_resource": 0})
        # Confirm the counterspeller has no spell slots
        cs_c = _c(mgr, cs)
        assert cs_c.class_resources.get("spell_slot_3", 0) == 0

        mgr.select_action(_c(mgr, cast).actions[0])
        mgr.execute_effect(tgt)

        assert mgr.reaction_used.get(cs, False) is False


class TestPlayerCounterspell:

    def test_sets_pending(self):
        mgr, cast, cs, tgt = _setup(cs_is_player=True)
        mgr.select_action(_c(mgr, cast).actions[0])
        result = mgr.execute_effect(tgt)

        assert result is None
        assert mgr._pending_counterspell is not None
        assert mgr._pending_counterspell["method"] == "effect"

    def test_resolve_success(self):
        mgr, cast, cs, tgt = _setup(cs_is_player=True)
        mgr.select_action(_c(mgr, cast).actions[0])
        mgr.execute_effect(tgt)

        countered, _ = mgr.resolve_counterspell_choice(cs, cast_level=3)
        assert countered is True
        assert mgr.reaction_used.get(cs, False) is True
        assert _c(mgr, cs).class_resources["spell_slot_3"] == 2

    def test_resolve_skip(self):
        mgr, cast, cs, tgt = _setup(cs_is_player=True)
        mgr.select_action(_c(mgr, cast).actions[0])
        mgr.execute_effect(tgt)

        countered, _ = mgr.resolve_counterspell_choice(None, None)
        assert countered is False
        assert mgr.reaction_used.get(cs, False) is False
        assert _c(mgr, cs).class_resources["spell_slot_3"] == 3


class TestCounterspellOnAttack:

    def test_spell_attack_countered(self):
        mgr, cast, cs, tgt = _setup(
            caster_actions=[_SCORCHING_RAY, _LONGSWORD],
        )
        mgr.select_action(_c(mgr, cast).actions[0])
        result = mgr.execute_attack(tgt)

        assert result is not None and result.success is False
        assert mgr.reaction_used.get(cs, False) is True


class TestCasterSlotConsumed:

    def test_slot_consumed_on_counter(self):
        mgr, cast, cs, tgt = _setup()
        initial = _c(mgr, cast).class_resources["spell_slot_3"]
        mgr.select_action(_c(mgr, cast).actions[0])
        result = mgr.execute_effect(tgt)

        assert result.success is False
        assert _c(mgr, cast).class_resources["spell_slot_3"] == initial - 1


class TestSameTeamNoCounterspell:

    def test_same_team(self):
        mgr, cast, cs, tgt = _setup(cs_team="enemy")
        mgr.select_action(_c(mgr, cast).actions[0])
        mgr.execute_effect(tgt)

        assert mgr.reaction_used.get(cs, False) is False
