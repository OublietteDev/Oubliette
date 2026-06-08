"""Load the SRD ruleset: parse it whole, lint the cross-references, hand back a
`Ruleset` (design doc §2.1/§3).

The ruleset is the GLOBAL system layer (classes/races/backgrounds/spells/feats/
conditions/equipment), separate from world packs and shared by every campaign.
Same validate-whole-or-fail discipline as the pack loader: a `RulesetValidationError`
aggregates every problem. Kept free of any import from `loader.py` so `loader`
can depend on this module without a cycle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ..enums import Skill
from .srd_schemas import (Background, CharClass, Condition, Feat, Race, Spell,
                          SrdEquipment, Subclass, Subrace)

_SRD_ROOT = Path(__file__).parent / "srd"
_VALID_SKILLS = {s.value for s in Skill}


class RulesetValidationError(Exception):
    """The SRD ruleset failed schema and/or cross-reference validation. Carries the
    full aggregated list of problems (`.errors`)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        body = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"SRD ruleset failed validation:\n{body}")


@dataclass(frozen=True)
class Ruleset:
    """The loaded SRD: everything chargen, the sheet, and the derivation engine
    read from. Each map is {id: model}."""

    srd_version: str
    classes: dict[str, CharClass] = field(default_factory=dict)
    subclasses: dict[str, Subclass] = field(default_factory=dict)
    races: dict[str, Race] = field(default_factory=dict)
    subraces: dict[str, Subrace] = field(default_factory=dict)
    backgrounds: dict[str, Background] = field(default_factory=dict)
    spells: dict[str, Spell] = field(default_factory=dict)
    feats: dict[str, Feat] = field(default_factory=dict)
    conditions: dict[str, Condition] = field(default_factory=dict)
    equipment: dict[str, SrdEquipment] = field(default_factory=dict)

    def subclasses_for(self, class_id: str) -> list[Subclass]:
        return [s for s in self.subclasses.values() if s.parent == class_id]

    def subraces_for(self, race_id: str) -> list[Subrace]:
        return [s for s in self.subraces.values() if s.race == race_id]

    def spells_for(self, class_id: str) -> list[Spell]:
        return [s for s in self.spells.values() if class_id in s.classes]


# --- file reading (standalone — no dependency on loader.py) -------------------
def _read_json(path: Path, filename: str, errors: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None                      # optional file
    except json.JSONDecodeError as e:
        errors.append(f"{filename}: invalid JSON ({e})")
        return None


def _format_errors(e: Exception) -> list[str]:
    if isinstance(e, ValidationError):
        out = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"]) or "(root)"
            out.append(f"{loc}: {err['msg']}")
        return out
    return [str(e)]


def _parse_list(root: Path, filename: str, model: type[BaseModel],
                errors: list[str]) -> list:
    data = _read_json(root / filename, filename, errors)
    if data is None:
        return []
    if not isinstance(data, list):
        errors.append(f"{filename}: expected a JSON array")
        return []
    out = []
    for i, raw in enumerate(data):
        ident = raw.get("id", f"index {i}") if isinstance(raw, dict) else f"index {i}"
        try:
            out.append(model(**raw))
        except (ValidationError, TypeError) as e:
            for line in _format_errors(e):
                errors.append(f"{filename}: {ident}: {line}")
    return out


def _dup_ids(entities: list, type_name: str, errors: list[str]) -> None:
    seen: set[str] = set()
    for ent in entities:
        if ent.id in seen:
            errors.append(f"{type_name}: duplicate id {ent.id!r}")
        seen.add(ent.id)


# --- cross-reference linter ---------------------------------------------------
def _lint(classes, subclasses, races, subraces, backgrounds, spells, feats,
          conditions, equipment, errors: list[str]) -> None:
    for ents, name in [(classes, "classes"), (subclasses, "subclasses"),
                       (races, "races"), (subraces, "subraces"),
                       (backgrounds, "backgrounds"), (spells, "spells"),
                       (feats, "feats"), (conditions, "conditions"),
                       (equipment, "equipment")]:
        _dup_ids(ents, name, errors)

    class_ids = {c.id for c in classes}
    race_ids = {r.id for r in races}
    equip_ids = {e.id for e in equipment}

    def need_equip(ref: str, where: str) -> None:
        if ref not in equip_ids:
            errors.append(f"{where} references unknown equipment {ref!r}")

    for c in classes:
        for sk in c.skill_choices.from_:
            if sk not in _VALID_SKILLS:
                errors.append(f"classes: {c.id}.skill_choices lists unknown skill {sk!r}")
        for g in c.starting_equipment.fixed:
            need_equip(g.item, f"classes: {c.id}.starting_equipment")
        for ch in c.starting_equipment.choices:
            for opt in ch.options:
                for g in opt:
                    need_equip(g.item, f"classes: {c.id}.starting_equipment")

    for s in subclasses:
        if s.parent not in class_ids:
            errors.append(f"subclasses: {s.id}.parent references unknown class {s.parent!r}")

    for s in subraces:
        if s.race not in race_ids:
            errors.append(f"subraces: {s.id}.race references unknown race {s.race!r}")

    for b in backgrounds:
        for sk in b.skill_proficiencies:
            if sk not in _VALID_SKILLS:
                errors.append(f"backgrounds: {b.id} lists unknown skill {sk!r}")
        for g in b.equipment:
            need_equip(g.item, f"backgrounds: {b.id}.equipment")

    for sp in spells:
        for cid in sp.classes:
            if cid not in class_ids:
                errors.append(f"spells: {sp.id}.classes references unknown class {cid!r}")


# --- public API ---------------------------------------------------------------
def load_ruleset(srd_root: Path | None = None) -> Ruleset:
    """Read `srd_root/*.json` -> validate (schema + linter) -> build the `Ruleset`.
    Raises `RulesetValidationError` (aggregated) on any problem; never loads partial."""
    root = srd_root or _SRD_ROOT
    errors: list[str] = []

    manifest = _read_json(root / "ruleset.json", "ruleset.json", errors) or {}
    if not isinstance(manifest, dict):
        errors.append("ruleset.json: expected an object")
        manifest = {}
    srd_version = str(manifest.get("srd_version", "5.1"))

    classes = _parse_list(root, "classes.json", CharClass, errors)
    subclasses = _parse_list(root, "subclasses.json", Subclass, errors)
    races = _parse_list(root, "races.json", Race, errors)
    subraces = _parse_list(root, "subraces.json", Subrace, errors)
    backgrounds = _parse_list(root, "backgrounds.json", Background, errors)
    spells = _parse_list(root, "spells.json", Spell, errors)
    feats = _parse_list(root, "feats.json", Feat, errors)
    conditions = _parse_list(root, "conditions.json", Condition, errors)
    equipment = _parse_list(root, "equipment.json", SrdEquipment, errors)

    _lint(classes, subclasses, races, subraces, backgrounds, spells, feats,
          conditions, equipment, errors)

    if errors:
        raise RulesetValidationError(errors)

    return Ruleset(
        srd_version=srd_version,
        classes={c.id: c for c in classes},
        subclasses={s.id: s for s in subclasses},
        races={r.id: r for r in races},
        subraces={s.id: s for s in subraces},
        backgrounds={b.id: b for b in backgrounds},
        spells={s.id: s for s in spells},
        feats={f.id: f for f in feats},
        conditions={c.id: c for c in conditions},
        equipment={e.id: e for e in equipment},
    )
