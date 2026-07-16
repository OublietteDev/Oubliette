"""The Arena test bed (Forge v2.0, T1 — the proving ground).

A world author pits their creatures against a KNOWN quantity — the benchmark
party (fighter / cleric / rogue / wizard at a chosen level, generated once by
``tools/gen_benchmark_party.py`` through the real chargen + level-up engines)
— on any authored battlefield, in the real Arena window. Everything here is a
sandbox: no session, no event log, no story; the result is read, shown, and
discarded.

This module deliberately reuses the play app's staging pieces
(`enemy_from_statblock`, `build_encounter`, `_write_encounter_file`,
`run_arena`) but resolves pack paths against the CREATOR's packs root — a
custom ``OUBLIETTE_PACKS_ROOT`` still finds its rich monster files and battle
assets, which the story-side helpers hard-wire to the shipped content dir.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from ..content.loader import LoadedWorld
from ..state.models import Character, Item
from .arena_bridge import (PortraitDirs, battle_setting, build_encounter,
                           enemy_from_statblock)
from .arena_launch import (PendingCombat, _statblock_for, _write_encounter_file,
                           _CONTENT_ROOT)
from .boundary import CombatError
from .schemas import TerrainSpec

BENCHMARK_PATH = Path(__file__).parents[1] / "content" / "benchmark" / "party.json"
MAX_BENCH_LEVEL = 9
MAX_BENCH_SIZE = 4


@lru_cache(maxsize=1)
def _benchmark_data() -> dict:
    return json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))


def benchmark_roster() -> list[str]:
    return list(_benchmark_data()["roster"])


def benchmark_party(level: int, size: int) -> tuple[list[Character], list[Item]]:
    """The first `size` heroes of the roster at `level`, plus their gear as
    state Items (the catalog the Arena bridge derives AC/weapons from)."""
    if not 1 <= level <= MAX_BENCH_LEVEL:
        raise CombatError(f"benchmark level must be 1-{MAX_BENCH_LEVEL}, got {level}")
    if not 1 <= size <= MAX_BENCH_SIZE:
        raise CombatError(f"benchmark party size must be 1-{MAX_BENCH_SIZE}, got {size}")
    data = _benchmark_data()
    chars: list[Character] = []
    items: dict[str, Item] = {}
    for cls in data["roster"][:size]:
        entry = data["levels"][cls]
        chars.append(Character(**entry["levels"][str(level)]))
        for raw in entry["items"]:
            it = Item(**raw)
            items.setdefault(it.id, it)
    return chars, list(items.values())


def stage_test_fight(
    world: LoadedWorld,
    pack_dir: Path,
    *,
    enemies: list[tuple[str, int]],          # (statblock ref, count)
    party_level: int,
    party_size: int,
    allies: list[str] = (),                  # statblock refs joining the player side
    place_id: str | None = None,             # a Place with an authored battle map
    watch: bool = False,                     # the AI plays the party too
    scratch_root: Path | None = None,
) -> PendingCombat:
    """Stage a sandbox fight and return the PendingCombat (encounter file
    written, result path chosen) — the caller runs `arena_launch.run_arena`.
    Raises CombatError on an unknown creature ref or empty enemy side."""
    if not enemies:
        raise CombatError("a test fight needs at least one enemy")

    # The tolerant statblock matcher only reads these two fields off "session".
    lookup = SimpleNamespace(statblocks=world.statblocks, ruleset=world.ruleset)
    ai_profiles = {p.id: p for p in world.ai_profiles or ()}
    monster_dir = pack_dir / "monsters"
    portraits = PortraitDirs(pc=pack_dir / "portraits",
                             pack=pack_dir / "portraits",
                             srd=_CONTENT_ROOT / "srd" / "portraits")

    def kit_for(ref: str):
        sb = _statblock_for(lookup, ref)
        if sb is None:
            raise CombatError(f"{ref!r} is not a creature in this world or the SRD")
        return sb, enemy_from_statblock(sb, portraits, ai_profiles=ai_profiles,
                                        pack_monster_dir=monster_dir)

    enemy_instances = []
    for ref, count in enemies:
        _, inst = kit_for(ref)
        enemy_instances.extend(inst for _ in range(max(1, count)))

    party, _items = benchmark_party(party_level, party_size)

    # Creature allies ride the companion-kit path: a sheetless party member
    # whose kit maps by id fights its full stat block, player-controlled.
    kits: dict = {}
    for n, ref in enumerate(allies or ()):
        sb, inst = kit_for(ref)
        ally = Character(id=f"testbed_ally_{n}", name=sb.name, kind="npc",
                         hp=sb.hp, max_hp=sb.hp)
        party.append(ally)
        kits[ally.id] = inst.creature

    battle = None
    if place_id:
        node = (world.places or {}).get(place_id)
        authored = getattr(node, "battle", None)
        if authored is None:
            raise CombatError(f"place {place_id!r} has no authored battlefield")
        battle = battle_setting(authored, pack_dir)

    plan = build_encounter(party, enemy_instances, TerrainSpec(),
                           name="Test Fight",
                           catalog=world.mechanics_catalog or None,
                           ruleset=world.ruleset,
                           portraits=portraits,
                           battle=battle,
                           companion_kits=kits,
                           house_rules=world.house_rules)
    if watch:
        # The built-in AI-takeover hook: the whole player team plays itself.
        plan.encounter.use_ai_for_allies = True

    import tempfile
    scratch_dir = Path(tempfile.mkdtemp(prefix="oubliette-testbed-", dir=scratch_root))
    encounter_path = scratch_dir / "encounter.json"
    _write_encounter_file(plan.encounter, scratch_dir, encounter_path)
    return PendingCombat(plan=plan, encounter_path=encounter_path,
                         result_path=scratch_dir / "result.json",
                         scratch_dir=scratch_dir)
