"""The DM role (spec §9). Phase 0 collapses parser + router + DM into two calls
per turn (assess, resolve) behind the swappable `LLMClient`."""
