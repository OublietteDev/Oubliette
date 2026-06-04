"""The model-as-parameter seam (spec §9).

Every LLM-backed role depends on the `LLMClient` protocol, never on a concrete
provider. Day one uses one client for every role; later you swap a cheap model
into one role without touching its logic.
"""
