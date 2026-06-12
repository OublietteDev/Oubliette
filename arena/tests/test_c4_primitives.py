"""C4 — new spell/feature primitives.

Sculpt Spells (Evocation wizard): the caster's harmful AoE spares allies
entirely — both effect-target resolvers, the AI's friendly-fire scoring,
and (visually) the AoE preview. The approximation of RAW's "choose 1+level
creatures to auto-succeed" is full exemption of the caster's team.
"""

from pathlib import Path
from unittest.mock import patch

from arena.ai.behavior import AIProfile
from arena.ai.context import CombatContext, CreatureView
from arena.ai.scoring import score_effect_action
from arena.combat.actions import (
    resolve_attack_damage,
    resolve_attack_hit,
    resolve_effect,
)
from arena.combat.buff_effects import (
    consume_buff_charge,
    get_buff_on_hit_riders,
)
from arena.combat.manager import CombatManager
from arena.combat.stat_modifiers import has_sculpt_spells
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
from arena.models.character import Creature, Feature, PlayerCharacter
from arena.models.conditions import ActiveBuff, BuffEffect
from arena.models.encounter import CombatantEntry, Encounter

SCULPT = Feature(name="Sculpt Spells", description="Spare allies from blasts.",
                 sculpt_spells=True)


def _creature(name="Pip", hp=40, is_player=True, actions=None, features=None):
    # Features live on PlayerCharacter, not base Creature — same split the
    # bridge uses (only PCs carry staged class features).
    common = dict(
        name=name,
        max_hit_points=hp,
        current_hit_points=hp,
        armor_class=12,
        ability_scores=AbilityScores(),
        proficiency_bonus=2,
        is_player_controlled=is_player,
        actions=actions or [],
    )
    if features:
        return PlayerCharacter(
            character_class="Wizard", features=features, **common)
    return Creature(**common)


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


