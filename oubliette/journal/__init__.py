"""The player journal — player-owned notes, deliberately INVISIBLE to the DM.

It is never read into the model's context. That's a feature: the player can record
their own version of events (quests, NPCs, locations, bestiary notes) without
risking model hallucination from player-asserted "facts", and without bloating the
context. It persists in its own table, separate from the authoritative event log.
"""
