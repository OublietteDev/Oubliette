"""C1 — the damage_rolls buff stat (Rage's +2 melee damage and kin)."""

from arena.combat.buff_effects import get_buff_damage_bonus
from arena.models.character import PlayerCharacter
from arena.models.conditions import ActiveBuff, BuffEffect


def _pc(*modifiers: BuffEffect) -> PlayerCharacter:
    return PlayerCharacter(
        name="Grog", character_class="Barbarian", max_hit_points=30,
        active_buffs=[ActiveBuff(name="Rage", source_id="self",
                                 modifiers=list(modifiers))],
    )


def test_melee_scope_applies_to_melee_attacks_only():
    pc = _pc(BuffEffect(stat="damage_rolls", modifier_type="flat_bonus",
                        value=2, scope="melee"))
    assert get_buff_damage_bonus(pc, "melee_weapon") == 2
    assert get_buff_damage_bonus(pc, "ranged_weapon") == 0
    assert get_buff_damage_bonus(pc, None) == 0


def test_all_scope_applies_everywhere_and_bonuses_sum():
    pc = _pc(
        BuffEffect(stat="damage_rolls", modifier_type="flat_bonus", value=2),
        BuffEffect(stat="damage_rolls", modifier_type="flat_bonus", value=1,
                   scope="all"),
    )
    assert get_buff_damage_bonus(pc, "ranged_spell") == 3


def test_other_stats_and_target_debuffs_are_ignored():
    pc = _pc(
        BuffEffect(stat="attack_rolls", modifier_type="flat_bonus", value=5),
        BuffEffect(stat="damage_rolls", modifier_type="flat_bonus", value=4,
                   target_grants_to_attacker=True),
    )
    assert get_buff_damage_bonus(pc, "melee_weapon") == 0
