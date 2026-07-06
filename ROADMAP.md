# Roadmap

Where Oubliette is headed. This is a direction, not a promise — priorities shift with what players actually ask for. Have an opinion? Open an issue.

## Now — v0.9

The current release. The full game, the Forge, and the Arena are all here and playable; see [FEATURES.md](FEATURES.md) for everything that already works, and [Known issues](README.md#known-issues) for the rough edges.

## Next — toward v1.0

The push to a true one-click release:

- **Polishing the known v0.9 issues** into a stable 1.0.

## Later — candidates for v2.0

Unordered, and gated on demand. The big themes:

### Deeper world-building in the Forge
- **Reskins** — rename and reflavor an SRD class or race ("Tide Warden" that plays as a ranger) with no mechanical work.
- **Per-world SRD allow/deny lists** — a world can say "no warlocks, no dragonborn" and character creation honors it.
- **Custom subclasses** and structured custom races — more of your own mechanics, not just prose.
- **Form-based editing for advanced monster traits** — legendary resistance, regeneration, lair actions, and monster spellcasting are all supported by the engine today, but currently need the raw-data editor.
- **A manifest editor** — edit a world's name, author, and description directly in the Forge.

### Richer worlds
- **Keyed encounters** — monsters bound to a place with trigger conditions (today the AI improvises encounters by design).
- **Factions** as first-class content — membership, reputation, and agendas.
- **Timed and scheduled world events.**
- **Persistent NPC companions** you can recruit and level over a campaign (today allies join fight-by-fight).

### Rules & engine
- **Difficulty & challenge settings** *(built — in testing on `main` for a future release)* — decide how dangerous your world feels. Choose a difficulty when you start a campaign (Story, Adventure, Challenge, or Hardcore, or set the dials yourself), changeable later in Settings. It caps the challenge rating of the encounters the AI improvises to the party's real strength, gates long rests behind the fiction (a night needs a safe-enough moment and costs lodging coin or rations, with interrupted camps on the harshest settings), lets Forge quests declare a minimum party level ("starts at party level 3+") that stays hidden until you've earned it, and gives the DM a clear read on the party's strength when it sizes up a fight. Pairs naturally with keyed encounters to shape a campaign's arc. Home, too, to hardcore mode: if the whole party falls, the DM narrates the end of the story, writes the campaign's final chapter, and says goodbye — that save is over for real.
- **House rules per world** — variant initiative, custom conditions, and other table tweaks.
- **Attunement enforcement** — the 3-item limit and attune-on-rest ritual (the flag is already tracked).
- **Arena test beds** - add the ability to preview spells, custom attack animations, or run simulations using existing combat AI to balance custom monsters and classes.
- Filling the last SRD gaps: the Sanctuary spell, Surprise, Ambushes, destructible walls, and more.

### The experience
- **Voiced narration** — optional AI voice for the DM's turns, with the Forge letting you assign a preferred voice per character so NPCs sound like themselves. The plan is to use ElevenLabs (high latency, can be very expensive but superior quality) and Kokoro 82M locally (low latency, low cost, small memory footprint, decent quality but lacking emotion). Requires touching the DM prompt.
- **Trinkets** - optional authored quest add-ons that can be stored in the player journal. A fragment of a map, a note from a powerful noble, etc.
- **Upgraded player journal** - different fonts, trinkets (see above), custom backgrounds to turn your journal into something that actually represents your journey. Possible "page turning" animations.

## Someday — the big maybes

- **Multiplayer.** No fleshed out design yet, but it feels possible. Early designs include one player functioning as the server, allowing others to connect.
- **A mobile app.** Only if players overwhelmingly ask for it. For the amount of development required for this, I would charge for access to the app. Not something I want to do, but am willing if the demand is there.

---

*Curious about the design thinking behind all of this? The specs live in [`docs/design/`](docs/design/).*
