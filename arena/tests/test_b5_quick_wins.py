"""B5 — quick wins: stat-SET buffs, the auto-hit volley (Magic Missile),
real friendly fire on AoE (+ AI awareness), and the magical tag on the
spell-damage paths that bypassed packet tagging (zones, recurring, saves).
"""

from pathlib import Path
from unittest.mock import patch

from arena.ai.behavior import AIProfile
from arena.ai.context import CombatContext, CreatureView
from arena.ai.scoring import score_effect_action
from arena.combat.actions import resolve_effect
from arena.combat.damage import DamagePacket, apply_damage
from arena.combat.events import CombatEventType
from arena.combat.manager import CombatManager, Combatant
from arena.combat.stat_modifiers import (
    get_effective_ability_score,
    get_effective_armor_class,
)
from arena.combat.zones import ActiveZone, _resolve_zone_damage
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action,
    ActionType,
    Attack,
    DamageRoll,
    DamageType,
    SavingThrowEffect,
    TargetType,
)
from arena.models.character import Creature, PlayerCharacter
from arena.models.conditions import ActiveBuff, BuffEffect
from arena.models.encounter import CombatantEntry, Encounter

NONMAGICAL_BPS = "bludgeoning, piercing, and slashing from nonmagical weapons"


def _creature(name="Pip", hp=40, ac=12, dexterity=10, strength=10,
              resistances=None, is_player=True, actions=None):
    return Creature(
        name=name,
        max_hit_points=hp,
        current_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(dexterity=dexterity, strength=strength),
        proficiency_bonus=2,
        damage_resistances=resistances or [],
        is_player_controlled=is_player,
        actions=actions or [],
    )


def _buff(name, *modifiers):
    return ActiveBuff(name=name, source_id="self", modifiers=list(modifiers))


# ── 1. stat-SET buffs (floor semantics) ──────────────────────────────


class TestAbilitySet:
    def test_giant_strength_floors_a_weak_score(self):
        c = _creature(strength=10)
        c.active_buffs.append(_buff(
            "Potion of Hill Giant Strength",
            BuffEffect(stat="strength", modifier_type="set", value=21),
        ))
        assert get_effective_ability_score(c, "strength") == 21

    def test_set_is_a_floor_not_a_cap(self):
        """SRD: "no effect if your score is already equal or higher"."""
        c = _creature(strength=24)
        c.active_buffs.append(_buff(
            "Potion of Hill Giant Strength",
            BuffEffect(stat="strength", modifier_type="set", value=21),
        ))
        assert get_effective_ability_score(c, "strength") == 24

    def test_set_respects_the_30_cap(self):
        c = _creature(strength=10)
        c.active_buffs.append(_buff(
            "Impossible Brew",
            BuffEffect(stat="strength", modifier_type="set", value=35),
        ))
        assert get_effective_ability_score(c, "strength") == 30

    def test_other_abilities_untouched(self):
        c = _creature(strength=10, dexterity=14)
        c.active_buffs.append(_buff(
            "Potion", BuffEffect(stat="strength", modifier_type="set", value=21),
        ))
        assert get_effective_ability_score(c, "dexterity") == 14


class TestAcSet:
    def test_mage_armor_formula_floors_stored_ac(self):
        """13+DEX evaluated against the wearer (DEX 16 → AC 16 over stored 12)."""
        c = _creature(ac=12, dexterity=16)
        c.active_buffs.append(_buff(
            "Mage Armor",
            BuffEffect(stat="ac", modifier_type="set", value="13+DEX"),
        ))
        assert get_effective_armor_class(c) == 16

    def test_mage_armor_moot_when_already_higher(self):
        c = _creature(ac=18, dexterity=10)
        c.active_buffs.append(_buff(
            "Mage Armor",
            BuffEffect(stat="ac", modifier_type="set", value="13+DEX"),
        ))
        assert get_effective_armor_class(c) == 18

    def test_flat_ac_buffs_stack_on_top_of_the_floor(self):
        """Shield (+5) adds AFTER the Mage Armor base — 13+3+5 = 21, as in 5e."""
        c = _creature(ac=12, dexterity=16)
        c.active_buffs.append(_buff(
            "Mage Armor",
            BuffEffect(stat="ac", modifier_type="set", value="13+DEX"),
        ))
        c.active_buffs.append(_buff(
            "Shield", BuffEffect(stat="ac", modifier_type="flat_bonus", value=5),
        ))
        assert get_effective_armor_class(c) == 21

    def test_plain_int_set_value_works(self):
        """Barkskin-style: AC can't be less than 16."""
        c = _creature(ac=11)
        c.active_buffs.append(_buff(
            "Barkskin", BuffEffect(stat="ac", modifier_type="set", value=16),
        ))
        assert get_effective_armor_class(c) == 16


