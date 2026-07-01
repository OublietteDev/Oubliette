# Oubliette — DM Robustness Arc (v0.1 design)

Status: **DRAFT for review.** Decisions tagged `[LOCKED]` / `[PROPOSED]` / `[OPEN]`.
Author: OublietteDev + Claude, 2026-06-30. Grounded in a two-agent code audit (context
in/out map + reload/continuity trace); file:line cites throughout are from that audit.

---

## 1. Why this arc

The live DM is a Claude model **called fresh every turn** — it has no memory except
what the per-turn `build_context` string carries and a small in-memory recap. So the
whole felt quality of "the DM understands, remembers, and plans" is really a question
of **what reaches context, what durably persists, and what the model is allowed to
think.** The audit surfaced two live bugs and three missing capabilities:

- **BUG — the DM forgets promised quest rewards.** The reward is rendered *only* inside
  the active-quest block (`context.py:317-320`); the moment a quest flips to
  `completed`, `session.quests.active()` (`loop.py:85`) stops returning it and the
  reward line vanishes with **no fallback surface**. Deferred handover ("return
  tomorrow to collect") is exactly the window where the info is already gone — so the
  DM guesses.
- **BUG — reload loses all narrative continuity.** Authoritative state (HP/gold/
  inventory/location/canon/quests) is event-sourced and replays perfectly, but the
  DM's recent-beats memory (`TurnLoop.history`, in-memory only, `loop.py:69`) and the
  player's chat transcript (client-side DOM only) are **both transient**, and nothing
  shows a "where we left off" recap. So after a reload the sidebar is correct but the
  chat is empty and the DM has zero short-term memory.
- **MISSING — a DM scratchpad** to plan/reason before it narrates.
- **MISSING — end-of-session notes** that carry into the next session.
- **MISSING — real streaming** (diagnosed separately: narration is trapped inside the
  forced tool call, so it arrives in one end-burst, never token-by-token).

## 2. The root cause they share

The resolve turn forces a single structured tool call whose input *is* the entire
`TurnResolution` (`narration` + `tool_calls` + environment), via
`tool_choice: {type: tool, name: emit}` (`anthropic_client.py:57`). That one decision
causes three of the five items above:

| Symptom | Because narration lives inside the forced tool JSON… |
|---|---|
| No streaming | …the model's JSON isn't flushed progressively — it materializes at the end (~7s silence, then a burst). |
| No durable narration | …narration is treated as transient model output, never recorded (`events.py:8` "only PROTECTED state is event-sourced"). |
| No scratchpad | …there is no separate channel for the model to think in before/around the narration. |

**Design spine:** restructure the resolve turn **once** so that narration is a normal
(streamable) text channel, the model has a thinking/scratchpad channel, and only
state-changing actions go through validated tool calls — then make narration durable.
Everything else (continuity, recap, session notes) builds on that durable record.

---

## 3. Workstreams

### W1 — Context lifecycle: stop the silent drops  `[quick win, mostly independent]`
The audit produced a full map of the 12 context sections and every point where info
silently drops or gets crowded out (canon search top-5, lore cap 3×1200, non-lore
canon clip 160, present-NPC location scoping, merchant stock cap 8, recent-turns
window 4-of-8, active-quest text clip 200 / last-note-only). Full table lives in the
audit appendix; the flowchart deliverable (below) visualizes it.

- **W1a — quest reward fix.** `[LOCKED: keep-until-paid]` `[BUILT 2026-06-30]`
  A completed quest stays in the DM's context in a new **REWARDS PENDING** block
  (distinct from ACTIVE QUESTS) until the DM confirms the party was compensated.
  **Settle signal = an explicit `reward_settled` flag on `update_quest`** — NOT inferred
  from a matching give/transact, because rewards are renegotiable (the party may take
  gold instead of the promised sword, or decline it), so a handover deliberately won't
  match the promise. `Quest.reward_settled` is event-sourced via QUEST_UPDATED (survives
  reload); `QuestStore.reward_pending()` = completed & unsettled; the block shows the
  authored reward (or, for emergent quests, the last note/text as a hint); the DM is
  prompted to hand over the reward then set `reward_settled=true`. A settle-only update
  emits no player quest-card (the give/transact chip already shows the handover).
  Tests: `tests/test_quests.py` (+4). Full oubliette suite 537 green.
- **W1b — audit the other drop points** and decide keep-as-designed vs fix (most are
  fine; present-NPC scoping and the canon top-5 are the ones worth a second look).
- **Deliverable: a context-lifecycle flowchart** (the thing you asked for) — a living
  diagram of what enters context, from which source, and under what condition it
  drops. Rendered from the audit map; kept in this doc's folder.

### W2 — Durable narration  `[keystone]  [LOCKED: new event kind]  [BUILT 2026-06-30]`
A new `NARRATION_RECORDED` event is emitted at the single beat-finalizing choke point
(`_record_beat`, reached by both `take_turn` and `enter_combat`), so every narrated turn
is captured exactly once. Payload = `{narration, beat}`: the **verbatim narration**
(rebuilds the player transcript, W3) + the **compact continuity beat** (rehydrates
`TurnLoop.history`, W3), with `caused_by` linking it to the prompting PLAYER_MESSAGE
(None for Arena entry). It carries **no ops → inert no-op on replay** (the PLAYER_MESSAGE
pattern), so protected state still replays byte-identical and the firewall holds:
`Session.emit_narration`. Tests: `tests/test_narration_durable.py` (+3, verbatim capture /
player-message linkage / no-ops-inert-on-replay). Full suite 540 green.

Make the DM's narration (and enough of each turn to reconstruct it) durable via a
**new event kind** (e.g. `NARRATION_RECORDED`, or fold into a per-turn record).
Narration is non-deterministic, so it is **stored verbatim and is a no-op on replay**
— exactly the pattern `PLAYER_MESSAGE` already uses (`events.py:210-211,237`). This
consciously extends the "only protected state is event-sourced" principle
(`events.py:8`) to also durably record model *output* — but as inert prose, never as
an authority the model can use to assert protected state (see firewall note §5). One
save file, one `open()` path; W3/W5 build directly on this. Store enough per turn to
rebuild both the DM's recent-beats recap and the player transcript (narration text +
turn linkage; player message already stored).

