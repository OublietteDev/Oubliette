"""C4f P-DISPEL — Dispel Magic and the effect-origin tag.

Buffs and conditions applied through resolve_effect by a SPELL remember
the slot level they were cast at (spell_level on ActiveBuff /
AppliedCondition). Dispel Magic ends tagged effects at or below its cast
slot automatically and rolls d20 + casting mod vs DC 10+level for higher
ones. Untagged effects — class features, potions, monster abilities —
are not spells and cannot be dispelled.
"""

from unittest.mock import patch

from arena.combat.actions import resolve_effect
from arena.combat.conditions import has_condition
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action,
    ActionType,
    SavingThrowEffect,
    TargetType,
)
from arena.models.character import Creature, PlayerCharacter
from arena.models.conditions import (
    ActiveBuff,
    AppliedCondition,
    BuffEffect,
    Condition,
)


def _creature(name="Pip", spellcasting_ability=None):
    common = dict(
        name=name,
        max_hit_points=40,
        current_hit_points=40,
        armor_class=12,
        ability_scores=AbilityScores(intelligence=16),
        proficiency_bonus=2,
        is_player_controlled=True,
        actions=[],
    )
    if spellcasting_ability:
        # spellcasting_ability lives on PlayerCharacter, not base Creature —
        # same split the bridge uses.
        return PlayerCharacter(
            character_class="Wizard",
            spellcasting_ability=spellcasting_ability,
            **common,
        )
    return Creature(**common)


def _grid():
    g = HexGrid(width=10, height=10)
    return g


def _dispel(spell_level=3):
    return Action(
        name="Dispel Magic", description="End spells on a target.",
        action_type=ActionType.ACTION, target_type=TargetType.ONE_CREATURE,
        range=120, spell_level=spell_level, dispel=True,
    )


def _buff(name, spell_level, stat="attack_rolls"):
    return ActiveBuff(
        name=name, source_id="someone",
        modifiers=[BuffEffect(stat=stat, modifier_type="flat_bonus", value=2)],
        spell_level=spell_level,
    )


def _cast(caster, target, action, cast_level=None):
    g = _grid()
    g.place_creature(HexCoord(2, 2), "caster", caster.size)
    g.place_creature(HexCoord(3, 2), "target", target.size)
    return resolve_effect(
        caster, "caster", target, "target", action, g,
        combatants={}, cast_level=cast_level,
    )


class TestDispelBuffs:
    def test_low_level_buff_auto_dispelled(self):
        caster = _creature("Wiz")
        target = _creature("Foe")
        target.active_buffs.append(_buff("Bless", 1))
        _cast(caster, target, _dispel())
        assert not target.active_buffs

    def test_untagged_buff_untouched(self):
        caster = _creature("Wiz")
        target = _creature("Foe")
        target.active_buffs.append(_buff("Rage", None))
        result = _cast(caster, target, _dispel())
        assert len(target.active_buffs) == 1
        assert any("No spell effects" in e.message for e in result.events)

    def test_high_level_buff_needs_check_failure_keeps_it(self):
        caster = _creature("Wiz", spellcasting_ability="intelligence")
        target = _creature("Foe")
        target.active_buffs.append(_buff("Holy Aura", 8))   # DC 18
        with patch("arena.combat.actions.roll_die", return_value=2):
            _cast(caster, target, _dispel())                 # 2+3=5 < 18
        assert len(target.active_buffs) == 1

    def test_high_level_buff_check_success_removes_it(self):
        caster = _creature("Wiz", spellcasting_ability="intelligence")
        target = _creature("Foe")
        target.active_buffs.append(_buff("Holy Aura", 8))   # DC 18
        with patch("arena.combat.actions.roll_die", return_value=15):
            _cast(caster, target, _dispel())                 # 15+3=18 >= 18
        assert not target.active_buffs

    def test_upcast_raises_auto_threshold(self):
        caster = _creature("Wiz")
        target = _creature("Foe")
        target.active_buffs.append(_buff("Hold Monster", 5))
        _cast(caster, target, _dispel(), cast_level=5)       # auto at 5
        assert not target.active_buffs


class TestDispelConditions:
    def test_spell_condition_dispelled(self):
        caster = _creature("Wiz")
        target = _creature("Foe")
        target.active_conditions.append(AppliedCondition(
            condition=Condition.PARALYZED, source="Cleric",
            duration_type="end_of_turn", save_to_end="wisdom", save_dc=13,
            spell_level=2,
        ))
        _cast(caster, target, _dispel())
        assert not has_condition(target, Condition.PARALYZED)

    def test_monster_condition_untouched(self):
        caster = _creature("Wiz")
        target = _creature("Foe")
        target.active_conditions.append(AppliedCondition(
            condition=Condition.PARALYZED, source="Ghoul",
            duration_type="end_of_turn", save_to_end="constitution",
            save_dc=10, spell_level=None,
        ))
        _cast(caster, target, _dispel())
        assert has_condition(target, Condition.PARALYZED)


class TestOriginTagging:
    def test_save_condition_carries_cast_level(self):
        caster = _creature("Cleric")
        target = _creature("Foe")
        hold = Action(
            name="Hold Person", description="Paralyze.",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_CREATURE,
            range=60, spell_level=2,
            saving_throw=SavingThrowEffect(
                ability="wisdom", dc=13,
                conditions_on_fail=["paralyzed"],
            ),
        )
        with patch("arena.combat.actions.roll_die", return_value=1):
            _cast(caster, target, hold, cast_level=4)
        cond = target.active_conditions[0]
        assert cond.spell_level == 4        # the slot it was CAST at

    def test_buff_carries_spell_level(self):
        caster = _creature("Cleric")
        target = _creature("Ally")
        bless = Action(
            name="Bless", description="+2 attacks/saves.",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_ALLY,
            range=30, spell_level=1,
            buff_effects=[BuffEffect(
                stat="attack_rolls", modifier_type="flat_bonus", value=2,
            )],
        )
        _cast(caster, target, bless)
        assert target.active_buffs[0].spell_level == 1

    def test_non_spell_action_leaves_tag_unset(self):
        caster = _creature("Monster")
        target = _creature("Victim")
        ability = Action(
            name="Petrifying Gaze", description="A monster ability.",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_CREATURE,
            range=30,
            saving_throw=SavingThrowEffect(
                ability="constitution", dc=13,
                conditions_on_fail=["restrained"],
            ),
        )
        with patch("arena.combat.actions.roll_die", return_value=1):
            _cast(caster, target, ability)
        assert target.active_conditions[0].spell_level is None
