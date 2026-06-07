# Oubliette Creator — World-Authoring Tool (design v0.1)

*Status: design doc, to be reviewed before building. A companion tool that lets a
person build a **content pack** (a world the game can play) by filling in forms in
their browser, instead of hand-typing data files. Companion to
`oubliette-content-pipeline-v0.1.md` (which defines what a pack IS) and
`oubliette-table-spec-v0.2.md` (the game engine).*

*Scope decided with the user: build editors for **all five world pieces** (items,
creatures, characters/NPCs, places, the opening setup); support **opening and
editing existing packs** as well as creating new ones; and design for **non-coders**
— gentle, plainly labelled, hard to break.*

> Tags (as in the other docs): **[LOCKED]** decided with the user · **[PROPOSED —
> confirm]** a default this doc suggests · **[OPEN]** still to decide.

---

## 0. Plain-language overview (read this first)

A **pack** is the *recipe* for a world: its items, people, creatures, places, and
where a new game starts. Today a pack is a folder of text files that have to be
typed by hand. That's fine for me, but no fun for a person who just wants to make
a world.

The **Creator** is a small, friendly app — it opens in your web browser, looks and
feels like the game, and you launch it by double-clicking, no typing of commands.
You build a world by filling in forms ("New item: name, what it's worth, what it
does…") and clicking to connect things ("this merchant sells: [pick from your
items]"). When you're done, it saves the recipe in exactly the format the game
reads.

Two ideas make this safe and pleasant, and everything below serves them:

1. **One source of truth for "is this world OK?"** The Creator checks your pack
   with the *exact same rulebook the game uses to load it.* So if the Creator says
   "this world is good to play," the game is guaranteed to accept it. We never write
   a second, separate definition of "valid" that could drift apart.

2. **Pick, don't type.** The places where hand-authoring goes wrong are the
   *connections* — "this merchant sells item `travel_boots`" and you mistype the id.
   The Creator removes that whole class of mistakes by letting you **pick from lists
   of things you've already made** instead of typing names of things. The rulebook
   check becomes a safety net under an authoring experience that mostly can't fail.

---

## 1. What it is, and what it is NOT

| | |
|---|---|
| **It IS** | A local browser app that reads, edits, validates, and writes **pack files** (the world recipe). |
| **It is NOT** | The game. It never runs a play session and never touches **save files** (those are the *database* the game builds from a pack when someone plays). |

Keeping the Creator and the game separate but living in the same project means the
Creator can borrow the game's rulebook (its schemas + loader) while staying a
distinct, simple tool with one job: produce good packs.

**[LOCKED]** Separate companion app, same project, browser-based, double-click launch.

---

## 2. Shape & where it lives [PROPOSED — confirm]

The game is a FastAPI app serving one self-contained page (`oubliette/app/server.py`
+ `static/index.html`), launched by `play.bat` / the `oubliette-play` command. The
Creator mirrors that, one folder over:

```
oubliette/creator/
  server.py            # FastAPI app: list/read/validate/write packs
  static/index.html    # the authoring UI (reuses the game's dark theme)
forge.bat              # double-click launcher (mirrors play.bat)
# new console script: oubliette-forge
```

It lives **inside** the `oubliette` package so it can import the rulebook directly
(`oubliette.content.schemas`, `oubliette.content.loader`). Same look, same launch
habit, zero new things to learn.

*(Working name "Creator"/"Forge" is cosmetic — see Open Questions.)*

---

## 3. The core principle: borrow the game's rulebook [LOCKED]

The pipeline already defines every world piece as a strict, typed schema in
`oubliette/content/schemas.py`, and `oubliette/content/loader.py` validates a whole
pack (each piece is well-formed **and** all the connections between pieces resolve).

The Creator **imports and reuses both**:

- **Per-field rules** come from the schemas (what fields exist, which are required,
  what type each is). The forms are built to match — so a form can never ask for a
  field the game doesn't understand, or miss a required one.
- **Whole-world check** runs the loader's cross-reference linter, which already
  collects *every* problem at once into one plain list (e.g. *"merchant Thom sells
  'belt' but doesn't carry it"*). The Creator shows that list in friendly language.

> The payoff, restated: **the tool's definition of "valid" and the game's are the
> same code.** No drift, ever. A pack the Creator blesses will load.

**[PROPOSED]** Build the forms automatically from the schema shape where practical
(Pydantic can describe its own fields), so the forms stay in lock-step with the data
model with no hand-maintenance. Friendly labels + help text are added to the schema
fields as author-facing notes. *(If auto-forms get fiddly, hand-built forms over the
same schemas are an acceptable fallback — the validation reuse is the non-negotiable
part.)*

---

## 4. The authoring experience (the five pieces)

One screen per world piece, plus an opening-setup screen. Each is a list of things
you've made, with an editor form. Friendly names everywhere; the technical id is
generated for you and kept out of sight (§5).

- **Items** — name, what it's worth, a short description, a category (weapon / armor
  / gear / consumable / treasure / trinket). If it's armor, a small "armor" sub-form
  (how much it protects); if a weapon, a "weapon" sub-form (its damage). These extra
  blocks are optional — the world plays without them; they're captured for later.
- **Creatures** — the stat lines for monsters and for townsfolk: health, defense, how
  hard they hit, the experience they're worth, and (later) loot they drop (**picked**
  from your items).
