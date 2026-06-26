"""D-COND-2 — exhaustion levels have mechanical effects.

RAW cumulative tiers (L1 ability-check disadvantage is intentionally not wired —
see condition_effects): L2 speed halved, L3 disadvantage on attacks and saves,
L4 hit-point maximum halved, L5 speed 0, L6 death (rendered as 0 HP).
"""

from pathlib import Path

from unittest.mock import patch

from arena.combat.conditions import apply_condition
from arena.combat.condition_effects import (
    effective_max_hp,
    exhaustion_level,
    get_attack_advantage,
    get_movement_multiplier,
    get_save_advantage,
)
from arena.combat.damage import apply_healing
from arena.combat.manager import CombatManager
from arena.combat.stat_modifiers import get_effective_speed
from arena.models.abilities import AbilityScores
from arena.models.character import Creature
from arena.models.conditions import AppliedCondition, Condition
from arena.models.encounter import CombatantEntry, Encounter


def _creature(name="Weary", hp=40, is_player=True):
    return Creature(
        name=name,
        max_hit_points=hp,
        current_hit_points=hp,
        armor_class=10,
        ability_scores=AbilityScores(),
        proficiency_bonus=2,
        is_player_controlled=is_player,
        actions=[],
    )


def _with_exhaustion(level):
    c = _creature()
    if level > 0:
        c.active_conditions.append(
            AppliedCondition(condition=Condition.EXHAUSTION, source="fatigue",
                             level=level)
        )
    return c


class TestQueries:
    def test_exhaustion_level_reads_applied_level(self):
        assert exhaustion_level(_with_exhaustion(0)) == 0
        assert exhaustion_level(_with_exhaustion(3)) == 3

    def test_speed_multiplier_by_tier(self):
        assert get_movement_multiplier(_with_exhaustion(1)) == 1.0
        assert get_movement_multiplier(_with_exhaustion(2)) == 0.5
        assert get_movement_multiplier(_with_exhaustion(4)) == 0.5
        assert get_movement_multiplier(_with_exhaustion(5)) == 0.0
        assert get_movement_multiplier(_with_exhaustion(6)) == 0.0

    def test_attack_disadvantage_at_level_3(self):
        target = _creature("Target")
        assert get_attack_advantage(_with_exhaustion(2), target) == 0
        assert get_attack_advantage(_with_exhaustion(3), target) == -1

    def test_save_disadvantage_at_level_3(self):
        assert get_save_advantage(_with_exhaustion(2), "wisdom") == 0
        assert get_save_advantage(_with_exhaustion(3), "wisdom") == -1
        assert get_save_advantage(_with_exhaustion(3), "strength") == -1

    def test_effective_max_hp_halved_at_level_4(self):
        assert effective_max_hp(_with_exhaustion(3)) == 40
        assert effective_max_hp(_with_exhaustion(4)) == 20


class TestSideEffects:
    def _stack_to(self, creature, level):
        for _ in range(level):
            apply_condition(creature, "c", Condition.EXHAUSTION, source="fatigue")

    def test_reaching_level_4_caps_current_hp(self):
        c = _creature(hp=40)
        self._stack_to(c, 4)
        assert exhaustion_level(c) == 4
        assert c.current_hit_points == 20  # capped to the halved maximum

    def test_reaching_level_6_drops_to_zero(self):
        c = _creature(hp=40)
        self._stack_to(c, 6)
        assert exhaustion_level(c) == 6
        assert c.current_hit_points == 0
        assert not c.is_conscious

    def test_healing_capped_at_halved_max(self):
        c = _creature(hp=40)
        self._stack_to(c, 4)  # current now 20, eff max 20
        c.current_hit_points = 5
        apply_healing(c, 100)
        assert c.current_hit_points == 20  # can't exceed the halved maximum


class TestReachesRealPlay:
    def test_turn_start_budget_is_halved_at_level_2(self):
        victim = _creature("Victim")
        combatants = [
            CombatantEntry(creature_id="victim", creature_data=victim,
                           team="player", starting_position=(4, 4)),
            CombatantEntry(creature_id="foe",
                           creature_data=_creature("Foe", is_player=False),
                           team="enemy", starting_position=(4, 6)),
        ]
        encounter = Encounter(name="Exh", grid_width=10, grid_height=10,
                              combatants=combatants)
        cm = CombatManager()
        cm.load_encounter(encounter, Path("."))
        # Exhaust the victim before the fight starts.
        cm.combatants["victim"].creature.active_conditions.append(
            AppliedCondition(condition=Condition.EXHAUSTION, source="fatigue",
                             level=2)
        )
        with patch("arena.combat.manager.roll_die", side_effect=[20, 5]):
            cm.roll_initiative()
        cm.begin_combat()
        assert cm.active_combatant.creature_id == "victim"
        full = get_effective_speed(victim)
        assert cm.movement.remaining_movement == int(full * 0.5)
