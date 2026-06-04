"""Per-turn state/scene context for the DM (fix for harness gap G2).

The model can't set a fair DC "by the NPC's shrewdness" or resolve a sale without
knowing who's present, their disposition, and the party's resources. This builds
a compact, readable snapshot injected into both the assess and resolve prompts.
It reads OPEN flavor (dispositions) + the protected sheet essentials — never
exposes internals the model shouldn't reason about as numbers it owns.
"""

from __future__ import annotations

from ..state.repository import Repository


def build_context(repo: Repository, scene: str = "", recent: list[str] | None = None) -> str:
    pc = repo.pc()
    # Show the item id alongside the name — tool calls need the id (gap G2b).
    inv = ", ".join(
        f"{s.qty}x {repo.get_item(s.item_id).name} [id: {s.item_id}]" for s in pc.inventory
    ) or "nothing"
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
    # Short-term continuity: what just happened, so the DM honors established
    # fiction and successful checks instead of re-litigating each turn (gap G5).
    if recent:
        lines.append("RECENT TURNS (oldest first — this already happened, treat as true):")
        for beat in recent:
            lines.append(f"  - {beat}")
    return "\n".join(lines)
