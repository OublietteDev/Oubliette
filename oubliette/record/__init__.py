"""Phase 0 recording: a plain append-only debug log + the seeded RNG service.

IMPORTANT (spec §14): this is NOT the event-sourcing substrate yet — just
visibility. Phase 2 replaces `DebugLog` with the real event log (§4) and makes
the RNG record `ROLL` events. The RNG already routes ALL dice through one place
so that swap is a substitution.
"""
