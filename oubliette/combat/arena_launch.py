"""The Arena launch coordinator (combat Stage 3 — "flip the switch").

This is the live-play seam that replaces the placeholder `auto_resolve`. It turns
a narrator `EncounterRequest` into a *staged* tactical fight, spawns The Arena as
a subprocess when the player enters it, and maps the result back through the
Stage-2 bridge.

The flow is two-step (D-COMBAT-3 — an explicit "⚔ Enter the Arena" button, never
an auto-pop):

  1. `stage_combat(...)` resolves enemies (templates → bestiary → persistent
     entities), maps the live party + monsters through `arena_bridge`, writes the
     encounter JSON to a scratch dir, and returns a `PendingCombat`. A non-combat
     exit (parley/flee/bribe) short-circuits to an immediate `CombatResult`
     instead — no Arena.
  2. when the player enters, `run_arena(pending)` spawns
     `python -m arena.handoff <encounter> <result>` (blocking — it owns the pygame
     window), reads the result JSON, and `resolve_to_combat_result(...)` maps it to
     a `CombatResult`. The caller emits the single COMBAT_RESULT event.

`run_arena` is the one impure step (it launches a GUI subprocess); tests
monkeypatch it with a canned result so the whole wiring is exercised headlessly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..schemas import TurnAssessment
from ..state.repository import Repository, StateError
from .arena_bridge import (
    BattleSetting,
    EnemyInstance,
    EncounterPlan,
    PortraitDirs,
    battle_setting,
    build_encounter,
    enemy_from_character,
    enemy_from_statblock,
    result_to_combat_result,
)
from .boundary import CombatError, _EXIT_DIGEST
from .schemas import CombatResult, EncounterRequest, ExitKind

# Project root (…/Oubliette) — the cwd the Arena subprocess needs so that
# `import arena` resolves. This file is at oubliette/combat/arena_launch.py.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Shipped content root (…/oubliette/content) — SRD + pack portrait dirs.
_CONTENT_ROOT = Path(__file__).resolve().parents[1] / "content"


def _portrait_dirs(session) -> PortraitDirs:
    """Where this campaign's token art lives (B6). PC uploads sit beside the
    save DB — the same OUBLIETTE_DB contract the app server uses for its
    character-portraits/ dir; pack portraits ship with the active pack; the
    SRD fleet ships with the global content. All lookups degrade to None."""
    db = Path(os.environ.get("OUBLIETTE_DB", "oubliette-save.sqlite")).resolve()
    pack_id = getattr(session, "pack_id", None)
    return PortraitDirs(
        pc=db.parent / "character-portraits",
        pack=(_CONTENT_ROOT / "packs" / pack_id / "portraits") if pack_id else None,
        srd=_CONTENT_ROOT / "srd" / "portraits",
    )


@dataclass
class PendingCombat:
    """A staged-but-unresolved fight, held on the session until the player enters
    the Arena. Transient runtime state — never event-sourced."""

    plan: EncounterPlan
    encounter_path: Path
    result_path: Path
    scratch_dir: Path
    assessment: TurnAssessment | None = None
    player_text: str = ""


@dataclass
class StageOutcome:
    """Either an immediate result (a non-combat exit, resolved without the Arena)
    or a staged fight awaiting "Enter the Arena". Exactly one is set."""

    result: CombatResult | None = None
    pending: PendingCombat | None = None


# --- enemy resolution (persistent entities → bestiary) -------------------

def _norm_ref(ref: str) -> str:
    """Normalise an enemy ref for tolerant matching: lowercase, trim, and treat
    spaces/hyphens as underscores so 'Dire Wolf' and 'dire-wolf' both hit
    `dire_wolf`."""
    return ref.strip().lower().replace(" ", "_").replace("-", "_")


def _statblock_for(session, ref: str):
    """Look a ref up as a monster stat block, tolerant of natural naming (the DM
    names creatures in plain English, not by exact id). Pack creatures (this-world
    bestiary) take precedence over the global SRD bestiary (334 monsters); each is
    matched by normalised id OR name."""
    want = _norm_ref(ref)
    pack = getattr(session, "statblocks", ()) or ()
    srd = (getattr(getattr(session, "ruleset", None), "bestiary", None) or {}).values()
    pool = (*pack, *srd)
    # Exact match on normalized id or name.
    for sb in pool:
        if _norm_ref(sb.id) == want or _norm_ref(sb.name) == want:
            return sb
    # Tolerant fallback for the DM's descriptive naming ("a wild wolf" → Wolf):
    # a creature whose full name is a trailing WHOLE-WORD of the ref. Prefer the
    # longest (most specific) match, so "giant wolf spider" beats a bare "wolf".
    # Whole-word only (the leading "_") so 'werewolf' never matches 'wolf'.
    best = None
    for sb in pool:
        name = _norm_ref(sb.name)
        if want.endswith("_" + name) and (best is None or len(name) > len(_norm_ref(best.name))):
            best = sb
    return best


def _try_entity(repo: Repository, ref: str):
    """The persistent character for an EXACT-id ref, or None. Exact-only so the
    DM's descriptive naming ('a wild wolf') still resolves as a stat block, while
    a code-issued entity id (a recurring foe) is recognised as persistent."""
    try:
        return repo.get_character(ref)
    except StateError:
        return None


def _resolve_enemies(
    request: EncounterRequest, repo: Repository, session,
    portraits: PortraitDirs | None = None,
) -> list[EnemyInstance]:
    """Resolve each `EnemyRef` to an `EnemyInstance`: persistent entity → stat
    block. Raises `CombatError` on an unknown ref.

    Precedence note (Forge Phase 4a): a persistent ENTITY is checked BEFORE a bare
    stat block, so a recurring creature-NPC (Seraphel, whose id matches her stat
    block) keeps entity semantics — final HP written back, a single instance, no
    loot — rather than spawning as an ephemeral copy. Generic monsters ('a pack of
    wolves') aren't repo entities, so they fall through to the stat-block path
    unchanged."""
    # The pack's Forge-authored personalities, keyed by id, so a custom
    # `ai_profile` on a stat block resolves to a real AIProfile in the Arena.
    ai_profiles = {p.id: p for p in getattr(session, "ai_profiles", ()) or ()}
    # {npc id -> StatBlock id}: the runtime Character drops the stat_block ref, so
    # this is how a recurring creature-NPC is mapped back to its authored block.
    npc_statblocks = getattr(session, "npc_statblocks", None) or {}
    # The pack's own combat files (Phase 3b): a Forge-authored creature that ships
    # `monsters/<id>.json` fights its full kit instead of the flat one-swing mapping.
    pack_id = getattr(session, "pack_id", None)
    pack_monster_dir = (_CONTENT_ROOT / "packs" / pack_id / "monsters") if pack_id else None

    def from_statblock(sb) -> EnemyInstance:
        return enemy_from_statblock(sb, portraits, ai_profiles=ai_profiles,
                                    pack_monster_dir=pack_monster_dir)

    out: list[EnemyInstance] = []
    for ref in request.enemies:
        ent = _try_entity(repo, ref.ref)
        if ent is not None:
            sb_id = npc_statblocks.get(ent.id)
            sb = _statblock_for(session, sb_id) if sb_id else None
            if sb is not None:
                # A creature-NPC: the full stat-block kit (its rich monsters/<id>.json
                # wins when present), but PERSISTENT — write HP back and drop no loot,
                # the recurring-foe policy `enemy_from_character` already follows. Keep
                # the NPC's own name (Seraphel), not the stat block's species label.
                inst = from_statblock(sb)
                inst.creature.name = ent.name
                inst.entity_id = ent.id
                inst.loot = []
            else:
                inst = enemy_from_character(ent, portraits)   # no stat block: flat
            out.append(inst)                                  # persistent ⇒ one
            continue
        sb = _statblock_for(session, ref.ref)
        if sb is not None:
            inst = from_statblock(sb)
            out.extend(inst for _ in range(max(1, ref.count)))
            continue
        raise CombatError(
            f"enemy ref {ref.ref!r} is neither a bestiary monster nor an entity"
        )
    return out


def _resolve_allies(
    request: EncounterRequest, repo: Repository, party: list,
) -> list:
    """The player party PLUS any friendly entities the encounter names as allies
    (Forge 4b-ally). Each ally id is an EXISTING persistent entity (a recruited
    person-NPC, or any present NPC who sides with the party); it joins the player
    team for THIS fight, player-controlled, at full sheet fidelity via
    `character_to_player`. Per-encounter only — naming an ally implies no standing
    party membership.

    Unlike an unknown ENEMY ref (which aborts the fight), an unresolvable or
    duplicate ally id is simply SKIPPED — an ally is additive, never required, so a
    stray ref the narrator invents must not collapse the encounter."""
    have = {c.id for c in party}
    out = list(party)
    for ref in request.allies:
        if ref in have:
            continue
        ent = _try_entity(repo, ref)
        if ent is not None:
            have.add(ent.id)
            out.append(ent)
    return out


def _battle_for(session) -> BattleSetting | None:
    """The current location's authored battlefield (location-battles arc), or
    None for the default field. Entirely session-side: the loader threads each
    Place's `battle` block onto its PlaceNode, and asset filenames resolve
    against the active pack's content dir. Every step degrades to None — a
    session without places (tests, legacy saves) stages exactly as before."""
    loc = getattr(session, "location", None)
    places = getattr(session, "places", None) or {}
    node = places.get(loc) if loc else None
    battle = getattr(node, "battle", None)
    if battle is None:
        return None
    pack_id = getattr(session, "pack_id", None)
    pack_dir = (_CONTENT_ROOT / "packs" / pack_id) if pack_id else None
    return battle_setting(battle, pack_dir)


# --- staging -------------------------------------------------------------

def stage_combat(
    request: EncounterRequest,
    repo: Repository,
    session,
    *,
    assessment: TurnAssessment | None = None,
    player_text: str = "",
    scratch_root: Path | None = None,
    portraits: PortraitDirs | None = None,
    budget=None,
) -> StageOutcome:
    """Validate + stage a fight. A chosen non-combat exit resolves immediately
    (no Arena); otherwise the live party + resolved enemies are written to an
    encounter file and a `PendingCombat` is returned. `assessment`/`player_text`
    are the triggering turn's (carried so the post-combat report can be built).
    `portraits` overrides the campaign's derived token-art dirs (tests).
    `budget` (an `EncounterBudget`, difficulty S2) checks the resolved enemies
    against the table's caps and raises `BudgetError` on a violation — the
    runtime's bounce-back path; None (direct/authored callers) skips it."""
    # Non-combat exit short-circuit (parley/flee/bribe) — same contract as the
    # boundary; no tactical board needed.
    if request.chosen_exit is not None:
        if request.chosen_exit not in request.allow_exits:
            raise CombatError(f"exit {request.chosen_exit.value!r} not permitted this encounter")
        return StageOutcome(result=CombatResult(
            outcome=request.chosen_exit.value,
            narrative_digest=_EXIT_DIGEST[request.chosen_exit],
        ))

    if not request.enemies:
        raise CombatError("encounter has no enemies and no chosen exit")

    if portraits is None:
        portraits = _portrait_dirs(session)
    enemies = _resolve_enemies(request, repo, session, portraits)
    if budget is not None:
        from .budget import check_encounter
        check_encounter(enemies, budget)
    party = _resolve_allies(request, repo, repo.party() or [repo.pc()])
    # The ruleset rides along: the mechanics catalog turns drinkable consumables
    # into Arena item actions (B1) and equipped +X items into real bonuses (B3),
    # and the class tables stage each PC's CURRENT spell-slot/resource state (B2).
    # The catalog is the session's MERGED set — SRD plus the pack's own magic
    # items (module-kit S1) — so a Forge-authored Flametongue works like SRD gear.
    ruleset = getattr(session, "ruleset", None)
    catalog = (getattr(session, "mechanics_catalog", None)
               or getattr(ruleset, "equipment", None))
    plan = build_encounter(party, enemies, request.terrain,
                           name=request.kind.title() or "Encounter",
                           catalog=catalog,
                           ruleset=ruleset,
                           portraits=portraits,
                           battle=_battle_for(session))

    scratch_dir = Path(tempfile.mkdtemp(prefix="oubliette-combat-", dir=scratch_root))
    encounter_path = scratch_dir / "encounter.json"
    result_path = scratch_dir / "result.json"
    _write_encounter_file(plan.encounter, scratch_dir, encounter_path)
    return StageOutcome(pending=PendingCombat(
        plan=plan, encounter_path=encounter_path, result_path=result_path,
        scratch_dir=scratch_dir, assessment=assessment, player_text=player_text,
    ))


def _write_encounter_file(encounter, scratch_dir: Path, path: Path) -> None:
    """Write the encounter JSON with each combatant EXTERNALIZED to its own file
    under monsters/ or characters/, referenced by absolute `creature_id`.

    Inline `creature_data` cannot survive the round-trip: the Arena types that
    field as the base `Creature`, so a `Monster`/`PlayerCharacter` written inline
    comes back as a plain `Creature` — silently losing its subclass fields
    (experience_points, challenge_rating, …), which zeroed out kill XP. Writing
    each creature to a path the Arena recognizes ('monsters'/'characters' in the
    id) routes it through the subclass-aware loader (`Monster.model_validate` /
    `PlayerCharacter.model_validate`), preserving every field. We externalize a
    DEEP COPY so the in-memory `plan.encounter` keeps its inline creatures.
    """
    enc = encounter.model_copy(deep=True)
    mon_dir = scratch_dir / "monsters"
    pc_dir = scratch_dir / "characters"
    mon_dir.mkdir(exist_ok=True)
    pc_dir.mkdir(exist_ok=True)
    for i, entry in enumerate(enc.combatants):
        creature = entry.creature_data  # the concrete Monster/PlayerCharacter instance
        target_dir = pc_dir if entry.team == "player" else mon_dir
        cfile = target_dir / f"{i:02d}.json"
        cfile.write_text(
            json.dumps(creature.model_dump(mode="json"), indent=2), encoding="utf-8"
        )
        entry.creature_id = str(cfile.resolve())  # absolute → ignores the Arena's data_dir
        entry.creature_data = None
    path.write_text(json.dumps(enc.model_dump(mode="json"), indent=2), encoding="utf-8")


# --- launch + map-back ---------------------------------------------------

def run_arena(pending: PendingCombat) -> dict:
    """Spawn The Arena into the staged encounter and block until the player exits,
    then read back the result dict. THE impure step — monkeypatched in tests."""
    cmd = [sys.executable, "-m", "arena.handoff",
           str(pending.encounter_path), str(pending.result_path)]
    proc = subprocess.run(cmd, cwd=str(_PROJECT_ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-500:]
        raise CombatError(f"the Arena exited abnormally (code {proc.returncode}): {tail}")
    try:
        return json.loads(pending.result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise CombatError(f"the Arena produced no readable result: {e}") from e


def resolve_to_combat_result(pending: PendingCombat, handoff: dict) -> CombatResult:
    """Map an Arena handoff result dict back to a `CombatResult` via the bridge."""
    return result_to_combat_result(handoff, pending.plan)


def cleanup(pending: PendingCombat) -> None:
    """Remove the scratch encounter/result files. Best-effort — a leftover temp
    dir is harmless."""
    import shutil
    shutil.rmtree(pending.scratch_dir, ignore_errors=True)
