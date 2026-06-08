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
    def install_pc(self, char: Character) -> None: ...

    # --- protected mutators (dispatcher- and combat-boundary-only) ---
    def adjust_gold(self, char_id: str, delta: int) -> None: ...
    def add_item(self, char_id: str, item_id: str, qty: int) -> None: ...
    def remove_item(self, char_id: str, item_id: str, qty: int) -> None: ...
    def set_hp(self, char_id: str, value: int) -> None: ...
    def adjust_xp(self, char_id: str, amount: int) -> None: ...
    def set_conditions(self, char_id: str, conditions: list[str]) -> None: ...


class InMemoryRepository:
    """Phase 0 store. Plain dicts; swapped for SQLite in Phase 2."""

    def __init__(self, characters: list[Character], items: list[Item], pc_id: str):
        self._chars: dict[str, Character] = {c.id: c for c in characters}
        self._items: dict[str, Item] = {i.id: i for i in items}
        self._pc_id = pc_id

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
        try:
            return self._items[item_id]
        except KeyError:
            raise StateError(f"no such item: {item_id!r}")

    def resolve_item_id(self, ref: str) -> str:
        """Map an item reference (id OR display name, loosely) to its canonical id.
        Lets the DM name an item by its prose label — exact id/name first, then a
        word-subset fallback (so 'belt' resolves 'sturdy belt' when unambiguous)."""
        if ref in self._items:
            return ref
        norm = ref.strip().lower().replace("_", " ")
        for item in self._items.values():
            if item.name.strip().lower() == norm or item.id.replace("_", " ") == norm:
                return item.id
        # Fuzzy: the ref's words are a subset of exactly one item's name/id words.
        ref_words = set(norm.split())
        if ref_words:
            hits = [
                item.id for item in self._items.values()
                if ref_words <= set(item.name.lower().split())
                or ref_words <= set(item.id.replace("_", " ").split())
            ]
            if len(hits) == 1:
                return hits[0]
        raise StateError(f"no such item: {ref!r}")

    # --- protected mutators ---------------------------------------------------
    def adjust_gold(self, char_id: str, delta: int) -> None:
        c = self.get_character(char_id)
        if c.gold + delta < 0:
            raise StateError(
                f"{c.name} cannot afford this: has {c.gold}g, needs {-delta}g"
            )
        c.gold += delta

    def add_item(self, char_id: str, item_id: str, qty: int) -> None:
        if qty <= 0:
            raise StateError(f"add_item qty must be positive, got {qty}")
        self.get_item(item_id)  # validate it exists
        c = self.get_character(char_id)
        for stack in c.inventory:
            if stack.item_id == item_id:
                stack.qty += qty
                return
        c.inventory.append(ItemStack(item_id=item_id, qty=qty))

    def remove_item(self, char_id: str, item_id: str, qty: int) -> None:
        if qty <= 0:
            raise StateError(f"remove_item qty must be positive, got {qty}")
        c = self.get_character(char_id)
        if c.item_qty(item_id) < qty:
            raise StateError(
                f"{c.name} does not hold {qty}x {item_id} (has {c.item_qty(item_id)})"
            )
        remaining = qty
        for stack in list(c.inventory):
            if stack.item_id == item_id:
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

    def install_pc(self, char: Character) -> None:
        """Replace the player character with a chargen-built one: drop the stopgap
        default-party PC(s) and make `char` the sole PC. PC-only for now (design
        §10.6), built to hold a party later."""
        for cid in [c.id for c in self._chars.values() if c.kind == "pc"]:
            del self._chars[cid]
        self._chars[char.id] = char
        self._pc_id = char.id
