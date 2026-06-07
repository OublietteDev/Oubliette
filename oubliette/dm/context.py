"""Per-turn state/scene context for the DM (fix for harness gap G2).

The model can't set a fair DC "by the NPC's shrewdness" or resolve a sale without
knowing who's present, their disposition, and the party's resources. This builds
a compact, readable snapshot injected into both the assess and resolve prompts.
It reads OPEN flavor (dispositions) + the protected sheet essentials — never
exposes internals the model shouldn't reason about as numbers it owns.
"""

from __future__ import annotations

from ..canon.models import CanonRecord
from ..state.repository import Repository

LORE_MAX = 3        # most lore entries surfaced in one turn's context
LORE_CHARS = 1200   # per-entry budget — generous (lore is meant to be retold, not clipped)


def _reachable(location: str | None, places: dict) -> list:
    """Places the party can travel to from `location`: its explicit exits, its
    sublocations (children), and its siblings (same parent). Returns PlaceNodes."""
    if location is None or location not in places:
        return []
    here = places[location]
    ids: set[str] = set(here.exits)
    ids |= {pid for pid, n in places.items() if n.parent == location}      # children
    if here.parent is not None:
        ids |= {pid for pid, n in places.items() if n.parent == here.parent}  # siblings
    ids.discard(location)
    return [places[i] for i in ids if i in places]


def build_context(repo: Repository, scene: str = "", recent: list[str] | None = None,
                  canon: list[CanonRecord] | None = None, location: str | None = None,
                  places: dict | None = None) -> str:
    pc = repo.pc()
    # Show the item id (tool calls need it, gap G2b) + an advisory value anchor for
    # the soft economy (the DM asked for a pricing reference; it's not enforced).
    def _item_label(item_id: str, qty: int) -> str:
        item = repo.get_item(item_id)
        worth = f", ~{item.base_value}g" if item.base_value else ""
        return f"{qty}x {item.name} [id: {item_id}{worth}]"

    inv = ", ".join(_item_label(s.item_id, s.qty) for s in pc.inventory) or "nothing"
    lines: list[str] = []
    if scene:
        lines.append(f"SCENE: {scene}")
    lines.append(
        f"PARTY: {pc.name} (id: {pc.id}) — {pc.hp}/{pc.max_hp} HP, {pc.gold}g, {pc.xp} XP; "
        f"carrying {inv}."
    )
    # Only NPCs whose home is the party's current location are "present" in the
    # scene — this keeps the prompt scoped as the cast grows. An NPC with no home
    # is "nowhere in particular" and isn't placed in any scene. Everyone remains
    # retrievable via canon search regardless of where they are. When no location
    # is known (e.g. a custom seed with no pack), fall back to showing all NPCs.
    npcs = repo.npcs()
    if location is not None:
        npcs = [n for n in npcs if n.home_location == location]
    if npcs:
        lines.append("PRESENT (NPCs you may reference by id):")
        for n in npcs:
            note = n.disposition or n.description or "no notes"
            # Surface a merchant's priced stock so the DM can negotiate (it was
            # "blind to the trade window contents" otherwise).
            stock = ""
            if n.price_list:
                in_stock = {s.item_id for s in n.inventory if s.qty > 0}
                items = [f"{repo.get_item(i).name} {p}g"
                         for i, p in list(n.price_list.items())[:8] if i in in_stock]
                if items:
                    stock = "; sells " + ", ".join(items)
            lines.append(f"  - {n.name} (id: {n.id}) — {note}; carries {n.gold}g{stock}.")
    # Where the party can travel from here (exits, sublocations, neighbours). The DM
    # moves them with the travel tool, naming the destination by id.
    dests = _reachable(location, places or {})
    if dests:
        lines.append("WHERE YOU CAN GO (travel here with the travel tool, by id):")
        for d in sorted(dests, key=lambda p: p.name):
            lines.append(f"  - {d.name} (id: {d.id})")
    # Long-term memory: world canon relevant to this turn, retrieved by keyword
    # (gap G4). Stay consistent with these; provisional canon is soft.
    if canon:
        lore_hits = [r for r in canon if r.entity_type == "lore"]
        other = [r for r in canon if r.entity_type != "lore"]
        # Authored history/legend gets a generous budget (a few entries, near-full
        # text) so the DM can actually retell it, not a clipped snippet.
        if lore_hits:
            lines.append("WORLD LORE (established history/legend — treat as true; weave in as it fits):")
            for r in lore_hits[:LORE_MAX]:
                text = (r.text[:LORE_CHARS] + "…") if len(r.text) > LORE_CHARS else r.text
                lines.append(f"  - {r.name}: {text}")
        if other:
            lines.append("RELEVANT CANON (established world facts — stay consistent):")
            for r in other:
                text = (r.text[:160] + "…") if len(r.text) > 160 else r.text
                lines.append(f"  - [{r.status}] {r.entity_type} '{r.name}' (id: {r.id}){': ' + text if text else ''}")
    # Short-term continuity: what just happened, so the DM honors established
    # fiction and successful checks instead of re-litigating each turn (gap G5).
    if recent:
        lines.append("RECENT TURNS (oldest first — this already happened, treat as true):")
        for beat in recent:
            lines.append(f"  - {beat}")
    return "\n".join(lines)