def _three_way_combat(caster_features=None):
    """Caster + adjacent ally vs adjacent enemy, everyone inside a 15ft blast."""
    caster = _creature("Caster", actions=[_fireburst()],
                       features=caster_features)
    ally = _creature("Ally")
    enemy = _creature("Brute", is_player=False)
    encounter = Encounter(
        name="Sculpt", grid_width=10, grid_height=10,
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


class TestSculptSpellsQuery:
    def test_feature_flag_detected(self):
        assert has_sculpt_spells(_creature(features=[SCULPT]))

    def test_absent_by_default(self):
        assert not has_sculpt_spells(_creature())


class TestSculptSpellsTargets:
    def test_harmful_aoe_spares_allies(self):
        cm, by_name = _three_way_combat(caster_features=[SCULPT])
        _, caster = by_name["Caster"]
        ally_id, _ = by_name["Ally"]
        brute_id, _ = by_name["Brute"]
        affected = cm._resolve_effect_targets(_fireburst(), caster, brute_id)
        assert brute_id in affected
        assert ally_id not in affected      # sculpted around

    def test_hex_targeted_aoe_spares_caster_and_ally(self):
        cm, by_name = _three_way_combat(caster_features=[SCULPT])
        caster_id, caster = by_name["Caster"]
        ally_id, _ = by_name["Ally"]
        brute_id, _ = by_name["Brute"]
        affected = cm._resolve_effect_targets_at_hex(
            _fireburst(), caster, HexCoord(4, 4),
        )
        assert brute_id in affected
        assert ally_id not in affected
        assert caster_id not in affected    # sculpting around yourself too

    def test_beneficial_aoe_still_reaches_allies(self):
        cm, by_name = _three_way_combat(caster_features=[SCULPT])
        _, caster = by_name["Caster"]
        ally_id, _ = by_name["Ally"]
        affected = cm._resolve_effect_targets(
            _fireburst(healing=True), caster, ally_id,
        )
        assert ally_id in affected

    def test_without_sculpt_friendly_fire_still_real(self):
        cm, by_name = _three_way_combat()
        _, caster = by_name["Caster"]
        ally_id, _ = by_name["Ally"]
        brute_id, _ = by_name["Brute"]
        affected = cm._resolve_effect_targets(_fireburst(), caster, brute_id)
        assert ally_id in affected          # B5 invariant unchanged


def _view(cid, team, pos, sculpt=False):
    return CreatureView(
        creature_id=cid, team=team, position=HexCoord(*pos), hp_percent=1.0,
        is_conscious=True, armor_class=12, has_concentration=False,
        is_spellcaster=False, condition_names=(), max_hit_points=20,
        current_hit_points=20, speed=30, actions_count=1,
        has_sculpt_spells=sculpt,
    )


def _context(me, allies=(), enemies=()):
    return CombatContext(
        me=me, allies=tuple(allies), enemies=tuple(enemies),
        all_combatants=(me, *allies, *enemies),
        grid_width=12, grid_height=12, round_number=1,
        remaining_movement=30, has_used_action=False,
        has_used_bonus_action=False,
    )


class TestSculptSpellsAiScoring:
    def test_sculpt_caster_ignores_allies_in_blast(self):
        target = _view("pc", "player", (6, 5))
        ally_in = _view("buddy", "enemy", (5, 6))   # 1 hex — inside 15ft
        burst = _fireburst()
        profile = AIProfile(name="caster", prefers_melee=False)
        plain = _view("me", "enemy", (5, 5))
        sculpted = _view("me", "enemy", (5, 5), sculpt=True)
        s_plain = score_effect_action(
            burst, profile, _context(plain, [ally_in], [target]), target, 1,
        )
        s_sculpt = score_effect_action(
            burst, profile, _context(sculpted, [ally_in], [target]), target, 1,
        )
        assert s_sculpt > s_plain           # no friendly-fire penalty


# ── C4b: spell-granted on-hit riders (on_hit_damage buffs) ───────────


def _weapon_action(name="Sword"):
    return Action(
        name=name, description="A sword swing",
        action_type=ActionType.ACTION, target_type=TargetType.ONE_CREATURE,
        range=5,
        attack=Attack(
            name=name, attack_type="melee_weapon", ability="strength",
            reach=5,
            damage=[DamageRoll(dice="1d8", damage_type=DamageType.SLASHING)],
        ),
    )


def _grid_pair(attacker_id="atk", target_id="tgt"):
    grid = HexGrid(width=10, height=10)
    grid.place_creature(HexCoord(2, 2), attacker_id)
    grid.place_creature(HexCoord(2, 3), target_id)
    return grid


def _favor_buff(source_id="atk", charges=None):
    return ActiveBuff(
        name="Divine Favor", source_id=source_id, charges=charges,
        modifiers=[BuffEffect(stat="on_hit_damage", modifier_type="flat_bonus",
                              value="1d4", damage_type="radiant",
                              scope="weapon")],
    )


def _mark_buff(source_id="atk"):
    return ActiveBuff(
        name="Hunter's Mark", source_id=source_id,
        modifiers=[BuffEffect(stat="on_hit_damage", modifier_type="flat_bonus",
                              value="1d6", scope="weapon",
                              target_grants_to_attacker=True)],
    )


class TestOnHitRiderQuery:
    def test_attacker_self_buff_fires_on_weapon_attack(self):
        attacker, target = _creature("A"), _creature("B")
        attacker.active_buffs.append(_favor_buff())
        riders = get_buff_on_hit_riders(attacker, "atk", target, "melee_weapon")
        assert len(riders) == 1
        owner, buff, mod = riders[0]
        assert owner is attacker and buff.name == "Divine Favor"

    def test_weapon_scope_skips_spell_attacks(self):
        attacker, target = _creature("A"), _creature("B")
        attacker.active_buffs.append(_favor_buff())
        assert get_buff_on_hit_riders(attacker, "atk", target, "ranged_spell") == []

    def test_mark_fires_only_for_its_caster(self):
        attacker, target = _creature("A"), _creature("B")
        target.active_buffs.append(_mark_buff(source_id="atk"))
        mine = get_buff_on_hit_riders(attacker, "atk", target, "melee_weapon")
        theirs = get_buff_on_hit_riders(attacker, "someone_else", target,
                                        "melee_weapon")
        assert len(mine) == 1 and mine[0][0] is target
        assert theirs == []

    def test_marked_creature_does_not_benefit_from_its_own_mark(self):
        # The mark lives ON the marked creature; its own attacks must not
        # pick it up via the attacker-side path.
        marked, victim = _creature("Marked"), _creature("Victim")
        marked.active_buffs.append(_mark_buff(source_id="hunter"))
        assert get_buff_on_hit_riders(marked, "marked", victim,
                                      "melee_weapon") == []

    def test_charge_consumption_removes_the_buff(self):
        c = _creature("A")
        buff = _favor_buff(charges=1)
        c.active_buffs.append(buff)
        event = consume_buff_charge(c, "atk", buff)
        assert event is not None and c.active_buffs == []

    def test_chargeless_buffs_never_consume(self):
        c = _creature("A")
        buff = _favor_buff()
        c.active_buffs.append(buff)
        assert consume_buff_charge(c, "atk", buff) is None
        assert c.active_buffs == [buff]


class TestOnHitRiderResolution:
    def _hit(self, attacker, target, roll=20):
        grid = _grid_pair()
        with patch("arena.combat.actions.roll_die", return_value=roll):
            hit = resolve_attack_hit(
                attacker, "atk", target, "tgt", _weapon_action(), grid,
            )
        assert hit.hit
        return resolve_attack_damage(hit)

    def test_divine_favor_adds_radiant_rider(self):
        attacker = _creature("Paladin")
        target = _creature("Wight", hp=60)
        attacker.active_buffs.append(_favor_buff())
        result = self._hit(attacker, target)
        rider_events = [e for e in result.events
                        if "Divine Favor adds" in e.message]
        assert len(rider_events) == 1
        assert "radiant" in rider_events[0].message

    def test_branding_smite_spends_after_one_hit(self):
        attacker = _creature("Paladin")
        target = _creature("Wight", hp=60)
        attacker.active_buffs.append(ActiveBuff(
            name="Branding Smite", source_id="atk", charges=1,
            modifiers=[BuffEffect(stat="on_hit_damage",
                                  modifier_type="flat_bonus", value="2d6",
                                  damage_type="radiant", scope="weapon")],
        ))
        first = self._hit(attacker, target)
        assert any("Branding Smite adds" in e.message for e in first.events)
        assert any("Branding Smite is spent" in e.message for e in first.events)
        assert attacker.active_buffs == []
        second = self._hit(attacker, target)
        assert not any("Branding Smite adds" in e.message
                       for e in second.events)

    def test_hunters_mark_inherits_weapon_damage_type(self):
        attacker = _creature("Ranger")
        target = _creature("Orc", hp=60)
        target.active_buffs.append(_mark_buff(source_id="atk"))
        result = self._hit(attacker, target)
        rider_events = [e for e in result.events
                        if "Hunter's Mark adds" in e.message]
        assert len(rider_events) == 1
        assert "slashing" in rider_events[0].message   # weapon's type

    def test_cast_threads_charges_onto_the_buff(self):
        caster = _creature("Paladin")
        grid = _grid_pair()
        smite = Action(
            name="Branding Smite", description="Next hit glows",
            action_type=ActionType.BONUS_ACTION, target_type=TargetType.SELF,
            range=0, buff_charges=1,
            buff_effects=[BuffEffect(stat="on_hit_damage",
                                     modifier_type="flat_bonus", value="2d6",
                                     damage_type="radiant", scope="weapon")],
        )
        result = resolve_effect(caster, "atk", caster, "atk", smite, grid)
        assert result.success
        assert caster.active_buffs[0].charges == 1


# ── C4c: Shield — the AC-reaction spell via the hit-reaction popup ───


def _shield_action():
    return Action(
        name="Shield", description="+5 AC until your next turn",
        action_type=ActionType.REACTION, target_type=TargetType.SELF,
        range=0, spell_level=1, resource_cost={"spell_slot_1": 1},
        buff_effects=[BuffEffect(stat="ac", modifier_type="flat_bonus",
                                 value=5)],
        buff_duration_rounds=1,
    )


def _shield_combat(slots=2):
    """Enemy bruiser vs a player wizard who knows Shield (AC 12)."""
    wizard = PlayerCharacter(
        name="Wizard", character_class="Wizard",
        max_hit_points=20, current_hit_points=20, armor_class=12,
        ability_scores=AbilityScores(), proficiency_bonus=2,
        is_player_controlled=True,
        class_resources={"spell_slot_1": slots},
        reactions=[_shield_action()],
    )
    brute = _creature("Brute", is_player=False,
                      actions=[_weapon_action("Club")])
    encounter = Encounter(
        name="ShieldTest", grid_width=10, grid_height=10,
        combatants=[
            CombatantEntry(creature_id="wiz", creature_data=wizard,
                           team="player", starting_position=(4, 4)),
            CombatantEntry(creature_id="brute", creature_data=brute,
                           team="enemy", starting_position=(4, 5)),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
        cm.roll_initiative()
    cm.begin_combat()
    by_name = {c.creature.name: (cid, c) for cid, c in cm.combatants.items()}
    return cm, by_name["Wizard"], by_name["Brute"]


def _attack_wizard(cm, brute, wiz, roll):
    brute_id, brute_c = brute
    wiz_id, wiz_c = wiz
    with patch("arena.combat.actions.roll_die", return_value=roll):
        hit = resolve_attack_hit(
            brute_c.creature, brute_id, wiz_c.creature, wiz_id,
            _weapon_action("Club"), cm.grid,
        )
    return hit


class TestShieldReaction:
    def test_option_offered_and_negates_the_hit(self):
        cm, wiz, brute = _shield_combat()
        wiz_id, wiz_c = wiz
        # roll 12 + 2 (str 10 + prof 2) = 14 vs AC 12: a hit by 2 — Shield's
        # +5 turns it into a miss.
        hit = _attack_wizard(cm, brute, wiz, roll=12)
        assert hit.hit and not hit.critical
        deferred = cm.complete_attack(hit)
        assert deferred is None                     # popup pending
        options = cm._pending_damage_reduction["options"]
        assert any(red == cm.AC_REACTION for _, red in options)

        cm.resolve_damage_reduction_choice("Shield")
        creature = wiz_c.creature
        assert hit.hit is False                     # retroactive miss
        assert creature.current_hit_points == 20    # no damage
        assert any(b.name == "Shield" for b in creature.active_buffs)
        assert creature.class_resources["spell_slot_1"] == 1
        assert cm.reaction_used[wiz_id] is True

    def test_natural_20_cannot_be_turned(self):
        cm, wiz, brute = _shield_combat()
        _, wiz_c = wiz
        hit = _attack_wizard(cm, brute, wiz, roll=20)
        assert hit.hit and hit.critical
        cm.complete_attack(hit)
        cm.resolve_damage_reduction_choice("Shield")
        creature = wiz_c.creature
        assert hit.hit is True                      # crits land regardless
        assert creature.current_hit_points < 20     # damage went through
        assert any(b.name == "Shield" for b in creature.active_buffs)

    def test_not_offered_without_a_slot(self):
        cm, wiz, brute = _shield_combat(slots=0)
        assert cm.check_ac_reaction_options(wiz[0]) == []

    def test_not_offered_when_reaction_spent(self):
        cm, wiz, brute = _shield_combat()
        cm.reaction_used[wiz[0]] = True
        assert cm.check_ac_reaction_options(wiz[0]) == []

    def test_skipping_completes_the_attack_normally(self):
        cm, wiz, brute = _shield_combat()
        wiz_id, wiz_c = wiz
        hit = _attack_wizard(cm, brute, wiz, roll=12)
        cm.complete_attack(hit)
        cm.resolve_damage_reduction_choice(None)    # player clicked Skip
        creature = wiz_c.creature
        assert creature.current_hit_points < 20
        assert creature.class_resources["spell_slot_1"] == 2
        assert not cm.reaction_used.get(wiz_id, False)


# ── C4d: decoys — Mirror Image and Sanctuary ─────────────────────────


def _decoy(charges=3):
    return ActiveBuff(
        name="Mirror Image", source_id="self", charges=charges,
        modifiers=[BuffEffect(stat="decoy_images",
                              modifier_type="flat_bonus", value=3)],
    )


def _ward(dc=13):
    return ActiveBuff(
        name="Sanctuary", source_id="cleric",
        modifiers=[BuffEffect(stat="sanctuary_ward",
                              modifier_type="flat_bonus", value=dc)],
    )


def _swing(attacker, target, roll, dex=10):
    target.ability_scores.dexterity = dex
    grid = _grid_pair()
    with patch("arena.combat.actions.roll_die", return_value=roll):
        return resolve_attack_hit(
            attacker, "atk", target, "tgt", _weapon_action(), grid,
        )


class TestMirrorImage:
    def test_redirected_hit_shatters_a_duplicate(self):
        attacker, target = _creature("Orc"), _creature("Wizard")
        buff = _decoy(charges=3)
        target.active_buffs.append(buff)
        # roll 15: redirect (15 >= 6 at 3 images), 15+2=17 vs image AC 10
        hit = _swing(attacker, target, roll=15)
        assert hit.hit is False                     # real wizard untouched
        assert buff.charges == 2                    # one image gone
        assert any("duplicate" in e.message for e in hit.events)

    def test_redirected_miss_spares_the_duplicate(self):
        attacker, target = _creature("Orc"), _creature("Wizard")
        buff = _decoy(charges=3)
        target.active_buffs.append(buff)
        # dex 18 → image AC 14; roll 8: redirect (8 >= 6), 8+2=10 < 14
        hit = _swing(attacker, target, roll=8, dex=18)
        assert hit.hit is False
        assert buff.charges == 3                    # image evaded too

    def test_low_redirect_roll_attacks_the_real_target(self):
        attacker, target = _creature("Orc"), _creature("Wizard")
        buff = _decoy(charges=1)                    # 1 image: needs 11+
        target.active_buffs.append(buff)
        # roll 10: redirect fails (10 < 11), real attack 10+2=12 vs AC 12
        hit = _swing(attacker, target, roll=10)
        assert hit.hit is True
        assert buff.charges == 1

    def test_last_image_removal_ends_the_spell(self):
        attacker, target = _creature("Orc"), _creature("Wizard")
        buff = _decoy(charges=1)
        target.active_buffs.append(buff)
        # roll 15: redirect (15 >= 11), 17 vs AC 10 shatters the last image
        hit = _swing(attacker, target, roll=15)
        assert hit.hit is False
        assert target.active_buffs == []            # spell spent
        assert any("spent" in e.message for e in hit.events)


# ── C4e: Turn Undead — the creature-type target filter ───────────────


def _turn_undead(dc=13):
    return Action(
        name="Turn Undead", description="Turn the undead",
        action_type=ActionType.ACTION, target_type=TargetType.AREA_SPHERE,
        range=0, area_size=30,
        saving_throw=SavingThrowEffect(
            ability="wisdom", dc=dc, conditions_on_fail=["frightened"],
        ),
        target_creature_types=["undead"],
    )


def _turn_combat():
    from arena.models.character import CreatureType

    cleric = _creature("Cleric", actions=[_turn_undead()])
    skeleton = _creature("Skeleton", is_player=False)
    skeleton.creature_type = CreatureType.UNDEAD
    orc = _creature("Orc", is_player=False)
    encounter = Encounter(
        name="Turn", grid_width=10, grid_height=10,
        combatants=[
            CombatantEntry(creature_id="cleric", creature_data=cleric,
                           team="player", starting_position=(4, 4)),
            CombatantEntry(creature_id="skeleton", creature_data=skeleton,
                           team="enemy", starting_position=(4, 5)),
            CombatantEntry(creature_id="orc", creature_data=orc,
                           team="enemy", starting_position=(5, 4)),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10, 1]):
        cm.roll_initiative()
    cm.begin_combat()
    by_name = {c.creature.name: (cid, c) for cid, c in cm.combatants.items()}
    return cm, by_name


class TestTurnUndeadFilter:
    def test_only_the_undead_are_affected(self):
        cm, by_name = _turn_combat()
        _, cleric = by_name["Cleric"]
        skeleton_id, _ = by_name["Skeleton"]
        orc_id, _ = by_name["Orc"]
        affected = cm._resolve_effect_targets(
            _turn_undead(), cleric, skeleton_id,
        )
        assert skeleton_id in affected
        assert orc_id not in affected           # not undead — untouched

    def test_clicking_a_non_undead_does_not_force_include_it(self):
        cm, by_name = _turn_combat()
        _, cleric = by_name["Cleric"]
        orc_id, _ = by_name["Orc"]
        affected = cm._resolve_effect_targets(
            _turn_undead(), cleric, orc_id,
        )
        assert orc_id not in affected

    def test_failed_save_turns_with_a_resave(self):
        from arena.models.conditions import Condition

        cm, by_name = _turn_combat()
        _, cleric = by_name["Cleric"]
        skeleton_id, skeleton_c = by_name["Skeleton"]
        with patch("arena.combat.actions.roll_die", return_value=2):
            result = resolve_effect(
                cleric.creature, "cl", skeleton_c.creature, skeleton_id,
                _turn_undead(), cm.grid,
            )
        assert result.success
        turned = [ac for ac in skeleton_c.creature.active_conditions
                  if ac.condition == Condition.FRIGHTENED]
        assert len(turned) == 1
        assert turned[0].save_to_end == "wisdom"   # re-save each turn


class TestSanctuary:
    def test_failed_save_loses_the_attack(self):
        attacker, target = _creature("Orc"), _creature("Cleric")
        target.active_buffs.append(_ward(dc=13))
        hit = _swing(attacker, target, roll=5)      # save 5+0 < 13
        assert hit.hit is False
        assert any("the attack is lost" in e.message for e in hit.events)
        assert target.current_hit_points == 40

    def test_passed_save_attacks_normally(self):
        attacker, target = _creature("Orc"), _creature("Cleric")
        target.active_buffs.append(_ward(dc=13))
        hit = _swing(attacker, target, roll=15)     # save 15 >= 13, then 17 vs 12
        assert hit.hit is True

    def test_attacking_breaks_your_own_ward(self):
        attacker, target = _creature("Cleric"), _creature("Orc")
        attacker.active_buffs.append(_ward(dc=13))
        _swing(attacker, target, roll=15)
        assert attacker.active_buffs == []          # ward ended by attacking
