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
    def get_character(self, char_id: str) -> Character: ...
    def get_item(self, item_id: str) -> Item: ...

    # --- protected mutators (dispatcher-only) ---
    def adjust_gold(self, char_id: str, delta: int) -> None: ...
    def add_item(self, char_id: str, item_id: str, qty: int) -> None: ...
    def remove_item(self, char_id: str, item_id: str, qty: int) -> None: ...


class InMemoryRepository:
    """Phase 0 store. Plain dicts; swapped for SQLite in Phase 2."""

    def __init__(self, characters: list[Character], items: list[Item], pc_id: str):
        self._chars: dict[str, Character] = {c.id: c for c in characters}
        self._items: dict[str, Item] = {i.id: i for i in items}
        self._pc_id = pc_id

    def pc(self) -> Character:
        return self._chars[self._pc_id]

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
