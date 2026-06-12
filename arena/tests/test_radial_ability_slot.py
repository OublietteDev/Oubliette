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
