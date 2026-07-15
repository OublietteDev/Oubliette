"""Destructible walls (SRD gap-fill): attack a spell-wall panel or an authored
terrain wall that the battlefield gave hit points; broken walls open paths.
Object rules kept simple — a wall doesn't dodge (auto-hit, no crit) and poison/
psychic damage does nothing to it."""

from pathlib import Path

import pytest

from arena.combat import house_rules as hr
from arena.combat.manager import CombatManager
from arena.combat.wall_spells import ActiveWall, WallPanel
from arena.grid.coordinates import HexCoord
from arena.models.abilities import AbilityScores
from arena.models.actions import (Action, ActionType, Attack, DamageRoll,
                                  DamageType)
from arena.models.character import PlayerCharacter
from arena.models.encounter import (CombatantEntry, Encounter, TerrainHex,
                                    TerrainType)


@pytest.fixture(autouse=True)
def _clean_rules():
    hr.reset()
    yield
    hr.reset()


def _pc() -> PlayerCharacter:
    return PlayerCharacter(name="Basher", character_class="Fighter",
                           max_hit_points=20, proficiency_bonus=2,
                           ability_scores=AbilityScores(strength=16),
                           is_player_controlled=True)


def _swing(dice: str = "1d4", bonus: int = 20,
           dtype: DamageType = DamageType.BLUDGEONING) -> Action:
    return Action(
        name="Maul", description="melee", action_type=ActionType.ACTION,
        attack=Attack(name="Maul", attack_type="melee_weapon",
                      ability="strength", reach=5,
                      damage=[DamageRoll(dice=dice, damage_type=dtype,
                                         bonus=bonus)]),
    )


def _manager(wall_hp: int | None = 10) -> tuple[CombatManager, str]:
    extra = {"hp": wall_hp} if wall_hp else {}
    enc = Encounter(
        name="t",
        terrain=[TerrainHex(position=(6, 5), terrain_type=TerrainType.WALL,
                            extra_data=extra)],
        combatants=[
            CombatantEntry(creature_id="inline", team="player",
                           creature_data=_pc(), starting_position=(5, 5)),
        ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    cid = next(iter(cm.combatants))
    return cm, cid


# --- authored terrain walls -----------------------------------------------------

def test_wall_hp_loads_and_scenery_walls_stay_untargetable():
    cm, _ = _manager(wall_hp=10)
    assert cm.terrain_wall_hp == {(6, 5): 10}
    assert cm.wall_target_at(HexCoord(6, 5)) == {"kind": "terrain", "key": (6, 5)}
    plain, _ = _manager(wall_hp=None)
    assert plain.terrain_wall_hp == {}
    assert plain.wall_target_at(HexCoord(6, 5)) is None   # permanent scenery


def test_smashing_a_terrain_wall_opens_the_hex():
    cm, cid = _manager(wall_hp=10)
    wall_hex = HexCoord(6, 5)
    assert cm.grid.is_passable(wall_hex) is False
    assert cm.attack_wall(cid, wall_hex, _swing()) is True   # 1d4+20 ≥ 10
    assert cm.terrain_wall_hp == {}
    assert cm.grid.is_passable(wall_hex) is True             # the way is open
    assert any("CRUMBLES" in ev.message for ev in cm.log.events)
    assert cm.turn_resources.has_used_action is True         # the swing cost an action


def test_a_battered_wall_holds_until_its_hp_runs_out():
    cm, cid = _manager(wall_hp=50)
    cm.attack_wall(cid, HexCoord(6, 5), _swing())            # ≤ 24 damage
    assert (6, 5) in cm.terrain_wall_hp
    assert cm.terrain_wall_hp[(6, 5)] >= 26
    assert cm.grid.is_passable(HexCoord(6, 5)) is False


def test_poison_does_nothing_to_a_wall():
    cm, cid = _manager(wall_hp=10)
    cm.attack_wall(cid, HexCoord(6, 5), _swing(dtype=DamageType.POISON))
    assert cm.terrain_wall_hp == {(6, 5): 10}                # unmoved


# --- spell-wall panels -----------------------------------------------------------

def test_smashing_a_spell_wall_panel_clears_its_hexes():
    cm, cid = _manager(wall_hp=None)
    panel_hex = HexCoord(8, 5)
    wall = ActiveWall(name="Wall of Stone", source_id="caster",
                      panels=[WallPanel(hexes=[panel_hex], max_hp=10,
                                        current_hp=10)])
    cm.active_walls.append(wall)
    assert cm.wall_target_at(panel_hex) == {"kind": "spell", "wall": wall,
                                            "panel": 0}
    assert cm.attack_wall(cid, panel_hex, _swing()) is True
    assert wall.panels[0].is_destroyed
    assert panel_hex not in wall.get_wall_hexes()            # LOS/paths open
    assert any("SHATTERS" in ev.message for ev in cm.log.events)


def test_an_indestructible_spell_wall_is_no_target():
    cm, _ = _manager(wall_hp=None)
    force_hex = HexCoord(9, 5)
    cm.active_walls.append(ActiveWall(
        name="Wall of Force", source_id="caster",
        panels=[WallPanel(hexes=[force_hex], max_hp=None)]))
    assert cm.wall_target_at(force_hex) is None              # Wall of Force laughs