### W3 — Save/load continuity  `[builds on W2]`
Once narration is durable:
- **Rehydrate the DM's short-term memory** on `Session.open`: rebuild
  `TurnLoop.history` from the last N durable turns instead of starting empty
  (`loop.py:69`).
- **Restore the player transcript**: new `GET /api/transcript` (or fold into
  `/api/state`) returns the durable turn records; `boot()` (`index.html:3342`) replays
  them into the chat log instead of only the static greeting.
- **"Where we left off" recap** on load, surfaced to the player and optionally seeded
  into the DM's first-turn context (the current scene text is a *static location
  description*, not the live situation — `session.py:66-72`). `[OPEN]`: full transcript
  replay vs. a short generated recap vs. both.

### W4 — DM scratchpad  `[rides the W2/W6 resolve restructure]  [LOCKED: both]`
Build **both** flavors:
- **Per-turn thinking:** a scratchpad/thinking space the model fills before it narrates
  (natural once resolve is restructured; a text/thinking block the UI never shows).
  Improves single-turn reasoning; not persisted. Near-free once W6 lands.
- **Persistent DM notebook:** a durable, DM-owned notes store (distinct from the
  player's DM-invisible journal) that rides context each turn — the DM's own memory of
  plans, foreshadowing, NPC intentions. Persisted via W2's durable record (its own
  event kind or notebook table); the DM writes to it with a tool; it feeds back into
  context. This is also the substrate for W5 (session notes = notebook entries the DM
  writes at session end). Firewall: notebook is DM memory/prose, never protected state.

### W5 — End-of-session notes  `[builds on W2/W4]`
On `end_session` (or on demand), the DM writes a durable session summary that reloads
into the next session's context ("Last time on…"). Today `emit_end` records only a
reason string that's never read back (`session.py:204-208`). Natural extension of the
persistent notebook.

### W6 — Streaming redesign  `[folded; shares the W2/W4 resolve restructure]  [LOCKED: one-call, narration as text]`
Restructure resolve so narration is a streaming assistant **text** channel and only
state-changing actions go through tool calls (`tool_choice: auto`, not forced `emit`).
One model call, real token-by-token streaming, narration leaves the validated schema
(fine — it's prose; the client already renders deltas, `index.html:1279-1298`). The
model emits: (optional thinking → W4) then narration text (streams) then 0+ tool calls
for actions/environment. **W2 (durable capture), W4 (thinking channel), and W6 (text
narration) all reshape this one call — design and build the resolve restructure ONCE**
covering all three. Risk to manage: the whole loop + tests are built around the forced
`TurnResolution` schema (`schemas.py:61`, `brain.resolve` `brain.py:181`), so this is
the highest-touch change in the arc — stage it behind tests and keep the non-streaming
path for the test suite.

---

## 4. Proposed build order

1. **W1a — quest reward fix** (small, independent, real bug a playtester would hit). ✅ BUILT
2. **W2 — durable narration** (keystone; unblocks the rest). ✅ BUILT
3. **W3 — continuity/recap on reload** (the other real bug). ← next
4. **Resolve restructure = W6 + W4 together** (narration-as-streaming-text + scratchpad,
   built in one pass so we don't rework the resolve path twice).
5. **W5 — end-of-session notes.**
6. **W1b — remaining context-drop cleanups** (as needed).

## 5. Decisions

**Locked (OublietteDev, 2026-06-30):**
1. **Narration durability (W2):** ✅ **new event kind** (verbatim, inert on replay).
2. **Quest-reward fix (W1a):** ✅ **keep-until-paid** (visible until reward handed over).
3. **Scratchpad (W4):** ✅ **both** — per-turn thinking + persistent DM notebook.
4. **Streaming (W6):** ✅ **one call, narration as streaming text**, actions as tools.

**Still open (decide at build time):**
- **Reload recap (W3):** replay the full stored transcript, show a short generated
  recap ("Last time…"), or both? Leaning: replay transcript for the player (we now
  store it) + seed a compact recap into the DM's first-turn context.
- ~~**W1a "settled" signal**~~ — RESOLVED: explicit `reward_settled` flag (renegotiation
  makes give/transact inference unworkable). Built.
- **Firewall invariant (must hold):** durable narration and the DM notebook are new
  persisted, model-written surfaces. They are **memory/prose, never protected state** —
  the model can read them but code still owns every number. Keep the "code owns state,
  the model never holds the pen" invariant intact (the project's core rule).

## 6. Appendix — audit references
Context map: `build_context` at `dm/context.py:174`; 12 sections in fixed order; key
constants `LORE_MAX=3`, `LORE_CHARS=1200`, `FEATURE_CAP=14`, canon `search limit=5`,
non-lore canon clip 160, active-quest text clip 200, merchant stock 8,
`HISTORY_IN_CONTEXT=4`, `HISTORY_CAP=8`, beat clip 140. Reload path: `Session.open`
(`session.py:74`) = seed + replay; `TurnLoop.history` in-memory (`loop.py:69`);
transcript client-side DOM only; no recap; `emit_end` reason never re-read.
