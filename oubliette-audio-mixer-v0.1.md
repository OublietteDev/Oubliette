# Oubliette Soundscape — Location-Driven Audio Mixer (design v0.1)

*Status: design doc, revised after the user's first review (2026-06-07); to be locked
before building. A layered ambient-audio system: the world has a living soundscape that
follows where the party is, what time it is, and what the weather is doing — a theme and
a town murmur in Brightvale, a fiddle and mug-clinks in the tavern, gulls and waves at the
docks, rain when a storm rolls in. Companion to `oubliette-table-spec-v0.2.md` (the
engine), `oubliette-content-pipeline-v0.1.md` (what a pack IS), and
`oubliette-creator-tool-v0.1.md` (The Forge).*

*Scope decided with the user: **audio is derived from authoritative state, never played by
the LLM**; **time-of-day and weather become real engine state** (the DM proposes, code
records); **the engine does the mixing** — the only player-facing controls are a Music
volume, a Sound-effects volume, and a mute-all; the **first build is the smallest safe
slice** — one ambient bed per location that crossfades as you travel, needing no new state.
The full layered vision is designed here but built through the seams.*

> Tags (as in the other docs): **[LOCKED]** decided with the user · **[PROPOSED —
> confirm]** a default this doc suggests · **[OPEN]** still to decide.

---

## 0. Plain-language overview (read this first)

Right now the world is silent, and "it's night" or "a storm is rolling in" exists only as
words the DM writes. The **Soundscape** gives the world an ear: as you move and as the day
and weather change, a set of sounds fades in and out to match.

Picture the sound as a stack of **layers**:

- A **theme** — the signature bed of the *top-level place* you're in. Brightvale's theme
  keeps playing as you cross from the Coin Quarter to the docks to the tavern, so your
  **ears tell you where you are**: same theme, still in Brightvale. A dungeon's theme rides
  every room of the dungeon. The theme is *passed down* to all of a place's children.
- **Local sounds** that belong to one spot only: the street crowd in Brightvale's open
  squares, a soft fiddle and mug-clinks in the tavern, gulls and waves at the docks.
- **Time** swaps things out: at night the bed goes hushed and a fire crackles.
- **Weather** adds layers: rain, or wind, or both for a storm — with intermittent thunder.

Two ideas keep this from becoming a tangle, and everything below serves them:

1. **The sound follows the state, it doesn't drive it.** The AI never "plays a sound." It
   does what it already does — moves the party, and (new) tells us the time and weather —
   and *code records that*. The mixer simply reads the resulting state and renders it. So
   the soundscape can never contradict the game, and the firewall (spec §1) is untouched.

2. **The sound rides the map.** Each place has its own sounds; a parent **passes chosen
   sounds (its theme) down** to its children, while other sounds stay **local** to one
   place — exactly the place hierarchy The Forge already authors (Brightvale ▸ the tavern).
   No second structure to learn or keep in sync.

---

## 1. What it is, and what it is NOT

| | |
|---|---|
| **It IS** | An engine-driven **mixer** that plays a stack of looping "beds" and sparse "one-shots," chosen by the party's current location, time-of-day, and weather — all of which are authoritative state. The player only ever adjusts volume. |
| **It is NOT** | A way for the LLM to trigger sounds, and not a soundtrack scripted per scene. There is no "play this now" from the AI; there is only state, and a renderer that follows it. No in-game sound editing — that's The Forge's job. |

**[LOCKED]** Audio is a pure function of authoritative state. The mixer is a *renderer*.

---

## 2. The core principle: a soundscape is derived state [LOCKED]

At any moment the engine can answer one question deterministically:

```
soundscape = f(location and its ancestors' passed-down sounds, time_of_day, weather)
```

- **Code resolves it.** The layering logic (which cues are passed down, which are local,
  condition matching) lives in code, like the map's discovery redaction lives in
  `/api/map`. The browser receives a flat, already-resolved list — "play these layers at
  these volumes" — and just renders audio. The client stays a dumb, swappable renderer.
- **The LLM only proposes.** The DM changes state through the same firewall as everything
  else: it travels the party (existing `LOCATION_CHANGED`), and — new — it reports the
  current time/weather as part of its turn, which code records (§5). It never names a sound.
- **It persists and replays.** Because the soundscape derives from recorded state, a
  reloaded save restores the exact soundscape, and the byte-identical-replay guarantee
  (spec D9) holds — audio adds no authoritative state of its own beyond the environment
  fields, which are event-sourced like location.

This is the whole safety story: the mixer can be as rich as we like and still cannot break
the game, because it has no authority — it only listens.

---

## 3. The layer model (the heart of it)

A soundscape is a set of **layers** (cues). Two kinds, two categories, two scopes.

**Kind** — how it plays:
- **Beds** — continuous loops that define the space: the theme, a town murmur, waves,
  rain, wind. They **crossfade** when the active set changes (you travel, night falls, a
  storm starts). Several play at once, each at its own volume.
