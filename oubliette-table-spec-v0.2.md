# Oubliette Table — Formal Design Spec (v0.2)

*Status: working spec. Supersedes the v0.1 decision record for anything they conflict on; v0.1 remains the source of intent and rationale. Implementation language: **Python**. Combat internals are out of scope here — only the combat **boundary** (encounter request in, result object out) is specified.*

*Revision: **v0.2.1** — incorporates colleague review (2026-06-04). Changes: OPEN content is no longer event-sourced (D-OPEN-1); new decisions D5–D9 + transact symmetry; replay determinism narrowed to authoritative state (D9); model-set adjudication numbers clarified (D8); added §14 build order and the Phase 0 acceptance test. See §13.1.*

> **Reading guide.** Sections marked **[LOCKED]** restate a decision already made in v0.1 and should not be reopened without cause. Sections marked **[PROPOSED — confirm]** are new technical decisions this spec introduces to make v0.1 buildable; they're defaults, not commitments. Sections marked **[OPEN]** are genuinely undecided.

---

## 0. Purpose and scope

This document specifies the *interfaces and data contracts* between the layers in v0.1 §3, in enough detail to start building. It deliberately does **not** specify: the combat rules engine internals, the prompt text for any LLM role, the front-end, or the deployment story. Those get their own documents.

The guiding invariant, restated because everything below serves it:

> **The LLM narrates and proposes; code owns state and the rules. The model is never the authority on a number, and the player never holds the pen.** **[LOCKED]**

Two structural facts enforce that invariant, and the whole spec is arranged so they can never be violated by accident:

1. **Only code mutates authoritative state, and only by applying a recorded tool call.** The LLM can *emit* a tool call (a request); the runtime decides whether to *apply* it. The player can do neither.
2. **Every mutation and every die roll is appended to an event log before it takes effect.** Reload replays the log; it never re-rolls and never re-asks the model.

**Scope of "never the authority on a number" (D8).** This governs **state numbers** — gold, HP, XP, inventory counts, faction standing — the values code owns and records. It does **not** govern **adjudication numbers** — skill-check DCs, whether a roll is required at all, advantage/disadvantage. Those are *intentionally* model-set and are the heart of the soft layer (§11). **Do not hard-code DCs.** Hard-coding them silently reverts the soft-economy/soft-difficulty decision; this note is a standing guardrail against a future "cleanup" pass undoing it.

---

## 1. Glossary

| Term | Meaning |
|---|---|
| **Authoritative state** | The single source of truth: character sheets, HP, inventory, gold, world flags, NPC/quest/faction records, canon status. Lives in the DB. |
| **Tool call** | A typed, named request to mutate protected state (`transact`, `grant_xp`, …). Emitted by the DM model, validated and applied by the runtime, recorded in the event log. |
| **Intent** | The parser's typed reading of one player message: a verb, optional skill, target, and args. |
| **Tier** | The router's classification of a turn: `authored` / `recombined` / `freestyle` / `denied`. |
| **Event log** | Append-only ordered record of everything non-deterministic or state-changing: player messages, rolls, applied tool calls, combat results. The replay substrate. |
| **Canon record** | Any piece of world content (NPC, place, lore, quest) with an `origin` and a `status` (`provisional` / `confirmed`). |
| **Summoned tool** | A bounded sub-mode (combat, trade window) that takes over the turn, shows authoritative state directly, and returns a structured result. Not a player-held control. |
| **OPEN / PROTECTED domain** | Two classes of state. OPEN: DM edits freely (still recorded). PROTECTED: changed only via named tool calls. (v0.1 §7) |

---

## 2. Architecture as Python modules

The v0.1 §3 layer table maps to packages. Each LLM-backed layer is a **function with the model as a swappable parameter** (v0.1 §3), expressed in Python as a role that depends on an injected `LLMClient` (see §9). **[PROPOSED — confirm]** package layout:

