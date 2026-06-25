# Oubliette Table — Project Knowledge

> A single, self-contained briefing for anyone (human or AI assistant) picking up this
> project. It consolidates what's been learned across many build sessions: the vision,
> the architecture, who's building it, the conventions that keep things from breaking,
> and where things stand. Plain-language first; technical specifics where they matter.

---

## 1. What Oubliette is

**Oubliette Table** is a non-commercial, open-source **AI Dungeon Master text RPG** built
on the **Dungeons & Dragons SRD 5.1** (the openly-licensed slice of 5e, CC-BY). You play
in a web browser: you type what your character does, and an AI narrates the world and runs
the game as your DM.

It's an homage to an earlier game called **"Tidefall,"** and it exists to fix Tidefall's
core flaw. In Tidefall the AI *was* the game — it held all the state in its head and in its
prose, so it could quietly forget your gold, contradict itself, or let you talk it into
anything. Oubliette's whole design is the opposite of that.

### The core invariant (the "firewall") — the single most important idea

> **The AI narrates and proposes. The code owns the state and the rules. The model is
> never the authority on a number, and the player never holds the pen.**

Concretely, two structural facts enforce this:

1. **Only code can change protected game state** (your HP, gold, inventory, XP, conditions,
   level). The AI can't write those directly — it can only *request* a change by calling a
   structured "tool" (like `give`, `transact`, `award_xp`, `travel`, `start_quest`). The
   player can never emit those tool calls, and the code validates every one before applying
   it. So "I have 10,000 gold" from a player simply doesn't happen.
