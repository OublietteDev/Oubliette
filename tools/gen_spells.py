"""Generate the Arena spell-action library (arena/data/spells/srd/) from the
machine-readable 5e-database 2014 dataset — a DETERMINISTIC parse, never an LLM
transcription (the CS4 lesson), the playbook's fifth use.

Source: https://github.com/5e-bits/5e-database  (CC-BY-4.0 / OGL SRD 5.1 content)
        src/2014/en/5e-SRD-Spells.json

Re-run:
    curl -sL https://raw.githubusercontent.com/5e-bits/5e-database/main/src/2014/en/5e-SRD-Spells.json -o srd-spells-raw.json
    python tools/gen_spells.py srd-spells-raw.json arena/data/spells/srd

Each emitted file is ONE Arena `Action` (validated against the model on write),
keyed by the Oubliette spell id (index with underscores) so the bridge can map a
character sheet's spell lists straight onto files. Only the pattern-extractable
combat families are emitted (D-COMBAT-2 — the cap is the design, not a failure):

  - spell-attack damage  (attack_type + damage)          e.g. Fire Bolt, Guiding Bolt
  - save-based damage    (dc + damage [+ area_of_effect]) e.g. Fireball, Sacred Flame
  - healing              (heal_at_slot_level)             e.g. Cure Wounds

Everything else is skipped with a reason into `_manifest.json` (control/buff
spells carry no structured mechanics in the source; rituals/long casts have no
combat shape; auto-hit and zone/duration spells need primitives the engine
doesn't route from data yet — Magic Missile is the famous one).

BRIDGE-BAKED FIELDS (the library is consumed by oubliette's arena_bridge, which
knows the caster's sheet — same philosophy as the +X gear bake in B3):
  - `Attack.ability` is emitted as a placeholder; the bridge rewrites it to the
    caster's spellcasting ability.
  - `SavingThrowEffect.dc` is emitted as null; the bridge stamps the caster's
    spell save DC (the engine's data-side fallback is a flat 10).
  - healing strings may contain the literal token `MOD` ("1d8+MOD"); the bridge
    substitutes the caster's spellcasting modifier.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.models.actions import Action  # noqa: E402  (validation gate)

_OK_TIMES = {"1 action": "action", "1 bonus action": "bonus_action",
             "1 reaction": "reaction"}
_ABILITY_LONG = {"str": "strength", "dex": "dexterity", "con": "constitution",
                 "int": "intelligence", "wis": "wisdom", "cha": "charisma"}
_AOE_TARGET = {"sphere": "area_sphere", "cube": "area_cube", "cone": "area_cone",
               "line": "area_line", "cylinder": "area_sphere"}
# Attack.ability placeholder — the bridge rewrites it to the caster's real
# spellcasting ability before the action ever reaches the engine.
_PLACEHOLDER_ABILITY = "intelligence"

_DICE_RE = re.compile(r"^\s*(\d+)d(\d+)\s*(?:\+\s*(\d+|MOD))?\s*$")


def _parse_dice(expr: str) -> tuple[int, int, str | None] | None:
    """ "8d6" / "3d4 + 3" / "1d8 + MOD" → (count, size, flat|"MOD"|None)."""
    m = _DICE_RE.match(expr or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), m.group(3)


def _dice_str(count: int, size: int, flat: str | None) -> str:
    out = f"{count}d{size}"
    if flat:
        out += f"+{flat}"
    return out


def _range_feet(text: str) -> int:
    """SRD range text → feet. Touch fights at reach; Self anchors AoE on the caster."""
    t = (text or "").strip().lower()
    if t == "touch":
        return 5
    if t == "self":
        return 0
    m = re.match(r"^(\d+)\s*(?:feet|foot|ft)", t)
    return int(m.group(1)) if m else 30


def _upcast_delta(rows: dict[str, str], base_level: int) -> str | None:
    """Per-slot-step bonus dice from the slot-level table ("8d6"→"9d6" = "1d6").
    None when rows are missing, unparseable, or don't step uniformly."""
    base = _parse_dice(rows.get(str(base_level), ""))
    nxt = _parse_dice(rows.get(str(base_level + 1), ""))
    if base is None or nxt is None or base[1] != nxt[1]:
        return None
    step = nxt[0] - base[0]
    if step <= 0:
        return None
    # verify uniformity across the table (non-uniform scalers get no upcast)
    for lvl in range(base_level, 10):
        row = _parse_dice(rows.get(str(lvl), ""))
        if row is None:
            continue
        if row[0] != base[0] + step * (lvl - base_level) or row[1] != base[1]:
            return None
    return f"{step}d{base[1]}"


