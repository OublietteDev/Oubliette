"""Bind a monster's spell-list prose to castable spell Actions.

Most SRD monster stat blocks carry their spellcasting as a *prose blob* inside a
``special_abilities`` Feature — e.g. the Mage's::

    The mage is a 9th-level spellcaster ... (spell save DC 14, +6 to hit ...).
    - Cantrips (at will): fire bolt, light, mage hand, prestidigitation
    - 3rd level (3 slots): counterspell, fireball, fly

The combat AI only ever scores entries in ``actions`` / ``bonus_actions`` /
``reactions``, so spells trapped in prose are invisible: a Mage stabs with its
dagger instead of casting Fireball.

This module parses that prose, looks each named spell up in the shared spell
library (``arena/data/spells/srd/``), and emits a baked spell Action carrying the
monster's own save DC. The spell becomes scorable and castable through the exact
machinery the player's spells (and the hand-authored ``mage.json``) already use —
no engine changes.

Spells absent from the library are skipped and reported. In practice those are
the non-combat utility spells (detect magic, light, tongues, scrying, …) a
monster would never spend a turn casting in a fight.

Known approximations (consistent with the hand-authored caster monsters):
  * leveled spells get an independent ``uses_per_rest`` = slots at that level,
    rather than a shared per-level slot pool;
  * cantrips keep their library damage dice (no per-caster-level scaling).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from arena.paths import DATA_DIR

SPELLS_DIR = DATA_DIR / "spells" / "srd"


# ── Name normalisation ───────────────────────────────────────────────


def _normalize(name: str) -> str:
    """Canonicalise a spell name to a library key: lowercase, drop apostrophes,
    collapse any run of non-alphanumerics to a single underscore."""
    s = name.strip().lower()
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def load_spell_library(spells_dir: Path | None = None) -> dict[str, dict]:
    """Load the spell library as ``normalized name -> spell-action dict``.

    Keys come from both the filename stem and the spell's ``name`` field so a
    lookup succeeds regardless of which the prose matches.
    """
    spells_dir = spells_dir or SPELLS_DIR
    library: dict[str, dict] = {}
    for path in sorted(spells_dir.glob("*.json")):
        if path.name.startswith("_"):  # _manifest.json and friends
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        library[_normalize(path.stem)] = data
        name = data.get("name")
        if name:
            library.setdefault(_normalize(name), data)
    return library


# ── Prose parsing ────────────────────────────────────────────────────

# A single parsed spell-list line: the spells it names and how many times per
# rest each may be cast (None = at-will / cantrip, unlimited).
_BULLET = re.compile(r"^\s*[-*•]?\s*")
_SLOT_LINE = re.compile(r"^(\d+)(?:st|nd|rd|th)\s+level\s*\(\s*(\d+)\s*slots?\s*\)\s*:(.*)$", re.I)
_PERDAY_LINE = re.compile(r"^(\d+)\s*/\s*day(?:\s+each)?\s*:(.*)$", re.I)
_ATWILL_LINE = re.compile(r"^(?:cantrips?\s*\(at will\)|at will)\s*:(.*)$", re.I)


def _split_spell_names(segment: str) -> list[str]:
    """Split the comma-separated spell tail of a list line into clean names.

    Drops parentheticals ("conjure elemental (fire elemental only)" -> "conjure
    elemental") and ignores empty fragments."""
    names: list[str] = []
    for tok in segment.split(","):
        tok = re.sub(r"\(.*?\)", "", tok)  # strip "(...)" notes
        tok = tok.strip().strip(".")
        if tok:
            names.append(tok)
    return names


def parse_spellcasting(desc: str) -> dict:
    """Parse a Spellcasting / Innate Spellcasting description.

    Returns ``{"dc": int|None, "attack_bonus": int|None, "spells": [(name, uses)]}``
    where ``uses`` is the per-rest cap (None = unlimited / at-will)."""
    dc_m = re.search(r"save\s+DC\s+(\d+)", desc, re.I)
    atk_m = re.search(r"([+-]\d+)\s+to\s+hit", desc, re.I)
    dc = int(dc_m.group(1)) if dc_m else None
    attack_bonus = int(atk_m.group(1)) if atk_m else None

    spells: list[tuple[str, int | None]] = []
    for raw in desc.splitlines():
        line = _BULLET.sub("", raw).strip()
        if not line:
            continue
        uses: int | None
        m = _SLOT_LINE.match(line)
        if m:
            uses, tail = int(m.group(2)), m.group(3)
        elif (m := _PERDAY_LINE.match(line)):
            uses, tail = int(m.group(1)), m.group(2)
        elif (m := _ATWILL_LINE.match(line)):
            uses, tail = None, m.group(1)
        else:
            continue
        for name in _split_spell_names(tail):
            spells.append((name, uses))
    return {"dc": dc, "attack_bonus": attack_bonus, "spells": spells}


# ── Action building ──────────────────────────────────────────────────


def _build_action(lib_spell: dict, uses: int | None, dc: int | None) -> dict:
    """Turn a library spell dict into a baked monster spell Action."""
    action = copy.deepcopy(lib_spell)
    action.setdefault("action_type", "action")

    # The monster's own save DC owns the number — the library leaves it null so
    # each caster stamps its own (a Mage's Fireball is DC 14, a Lich's is higher).
    st = action.get("saving_throw")
    if isinstance(st, dict) and dc is not None:
        st["dc"] = dc

    # Spell slots become an independent per-rest budget; the engine reads
    # uses_per_rest, not a monster spell-slot pool, so drop resource_cost.
    action.pop("resource_cost", None)
    if uses is not None:
        action["uses_per_rest"] = uses
    else:
        action.pop("uses_per_rest", None)  # at-will / cantrip: unlimited

    # Sensible AI gates, mirroring the hand-authored caster monsters, so a freshly
    # bound spell doesn't get spammed:
    #   * a self-teleport (Misty Step) is an ESCAPE tool — only when in melee,
    #     otherwise a ranged caster blinks away every single turn;
    #   * a damaging area spell shouldn't be wasted on a lone target.
    is_self_teleport = (
        action.get("teleport_range") or action.get("teleport_self")
    ) and action.get("target_type") == "self"
    if "ai_use_condition" not in action:
        if is_self_teleport:
            action["ai_use_condition"] = "is_in_melee"
        elif str(action.get("target_type", "")).startswith("area"):
            action["ai_use_condition"] = "enemies_in_range >= 2"

    return action


def build_spell_actions(
    desc: str, library: dict[str, dict]
) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    """From a spellcasting description, build baked spell Actions.

    Returns ``(actions, bonus_actions, reactions, skipped)`` — routed by each
    spell's ``action_type`` — plus the list of spell names not in the library.
    """
    parsed = parse_spellcasting(desc)
    dc = parsed["dc"]
    actions: list[dict] = []
    bonus_actions: list[dict] = []
    reactions: list[dict] = []
    skipped: list[str] = []
    seen: set[str] = set()

    for name, uses in parsed["spells"]:
        key = _normalize(name)
        if key in seen:
            continue
        seen.add(key)
        lib_spell = library.get(key)
        if lib_spell is None:
            skipped.append(name)
            continue
        action = _build_action(lib_spell, uses, dc)
        atype = action.get("action_type", "action")
        if atype == "bonus_action":
            bonus_actions.append(action)
        elif atype == "reaction":
            reactions.append(action)
        else:
            actions.append(action)
    return actions, bonus_actions, reactions, skipped


def hydrate_monster_spells(monster: dict, library: dict[str, dict]) -> dict:
    """Append baked spell Actions to a monster dict (mutates and returns it).

    Looks for a ``Spellcasting`` or ``Innate Spellcasting`` special ability,
    binds its spells, and merges them into ``actions`` / ``bonus_actions`` /
    ``reactions`` (skipping any whose name a creature already defines). Returns a
    summary: ``{"added": int, "skipped": [names]}``. A no-op for non-casters.
    """
    desc = None
    for sa in monster.get("special_abilities", []):
        if "Spellcasting" in sa.get("name", ""):
            desc = sa.get("description", "")
            break
    if not desc:
        return {"added": 0, "skipped": []}

    actions, bonus_actions, reactions, skipped = build_spell_actions(desc, library)

    def _merge(target_key: str, new: list[dict]) -> int:
        existing = monster.setdefault(target_key, [])
        have = {_normalize(a.get("name", "")) for a in existing}
        added = 0
        for a in new:
            if _normalize(a.get("name", "")) in have:
                continue
            existing.append(a)
            added += 1
        return added

    added = (
        _merge("actions", actions)
        + _merge("bonus_actions", bonus_actions)
        + _merge("reactions", reactions)
    )
    return {"added": added, "skipped": skipped}
