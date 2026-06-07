"""Quests: the game's official record of the party's goals.

Distinct from the player journal (private, DM-invisible notes) and from canon
(world facts): a quest is authoritative state the CODE owns — the DM proposes
"start this", "note this", "this is done", and the runtime records it. Quests are
event-sourced like protected state, so a reload rebuilds them exactly.

Scope (per design): EMERGENT quests the DM creates in play, SIMPLE shape (a goal
with a status + running notes). Rewards are ordinary give/transact tool calls, so
they stay flexible (and renegotiable). No player panel yet — the DM tracks them
and weaves them into narration.
"""
