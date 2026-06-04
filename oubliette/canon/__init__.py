"""Canonization lifecycle (spec §11) + retrieval/memory.

The DM's long-term memory: world content it creates during play (NPCs, places,
lore) as `CanonRecord`s. New content is born `provisional` (kept but quarantined —
can't be load-bearing) and is `promote_canon`-d to `confirmed` on purpose. Entity
creation is event-sourced (D-OPEN-1), so the canon set rebuilds on replay exactly
like protected state. Retrieval (`CanonStore.search`) feeds relevant canon back
into the DM's context so it stays consistent across a session (closes gap G4).
"""
