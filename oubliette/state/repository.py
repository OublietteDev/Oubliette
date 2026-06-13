"""The repository: the only writer of protected state.

`Repository` is a Protocol so Phase 2 can drop in a SQLite-backed implementation
behind the same seam (decision D1). The protected mutators (`adjust_gold`,
`add_item`, `remove_item`) raise on an illegal change rather than silently
clamping — the dispatcher turns those raises into the retry path (D6).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import Character, Item, ItemStack


class StateError(Exception):
    """A protected-state mutation that cannot be satisfied (insufficient funds,
    item not held, ...). Surfaces to the dispatcher as a validation failure."""


@runtime_checkable
class Repository(Protocol):
    def pc(self) -> Character: ...
    def party(self) -> list[Character]: ...
    def get_character(self, char_id: str) -> Character: ...
    def get_item(self, item_id: str) -> Item: ...
    def resolve_item_id(self, ref: str) -> str: ...
    def npcs(self) -> list[Character]: ...
    def set_equipped(self, char_id: str, item_ids: list[str]) -> None: ...
    def register_item(self, item: Item) -> None: ...
    def set_fallback_catalog(self, items: dict[str, Item]) -> None: ...
    def install_pc(self, char: Character) -> None: ...
    def install_party(self, chars: list[Character]) -> None: ...
    def replace_character(self, char: Character) -> None: ...
    def set_slots_used(self, char_id: str, mapping: dict) -> None: ...
    def set_hit_dice_used(self, char_id: str, value: int) -> None: ...
    def set_resources_used(self, char_id: str, mapping: dict) -> None: ...
    def set_max_hp(self, char_id: str, value: int) -> None: ...
    def set_level(self, char_id: str, value: int) -> None: ...
    def set_portrait(self, char_id: str, filename: str | None) -> None: ...

    # --- protected mutators (dispatcher- and combat-boundary-only) ---
    def adjust_gold(self, char_id: str, delta: int) -> None: ...
    def add_item(self, char_id: str, item_id: str, qty: int, spell: str | None = None,
                 spell_level: int | None = None) -> None: ...
    def remove_item(self, char_id: str, item_id: str, qty: int, spell: str | None = None,
                    spell_level: int | None = None) -> None: ...
    def set_hp(self, char_id: str, value: int) -> None: ...
    def adjust_xp(self, char_id: str, amount: int) -> None: ...
    def set_conditions(self, char_id: str, conditions: list[str]) -> None: ...


class InMemoryRepository:
    """Phase 0 store. Plain dicts; swapped for SQLite in Phase 2."""

    def __init__(self, characters: list[Character], items: list[Item], pc_id: str):
        self._chars: dict[str, Character] = {c.id: c for c in characters}
        self._items: dict[str, Item] = {i.id: i for i in items}
        # The global SRD equipment catalog, attached at session open. A second-tier
        # lookup so the DM can `give`/reference ANY SRD item, while the lean campaign
        # catalog (`_items`) keeps PRECEDENCE — exact names and short abbreviations still
        # resolve to pack/owned items, not the hundreds of SRD entries (A5).
        self._fallback: dict[str, Item] = {}
        self._pc_id = pc_id

    def set_fallback_catalog(self, items: dict[str, Item]) -> None:
        self._fallback = dict(items)

    def pc(self) -> Character:
        return self._chars[self._pc_id]

    def party(self) -> list[Character]:
        return [c for c in self._chars.values() if c.kind == "pc"]

    def npcs(self) -> list[Character]:
        return [c for c in self._chars.values() if c.kind == "npc"]

    def get_character(self, char_id: str) -> Character:
        try:
            return self._chars[char_id]
        except KeyError:
            raise StateError(f"no such character: {char_id!r}")

    def get_item(self, item_id: str) -> Item:
        item = self._items.get(item_id) or self._fallback.get(item_id)
        if item is None:
            raise StateError(f"no such item: {item_id!r}")
        return item

    def resolve_item_id(self, ref: str) -> str:
        """Map an item reference (id OR display name, loosely) to its canonical id.
        Lets the DM name an item by its prose label — exact id/name first, then a
        word-subset fallback (so 'belt' resolves 'sturdy belt' when unambiguous).
        The campaign catalog is tried first and wins; only if it has no match do we
        consult the global SRD catalog — so the rich SRD set never makes a short,
        pack-specific abbreviation ambiguous."""
        for catalog in (self._items, self._fallback):
            hit = self._resolve_in(catalog, ref)
            if hit is not None:
                return hit
        raise StateError(f"no such item: {ref!r}")

    @staticmethod
    def _resolve_in(catalog: dict[str, Item], ref: str) -> str | None:
        if ref in catalog:
            return ref
        norm = ref.strip().lower().replace("_", " ")
        for item in catalog.values():
            if item.name.strip().lower() == norm or item.id.replace("_", " ") == norm:
                return item.id
        # Fuzzy: the ref's words are a subset of exactly one item's name/id words.
        ref_words = set(norm.split())
        if ref_words:
            hits = [
                item.id for item in catalog.values()
                if ref_words <= set(item.name.lower().split())
                or ref_words <= set(item.id.replace("_", " ").split())
            ]
            if len(hits) == 1:
                return hits[0]
        return None

    # --- protected mutators ---------------------------------------------------
    def adjust_gold(self, char_id: str, delta: int) -> None:
        c = self.get_character(char_id)
        if c.gold + delta < 0:
            raise StateError(
                f"{c.name} cannot afford this: has {c.gold}g, needs {-delta}g"
            )
        c.gold += delta

    def add_item(self, char_id: str, item_id: str, qty: int, spell: str | None = None,
                 spell_level: int | None = None) -> None:
        if qty <= 0:
            raise StateError(f"add_item qty must be positive, got {qty}")
        self.get_item(item_id)  # validate it exists
        c = self.get_character(char_id)
        for stack in c.inventory:               # stack identity is (item_id, spell, spell_level)
            if stack.item_id == item_id and stack.spell == spell and stack.spell_level == spell_level:
                stack.qty += qty
                return
        c.inventory.append(ItemStack(item_id=item_id, qty=qty, spell=spell, spell_level=spell_level))

    def remove_item(self, char_id: str, item_id: str, qty: int, spell: str | None = None,
                    spell_level: int | None = None) -> None:
        if qty <= 0:
            raise StateError(f"remove_item qty must be positive, got {qty}")
        c = self.get_character(char_id)
        have = c.variant_qty(item_id, spell, spell_level)   # the exact variant
        if have < qty:
            raise StateError(f"{c.name} does not hold {qty}x {item_id} (has {have})")
        remaining = qty
        for stack in list(c.inventory):
            if stack.item_id == item_id and stack.spell == spell and stack.spell_level == spell_level:
                take = min(stack.qty, remaining)
                stack.qty -= take
                remaining -= take
                if stack.qty == 0:
                    c.inventory.remove(stack)
                if remaining == 0:
                    break

    def set_hp(self, char_id: str, value: int) -> None:
        """Absolute HP write (D7). Clamped to [0, max_hp]."""
        c = self.get_character(char_id)
        c.hp = max(0, min(value, c.max_hp))

    def adjust_xp(self, char_id: str, amount: int) -> None:
        if amount < 0:
            raise StateError(f"adjust_xp expects a non-negative award, got {amount}")
        self.get_character(char_id).xp += amount

    def set_conditions(self, char_id: str, conditions: list[str]) -> None:
        """Absolute condition set (D7)."""
        self.get_character(char_id).conditions = list(conditions)

    def set_equipped(self, char_id: str, item_ids: list[str]) -> None:
        """Absolute equipped loadout (item ids the character wears/wields)."""
        self.get_character(char_id).equipped = list(item_ids)

    # --- chargen seams (CHARACTER_CREATED apply/replay) -----------------------
    def register_item(self, item: Item) -> None:
        """Add an item to the campaign catalog. Idempotent: a created character's
        granted SRD gear is registered here (design §2.1), and replay re-registers
        it, so a repeated id simply overwrites with the same definition."""
        self._items[item.id] = item

    def install_party(self, chars: list[Character]) -> None:
        """Replace the player party with chargen-built characters: drop the stopgap
        default-party PC(s) and install the given list, the FIRST becoming the lead PC
        (the one `pc()` returns). Used at game start when the player builds their party."""
        for cid in [c.id for c in self._chars.values() if c.kind == "pc"]:
            del self._chars[cid]
        for c in chars:
            self._chars[c.id] = c
        if chars:
            self._pc_id = chars[0].id

    def install_pc(self, char: Character) -> None:
        """Replace the whole party with a single chargen-built PC (the one-character
        case of `install_party`). Kept for legacy single-PC saves."""
        self.install_party([char])

    def replace_character(self, char: Character) -> None:
        """Swap ONE character in place (level-up: CHARACTER_LEVELED), preserving the
        rest of the party and the lead-PC pointer. The character is stored whole, never
        re-derived (D9)."""
        self._chars[char.id] = char

    # --- rest / level-up trackers (CS5; absolute writes, D7) ------------------
    def set_slots_used(self, char_id: str, mapping: dict) -> None:
        self.get_character(char_id).spell_slots_used = {int(k): v for k, v in mapping.items()}

    def set_hit_dice_used(self, char_id: str, value: int) -> None:
        self.get_character(char_id).hit_dice_used = max(0, value)

    def set_resources_used(self, char_id: str, mapping: dict) -> None:
        self.get_character(char_id).resources_used = dict(mapping)

    def set_max_hp(self, char_id: str, value: int) -> None:
        c = self.get_character(char_id)
        c.max_hp = max(1, value)
        c.hp = min(c.hp, c.max_hp)

    def set_level(self, char_id: str, value: int) -> None:
        self.get_character(char_id).level = max(1, value)

    def set_portrait(self, char_id: str, filename: str | None) -> None:
        """Attach (or clear, with None) a PC's portrait token. Event-sourced via
        PORTRAIT_SET so the reference survives replay; the image bytes live on disk."""
        self.get_character(char_id).portrait = filename
