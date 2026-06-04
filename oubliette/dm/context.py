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


def build_context(repo: Repository, scene: str = "", recent: list[str] | None = None,
                  canon: list[CanonRecord] | None = None) -> str:
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
    npcs = repo.npcs()
    if npcs:
        lines.append("PRESENT (NPCs you may reference by id):")
        for n in npcs:
            note = n.disposition or n.description or "no notes"
            lines.append(f"  - {n.name} (id: {n.id}) — {note}; carries {n.gold}g.")
    # Long-term memory: world canon relevant to this turn, retrieved by keyword
    # (gap G4). Stay consistent with these; provisional canon is soft.
    if canon:
        lines.append("RELEVANT CANON (established world facts — stay consistent):")
        for r in canon:
            text = (r.text[:160] + "…") if len(r.text) > 160 else r.text
            lines.append(f"  - [{r.status}] {r.entity_type} '{r.name}' (id: {r.id}){': ' + text if text else ''}")
    # Short-term continuity: what just happened, so the DM honors established
    # fiction and successful checks instead of re-litigating each turn (gap G5).
    if recent:
        lines.append("RECENT TURNS (oldest first — this already happened, treat as true):")
        for beat in recent:
            lines.append(f"  - {beat}")
    return "\n".join(lines)
