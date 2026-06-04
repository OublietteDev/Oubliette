"""Combat subsystem — Phase 1 BOUNDARY only (spec §8, §10, §14 Phase 1).

What's real here: the edges. A declarative `EncounterRequest` comes in; code
instantiates combatants from templates + LIVE authoritative state (ephemeral by
default, D5); a placeholder engine auto-resolves; a `CombatResult` carrying
ABSOLUTE final values (D7) goes out and is applied to state as one recorded
result. Non-combat exits (parley/flee/...) are first-class outcomes.

What's deliberately a placeholder: the tactical internals (hex grid, action
economy, conditions, reactions). The revived prototype slots in behind
`engine.auto_resolve` later without changing the boundary.
"""