- **Characters / NPCs** — the people: name, temperament ("cautious and shrewd…",
  which is what the game's DM uses to judge how hard they are to persuade), where they
  live (**pick a place**), their combat stats (**pick a creature stat line**), their
  coin, and — for merchants — what they stock and the price of each (**pick items**,
  set a number).
- **Places** — name, the scene description players read on arrival, and the ways out
  ("north toward the gate" → **pick the destination place**). These connections are
  also the skeleton of a future map.
- **Opening setup (scenario)** — which place a new game begins in (**pick a place**)
  and, for now, a starter party. *(Proper character creation is its own future arc;
  until then the party is a simple character form, exactly the "stopgap" the pipeline
  already describes.)*

---

## 5. Guard-rails for non-coders [LOCKED — the audience choice]

Everything here exists so a biologist friend can make a world without fear.

- **Pick, don't type (the big one).** Every connection between pieces is a dropdown
  of things you've already made — merchant stock, prices, a creature's loot, an NPC's
  home and stat line, a place's exits, the starting location, party gear. You can't
  reference something that doesn't exist, because you choose from a list. This
  prevents most errors *before* they happen.
- **Ids stay hidden.** The game needs a short code name (an "id", like
  `merchant_thom`) for each thing. The Creator makes that for you from the name and
  keeps it backstage; you only ever see "Thom". *(Design note: once a thing is made,
  its hidden id stays fixed even if you rename it, so existing connections never
  break — renaming changes only what you see.)*
- **Plain-language problem list.** A "Check this world" button runs the game's
  rulebook and lists anything wrong in friendly terms, grouped by piece, each saying
  *what* and *where*. Technical phrasings get translated (e.g. *"references unknown
  item 'belt'"* → *"Thom's shop lists 'belt' for sale, but there's no such item — did
  you mean 'sturdy belt'?"*).
- **Save anytime; know when it's playable.** You can save unfinished work without
  passing every check (so you never lose progress) — this matches the pipeline's
  "relaxed while authoring." A clear status badge tells you which state you're in:
  **✓ Ready to play** or **⚠ 3 things to fix before this world will load.**
- **Helpful empty states & examples.** Open the Brightvale starter to see a complete,
  working world and learn by poking at it (that's why open-and-edit matters).

---

## 6. Opening, editing, saving (the round-trip) [LOCKED — open+edit+create]

- **Open** a pack → read its files → fill the forms. The Brightvale starter is
  directly openable, so it doubles as a tutorial world.
- **Edit** freely; connections update through the pickers.
- **Save** → write the files back in a **clean, stable format** (pretty-printed,
  consistent ordering) so a saved pack is tidy and changes are easy to track. The
  Creator writes the same per-type files the game reads — nothing bespoke.
- **New** → start from a blank world (or a tiny template) and build up.

The Creator only ever touches the **pack folder** (the recipe). It never reads or
writes a save/database. That clean separation is what keeps it safe to use.

---

## 7. Seams for later (designed for, not built now)

- **A map view.** Places already record their exits (and have a spot reserved for
  map coordinates). A future "arrange your world" screen can draw places as a map you
  drag around; the data is ready.
- **Building on a base set.** The pipeline plans for *layered* packs — a shared
  "basics" pack (standard items/monsters) that world packs build on top of, so you
  don't recreate the basics. A future Creator can let you pick from the base set when
  stocking a shop. v1 makes one self-contained pack.
- **Character creation.** When the real "make your hero" flow exists, the Creator's
  starter-party form is replaced by it; the seam is the same character shape.
- **"Test play this world" button.** A future convenience: hand the current pack to
  the game and open a play session, to try a world without leaving the Creator.

---

## 8. Build order [PROPOSED — confirm]

Each step is something you can see working in the browser before the next begins.

1. **C1 — open & check.** Launch the app; list the packs in `content/packs`; open one
   and show its contents (read-only); run the rulebook and show ✓/⚠ with the plain
   problem list. *Proves the round-trip read + the shared-validation payoff.*
2. **C2 — edit the simple pieces.** Forms + save-back for **items** and **places**,
   with the stable file writer and the first **pickers** (a place's exits). *Proves
   editing and clean saves.*
3. **C3 — the connected pieces.** **Creatures**, then **NPCs** (stock, prices,
   home, stat line — all via pickers), then the **opening setup** (start location +
   starter party). *Now a whole world is authorable.*
4. **C4 — non-coder polish.** Hidden-id handling on rename, friendly error
   translations, the ✓/⚠ status badge, the new-world flow, help text, and opening
   Brightvale as the worked example.

Later arcs: map view · layered base set · chargen integration · test-play button.

---

## 9. Open questions — RESOLVED (2026-06-07)

1. **Name → "The Forge"** **[LOCKED]**. (The tool is *Oubliette: The Forge*; module
   `oubliette/creator/`, launcher `forge.bat`, command `oubliette-forge`.)
2. **Backups → YES** **[LOCKED]**. Saving over an existing pack first writes a
   timestamped copy of the previous version, so a mistake is never permanent.
3. **Forms → hand-built, validated by the shared rulebook** **[LOCKED]**. The five
   nouns rarely change and friendliness (plain labels, help text, and the "pick from a
   list" connection dropdowns) has to be hand-crafted per field regardless — an
   auto-generator would still need all that hand-written and would fight the friendly
   parts. So: hand-build the forms for the best experience; keep the schema as the one
   source of truth for *validity* (every save runs through it); add a tiny dev-time
   check that warns if the rulebook gains a field a form forgot (drift caught cheaply).
4. **Test-play button → later nicety** **[LOCKED]**. For now the flow is: save the
   pack, then run `play.bat` to try it with the DM. Fine as-is; a button can come later.
```
