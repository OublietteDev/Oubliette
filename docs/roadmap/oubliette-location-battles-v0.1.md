# Battles by Location — plan v0.1

*Fights should look, sound, and play like WHERE they happen. A tavern brawl gets
the tavern background, the fiddle music, chairs as half-cover, and the ale spill
as difficult terrain — all authored in the Forge, per location.*

Pulled forward from the v2.0 wishlist (2026-07-04). Scoping verdict from the
two-sided audit: **the 45k→30k trim never removed the runtime** — it removed the
authoring UI and never built the story→Arena plumbing.

## Ground truth (what already works)

**Arena (current, in-repo):**
- `Encounter` still carries `music_track`, `background_image`,
  `background_offset`, `background_scale`, `grid_width`, `grid_height`, and
  per-hex `terrain[]` (`arena/models/encounter.py:44-78`).
- `combat.py load_encounter` already plays the music and renders the background
  if the fields are set; `grid_view` has full transform support.
- All 9 terrain types work in play (difficult, water, hazard+damage, pit, wall,
  half/¾/full cover) — pathfinding, LOS, and the AI respect them.
- Pathlib gift: `MUSIC_DIR / filename` and `Path("assets")/.../bg` are pathlib
  joins, and **joining an absolute path replaces the base** — so the bridge can
  pass absolute paths into pack assets with ZERO Arena changes.

**Old sim** (`Documents/DND Combat Sim main folder/…phase 11.1…`, ~40k lines):
- `src/gui/screens/encounter_setup.py` (1512 lines) is the cut editor: terrain
  paint palette (9 types), erase, grid −/+ spinners (clamped 5–40), music +
  background dropdowns, right-click-drag background pan + wheel scale
  (0.25–4.0×). Same codebase lineage as the current Arena → near-wholesale port.
- Assets survive: `tavernbrawl/forest/temple_background.png` + 7 music tracks.

**Oubliette side:**
- `stage_combat(request, repo, session)` already receives the session, which
  tracks `location` and `places` (`{place_id: PlaceNode}`) — no narrator or
  EncounterRequest changes needed.
- `PlaceNode` is the loader's slim runtime view of a `Place`; battle data
  threads through it.
- The Forge already has image upload (`POST /api/pack/{id}/image` →
  `<pack>/images/`), audio upload (`POST /api/pack/{id}/audio` →
  `<pack>/audio/`), serving GETs for both, and the soundscape "drawer" UI
  pattern to imitate. Export zips **everything** under the pack recursively —
  battle assets ride along for free.

## Design decisions

- **Battle data lives on the Place** as an optional `battle` block (pack-merged
  authoring, same as everything else). No sidecars (module-kit precedent).
- **Assets reuse the existing pack folders**: `background_image` → `images/`,
  `music_track` → `audio/` — the existing upload/serve endpoints just work.
- **Authored terrain replaces the kind-palette**: when a location has a battle
  block with terrain, `_terrain_for(kind)` is skipped (no chokepoint walls
  inside a tavern). No battle block → today's behavior, exactly.
- **Spawns respect authored terrain**: impassable hexes (wall/pit) seed the
  spawn-claim set so nobody spawns inside a wall; spawn columns derive from the
  actual grid width instead of module constants.
- **The battlefield editor is the Arena itself**, launched by the Forge server
  as a subprocess (same pattern as fights: in-JSON → GUI → out-JSON). The Forge
  uploads the raw assets; the Arena editor does what a web page can't — paint
  terrain on the real hex grid over the real background at the real size.

## Stages

### S1 — schema + bridge wiring (no new UI; hand-authorable)
1. `BattleMap` model in `oubliette/content/schemas.py`: `background_image`,
   `background_offset (0,0)`, `background_scale (1.0)`, `music_track`,
   `grid_width (20, 5–40)`, `grid_height (15, 5–40)`,
   `terrain: list[BattleTerrain{position, terrain_type, extra_data}]` with
   terrain_type a Literal mirror of the Arena's 9 values. `Place.battle:
   BattleMap | None`.
2. Thread `battle` through `PlaceNode` (`content/loader.py`).
3. Bridge: `build_encounter(..., battle=...)` uses the block's grid size,
   converts terrain (skipping out-of-bounds/unknown hexes defensively),
   populates music/background fields with **absolute paths** resolved against
   the pack dir (missing files degrade to None — `play_music` already no-ops).
   `stage_combat` does the `session.location` → `session.places[loc].battle`
   lookup. Fallback path byte-identical to today.
4. Tests: schema validation, loader threading, bridge conversion + spawn
   safety + fallback. Full suite green.
5. Live-test kit: copy the old tavern assets into the Atria pack and
   hand-author a battle block on a tavern location for OublietteDev to play.

### S2 — the Arena battlefield editor (the port)
- Engine rider: static `hazard` terrain hexes are currently COSMETIC — the
  entry-damage machinery exists only for spell zones. Wire terrain-hazard
  entry damage (`extra_data: {damage: "1d6 fire"}`) through the same
  zone-movement seam, so a hearth can be a hazard you shove people into
  instead of a wall.
- New screen in the current Arena, ported from the old `encounter_setup.py`,
  battlefield-only: terrain paint + erase, grid spinners, background
  pan/scale, music preview. **No creature placement** (fights are
  story-driven; spawns are the bridge's job).
- New entry point `python -m arena.battlefield_editor <in.json> <out.json>`:
  in = battle block + absolute asset paths; out = edited battle block.
  Mirrors `arena.handoff`'s contract.
- Save writes the out-JSON and exits; cancel exits without writing.

### S3 — Forge locations UI
- "Battlefield" drawer in the place editor (soundscape-drawer pattern):
  background image picker/upload (existing image endpoint), music
  picker/upload (existing audio endpoint + ▶ preview pattern), and an
  **"Edit battlefield"** button.
- New Forge endpoint `POST /api/pack/{id}/battle-editor/{place_id}`: writes
  the in-JSON (battle block + resolved asset paths), launches the Arena
  editor subprocess (blocking, like fights), reads the out-JSON, returns the
  updated block to the client, which folds it into the place form → normal
  pack save. (First subprocess in the Forge server — local app, same machine,
  same pattern as the play app's `run_arena`.)
- Validation warnings for missing battle asset files (mirror
  `_audio_warnings`).

### S4 (optional rider) — stock battle library
- Ship the old sim's 3 backgrounds + 7 tracks (OublietteDev's own assets) as a stock
  library selectable in the Forge, so new worlds have battle flavor without
  uploading anything.

## Out of scope (this arc)
- Per-ENCOUNTER (as opposed to per-location) battle maps; DM-chosen variants.
- Lighting/environmental_effects (schema exists Arena-side, no runtime).
- Spawn-zone authoring (bridge keeps placing spawns; editor doesn't).
- Lair-action authoring in the editor (Forge monster editor may want it later).
