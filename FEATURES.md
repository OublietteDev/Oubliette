# Oubliette — Feature Guide

*A complete, code-verified inventory of everything the project does, grouped by its three apps.*

Oubliette is a non-commercial, open-source **AI Dungeon Master text RPG** built on the D&D 5e SRD (5.1). It is three programs that share one engine and one house style:

| App | What it is | How you launch it |
|---|---|---|
| **Oubliette** | The main game — an AI Dungeon Master you play in your browser. | `play.bat` |
| **The Forge** | The world-authoring studio — build the worlds the game plays. | `forge.bat` |
| **The Arena** | A standalone D&D 5e tactical combat engine — where fights are fought. | `arena.bat` (also launched automatically by the game) |

The project's defining principle is a **firewall between rules and narration**: the *code* owns every piece of game state and every rule, and the AI only narrates and proposes. The model can never directly write your HP, gold, XP, inventory, or conditions — it can only *request* a change through a validated tool call, which the code checks before applying. Every change and every die roll is written to an append-only log before it takes effect, so a saved game reloads by *replaying that log* — the dice are never re-rolled and the model is never re-asked.

---

## Lines of code

Hand-written code only — excludes JSON data/content, art, audio, `.venv`, and generated files.

| App | Source | Tests |
|---|--:|--:|
| **The Arena** (standalone) | 40,949 | 44,678 |
| **Oubliette** (main app + shared engine) | 17,396 | 11,664¹ |
| **The Forge** (own code only²) | 4,988 | — |
| Build & content tooling | 2,462 | — |

¹ The engine test-suite backs both the main app and the Forge (they share the engine).
² The Forge rides on the main app's engine; this counts only the creator server + its authoring frontend.

**Totals:** ~65,800 lines of source, ~56,300 lines of tests — **~122,000 lines** of hand-written code.

---
---

# Oubliette — the main game

**Oubliette Table** is an AI Dungeon Master you play entirely in a web browser. You type what your character does in the first person, and an AI narrates the world's reply. It's a single local process serving one self-contained page (no build step, no account, single continuous save), and it plays worlds authored in the Forge, handing tactical fights off to the Arena.

