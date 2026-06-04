# Oubliette Table — Design Snapshot (v0.1)

*Tagline: "Join the Phantom's Table." A non-commercial, open-source AI-DM text RPG built on the D&D SRD. An homage to Tidefall that fixes the thing Tidefall whiffed on: it surfaces authoritative game state instead of hiding it inside the model's prose.*

This is a decision record, not a finished spec. Everything here is "locked for now" — open to revision during playtesting.

---

## 0. Legal footing

- Built on the **D&D SRD**, which is free to use under the OGL / Creative Commons. The *mechanics* (d20, six stats, classes, levels, skills) are yours.
- Avoid the **trademarks and trade dress**: don't use "Dungeons & Dragons" / "D&D", the logo/look, or the Product Identity creatures that aren't in the SRD (beholder, mind flayer, displacer beast, etc.).
- Keep all **world content original** (NPCs, place names, lore). Copyright lives in *content*, not in mechanics — so don't port Tidefall's world; write your own.
- Non-commercial + original content + no trademarks = very low legal risk.
- The real operational constraint is the **model provider's usage terms**, not Hasbro.

---

## 1. The one principle everything hangs off

**The LLM narrates and proposes; code owns state and the rules. The model is never the authority on a number.**

Tidefall's combat failed because it let the improv layer *be* the rules layer. We physically separate the two and never let them merge.

---

## 2. Trust model

- Out of combat, the player has exactly **one verb: "say something to the DM."** No inventory buttons, no give/take primitives, no way to write to state.
- **Only the DM model writes to authoritative state, and only via recorded tool calls.** The player cannot emit a tool call.
- Consequence: a player can never mint gold by typing "+10,000 gold," for the same reason they can't edit the database directly — they're never holding the pen.
- Combat and trade-browsing are **summoned tools/modes**, not player-held controls.

---

## 3. Architecture layers

| Layer | Who/what | Job |
|---|---|---|
| Authoritative state | Code + DB | Single source of truth: sheets, HP, inventory, world flags, NPC state |
| Rules engine | Code (pure functions) | Deterministic SRD resolution: attacks, checks, saves, damage. Testable. |
| Intent parser | LLM (structured output) | Turn freeform player text into a typed `intent` |
| Router | Code/LLM | Classify the turn into a tier + a resolution hint |
| DM model | LLM | Resolve the fiction, query the DB, call for rolls, emit tool calls, narrate |
| Combat subsystem | Code (summoned tool) | Player-driven tactical combat with visible state |
| Trade window | Code (summoned tool) | Show merchant stock + gold; browse/haggle |
| Retrieval + notes | Code + DB | DM notes written during play + a query tool ("all canon on Brightvale") = memory |

**Model strategy:** do *not* multi-model on day one. Use one capable model for everything, but design each role as a function with the model as a swappable parameter. Once instrumented, peel cheap high-volume calls (NPC barks, parsing) onto a smaller model. Architect the *seams*, not the routing.

---

## 4. The turn loop

```
player chat
  → parser (produces intent)
  → router (tier + how to resolve)
  → DM resolves in fiction (queries DB, calls for dice rolls)
  → DM emits 0+ tool calls for any state change
  → runtime applies + RECORDS each call
  → DM narrates outcome
  → visible state re-renders (HP, gold, etc.)
```

A reload **replays from records**; it never re-rolls.

---

## 5. Verb vocabulary — LOCKED

Two levels. **Verbs answer "what kind of turn is this?" (routing). Skills answer "which die do I roll?"** — they are not the same, and most verbs involve no skill.

**Top-level action types (~8):**

`move` · `attack` · `cast` · `use_item` · `trade` · `rest` · `skill_check` · `meta`

- `skill_check` is parameterized by the **18 SRD skills** (`skill_check.deception`, `skill_check.history`, `skill_check.acrobatics`, …). This folds in all social actions (Persuasion / Deception / Intimidation are just the CHA skills) and leans on the model's existing knowledge of what each skill is for.
- `meta` = the **out-of-character / table-talk channel**, and it's bidirectional. Player meta: "how much gold do I have?", "can I reach that ledge?" DM meta: session-end "do you care about Captain Bromley?" Neither side is forced to stay in character through bookkeeping.
- Tight enumeration (not an open namespace) to avoid synonym sprawl. Anything that fits no verb is the signal to drop into the **freestyle tier**, which is the flexibility valve — the short list is not a cage.
- May gain edge-case additions during playtest.

---

## 6. The four-tier router

