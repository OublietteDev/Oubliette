"""C3.x — the radial menu's Items/Abilities split: class abilities (Lay on
Hands, Wild Shape...) no longer masquerade as "Items"; only actions that came
from carried gear (source_item) do."""

from arena.gui.radial_menu import RadialMenu
from arena.models.actions import Action, ActionType, TargetType
from arena.models.character import PlayerCharacter


def _pc() -> PlayerCharacter:
    return PlayerCharacter(
        name="Sera", character_class="Paladin", max_hit_points=40,
        actions=[
            Action(name="Potion of Healing", description="drink",
                   action_type=ActionType.ACTION, target_type=TargetType.SELF,
                   healing="2d4+2", source_item="Potion of Healing",
                   source_item_id="potion_healing", uses_per_rest=1,
                   current_uses=1),
            Action(name="Lay on Hands", description="heal 5",
                   action_type=ActionType.ACTION,
                   target_type=TargetType.ONE_CREATURE, range=5, healing="5",
                   resource_cost={"lay_on_hands": 5}),
            Action(name="Wild Shape: Wolf", description="transform",
                   action_type=ActionType.ACTION, target_type=TargetType.SELF,
                   summon_creature="monsters/srd/wolf.json", is_wild_shape=True,
                   resource_cost={"wild_shape": 1}),
        ],
    )


def test_items_and_abilities_split_on_source_item():
    pc = _pc()
    items = [a.name for a in RadialMenu._get_item_actions(pc)]
    abilities = [a.name for a in RadialMenu._get_ability_actions(pc)]
    assert items == ["Potion of Healing"]
    assert abilities == ["Lay on Hands", "Wild Shape: Wolf"]


def test_utility_filter_still_excludes_attacks_and_spells():
    pc = _pc()
    pc.actions.append(Action(
        name="Bless", description="bless", action_type=ActionType.ACTION,
        target_type=TargetType.SELF, spell_level=1,
        resource_cost={"spell_slot_1": 1}))
    assert "Bless" not in [a.name for a in RadialMenu._get_ability_actions(pc)]


# ── Bonus-typed ability slot gating (the "Practiced Shove after a cast" bug) ──
#
# A BONUS_ACTION-typed entry stored in ``creature.actions`` (not
# ``bonus_actions``) — e.g. a forced-movement bonus — used to be greyed out the
# moment the *action* slot was spent, because the utility-slot gating hardcoded
# the action slot. It should track the *bonus* slot instead.

from pathlib import Path  # noqa: E402

from arena.combat.manager import CombatManager  # noqa: E402
from arena.models.character import Creature  # noqa: E402
from arena.models.encounter import Encounter, CombatantEntry  # noqa: E402


def _caster_with_bonus_shove() -> Creature:
    return Creature(
        name="Vesper", max_hit_points=40, is_player_controlled=True,
        actions=[
            Action(name="Practiced Shove", description="bonus push",
                   action_type=ActionType.BONUS_ACTION,
                   target_type=TargetType.ONE_ENEMY, range=60,
                   forced_movement_type="push", forced_movement_distance=10),
        ],
    )


def _shove_slot(menu: RadialMenu):
    menu._rebuild_slots()
    for slot in menu.all_slots:
        if slot.action is not None and slot.action.name == "Practiced Shove":
            return slot
    return None


def test_bonus_ability_slot_survives_action_spend():
    """Casting/using the action does NOT grey out a bonus-typed ability; only
    spending the bonus slot does."""
    enc = Encounter(
        name="ShoveGate", grid_width=10, grid_height=10,
        combatants=[
            CombatantEntry(creature_id="v", creature_data=_caster_with_bonus_shove(),
                           team="player", starting_position=(2, 2)),
            CombatantEntry(creature_id="e", creature_data=Creature(name="Foe", max_hit_points=30),
                           team="enemy", starting_position=(3, 2)),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    cm.roll_initiative()
    cm.begin_combat()
    # load_encounter generates ids from the display name, so resolve the real id.
    vid = next(i for i, c in cm.combatants.items() if c.team == "player")
    # Force Vesper active.
    for _ in range(40):
        if cm.active_combatant and cm.active_combatant.creature_id == vid:
            break
        cm.end_turn()
    assert cm.active_combatant.creature_id == vid

    menu = RadialMenu()
    menu.set_combat(cm)
    menu.open(vid)

    slot = _shove_slot(menu)
    assert slot is not None and not slot.is_disabled  # available at turn start

    # Spend the ACTION slot (as a spell cast would) — shove must stay enabled.
    cm.turn_resources.has_used_action = True
    slot = _shove_slot(menu)
    assert slot is not None and not slot.is_disabled

    # Spend the BONUS slot — now it greys out.
    cm.turn_resources.has_used_bonus_action = True
    slot = _shove_slot(menu)
    assert slot is not None and slot.is_disabled
