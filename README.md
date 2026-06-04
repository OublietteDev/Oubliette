# Oubliette Table

A non-commercial, open-source AI-DM text RPG built on the D&D SRD. The thesis:
**code owns state and the rules; the LLM only narrates and proposes; the player
never holds the pen.** See [`oubliette-table-spec-v0.2.md`](oubliette-table-spec-v0.2.md)
for the full design (and [`oubliette-table-design-v0.1.md`](oubliette-table-design-v0.1.md)
for the original rationale).

## Status: Phase 0 — walking skeleton

Per spec §14, we build *through the seams* so later phases are substitutions, not
rewrites. Phase 0 proves the core loop end to end with **in-memory state** and a
**scripted (offline) DM** — no API key required. Phases 1–2 (combat boundary, then
the real event log + SQLite) slot in behind interfaces that already exist.

## Quickstart

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate     # POSIX: source .venv/bin/activate
pip install -e ".[dev]"

pytest                                   # run the §14.1 acceptance test
python -m oubliette.app.repl --script --scripted   # watch the demo transcript
python -m oubliette.app.repl             # interactive REPL (uses a real model if
                                         # ANTHROPIC_API_KEY is set; install .[anthropic])
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
| `record/` | Phase 0 debug log + the single seeded RNG (becomes the event log in Phase 2) |
| `llm/` | the `LLMClient` seam; `scripted` (offline double) + `anthropic` (real) adapters |
| `schemas.py` | typed structured-output contracts (Intent, assessment, resolution, tool calls) |
| `tools/` | the tool surface — the only doors into protected state |
| `dm/` | the DM brain: assess, then resolve (narrate + emit tools) |
| `runtime/` | the turn loop: assess → roll → resolve → apply → render |
| `app/` | terminal REPL |

## What Phase 0 deliberately does NOT do yet

Event sourcing / replay, SQLite, the combat subsystem, canonization persistence,
and the trade window. Those are Phases 1–3 (spec §14). The seams for all of them
already exist (`Repository`, `LLMClient`, the `record/` RNG, the combat boundary).
