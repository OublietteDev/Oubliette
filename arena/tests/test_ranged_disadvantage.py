"""D-ACT-4 — ranged attacks: long range allowed at disadvantage, plus
disadvantage when a hostile is within 5 ft of the shooter.

Before: a ranged attack past range_normal was refused outright and there was no
in-melee penalty. Now is_in_range allows out to range_long, and
ranged_positional_disadvantage flags both the long-range band and an adjacent
action-capable foe.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena.combat.actions import (
    is_in_range,
    ranged_positional_disadvantage,
    resolve_attack_hit,
)
from arena.combat.conditions import apply_condition
from arena.combat.manager import CombatManager
from arena.grid.coordinates import HexCoord
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action,
    ActionType,
    Attack,
    DamageRoll,
    DamageType,
)
from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.models.encounter import CombatantEntry, Encounter


def _bow():
    return Action(
        name="Longbow", description="x", action_type=ActionType.ACTION,
        attack=Attack(
            name="Longbow", attack_type="ranged_weapon", ability="dexterity",
            range_normal=80, range_long=320,
            damage=[DamageRoll(dice="1d8", damage_type=DamageType.PIERCING)],
        ),
    )


def _sword():
    return Action(
        name="Sword", description="x", action_type=ActionType.ACTION,
        attack=Attack(
            name="Sword", attack_type="melee_weapon", ability="strength", reach=5,
            damage=[DamageRoll(dice="1d8", damage_type=DamageType.SLASHING)],
        ),
    )


def _creature(name, is_player=True):
    return Creature(
        name=name, max_hit_points=30, current_hit_points=30, armor_class=10,
        ability_scores=AbilityScores(), proficiency_bonus=2,
        is_player_controlled=is_player, actions=[],
    )


def _combatant(team, pos):
    return SimpleNamespace(team=team, position=pos, creature=_creature("X", team == "player"))


class TestRangeBand:
    def test_within_normal_range(self):
        assert is_in_range(HexCoord(0, 0), HexCoord(10, 0), _bow()) is True

    def test_within_long_range_now_allowed(self):
        # 20 hexes = 100 ft: past normal (80) but within long (320).
        assert is_in_range(HexCoord(0, 0), HexCoord(20, 0), _bow()) is True

    def test_beyond_long_range_refused(self):
        # 70 hexes = 350 ft: past long (320).
        assert is_in_range(HexCoord(0, 0), HexCoord(70, 0), _bow()) is False


class TestPositionalDisadvantage:
    def _combatants(self, archer_pos, *foes):
        cs = {"archer": SimpleNamespace(
            team="player", position=archer_pos, creature=_creature("Archer"))}
        for i, (pos, capable) in enumerate(foes):
            foe = _creature(f"Foe{i}", is_player=False)
            if not capable:
                apply_condition(foe, f"foe{i}", Condition.STUNNED, source="x")
            cs[f"foe{i}"] = SimpleNamespace(team="enemy", position=pos, creature=foe)
        return cs

    def test_normal_range_no_foe_is_clean(self):
        cs = self._combatants(HexCoord(0, 0))
        dis, reason = ranged_positional_disadvantage(
            HexCoord(0, 0), _creature("A").size,
            HexCoord(8, 0), _creature("T").size, _bow(), "archer", cs)
        assert dis is False and reason == ""

    def test_long_range_gives_disadvantage(self):
        cs = self._combatants(HexCoord(0, 0))
        dis, reason = ranged_positional_disadvantage(
            HexCoord(0, 0), _creature("A").size, HexCoord(20, 0),
            _creature("T").size, _bow(), "archer", cs)
        assert dis is True and "long range" in reason

    def test_adjacent_foe_gives_disadvantage(self):
        cs = self._combatants(HexCoord(0, 0), (HexCoord(1, 0), True))
        dis, reason = ranged_positional_disadvantage(
            HexCoord(0, 0), _creature("A").size, HexCoord(8, 0),
            _creature("T").size, _bow(), "archer", cs)
        assert dis is True and "foe within 5 ft" in reason

    def test_incapacitated_adjacent_foe_does_not_threaten(self):
        cs = self._combatants(HexCoord(0, 0), (HexCoord(1, 0), False))
        dis, reason = ranged_positional_disadvantage(
            HexCoord(0, 0), _creature("A").size, HexCoord(8, 0),
            _creature("T").size, _bow(), "archer", cs)
        assert dis is False

    def test_melee_attack_never_qualifies(self):
        cs = self._combatants(HexCoord(0, 0), (HexCoord(1, 0), True))
        dis, _ = ranged_positional_disadvantage(
            HexCoord(0, 0), _creature("A").size, HexCoord(1, 0),
            _creature("T").size, _sword(), "archer", cs)
        assert dis is False


class TestReachesTheRoll:
    """The disadvantage must actually reach resolve_attack_hit's roll."""

    def _scene(self, target_col, adj_foe=False):
        # Row 40 of an 80-tall grid: a horizontal LOS line drifts a hex or two
        # in axial space, so keep margin from the edges (off-grid hexes block LOS).
        archer = _creature("Archer")
        archer.actions = [_bow()]
        combatants = [
            CombatantEntry(creature_id="archer", creature_data=archer,
                           team="player", starting_position=(0, 40)),
            CombatantEntry(creature_id="dummy",
                           creature_data=_creature("Dummy", is_player=False),
                           team="enemy", starting_position=(target_col, 40)),
        ]
        if adj_foe:
            combatants.append(CombatantEntry(
                creature_id="adj", creature_data=_creature("Adj", is_player=False),
                team="enemy", starting_position=(1, 40)))
        enc = Encounter(name="rng", grid_width=80, grid_height=80,
                        combatants=combatants)
        cm = CombatManager()
        cm.load_encounter(enc, Path("."))
        return cm

    def _hit(self, cm, nat=10):
        a = cm.combatants["archer"]
        t = cm.combatants["dummy"]
        cm.selected_action = _bow()
        with patch("arena.combat.actions.roll_die", return_value=nat):
            return resolve_attack_hit(
                a.creature, "archer", t.creature, "dummy", _bow(), cm.grid,
                combatants=cm.combatants, attacker_pos=a.position,
                target_pos=t.position)

    def test_normal_range_no_foe_is_straight_roll(self):
        cm = self._scene(target_col=8)
        assert self._hit(cm).effective_advantage == 0

    def test_long_range_rolls_disadvantage(self):
        cm = self._scene(target_col=20)  # 100 ft > 80
        assert self._hit(cm).effective_advantage == -1

    def test_adjacent_foe_rolls_disadvantage(self):
        cm = self._scene(target_col=8, adj_foe=True)
        assert self._hit(cm).effective_advantage == -1
