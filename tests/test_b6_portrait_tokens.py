"""B6 — portraits as Arena battlefield tokens.

The Arena already renders `Creature.token_image` (circle-clipped tokens,
polygon-clipped for Large+); B6 is the bridge pointing that field at the
right file when a fight is staged:

  - monsters: the statblock's `portrait` filename or `<id>.png`, pack dir
    first then the SRD fleet — the same convention the bestiary panel serves,
    but matched case-insensitively so `Awakened_Shrub.png` answers for
    `awakened_shrub` on any OS;
  - party PCs (and persistent NPC foes): the A3 uploaded-portrait filename
    under the campaign's character-portraits/ dir.

Missing dirs or files leave token_image unset — the colored-circle fallback.
"""

from __future__ import annotations

import json
from pathlib import Path

from arena.models.encounter import Encounter

from oubliette.combat import arena_launch
from oubliette.combat.arena_bridge import (
    PortraitDirs,
    _token_image,
    build_encounter,
    enemy_from_statblock,
)
from oubliette.combat.arena_launch import stage_combat
from oubliette.combat.schemas import EncounterRequest, EnemyRef, TerrainSpec
from oubliette.content.ruleset import load_ruleset
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.session import Session

RS = load_ruleset()


def _session() -> Session:
    return Session.open(InMemoryEventStore())


def _dirs(tmp_path) -> PortraitDirs:
    pc = tmp_path / "character-portraits"
    pack = tmp_path / "pack-portraits"
    srd = tmp_path / "srd-portraits"
    for d in (pc, pack, srd):
        d.mkdir()
    return PortraitDirs(pc=pc, pack=pack, srd=srd)


def _png(directory, name: str) -> None:
    (directory / name).write_bytes(b"\x89PNG fake")


# --- the resolver ----------------------------------------------------------

def test_lookup_is_case_insensitive_for_the_srd_fleet(tmp_path):
    """OublietteDev's `Awakened_Shrub.png` must answer for the id `awakened_shrub`
    by matching, not by relying on Windows' case-insensitive filesystem."""
    dirs = _dirs(tmp_path)
    _png(dirs.srd, "Awakened_Shrub.png")
    art = _token_image([dirs.pack, dirs.srd], ["awakened_shrub.png"])
    assert art is not None and art.endswith("Awakened_Shrub.png")


def test_pack_dir_takes_precedence_over_srd(tmp_path):
    dirs = _dirs(tmp_path)
    _png(dirs.pack, "wolf.png")
    _png(dirs.srd, "wolf.png")
    art = _token_image([dirs.pack, dirs.srd], ["wolf.png"])
    assert "pack-portraits" in art


def test_traversal_candidates_are_rejected(tmp_path):
    dirs = _dirs(tmp_path)
    assert _token_image([dirs.pc], ["..\\evil.png"]) is None
    assert _token_image([dirs.pc], ["../evil.png"]) is None
    assert _token_image([dirs.pc], [None]) is None


def test_missing_dirs_and_files_resolve_to_none(tmp_path):
    dirs = PortraitDirs(pc=tmp_path / "nope", pack=None, srd=None)
    assert _token_image([dirs.pc, dirs.pack, dirs.srd], ["wolf.png"]) is None


# --- monsters ----------------------------------------------------------------

def test_bestiary_monster_gets_its_portrait_as_token_art(tmp_path):
    dirs = _dirs(tmp_path)
    _png(dirs.srd, "Wolf.png")                       # fleet naming, id is "wolf"
    inst = enemy_from_statblock(RS.bestiary["wolf"], dirs)
    assert inst.creature.token_image is not None
    assert inst.creature.token_image.endswith("Wolf.png")


def test_statblock_portrait_field_wins_over_id(tmp_path):
    dirs = _dirs(tmp_path)
    _png(dirs.pack, "scarred_alpha.png")
    _png(dirs.srd, "wolf.png")
    sb = RS.bestiary["wolf"].model_copy(update={"portrait": "scarred_alpha.png"})
    inst = enemy_from_statblock(sb, dirs)
    assert inst.creature.token_image.endswith("scarred_alpha.png")