```
oubliette/
  state/        # authoritative state: ORM models + repositories (the only DB writers)
  rules/        # pure SRD functions: checks, attacks, saves, damage. No I/O.
  record/       # event log: append, read, replay; the deterministic-RNG service
  llm/          # LLMClient protocol + provider adapters; role base classes
  parser/       # player text -> Intent (structured output)
  router/       # Intent + context -> RouteDecision (tier + hint)
  tools/        # the protected-state tool surface: schemas, validation, dispatch
  dm/           # DM orchestration: query state, request rolls, emit tools, narrate
  canon/        # canonization lifecycle: provisional/confirmed, promotion
  trade/        # trade window (summoned tool)
  combat/       # BOUNDARY ONLY here: EncounterRequest in, CombatResult out
  runtime/      # the turn loop: wires parser -> router -> dm -> apply -> render
  app/          # entry point, session lifecycle, transport to the UI
```

**Dependency rule:** `rules/` and `record/`'s RNG are **pure / deterministic** and depend on nothing else in the tree. `state/` is the only package that writes the DB. `tools/` is the only package that calls `state/` write methods on behalf of the DM. Everything LLM-backed depends on `llm/` but never on each other directly — they compose only in `runtime/`. This is the "architect the seams" instruction from v0.1 §3 made concrete.

```
player ──> runtime ──> parser ──> router ──> dm ─┬─> tools ──> state
                                                  ├─> rules (via record's RNG)
                                                  └─> combat / trade (summoned)
              every roll & applied tool ──> record (append-only) ──> replay
```

---

## 3. Authoritative state — data model

**[DECIDED]** Modeled with SQLModel/Pydantic (gives us ORM + validation + JSON schema from one definition). Storage: **SQLite** for single-player dev, with the repository layer abstracting it so Postgres is a later swap when multiplayer/hosting arrives (decision D1, §13). Every protected field is annotated so the firewall (§6) can be enforced mechanically rather than by convention.

### 3.1 Domain classification (the firewall, as data)

Per v0.1 §7, every mutable field belongs to exactly one domain:

- **OPEN** — DM may create/edit during narration: scene flavor, world detail, minor/ephemeral NPC attributes, provisional lore text. **Stored as plain current-state rows, last-write-wins; NOT event-sourced (D-OPEN-1).** OPEN content is soft and non-load-bearing, so it does not belong in the replay substrate — on reload it is simply whatever it last was.
- **PROTECTED** — mutated *only* through a tool call in §5: `gold`, `xp`, `level`, ability scores, `inventory`, `hp`/`max_hp`, `conditions`, faction standing, quest flags/state, and the `status` of any canon record. This — plus entity creation (`create_entity`) — is the **only** state that is event-sourced.

The model layer tags each field (`Field(domain="protected")`). A single guard in `state/` rejects any write to a protected field that does not arrive through `tools/`'s dispatcher. That guard is the firewall — code, not discipline.

### 3.2 Core entities

```python
# --- Character (the player and any statted NPC share this shape) ---
class Character:
    id: EntityId
    name: str
    kind: Literal["pc", "npc"]
    level: int                      # PROTECTED
    xp: int                         # PROTECTED
    class_name: str                 # SRD class; PROTECTED at creation
    abilities: dict[Ability, int]   # STR..CHA, 6 scores; PROTECTED
    proficiency_bonus: int          # derived from level; computed, not stored authoritatively
    max_hp: int                     # PROTECTED
    hp: int                         # PROTECTED  (combat writes via CombatResult, §8)
    armor_class: int                # PROTECTED
    conditions: list[Condition]     # PROTECTED
    skill_proficiencies: set[Skill] # which of the 18 SRD skills are proficient
    spell_slots: dict[int, SlotState]   # level -> {max, remaining}; PROTECTED
    inventory: list[ItemStack]      # PROTECTED
    gold: int                       # PROTECTED
    # OPEN: description, personality notes, disposition text, appearance

# --- Item ---
class Item:
    id: EntityId
    name: str
    slug: str                       # stable key for authored items
    tags: list[str]                 # "weapon","light","consumable",...
    srd_ref: str | None             # link to SRD stat block if applicable
    base_value: int | None          # advisory only; economy is soft (§7). Never enforced.

class ItemStack:
    item_id: EntityId
    qty: int

# --- World flags & quests ---
class Flag:                         # PROTECTED
    key: str                        # "brightvale.gate_open"
    value: bool | int | str

class Quest:
    id: EntityId
    slug: str
    title: str                      # OPEN text
    state: Literal["inactive","active","completed","failed"]  # PROTECTED
    stage: int                      # PROTECTED; advance_quest steps this
    depends_on: list[EntityId]      # entities this quest is load-bearing on (drives auto-promotion, §10)

# --- Faction ---
class Faction:
    id: EntityId
    slug: str
    name: str
    standing: dict[EntityId, int]   # character_id -> standing; PROTECTED

# --- Canon wrapper: every world-content entity carries one ---
class CanonRecord:
    entity_id: EntityId
    entity_type: Literal["npc","place","lore","item","quest","faction"]
    origin: Literal["authored","recombined","freestyle"]
    status: Literal["provisional","confirmed"]   # PROTECTED; promote_canon flips it
    created_by_event: EventId       # back-reference into the log
    load_bearing: bool              # true once something confirmed depends on it (§10)
```

