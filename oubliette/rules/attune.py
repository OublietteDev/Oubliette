"""Attunement (multiplayer pre-work): the SRD's three-item bond, enforced.

An item flagged `requires_attunement` grants NOTHING until its bearer attunes
to it, and a character holds at most MAX_ATTUNED bonds at once. Attuning — and
ending a bond — is a rest-time ritual: the rest popup collects each hero's
choices and the resulting `attune` ops ride the same REST_TAKEN event,
replay-safe. If an attuned item leaves a hero's hands outside a rest (a
hand-over, a sale), the bond ends with it (ATTUNEMENT_CHANGED).

The requires-attunement flag lives in the session's merged mechanics catalog
(SRD + pack, module-kit S1); the bond list lives on the character
(`Character.attuned`, absolute writes, D7). Validation happens here on the
live path before any op is produced (D6); replay trusts the recorded list.
"""

from __future__ import annotations

from ..state.models import Character
from ..state.repository import StateError

MAX_ATTUNED = 3


def requires_attunement(catalog: dict | None, item_id: str) -> bool:
    """Whether this item is inert until attuned, per the mechanics catalog.
    An item the catalog doesn't know (a bare campaign item) never requires it."""
    eq = (catalog or {}).get(item_id)
    return bool(eq is not None and getattr(eq, "requires_attunement", False))


def attunable_carried(char: Character, catalog: dict | None) -> list[str]:
    """The distinct requires-attunement item ids this character carries, in
    inventory order — the choices the rest-time ritual offers them."""
    out: list[str] = []
    for stack in char.inventory:
        if stack.item_id not in out and requires_attunement(catalog, stack.item_id):
            out.append(stack.item_id)
    return out


def active_attuned(char: Character) -> list[str]:
    """The character's live bonds: attuned ids they still carry. A recorded bond
    to an item that has since left their hands is dead weight, never a benefit."""
    return [i for i in char.attuned if char.item_qty(i) > 0]


def validate_attunement(char: Character, catalog: dict | None,
                        item_ids: list[str]) -> list[str]:
    """Check a requested bond list on the live path and return it normalized
    (deduplicated, order kept). Raises StateError if an item isn't carried,
    doesn't require attunement, or the list exceeds MAX_ATTUNED."""
    def label(item_id: str) -> str:
        eq = (catalog or {}).get(item_id)
        return getattr(eq, "name", None) or item_id

    wanted: list[str] = []
    for item_id in item_ids:
        if item_id not in wanted:
            wanted.append(item_id)
    for item_id in wanted:
        if char.item_qty(item_id) <= 0:
            raise StateError(f"{char.name} is not carrying {label(item_id)}")
        if not requires_attunement(catalog, item_id):
            raise StateError(f"{label(item_id)} does not require attunement")
    if len(wanted) > MAX_ATTUNED:
        raise StateError(
            f"{char.name} can attune to at most {MAX_ATTUNED} items "
            f"(asked for {len(wanted)})")
    return wanted
