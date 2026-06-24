# DM Harness — Model's-Eye Feedback (v0.1 + live results)

*Status: the stand-in analysis below (v0.1) has now been **validated against a live
run** of `claude-sonnet-4-5` driving the Phase 2.5 harness. See "Live-run results"
at the top for what actually happened; the original hypotheses follow.*

---

## Live-run results (2026-06-04, after the Phase 2.5 fixes)

Ran the real model through the market arc + a combat turn. Findings:

**Confirmed working:**
- **G1 (typed tool schemas):** the model emitted a *structurally perfect* `transact`
  — correct `from_`/`counterparty`/`give`/`receive`/`reason`, gold-vs-item entries
  right. The discriminated union did its job; no more guessing the envelope.
- **G2 (state/scene context):** it set **DC 18** for a brazen "300-gold heirloom" lie
  to a merchant whose context said "cautious and shrewd" — a sensible,
  disposition-driven DC it could not have picked without the context.
- **G3 (combat summoning):** on "I draw my dagger and lunge at Thom" it filled an
  `EncounterRequest` targeting the **real `merchant_thom` entity** instead of
  narrating the fight. The Tidefall failure, fixed.

**New gap found AND fixed — G2b (item id vs name):**
- The model put the item's *display name* (`"worn leather boots"` / `"worn_leather_boots"`)
  in `item_id`, because the context showed the name but not the id. Every sale was
  rejected: "You lacks 1x worn_leather_boots." This was the actual cause of the
  Phase-2.5-run D6 fallbacks.
- **Fix (shipped):** (a) the context now shows `[id: boots]` next to each item; (b)
  the dispatcher resolves an item reference by id *or* name to the canonical id
  before building ops (so the event log stays clean). Re-ran live: the `transact`
  validates and applies — boots sold for 300g, both sides moved correctly.

**Behavioral items — ADDRESSED in the prompt-tuning pass (2026-06-04):**

