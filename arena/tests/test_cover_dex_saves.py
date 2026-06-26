"""D-ACT-3 — cover grants its +2/+5 to DEX saves, not just AC.

A creature behind half/three-quarters cover (relative to the effect's point of
origin) adds +2/+5 to a Dexterity saving throw, the same bonus cover gives AC.
resolve_saving_throw takes a cover_bonus; resolve_effect computes it from the
terrain between the effect origin and the target for DEX saves only.
"""

from arena.combat.actions import resolve_effect, resolve_saving_throw
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.grid.line_of_sight import hex_line
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
from arena.models.encounter import TerrainType
from unittest.mock import patch


def _creature(name="Pip"):
    return Creature(
        name=name, max_hit_points=30, current_hit_points=30, armor_class=10,
        ability_scores=AbilityScores(), proficiency_bonus=2, actions=[],
    )


def _save_action(ability="dexterity"):
    return Action(
        name="Blast", description="x", action_type=ActionType.ACTION,
        target_type=TargetType.AREA_SPHERE, range=150, area_size=20, spell_level=3,
        saving_throw=SavingThrowEffect(
            ability=ability, dc=15,
            damage_on_fail=[DamageRoll(dice="2d6", damage_type=DamageType.FIRE)],
            damage_on_success="half",
        ),
    )


def _save_modifier(events):
    for e in events:
        if e.details.get("ability") is not None and "modifier" in e.details:
            return e.details["modifier"]
    raise AssertionError("no saving-throw event found")


class TestResolveSavingThrowCoverBonus:
    def test_cover_bonus_raises_modifier(self):
        with patch("arena.combat.actions.roll_die", return_value=10):
            _, base = resolve_saving_throw(_creature(), "p", "dexterity", 15)
            _, with_cover = resolve_saving_throw(
                _creature(), "p", "dexterity", 15, cover_bonus=2)
        assert with_cover.details["modifier"] - base.details["modifier"] == 2
        assert "[cover: +2]" in with_cover.message


class TestResolveEffectComputesCover:
    def _grid_with_cover(self, origin, target, terrain):
        grid = HexGrid(80, 80)
        for coord in hex_line(origin, target)[1:-1]:
            cell = grid.get_cell(coord)
            if cell is not None:
                cell.terrain = terrain
        return grid

    def _resolve(self, ability, terrain=None):
        origin, target_pos = HexCoord(0, 40), HexCoord(6, 40)
        grid = (self._grid_with_cover(origin, target_pos, terrain)
                if terrain else HexGrid(80, 80))
        caster, target = _creature("Caster"), _creature("Target")
        with patch("arena.combat.actions.roll_die", return_value=10):
            res = resolve_effect(
                caster, "c", target, "t", _save_action(ability), grid,
                user_pos=origin, target_pos=target_pos, effect_origin=origin,
            )
        return _save_modifier(res.events)

    def test_half_cover_adds_two_to_dex_save(self):
        assert self._resolve("dexterity", TerrainType.COVER_HALF) - \
            self._resolve("dexterity") == 2

    def test_three_quarters_cover_adds_five_to_dex_save(self):
        assert self._resolve("dexterity", TerrainType.COVER_THREE_QUARTERS) - \
            self._resolve("dexterity") == 5

    def test_cover_does_not_help_non_dex_saves(self):
        # A CON save (e.g. Cloudkill) gets no cover benefit.
        assert self._resolve("constitution", TerrainType.COVER_THREE_QUARTERS) == \
            self._resolve("constitution")