def map_spell(s: dict) -> tuple[dict | None, str | None]:
    """One source spell → (Action dict, None) or (None, skip_reason)."""
    action_type = _OK_TIMES.get(s.get("casting_time", ""))
    if action_type is None:
        return None, f"casting time {s.get('casting_time')!r} has no combat shape"

    level = int(s.get("level", 0))
    dmg = s.get("damage") or {}
    dmg_rows = dmg.get("damage_at_slot_level") or {}
    cantrip_rows = dmg.get("damage_at_character_level") or {}
    heal_rows = s.get("heal_at_slot_level") or {}
    dc = s.get("dc") or {}
    aoe = s.get("area_of_effect") or {}

    is_cantrip = level == 0
    base_dice = (cantrip_rows.get("1") if is_cantrip
                 else dmg_rows.get(str(level)))
    has_damage = bool(base_dice)
    dtype = ((dmg.get("damage_type") or {}).get("index") or "").lower()

    desc_list = s.get("desc") or []
    description = (desc_list[0] if desc_list else s["name"])[:300]

    base: dict = {
        "name": s["name"],
        "description": description,
        "action_type": action_type,
        "range": _range_feet(s.get("range", "")),
        "requires_concentration": bool(s.get("concentration")),
        "ai_priority": 6,
    }
    if not is_cantrip:
        base["spell_level"] = level
        base["resource_cost"] = {f"spell_slot_{level}": 1}
    else:
        base["spell_level"] = 0
        base["cantrip_scaling"] = True

    if aoe:
        target = _AOE_TARGET.get((aoe.get("type") or "").lower())
        if target is None:
            return None, f"area type {aoe.get('type')!r} not expressible"
        base["target_type"] = target
        base["area_size"] = int(aoe.get("size", 5))

    # --- healing -----------------------------------------------------------
    if heal_rows:
        row = heal_rows.get(str(max(level, 1)), "")
        parsed = _parse_dice(row)
        if parsed is not None:
            base["healing"] = _dice_str(*parsed)      # may carry literal +MOD
        elif row.strip().isdigit():
            base["healing"] = row.strip()             # flat heal (Heal = 70)
        else:
            return None, "healing row unparseable"
        base.setdefault("target_type", "one_ally")
        delta = _upcast_delta(
            {k: v.replace(" + MOD", "").replace("+MOD", "") for k, v in heal_rows.items()},
            max(level, 1))
        if delta:
            base["upcast_healing_dice"] = delta
        base["ai_priority"] = 7
        return base, None

    # --- spell-attack damage -------------------------------------------------
    if s.get("attack_type") and has_damage:
        parsed = _parse_dice(base_dice)
        if parsed is None or parsed[2] == "MOD":
            return None, "damage row unparseable"
        if not dtype:
            return None, "attack spell without a damage type"
        base.setdefault("target_type", "one_creature")
        base["attack"] = {
            "name": s["name"],
            "attack_type": f"{s['attack_type'].lower()}_spell",
            "ability": _PLACEHOLDER_ABILITY,           # bridge rewrites
            "reach": base["range"] if s["attack_type"].lower() == "melee" else 5,
            "range_normal": base["range"] if s["attack_type"].lower() == "ranged" else None,
            "damage": [{"dice": _dice_str(parsed[0], parsed[1], None),
                        "damage_type": dtype,
                        "bonus": int(parsed[2]) if parsed[2] and parsed[2] != "MOD" else 0}],
        }
        if not is_cantrip:
            delta = _upcast_delta(dmg_rows, level)
            if delta:
                base["upcast_damage_dice"] = delta
        return base, None

    # --- save-based damage ---------------------------------------------------
    if dc and has_damage:
        ability = ((dc.get("dc_type") or {}).get("index") or "").lower()
        success = (dc.get("dc_success") or "none").lower()
        if ability not in _ABILITY_LONG:
            return None, f"save ability {ability!r} unknown"
        if success not in ("half", "none"):
            return None, f"save success rule {success!r} not expressible"
        parsed = _parse_dice(base_dice)
        if parsed is None or parsed[2] == "MOD":
            return None, "damage row unparseable"
        if not dtype:
            return None, "save spell without a damage type"
        base.setdefault("target_type", "one_creature")
        base["saving_throw"] = {
            "ability": _ABILITY_LONG[ability],
            "dc": None,                                # bridge stamps caster DC
            "damage_on_fail": [{"dice": _dice_str(parsed[0], parsed[1], None),
                                "damage_type": dtype,
                                "bonus": int(parsed[2]) if parsed[2] and parsed[2] != "MOD" else 0}],
            "damage_on_success": success,
        }
        if not is_cantrip:
            delta = _upcast_delta(dmg_rows, level)
            if delta:
                base["upcast_damage_dice"] = delta
        return base, None

    if has_damage:
        return None, "auto-hit / zone / rider damage — no engine route from data yet"
    return None, "no structured combat mechanics in the source (control/buff/utility)"


def main(src: str, out_dir: str) -> int:
    spells = json.loads(Path(src).read_text(encoding="utf-8"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    generated: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for s in spells:
        spell_id = s["index"].replace("-", "_")
        mapped, reason = map_spell(s)
        if mapped is None:
            skipped[spell_id] = reason or "unknown"
            continue
        # Validation gate — every emitted file loads through the Arena's model.
        # (The literal MOD token in healing is bridge-substituted before play but
        # must already validate as a plain string here.)
        Action.model_validate(mapped)
        (out / f"{spell_id}.json").write_text(
            json.dumps(mapped, indent=2), encoding="utf-8")
        generated[spell_id] = s["name"]

    (out / "_manifest.json").write_text(
        json.dumps({"generated": generated, "skipped": skipped}, indent=2),
        encoding="utf-8")
    print(f"generated {len(generated)} spell actions, skipped {len(skipped)} "
          f"(see _manifest.json)")
    by_reason: dict[str, int] = {}
    for r in skipped.values():
        by_reason[r] = by_reason.get(r, 0) + 1
    for r, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        print(f"  skipped {n:3d}: {r}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python tools/gen_spells.py <srd-spells-raw.json> <out-dir>",
              file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