def test_no_art_on_disk_leaves_the_circle_fallback(tmp_path):
    inst = enemy_from_statblock(RS.bestiary["wolf"], _dirs(tmp_path))
    assert inst.creature.token_image is None


# --- party PCs ----------------------------------------------------------------

def test_pc_uploaded_portrait_becomes_token_art(tmp_path):
    dirs = _dirs(tmp_path)
    s = _session()
    pc = s.repo.pc()
    s.repo.set_portrait(pc.id, "hero.png")
    _png(dirs.pc, "hero.png")

    plan = build_encounter([s.repo.pc()], [], TerrainSpec(), portraits=dirs)
    (entry,) = plan.encounter.combatants
    assert entry.creature_data.token_image.endswith("hero.png")


def test_pc_without_a_portrait_keeps_the_fallback(tmp_path):
    s = _session()
    plan = build_encounter([s.repo.pc()], [], TerrainSpec(), portraits=_dirs(tmp_path))
    (entry,) = plan.encounter.combatants
    assert entry.creature_data.token_image is None


# --- end to end through staging ------------------------------------------------

def test_token_art_survives_the_externalized_encounter_round_trip(tmp_path):
    """stage_combat writes each creature to its own JSON in the scratch dir;
    the absolute token_image path must ride along and load back through the
    Arena's own Encounter model + creature files."""
    dirs = _dirs(tmp_path)
    _png(dirs.srd, "Goblin.png")
    _png(dirs.pc, "hero.png")

    s = _session()
    s.repo.set_portrait(s.repo.pc().id, "hero.png")
    req = EncounterRequest(kind="ambush", enemies=[EnemyRef(ref="goblin", count=2)],
                           terrain=TerrainSpec())
    pending = stage_combat(req, s.repo, s, portraits=dirs).pending

    enc = Encounter.model_validate(
        json.loads(pending.encounter_path.read_text("utf-8")))
    arts = {}
    for entry in enc.combatants:
        creature = json.loads(Path(entry.creature_id).read_text("utf-8"))
        arts[entry.team] = arts.get(entry.team, [])
        arts[entry.team].append(creature.get("token_image"))

    assert all(a and a.endswith("hero.png") for a in arts["player"])
    assert all(a and a.endswith("Goblin.png") for a in arts["enemy"])
    arena_launch.cleanup(pending)


# --- spawn placement respects footprints ----------------------------------------

def test_big_monsters_all_spawn_on_grid_without_overlap():
    """Regression: naive one-hex column spacing collided Large+ footprints —
    the engine's place_creature refused the overlap and the combatant spawned
    OFF-GRID (position=None). A mixed menagerie must land cleanly."""
    from pathlib import Path as P

    from arena.combat.manager import CombatManager
    from arena.grid.footprint import get_occupied_hexes

    s = _session()
    req = EncounterRequest(
        kind="brawl",
        enemies=[EnemyRef(ref="ogre", count=2),
                 EnemyRef(ref="adult red dragon"),    # huge: 7 hexes
                 EnemyRef(ref="frog")],               # tiny: 1 hex
        terrain=TerrainSpec(),
    )
    pending = stage_combat(req, s.repo, s).pending
    enc = Encounter.model_validate(
        json.loads(pending.encounter_path.read_text("utf-8")))
    cm = CombatManager()
    cm.load_encounter(enc, P("."))

    claimed: set[tuple[int, int]] = set()
    for cid, c in cm.combatants.items():
        assert c.position is not None, f"{cid} was never placed on the grid"
        hexes = {(h.q, h.r) for h in get_occupied_hexes(c.position, c.creature.size)}
        assert not (hexes & claimed), f"{cid} spawned overlapping another footprint"
        claimed |= hexes
    arena_launch.cleanup(pending)
