# v0.9 joint playtest — fix list

Running list from the OublietteDev + Claude playtest session (2026-07-04, Sonnet 5 DM,
fresh save `playtest-v09-save.sqlite`, Atria, level-1 bard "Corin Vale").
Fixes to land before/alongside the GitHub release; player-guide material lives
in `docs/player-guide.md`.

## STATUS SUMMARY (end of session)

- **FIXED + tested (721 green):** #1 narration starvation (three layers: prompt
  nudge, max_tokens raise, and the decisive one — the narration-only follow-up
  pass in `loop._narrate_followup`), #3 travel blindness (destination residents
  in WHERE YOU CAN GO + post-travel context rebuild in the follow-up pass),
  #6 silent empty-notes wrap (300s timeout + retry + refusal), and the travel
  reachability holes (parent zoom-out + root↔root; Seraphel's Roost was
  unreachable from ANYWHERE — live-verified reachable now).
- **OPEN (post-release candidates):** #2 canon NPC dedup, #4 ghost rolls across
  a rest boundary (assess-side fix; player guide covers the behavior), #5 NPC
  name discipline (Bram/Bromley blur, second "Bram").

## 1. Tool-heavy turns starve the narration (prompt nudge)

**Seen:** Turn 2 — player pitch to the tavern landlord auto-resolved as
persuasion (rolled 20 vs DC 12), travel fired, canon NPC "Bram Ostler" created…
and the entire narration was "You make your way to The Lantern & Wake Tavern."
A nat-20 first impression with zero prose payoff. Same signature in the older
Wizardo save (event 11: near-empty narration on a `location_changed` turn).

**Diagnosis:** on turns where the model spends heavily on tool calls
(move_party + create_entity + …), it under-writes the assistant text and ends on
a bare movement line. A follow-up "what do I see?" turn recovers completely, so
state/context is unharmed — the miss is purely the on-screen prose.

**Fix:** prompt nudge in the DM system prompt: after tools resolve, always
narrate the outcome of the player's action in prose — especially the result of
any die roll — and never end the turn on only a travel/status line. Optional
belt-and-braces code guard: if tools fired and narration < ~100 chars,
ask the model to continue.

**Status:** OPEN

## 2. Canon NPC duplicated instead of reused

**Seen:** Turn 2 created canon NPC "Bram Ostler" (canon-0, provisional). Turn 7
created "Bram" (canon-1) — the same landlord, minted again. The model doesn't
dedup against existing canon when creating entities.

**Fix candidates:** surface existing canon entities (at least those present in
the current scene) more prominently in the DM context; and/or a code-side
near-name match on create_entity that reuses/promotes the existing record
instead of inserting a twin.

**Status:** OPEN

## 3. Travel turns are blind to the destination (root cause of #1, feeds #2)

**Seen:** Turn 8 — player walks from the tavern to Silverfin Docks looking for
old fishers. The DM invented a freestyle NPC ("Old Pell", canon-2) at the exact
place and role where the AUTHORED quest giver (Captain Bromley,
home_location=silverfin_docks, giver of root quest "The Empty Nets") lives.

**Diagnosis:** `dm/context.py` scopes the PRESENT NPC list to the party's
location *at turn start*. A turn that calls `move_party` then narrates an
arrival scene whose authored cast the model cannot see — so it improvises.
Also explains why arrival narrations run thin (finding #1): the model has no
material for the new place.

**Fix:** enrich the `move_party` tool RESULT with the destination's place
description + PRESENT-NPC list (id, name, one-line role), so the model narrates
arrival with the authored cast in hand. Prompt nudge as belt-and-braces:
"prefer authored/present NPCs over inventing new ones when a role fits."

**Status:** OPEN

## 4. Pre-rolled checks that cross a night/rest boundary become ghost scenes

**Seen:** Turn 18 message contained two beats: "sleep, then infiltrate the
Drowned Bell tomorrow." Assess pre-rolled the beat-two check (perception 22 vs
DC 13, success) but the DM — correctly — halted narration at the rest proposal.
The success was never narrated. Next turn, the DM RETCONNED an off-screen first
visit to reconcile the dangling roll ("the same low corner… the crew you marked
before", notebook: "the crew from the successful read wasn't present tonight")
and rolled the stakeout FRESH (a 5 — failed). Net effect: a success the player
never saw, replaced by a failure, plus fabricated history.

**Fix candidates (layered):**
- assess-side (real fix): stage rolls only for the FIRST unresolved beat of a
  multi-beat message; never roll past a night/rest the message itself proposes.
- prompt (cheap): "never reference scenes the player was not shown; if a staged
  roll belongs to a beat you are deferring past a rest, leave it for the next
  turn."
- player guide (now): one scene-beat per message; never straddle sleep.

**Status:** OPEN

## 5. NPC name discipline — collisions and cross-contamination

**Seen:** (a) Turn 18 narrated "Bram grumbling companionably beside you" for a
walk home from BROMLEY's boat — Bram (tavern landlord) and Bromley (captain)
blurred. (b) Turn 19 introduced the Drowned Bell's barkeep as… "Bram, the
barkeep" — a second Bram. The model drifts toward reusing established names.

**Fix:** prompt nudge alongside the create/canon rules: "new NPCs get names
clearly distinct from the established cast; check PRESENT/canon before naming."

**Status:** OPEN

## 6. Session wrap can silently seal with EMPTY notes — FIXED

**Seen:** first real wrap of the playtest returned `wrapped: true,
wrote_notes: false` — the session sealed with empty player_facing/dm_private,
silently destroying its continuity. Root cause: `_post` had `timeout=60`, the
wrap call hands the model the FULL transcript (49k chars here) and can exceed
it; the exception was swallowed by design ("never let a bad note-gen strand
the wrap") and the empty seal proceeded.

**Fixed (this session):**
- `anthropic_client._post` timeout 60s → 300s.
- `wrap_session` now retries note-gen once, then REFUSES the wrap with a
  visible notice instead of sealing empty (Offline Mode unchanged). New test:
  `test_wrap_refused_when_note_writing_fails`.
- The playtest save's empty marker (event 109) was repaired post-hoc by
  regenerating the notes and patching the payload.

**Also fixed this session (finding #1 root cause):** `act` max_tokens was
2048/4096 shared by thinking + tool JSON + narration, truncating SILENTLY —
the model's prose was getting cut, not skipped. Raised to 8192/16384 (a cap,
not a spend). Rich tool-heavy turns since the fix all narrated in full.

**Status:** FIXED (719 tests green)

## Watch list (not yet confirmed)

- ~~Rest never formally proposed~~ **CLOSED:** turn 18 proposed a long rest,
  player confirmed via /api/rest, REST_TAKEN recorded recovery ops. Works.
- **Unquoted player reflection treated as audible:** Bram reacted to Corin's
  internal aside as though spoken. Player-guide material (quotes = speech), but
  if it recurs egregiously, consider a prompt line distinguishing player
  framing from in-world speech.