# ── 2. auto-hit + the Magic Missile volley ───────────────────────────


def _magic_missile(slots=1):
    return Action(
        name="Magic Missile",
        description="Three darts of magical force.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=120,
        spell_level=1,
        resource_cost={"spell_slot_1": 1},
        target_count=3,
        upcast_target_count=1,
        attack=Attack(
            name="Magic Missile",
            attack_type="ranged_spell",
            ability="intelligence",
            range_normal=120,
            auto_hit=True,
            damage=[DamageRoll(dice="1d4", damage_type=DamageType.FORCE, bonus=1)],
        ),
    )


def _volley_combat(action, slots=1, enemy_hp=50):
    caster = PlayerCharacter(
        name="Wizard",
        character_class="wizard",
        max_hit_points=20,
        current_hit_points=20,
        armor_class=12,
        ability_scores=AbilityScores(),
        proficiency_bonus=2,
        is_player_controlled=True,
        actions=[action],
        class_resources={"spell_slot_1": slots},
    )
    enemy = _creature("Ogre", hp=enemy_hp, is_player=False)
    encounter = Encounter(
        name="Volley", grid_width=10, grid_height=10,
        combatants=[
            CombatantEntry(creature_id="wiz", creature_data=caster,
                           team="player", starting_position=(2, 2)),
            CombatantEntry(creature_id="ogre", creature_data=enemy,
                           team="enemy", starting_position=(3, 2)),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
        cm.roll_initiative()
    cm.begin_combat()
    ids = {c.team: cid for cid, c in cm.combatants.items()}
    assert cm.active_combatant.creature_id == ids["player"]
    return cm, ids["player"], ids["enemy"]


class TestMagicMissileVolley:
    def test_three_darts_one_slot(self):
        """The whole point of the volley fix: 3 darts, ONE slot spent."""
        mm = _magic_missile()
        cm, wiz_id, ogre_id = _volley_combat(mm, slots=3)
        cm.select_action(mm)
        # Each dart's 1d4 rolls a 2 → 3 damage per dart, 9 total
        with patch("arena.combat.damage.roll_expression", return_value=(2, [2])):
            result = cm.execute_attack(ogre_id)
        assert result is not None and result.success
        wiz = cm.combatants[wiz_id].creature
        assert wiz.class_resources["spell_slot_1"] == 2     # exactly one deducted
        ogre = cm.combatants[ogre_id].creature
        assert ogre.current_hit_points == 50 - 9
        auto_hits = [e for e in result.events
                     if e.event_type == CombatEventType.ATTACK_ROLL]
        assert len(auto_hits) == 3
        assert all(e.details.get("auto_hit") for e in auto_hits)
        # The volley restores the action's cost for the next cast
        assert mm.resource_cost == {"spell_slot_1": 1}

    def test_no_slot_means_no_darts(self):
        mm = _magic_missile()
        cm, wiz_id, ogre_id = _volley_combat(mm, slots=0)
        cm.select_action(mm)
        result = cm.execute_attack(ogre_id)
        assert result is not None and not result.success
        assert cm.combatants[ogre_id].creature.current_hit_points == 50

    def test_darts_never_crit(self):
        """Auto-hit bypasses the d20 entirely — a nat-20 path can't fire."""
        mm = _magic_missile()
        cm, _, ogre_id = _volley_combat(mm, slots=1)
        cm.select_action(mm)
        with patch("arena.combat.damage.roll_expression", return_value=(4, [4])):
            result = cm.execute_attack(ogre_id)
        rolls = [e for e in result.events
                 if e.event_type == CombatEventType.ATTACK_ROLL]
        assert rolls and all(e.details["critical"] is False for e in rolls)


# ── 3. friendly fire (resolvers + AI awareness) ──────────────────────


def _fireburst(healing=False):
    if healing:
        return Action(
            name="Mass Cure", description="Healing burst",
            action_type=ActionType.ACTION, target_type=TargetType.AREA_SPHERE,
            range=30, area_size=15, healing="1d8",
        )
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


def _three_way_combat():
    """Caster + adjacent ally vs adjacent enemy, everyone inside a 15ft blast."""
    caster = _creature("Caster", actions=[_fireburst()])
    ally = _creature("Ally")
    enemy = _creature("Brute", is_player=False)
    encounter = Encounter(
        name="FF", grid_width=10, grid_height=10,
        combatants=[
            CombatantEntry(creature_id="caster", creature_data=caster,
                           team="player", starting_position=(4, 4)),
            CombatantEntry(creature_id="ally", creature_data=ally,
                           team="player", starting_position=(5, 4)),
            CombatantEntry(creature_id="brute", creature_data=enemy,
                           team="enemy", starting_position=(4, 5)),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10, 1]):
        cm.roll_initiative()
    cm.begin_combat()
    by_name = {c.creature.name: (cid, c) for cid, c in cm.combatants.items()}
    return cm, by_name


class TestFriendlyFireTargets:
    def test_harmful_aoe_includes_allies(self):
        cm, by_name = _three_way_combat()
        caster_id, caster = by_name["Caster"]
        ally_id, _ = by_name["Ally"]
        brute_id, _ = by_name["Brute"]
        affected = cm._resolve_effect_targets(_fireburst(), caster, brute_id)
        assert brute_id in affected
        assert ally_id in affected          # friendly fire is real
        assert caster_id not in affected    # caster-centered blast skips caster

    def test_beneficial_aoe_stays_allies_only(self):
        cm, by_name = _three_way_combat()
        _, caster = by_name["Caster"]
        ally_id, _ = by_name["Ally"]
        brute_id, _ = by_name["Brute"]
        affected = cm._resolve_effect_targets(
            _fireburst(healing=True), caster, ally_id,
        )
        assert ally_id in affected
        assert brute_id not in affected

    def test_hex_targeted_aoe_can_catch_the_caster(self):
        cm, by_name = _three_way_combat()
        caster_id, caster = by_name["Caster"]
        affected = cm._resolve_effect_targets_at_hex(
            _fireburst(), caster, HexCoord(4, 4),
        )
        assert caster_id in affected        # standing in your own Fireball


def _view(cid, team, pos):
    return CreatureView(
        creature_id=cid, team=team, position=HexCoord(*pos), hp_percent=1.0,
        is_conscious=True, armor_class=12, has_concentration=False,
        is_spellcaster=False, condition_names=(), max_hit_points=20,
        current_hit_points=20, speed=30, actions_count=1,
    )


def _context(me, allies=(), enemies=()):
    return CombatContext(
        me=me, allies=tuple(allies), enemies=tuple(enemies),
        all_combatants=(me, *allies, *enemies),
        grid_width=12, grid_height=12, round_number=1,
        remaining_movement=30, has_used_action=False,
        has_used_bonus_action=False,
    )


class TestAiFriendlyFireScoring:
    def test_ally_in_blast_lowers_the_score(self):
        me = _view("me", "enemy", (5, 5))
        target = _view("pc", "player", (6, 5))
        ally_in = _view("buddy", "enemy", (5, 6))      # 1 hex — inside 15ft
        ally_out = _view("buddy", "enemy", (5, 9))     # 4 hexes — outside
        profile = AIProfile(name="caster", prefers_melee=False)
        burst = _fireburst()
        s_in = score_effect_action(
            burst, profile, _context(me, [ally_in], [target]), target, 1,
        )
        s_out = score_effect_action(
            burst, profile, _context(me, [ally_out], [target]), target, 1,
        )
        assert s_in < s_out

    def test_protective_profiles_penalize_harder(self):
        me = _view("me", "enemy", (5, 5))
        target = _view("pc", "player", (6, 5))
        ally_in = _view("buddy", "enemy", (5, 6))
        ctx = _context(me, [ally_in], [target])
        burst = _fireburst()
        careless = score_effect_action(
            burst, AIProfile(name="a", protects_allies=False), ctx, target, 1,
        )
        careful = score_effect_action(
            burst, AIProfile(name="b", protects_allies=True), ctx, target, 1,
        )
        assert careful < careless

    def test_more_enemies_in_blast_still_raises_the_score(self):
        me = _view("me", "enemy", (5, 5))
        t1 = _view("pc1", "player", (6, 5))
        t2 = _view("pc2", "player", (5, 6))
        profile = AIProfile(name="caster")
        burst = _fireburst()
        s_two = score_effect_action(
            burst, profile, _context(me, [], [t1, t2]), t1, 1,
        )
        s_one = score_effect_action(
            burst, profile, _context(me, [], [t1]), t1, 1,
        )
        assert s_two > s_one


# ── 4. the magical tag on bypassed spell-damage paths ────────────────


class TestMagicalTagging:
    def test_zone_damage_overcomes_nonmagical_defenses(self):
        """A bludgeoning spell zone vs a werewolf-style defense: full damage."""
        target = _creature("Werewolf", hp=40, resistances=[NONMAGICAL_BPS],
                           is_player=False)
        combatants = {
            "wolf": Combatant(creature_id="wolf", creature=target,
                              team="enemy", position=HexCoord(3, 3)),
            "caster": Combatant(creature_id="caster", creature=_creature("C"),
                                team="player", position=HexCoord(2, 2)),
        }
        zone = ActiveZone(
            zone_id="z", caster_id="caster", name="Crushing Field",
            radius_feet=15, saving_throw_dc=30,   # un-makeable — always fails
            damage_dice="1d1+9", damage_type="bludgeoning",
            damage_on_save="half",
        )
        _resolve_zone_damage(zone, "wolf", combatants)
        assert target.current_hit_points == 30    # 10, not 5: tag bypassed it

    def test_untagged_packet_is_still_resisted(self):
        """Control: the defense itself works when damage ISN'T magical."""
        target = _creature("Werewolf", hp=40, resistances=[NONMAGICAL_BPS])
        apply_damage(target, [DamagePacket(amount=10, dtype="bludgeoning")])
        assert target.current_hit_points == 35    # halved

    def test_spell_save_damage_is_magical(self):
        """resolve_effect's save path now tags packets (Fireball et al.)."""
        caster = _creature("Caster")
        target = _creature("Werewolf", hp=40, resistances=[NONMAGICAL_BPS])
        action = Action(
            name="Stone Crush", description="Magical bludgeoning save spell",
            action_type=ActionType.ACTION, target_type=TargetType.ONE_CREATURE,
            range=30, spell_level=2,
            saving_throw=SavingThrowEffect(
                ability="dexterity", dc=30,        # always fails
                damage_on_fail=[DamageRoll(dice="1d1", damage_type=DamageType.BLUDGEONING, bonus=9)],
                damage_on_success="half",
            ),
        )
        grid = HexGrid(width=8, height=8)
        result = resolve_effect(
            caster, "caster", target, "wolf", action, grid,
            user_pos=HexCoord(1, 1), target_pos=HexCoord(2, 1),
        )
        assert result.success
        assert target.current_hit_points == 30    # full 10 — magical bypass

    def test_nonspell_save_ability_is_not_tagged(self):
        """A mundane save effect (no spell_level, no magic) stays nonmagical."""
        brute = _creature("Brute")
        target = _creature("Werewolf", hp=40, resistances=[NONMAGICAL_BPS])
        action = Action(
            name="Rock Toss", description="A thrown boulder",
            action_type=ActionType.ACTION, target_type=TargetType.ONE_CREATURE,
            range=30,
            saving_throw=SavingThrowEffect(
                ability="dexterity", dc=30,
                damage_on_fail=[DamageRoll(dice="1d1", damage_type=DamageType.BLUDGEONING, bonus=9)],
                damage_on_success="half",
            ),
        )
        grid = HexGrid(width=8, height=8)
        resolve_effect(
            brute, "brute", target, "wolf", action, grid,
            user_pos=HexCoord(1, 1), target_pos=HexCoord(2, 1),
        )
        assert target.current_hit_points == 35    # halved — still nonmagical
