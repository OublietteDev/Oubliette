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
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..schemas import TurnAssessment
from ..state.repository import Repository, StateError
from .arena_bridge import (
    EnemyInstance,
    EncounterPlan,
    build_encounter,
    enemy_from_character,
    enemy_from_statblock,
    enemy_from_template,
    result_to_combat_result,
)
from .boundary import CombatError, _EXIT_DIGEST
from .schemas import CombatResult, EncounterRequest, ExitKind
from .templates import ENEMY_TEMPLATES

# Project root (…/Oubliette) — the cwd the Arena subprocess needs so that
# `import arena` resolves. This file is at oubliette/combat/arena_launch.py.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


# --- enemy resolution (templates → bestiary → persistent entities) -------

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


def _resolve_enemies(request: EncounterRequest, repo: Repository, session) -> list[EnemyInstance]:
    """Resolve each `EnemyRef` to an `EnemyInstance`, mirroring the boundary's
    precedence but producing Arena creatures: template → stat block → persistent
    entity. Raises `CombatError` on an unknown ref."""
    out: list[EnemyInstance] = []
    for ref in request.enemies:
        tmpl = ENEMY_TEMPLATES.get(ref.ref)
        if tmpl is not None:
            inst = enemy_from_template(tmpl)
            out.extend(inst for _ in range(max(1, ref.count)))
            continue
        sb = _statblock_for(session, ref.ref)
        if sb is not None:
            inst = enemy_from_statblock(sb)
            out.extend(inst for _ in range(max(1, ref.count)))
            continue
        try:
            ent = repo.get_character(ref.ref)
        except StateError as e:
            raise CombatError(
                f"enemy ref {ref.ref!r} is neither a template, a bestiary monster, nor an entity"
            ) from e
        out.append(enemy_from_character(ent))
    return out


# --- staging -------------------------------------------------------------

def stage_combat(
    request: EncounterRequest,
    repo: Repository,
    session,
    *,
    assessment: TurnAssessment | None = None,
    player_text: str = "",
    scratch_root: Path | None = None,
) -> StageOutcome:
    """Validate + stage a fight. A chosen non-combat exit resolves immediately
    (no Arena); otherwise the live party + resolved enemies are written to an
    encounter file and a `PendingCombat` is returned. `assessment`/`player_text`
    are the triggering turn's (carried so the post-combat report can be built)."""
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

    enemies = _resolve_enemies(request, repo, session)
    party = repo.party() or [repo.pc()]
    plan = build_encounter(party, enemies, request.terrain, name=request.kind.title() or "Encounter")

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
