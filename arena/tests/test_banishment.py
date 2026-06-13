"""C4f P-BANISH — removal from the battlefield.

The BANISHED condition takes a creature off the grid: the manager stashes
its hex, the renderer/AoE/AI all skip position=None, its turns are skipped,
and can_take_actions blocks reactions and legendary actions. The
_reconcile_banishment sweep returns it — at the stashed hex or the nearest
free one — whenever the condition ends: a re-save (Maze), round expiry
(Blink), or concentration cleanup (Banishment, Resilient Sphere). A
banished creature with NO path back (Plane Shift's offensive use: no
re-save, no concentration) counts as defeated for victory.
"""

from pathlib import Path
from unittest.mock import patch

from arena.combat.condition_effects import can_take_actions
from arena.combat.conditions import has_condition
from arena.combat.concentration import end_concentration
from arena.combat.manager import CombatManager
from arena.grid.coordinates import HexCoord
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action,
    ActionType,
    DamageRoll,
    DamageType,
    SavingThrowEffect,
    TargetType,
)
from arena.models.character import Creature
from arena.models.conditions import (
    ActiveBuff,
    AppliedCondition,
    BuffEffect,
    Condition,
)
from arena.models.encounter import CombatantEntry, Encounter


def _creature(name="Pip", hp=40, is_player=True):
    return Creature(
        name=name,
        max_hit_points=hp,
        current_hit_points=hp,
        armor_class=12,
        ability_scores=AbilityScores(),
        proficiency_bonus=2,
        is_player_controlled=is_player,
        actions=[],
    )


def _banishment(concentration=True, no_resave=True, ability="charisma"):
    """Banishment-shaped action: save or off the battlefield."""
    return Action(
        name="Banishment", description="Send a creature to another plane.",
        action_type=ActionType.ACTION, target_type=TargetType.ONE_CREATURE,
        range=60, spell_level=4,
        requires_concentration=concentration,
        saving_throw=SavingThrowEffect(
            ability=ability, dc=15,
            conditions_on_fail=["banished"],
            conditions_no_resave=no_resave,
        ),
    )


def _maze():
    """Maze-shaped action: no save on cast, DC 20 INT re-save to escape."""
    return Action(
        name="Maze", description="Banish into a labyrinthine demiplane.",
        action_type=ActionType.ACTION, target_type=TargetType.ONE_CREATURE,
        range=60, spell_level=8,
        requires_concentration=True,
        conditions_applied=["banished"],
        condition_duration_type="end_of_turn",
        condition_save_to_end="intelligence",
        condition_save_to_end_dc=20,
    )


def _fireburst():
    return Action(
        name="Burst", description="A damaging burst",
        action_type=ActionType.ACTION, target_type=TargetType.AREA_SPHERE,
        range=30, area_size=15, spell_level=3,
        saving_throw=SavingThrowEffect(
            ability="dexterity", dc=15,
            damage_on_fail=[DamageRoll(dice="2d6", damage_type=DamageType.FIRE)],
            damage_on_success="half",
        ),
    )


