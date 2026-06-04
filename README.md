# Oubliette Table

A non-commercial, open-source AI-DM text RPG built on the D&D SRD. The thesis:
**code owns state and the rules; the LLM only narrates and proposes; the player
never holds the pen.** See [`oubliette-table-spec-v0.2.md`](oubliette-table-spec-v0.2.md)
for the full design (and [`oubliette-table-design-v0.1.md`](oubliette-table-design-v0.1.md)
for the original rationale).

## Status: Phase 2 — event sourcing + SQLite (on Phase 0/1)

Per spec §14, we build *through the seams* so later phases are substitutions, not
rewrites. Everything runs with a **scripted (offline) DM** — no API key required.

- **Phase 0** (tag `phase-0`): the core non-combat loop end to end.
- **Phase 1** (tag `phase-1`): the combat *boundary* (§8) — declarative
  `EncounterRequest` in, instantiation from live state + templates (ephemeral
  combatants, D5), a `CombatResult` with absolute values (D7) out, applied as one
  recorded result; non-combat exits (parley/flee) first-class. Engine internals
  are a placeholder the real tactical prototype slots in behind later.
- **Phase 2** (tag `phase-2`): the **event log** is now real. Authoritative state
  is rebuilt by `seed(authored baseline) + replay(events)`; every protected
  mutation decomposes into atomic, replayable `StateOp`s applied through one path
  (live + replay); the RNG emits `ROLL` events (recorded, never re-rolled); the
  log persists to **SQLite**. Reload is byte-identical for authoritative state
  (D9). Run with `--db PATH` to persist and reload.
- **Next (Phase 3):** canonization lifecycle (incl. the D5 ephemeral-survivor
  promotion hook), the trade window, then a front-end.

## Quickstart

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate     # POSIX: source .venv/bin/activate
pip install -e ".[dev]"

pytest                                   # acceptance suite (Phase 0 + 1 + 2 replay)
python -m oubliette.app.repl --script --scripted   # the §14.1 non-combat transcript
python -m oubliette.app.repl --combat --scripted   # the Phase 1 combat-boundary demo
python -m oubliette.app.repl --scripted --db save.sqlite   # persist; re-run to reload+replay
python -m oubliette.app.repl             # interactive REPL — uses the REAL model when
                                         # ANTHROPIC_API_KEY is set (in env or a .env file);
                                         # no extra deps, the adapter uses the stdlib
```

## The acceptance transcript (definition of "done" for Phase 0)

1. *"I look around the market."* → narration only; no roll, no state change.
2. *"…these worn boots are priceless dwarven heirlooms."* → a real `skill_check.deception`
   d20 roll is logged; the DM sets the DC, code supplies the sheet bonus.
3. *"Sold."* → a `transact` fires; gold and the boots move on **both** sides.
4. *"I now have 10,000 gold."* → routed `denied`; no tool fires; gold unchanged.

## Layout (mirrors spec §2)

| Package | Job |
|---|---|
| `state/` | authoritative state; the only writer of protected fields (the firewall) |
| `rules/` | pure SRD functions (ability mods, checks); no I/O |
| `record/` | the event log (`events.py` ops/replay, `store.py` SQLite/in-memory), the seeded RNG (emits ROLL events), + a non-replayed debug log |
| `runtime/session.py` | session lifecycle: durable store + materialized state, kept in sync via seed-then-replay |
| `llm/` | the `LLMClient` seam; `scripted` (offline double) + `anthropic` (real) adapters |
| `schemas.py` | typed structured-output contracts (Intent, assessment, resolution, tool calls) |
| `tools/` | the tool surface — the only doors into protected state |
| `combat/` | the combat boundary: `EncounterRequest` → placeholder engine → `CombatResult` |
| `dm/` | the DM brain: assess, then resolve (narrate + emit tools) |
| `runtime/` | the turn loop: assess → (combat \| roll → resolve) → apply → render |
| `app/` | terminal REPL |

## What this does NOT do yet

The *tactical* combat internals (only the boundary + an auto-resolve placeholder
exist), the canonization lifecycle, and the trade window — Phase 3 (spec §14).
Also note: RNG *state* isn't persisted across reload (past rolls are in the log;
post-reload rolls restart from the base seed) — fine for single-player and it
doesn't affect the byte-identical-**state** guarantee, since state comes from
recorded ops, not rolls.