### The AI Dungeon Master
- **A structured turn loop every message:** *assess* (classify intent, decide if a roll/fight/trade is needed, set the DC) → *roll* (code supplies the character's bonus and rolls seeded dice) → *resolve* (narrate + propose tool calls) → *apply* (validate and commit as events).
- **The DM sets difficulty, never outcomes.** The model chooses which check or saving throw applies and the DC (informed by the character sheet and an NPC's disposition); code adds the modifier, rolls, and owns the result. It can waive rolls a character would trivially pass.
- **Streaming narration** delivered token-by-token with a live cursor, markdown, and fade-ins.
- **Adaptive reasoning:** the DM spends hidden "thinking" effort only on genuinely contested turns and skips it on routine narration — no latency tax where it wouldn't change the ruling. The scratchpad is never shown to the player.
- **The firewall in play:** a bare player claim to protected state ("I now have 10,000 gold") gets a diegetic "no" and fires no tool.
- **Out-of-character mode:** an explicit OOC toggle is the *only* signal for meta questions (rules, "what's in my pack?"); those turns are answered without advancing the fiction.
- **Model-welfare exits:** the DM can propose wrapping a session at a natural lull (you confirm), and can cleanly, terminally close a hostile or bad-faith table.

### Character creation & sheets
- **Full SRD character creation:** all ability-score methods, races/subraces, all 12 classes (+ subclasses), background, and feat-or-ASI — validated live by the same firewall (the wizard never mutates state, it returns a fully-derived preview).
- **Multi-character party** of up to 6 heroes via a tabbed builder, plus a one-click **quick-start** pre-made hero.
- **Read-only derived character sheet** where every number is code-derived: abilities/mods, saving throws, skills (with expertise), AC, spellcasting (save DC, attack bonus, slots, prepared/known spells), hit dice, class resources, features grouped by source, proficiencies/languages, and flavor.
- **Player-uploaded portraits** (PNG/JPG/WEBP/GIF ≤ 8 MB) stored beside the save, event-recorded so they survive replay, and reused as the Arena board token.

### Leveling, rests & resources
- **XP-gated leveling** with a Level-Up button that lights up when eligible; HP rolled (seeded) or taken as average.
- **Combat XP sharing** split across the party per RAW (no XP lost to rounding).
- **Short & long rests, party-wide:** per-member hit-die spend on a short rest, full HP/slot/resource restore on a long rest — all seeded and event-sourced.
- **Re-prepare spells on a long rest**, validated (exact count, drawn from the class list), only in the window before the party acts.
- **Recovery firewall:** HP/slots/hit dice come back only through code (a rest, or a consumable via `use_item`) — never through narration.

### Combat (story ↔ Arena handoff)
- Combat is a **separate tactical app, not prose.** When violence starts, the DM fills an encounter request naming enemies (by template, by existing entity, or *any SRD creature by plain name* — "dire wolf", "bandit captain"), counts, and terrain.
- The turn **locks input** and shows an **⚔ Enter the Arena** button; the fight's outcome folds back as a single recorded event (replay never re-runs the fight).
- **De-escalation is first-class:** talking down, fleeing, surrendering, or bribing resolves instantly with no Arena.
- **Player-controlled allies:** a friendly NPC who would plainly fight alongside you joins the battle under your control.
- **Robustness:** if the Arena crashes or writes no result, the fight resolves as a harmless break-off so play always continues.

### Economy & trade
- **Party purse in real coins** (cp/sp/gp, with platinum promotion for hoards); any hero spends from it and any hero's earnings land in it.
- **Soft, DM-set economy:** item values are advisory anchors; prices shift with NPC disposition and haggling.
- **Trade window:** browse a merchant's priced stock and their carried coin (which caps what they'll pay), build a basket with quantity steppers and a running net total, then **Settle** (one validated transaction) or **Haggle** (the DM rolls persuasion/deception and adjusts).
- **Hand-over between heroes:** pass an item (including exact scroll stacks) from one party member to another.
- **World rewards:** the DM can grant a quest payout or found cache straight to the party, or levy tolls/fines/thefts.

### Inventory & equipment
- **Per-member inventory** grouped into Weapons / Armor / Gear / Consumables / Other, with an **Equipped** section and equip/unequip toggles (event-sourced).
- **Item hover-cards:** description, value, weapon damage/properties, armor AC, magic-item family/rarity/attunement, consumable effects, poison stats, worn resistances.
- **Spell scrolls** carry their inscribed spell and cast level in the label.

### Quests
- **Emergent quests** the DM starts and advances as the story develops, with an Active Quest panel and illustrated quest cards in the chat stream.
- **Authored quests** tied to one source (a giver NPC or a discoverable place), each with a **player-facing hook** and a separate **DM-only briefing**; rewards are advisory; chains **branch on outcome** ("spared" → quest B, "killed" → quest C).
- **Two-tier discoverability:** sparse regional signposts nudge you toward work; full details appear only on arrival at the source, where a quest can be accepted.
- **Rewards-pending tracking** so the DM never forgets what it owes.

### Travel, world map & environment
- **DM-driven travel** between authored, nesting places (a town holds districts; a dungeon holds rooms).
- **World map** with pins on assignable art, two levels deep, hover tooltips, and drill-in sub-maps. **Identities are earned by visiting** — unvisited areas are redacted to "Unknown," and redaction is **server-side** so their names never reach the browser.
- **Time-of-day & weather** the DM reports, shown live in the Scene card and carried forward until the fiction changes it.

### Audio soundscape
- **Location-driven ambient mixer** (Web Audio): looping beds + sparse one-shots, derived from state — *the AI never plays a sound.*
- **Theme inheritance** (a city's theme plays in every shop inside it) and cues filtered by time-of-day/weather.
- Player controls: enable-sound gate, separate Music/SFX volume, mute-all, and a crossfade on travel.

### Bestiary & content
- **Searchable bestiary** merging the loaded world's creatures with the full **334-monster SRD library**, ordered by CR, source-badged, with portraits and full stat blocks.
- **Optional per-world knowledge gate:** creatures above a CR threshold stay hidden (even their portrait is silhouetted) until the party fights them.
- **SRD ruleset layer** shared by every world: 12 classes (+ subclasses), 9 races (+ subraces), 319 spells, ~590 items, 334 monsters, 15 conditions, background and feat — content-complete, with world packs merging their own content on top.

### Memory & continuity
- **Short-term beats:** a compact recap of recent turns keeps the DM honoring established fiction.
- **Canon lifecycle:** the DM creates world content (born *provisional*), promotes it to canon when it matters, and keyword-retrieves relevant canon back into context — its long-term memory, event-sourced so it rebuilds identically on replay.
- **DM private notebook:** per-session working memory (plans, an NPC's true intent, a lie left standing) — invisible to the player.
- **Session wrap with two-faced notes:** at a wrap the DM writes a spoiler-free **player chronicle** ("Previously…") *and* private **continuity notes** (unresolved threads, secret motives) that thread into future sessions.
- **Reload replays the chat**, restoring the in-progress transcript plus past-session chronicles so you resume mid-story.

### Save & session management
- **One continuous save** (append-only SQLite event log) — no slots; **byte-identical reload** via *seed + replay*.
- **Reload world** mid-session to pick up Forge edits without starting over.
- **World import/export** as shareable zips (validated whole, old copy shelved to backups, never lost).
- **Character portability:** export any hero as a self-contained bundle (snapshot + item defs + portrait) and import into a new game, pre-flight-checked for both the game and the Arena.

### Table contract (session-zero safety)
- On New Game you **set the table:** a tone dial (whimsical → grim) and **Lines & Veils** (content never depicted, or faded tactfully past). Injected into every resolve prompt — the DM honors it and can never set it.

### Provider / model configuration
- **"Connect your AI" front door:** pick **Anthropic**, **OpenAI**, **Google Gemini**, or **local models** (any OpenAI-compatible server — Ollama, LM Studio, llama.cpp — no key needed), paste a key, and type the model's **exact API id as free text** (new models work the day they ship).
- **Ping-gated save:** a Test button makes one real tiny call so a typo shows up as a sentence, not mid-game; settings save only after it passes, and the live DM re-picks with no restart.
- **Local, private storage** (gitignored config), explicit **Disconnect & go offline**, and an **Offline Mode** scripted demo DM when no key is set.

### UI/UX
- **Two-column layout:** chat with roll/effect/combat/quest chips on the left; a live HUD (Scene, character card, Present NPCs, Active Quest) on the right.
- **☰ Menu:** Journal, Inventory, Party Sheets, Bestiary, Map, Help, Settings, Wrap-up.
- **Player journal** — markdown notes and status-grouped entries, **deliberately invisible to the DM** so a player can't induce a hallucination.
- **In-chat confirmations** for entering the Arena, wrapping a session, and taking a proposed rest; a general-audience How-to-Play help panel; auto-opens the browser on launch.

---
---

# The Forge — the world-authoring studio

**The Forge** is Oubliette's world-building tool: a standalone single-page web app where you create and edit the "worlds" (content packs) the game and the Arena play. It requires no coding — everything is authored through visual forms, drawers, checklists, live previews, drag-and-drop maps, and a hex-grid battlefield painter. Its defining promise is **truthful validation**: the Forge runs *the game's own loader* to check a world, so a green "✓ Ready to play" badge guarantees the game will accept it.

### World management & shell
- **Worlds sidebar** listing every world with a live status pill (`✓ ready`, `⚠ N to fix`, `♪ N` sound warnings).
- **Create a new world** that already loads green (a manifest, a starting place, a starter hero).
- **Save** writes all files back to disk, always making a **timestamped backup** first — saving is never destructive, and you can save work-in-progress even with outstanding issues.
- **Live validity report:** a plain-language, per-section list of what to fix (dangling exits, unknown references, unreachable quests, missing quest sources), with "did you mean?" suggestions and non-blocking sound warnings.
- **Unsaved-changes guard** and collapsible, foldable content sections.
- **Export / import** whole worlds as `.oubliette-world.zip` (JSON + images + audio + combat files + character snapshots); imports install even with issues (the Forge is where you fix them).

### World settings & toggles
- **Bestiary knowledge gate** — per-world toggle + CR threshold controlling what stays redacted in the player's bestiary until fought.
- Manifest fields (name, semver, author, description, entry scenario) and the world map image.

### World & place editing
Each **Place** authors: name, a **scene description** (the text players read on arrival), an optional **parent area** (rendering an indented, collapsible place tree), tags, **ways out** (exits picked from your places by friendly name, with prose labels), an **illustration** (auto-resized, previewed as it'll appear on a quest card), a **soundscape** drawer, and a **battlefield** drawer.

### Maps (drag-arrange, drill-in, redaction)
- Assign a **world map** and a distinct **sub-map per top-level area.**
- **Pins** for each place, positioned as a **percentage** of the map image so they stay aligned across screen sizes (the game reuses the same coordinates).
- **Drill-in** to an area's own sub-map (two levels), **breadcrumb** navigation, **drawn exits** as dashed edges between pins, and hover tooltips.
- The **player-facing map redacts unvisited places** as "Unknown" (server-side visit-gating).

### Quests & NPCs
- **Characters / NPCs:** name, role, **coin** (caps what they pay), temperament/disposition (feeds the DM's difficulty), description, home place, a **shop & belongings** list (price an item to sell it, leave blank to merely carry it), and a **"how they fight"** combat fork.
- **Quests:** title, player-facing **hook**, DM-only **briefing**, an optional region-wide **rumor**, exactly one **source** (giver NPC or discoverable place + a "how it's found" note), an **advisory reward** (gold or item, plus a note), and a **chain** editor (a "starting quest" toggle + outcome → next-quest branches with an arc label).

### Bestiary / creatures
- **Tabbed stat-block editor** (Core / Abilities / Combat / Defenses / Loot): identity (name, kind, size, **Challenge Rating**, type, alignment, XP, HP, AC), a **portrait** into the pack, the six abilities + saves, **skill proficiencies** (checklist — a typo would crash the load, so it's guarded), languages, senses, attack/damage, speeds, special traits, an AI **personality** picker, resistance/immunity/vulnerability checklists, and a loot table.
- **"Start from an existing creature":** a searchable clone picker across the **full ~334-creature SRD bestiary** *and* the world's own creatures, copying the full combat kit under a new id.
- **⚔ Combat editor** (the full Arena statblock): repeatable **attacks** with a live 5e to-hit preview, **multiattack** (1–6 swings), **special moves** (save-for-effect area abilities — shape, size, save & DC, damage, imposed conditions, recharge/frequency, and an "AI uses it when…" gate), and a **⚙ raw combat-data editor** validated against the engine model for exotic content.

### AI personalities
A reusable **personality** editor with **Easy mode** (plain questions + one-click presets: Berserker, Archer, Battle-mage, Coward, Bodyguard) and **Pro mode** (the underlying dials: aggression, self-preservation, target priority, flanking, opportunity-attack avoidance, ability conservation, flee threshold, and more). Personality shapes *how* a creature fights; its competence is always automatic from the stat block.

### NPC combat: the person/creature fork
An NPC's **"how they fight"** routes to three outcomes:
- **None / generic** — no combat, or an optional generic SRD stat line so a townsfolk can be dragged into a fight.
- **A creature** — the NPC *is* a fully-authored monster (a boss fights as the dragon she is), with a cancel-safe hop into the creature editor that links the minted creature back to the NPC.
- **A person** — the NPC is built with the **same chargen + level-up engine the players use**, snapshotted at authoring time.

### Character builder (person-NPCs)
An embedded two-pane build-a-character overlay (the play app's wizard), driven by the SRD ruleset **merged with this world's own backgrounds, items, and spells:** race/class/background, ability scores, skills/spells/equipment, a **target level** that auto-walks the level-up engine (surfacing each level's choices), a **live derived sheet preview**, and a read-only "View sheet."

### Magic items & equipment
An **item editor** for ordinary gear and full magic items to the same contract the game and Arena consume: name, kind, worth, description, slot, tags; weapon and armor sub-forms; **magic & mechanics** (item family, rarity, **+N magic bonus** enforced to worn/wielded families, attunement, **worn wards** granting resistance/immunity); **consumable mechanics** (healing dice, set-ability-score, grants-resistance, casts-a-spell-of-level for scrolls, duration, action cost); and **poison mechanics** (delivery, save, damage, conditions, duration).

### Custom backgrounds
A **backgrounds editor** for chargen origins beyond the SRD's single one: skill/tool proficiencies, free language picks, a **starting kit** (pointing at this world's items or SRD gear + gold), a narrated **feature**, and **flavor tables** (traits/ideals/bonds/flaws). These merge into the character builder wherever chargen runs against the pack.

### Spell builder (chassis spells)
A **spells editor** where you pick one of four proven **chassis** the Arena executes natively and fill in numbers — **Bolt** (spell-attack damage), **Blast** (area burst, save for half), **Heal** (dice + modifier), **Hex** (save-or-suffer-condition, concentration) — plus level, school, who-can-learn checklist, range, cast time, and upcasting, with a **live stat-block preview** worded to match the Arena's projected action. One saved entry is *both halves*: chargen learns it and the Arena bridge projects it into a castable action at fight time — no sidecar files.

### Battle scenes for the Arena
A per-place **Battlefield** drawer authoring what a fight staged here looks and sounds like: a **background image** under the hex grid, a **battle music** track (with preview), a **grid size**, and terrain. **"Open in Arena"** launches the actual Arena battlefield editor over the real image, where you **paint terrain** (normal, difficult, hazard *with per-hex damage like "1d6 fire"*, water, pit, wall, and half/three-quarter/full cover), size the grid, and fit/pan/scale the background — then Save folds the result back into the place.

### Audio, art & portability
- **Soundscape** drawer: repeatable cues (looping bed vs one-shot, music vs SFX, "only here" vs "plays in sub-locations"), per-cue volume, one-shot intervals, and **when** conditions (time of day, weather), with inherited parent cues shown read-only and ▶ preview.
- **Art:** creature portraits (transparency preserved), place illustrations, map images, and battle backgrounds — all copied into the pack so worlds stay self-contained and portable.

---
---

# The Arena — the tactical combat engine

**The Arena** is a standalone, hex-grid **D&D 5e tactical combat simulator** (Pygame). It fields any SRD creature or player character on a painted battlefield, resolves a faithful implementation of 5e's combat rules turn by turn, drives enemies with a genuine tactical AI, and presents the whole thing with sequenced animation, telegraphed danger, floating numbers, and sound. It runs on its own or is launched by the story game to resolve a fight and hand the results back.

### Turn structure & the action economy
- **Initiative** by d20 + Dex with full 5e tie-breaking (roll → Dex → player-over-AI → random); round tracking; a lair pseudo-turn at initiative 20.
- **Full action economy:** one action, one bonus action, one reaction per round, a free object interaction, and movement — each tracked separately, with the Slow spell's "action XOR bonus" restriction modeled.
- **Standard actions:** Dash, Disengage, Dodge, Help, Hide (Stealth vs passive Perception), and first-aid Stabilize — plus Stand-up-from-prone (half movement) and Fighter Action Surge.
- **Readied actions** with four trigger types (a creature moves / enters range / attacks / casts) plus a custom trigger, expiring at the holder's next turn.

### Movement, positioning & terrain
- **Hex grid** with axial coordinates, A* pathfinding, and Dijkstra reachability that respects a movement budget.
- **Creature footprints** from Tiny through **Gargantuan** (a 19-hex diamond), with footprint-aware distance, range, and adjacency for every calculation.
- **Terrain:** normal, difficult (double cost), water, pit, walls, and three cover grades; dead creatures' spaces are difficult terrain, not walls.
- **Line of sight** through intervening hexes (walls and full cover block; adjacency ignores cover), and **cover** granting +2 / +5 AC.
- **Forced movement** — push / pull / slide — that stops at obstacles, can drop a target into a pit, and can knock prone.

### Attacks & damage
- **To-hit** = ability + proficiency + magic bonus vs AC + cover, with a comprehensive **advantage/disadvantage** model (prone, blinded, restrained, invisible, hidden, dodging, flanking-style Pack Tactics, Reckless Attack, long range, an adjacent foe on ranged attacks, Bless/Bane, and more — with the standard "one of each cancels" rule).
- **Critical hits:** natural 20 (plus expanded crit ranges), doubled dice (not modifiers), and Brutal Critical bonus dice; auto-crits on melee vs paralyzed/stunned/unconscious targets; natural-1 misses.
- **Typed damage packets** resolved per-type through **immunity → resistance → vulnerability**, including conditional defenses ("nonmagical," silvered, adamantine) and **temporary HP** absorption.
- **On-hit riders** (Divine Smite, Sneak Attack, Hunter's Mark, Branding Smite…), **creature-type bonus damage**, **upcast** and **cantrip scaling**, and auto-hit darts (Magic Missile).
- **Multiattack / Extra Attack** looping an attack action, with swings that re-target if the first drops the enemy.
- **Damage-reduction reactions:** Parry, Uncanny Dodge (halve), Deflect Missiles.

### Conditions & status effects
- **All 15 SRD conditions** with full mechanical effects, including level-by-level **Exhaustion** (L1 disadvantage → L5 speed-0 → L6 death).
- **Concentration:** one effect at a time, a CON save (DC = max(10, damage ÷ 2)) on damage, and cleanup of every linked condition/buff when it drops.
- **Death saves & stabilization:** the full 3-success / 3-failure track, nat-20 rebound, nat-1 double-fail, massive-damage instant death, and "damage while dying" failures.
- **Pseudo-conditions** for engine mechanics: Dodging, Hidden, Helped, Reckless, Slowed, Confused (the d10 behavior table), Banished (off-board with position saved), and Dominated (team-switch with re-saves).
- **Immunities** — static, resource-gated (e.g. Mindless Rage), and **aura-based** (Aura of Courage-style).

### Spells & area effects
- **158 SRD spells** with real mechanics, plus **AoE shapes** — sphere, cone, line, cube, cylinder — resolved by one shared geometry resolver (so both the AI's aim and the on-screen preview use the exact hexes the engine will hit).
- **Persistent zones** (Spirit Guardians, Cloudkill, Spike Growth…) with start-of-turn damage, entry damage, per-5-ft movement hazards, imposed conditions, and fog/darkness obscurement.
- **Wall spells** as real barriers with per-panel HP, movement/LOS blocking, and entry damage (Wall of Fire, Wall of Force, Wall of Ice…).
- **Sculpt Spells** (evocation) sparing allies; **Counterspell** and **Dispel Magic** (auto below your level, a check above it); **teleportation**, **chain** effects, **domination/compulsion**, **summoning**, **recurring** spells (Witch Bolt, Spiritual Weapon), and **HP-threshold** effects (Power Word Kill, Sleep, Toll the Dead).

### Monster & legendary mechanics
- **Legendary actions** (point-cost, queued between other turns) and **Legendary Resistance** (turn a failed save into a success).
- **Recharge** abilities (roll a d6 ≥ threshold to reload a breath weapon), **regeneration** with damage-type negation (a troll's acid/fire), and **traits/auras** (Pack Tactics, Reckless/Blood Frenzy, Undead Fortitude, Stench).
- **Lair actions** on the initiative-20 pseudo-turn.

### The AI opponent
A genuine tactical brain, not scripted moves:
- **Target selection** by priority mode (nearest / weakest / strongest / most-threatening / random), with bonuses for finishing low-HP foes, focusing spellcasters, and breaking concentration.
- **Action scoring** over attacks, heals, saves, terrain effects, escapes, and standard actions — weighted by an editable **behavior profile** (aggression, self-preservation, target priority, melee/ranged preference, flanking, opportunity-attack avoidance, ally protection, ability conservation, flee threshold), with six built-in presets and Gaussian noise for variety.
- **Multiattack, spellcasting, and AoE aiming:** it plans all swings and re-targets on kills, conserves limited abilities intelligently, upcasts, centers blasts to maximize enemy hits while avoiding friendly fire (respecting Sculpt Spells), and keeps self-centered auras on itself.
- **Movement & tactics:** footprint-aware pathfinding to the right range, cover- and flank-seeking, **Dash** planned before the walk, charge/pounce hold-lines, **kiting and retreat** (Disengage or Misty Step when hurt or stuck in melee), frightened fleeing, and focus-fire on nearly-dead targets.
- **Reactions & the big turns:** opportunity attacks, on-hit rider choices, damage-reduction reactions, plus scored **legendary** and **lair** action planning.

### Animation & presentation
- **An animation director (beat queue)** so damage numbers, HP-bar drops, knock-downs, and sounds all land at the *moment of impact* — and multiattack swings play visibly one at a time rather than all at once.
- **Danger telegraphs:** incoming AI area attacks pulse the **true blast shape** (color-coded by damage type) before they land; player-aimed spells preview the same exact hexes under the cursor.
- **Charge lunges**, smooth hex-hop movement, direction-rotated projectiles, and a library of code-drawn effects (expanding AoE rings, zone shimmer, teleport vanish/appear, forced-movement slides, spawn glows).
- **Board & tokens:** hex rendering over an optional battlefield background, merged multi-hex token shapes, portrait tokens with fallbacks, animated HP bars (with temp-HP overlay), floating damage/heal numbers, red damage flashes, condition icons, move/attack-range highlights, and a smooth pan/zoom camera that auto-focuses the active creature.
- **UI:** an initiative panel (with legendary-action badges and a lair entry), a full creature info sheet, an action bar, and a filterable, color-coded, actor-tagged combat log — plus custom animated cursors (sword/wand/arrow particle trails) and a cross-fading menu-background slideshow.

### Audio
- **Event-driven combat sound:** attacks route to hit/miss by result; movement, conditions, saves, teleports, and terrain effects each have cues; graceful no-op when a file is missing.
- **Encounter music** with separate master / SFX / music volumes that **live-update** from an in-fight settings slider.

### Battlefield editor
The same tool the Forge launches: **paint terrain** (normal, difficult, hazard with a 9-dice × 12-damage-type brush, water, pit, wall, three cover grades), size the grid (5–40 per side), and **fit/pan/scale a background image** — reading a spec in and writing an updated battle block out.

### Integration with the story game
- Oubliette spawns the Arena as a **subprocess:** an encounter JSON goes in (creatures by id or inline, terrain, grid, music, background, placement), the fight plays out, and a **versioned result** comes back — final HP, conditions, spent **resources** (spell slots, ki, rage), **consumables used**, **death saves**, XP, and the winner.
- **Full PC round-trip:** heroes fight with their real sheets and resources, and what they spend or suffer flows back into the story.
- A per-run **combat log dump** (`last_combat_log.txt`) supports post-game audits.

### Content
- **353 creatures** (334 SRD + 19 custom), **158 SRD spells**, **21 pre-generated characters**, and **53 sample encounters** — including a battery of focused mechanic "labs" (AoE, conditions, control, charge, breath weapons, death triggers, casters, bards…) used as living tests.