def _duel(enemy_count=1):
    """Caster vs enemy(-ies); caster wins initiative."""
    combatants = [
        CombatantEntry(creature_id="caster", creature_data=_creature("Caster"),
                       team="player", starting_position=(4, 4)),
    ]
    for i in range(enemy_count):
        combatants.append(CombatantEntry(
            creature_id=f"brute{i}",
            creature_data=_creature(f"Brute{i}", is_player=False),
            team="enemy", starting_position=(4 + i, 6),
        ))
    encounter = Encounter(
        name="Banish", grid_width=10, grid_height=10, combatants=combatants,
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    rolls = [20] + [10 - i for i in range(enemy_count)]
    with patch("arena.combat.manager.roll_die", side_effect=rolls):
        cm.roll_initiative()
    cm.begin_combat()
    return cm


def _cast(cm, action, target_id, save_roll):
    """Cast the action as the active combatant, with a forced target save."""
    cm.selected_action = action
    with patch("arena.combat.actions.roll_die", return_value=save_roll):
        return cm.execute_effect(target_id)


class TestBanishOut:
    def test_failed_save_takes_creature_off_grid(self):
        cm = _duel()
        old_pos = cm.combatants["brute0"].position
        _cast(cm, _banishment(), "brute0", save_roll=1)

        brute = cm.combatants["brute0"]
        assert has_condition(brute.creature, Condition.BANISHED)
        assert brute.position is None
        assert cm.banished_positions["brute0"] == old_pos
        # the grid hex is actually free again
        assert cm.grid.get_cell(old_pos).occupant_id is None

    def test_successful_save_resists(self):
        cm = _duel()
        _cast(cm, _banishment(), "brute0", save_roll=20)
        brute = cm.combatants["brute0"]
        assert not has_condition(brute.creature, Condition.BANISHED)
        assert brute.position is not None

    def test_no_resave_condition_has_no_escape_roll(self):
        cm = _duel()
        _cast(cm, _banishment(), "brute0", save_roll=1)
        cond = next(
            ac for ac in cm.combatants["brute0"].creature.active_conditions
            if ac.condition == Condition.BANISHED
        )
        assert cond.save_to_end is None
        assert cond.duration_type == "indefinite"

    def test_banished_creature_is_untargetable_by_aoe(self):
        cm = _duel(enemy_count=2)
        _cast(cm, _banishment(), "brute0", save_roll=1)
        caster = cm.combatants["caster"]
        affected = cm._resolve_effect_targets(_fireburst(), caster, "brute1")
        assert "brute0" not in affected
        assert "brute1" in affected

    def test_banished_creature_cannot_act(self):
        c = _creature()
        c.active_conditions.append(
            AppliedCondition(condition=Condition.BANISHED, source="Banishment")
        )
        assert can_take_actions(c) is False

    def test_banished_turn_is_skipped(self):
        cm = _duel()
        _cast(cm, _banishment(), "brute0", save_roll=1)
        # caster ends turn -> brute's turn auto-skips -> back to caster
        with patch("arena.combat.actions.roll_die", return_value=1):
            cm.end_turn()
        assert cm.active_combatant.creature_id == "caster"
        messages = [e.message for e in cm.log.events]
        assert any("banished from the battlefield" in m for m in messages)


class TestReturn:
    def test_concentration_break_returns_creature_at_stashed_hex(self):
        cm = _duel()
        old_pos = cm.combatants["brute0"].position
        _cast(cm, _banishment(), "brute0", save_roll=1)

        caster = cm.combatants["caster"]
        end_concentration(caster.creature, "caster", cm.combatants)
        cm._reconcile_banishment()

        brute = cm.combatants["brute0"]
        assert not has_condition(brute.creature, Condition.BANISHED)
        assert brute.position == old_pos
        assert cm.grid.get_cell(old_pos).occupant_id == "brute0"
        assert "brute0" not in cm.banished_positions

    def test_occupied_stash_hex_returns_to_nearest_free(self):
        cm = _duel(enemy_count=2)
        old_pos = cm.combatants["brute0"].position
        _cast(cm, _banishment(), "brute0", save_roll=1)

        # someone moves onto the vacated hex while brute0 is away
        squatter = cm.combatants["brute1"]
        cm.grid.remove_creature(squatter.position, squatter.creature.size)
        cm.grid.place_creature(old_pos, "brute1", squatter.creature.size)
        squatter.position = old_pos

        caster = cm.combatants["caster"]
        end_concentration(caster.creature, "caster", cm.combatants)
        cm._reconcile_banishment()

        brute = cm.combatants["brute0"]
        assert brute.position is not None
        assert brute.position != old_pos
        assert brute.position in old_pos.neighbors()

    def test_maze_escape_resave_returns_creature(self):
        cm = _duel()
        old_pos = cm.combatants["brute0"].position
        _cast(cm, _maze(), "brute0", save_roll=1)
        brute = cm.combatants["brute0"]
        assert has_condition(brute.creature, Condition.BANISHED)
        assert brute.position is None

        # caster ends turn; brute's skipped turn still rolls the DC 20
        # INT re-save at end of turn — force a 20: they escape the maze
        with patch("arena.combat.actions.roll_die", return_value=20):
            cm.end_turn()

        assert not has_condition(brute.creature, Condition.BANISHED)
        assert brute.position == old_pos


class TestBlink:
    def _give_blink(self, cm):
        cm.combatants["caster"].creature.active_buffs.append(ActiveBuff(
            name="Blink", source_id="caster",
            modifiers=[BuffEffect(stat="blink", modifier_type="flat_bonus",
                                  value=11)],
            duration_type="rounds", duration_rounds=10,
        ))

    def test_high_roll_blinks_out_and_returns_on_own_turn(self):
        cm = _duel()
        self._give_blink(cm)
        caster = cm.combatants["caster"]
        home = caster.position

        # end of caster's turn: d20 -> 20, blinks out
        with patch("arena.combat.manager.roll_die", return_value=20), \
                patch("arena.combat.actions.roll_die", return_value=10):
            cm.end_turn()

        assert cm.active_combatant.creature_id == "brute0"
        assert has_condition(caster.creature, Condition.BANISHED)
        assert caster.position is None

        # enemy's turn ends; caster returns at the start of their own turn
        # (roll low so Blink does not immediately re-trigger this round)
        with patch("arena.combat.manager.roll_die", return_value=1), \
                patch("arena.combat.actions.roll_die", return_value=10):
            cm.end_turn()

        assert cm.active_combatant.creature_id == "caster"
        assert not has_condition(caster.creature, Condition.BANISHED)
        assert caster.position == home
        assert cm.turn_phase.name == "AWAITING_ACTION"

    def test_low_roll_stays_on_plane(self):
        cm = _duel()
        self._give_blink(cm)
        caster = cm.combatants["caster"]
        with patch("arena.combat.manager.roll_die", return_value=10), \
                patch("arena.combat.actions.roll_die", return_value=10):
            cm.end_turn()
        assert not has_condition(caster.creature, Condition.BANISHED)
        assert caster.position is not None


class TestVictory:
    def test_permanent_banish_counts_as_defeated(self):
        cm = _duel()
        # Plane Shift's offensive shape: no concentration, no re-save
        _cast(cm, _banishment(concentration=False), "brute0", save_roll=1)
        assert cm.winner == "player"

    def test_concentration_banish_does_not_end_the_fight(self):
        cm = _duel()
        _cast(cm, _banishment(concentration=True), "brute0", save_roll=1)
        assert cm.winner is None