`EntityId` and `EventId` are opaque, monotonic, replay-stable IDs (§4.4). `proficiency_bonus` is shown as stored but is a pure function of `level`; the spec's stance is **derive, don't store** for anything the SRD computes, so it can't drift.

---

## 4. The event log and replay

This is the determinism backbone (v0.1 §4, §12). It is the most important section to get right because every other guarantee leans on it.

### 4.1 What is an event

An **event** is an append-only, immutable record of one thing that either changed state or consumed entropy. Events are the *only* things replayed. Narration, model prompts, and router decisions are **not** replayed — they are regenerated or simply skipped on reload, because they are downstream of events and never authoritative.

```python
class Event:
    id: EventId                     # monotonic, gap-free per session
    session_id: SessionId
    turn_id: TurnId
    seq: int                        # order within the session
    kind: EventKind
    payload: dict                   # kind-specific, schema-validated
    caused_by: EventId | None       # provenance chain
    # NO wall-clock timestamp is load-bearing; a recorded clock value may live in payload
    #   for display, but replay ordering is by (seq), never by time.

class EventKind(Enum):
    PLAYER_MESSAGE   = "player_message"     # raw player text + parsed Intent
    ROLL             = "roll"               # a die roll and its result (§4.3)
    TOOL_APPLIED     = "tool_applied"       # a validated tool call that mutated state (§5)
    COMBAT_RESULT    = "combat_result"      # the structured result object from combat (§8)
    TRADE_RESULT     = "trade_result"       # the structured result object from the trade window
    CANON_PROMOTED   = "canon_promoted"     # provisional -> confirmed (§10)
    SESSION_MARKER   = "session_marker"     # session start/end, used by end-of-session review
```

### 4.2 Replay contract

