# Oubliette

**An AI Dungeon Master that never cheats — with real dice, a real tactical battlefield, and worlds you build yourself.**

Oubliette is a free and open-source tabletop RPG you play in your browser, powered by the D&D 5e SRD. You type what your character does in the first person; an AI narrates the world's reply as your DM. But unlike a plain chatbot, **the code owns the game — the AI only tells the story.** Your HP, gold, XP, inventory, and every die roll live in a rules engine the model can't reach; it can only *propose* changes that the code validates first. The result is an AI DM that improvises freely but can never fudge your character sheet or hand-wave a fight.

It ships as three programs that share one engine:

| | | |
|---|---|---|
| 🎭 **Oubliette** | The game — an AI DM you play in your browser. | `play.bat` |
| 🔨 **The Forge** | Build your own worlds — no coding, ever. | `forge.bat` |
| ⚔️ **The Arena** | A full D&D 5e tactical combat engine. | launches from the game |

> **Status: v1.0.** The full game — with voiced narration, persistent companions, and a living world of factions, clocks, and scheduled events. A handful of honest rough edges remain (see [Known issues](#known-issues)).

---

## What makes it different

Most AI-DM projects are a clever prompt around a chatbot. Oubliette is a **rules engine with an AI narrator bolted on** — and that changes everything.

### 🎲 The AI can't cheat — the firewall
The model never writes your state. It narrates, and it *requests* changes through a small set of validated tools. Say *"I now have 10,000 gold"* and the DM gives you a diegetic "no" — no gold moves. Every change and every die roll is written to an append-only log **before** it happens, so a saved game reloads by *replaying that log*: the dice are never re-rolled and the model is never re-asked. Your character sheet is always the real, code-derived truth.

### ⚔️ Combat is *fought*, not narrated
When a fight breaks out, Oubliette doesn't ask the AI to describe who wins. It hands the encounter to **The Arena** — a genuine hex-grid D&D 5e combat simulator with initiative, the full action economy, all 15 conditions, concentration, cover, opportunity attacks, spells with real area-of-effect shapes, legendary and lair actions, and a tactical AI that flanks, kites, focus-fires, and aims its fireballs. You play the fight; the outcome — HP, spent spell slots, conditions, the dead — flows back into the story.

### 🌍 Worlds that are authored *and* alive
Your world isn't just an AI hallucination each session. In **The Forge** you author real places, NPCs, branching quests, monsters, magic items, and maps — and the game plays them faithfully. But the AI DM also *invents* as it goes, and its inventions become **canon**: an NPC it names, a rumor it plants, a promise it makes are all recorded, promoted to permanent world-truth when they matter, and fed back to keep the story consistent for months. Authored backbone, living memory — not one or the other.

---

## Quick start

**Play it (Windows, easiest):**
1. Double-click `setup.bat` once — it builds the environment and, if your PC has no suitable Python, downloads a private one into the game folder (nothing to install).
2. Double-click `play.bat`. Your browser opens to the start menu.
3. Click **Connect your AI**, pick a provider, paste a key, and go. (Claude Sonnet 5 is the recommended model and most heavily tested)

**Play it (Currently only tested on Windows):**
```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate     # macOS/Linux: source .venv/bin/activate
pip install -e ".[web]"
oubliette-play                 # opens the browser game
```

**Bring your own model.** The **Connect your AI** panel supports **Anthropic**, **OpenAI**, **Google Gemini**, and **local models** (any OpenAI-compatible server — Ollama, LM Studio, llama.cpp — no key needed). The model id is free text, so new models work the day they ship, and a **Test** button makes one tiny real call so a typo shows up as a sentence, never mid-game. Your key is stored locally in a gitignored file, never committed. No key? The game runs a scripted **Offline Mode** demo so you can look around.

**See what a session costs — and pay less.** With Anthropic connected, a **Token Usage** panel (☰ menu) tallies the session's exact token counts from the API's own reports and prices them in dollars. The standard Claude rates are built in, and an optional pricing field in Connect your AI takes any model's own $-per-million-token rates, so the meter reads true even on models it's never heard of. Behind the scenes, **prompt caching** re-bills the unchanging part of every turn — the DM's standing instructions, its tool kit, and your campaign's past-session memory — at roughly a tenth of full price while you play, so long sessions and long campaigns stay affordable.

---

## The three apps, a little deeper

### 🎭 Oubliette — the game
A structured turn loop runs under every message: the DM *assesses* what you're attempting and sets a difficulty, the **code** rolls the dice with your real sheet bonus, and the DM narrates the result it's given. Around that core: full SRD character creation and a party of up to six heroes, XP-gated leveling, short/long rests, a shared coin purse with real cp/sp/gp/pp and haggling merchants, an inventory with equip toggles, emergent and authored quests, a visit-gated world map, a location-driven ambient soundtrack, a searchable bestiary, and a session-zero **table contract** (a tone dial plus Lines & Veils the DM always honors). It remembers: a session wrap writes a spoiler-free "previously…" for you and private continuity notes for the DM, so next session picks up where you left off.

New in v1.0, the world got a pulse: a **voiced narrator** reads the DM aloud entirely on your machine (two local voice tiers, no cloud, no keys), **companions** you recruit or buy stay on the party card, grow, and fight at your side with their real monster kits, and the **living world** keeps its own time — authored encounters fire where the author bound them, factions track your standing (and can sour on you in the dark), a campaign clock counts nights slept and roads travelled, and scheduled world events happen whether you attend or not, reaching you as rumor if you're elsewhere.

### 🔨 The Forge — build your own worlds
A visual studio — no code, ever. Author places and a drag-arrange world map (with visit-gated redaction), NPCs and shops, branching quests with player hooks and DM-only briefings, and full monster stat blocks (clone any of the 334 SRD creatures and tweak). The module kit adds **magic items**, **custom backgrounds**, and a **spell builder**, all of which merge straight into character creation and the Arena. You can even paint a battlefield — terrain, hazards, cover — for fights that start in a given location. Its promise: the Forge validates your world with *the game's own loader*, so a green "✓ Ready to play" badge means it really will. Share a world as a single `.zip`.

### ⚔️ The Arena — real tactical combat
A standalone hex-grid 5e combat engine (also playable on its own). Creatures from Tiny to Gargantuan, footprints and difficult terrain and line-of-sight, typed damage through resistances and immunities, on-hit riders, upcasting, 158 spells, walls and zones and telegraphed area effects, legendary/lair/recharge/regeneration mechanics — and an opponent AI with editable personalities (berserker, archer, coward, bodyguard…). A presentation layer sequences every hit so damage numbers, HP drops, and sounds land on impact, with charge lunges and danger telegraphs.

📖 **The complete, code-verified feature inventory is in [FEATURES.md](FEATURES.md).**

---

## Content

Every world stands on a content-complete **SRD 5.1** layer: all 12 classes and their subclasses, 9 races, **319 spells**, **~590 items** (mundane, magic, and poisons), **334 monsters** with portraits, all 15 conditions, plus the SRD background and feat. Worlds you build in the Forge merge their own content on top.

## How it works (for the curious)

- **Event-sourced core** — every protected change is an atomic, replayable operation; state is `seed(authored world) + replay(event log)`, byte-identical on reload.
- **Provider-agnostic** — a thin `LLMClient` seam with native Anthropic and OpenAI-compatible (OpenAI/Gemini/local) adapters.
- **No build step** — the game and Forge are FastAPI servers each serving one self-contained HTML page.
- **~65k lines of source, ~56k lines of tests.**

```bash
pip install -e ".[dev]"
pytest                          # the full acceptance + engine suite
```

## Roadmap & known issues

- 🗺️ **[ROADMAP.md](ROADMAP.md)** — what's planned beyond v1.0.
- 🐞 **[Known issues](#known-issues)** — see below.

## Known issues

*v1.0 is stable and fun, but honest about its rough edges. Full list to be tracked in GitHub Issues.*

- **Bestiary art is ~20% complete.** Every creature works fully in the Arena — all abilities, actions, spells, and legendary actions — they just show a generic token until art is added. This grows slowly over time. Art added via a pack is unaffected and displays fine in the bestiary.
- **API calls occasionally drop.** A dropped connection mid-call surfaces an error (no effect on gameplay or the DM's memory) — but it's annoying if it takes ~300 seconds to time out.
- **A few racial traits are still story-only.** v1.0 wired most of them into combat (Relentless Endurance, the dragonborn breath weapon and ancestry resistance, dwarven poison resistance, and more), but Halfling Lucky (the reroll-on-1), the tiefling's Infernal Legacy spells, and Gnome Cunning still await engine support.
- **Walls are indestructible.** You can cheese melee enemies by dropping a Wall of Force or Wall of Stone and then plinking them with cantrips.
- **Charge attacks don't animate.** Pounce, Trample, and Charge resolve correctly in code but have no visual yet — needs investigation and a fix.
- **Encounter balance is still being tuned.** v0.9.2 added a party-CR budget — improvised fights are now sized to the party's real levels and size and to your chosen difficulty (Story → Hardcore) — but the CR bands themselves will take several more balancing passes before every fight feels fair at every level.
- **Arena token art can be sized inconsistently.** The plan is a token previewer that lets you adjust framing so your art (and the current bestiary art) is represented well.
- **New Game character creation uses the current session's ruleset, not the chosen world's.** When you start a New Game, the background and spell options come from whichever world was last loaded — so a brand-new world's own pack content can't be picked at its own character creation. Workaround: start the New Game once with the world/pack you want, save and close, then start the New Game a second time — the options now reflect that world. This only matters if you regularly switch between multiple packs. (Your save is safe throughout: it isn't deleted until character generation finishes.)

---

## License & attribution

Oubliette Table is a **free and open-source** project. It includes material from the **System Reference Document 5.1** by Wizards of the Coast LLC, used under the Creative Commons Attribution 4.0 International License. Bundled fonts (MedievalSharp, PT Serif) are used under the SIL Open Font License. See [`NOTICE`](NOTICE) for details.
