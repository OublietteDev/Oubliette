"""Tests for the Ready action popup's filter + two-stage selection (D-ACT-1)."""

from __future__ import annotations

import pygame
import pytest

from arena.gui.ready_popup import (
    ReadyPopup, is_readyable, readyable_actions, _TRIGGERS,
)
from arena.combat.ready_action import TriggerType
from arena.models.actions import (
    Action, ActionType, Attack, DamageRoll, DamageType,
    SavingThrowEffect, TargetType,
)


@pytest.fixture(autouse=True)
def init_pygame():
    pygame.init()
    pygame.display.set_mode((1, 1))
    yield
    pygame.quit()


def _attack_action():
    return Action(
        name="Sword", description="", action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        attack=Attack(name="Sword", attack_type="melee_weapon",
                      ability="strength", reach=5,
                      damage=[DamageRoll(dice="1d6",
                                         damage_type=DamageType.SLASHING)]),
    )


def _single_target_save_spell():
    return Action(
        name="Hold Person", description="", action_type=ActionType.ACTION,
        spell_level=2, target_type=TargetType.ONE_CREATURE, range=60,
        saving_throw=SavingThrowEffect(ability="wisdom", dc=14,
                                       conditions_on_fail=["paralyzed"]),
    )


def _fireball():
    """A placed radius burst — readyable (releases centered on the trigger)."""
    return Action(
        name="Fireball", description="", action_type=ActionType.ACTION,
        spell_level=3, target_type=TargetType.AREA_SPHERE, range=150,
        area_size=20,
        saving_throw=SavingThrowEffect(ability="dexterity", dc=15,
                                       damage_on_fail=[]),
    )


def _cone_spell():
    """A directional cone — NOT readyable (waits on D-AOE-1 geometry)."""
    return Action(
        name="Burning Hands", description="", action_type=ActionType.ACTION,
        spell_level=1, target_type=TargetType.AREA_CONE, range=15, area_size=15,
        saving_throw=SavingThrowEffect(ability="dexterity", dc=15,
                                       damage_on_fail=[]),
    )


def _zone_spell():
    """A concentration zone (Web) — NOT readyable (needs zone placement)."""
    return Action(
        name="Web", description="", action_type=ActionType.ACTION,
        spell_level=2, target_type=TargetType.AREA_CUBE, range=60, area_size=20,
        requires_concentration=True,
        saving_throw=SavingThrowEffect(ability="dexterity", dc=15,
                                       conditions_on_fail=["restrained"]),
    )


def _bonus_action():
    return Action(
        name="Off-hand", description="", action_type=ActionType.BONUS_ACTION,
        target_type=TargetType.ONE_CREATURE,
        attack=Attack(name="Dagger", attack_type="melee_weapon",
                      ability="dexterity", reach=5,
                      damage=[DamageRoll(dice="1d4",
                                         damage_type=DamageType.PIERCING)]),
    )


def test_is_readyable_filter():
    assert is_readyable(_attack_action())
    assert is_readyable(_single_target_save_spell())   # Hold Person (one_enemy)
    assert is_readyable(_fireball())                   # placed radius burst
    # Directional shapes, zones, and bonus actions are NOT readyable yet
    assert not is_readyable(_cone_spell())
    assert not is_readyable(_zone_spell())
    assert not is_readyable(_bonus_action())


def test_readyable_actions_filters_creature_list():
    class _C:
        actions = [_attack_action(), _fireball(), _cone_spell(), _zone_spell(),
                   _bonus_action(), _single_target_save_spell()]
    names = [a.name for a in readyable_actions(_C())]
    assert names == ["Sword", "Fireball", "Hold Person"]


def test_two_stage_selection():
    p = ReadyPopup([_attack_action(), _single_target_save_spell()])
    assert p.stage == "action"
    assert p._choose(0) is None       # picked action → advance to trigger
    assert p.stage == "trigger"
    assert p.selected_action.name == "Sword"
    assert p._choose(2) == "__ready__"  # picked a trigger
    assert p.selected_trigger == _TRIGGERS[2][1]


def test_escape_backs_out_of_trigger_stage():
    p = ReadyPopup([_attack_action()])
    p._choose(0)
    assert p.stage == "trigger"
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
    assert p.handle_event(esc) is None   # backs out, doesn't close
    assert p.stage == "action"
    # A second Esc at the action stage cancels.
    assert p.handle_event(esc) == "__close__"