> Given the same ordered sequence of events from `seq=0`, applying them produces a byte-identical authoritative state. **[LOCKED — this is v0.1's "replay from records."]**

**Replay scope (D9).** Byte-identical replay applies to **authoritative state only** (the PROTECTED ledger + created entities). **Narrative continuity is best-effort:** narration is regenerated on reload and may differ from an uninterrupted run. This is a known, accepted limitation — do **not** attempt to make narration deterministic. (It also follows from D-OPEN-1: OPEN flavor content isn't replayed at all, so it can't be expected to reproduce.)

Therefore the apply functions must be **pure with respect to the event**: a `TOOL_APPLIED` event carries everything needed to reproduce its effect (final values, not "ask the model again"). Replay walks events in `seq` order, dispatches each to its deterministic applier, and never calls an LLM and never calls the RNG (rolls are already events — see §4.3).

### 4.3 Deterministic RNG — the subtle part

Dice are non-deterministic, so they must be recorded, not re-rolled. The rule:

- All randomness flows through one service, `record.rng`. It is the **only** source of dice in the system; `rules/` receives roll *results*, never a raw RNG.
- During **live play**, `rng.roll(spec)` draws from a seeded PRNG, **appends a `ROLL` event** with the spec and the concrete result, and returns the result.
- During **replay**, `rng.roll(spec)` is never called by the appliers at all — the `ROLL` events are themselves replayed as state, and any code that needs a past roll reads it from the log.

This means the rules engine is pure (results in, decision out) and the only stateful, recorded entropy lives in exactly one place. A `ROLL` payload:

```python
{ "spec": "1d20+5", "rolls": [14], "modifier": 5, "total": 19,
  "purpose": "skill_check.deception", "dc": 15, "outcome": "success" }
```

### 4.4 ID allocation

`EntityId`/`EventId` come from a per-session monotonic counter that is **itself part of the replayed state** (the "next id" is reconstructed by replay), so created entities get identical IDs on every replay. No UUIDs, no wall-clock seeds — both would break byte-identical replay. **[PROPOSED — confirm]**

---

## 5. The tool surface — the only doors into protected state

These are the named, recorded doors from v0.1 §7. The DM model emits a tool call as structured output; the runtime **validates, applies, and records** it. Validation failures are returned to the DM as a tool error (it may try again or narrate around it); they never partially mutate state.

Each tool is a Pydantic model (so we get JSON schema for free to hand the model) plus a pure applier `apply(call, state) -> (new_state, Event)`.

```python
# transact: the workhorse. Atomic, BALANCED exchange between two parties.
class Transact:
    give:    list[ItemStack | GoldAmount]   # leaves `from_`, lands with `counterparty`
    receive: list[ItemStack | GoldAmount]   # leaves `counterparty`, lands with `from_`
    from_:   EntityId                        # usually the PC
    counterparty: EntityId                   # merchant/NPC
    reason:  str                             # fiction hook, for the audit trail
    # Symmetry (per review): the exchange is atomic and balanced on BOTH sides — `give`
    #   moves from_ -> counterparty AND `receive` moves counterparty -> from_, all-or-nothing.
    #   The TOOL_APPLIED event records BOTH parties' deltas, not just from_'s.
    # Validation: from_ actually holds what it gives; counterparty actually holds what it
    #   gives back (caps merchant purchases at their gold — v0.1 §9). Never checks a "true value".

# give / take: one-directional convenience over transact (no counterparty exchange)
class Give: to: EntityId;  items: list[ItemStack | GoldAmount]; reason: str
class Take: from_: EntityId; items: list[ItemStack | GoldAmount]; reason: str

# grant_xp: resolution events ONLY (combat end, quest stage, skill challenge)
class GrantXp: to: EntityId; amount: int; source_event: EventId; reason: str
    # Validation: source_event must be a resolution-class event, not bare DM say-so.

# set_flag / advance_quest
class SetFlag: key: str; value: bool|int|str; reason: str
class AdvanceQuest: quest_id: EntityId; to_stage: int; reason: str
    # advance_quest auto-marks its depends_on entities load_bearing -> triggers §10.

# create_entity: introduces new world content; ALWAYS carries a CanonRecord
class CreateEntity:
    entity_type: Literal["npc","place","lore","item","quest","faction"]
    data: dict                       # validated against the entity schema
    origin: Literal["recombined","freestyle"]   # authored content isn't created at runtime
    # status is forced to "provisional" on creation; only promote_canon confirms it.

# promote_canon: provisional -> confirmed (§10)
class PromoteCanon: entity_id: EntityId; trigger: Literal["session_review","load_bearing"]; reason: str
```

**Dispatch invariants:**

- The runtime applies a tool call **only** if it arrived in the DM model's structured output for the current turn. A tool call appearing in narration text is ignored (and logged as a parser anomaly).
- Every successful apply produces exactly one `TOOL_APPLIED` event **before** the new state is committed. (Append-then-commit, so a crash mid-apply replays cleanly.)
- `reason` is mandatory on every tool. It's the human-readable audit trail that makes "every change auditable" (v0.1 §7) real.
- **Retry bound (D6).** On tool-call validation failure the DM gets **at most 2 retries** within the turn. After that the runtime forces a **narration-only** resolution for the turn and surfaces a `meta`-channel notice to the player ("the DM lost the thread — try rephrasing"). Failed attempts are logged as **anomalies**, never as `TOOL_APPLIED`. (Without a cap, a confused model loops and burns real money.)

Combat's HP/condition writes do **not** go through this surface — they arrive as a single `COMBAT_RESULT` event (§8), keeping the "never parse prose back into numbers" rule intact.

---

## 6. Intent schema (parser output)

The parser (`parser/`) is an LLM role with structured output. It converts one player message into a typed `Intent`. It classifies; it does **not** resolve or touch state.

```python
class Intent:
    raw_text: str
    verb: Verb                       # the ~8 from v0.1 §5
    skill: Skill | None              # one of the 18 SRD skills; only when verb == skill_check
    targets: list[EntityRef]         # resolved-if-possible references ("the merchant","ledge")
    args: dict                       # verb-specific freeform slots (e.g. item name for use_item)
    confidence: float                # parser's self-rated certainty; low -> router leans freestyle/meta
    ooc: bool                        # true when this is the meta/table-talk channel

class Verb(Enum):
    MOVE="move"; ATTACK="attack"; CAST="cast"; USE_ITEM="use_item"
    TRADE="trade"; REST="rest"; SKILL_CHECK="skill_check"; META="meta"
```

**[LOCKED]** The verb enum is closed (v0.1 §5). Anything that fits no verb is *not* a parser error — it's the signal that pushes the router toward the `freestyle` tier (§7). `skill_check` is the only parameterized verb; the 18 SRD skills are its parameter, and social actions (persuasion/deception/intimidation) are just the CHA skills, not separate verbs. `meta` is bidirectional and never mutates state.

---

## 7. Router contract

The router (`router/`) takes `Intent + context` and returns a `RouteDecision`. It assigns a tier and a resolution hint. **It does not protect state** — protection is structural (§5/§6). Its job is purely to tell the DM *how* to treat the turn. **[LOCKED — v0.1 §6]**

```python
class RouteDecision:
    tier: Tier
    may_canonize: bool               # derived from tier, restated for the DM's convenience
    resolution_hint: str             # short instruction to the DM ("use authored Thom stats")
    matched_content: list[EntityId]  # what authored/confirmed content this turn touches

class Tier(Enum):
    AUTHORED="authored"        # matches existing content; use it.            may_canonize=False
    RECOMBINED="recombined"    # pieces exist, assemble them.                 may_canonize=True
    FREESTYLE="freestyle"      # genuinely novel; improvise within schema.    may_canonize=True
    DENIED="denied"            # violates a hard constraint; diegetic "no".   may_canonize=False
```

`denied` exists only to phrase a graceful in-world refusal; exploits already fail safe by construction, so `denied` is never load-bearing for security (v0.1 §6/§7). The "fiat" example ("I now have 10,000 gold") routes `denied` simply so the refusal reads nicely — but even if it were mis-routed, no tool call would fire, so state is safe regardless.

**[DECIDED]** The router starts as an **LLM role behind the same swappable interface** as the others, because tiering needs world knowledge (decision D3, §13). Instrument cost/latency from day one and peel cheap, high-confidence cases onto a rule or a smaller model once there's data.

---

## 8. Combat boundary (internals deferred)

Per your scoping, only the two edges are specified here. The internals (hex grid, action economy, conditions, reactions, concentration) are a separate document.

**In — `EncounterRequest`** (emitted by the narrator when it detects hostility; declarative):

```python
class EncounterRequest:
    kind: Literal["ambush","standoff","brawl",...]
    enemies: list[EntityRef]         # each resolves to EITHER a template OR an existing persistent entity
    terrain: TerrainSpec
    allow_exits: list[ExitKind]      # which non-combat exits are available this fight
```

The runtime **validates** the request and instantiates the encounter from templates + **live authoritative state** (v0.1 §10) — the model names *who*, code supplies their *numbers*.

**Ephemeral combatants (D5).** Each `EntityRef` in `enemies` resolves one of two ways:
- → a **template** ⇒ the combatant is **ephemeral**: spawned from the template, no `CanonRecord`, no persistent entity row, **discarded when the combat instance closes.** Dead mooks must never pollute the entity table.
- → an **existing persistent entity** (a recurring villain) ⇒ that entity is used directly and its post-combat numbers are written back via `CombatResult`.

An ephemeral combatant is promoted to a persistent entity **only if** it (a) survives **and** (b) is flagged significant (named in the fiction, or the DM marks it). Promotion **reuses the canonization path** (§10) — `create_entity` + the lifecycle — rather than a parallel mechanism.

**Out — `CombatResult`** (the truth object the subsystem returns):

```python
class CombatResult:
    outcome: Literal["victory","defeat","fled","parley","surrender","bribe", ...]  # exits are first-class
    hp_final: dict[EntityId, int]            # ABSOLUTE final HP, not deltas (D7)
    conditions_final: dict[EntityId, list[Condition]]   # ABSOLUTE final condition set, not changes (D7)
    loot: list[ItemStack | GoldAmount]
    xp_award: int
    narrative_digest: str            # short prose GENERATED FROM the object, for DM context
```

**Absolute values, not deltas (D7).** Every field that lands in authoritative state via a result object carries **absolute final values** (e.g. `hp_final`, `conditions_final`), never deltas. This removes all apply/replay ambiguity — applying the same result twice is idempotent, and replay can't drift. (Only persistent combatants produce write-backs; ephemeral ones per D5 are discarded.)

The runtime applies `CombatResult` to authoritative state and writes **one** `COMBAT_RESULT` event. The `narrative_digest` flows *into* the DM's context; the numbers flow *into* state. The LLM never reads numbers back out of prose (v0.1 §10). Non-combat exits (`fled`/`parley`/`surrender`/`bribe`) are ordinary outcome values, not special cases — "talk the raiders down," actually wired in.

---

## 9. The model-as-parameter seam

v0.1 §3's "design each role as a function with the model as a swappable parameter" becomes one Protocol and one base class.

**[DECIDED]** The interface is **async** (decision D2, §13): `runtime` and `llm` are async — enabling streaming narration and concurrent role calls — while `rules` and `tools` appliers stay sync-pure, which keeps replay trivial. Structured output uses **provider-native JSON-schema/tool-use wrapped behind this protocol** (decision D4, §13); `instructor`-style retry can be added inside an adapter later without changing the contract.

```python
class LLMClient(Protocol):
    async def complete(self, *, system: str, messages: list[Msg],
                       schema: type[BaseModel] | None) -> LLMResult: ...
    # schema != None  -> provider-native structured output, validated into that model.

class Role:
    def __init__(self, client: LLMClient): self.client = client
    # Parser, Router, DM, Narrator each subclass Role and own their prompt + schema.
```

**[PROPOSED — confirm]** Day one: one capable model instance injected into every role (v0.1 §3 — "do not multi-model on day one"). The seam means later you swap `Parser(client=cheap_model)` without touching `Parser`'s logic. Instrument every role's call with token/latency counters from the start so the "peel cheap high-volume calls onto a smaller model" decision is data-driven.

---

## 10. Canonization lifecycle

Restating v0.1 §11 as a state machine on `CanonRecord.status`.

```
            create_entity (origin: recombined|freestyle)
                          │
                          ▼
                   ┌─────────────┐   promote_canon(session_review | load_bearing)   ┌───────────┐
   (authored ↦ ) ─►│ provisional │ ───────────────────────────────────────────────►│ confirmed │
                   └─────────────┘                                                   └───────────┘
                          │
            quarantine rule: provisional content CANNOT be load-bearing
            (a provisional NPC can't hand out quests, etc.)
```

- **`provisional`** — kept but quarantined. Persists, replays, but is "soft": the runtime refuses to let confirmed/authored content take a hard dependency on it. Any tool call that would make a provisional entity load-bearing (e.g. `advance_quest` whose `depends_on` includes it) **first** forces a `promote_canon(trigger="load_bearing")` — the **automatic** promotion path.
- **`confirmed`** — as dependable as authored content.
- **Primary promotion** is the end-of-session gut-check: at a `SESSION_MARKER(end)`, the DM may break character (a `meta` turn) and ask the player directly ("Do you care about Captain Bromley?"). A yes emits `promote_canon(trigger="session_review")`; silence/no leaves it provisional (and eligible to be written out later).

> **Canon only grows on purpose.** **[LOCKED]** Both promotion paths are explicit, recorded events; nothing is silently confirmed.

---

## 11. Economy & trade (soft)

**[LOCKED — v0.1 §8/§9]** No valuation engine. Price = LLM judgment + a haggle roll (`skill_check.persuasion` or `.deception`) whose DC is set by NPC disposition/shrewdness. `Item.base_value` exists only as an advisory hint to the model and is **never** enforced by code.

> **The haggle DC is a model-set adjudication number (D8), not a state number — do not hard-code it.** This is the canonical instance of the §0 scope note: difficulty and price live in the soft layer on purpose. A code-side DC table would silently revert this decision.

The self-correction mechanism is the **retrieval tool**, not an engine: before a large trade the DM is expected to pull party-wealth / economy context, which makes unwitnessed compounding visible and therefore self-limiting (v0.1 §8). The trade window (`trade/`) is a summoned tool with the same shape as combat: it *shows* merchant stock + merchant gold (capping what they can buy off the player), stock comes from the DB (authored or rolled from a loot template — the DM may nudge within bounds but not invent powerful items), and it returns a `TRADE_RESULT` event. Trivial buys skip the window entirely and resolve as a single `transact` in chat (v0.1 §9).

---

## 12. The turn loop as a state machine

Concrete realization of v0.1 §4, owned by `runtime/`.

```
RECEIVE       player message arrives
  └─> PARSE        parser -> Intent          (append PLAYER_MESSAGE event w/ intent)
        └─> ROUTE      router -> RouteDecision
              └─> branch on verb/tier:
                    ├─ meta            -> DM answers OOC, no state path, END
                    ├─ denied          -> DM returns diegetic refusal, no tools, END
                    ├─ summons combat  -> EncounterRequest -> COMBAT subsystem
                    │                       -> CombatResult -> APPLY -> END
                    ├─ summons trade   -> trade window -> TRADE_RESULT -> APPLY -> END
                    └─ otherwise       -> RESOLVE
  RESOLVE      DM resolves in fiction: queries state, requests rolls (each -> ROLL event)
        └─> EMIT       DM emits 0+ tool calls (structured output)
              └─> VALIDATE+APPLY   for each call: validate -> apply -> TOOL_APPLIED event
                    └─> NARRATE     DM narrates outcome (NOT recorded as authoritative)
                          └─> RENDER   visible state (HP, gold, …) re-renders from state
                                └─> END
```

Invariants over the loop:

- Every transition that consumes entropy or changes state appends an event **before** its effect is visible. The append is the commit point.
- `NARRATE` output is disposable — regenerable from state + event log, never the source of truth.
- A reload re-enters at `RENDER` after replaying the log; it resumes mid-loop only at event boundaries, so a crash between `EMIT` and `APPLY` loses at most the un-applied (un-recorded) tool call, never half-applies one.

---

## 13. Decisions and open questions

### 13.1 Resolved

Stack decisions (2026-06-04):

| ID | Decision | Choice | Rationale |
|---|---|---|---|
| **D1** | Persistence engine (§3) | **SQLite now, repository-abstracted** | Zero-setup, fast enough for single-player; the repo layer keeps Postgres a clean later swap for multiplayer/hosting. No ops cost taken on prematurely. |
| **D2** | Concurrency model (§9, §12) | **Async edges, sync core** | `runtime`/`llm` async to enable streaming narration + concurrent role calls; `rules`/`tools` appliers stay sync-pure, keeping replay trivial. |
| **D3** | Router placement (§7) | **LLM-first behind the swappable seam** | Tiering needs world knowledge; instrument from day one and peel high-confidence cases to code / a cheap model once there's data. |
| **D4** | Structured-output mechanism (§9) | **Provider-native schema + thin wrapper** | Most reliable on frontier models, minimal deps; `instructor`-style retry can live inside an adapter later without changing the `LLMClient` contract. |

Review decisions (2026-06-04, colleague review of v0.2):

| ID | Decision | Choice | Where |
|---|---|---|---|
| **D-OPEN-1** | OPEN-content recording | **Do not event-source OPEN content.** Plain current-state rows, last-write-wins; only PROTECTED state + `create_entity` are event-sourced. `OPEN_EDIT` kind dropped. | §3.1, §4.1 |
| **D5** | Ephemeral combatants | Template-resolved combatants are ephemeral (no `CanonRecord`, no row, discarded on close); persistent entities written back via `CombatResult`. Promotion reuses the canonization path. | §8 |
| **D6** | Tool-call retry bound | Max **2 retries**/turn on validation failure → then narration-only + `meta` notice; failures logged as anomalies, never `TOOL_APPLIED`. | §5 |
| **D7** | Result objects carry **absolute** values | `hp_final`/`conditions_final` etc. are absolute, not deltas → idempotent apply, no replay drift. | §8 |
| **D8** | Adjudication numbers are model-set | DCs / roll-required / advantage live in the soft layer; **do not hard-code DCs**. Distinct from state numbers, which code owns. | §0, §11 |
| **D9** | Replay scope | Byte-identical replay = **authoritative state only**; narration is best-effort/regenerated. | §4.2 |
| **—** | Transact symmetry | `transact` is atomic and balanced on both sides; the event records both parties' deltas. | §5 |

### 13.2 Still open [OPEN]

1. **Multiplayer/co-op** — one player's fiat affecting shared canon. Deferred (v0.1 §12). Note: the single-writer assumptions baked into v1 (gap-free `seq`, one monotonic ID counter) will need revisiting for `seq` allocation and ID generation under concurrent writers. That's a later document, not now.
2. **`provisional → confirmed` UX/prompts** — the lifecycle (§10) is settled; the exact prompts/UX of the session-end gut-check are deferred to the prompt-design doc.

**Standing decisions (closed unless playtest forces otherwise):**
- **Verb enum stays closed** (v0.1 §5). Do not add verbs speculatively; widen only when a real playtest case forces it.

---

## 14. Build order (per review) — IMPORTANT

The spec is *arranged* so the event log (§4) is the foundation everything leans on. **Do not build it first.** Event-sourcing is the right end state but a heavy substrate to stand up before anything is playable, and the priority is a playable turn fast. Build **through the seams** in this order so the later phases are *substitutions, not rewrites* — which is exactly what the §2 dependency rule and the repository interface buy us.

**Phase 0 — Walking skeleton (FIRST):**
- In-memory authoritative state as plain objects, **behind the repository interface** (§2), so it's swappable later.
- One model instance wired into parser + router + DM. Collapsing them into a single prompt is acceptable for the skeleton.
- The tool surface (§5) with **real** validation and appliers — but appliers mutate the in-memory state directly.
- A plain append-only Python list as a **debug** action log. *Not* the event-sourcing substrate — just visibility.
- **Acceptance:** in a terminal REPL, one full non-combat turn works end to end (see §14.1).

**Phase 1 — Combat boundary (SECOND):**
- Implement `EncounterRequest` → combat → `CombatResult` round trip with ephemeral combatants (D5). Internals can be a **minimal placeholder** (even auto-resolve) — the point is the boundary: live state in, result object out, applied to state, digest to DM. The revived tactical prototype slots in behind this boundary later.

**Phase 2 — Harden into event sourcing (THIRD):**
- Introduce the real event log (§4), the deterministic RNG service, replay, and swap the in-memory repo for SQLite via the repository interface. Because Phase 0 went through the seams, this is a **substitution**. Add reload/replay tests for the byte-identical-**state** guarantee (D9 scope).

**Phase 3+ —** full canonization lifecycle machinery, trade-window UI, then the front-end.

### 14.1 Phase 0 acceptance test (definition of "done" for the skeleton)

In a terminal REPL, this transcript must run clean:

1. Player: *"I look around the market."* → DM narrates. **No roll, no state change.**
2. Player: *"I tell the merchant these worn boots are priceless dwarven heirlooms."* → `skill_check.deception`; a **real d20 roll** happens and is logged; the DM decides whether/how far the merchant bends (DC is model-set — D8).
3. Player: *"Sold."* → `transact` fires; player gold increases by the agreed amount, boots leave inventory, **both reflected in the visible state readout** (transact symmetry).
4. Player: *"I now have 10,000 gold."* → routes `denied`; **no tool fires; gold unchanged.**

When that transcript runs clean, the core loop is proven and everything else is additive.

---

## Appendix A — Mapping v0.1 → v0.2

| v0.1 section | Where it lives now |
|---|---|
| §1 one principle | §0 invariant **[LOCKED]** |
| §2 trust model | §0 + §5 dispatch invariants |
| §3 architecture layers | §2 module layout |
| §4 turn loop | §12 state machine |
| §5 verb vocabulary | §6 Intent schema **[LOCKED]** |
| §6 four-tier router | §7 router contract |
| §7 procedural protection | §3.1 firewall-as-data + §5 tool surface |
| §8 economy & haggling | §11 |
| §9 trade window | §11 |
| §10 combat | §8 boundary only (internals deferred) |
| §11 canonization | §10 lifecycle state machine |
| §12 open/deferred | §13 |
```
