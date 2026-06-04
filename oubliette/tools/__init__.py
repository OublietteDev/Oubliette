"""The tool surface (spec §5): the only doors into protected state.

The DM *emits* tool calls; the dispatcher *validates, applies, and records*
them. The player can never emit one. A validation failure mutates nothing.
"""