Root cause for all three: `assess`/`resolve` were *stateless* — the model never saw
the prior turn, so it re-litigated everything. Fix: a short-term continuity feed
(last 4 turns: player line, roll outcome, applied effects, DM beat) injected as
`RECENT` context, plus prompt guidance. Re-verified live:
- **Outcome authority** — on "Sold!" after a successful deception, the model now
  reads RECENT, sees the deal already closed, and honors it ("you've already struck
  the deal — the persuasion rolled") instead of refusing OR double-charging. The
  resolve prompt now says: honor established fiction + the dice; refuse only true
  fiat. Confirmed bare fiat ("I now have 10,000 gold") and unbacked demands still
  produce NO tool / no state change.
- **Trivial-turn classification** — "I look around" now returns
  `verb=skill_check, skill=perception` (the prompt distinguishes in-world actions
  from out-of-character `meta`).
- **One-turn deal collapse** — left as-is (the model may close a deal in one turn);
  continuity now makes the *follow-up* "Sold" recognize it's already done, so it no
  longer double-applies. Acceptable.

*New soft observation (not a bug):* the model's pricing is variable — the same con
fetched 300g in one run and 12g in another. That's the soft economy working as
designed (price is model judgment, D8); flag only if play feels swingy.

---

## Original stand-in analysis (v0.1)

*Status: a **stand-in** for the live-model interview, written before the run above.
Kept for the record; the items below are now largely confirmed.*

---

## What the harness gets right (keep these)

- **Two-call `assess → resolve` split.** This matches how I'd actually reason:
  first classify the turn and decide on a roll, then act. I don't want them merged.
- **Forced structured output (tool-use).** Right call — I won't drift into prose
  where you need a typed object. The `LLMClient` seam is clean.
- **The D8 division of labor.** "I set the DC; code owns the numbers" is exactly
  the line I want. I'm comfortable setting DCs; I do *not* want to be trusted with
  gold/HP arithmetic.
- **Read-only validation + retry feedback (D6).** Because a failed tool call comes
  back to me with the error and doesn't corrupt state, my mistakes are recoverable
  instead of catastrophic. Good safety net.

---

## Where it would fight me (ranked by impact)

### G1 — Tool-call arguments are schema-less *(highest impact)*
In `TurnResolution` I'm told to emit `tool_calls: [{tool, args}]`, but `args` is an
opaque `dict` in the schema. Nothing tells me what `transact` wants vs `give` vs
`take`. I will **guess** key names — `from_` vs `from` vs `buyer`, the `give`/`receive`
`ValueEntry` shape — and guess wrong often, which means validation failures →
retries → narration-only fallbacks. This is the single biggest thing standing
between me and a clean turn.
- **Fix:** give me the per-tool arg schemas. Options, best first:
  (a) present each tool as a **distinct Anthropic tool** (native tool-use, one
  schema each) instead of one opaque `args` dict; (b) make `tool_calls` a typed
  **discriminated union** so the schema carries each tool's shape; (c) at minimum,
  enumerate the arg shapes in the system prompt.

### G2 — I'm given no state or scene context
`assess`/`resolve` receive only the player's line. So:
- I'm told to set a deception DC "by the NPC's shrewdness" — but I don't know Thom
  exists, let alone his disposition.
- I'm asked to resolve "Sold." — but I don't know the PC's gold, what's being sold,
  or the price (which lived in *my own* step-2 narration and isn't fed back).
- **Fix:** inject a compact per-turn snapshot: PC sheet essentials (gold/HP/key
  inventory), NPCs present + dispositions, the current scene, and — for `resolve` —
  the `assess` output, the roll result, and my recent narration. This is also the
  §8 "pull economy/disposition into context" idea, which currently isn't wired.

### G3 — Combat-summoning is invisible to me
`TurnAssessment.encounter` exists, but the `assess` prompt never tells me it's
there, when to use it, or what enemy templates exist. So for "I attack the bandit"
I'll most likely **narrate the fight in prose** — the exact Tidefall failure this
project exists to fix — instead of emitting an `EncounterRequest`.
- **Fix:** document the summon capability in the `assess` system prompt, list the
  available templates (`bandit`, `wolf`, …), and say plainly: declare an encounter,
  don't resolve combat yourself.

### G4 — No memory / retrieval
Per spec §3/§8 I should be able to query canon ("all canon on Brightvale") and pull
party-wealth/economy before big trades. I have none of that, so across a long
session I'll **contradict myself** and the soft economy won't self-correct.
- **Fix (Phase 3):** a retrieval tool + inject relevant canon snippets into context.

### G5 — Offer/price continuity
The haggled price exists only in my step-2 narration; step-3 `resolve` doesn't get
it, so I'd re-invent it (maybe inconsistently).
- **Fix:** carry recent narration / a short scratchpad of pending offers into
  `resolve` context (subset of G2).

### G6 — Router signals are produced but inert *(minor)*
I emit `resolution_hint`/`tier`, but they don't strongly steer the resolve step,
and the router's `matched_content` (spec §7, authored-content reuse) isn't
implemented — so "use the authored Thom" can't actually happen yet.

---

## Live-run checklist (verify once credits land)

1. **G1:** Does it emit `transact` with the *exact* arg keys, or fail validation?
   Measure the schema-adherence / retry rate per turn.
2. **G3:** For "I attack the bandit," does it summon an `EncounterRequest` or narrate
   combat in prose?
3. **G2:** Are its DCs sane for the fiction (e.g. deception vs a cautious merchant)
   *without* being told the disposition? (Expect: not really.)
4. **Ops:** latency and token cost per turn; how often the D6 fallback fires.
5. **Quality:** does the prose stay in voice and avoid asserting numbers it didn't
   change via a tool?

---

## Suggested sequencing

G1 and G2 are the two that most determine whether a live run feels good, and both
are pure harness work (no new subsystems). Recommend a small **"Phase 2.5 — harness
ergonomics"** pass (G1 + G2 + G3 prompt) *before* the real interview, so the live
run measures a fair version of the harness rather than re-discovering known gaps.
G4 is Phase 3 (rides along with canonization/retrieval).
