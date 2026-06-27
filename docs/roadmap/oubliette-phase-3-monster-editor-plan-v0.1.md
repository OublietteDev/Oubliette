# Forge Phase 3 — the Monster Editor (richer creature authoring)

*Plan v0.1 — 2026-06-27. Follows Forge Phase 2 (AI personality editor, COMPLETE).
See `PROJECT_NOTES.md` "Post-Phase-D: AI + Forge arc" and the `oubliette-ai-forge-arc`
memory for context.*

## Goal

Let a non-coder author a creature in the Forge that **actually fights well** in the
Arena — including real attacks, multiattack, and signature special abilities — not
just a single generic swing. This is the open-source payoff: anyone who plays 5e
should be able to homebrew a monster and have it behave correctly in a fight.

## The problem this solves

The 354 SRD monsters each ship a full-fidelity Arena combat file
(`arena/data/monsters/srd/<id>.json`) — so a goblin or dragon dropped into the
Arena already multiattacks, breathes, and uses its kit. But a **brand-new
authored creature has no such file**, so the bridge falls back to the *flat*
mapping (`statblock_to_monster`) and the creature gets exactly **one generic
attack per turn**. Its ability scores, AC/HP, CR, and damage
resistances/immunities/vulnerabilities/condition-immunities *do* carry (those are
real, already-honored combat depth that the form simply doesn't expose yet) — but
its actual *moves* do not. "Competence is free" silently breaks for new creatures.

## Locked decisions (with OublietteDev, 2026-06-27)

1. **Open-source bar.** This ships on GitHub for anyone authoring 5e worlds.
   Expose the engine's *real* combat primitives, not a dumbed-down subset.
2. **Escape hatch = data + safe expressions, never executable code.** A downloaded
   pack must never be able to run arbitrary code (supply-chain / RCE risk). The
   power-user release valve is (a) a raw **structured-data** editor over the full
   engine primitives (inert, validated) and (b) tiny whitelisted expressions in
   the existing `ai_use_condition` style (`"self.hp_percent < 50"`). "Run authored
   code" is a hard no for shareable packs.
3. **Architecture: Option A — packs carry the engine's real combat file.** A
   creature may optionally ship a full Arena `Monster` JSON (the exact shape the
   SRD files already use). The bridge already prefers a rich file when present
   (`arena_monster_file`) — we teach it to look in the pack too. Consequences:
   - **"Clone an existing creature" = copy + rename a combat file** (the keystone
     on-ramp). All primitives work for free, forever, with no mapping layer.
   - The slim `StatBlock` stays the bestiary / identity / knowledge-gate record and
     the thing NPCs reference. The rich combat file is *optional* and layered on top.
   - The pack format leans on the engine's `Monster` shape — already the de-facto
     interchange format (SRD files + cross-process handoff), so the coupling is real
     but pre-existing.

## Storage shape

Mirror the SRD layout inside the pack:

```
oubliette/content/packs/<pack_id>/
  statblocks.json        # identity/bestiary records (unchanged; gains richer fields in 3a)
  monsters/<sb_id>.json  # OPTIONAL full Arena Monster JSON (combat truth) — NEW
```

- A creature with no `monsters/<id>.json` behaves exactly as today (flat mapping).
- When the file exists it is the combat truth; the `StatBlock` remains the
  bestiary card. Identity fields the player sees (name, CR, size/type, portrait)
  live on the `StatBlock`; the combat file owns attacks/abilities/multiattack.
- Validation: the bridge already does `Monster.model_validate(...)` with a
  try/except → None fallback. Keep that as the load-time guard so a malformed
  authored file degrades to the flat mapping rather than crashing a fight. The
  Forge validates on save too (reject before write).

## Work breakdown (sequenced safest-first)

### Phase 3a — Richer identity & defense fields (mostly frontend, low risk)
Expose the `StatBlock` fields the engine already honors or the bestiary already
shows but the creature form omits:
- size, type, alignment, challenge rating (CR)
- speed (walk/fly/swim/burrow/climb)
- saving-throw proficiencies, skill bonuses
- **damage resistances / immunities / vulnerabilities, condition immunities**
  (real combat depth, already honored by the flat mapping — pure UI win)
- senses (darkvision, etc.), languages, hit dice, AC description
- portrait selection

Plain-language labels throughout (biologist-friendly; see `comms-plain-language`).
No engine change. Tests: schema round-trip already covered; add a creator-server
test only if the save shape changes.

### Phase 3b-1 — Bridge: prefer a pack combat file (the Option-A keystone)
- Teach `arena_monster_file` / `enemy_from_statblock` to look in the pack's
  `monsters/` dir before the SRD dir (pack dir already threaded via `PortraitDirs`;
  add a parallel monster-dir or generalize to a search list).
- Forge server: register the `monsters/` subdir in the pack read/save/scaffold/
  backup flow (it's a directory of per-creature files, not the single-file pattern
  — the one genuinely new storage shape this phase).
- Tests: `test_arena_bridge.py` (pack file preferred over flat mapping; missing
  file still falls back) + `test_creator_server.py` (monsters/ round-trips, backs up).

### Phase 3b-2 — "Start from an existing creature" (clone)
- Forge UI: a picker over all SRD + this-pack creatures; on choose, copy the
  source combat file into the pack's `monsters/` under the new id and prefill the
  `StatBlock` identity from it. Instantly gives a fully-competent starting point to
  rename/tweak. This is the highest-value single feature for open-source authors.

### Phase 3b-3 — The ability builder (compose from primitives)
A friendly editor that writes Actions into the combat file. Curated palette over
the real `arena/models/actions.py` primitives:
- **Multiattack count** ("attacks twice/three times").
- **Attack** action: name, melee/ranged, reach/range, to-hit, damage rolls
  (dice + type), on-hit rider (extra damage, condition + save).
- **Save-for-effect** action: area shape (sphere/cone/line/cube), save ability +
  DC, damage (dice + type) + half-on-save, conditions on fail — i.e. breath
  weapons, frightful presence, poison clouds.
- **Heal / temp-HP / buff** action.
- **Limits**: at-will / N per day / recharge X–6. **Economy**: action / bonus /
  reaction / legendary.

### Phase 3b-4 — The advanced (data) escape hatch
- A raw structured-data editor over the Action/Monster JSON for anything the
  builder doesn't cover, validated on save (decision #2). Plus surface the existing
  `ai_use_condition` constrained-expression field for conditional use. **No code
  execution.**

## Open sub-questions (resolve as we build, not now)
- Keeping `StatBlock` HP/AC/abilities in sync with the combat file when both exist
  (single source of truth vs. derive-on-clone). Lean: combat file owns combat
  numbers when present; `StatBlock` mirrors for the bestiary card.
- Whether the ability builder edits the combat file in place or regenerates it.
- How `bestiary_gate` (CR redaction) reads CR for a clone (from `StatBlock`).

## Out of scope (this phase)
- Authored lair actions (no SRD data precedent; engine scaffolding exists).
- A visual token/portrait *painter* (portrait *selection* only).
- Any executable-code pathway.
