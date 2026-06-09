"""Generate Arena monster files from the 5e-database — a DETERMINISTIC parse, never
an LLM transcription (the CS4 lesson, same as gen_bestiary.py: the source JSON is
already authoritative; agents garble stat tables).

Source: https://github.com/5e-bits/5e-database  (CC-BY-4.0 / OGL SRD 5.1)
        src/2014/en/5e-SRD-Monsters.json

Re-run:
    curl -sL https://raw.githubusercontent.com/5e-bits/5e-database/main/src/2014/en/5e-SRD-Monsters.json -o srd-monsters-raw.json
    python tools/gen_arena_monsters.py srd-monsters-raw.json arena/data/monsters/srd

What it maps onto the Arena `Monster` model, with full combat fidelity:
  - every weapon/natural attack, including MULTI-TYPE damage (a dragon's bite =
    piercing + fire) — `Attack.damage` is a list of typed `DamageRoll`s;
  - save-based actions (breath weapons etc.) → `SavingThrowEffect` (DC, ability,
    damage, half/none on success). The Arena has no recharge timer, so a recharge
    action is capped at `uses_per_rest=2` (a balance approximation);
  - core stats: abilities, AC, HP, hit dice, speed, proficiency, CR, XP,
    resistances/immunities/vulnerabilities, condition immunities, senses;
  - MULTIATTACK as a `special_abilities` Feature carrying `extra_attack_count`
    (= total attacks − 1). NOTE: monster multiattack is currently DORMANT — the
    engine's get_extra_attack_count only reads PlayerCharacter.features, not a
    monster's special_abilities. The data is forward-compatible: a ~4-line engine
    change ("turn on" monster multiattack) activates it across the whole set.

DEFERRED (Phase 2 / not mechanized): spellcasting (spells are listed by name, not
as mechanical effects), legendary/lair actions, on-hit rider conditions. Passive
abilities (Pack Tactics etc.) are stored for display but stay inert (no engine
support). Generated monsters get the default AI profile.

Every output is validated against the Arena `Monster` model before writing.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root for `arena`
from arena.models.monster import Monster  # noqa: E402

_ABILS = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
_SIZES = {"tiny", "small", "medium", "large", "huge", "gargantuan"}
_TYPES = {"aberration", "beast", "celestial", "construct", "dragon", "elemental",
          "fey", "fiend", "giant", "humanoid", "monstrosity", "ooze", "plant", "undead"}
_DMG_TYPES = {"acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic",
              "piercing", "poison", "psychic", "radiant", "slashing", "thunder"}
_ABIL_FROM_INDEX = {"str": "strength", "dex": "dexterity", "con": "constitution",
                    "int": "intelligence", "wis": "wisdom", "cha": "charisma"}
_NUM_WORD = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _mod(score: int) -> int:
    return (score - 10) // 2


def _first_int(text) -> int | None:
    m = re.search(r"\d+", str(text))
    return int(m.group()) if m else None


def _parse_dice(s: str) -> tuple[str, int]:
    """'2d10+6' → ('2d10', 6); '16d6' → ('16d6', 0)."""
    m = re.match(r"^\s*(\d+d\d+)\s*([+-]\s*\d+)?\s*$", s or "")
    if not m:
        return (s or "1d4", 0)
    return (m.group(1), int(m.group(2).replace(" ", "")) if m.group(2) else 0)


def _speed(spd: dict) -> dict:
    out = {}
    for k, v in (spd or {}).items():
        n = _first_int(v)
        if n is not None:
            out[k] = n
    return out or {"walk": 30}


def _senses(senses: dict) -> tuple[dict, int | None]:
    out, passive = {}, None
    for k, v in (senses or {}).items():
        if k == "passive_perception":
            passive = _first_int(v)
        else:
            n = _first_int(v)
            if n is not None:
                out[k] = n
    return out, passive


def _save_profs(profs: list) -> list[str]:
    out = []
    for p in profs or []:
        idx = (p.get("proficiency") or {}).get("index", "")
        if idx.startswith("saving-throw-"):
            ab = idx.rsplit("-", 1)[-1]
            if ab in _ABIL_FROM_INDEX:
                out.append(_ABIL_FROM_INDEX[ab])
    return out


def _damage_rolls(damage_list: list) -> list[dict]:
    rolls = []
    for d in damage_list or []:
        dtype = (d.get("damage_type") or {}).get("index")
        dd = d.get("damage_dice")
        if not dtype or dtype not in _DMG_TYPES or not dd:
            continue  # skip conditional/choice/typeless damage (Phase 1)
        dice, bonus = _parse_dice(dd)
        rolls.append({"dice": dice, "damage_type": dtype, "bonus": bonus})
    return rolls


def _attack_ability(abils: dict, prof: int, atk_bonus: int) -> str:
    """Pick the ability whose mod+prof equals the flat attack_bonus (SRD attacks
    decompose exactly); prefer STR then DEX, else the closest."""
    best = None
    for a in _ABILS:
        diff = abs(atk_bonus - (_mod(abils[a]) + prof))
        if diff == 0:
            return a
        if best is None or diff < best[0]:
            best = (diff, a)
    return best[1]


def _aoe_shape(desc: str) -> tuple[str, int | None]:
    d = desc.lower()
    size = None
    m = re.search(r"(\d+)[- ]foot", d)
    if m:
        size = int(m.group(1))
    if "cone" in d:
        return "area_cone", size
    if "line" in d:
        return "area_line", size
    if "radius" in d or "sphere" in d:
        return "area_sphere", size
    return "one_creature", None


def _action(a: dict, abils: dict, prof: int) -> dict | None:
    """Map a 5e-db action to an Arena Action dict — an attack (possibly multi-type)
    or a saving-throw effect. Returns None for non-mechanizable utility actions."""
    name, desc = a["name"], a.get("desc", "")
    if a.get("attack_bonus") is not None and a.get("damage"):
        rolls = _damage_rolls(a["damage"])
        if not rolls:
            return None
        ranged = "ranged" in desc.lower()
        reach = _first_int(re.search(r"reach (\d+)", desc.lower()) and re.search(r"reach (\d+)", desc.lower()).group(1)) or 5
        return {
            "name": name, "description": desc, "action_type": "action",
            "target_type": "one_creature", "range": reach,
            "attack": {
                "name": name,
                "attack_type": "ranged_weapon" if ranged else "melee_weapon",
                "ability": _attack_ability(abils, prof, a["attack_bonus"]),
                "reach": reach,
                "damage": rolls,
            },
        }
    if a.get("dc"):
        dc = a["dc"]
        success = dc.get("success_type")
        shape, size = _aoe_shape(desc)
        out = {
            "name": name, "description": desc, "action_type": "action",
            "target_type": shape,
            "saving_throw": {
                "ability": _ABIL_FROM_INDEX.get((dc.get("dc_type") or {}).get("index"), "dexterity"),
                "dc": dc.get("dc_value"),
                "damage_on_fail": _damage_rolls(a.get("damage")),
                "damage_on_success": success if success in ("none", "half", "full") else "none",
            },
        }
        if size:
            out["area_size"] = size
        usage = (a.get("usage") or {}).get("type", "")
        if usage.startswith("recharge"):
            # The Arena has no recharge timer; cap it as a balance approximation.
            out["uses_per_rest"] = 2
            out["rest_type"] = "short"
            out["current_uses"] = 2
        return out
    return None


def _multiattack(actions: list) -> dict | None:
    """A Multiattack action → a Feature carrying extra_attack_count (total − 1).
    Prefers the structured `actions` refs, falls back to parsing the count word."""
    for a in actions:
        is_ma = a.get("multiattack_type") or a["name"].lower() == "multiattack"
        if not is_ma:
            continue
        refs = a.get("actions") or []
        total, saw_int = 0, False
        for r in refs:
            try:
                total += int(r.get("count", 1))  # count may be "1d4"/"Number of Heads"
                saw_int = True
            except (TypeError, ValueError):
                continue  # variable count — not a fixed extra-attack number
        if not saw_int:
            m = re.search(r"makes (\w+) ", a.get("desc", "").lower())
            total = _NUM_WORD.get(m.group(1), 0) if m else 0
        if total and total > 1:
            return {"name": "Multiattack", "description": a.get("desc", ""),
                    "extra_attack_count": total - 1}
    return None


def build_monster(m: dict) -> dict:
    abils = {a: m[a] for a in _ABILS}
    prof = m.get("proficiency_bonus") or 2
    ac_raw = m["armor_class"]
    ac = ac_raw[0]["value"] if isinstance(ac_raw, list) else ac_raw
    senses, passive = _senses(m.get("senses"))

    actions = []
    for a in m.get("actions", []):
        if a.get("multiattack_type") or a["name"].lower() == "multiattack":
            continue
        act = _action(a, abils, prof)
        if act:
            actions.append(act)

    special = []
    ma = _multiattack(m.get("actions", []))
    if ma:
        special.append(ma)
    for sa in m.get("special_abilities", []):
        special.append({"name": sa["name"], "description": sa.get("desc", "")})

    size = m.get("size", "Medium").lower()
    ctype = m.get("type", "humanoid").lower()
    mon = {
        "name": m["name"],
        "size": size if size in _SIZES else "medium",
        "creature_type": ctype if ctype in _TYPES else "humanoid",
        "alignment": m.get("alignment"),
        "ability_scores": abils,
        "armor_class": max(1, ac),
        "max_hit_points": max(1, m["hit_points"]),
        "hit_dice": m.get("hit_dice"),
        "speed": _speed(m.get("speed")),
        "proficiency_bonus": prof,
        "saving_throw_proficiencies": _save_profs(m.get("proficiencies")),
        "damage_resistances": list(m.get("damage_resistances", [])),
        "damage_immunities": list(m.get("damage_immunities", [])),
        "damage_vulnerabilities": list(m.get("damage_vulnerabilities", [])),
        "condition_immunities": [c["index"] for c in m.get("condition_immunities", [])],
        "senses": senses,
        "passive_perception": passive,
        "actions": actions,
        "special_abilities": special,
        "challenge_rating": float(m.get("challenge_rating", 0)),
        "experience_points": int(m.get("xp", 0)),
        "is_player_controlled": False,
    }
    return mon


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python tools/gen_arena_monsters.py <srd-monsters.json> <out-dir>",
              file=sys.stderr)
        return 2
    source = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    out_dir = Path(argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)

    written, failed = 0, []
    for m in source:
        mid = m["index"].replace("-", "_")
        try:
            data = build_monster(m)
            Monster.model_validate(data)  # structural gate — fail loud, never ship junk
        except Exception as e:  # noqa: BLE001
            failed.append((mid, str(e)[:140]))
            continue
        (out_dir / f"{mid}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        written += 1

    print(f"wrote {written} monster files to {out_dir}")
    if failed:
        print(f"FAILED {len(failed)}:")
        for mid, err in failed:
            print(f"  {mid}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
