"""Authoritative state: the single source of truth.

In Phase 0 this is in-memory plain objects behind the `Repository` interface, so
Phase 2 can swap in SQLite + event sourcing as a substitution, not a rewrite
(spec §14). The repository is the ONLY writer of protected state — that's the
firewall (spec §3.1), enforced structurally because nothing else exposes mutators.
"""