- **One-shots** — short, sparse sounds fired at *randomized intervals* so the world
  breathes instead of looping mechanically: a mug clink, a chair scrape, a gull, a
  thunderclap. Each carries a gap range (e.g. every 8–25s) and a little volume/pan jitter.

**Category** — which player slider owns it: **music** or **sfx**. The theme is music; the
murmur, waves, rain, wind, clinks and thunder are sfx. (Drives the two volume sliders, §6.)

**Scope** — how far it reaches in the place tree:
- **Passed down** — plays at this place *and every place inside it*. The top-level
  **theme** is the canonical passed-down bed (the "where am I" signal); a dungeon's theme
  is passed down to all its rooms.
- **Local** — plays *only* at this exact place. The street crowd is local to Brightvale's
  open squares; the fiddle is local to the tavern.

**Condition** — when it's active: a `time` (any / day / night) and a `weather` (any /
clear / rain / storm / wind). The fire crackle is `time: night`; thunder is
`weather: storm`; rain is `weather: rain` (or also `storm`, author's choice).

**Resolving the stack (in code):** walk from the current place up through its ancestors;
take *every cue local to the current place* plus *every passed-down cue from the current
place and its ancestors*; keep those whose `time`/`weather` match; emit the flat list with
each cue's volume and (for one-shots) gap range and category. The client crossfades from
what it's playing now to this list.

*No engine muffling.* If an author wants the rain to sound different indoors, they author a
separate "rain on roof" cue on the indoor place and don't pass the "rain in streets" cue
down into it. The model gives authors that control directly, and us less code to own.

---

## 4. Authoring (in The Forge) [PROPOSED — confirm; may evolve after testing]

Audio is authored where places already are. A place gains an **Audio** section: a list of
**cues**, each is *pick a sound + say how it behaves*:

- **Sound** — pick a file (uploaded into the pack, browser-side, like map art).
- **Kind** — *ambient loop* (bed) or *occasional sound* (one-shot).
- **Category** — *music* or *sound effect* (which volume slider controls it).
- **Reach** — *plays in sub-locations too* (passed down — e.g. a theme) or *only here*
  (local — e.g. a street crowd). **[default: only here]**
- **When** — time (any / day / night) and weather (any / clear / rain / storm / wind).
- **Volume**, and for occasional sounds a **gap range** (how often it fires).

"Pick, don't type" holds (creator-tool §5): you choose a sound from the pack's uploaded
files, not a path. Sounds live in `content/packs/<pack>/audio/` and travel with the pack,
exactly like `images/` — so packs stay self-contained and shareable.

Worked examples the model should make natural:
- *Brightvale (top-level):* theme = bed / music / **passed down**; street crowd = bed /
  sfx / **local**, `time: day`; a hushed night murmur = bed / sfx / local, `time: night`.
- *The tavern (inside Brightvale):* keeps Brightvale's theme automatically; adds a fiddle
  (bed / sfx / local) and mug-clink + chair-scrape one-shots (sfx / local). For muffled
  rain, the author adds a "rain on roof" cue (sfx / local, `weather: rain`).
- *The docks:* gulls (one-shot) + waves (bed), both local; Brightvale's theme still rides.

Weather and time are **runtime** concepts, not authored per place — but a **scenario** can
set the **starting** time/weather. The Forge gets a small spot for that default.

*Note (the user's flag):* this section is most likely to shift once we hear real packs —
the cue form may want grouping or presets. We'll revisit after S1–S3.

---

## 5. Environment state: time-of-day & weather [LOCKED — engine-owned]

The new authoritative state, modeled like location:

- **Fields.** `time_of_day` ∈ {day, night} and `weather` ∈ {clear, rain, storm, wind}.
  **[LOCKED]** — intentionally coarse; "storm" is just a value authors hang rain+wind cues
  under. The enums can grow later without reshaping anything.
- **The DM proposes, code records.** The DM is **told the current time/weather** in its
  per-turn context, and **reports them back** as two optional fields on its existing
  structured turn output. Code diffs the report against current state; on a change it
  records an `ENVIRONMENT_CHANGED` event and updates state — replayable, like
  `LOCATION_CHANGED`. No separate tool; it rides the structured-output seam the DM already
  uses. The DM (capable as it is) sets these from what the story has done — dusk falling,
  a storm blowing in off the bay.
- **Defaults.** A scenario sets the opening `time_of_day`/`weather`; absent a value the
  engine assumes `day` / `clear`.
- **[OPEN — to workshop]** the *prompting*: how to ask each turn so the DM keeps the
  environment **stable** and only changes it when the narrative clearly turns (we don't
  want weather flickering). Likely: "carry the current values forward unchanged unless the
  story has just changed them." Tunable, and easy to gate to travel-turns if needed.

This is the genuinely new subsystem, and it is deliberately **not** in the first build (S5).

---

## 6. The mixer (browser side)

- **Web Audio API.** Each bed is a looping buffer → gain node → output; crossfades are gain
  ramps. One-shots are buffers scheduled at random gaps with small gain/pan jitter.
- **Two category buses + master.** Every cue routes through a **music** or **sfx** gain bus
  → a master gain → output. The player's controls are exactly those: a **Music** slider, a
  **Sound-effects** slider, and a **Mute all** toggle. **[LOCKED]** That's the entire
  player-facing surface; it lives by the enable-sound control. Volumes persist locally.
- **Assets load on demand** (fetch → `decodeAudioData`), cached; the current location's and
  its immediate neighbors' sounds **preload** so travel doesn't gap.
- **The autoplay gate.** Browsers block sound until a user gesture. A one-time, friendly
  **🔊 enable sound** control resumes the audio context on first click; until then the game
  is silent and clearly says so.
- **The server hands over a resolved spec.** The current soundscape (the flat layer list
  from §3, computed server-side) rides the **turn payload** (and a `GET /api/soundscape`
  for initial load), like `/api/map`. The client **diffs** it against what's playing and
  crossfades the difference. No audio logic leaks into the client.

---

## 7. Build order (through the seams) [PROPOSED — confirm]

Each step is audible before the next begins.

1. **S1 — location beds (the smallest safe slice [LOCKED]).** One ambient loop per place;
   the server resolves "current bed" from `location`; the client crossfades it on travel;
   the autoplay gate + master volume; sounds served from `pack/audio/`. Ships with **a few
   synthesized placeholder loops** so there's something to hear immediately (swappable for
   the user's real assets). Authoring is minimal (a single bed per place). *Proves the
   whole pipeline — pack audio → state → mixer → crossfade — with no new state.*
2. **S2 — theme inheritance + layers.** Passed-down vs local scope, multiple beds per
   place, the music/sfx category split + the two player sliders. *Now Brightvale's theme
   rides into the tavern while the street crowd stays outside.*
3. **S3 — one-shots.** Sparse, randomized incidental sounds (clinks, gulls, chair scrapes),
   with gap ranges and jitter.
4. **S4 — Forge authoring.** The full **Audio** section (§4): upload sounds, add cues with
   kind / category / reach / when / volume / gap. The linter checks audio refs resolve.
5. **S5 — environment state.** `time_of_day` + `weather` fields, the DM report →
   `ENVIRONMENT_CHANGED` event, DM context, scenario defaults; condition-matching goes live.
6. **S6 — weather/time polish.** Night bed swaps, fire crackle, rain / wind / storm beds,
   intermittent thunder — with crossfades on every environment change, and the prompting
   workshopped (§5).

Later niceties: area-level weather sets; time advancing on a long rest; per-cue presets.

---

## 8. Validation & portability

- **Linter (loader).** Every audio cue's file must exist in the pack's `audio/` folder
  (mirrors the existing image-ref check); cue `kind`/`category`/`time`/`weather` must be
  valid enums. A pack the Forge blesses still loads (creator-tool §3).
- **Portable.** Sounds are copied into the pack (`audio/`) and referenced by bare filename,
  like map art — zip the pack, hand it to a friend, the soundscape travels intact.
- **Honest cost: pack size.** Audio is heavier than art. **[OPEN]** keep loops short and
  seamless; pick a compressed format (ogg / opus / mp3); a per-pack size note in the Forge.

---

## 9. Open questions

**Resolved with the user:**
1. Audio is **derived state**, never LLM-played — **[LOCKED]**.
2. Time/weather are **engine-owned** (DM reports, code records) — **[LOCKED]**.
3. First build is the **location-bed slice**, no new state — **[LOCKED]**.
4. **Time = day/night; weather = clear/rain/storm/wind** — **[LOCKED]**.
5. **Player controls = Music vol + SFX vol + mute-all**; cues carry a music/sfx category —
   **[LOCKED]**. Nothing else is player-facing.
6. **No engine muffling** — replaced by per-cue **passed-down vs local** scope; authors
   compose indoor/outdoor differences themselves (e.g. a separate "rain on roof") —
   **[LOCKED]**.
7. **Assets** — the user supplies real sounds; we ship **synth placeholders** for S1
   testing — **[LOCKED]**.

**Still open [OPEN]:**
8. **Environment prompting** — how to elicit the DM's time/weather each turn so it stays
   stable and changes only when the story turns (every turn vs travel-only; exact wording).
   *To workshop during S5.*
9. **Audio format & size budget** — format and a sensible per-pack ceiling.
10. **Does time advance on its own** (long rest → night) in a later phase, or stay fully
    DM-reported?
11. **Authoring ergonomics** — the §4 cue form may want grouping/presets once we hear real
    packs (the user's flag). Revisit after S1–S3.