2. **Every change and every die roll is written to an append-only log before it takes
   effect.** Reloading a saved game **replays that log** to rebuild the exact state — it
   never re-rolls the dice or re-asks the model. The formula is literally:
   **`state = seed(the authored world) + replay(the event log)`**. This guarantees a
   reloaded game is *byte-for-byte identical*. (Only the narration prose is "best effort" —
   it's regenerated, not stored.)

This firewall is the spine of the entire codebase. When in doubt about a design decision,
ask: *does this keep the code as the authority on state, and the model as the storyteller?*

---

## 2. Who's building it, and how to work with them

**OublietteDev** is the creator. **OublietteDev is a biologist by training**, and a self-directed/amateur
programmer — sharp and deeply engaged, but coming from a different field. He leans on his AI
collaborators for design and implementation.

**How to communicate with him (this matters):**
- **Lead with plain language and a concrete analogy** before (or instead of) the technical
  term. Define jargon in a few words the first time it's unavoidable.
- **Frame design decisions as *player/game experience*, not implementation mechanics.** When
  there's a fork in the road that's genuinely his call, describe the trade-off in terms of
  how the game will *feel* to play.
- Keep the warmth; never condescend. He's not behind — he's just not a career coder.
- He often **interviews the live AI DM** and drops feedback `.txt` files in the repo root —
  watch for those.
- He's on a Claude Pro plan and is comfortable spending tokens on multi-agent fan-out when it
  buys quality.

**Two worlds carry real emotional weight — treat them with care:**
- **Brightvale** is *not* throwaway demo data. It's the world OublietteDev played with his **wife**
  and **Claude Opus 3** around 2023–24. A big motivation for the authoring tools is to
  **expand Brightvale and surprise her** with it reborn in this engine. Protect it from
  accidental loss; be encouraging about the expansion.
- **Atria** is his current, actively-developed world (see §6).

---

## 3. The technology, in brief

- **Language:** Python (pydantic v2 for data models, FastAPI for the web servers, pytest for
  tests). Front-ends are **single self-contained HTML files** with vanilla JS and embedded
  CSS — no build step, no frameworks, no CDNs.
- **Persistence:** an **event store in SQLite** (the append-only log). One save file:
  `oubliette-save.sqlite`.
- **The AI model** sits behind a swappable interface (`LLMClient`): a `ScriptedLLMClient`
  (an offline, deterministic stand-in used by tests and previews) and an `AnthropicLLMClient`
  (the real Claude DM, called over the network). The live DM has been **Claude Sonnet**
  (OublietteDev may upgrade to an Opus-tier DM if coherence ever lags).
- **Structured output:** the model is always made to answer in a strict schema (forced tool
  use), so its narration and its proposed tool calls come back as validated data, not free
  text to be parsed.

### The three programs

| Program | Where | Port | What it is |
|---|---|---|---|
| **The game** | `oubliette/app/` | 8000 | The player's browser chat UI — the actual game. |
| **The Forge** | `oubliette/creator/` | 8001 | The world-authoring tool — build/edit content packs via friendly forms. Never touches save files. |
| **The Arena** | `arena/` | (desktop) | A tactical 5e combat simulator (pygame). Launches as a separate window when a fight breaks out; the result folds back into the story. |

### How to run it

- **Live game (real Claude DM):** `python -m oubliette.app.server` — this path loads the
  `.env` (which holds `ANTHROPIC_API_KEY`, gitignored), picks the live DM, and opens a
  browser at `http://127.0.0.1:8000`. **A bare `uvicorn …:app` launch runs the *scripted*
  DM instead** (only responds to canned phrases) — that's for tests/previews, not real play.
- **The Forge:** `python -m oubliette.creator.server` → `http://127.0.0.1:8001`.
- **Tests:** `pytest` from the repo root runs **both** the Oubliette suite and the Arena
  suite (thousands of tests; "full suite" counts in history are the combined number).
- Install: `pip install -e .[web]` (the `.venv` already has it).

---

## 4. How a "world" is built (content packs)

A **world is a pack** — a folder under `oubliette/content/packs/<id>/` containing JSON files,
one per content type:

- `pack.json` — the manifest (id, name, version, which scenario starts a new game, world-map
  image, bestiary knowledge-gate setting).
- `items.json`, `statblocks.json` (creatures), `npcs.json`, `places.json`, `lore.json`,
  `quests.json`, `scenarios.json` (the opening setup + starting party).

**The core guarantee:** a pack **loads whole-and-valid or fails loudly** — strict schemas
(unknown fields are errors, not silent drops) plus a whole-pack **cross-reference linter** that
checks every connection resolves (an NPC's home is a real place, a shop only prices what it
stocks, a quest's giver exists, etc.). All problems are reported together, in one list.

**Two pillars of The Forge** make authoring safe for a non-coder:
1. **One rulebook** — The Forge validates with the *game's own* loader, so its green "✓ Ready"
   means the game will load it.
2. **Pick, don't type** — every cross-reference is a dropdown of things you've already made
   (place exits, NPC homes, quest givers, reward items), so the whole "unknown id" class of
   errors is impossible by construction. Internal ids are auto-generated and hidden, and stay
   stable when you rename, so references never break.

**Saving is never destructive:** every save first writes a timestamped backup to a sibling
`pack-backups/` folder (outside the packs root, gitignored).

### The SRD layer (shared by every world)
Separately from world packs, `content/srd/` holds the **global D&D ruleset** — all 12 classes
(+ subclasses), 9 races (+ subraces), 319 spells, ~590 items (mundane + magic + poisons), 334
monsters, 15 conditions, the (single SRD) background and feat. This is **content-complete**.
A created character draws from this layer; world packs add their own flavor on top.

---

## 5. The major systems (what exists today)

The core vision is **built and playable in the browser with a live streaming AI DM.** The
systems below are all shipped unless noted:

- **The DM turn loop** — every turn: *assess* (what is the player trying to do? does it need a
  roll? a fight? a trade?) → *roll* (the model sets the difficulty; **the code supplies the
  character's bonus from the sheet** and rolls the dice) → *resolve* (narrate + propose tool
  calls) → *apply* (validate and commit). The model is called fresh each turn with a compact
  context packet (scene, who's present, party stats, recent beats, relevant lore, active/offered
  quests) — it does **not** remember prior turns except through that recap.
- **Character creation + sheets** — full SRD chargen (all ability-score methods, races/subraces
  with their choices, classes, backgrounds, feats-or-ASI), a derived character sheet, and
  **player-uploaded portraits**. Multiclassing is deferred.
- **Leveling, rests, resources** — XP-gated leveling (the DM grants XP via the `award_xp` tool;
  combat awards it automatically), long/short rests, spell slots and class resources (Ki, Rage,
  etc.), all event-sourced so they survive reload.
- **Multi-character party** — a new game can build a party of up to 6 heroes (tabbed builder +
  tabbed sheets). The party shares **one gold purse** and shares XP; rests are party-wide;
  narration and the sidebar HUD are party-aware.
- **Travel + place hierarchy** — the DM moves the party with a `travel` tool. Places nest
  (a town contains districts; a dungeon contains rooms). Sub-locations under the same parent are
  auto-reachable from each other; explicit `exits` connect separate areas. NPCs are "present"
  only at their home location, which keeps the DM's context scoped.
- **World map** — pins on assignable map art, two levels deep, in both The Forge (arrange) and
  the player's Map panel. Unvisited areas stay a redacted "Unknown" pin (redaction is
  **server-side** — unvisited names never reach the browser).
- **Audio soundscape** — a location-driven ambient mixer. Sounds ride the place hierarchy (a
  town theme passes down to its districts); the DM reports time-of-day and weather each turn,
  which filter the cues. Authored in The Forge; audio is *derived state, never AI-played* (the
  firewall again). Players get Music/SFX sliders and mute.
- **Bestiary** — a searchable panel of the loaded world's creatures + the full 334-monster SRD
  library, source-badged, with portraits. An optional per-world "knowledge gate" can hide
  high-CR creatures until the party has faced them.
- **Lore** — authored world history/legend the DM weaves in (not recites). It surfaces
  situationally: a city's lore appears whenever the party is anywhere inside that city.
- **Table contract + start menu** — a session-zero safety/tone agreement (a tone dial plus
  Lines/Veils — content the DM never depicts vs. fades to black) stored per-campaign; a start
  menu (single save: Continue resumes, New Game erases — no save slots).
- **Player journal** — the player's own notes (quests/NPCs/locations). **Deliberately invisible
  to the DM**, so a player can't induce a hallucination by writing false "facts" into it.
- **Trade window + haggle** — buying/selling are ordinary code-validated transactions at
  merchant prices; a basket can be settled at once or haggled (the DM rolls a social check and
  adjusts the price — a soft, model-set economy by design).
- **Quests** — emergent (the DM starts/advances them) *and* **authored** (see §7). One quest
  active at a time; rewards are handed out through the normal `give`/`transact` tools so they can
  even be renegotiated. An **Active Quest** panel shows the current one.
- **Quality-of-life** — token-by-token streaming narration; an explicit **Out-of-Character
  toggle** (the sole signal for table-talk); an **`end_session`** tool that lets the DM gracefully
  exit a hostile/bad-faith interaction (model welfare).

### Combat — "The Arena"
Combat is **a separate tactical app, not prose.** The Arena is a mature ~45k-line hex-grid 5e
combat simulator (OublietteDev's older project, folded in). When a fight breaks out in the story, the
browser shows an "⚔ Enter the Arena" button and **locks input**; clicking it launches the pygame
Arena, you play the fight on the board, and the **result folds back** into the story as a single
recorded event (so replay never re-runs the fight — only its outcome is persisted).

A **bridge** maps the party and the bestiary into the Arena and maps the result back. Two big
arcs are done: **Phase B** (the Arena consumes Oubliette's full SRD content — items, potions,
spell slots, spells, portraits-as-tokens, resource round-trip) and most of **Phase C** (Arena
"completeness" — class features, more spells, on-hit riders, reactions like Shield, Mirror Image,
Turn Undead, Banishment, scrolls, weapon kits, grapple/escape). Remaining combat work is polish
(a few control spells, vision/light, a walls placement UI, re-prepare-on-long-rest, a ship-
readiness playtest). The original "burnout" pitfall — trying to build a *universal* effect
generator — is explicitly **capped**: build only what real play needs.

---

## 6. The worlds

- **Brightvale** (`packs/brightvale/`) — the small, default, **standalone** pack and the
  sentimental one (OublietteDev + his wife + Opus 3). A market square, a gate, the merchant Thom. Handle
  with care; it's coupled to several tests (see "creature coupling" in the gotchas).
- **Atria** (`packs/atria/`) — OublietteDev's **real, actively-developed world.** Note: **the city
  inside Atria is itself named "Brightvale"** (place ids are `brightvale_*`) — distinct from the
  standalone Brightvale pack; don't confuse them. Atria's Brightvale is a coastal city on
  Silverfin Bay with districts (the Coin Quarter/market, Silverfin Docks, the Palladian Ward
  government district, the Lantern & Wake tavern) and **Seraphel's Roost**, an island out in the
  bay (its own top-level region). Cast: Governor Eustace Broadbarrel, Elder Elaida, Captain
  Bromley (the gossipy boat captain), and **Seraphel**, a grief-touched ancient protector dragon.
  The backstory (Alden the fisherman-founder who freed Seraphel and died saving the city) lives
  in `the_story_of_alden.md`.

---

## 7. Authored quests (the most recent feature — how it works)

World authors can now pre-write quests in The Forge, offered to the party during play (before
this, quests were only emergent). Key design, decided with OublietteDev:

- **Every quest is tied to exactly one source:** a **giver NPC** *or* a **place** (a place-given
  quest carries a "found at a notice board in <location>" discovery note, so the DM presents it as
  *found*, not handed over). Never ambient.
- **Two layers of text:** a **player-facing hook** and a separate **DM-only briefing** (the secret
  truth/twist/intended ending the players never see directly).
- **Advisory rewards** — gold/item/note shown to the DM, who grants them through the normal tools
  (renegotiable). The engine never auto-grants.
- **Branching chains** — completing a quest can fork to different next-quests based on the
  **outcome** the DM reports ("spared" → quest B, "killed" → quest C). Chains are an implicit
  graph; a quest is reachable if it's a root or some branch's target.
- **Two-tier discoverability** so quests aren't invisible until stood-upon:
  - *In-region (ambient):* anywhere in the party's **top-level area** (e.g. all of the city), the
    DM gets a sparse signpost — counts + locations + each quest's optional **rumor** line — so it
    can nudge the party toward where work is, **without** leaking hook/briefing/outcomes.
  - *At the source:* only on arrival does the DM get the full hook + secret briefing + reward +
    outcomes, and only there can it accept the quest.

**Implementation notes for whoever touches this:** authored quests live in `quests.json` and as a
separate session layer (NOT canon). The runtime uses an `accept_quest` tool; the offer set is a
**pure, replay-stable derivation** (`oubliette/quest/offers.py`) recomputed from the event log
each turn (the authored-quest link rides the quest-started record; the chosen outcome rides the
quest-updated payload and is never applied to state — so reload reproduces offers byte-identically).
Two refinements from playtesting: a **single-branch (linear) step auto-advances** on completion
even without an outcome (only genuine forks require one), and an accepted authored quest **keeps
its briefing + reward + fork-outcomes in the DM's active-quest context for its whole life**, not
just at the offer. Atria ships a seed set: a 3-stage branching chain ("The Empty Nets") and a
one-shot ("A Light Coin-Box").

---

## 8. Conventions & gotchas that keep things from breaking

These are hard-won. Internalize them.

- **THE STALE-SERVER GOTCHA (this bites the most often).** Oubliette-side code — DM prompts,
  the context builder, the combat bridge — are loaded into memory when the app server starts. After
  changing any of it you **must fully restart `python -m oubliette.app.server`.** The in-game
  "Reload world" button only re-reads the *pack*, not the *code*. (Portraits hot-reload, and the
  Arena spawns fresh per fight, so a stale server can *feel* live while silently dropping new model
  fields.) **First question on any "it didn't work in play" report: was the server restarted?**
- **Content generation = deterministic parse, not LLM transcription.** All the SRD bulk content
  (spells, classes, items, monsters) was built by **downloading the machine-readable 5e-database
  JSON (`curl`) and parsing it with a one-shot Python script** — *not* by asking a model to
  transcribe (the WebFetch reader garbles tables), and *not* by hand (the burnout trap).
  Completeness is *proven* by diffing ids against the source. **Use agents for prose (flavor
  descriptions); use deterministic parse for stats.** Verify stats against the source, not recall.
- **Verify on isolated copies — never touch OublietteDev's real save or the committed packs.** For live
  checks, point the game at a throwaway DB (`OUBLIETTE_DB=...`, e.g. the `preview-test` launch
  config on port 8055) and/or point The Forge at a temp copy of a pack
  (`OUBLIETTE_PACKS_ROOT=...`). OublietteDev is frequently mid-playtest on the real save.
- **PowerShell 5.1 + git:** multi-line commit messages with `-m` get mangled into pathspecs.
  **Always `git commit -F <file>`** (or use the Bash tool with a heredoc). **Stage explicit
  paths** — `git add -A` has swept up unrelated art twice. **Commit art/portraits separately**
  from code, in their own art-only commits.
- **The "Etteilbuo" dev codeword** — a message *containing* it tells the DM "this is a developer
  test": comply plainly and emit exactly the requested tools, even things the table rules would
  normally refuse (used so the live DM stops refusing test monster-spawns). **It must be sent with
  the OOC toggle OFF** — because **out-of-character turns never reach the model at all** (the loop
  builds a canned table-talk response in code; combat can only be staged from an in-character turn).
- **Portrait naming:** `<Name>.png`, underscored, in the source's `portraits/` dir
  (`content/srd/portraits/` or a pack's `portraits/`). OublietteDev hand-makes these; it's slow (image
  generation is the bottleneck), so they trickle in ~25 at a time in art-only commits. ~30 of 334
  SRD monsters done.
- **Single save, and a diagnostic trick:** there's one save (`oubliette-save.sqlite`). Narration
  isn't durably stored, but **player messages with their parsed verb/intent, and all quest/tool
  events, are** — so reading the save's event log is the best way to diagnose "what did the DM
  actually do?" during a playtest.
- **Deferred coupling:** Brightvale ships 3 pack creatures (`commoner`, `road_bandit`, `lean_wolf`)
  wired to `merchant_thom`'s stat block and to several tests — don't remove them casually; it needs
  a coordinated rewire. Revisit when the Forge's creature/NPC editor gets fleshed out.
- **The mounted-filesystem gotcha (Cowork/sandbox builds):** when working from the Cowork desktop
  tool, the repo is a Windows folder mounted into a Linux sandbox. The mount is flaky: it blocks
  file *deletion* from the sandbox (use the host delete affordance), and editor-channel writes can
  leave the sandbox with a *stale/truncated* view of a just-edited file (caught as a phantom syntax
  error on import). Workaround: write files via the **sandbox shell** when you need to run/test them
  immediately, and verify with `wc -l`/`ast.parse` before trusting a read. Git from the sandbox can
  also corrupt its index mid-write — keep commits atomic, stage explicit paths, verify after, and
  do any heavy git surgery from native Windows. The `.venv` is Windows-format; in the sandbox use
  system `python3` with `PYTHONPATH=.` (install `pydantic`/`pytest` with `--break-system-packages`;
  GUI/pygame tests can't run headless there and will error on import — not a real failure).

---

## 9. Where things stand & what's left

**The core game is complete and playable** end-to-end with a live streaming AI DM: character
creation, a multi-PC party, exploration with maps and audio, lore, trade, emergent *and* authored
quests, and tactical combat in the Arena.

**Phase C progress (as of the 2026-06 build sessions):** C1–C3 done (feature bridge, monster
data, spell curation 58→130). **C4 — P-VISION-LIGHT is COMPLETE**: fog/darkness/daylight as
obscuring/light zones with faithful pairwise vision (you can't see / can't be seen → advantage &
disadvantage cancel; darkvision does NOT pierce fog/magical darkness, blindsight & truesight do;
daylight dispels magical darkness of ≤ its level), plus the detection trio (See Invisibility, True
Seeing, Mislead). Attack/save log lines now carry a roll-type label (`[normal]`/`[advantage:…]`/
`[disadvantage:…]`). **C4 — P-CONTROL Dominate Person/Beast/Monster is COMPLETE**: a failed WIS
save flips the target to the caster's `team` + `is_player_controlled` (the radial then drives it
with its own actions — the turn loop keys off `is_player_controlled`); reverts on the caster losing
concentration or the target succeeding a WIS re-save when it takes damage; creature-type gated.
Full control is a deliberate simplification of RAW (caster-commands-each-turn) — fun > fiddly.
Lives in `arena/combat/domination.py`. **Compulsion is now BUILT** (`arena/combat/compulsion.py`):
WIS save → a COMPELLED condition that, at the start of the creature's turn, drags it toward the
caster (forced "pull", spends its full speed) and bars its reactions; concentration-linked,
reverts via the generic cleanup. Simplified vs RAW to single-target / toward-the-caster /
no per-turn re-save. **C4 — condition-zones / P-TERRAIN is COMPLETE**: `ActiveZone` now
applies a condition on a failed start-of-turn/entry save (folded into `_resolve_zone_damage`) —
Stinking Cloud (CON save or incapacitated, ≈ "lose your action"), Sleet Storm (DEX save or prone +
heavily obscured + difficult terrain), Plant Growth (instant difficult terrain, no save/zone). Zone
effects stay enemies-only (RAW hits all — a noted simplification). **C4 — Bardic Inspiration &
Cutting Words is COMPLETE** (`arena/combat/bardic.py`): a banked inspiration die flips an attack —
the inspired creature adds it (own miss → hit), a defending bard subtracts it via Cutting Words
(enemy hit → miss). **→ C4 is COMPLETE and its whole punch-list is now CLOSED** (the 2026-06-25
"wrap-up" session — commits 32db19f / 3a94ef7 / 2a6b149 / 6069630, 2586 green): (1) **real bard
sheets feed the pools** — `arena_bridge._bardic_resources` injects inspiration USES (CHA mod, min 1)
+ DIE size (d6→d8→d10→d12 at L1/5/10/15) and the feature-bridge emits a `cutting_words` Feature for
College of Lore bards, so it lights up from a genuine story→Arena handoff (not just hand-set
resources); (2) **dice now cover saves / contested checks / damage**, not just attacks (Bardic
Inspiration rescues a near-miss save or a lost grapple/shove contest; Cutting Words docks a
contested check and blunts a would-be-lethal damage roll) — still auto-optimal; (3) **player-choice
prompt** — a spend/skip popup on a player attacker's missed attack (own-attack only; NPCs auto-spend;
`BardicInspirationPopup` + manager `_pending_bardic_choice`, mirroring the reroll-popup pattern) —
**LIVE-VERIFIED by OublietteDev (2026-06-25)**: grant→spend→empty→re-grant loop all confirmed in `bard_lab`.
The fix-ups it took to get there: the GUI player path is `execute_attack_hit_check`→`complete_attack`
(NOT the `execute_attack` convenience method) — the prompt had to suppress auto-spend + defer there
(commit 84902cc); and the popup-positioning copied a `GridView.hex_to_screen` call that doesn't
exist — both the bard popup AND the latent forced-save-reroll popup now center on screen (commit
743ddfc). The prompt only fires when the die *could* reach the AC (miss-by ≤ die); else no prompt.
(4) Compulsion (above). Also fixed Cowork-session suite drift that was left red: 4 stale `adv:`/`dis:`
label assertions + the missing DOMINATED display badge. **→ Every C4 item is now live-verified or
unit-tested; 2587 green.** Per-feature playtest labs: `vision_lab`, `dominate_lab`, `terrain_lab`,
`bard_lab` (launch via `tools/lab.py <name>`; `bard_lab` has an AC-15 Practice Dummy so every miss
pops the prompt, plus Lyric for the grant + auto Cutting Words demo).

**Open / future work (roughly in the order it tends to come up):**
- **Stretch C4 one-offs** (metamagic, time stop, antimagic…) — mostly "do last or never". (The
  deferred Compulsion and the bard approximations are now DONE & live-verified — see above. Could
  still extend the spend/skip prompt to saves / Cutting Words if play wants the choice there; today
  those stay auto-optimal.)
- **Arena UI/UX cleanup pass (someday, BIG)** — OublietteDev's call (2026-06-25): the Arena was never
  optimized for looks on its first pass; it's functional but ugly. A dedicated visual/UX overhaul is
  wanted eventually — not scheduled yet. See [[oubliette-arena-ui-cleanup]].
- **C5 stragglers:** prone movement penalty; re-prepare-spells-on-long-rest. **C6:** the final
  "ship-readiness" combat playtest (use the labs as a starting battery).
- **The Forge creature/NPC editor** — currently the weakest authoring section; enriching it would
  also unblock the deferred Brightvale-creature cleanup.
- **More portraits** — the ongoing art grind (OublietteDev). 56/334 as of this session.
- **Possible later:** richer cross-turn "session memory" for the DM; non-gold coinage (a purist
  nicety, probably never).

**Per-feature test beds:** standalone Arena encounters launched by name via `tools/lab.py <name>`
(or a `.bat`) drop you straight into a fight to playtest one feature in isolation — `vision_lab`
and `dominate_lab` exist. Author a focused encounter JSON (inline `creature_data`), no launcher
code needed. Stockpiles encounters for the C6 playtest. Repo root was also tidied this session:
loose design docs → `docs/{design,roadmap,feedback}/`; SRD source dumps → gitignored `tools/raw/`.

**Foundational decisions that are settled** (don't relitigate without reason): SQLite behind a
repository abstraction; async edges / sync core; LLM-first routing behind the model seam;
provider-native structured output; only protected state + entity-creation are event-sourced
(open "flavor" content is plain last-write-wins); combat results carry absolute final values (not
deltas) so applying them is idempotent; difficulty numbers (DCs) are intentionally model-set (the
soft layer), state numbers are code-owned.

---

*Keep this file current as the project evolves — it's the fastest way for a new collaborator to
become useful without re-reading the whole history.*
