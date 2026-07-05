# Oubliette v2.0 wishlist

*Living, unprioritized list of features deferred past the v1.0 .exe freeze.
Started 2026-07-02 when the Forge module-kit arc was scoped
(`oubliette-forge-module-kit-v0.1.md`). v1.0 freeze riders (Arena-subprocess
self-dispatch, asset paths) are intentionally NOT here — those are v1.0 work.*

## Character options (deferred from the module-kit arc)

- **Full custom classes** — 20-level tower of code-backed features, resource
  tables, spell progressions. Very high cost; revisit only with real demand.
- **Custom subclasses** — the plausible middle rung (features at 3–4 fixed
  levels; prose features are free at the table, Arena-teeth features are not).
- **Structured custom races/subraces** — ability bumps/speed/darkvision/languages
  are easy fields; the cost is combat-mechanical traits. Prose-trait v1 possible.
- **Truly custom / freeform spells** — anything beyond the chassis set (summons,
  walls, teleports, wish-likes).
- **Reskins** — pack-level aliases of SRD classes/races ("Tide Warden" = ranger
  mechanically, own name/flavor everywhere). Cheap and high-value; a strong
  candidate to pull FORWARD if the module-kit arc leaves appetite.
- **SRD allow/deny lists** — a world says "no dragonborn / no warlocks" and
  chargen honors it. Manifest-level, cheap; another pull-forward candidate.

## Module texture

- Pre-authored / keyed encounters (monsters bound to a place with trigger
  conditions) — today the AI DM improvises encounters by design.
- Factions as first-class content (membership, reputation, agendas).
- Timed / scheduled world events.
- Per-place DM-only notes (rider candidate in the module-kit arc).

## Forge

- Monster complex-trait FORM fields: legendary resistance count, regeneration,
  undead fortitude, death burst, lair actions, monster spellcasting — engine
  supports all of these; today they're raw-JSON-editor only.
- "Save chargen build to scenario default party" affordance.
- Persistent NPC recruitment + leveling (today: per-encounter allies only;
  re-author to level an NPC).
- Manifest editor (name/author/description/entry scenario/world map are
  read-only in the Forge today).
- ~~Custom backgrounds, area size, obstacle placement, music in the Arena based
  on where fights begin.~~ **SHIPPED early (2026-07-04, location-battles arc):**
  Place.battle blocks + bridge wiring + Arena battlefield editor + Forge UI +
  in-fight opacity/volume sliders + hazard entry damage. Plan:
  docs/roadmap/oubliette-location-battles-v0.1.md. Still wishlisted from that
  arc: a stock battle asset library (ship the original 3 backgrounds + 7
  tracks as out-of-the-box flavor), AI hazard-avoidance polish.

## Rules / engine

- House rules per world (variant initiative, custom conditions, etc.) — schema
  seam exists in the design doc, no wiring.
- Attunement ENFORCEMENT (the flag is recorded on items; the 3-item limit and
  attune-on-rest ritual are not enforced).
- Sanctuary spell (deferred until allies appear in regular fights).
- Surprise Attack; destructible-wall HP; lair-action content (needs non-SRD
  data); walls GUI authoring slice.

## App / infrastructure

- DM model picker (needs automatic model-release tracking).
- Canonization ceremony (DM-robustness arc follow-on).
- W1b context-drop patches (DM-robustness arc follow-on).
- NPC disposition system (parked from the DM interview findings).
- Unified OOC channel (low priority, ditto).
- Long-rest anti-spam gating (undesigned ask from the interview follow-ups —
  may land pre-v2 if it bites playtesters).
- Eleven Labs narration for the DM turns - characters in the Forge should have Eleven Labs 
  preferred voices attached, so that their speaking lines are done by a voice that matches their
  character. Likely will use a Haiku model to break the player facing DM turn into an API readable
  set, then send to Eleven Labs. Then stream the tokens to the player as well as the narration. Make
  optional. (Added by OublietteDev).
- Multiplayer. Have no idea how this will work, but we can make it happen I think. (Added by OublietteDev).
- Mobile phone app. Only if people overwhelmingly beg for this. If so, I will begin charging. Not excited
  to build and support that. (Added by OublietteDev).
