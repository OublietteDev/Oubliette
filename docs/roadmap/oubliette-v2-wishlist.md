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
