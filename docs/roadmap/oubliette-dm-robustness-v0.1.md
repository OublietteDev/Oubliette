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

### W3 — Save/load continuity  `[builds on W2]  [BUILT 2026-07-01]`
**Current-session continuity on reload, for both parties.** New `runtime/transcript.py`
holds the **session-segmentation primitive** both W3 and W5 stand on: a session is the
span of events since the last `SESSION_MARKER{marker:"wrap"}` (W5's wrap; none yet → the
whole log is "the session in progress"); force-ends (`marker:"end"`) are terminal and do
NOT segment. `current_session_events` / `transcript_turns` (ordered player+DM bubbles) /
`recent_beats`. Wiring: `TurnLoop.__init__` rehydrates `self.history` from the last
HISTORY_CAP durable beats of the current session, so a reloaded DM resumes with the same
short-term memory (not an empty head); new `GET /api/transcript` returns the current
session's bubbles and `boot()` replays them into the chat ("— resumed where you left off
—"), falling back to the opening prompt for a fresh game. **Design decisions locked with
OublietteDev:** the DM gets its *beats window* rehydrated (NOT the full verbatim transcript — that
would blow context); the *player* gets the full transcript. Past ended sessions will reach
the DM as **notes** and the player as spoiler-free per-session summaries (that's W5).
Live-verified (scripted preview): reload restores the full chat; fresh game shows the
opening prompt. Tests: `tests/test_transcript_replay.py` (+6) + transcript endpoint in
`test_server_frontend.py` (+1). Full suite 547 green.

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
- **Per-turn thinking:** ✅ **BUILT 2026-07-01 (Stage 2), live-verified.** Native extended
  thinking on the resolve `act` call — `thinking: {type: "adaptive", display: "summarized"}`
  + `output_config: {effort}` (claude-sonnet-5's shape; the old `{enabled, budget_tokens}`
  400s). **Per-turn effort by tier** (`Brain._effort_for`): contested adjudications
  (`RECOMBINED`, `DENIED`) → `high`; routine narration (`FREESTYLE`, `AUTHORED`) → thinking
  off — so the DM reasons only where the ruling is genuinely in question, with no latency/
  cost tax on routine turns. `act(effort=...)` overrides the client default per call (sentinel
  `_INHERIT`); the summarized thinking is captured and logged to the non-replayed debug channel
  (`TurnLoop._resolve_turn`), never shown to the player. `complete` (assess/wrap) explicitly
  sets `thinking: {type: "disabled"}` (forced-tool calls can't think, and sonnet-5 would
  otherwise default adaptive-on). **Empirical finding that drove the design:** at low/medium
  effort adaptive thinking almost never fires on DM narration turns (the dice are pre-resolved
  in code, and it's a generative task) — only `high` on an open judgment reliably triggers it
  (live: a contested trap ruling → 541 chars of reasoning; a routine "glance around" → 0).
  Tests: `test_resolve_streaming.py` (adaptive-thinking payload, canned-SSE thinking parse,
  tier→effort mapping, Brain passes per-turn effort). NOT persisted across turns.
- **Persistent DM notebook:** ✅ **BUILT 2026-07-01 (Stage 3), live-verified.** A `dm_note`
  tool the DM calls to jot private working memory — plans, an NPC's true intention, foreshadowing
  planted, a lie left standing. Recorded as a new `NOTEBOOK_NOTE` event (payload `{note}`, inert
  on replay like NARRATION_RECORDED — the firewall pattern), fed back each turn as a **DM NOTEBOOK**
  context block (`transcript.notebook_notes` → `build_context`). **Scoped to the current session**
  (like beats): the DM's episodic working memory, durable across reloads within the session, reset
  at wrap — its threads carry forward via STORY SO FAR (W5's per-session dm_private notes are the
  semantic layer above it). Players NEVER see it (not in the transcript). Pieces: `EventKind.NOTEBOOK_NOTE`,
  `Session.emit_notebook_note`, `DmNote` tool + TOOL_MODELS + dispatch (`ResolvedTool.note_text`),
  loop apply-branch + beat summary, `transcript.notebook_notes`, `build_context` DM NOTEBOOK block,
  `RESOLVE_SYSTEM` NOTEBOOK guidance. Live-verified: the DM recorded an NPC's secret allegiance to
  the notebook, it reached the next turn's context, and the secret stayed OUT of the player narration.
  Tests: `test_resolve_streaming.py` (dispatch, records+feeds-context+player-invisible, current-session
  scoping + inert-on-replay). Full suite 2987 green. (Also fixed the stale `build_context` ENVIRONMENT
  line — "report on your TurnResolution" → "emit set_environment when the story turns them".)

### W5 — Session wrap-up + two-faced notes  `[builds on W2/W3]  [BUILT 2026-07-01]`
The episodic→semantic compaction. A **wrap** (distinct from a free pause = closing the
window) seals the session in progress: the DM authors `SessionNotes{player_facing,
dm_private}` from the FULL session transcript — the one place it sees the whole thing,
not just beats — recorded on a `SESSION_MARKER{marker:"wrap"}` (the segmentation boundary
W3 already keys on). `dm_private` feeds the DM's context every turn thereafter (new
**STORY SO FAR** block, cumulative, players never see it); `player_facing` becomes the
player's spoiler-free **chronicle** ("Previously — Session N", rendered above the live
chat on boot). The beats window resets on wrap — the session's episodic memory now lives
in its note. **Trigger:** the DM PROPOSES via the freed `end_session` tool → transient
`wrap_pending` flag → the client shows a wrap-bar (Wrap up / Keep playing); the player can
also wrap directly (Menu → "Wrap up session"). Both hit `POST /api/wrap`. Mirrors the
`combat_pending` staging pattern (DM proposes, player disposes). **Offline Mode writes no
notes** (server gates on `client_name`); a note-gen failure degrades to an empty wrap so
the ritual never dead-ends; a wrap with nothing to seal is refused. Firewall intact: notes
are prose, inert on replay, never protected state. Pieces: `SessionNotes` schema +
`EndSession` tool + `ResolvedTool.wrap_proposed`; `Brain.write_session_notes`/`WRAP_SYSTEM`;
`Session.emit_wrap`; `transcript.session_notes`; `TurnLoop.wrap_session` + `_build_context`
(shared, now carries `past_notes`); `build_context` STORY-SO-FAR block; `/api/wrap` +
chronicle on `/api/transcript`; frontend wrap-bar + menu item + chronicle replay.
Live-verified (scripted preview): DM proposal → bar → wrap → session sealed; chronicle
render path confirmed. **Note CONTENT (real two-faced notes, STORY SO FAR reaching a live
DM) needs the API key — for OublietteDev to confirm in live play.** Tests: `test_session_wrap.py`
(+8) + server (+3). Full suite 558 green. **The canonization ceremony remains the deferred
follow-on** (promote provisional→confirmed canon at wrap).

