"""Generate the SRD bestiary (content/srd/bestiary.json) from the machine-readable
5e-database 2014 dataset — a DETERMINISTIC parse, never an LLM transcription (the
CS4 lesson: agents garble stat tables; the source JSON is already authoritative).

Source: https://github.com/5e-bits/5e-database  (CC-BY-4.0 / OGL SRD 5.1 content)
        src/2014/en/5e-SRD-Monsters.json

Re-run:
    curl -sL https://raw.githubusercontent.com/5e-bits/5e-database/main/src/2014/en/5e-SRD-Monsters.json -o srd-monsters-raw.json
    python tools/gen_bestiary.py srd-monsters-raw.json oubliette/content/srd/bestiary.json

Each monster is mapped onto the enriched `StatBlock` schema (content/schemas.py).
Every action keeps BOTH the structured fields (attack_bonus/damage/damage_type — for
the combat app) AND the verbatim SRD prose `desc` (what the panel renders). The
top-level attack_bonus/damage carry one representative attack for the placeholder
auto-resolver. The loader/linter (load_ruleset) is the structural gate.
"""

from __future__ import annotations

import json
import sys

_ABILITY = {"str": "strength", "dex": "dexterity", "con": "constitution",
            "int": "intelligence", "wis": "wisdom", "cha": "charisma"}


def _ac(entry_list: list) -> tuple[int, str | None]:
    """First AC entry → (value, descriptor). 5e-db lists armor pieces, or marks the
    source as natural/dex/etc."""
    if not entry_list:
        return 10, None
    e = entry_list[0]
    value = e.get("value", 10)
    if e.get("armor"):
        return value, ", ".join(a["name"].lower() for a in e["armor"])
    if e.get("desc"):
        return value, e["desc"]
    if e.get("type") == "natural":
        return value, "natural armor"
    return value, None


def _speed(speed: dict) -> dict:
    """Coerce to {str: str}; `hover` is a bool in the source."""
    out = {}
    for k, v in speed.items():
        if isinstance(v, bool):
            if v:
                out[k] = "yes"
        else:
            out[k] = str(v)
    return out


def _proficiencies(profs: list) -> tuple[list, dict, dict]:
    """Split the combined proficiency list into proficient skills, their numeric
    bonuses, and saving-throw bonuses."""
    skills, skill_bonuses, saves = [], {}, {}
    for p in profs:
        idx = p["proficiency"]["index"]
        val = p.get("value")
        if idx.startswith("skill-"):
            name = idx[len("skill-"):]
            skills.append(name)
            if val is not None:
                skill_bonuses[name] = val
        elif idx.startswith("saving-throw-"):
            if val is not None:
                saves[idx[len("saving-throw-"):]] = val
    return skills, skill_bonuses, saves


def _usage_suffix(usage: dict | None) -> str:
    """Render the SRD '(Recharge 5-6)' / '(N/Day)' suffix onto an action name."""
    if not usage:
        return ""
    kind = usage.get("type")
    if kind == "recharge on roll":
        lo = usage.get("min_value", 6)
        return f" (Recharge {lo}-6)" if lo < 6 else " (Recharge 6)"
    if kind == "recharge after rest":
        return " (Recharges after a Short or Long Rest)"
    if kind == "per day":
        return f" ({usage.get('times', 1)}/Day)"
    return ""


def _primary_damage(damage: list) -> tuple[str | None, str | None]:
    """The first concrete damage component (dice, type index), if any."""
    for d in damage or []:
        if isinstance(d, dict) and d.get("damage_dice"):
            dt = d.get("damage_type") or {}
            return d["damage_dice"], dt.get("index")
    return None, None


def _action(a: dict) -> dict:
    """One action → an `Action` dict: structured fields for combat + verbatim prose."""
    act = {"name": a["name"] + _usage_suffix(a.get("usage")), "desc": a.get("desc", "")}
    if a.get("attack_bonus") is not None:
        act["attack_bonus"] = a["attack_bonus"]
    dice, dtype = _primary_damage(a.get("damage"))
    if dice:
        act["damage"] = dice
    if dtype:
        act["damage_type"] = dtype
    return act


def _primary_attack(actions: list) -> tuple[int, str]:
    """The combat-seam single attack: the first real weapon attack (skips Multiattack
    and save-only actions). Falls back to the schema defaults."""
    for a in actions:
        if a.get("attack_bonus") is not None:
            dice, _ = _primary_damage(a.get("damage"))
            if dice:
                return a["attack_bonus"], dice
    return 0, "1d4"


def map_monster(m: dict) -> dict:
    ac, ac_desc = _ac(m.get("armor_class", []))
    skills, skill_bonuses, saves = _proficiencies(m.get("proficiencies", []))
    actions = [_action(a) for a in m.get("actions", [])]
    atk, dmg = _primary_attack(m.get("actions", []))
    type_ = m.get("type", "")
    if m.get("subtype"):
        type_ = f"{type_} ({m['subtype']})"

    sb = {
        "id": m["index"].replace("-", "_"),
        "name": m["name"],
        "kind": "monster",
        "size": m.get("size"),
        "type": type_ or None,
        "alignment": m.get("alignment") or None,
        "cr": float(m["challenge_rating"]),
        "abilities": {k: m[v] for k, v in _ABILITY.items()},
        "hp": m["hit_points"],
        "hit_dice": m.get("hit_points_roll") or m.get("hit_dice"),
        "armor_class": ac,
        "ac_desc": ac_desc,
        "speed": _speed(m.get("speed", {})),
        "attack_bonus": atk,
        "damage": dmg,
        "saves": saves,
        "skills": skills,
        "skill_bonuses": skill_bonuses,
        "damage_vulnerabilities": m.get("damage_vulnerabilities", []),
        "damage_resistances": m.get("damage_resistances", []),
        "damage_immunities": m.get("damage_immunities", []),
        "condition_immunities": [c["index"] for c in m.get("condition_immunities", [])],
        "senses": {k: str(v) for k, v in m.get("senses", {}).items()},
        "languages": m.get("languages") or "—",
        "xp": m.get("xp", 0),
        "traits": [f"{sa['name']}{_usage_suffix(sa.get('usage'))}. {sa['desc']}"
                   for sa in m.get("special_abilities", [])],
        "actions": actions,
        "legendary_actions": [_action(a) for a in m.get("legendary_actions", [])],
        "reactions": [_action(a) for a in m.get("reactions", [])],
        "description": "",
        "srd_ref": m["index"],
    }
    # Drop empty optional containers so the file stays lean & diff-friendly.
    return {k: v for k, v in sb.items()
            if v not in ([], {}, None, "")
            or k in ("hp", "armor_class", "cr", "attack_bonus", "damage", "abilities")}


def main(src: str, dst: str) -> None:
    monsters = json.load(open(src, encoding="utf-8"))
    out = [map_monster(m) for m in monsters]
    out.sort(key=lambda s: (s["cr"], s["name"]))
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"wrote {len(out)} monsters -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
