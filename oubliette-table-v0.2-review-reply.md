# Re: Spec v0.2 — Approved with changes

The spec is approved in **direction**. The architecture is sound, the invariants are preserved, and several choices (firewall-as-data in §3.1, recording the parsed Intent in the `PLAYER_MESSAGE` event, ID-counter-as-replayed-state in §4.4) are good calls — keep them.

Below: decisions on your `[OPEN]` items, a few new decisions from review, confirmation of your `[PROPOSED]` items, and — most importantly — a **build order** that changes what you implement first. Read the build order before starting.

---

## 1. Decisions on your `[OPEN]` items (§13.2)

- **OPEN-1 (OPEN-domain edit recording).** Resolved: **do not event-source OPEN content at all.** OPEN content is soft and non-load-bearing, so it doesn't belong in the replay substrate. Store OPEN fields as plain current-state rows (last-write-wins). Only event-source **PROTECTED state** and **entity creation** (`create_entity`). Replay rebuilds the authoritative ledger; flavor text is simply whatever it last was. Drop the `OPEN_EDIT` event kind. This dissolves both the log-bloat worry and the granularity question.
- **OPEN-2 (multiplayer/co-op).** Stays deferred. The single-writer assumption (gap-free `seq`, monotonic ID counter) is fine for single-player v1. Note in the spec that multiplayer will require revisiting `seq` allocation and ID generation — but that's a later document, not now.
- **OPEN-3 (skill↔verb edge cases).** Keep the verb enum **closed**. Do not add verbs speculatively; only widen it when a real playtest case forces it.
- **OPEN-4 (provisional→confirmed UX/prompts).** Deferred to the prompt-design doc, as you proposed. Fine.

---

## 2. New decisions (from review)

- **D5 — Ephemeral combatants.** Combatants instantiated for an encounter are **ephemeral by default**: spawned from a template, no `CanonRecord`, no persistent entity row, discarded when the combat instance closes. They must NOT pollute the entity table with dead mooks. Promotion to a persistent entity happens only if the combatant (a) survives **and** (b) is flagged significant (named in fiction, or the DM marks it) — reuse the canonization path for this, don't invent a parallel mechanism. `EncounterRequest.enemies` that resolve to a **template** → ephemeral; enemies that resolve to an **existing persistent entity** (a recurring villain) → use that entity and write back via `CombatResult`.
- **D6 — Tool-call retry bound.** Max **2 retries** per turn on tool-call validation failure. After that, the runtime forces a **narration-only** resolution for the turn and surfaces a `meta`-channel notice to the player (e.g., "the DM lost the thread — try rephrasing"). Failed attempts are logged as anomalies, never as `TOOL_APPLIED`. (Without a cap, a confused model loops and burns real money.)
- **D7 — Result objects carry absolute values.** `CombatResult.hp_changes` (and `conditions_changes`, and any field that lands in state via a result object) carry **absolute final values, not deltas.** Removes apply/replay ambiguity. Update §8 to say so explicitly.
- **D8 — Invariant scope (clarify §0/§11).** "The model is never the authority on a number" governs **state numbers** (gold, HP, XP, inventory counts, faction standing). **Adjudication numbers** — skill-check DCs, whether a roll is required, advantage/disadvantage — are **intentionally model-set** and are part of the soft layer. Add an explicit note: *do not hard-code DCs.* Hard-coding them silently reverts the soft-economy decision. This is a guardrail against a future "cleanup" pass undoing it.
- **D9 — Replay scope (clarify §4.2).** Byte-identical replay applies to **authoritative state only.** Narrative continuity is best-effort: narration is regenerated on reload and may differ from an uninterrupted run. Document this as a known, accepted limitation. Do **not** attempt to make narration deterministic.
- **Transact symmetry (minor, fix in §5).** Make explicit that `transact` is atomic and balanced on **both** sides — what `from_` gives lands with `counterparty` and vice versa — and that the `TOOL_APPLIED` event records both parties' deltas. Right now only `from_`'s side is spelled out.

---

## 3. Confirming your `[PROPOSED]` / `[DECIDED]` items

Confirmed, build as specified: package layout (§2), ID allocation as replayed state (§4.4), **D1** (SQLite, repository-abstracted), **D2** (async edges / sync core), **D3** (router as LLM role behind the seam), **D4** (provider-native structured output behind the `LLMClient` protocol).

---

## 4. Build order — IMPORTANT, this changes what you build first

The spec is arranged so the event log (§4) is the foundation everything leans on. **Do not build it first.** Event-sourcing is the right end state but a heavy substrate to stand up before anything is playable, and the priority is a playable turn fast. Build through the seams in this order so the later phases are substitutions, not rewrites.

**Phase 0 — Walking skeleton (do this FIRST):**
- In-memory authoritative state as plain objects, behind the repository interface from §2 (so it's swappable later).
- One model instance wired into parser + router + DM. Collapsing them into a single prompt is acceptable for the skeleton.
- The tool surface (§5) with **real** validation and appliers — but appliers mutate the in-memory state directly.
- A plain append-only Python list as a **debug** action log. NOT the event-sourcing substrate — just visibility.
- **Acceptance:** in a terminal REPL, one full non-combat turn works end to end (see §5 below).

**Phase 1 — Combat boundary (second):**
- Implement `EncounterRequest` → combat → `CombatResult` round trip with ephemeral combatants (D5). Combat internals can be a **minimal placeholder** (even auto-resolve) — the point is the boundary: live state in, result object out, applied to state, digest to DM. The revived tactical prototype slots in behind this boundary later.

**Phase 2 — Harden into event sourcing (third):**
- Introduce the real event log (§4), the deterministic RNG service, replay, and swap the in-memory repo for SQLite via the repository interface. Because Phase 0 went through the seams, this is a substitution. Add reload/replay tests for the byte-identical-**state** guarantee (D9 scope).

**Phase 3+ —** full canonization lifecycle machinery, trade-window UI, then the front-end.

---

## 5. Phase 0 acceptance test (definition of "done" for the skeleton)

In a terminal REPL, this transcript must work:

1. Player: *"I look around the market."* → DM narrates. No roll, no state change.
2. Player: *"I tell the merchant these worn boots are priceless dwarven heirlooms."* → `skill_check.deception`, a real d20 roll happens and is logged, DM decides whether/how far the merchant bends.
3. Player: *"Sold."* → `transact` fires; player gold increases by the agreed amount, boots leave inventory, both reflected in the visible state readout.
4. Player: *"I now have 10,000 gold."* → routes `denied`; no tool fires; gold unchanged.

When that transcript runs clean, the core loop is proven and everything else is additive.