Old note (superseded): `emit_end` recorded only a reason string that was never read back.

### W6 — Streaming redesign  `[folded; shares the W2/W4 resolve restructure]  [LOCKED: one-call, narration as text]  [BUILT 2026-07-01]`
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

**BUILT (Stage 1 of the resolve restructure):** a second seam method `LLMClient.act(system,
messages, tools, on_text) -> ActResult{narration, tool_calls, thinking}` (`llm/client.py`).
`AnthropicLLMClient.act` uses `tool_choice: auto`, registers each tool model by its `tool`
literal (`_tool_def` strips the discriminator from the input schema), streams assistant
**text** deltas straight to `on_text` (genuine token-by-token — `_post_stream_act`), and
accumulates `tool_use` blocks (validated via the shared `_coerce_input` envelope-unwrap).
The forced-`emit` streaming path it replaced (`_post_stream` + `llm/streaming.py`
`extract_string_field` + `test_streaming_extract.py`) is DELETED; `complete()` is now
assess/wrap-only (forced structured output, no streaming). `Brain.resolve` calls `act` with
`TOOL_MODELS` and returns `ActResult` (empty-narration-AND-no-tools → raises → the loop's
existing retry/D6 fallback catches it). Environment left the `TurnResolution` schema and
became a `set_environment` tool (`tools/schemas.py`, dispatch branch → `ResolvedTool.env_time/
env_weather`, loop emits `ENVIRONMENT_CHANGED` only on an ACTUAL change). `ScriptedLLMClient.act`
reuses its `_resolve` and unpacks. Tests: `test_resolve_streaming.py` (+9: scripted act, the
Anthropic pure helpers `_tool_def`/`_collect_act`, a canned-SSE parse of `_post_stream_act`,
and `set_environment` through the loop) + `test_table_contract` capturing-client updated to
`act`; `test_resolve_robustness` unchanged (still catches the raised empty resolution). Full
suite 2979 green. **Stage 2 (W4 per-turn thinking) + Stage 3 (W4 notebook) deferred to the
reassess after live-verifying Stage 1 streaming with the real key.** Live Anthropic behavior
(does `tool_choice: auto` stream text deltas as expected; sonnet-5 quirks) still needs OublietteDev's
key to confirm in live play — same handoff as W5.