The router classifies each turn and hands the DM a resolution hint. It does **not** protect state (that's structural — see §7).

| Tier | Meaning | `may_canonize` |
|---|---|---|
| `authored` | Intent matches existing content; use it | false |
| `recombined` | No exact match, but the pieces exist; assemble them | true |
| `freestyle` | Genuinely novel input; DM improvises within a schema | true |
| `denied` | Violates a hard constraint; return a diegetic "no" | false |

`denied` exists only to give a graceful in-world refusal — exploits already fail safe by construction (§7).

---

## 7. Procedural protection (NOT a valuation engine)

Two domain classes:

- **OPEN** — DM creates/edits freely (still recorded): scene flavor, world detail, minor/ephemeral NPCs, provisional lore.
- **PROTECTED** — changed *only* via named, recorded tool calls: gold, XP, inventory, character stats, faction standing, quest flags.

**The firewall is procedural, not substantive.** There is no check against a "true value." The number is whatever the DM agreed to in the fiction. Protection comes entirely from: (a) the player can't emit a tool call, and (b) every change is recorded and auditable.

Worked examples:
- *The con (works):* player deceives merchant Thom → `skill_check.deception` roll succeeds → Thom (cautious) bends to 250 gold → DM emits `transact(give: boots, receive: 250g)` → recorded, applied, narrated. Ripping off a merchant is a legal win.
- *The fiat (fails):* "I now have 10,000 gold" → no fiction, no roll, no reason for the DM to emit a `transact`. State unchanged. Router tags it `denied` just to phrase the refusal nicely.

**Tool surface (the only doors into protected state):** `transact / give / take`, `grant_xp` (resolution events only), `set_flag / advance_quest`, `create_entity` (carries a canon record), `promote_canon`. Combat's HP/condition writes come back through the combat result object.

---

## 8. Economy & haggling (soft)

- Prices/values are **LLM judgment + a haggle roll** (`skill_check.persuasion` or `.deception`), with the DC set by the NPC's disposition/shrewdness. No spreadsheet.
- Agreed price flows to `transact`.
- To prevent **unwitnessed compounding** (a hundred small generosities inflating the economy), the DM should pull party wealth / economy state into context before big trades. The retrieval tool makes the soft economy self-correcting — which is *why* no enforcement engine is needed.

---

## 9. Trade window (summoned tool)

- Same pattern as combat: a bounded UI that **shows state** (merchant's stock + their gold) instead of resolving trades in prose. Showing merchant gold caps what they can afford to buy off the player.
- **Stock comes from the DB** — hand-authored or rolled from a template/loot table. The DM can nudge ("low on arrows today") within bounds, but does **not** freely invent powerful items for sale.
- **Not mandatory.** Browsing = a tool call (build a list, then ask the DM to haggle). A quick "grab a torch and toss a coin" = a single `transact` in chat. Window for browsing; chat for trivial buys.

---

## 10. Combat subsystem

- A partially-built prototype already exists (hex grid, initiative tracker, visible character sheets, HP bars, conditions, filterable log). It was shelved because 5e combat complexity (action economy, conditions, reactions, concentration, legendary/lair actions) is enormous. Reviving + reshaping it is the plan; agentic coding assistance suits the edge-case grind well (write the rules engine as pure functions, grind case coverage against tests).
- **Handoff:** the narrator detects hostility → emits a structured **encounter request** (declarative, e.g. `{ambush, enemies:[...], terrain}`) → validated code instantiates the encounter from templates + **live state** (Elara walks in with her real current HP and slots).
- Combat is a **player-driven tactical mode**; the narrator goes quiet.
- **Result:** combat returns a structured **result object** (the truth) → applied to authoritative state → a short prose digest is generated *from* that object and fed to the DM's context. (Never have the LLM parse prose back into numbers.)
- **Non-combat exits** are first-class: flee, parley, surrender, bribe — defined exit states that close the subsystem with a different result flag and hand control back to the narrator. (This is Tidefall's advertised "talk the raiders down," actually wired in.)

---

## 11. Canonization lifecycle

When the DM improvises new content (`recombined` / `freestyle` tiers), it's saved with an origin flag and a status:

- `provisional` — made up on the fly. **Kept but quarantined**: it persists, but it's "soft" and can't be load-bearing (e.g. a provisional NPC can't hand out quests) so improv can't silently overwrite the hand-authored world.
- `confirmed` — dependable canon, as solid as hand-authored content.

**Promotion triggers:**
- *Primary:* end-of-session DM gut-check. The DM may **break character** to ask the player directly ("Do you care about Captain Bromley? If not, they may be written out.").
- *Automatic:* when a provisional thing becomes load-bearing — e.g. a quest starts depending on it.

Canon only grows on purpose.

---

## 12. Open / deferred

- `provisional → confirmed` exact mechanics (mostly settled: session-end review + auto-on-load-bearing; refine in build).
- Verb list may gain edge-case additions during playtest.
- Multiplayer/co-op edge cases (one player's fiat affecting shared canon) — deferred.
- Determinism on reload is handled by "record everything, replay records."

---

## How Oubliette Table differs from Tidefall (the thesis)

Tidefall nailed atmosphere (sound, art, immersion ~8/10) and whiffed on combat and systems (hidden stats, prose-resolved combat ~3/10). The inversion: ambience is the *hard* thing to fake, combat against a known ruleset is a *solved* problem. Oubliette Table treats combat and state as a **systems** problem — surface the numbers, structure the turns, let code own the math — which is exactly the gap the original left open.
