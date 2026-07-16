"""Generate the benchmark party (Arena test beds, T1).

The proving ground pits an author's monsters against a KNOWN quantity: the
classic four — fighter, cleric, rogue, wizard — at any level 1-9. Rather than
auto-resolving level-up choices at runtime (sloppy picks would make a
worthless benchmark), this script drives the REAL chargen + level-up engines
once, with curated choices, and ships the snapshots as data:
`oubliette/content/benchmark/party.json`.

Every character passes the same firewall a player's does — build_character
validates the level-1 build, level_up validates every level after it, and
the curated spell lists are drawn in priority order from what the engine
says each level owes. A typo'd spell id fails loudly here, never at the
table. Human across the roster (+1 all, no subrace/ancestry choices), the
SRD's single subclass per class, average HP, +2 primary ASIs.

Rerun after SRD data changes: python tools/gen_benchmark_party.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oubliette.content.ruleset import load_ruleset
from oubliette.enums import Ability
from oubliette.rules import derive
from oubliette.rules.chargen import CharacterBuild, build_character
from oubliette.rules.levelup import LevelUpChoice, level_up, xp_for_level

OUT = Path(__file__).resolve().parent.parent / "oubliette" / "content" / "benchmark" / "party.json"

MAX_BENCH_LEVEL = 9
ROSTER = ["fighter", "cleric", "rogue", "wizard"]   # party of N = the first N

# Standard-array assignments (pre-racial; human adds +1 to all six).
_A = lambda **kw: {Ability(k): v for k, v in kw.items()}

PLANS = {
    "fighter": {
        "abilities": _A(str=15, con=14, dex=13, wis=12, int=10, cha=8),
        "skills": ["athletics", "perception"],
        "subclass": {3: "champion"},
        "asi": {4: {"str": 2}, 6: {"str": 2}, 8: {"con": 2}},
        "cantrip_priority": [],
        "spell_priority": [],
    },
    "cleric": {
        "abilities": _A(wis=15, con=14, str=13, cha=12, dex=10, int=8),
        "skills": ["medicine", "persuasion"],   # acolyte already grants insight+religion
        "subclass": {1: "life"},                    # clerics choose at level 1
        "asi": {4: {"wis": 2}, 8: {"wis": 2}},
        "cantrip_priority": ["sacred_flame", "guidance", "thaumaturgy",
                             "light", "mending"],
        "spell_priority": [
            "cure_wounds", "bless", "guiding_bolt", "healing_word",
            "shield_of_faith", "sanctuary", "spiritual_weapon", "hold_person",
            "lesser_restoration", "silence", "spirit_guardians",
            "dispel_magic", "mass_healing_word", "revivify",
            "guardian_of_faith", "death_ward", "freedom_of_movement",
            "banishment", "flame_strike", "mass_cure_wounds", "commune",
            "greater_restoration",
        ],
    },
    "rogue": {
        "abilities": _A(dex=15, con=14, wis=13, int=12, cha=10, str=8),
        "skills": ["stealth", "perception", "acrobatics", "investigation"],
        "expertise": ["stealth", "perception"],
        "subclass": {3: "thief"},
        "asi": {4: {"dex": 2}, 8: {"dex": 2}},
        # _auto_loadout equips the FIRST weapon granted — the fixed daggers —
        # but the benchmark rogue fights with the chosen rapier.
        "equip": ["leather_armor", "rapier"],
        "cantrip_priority": [],
        "spell_priority": [],
    },
    "wizard": {
        "abilities": _A(int=15, con=14, dex=13, wis=12, str=10, cha=8),
        "skills": ["arcana", "investigation"],
        "subclass": {2: "evocation"},
        "asi": {4: {"int": 2}, 8: {"int": 2}},
        "cantrip_priority": ["fire_bolt", "mage_hand", "light",
                             "prestidigitation", "ray_of_frost"],
        "spell_priority": [
            "magic_missile", "shield", "mage_armor", "burning_hands",
            "sleep", "thunderwave", "detect_magic", "misty_step",
            "scorching_ray", "mirror_image", "shatter", "fireball",
            "counterspell", "haste", "fly", "dimension_door",
            "greater_invisibility", "ice_storm", "phantasmal_killer",
            "cone_of_cold", "wall_of_force", "hold_monster",
        ],
    },
}

NAMES = {"fighter": "Bram", "cleric": "Mirelle", "rogue": "Vex", "wizard": "Aldous"}


def _check_priorities(rs) -> None:
    """Every curated spell id must exist and sit on its class's list — a typo
    here would silently starve a caster at some level."""
    bad = []
    for cls, plan in PLANS.items():
        on_list = {s.id for s in rs.spells_for(cls)}
        for sid in plan["cantrip_priority"] + plan["spell_priority"]:
            if sid not in on_list:
                bad.append(f"{cls}: {sid!r}")
    if bad:
        raise SystemExit("unknown/off-list spell ids:\n  " + "\n  ".join(bad))


def _wants(char, rs, level: int, abilities: dict) -> tuple[int, int, int]:
    """(cantrips, leveled spells, max castable level) the sheet should hold AT
    `level` with `abilities` — the same probe the level-up validator uses."""
    probe = char.model_copy(update={"level": level, "abilities": abilities})
    slots = derive.spell_slots(probe, rs)
    return (derive.cantrips_known(probe, rs) or 0,
            derive.spells_known_count(probe, rs) or 0,
            max(slots) if slots else 0)


def _take(priority: list[str], have: list[str], need: int, rs, max_level: int,
          cls: str) -> list[str]:
    """The next `need` castable picks from the priority order."""
    picks = [sid for sid in priority
             if sid not in have and rs.spells[sid].level <= max_level][:need]
    if len(picks) < need:
        raise SystemExit(f"{cls}: priority list ran dry ({need} needed at "
                         f"max spell level {max_level}, found {len(picks)})")
    return picks


def _build_level_1(cls: str, plan: dict, rs):
    cc = rs.classes[cls]
    temp_abilities = {a: v + 1 for a, v in plan["abilities"].items()}   # human +1 all
    # Probe with a raw level-1 human of this class to learn the pick counts.
    from oubliette.state.models import Character, CharacterSheet
    probe = Character(id="_", name="_", kind="pc", level=1,
                      abilities=temp_abilities,
                      sheet=CharacterSheet(race="human", char_class=cls, background="acolyte",
                                           spellcasting_ability=(Ability(cc.spellcasting.ability)
                                                                 if cc.spellcasting else None)))
    want_c = derive.cantrips_known(probe, rs) or 0
    want_s = derive.spells_known_count(probe, rs) or 0
    slots = derive.spell_slots(probe, rs)
    max_lvl = max(slots) if slots else 0
    build = CharacterBuild(
        name=NAMES[cls], race="human", char_class=cls, background="acolyte",
        subclass=plan["subclass"].get(1),
        ability_method="standard_array",
        base_abilities=plan["abilities"],
        skills=plan["skills"],
        expertise=plan.get("expertise", []),
        languages=["elvish", "celestial"],     # acolyte's two free picks
        race_languages=["dwarvish"],
        cantrips=plan["cantrip_priority"][:want_c],
        spells=_take(plan["spell_priority"], [], want_s, rs, max_lvl, cls),
        equipment_choices=[[0] for _ in cc.starting_equipment.choices],
        alignment="neutral good",
        description=f"Benchmark {cls} — the proving ground's known quantity.",
    )
    return build_character(build, rs, char_id=f"bench_{cls}")


def main() -> None:
    rs = load_ruleset()
    _check_priorities(rs)
    out: dict = {"roster": ROSTER, "levels": {}}
    for cls in ROSTER:
        plan = PLANS[cls]
        char, items = _build_level_1(cls, plan, rs)
        if "equip" in plan:
            char.equipped = list(plan["equip"])
        entry = {"items": [i.model_dump(mode="json") for i in items], "levels": {}}
        entry["levels"]["1"] = char.model_dump(mode="json")
        for lvl in range(2, MAX_BENCH_LEVEL + 1):
            char = char.model_copy(update={"xp": xp_for_level(lvl)})
            asi = plan["asi"].get(lvl, {})
            abilities_after = dict(char.abilities)
            for k, v in asi.items():
                abilities_after[Ability(k)] = abilities_after.get(Ability(k), 10) + v
            want_c, want_s, max_lvl = _wants(char, rs, lvl, abilities_after)
            choice = LevelUpChoice(
                hp_method="average",
                subclass=plan["subclass"].get(lvl),
                ability_increases={Ability(k): v for k, v in asi.items()},
                new_cantrips=_take(plan["cantrip_priority"],
                                   char.sheet.cantrips_known,
                                   max(0, want_c - len(char.sheet.cantrips_known)),
                                   rs, 0 if max_lvl == 0 else max_lvl, cls),
                new_spells=_take(plan["spell_priority"],
                                 char.sheet.spells_known,
                                 max(0, want_s - len(char.sheet.spells_known)),
                                 rs, max_lvl, cls),
            )
            char = level_up(char, rs, choice, char_id=f"bench_{cls}")
            entry["levels"][str(lvl)] = char.model_dump(mode="json")
        out["levels"][cls] = entry
        line = [f"L{lv}: hp {c['max_hp']}" for lv, c in entry["levels"].items()]
        print(f"{cls:8s} {NAMES[cls]:8s} " + "  ".join(line))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