**LIVE-VERIFIED by Claude with OublietteDev's key (2026-07-01, sandboxed preview):** `act()` streams real
text deltas and returns validated tool calls (a fountain call-out produced ~1.3k chars over ~20
deltas + a `CreateEntity` witness and a `StartQuest`). Two follow-on fixes landed from the live run:
1. **Choppiness smoothing (frontend).** The API delivers narration in ~11 fat, clause-sized lurches
   (~60 chars every ~360ms). The client no longer renders deltas as they land — it buffers them and
   reveals at a steady, frame-rate-independent ~190 chars/sec (a `requestAnimationFrame` pump using
   elapsed-time, with proportional catch-up above a 220-char backlog), decoupling on-screen cadence
   from network jitter. `index.html` `send()`: `pump`/`startPump`/`finalize`, `REVEAL_CPS`/
   `CATCHUP_BACKLOG`. Chips/state/quest-cards now apply on `finalize` (after the reveal drains), not
   at `done`. (Frame-level smoothness is a focused-browser eyeball check — automated preview tabs
   throttle timers when unfocused, so headless measurement only shows ~1/sec granularity.)
2. **Empty-`emit` hardening (`complete`).** Sonnet-5 intermittently returns an empty forced call
   `emit({})`; the live run caught it crashing **assess** with "2 validation errors for
   TurnAssessment" (assess/wrap have no upstream retry loop, unlike resolve). `complete` now
   regenerates a few times on a validation failure before surfacing it. Test:
   `test_resolve_streaming.py::test_complete_retries_on_empty_forced_emit`. Full suite 2980 green.

---

## 4. Proposed build order

1. **W1a — quest reward fix** (small, independent, real bug a playtester would hit). ✅ BUILT
2. **W2 — durable narration** (keystone; unblocks the rest). ✅ BUILT
3. **W3 — current-session continuity on reload** (the other real bug). ✅ BUILT
4. **W5 — session wrap-up + two-faced notes** (the `end_session` wrap ritual). ✅ BUILT
   (canonization ceremony still the deferred follow-on).
5. **Resolve restructure = W6 + W4.** Staged, not one pass:
   - **Stage 1 — W6 streaming** (narration-as-streaming-text, actions/env as `tool_choice:auto`
     tools). ✅ BUILT 2026-07-01 (2979 green). Live-verify streaming with the real key, then:
   - **Stage 2 — W4 per-turn thinking.** ✅ BUILT + live-verified 2026-07-01 (2984 green).
     Native adaptive thinking, **per-turn effort by tier** (contested → high, routine → off).
     See W4 above for the empirical finding (thinking only fires at high effort on genuinely
     contested turns) and the wiring.
   - **Stage 3 — W4 persistent DM notebook.** ✅ BUILT + live-verified 2026-07-01 (2987 green).
     `dm_note` tool → `NOTEBOOK_NOTE` inert-on-replay event → current-session "DM NOTEBOOK"
     context block (resets at wrap, carried forward by STORY SO FAR); firewall: prose only,
     player-invisible. See W4 above.
6. **W1b — remaining context-drop cleanups** (opportunistic, as we go).

**ARC STATUS 2026-07-01: W1a, W2, W3, W5, W6, and W4 (both flavors) all BUILT. The DM-robustness
arc's planned workstreams are complete.** Remaining follow-ons (all deferred, none blocking): the
canonization ceremony (promote provisional→confirmed canon at wrap), W1b opportunistic context-drop
patches, and the interview-surfaced backlog (HP-outside-combat gap + small prompt fixes).

**Session-memory model locked with OublietteDev (2026-07-01):** episodic vs. semantic memory.
*Current session* → player gets full transcript replay, DM gets its beats window rehydrated
(W3, done). *Past ended sessions* → DM gets all session notes cumulatively; player gets
spoiler-free per-session summaries (W5). **Pause** (close the window) = zero ceremony, resume
exactly. **Wrap** (`end_session`) = explicit ritual: a narrative arc wrapped AND the player
stops; player-initiated button OR the DM *proposes* via the tool (surfaces a confirm — player
disposes, mirroring `combat_pending`). Wrap seals the session into a note (the ONE place the
full transcript is fed to the model), resets the beats window, and starts session N+1.
Offline Mode writes no notes (it's a UI demo, not real play).

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
