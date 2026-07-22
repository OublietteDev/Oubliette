# Oubliette

**An AI Dungeon Master that never cheats — with real dice, a real tactical battlefield, and worlds you build yourself.**

Oubliette is a free and open-source tabletop RPG you play in your browser, powered by the D&D 5e SRD. You type what your character does in the first person; an AI narrates the world's reply as your DM. But unlike a plain chatbot, **the code owns the game — the AI only tells the story.** Your HP, gold, XP, inventory, and every die roll live in a rules engine the model can't reach; it can only *propose* changes that the code validates first. The result is an AI DM that improvises freely but can never fudge your character sheet or hand-wave a fight.

It ships as three programs that share one engine:

| | | |
|---|---|---|
| 🎭 **Oubliette** | The game — an AI DM you play in your browser. | `play.bat` |
| 🪑 **Host a table** | The same game, multiplayer — friends join with a code. | `host.bat` |
| 🔨 **The Forge** | Build your own worlds — no coding, ever. | `forge.bat` |
| ⚔️ **The Arena** | A full D&D 5e tactical combat engine. | launches from the game |

> **Status: v1.1.** The table seats a whole party now — **multiplayer** is here: one player hosts, friends join from their own browsers, on the couch wifi or across the internet. All of v1.0 rides along: voiced narration, persistent companions, and a living world of factions, clocks, and scheduled events. A handful of honest rough edges remain (see [Known issues](#known-issues)).

---

## What makes it different

Most AI-DM projects are a clever prompt around a chatbot. Oubliette is a **rules engine with an AI narrator bolted on** — and that changes everything.

### 🎲 The AI can't cheat — the firewall
The model never writes your state. It narrates, and it *requests* changes through a small set of validated tools. Say *"I now have 10,000 gold"* and the DM gives you a diegetic "no" — no gold moves. Every change and every die roll is written to an append-only log **before** it happens, so a saved game reloads by *replaying that log*: the dice are never re-rolled and the model is never re-asked. Your character sheet is always the real, code-derived truth.

### ⚔️ Combat is *fought*, not narrated
When a fight breaks out, Oubliette doesn't ask the AI to describe who wins. It hands the encounter to **The Arena** — a genuine hex-grid D&D 5e combat simulator with initiative, the full action economy, all 15 conditions, concentration, cover, opportunity attacks, spells with real area-of-effect shapes, legendary and lair actions, and a tactical AI that flanks, kites, focus-fires, and aims its fireballs. You play the fight; the outcome — HP, spent spell slots, conditions, the dead — flows back into the story.

### 🪑 One table, many chairs
One player runs `host.bat`; everyone else joins from a plain browser with a five-letter code — nothing to install, phones welcome. Same wifi works out of the box, and for remote friends the host gets a secure internet address opened automatically (a Cloudflare quick tunnel — no router surgery, no port forwarding). The whole table plays **one story with one DM**: it knows who's speaking and answers by name, keeps an eye on who hasn't had a scene lately, and phrases its offers to the group. Seats remember whose hero is whose, any player can act or confirm, fights stream to every browser so each player clicks their own moves, and the voiced narrator reads to every ear that asks. One click on the **Invite** button puts the address and code on your clipboard, ready for the group chat.

### 🌍 Worlds that are authored *and* alive
Your world isn't just an AI hallucination each session. In **The Forge** you author real places, NPCs, branching quests, monsters, magic items, and maps — and the game plays them faithfully. But the AI DM also *invents* as it goes, and its inventions become **canon**: an NPC it names, a rumor it plants, a promise it makes are all recorded, promoted to permanent world-truth when they matter, and fed back to keep the story consistent for months. Authored backbone, living memory — not one or the other.

---

## Quick start

**Play it (Windows, easiest):**
1. Double-click `setup.bat` once — it builds the environment and, if your PC has no suitable Python, downloads a private one into the game folder (nothing to install).
2. Double-click `play.bat`. Your browser opens to the start menu.
3. Click **Connect your AI**, pick a provider, paste a key, and go. (Claude Sonnet 5 is the recommended model and most heavily tested)

**Play with friends:** double-click `host.bat` instead of `play.bat`. It starts the same game with the table open: a join code on the door, and — when the internet door opens a few seconds later — a public address on the **Invite** button. Friends need nothing installed; they open the link, type a name and the code, and they're seated. A tip from our playtests: the table runs best like a real one — talk it over out loud (a group call works great), let one player commit the party's action, and speak in your own hero's voice for personal beats. The DM tracks who says what and answers accordingly.

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

New in v1.1, the table got chairs — **multiplayer** (see [One table, many chairs](#-one-table-many-chairs)) — and the rules got deeper: **attunement** is enforced for real (three bonds per hero, made at rests, broken when the item leaves your hands), a world's author can set **house rules** the engine itself enforces (side initiative, flanking, crits on 19–20, brutal crits, potions as a bonus action), **ambushes genuinely surprise** (the caught side loses its opening turn — and the Alert feat finally earns its keep), and **walls can be broken through**. Table-wide settings behave like table rules now, too: flip **Hidden Rolls** and the DCs and pass/fail vanish from every player's screen at once.

### 🔨 The Forge — build your own worlds
A visual studio — no code, ever. Author places and a drag-arrange world map (with visit-gated redaction), NPCs and shops, branching quests with player hooks and DM-only briefings, and full monster stat blocks (clone any of the 334 SRD creatures and tweak). The module kit adds **magic items**, **custom backgrounds**, and a **spell builder**, all of which merge straight into character creation and the Arena. You can even paint a battlefield — terrain, hazards, cover — for fights that start in a given location. Its promise: the Forge validates your world with *the game's own loader*, so a green "✓ Ready to play" badge means it really will. Share a world as a single `.zip`.

New in v1.1, the Forge grew a **proving ground**: preview any spell or attack on training dummies to see exactly what it looks like and does, drop your custom monsters against a benchmark party that never flinches, and let the war room run an encounter a hundred times headless — round caps, honest defeat scoring, the lot — so you know whether your boss fight is a bloodbath or a pushover before a player ever meets it. Authors also got a **manifest editor** (a world's name, author, and description — no files to hand-edit) and **per-world character-creation limits**: a world can say "no warlocks, no dragonborn" and the creation wizard honors it.

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
- **~67k lines of source, ~52k lines of tests.**

```bash
pip install -e ".[dev]"
pytest                          # the full acceptance + engine suite
```

## Roadmap & known issues

- 🗺️ **[ROADMAP.md](ROADMAP.md)** — what's planned beyond v1.1.
- 🐞 **[Known issues](#known-issues)** — see below.

## Known issues

*v1.1 is stable and fun, but honest about its rough edges. Full list to be tracked in GitHub Issues.*

- **Multiplayer is young.** It has survived its first real group tables, but expect seams: if a screen ever looks out of step, a page reload lands you right back in the story with nothing lost (the save replays — that's the point of the event log). Remote play borrows a free Cloudflare quick tunnel, so the internet address changes each evening — the Invite button always has the current one.

- **Bestiary art is ~20% complete.** Every creature works fully in the Arena — all abilities, actions, spells, and legendary actions — they just show a generic token until art is added. This grows slowly over time. Art added via a pack is unaffected and displays fine in the bestiary.
- **API calls occasionally drop.** A dropped connection mid-call surfaces an error promptly (no effect on gameplay or the DM's memory) — just send your turn again.
- **Racial traits are now wired into the engine.** v1.0 brought Relentless Endurance, the dragonborn breath weapon and ancestry resistance, dwarven poison resistance, and more; the last three holdouts landed after it — Halfling Lucky rerolls natural 1s on attacks, checks, and saves (story and Arena alike), Gnome Cunning grants advantage on INT/WIS/CHA saves against magic, and the tiefling's Infernal Legacy is real: thaumaturgy known from level 1, Hellish Rebuke once per long rest at 3rd, Darkness at 5th — castable in the Arena even by tieflings with no spellcasting class. (One nicety remains: a non-caster's sheet has no spellcasting panel, so thaumaturgy shows only in the DM's narration.)
- **Encounter balance is still being tuned.** v0.9.2 added a party-CR budget — improvised fights are now sized to the party's real levels and size and to your chosen difficulty (Story → Hardcore) — but the CR bands themselves will take several more balancing passes before every fight feels fair at every level.
- **Some bestiary art may sit oddly in its token.** Tokens now crop-to-fill (matching the bestiary card), which fixed most of the old zoomed-out look — and Forge-authored creatures have a token previewer (drag + zoom in the creature editor) for perfect framing. The built-in SRD art gets re-cropped at the source as it grows.

---

## License & attribution

Oubliette Table is a **free and open-source** project. It includes material from the **System Reference Document 5.1** by Wizards of the Coast LLC, used under the Creative Commons Attribution 4.0 International License. Bundled fonts (MedievalSharp, PT Serif) are used under the SIL Open Font License. See [`NOTICE`](NOTICE) for details.
