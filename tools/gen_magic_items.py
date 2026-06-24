"""Generate the SRD magic-item catalog and FOLD it into content/srd/equipment.json,
from the machine-readable 5e-database 2014 dataset — a DETERMINISTIC parse, never an
LLM transcription (the CS4 lesson: agents garble tables; the source JSON is already
authoritative). Fourth use of this proven playbook (gen_bestiary / gen_arena_monsters
/ the CS4 equipment fill).

Source: https://github.com/5e-bits/5e-database  (CC-BY-4.0 / OGL SRD 5.1 content)
        src/2014/en/5e-SRD-Magic-Items.json

Re-run:
    curl -sL https://raw.githubusercontent.com/5e-bits/5e-database/main/src/2014/en/5e-SRD-Magic-Items.json -o tools/raw/srd-magic-items-raw.json
    python tools/gen_magic_items.py tools/raw/srd-magic-items-raw.json oubliette/content/srd/equipment.json

WHAT IT DOES
- Drops the 21 "parent template" records (those with a non-empty `variants` list):
  every concrete child is itself a top-level record, so nothing is lost and all the
  `rarity: "Varies"` umbrellas disappear.
- Maps each concrete item onto the SrdEquipment schema, keeping `category` inside the
  closed set state.Item accepts (potion/scroll -> consumable, weapon/armor -> same,
  rest -> gear) and recording the granular SRD class in the new `item_type` field.
- Extracts structured, bridge-readable mechanics from the prose for the families the
  content-first plan names (healing / +X bonus / ability-set / resistance / scroll).
  Anything else ships as prose with `mechanics: "none"` — a success state, NOT a skip.
- Merges into the existing equipment.json by normalized name: the one overlap with the
  mundane catalog (Potion of Healing) ENRICHES the existing record in place rather than
  adding a duplicate. Existing item ids are never changed.
- Validates EVERY record against SrdEquipment before writing (the structural gate).
"""

from __future__ import annotations

import json
import re
import sys

from oubliette.content.srd_schemas import ConsumableMechanics, SrdEquipment

# 5e-database equipment_category.name -> (state-compatible category, granular item_type)
_CATEGORY_MAP = {
    "Potion": ("consumable", "potion"),
    "Scroll": ("consumable", "scroll"),
    "Weapon": ("weapon", "weapon"),
    "Armor": ("armor", "armor"),
    "Ammunition": ("gear", "ammunition"),
    "Wand": ("gear", "wand"),
    "Ring": ("gear", "ring"),
    "Rod": ("gear", "rod"),
    "Staff": ("gear", "staff"),
    "Wondrous Items": ("gear", "wondrous"),
}

# advisory price hint by rarity (soft economy §11 — never enforced)
_RARITY_VALUE = {
    "common": 50, "uncommon": 400, "rare": 4000,
    "very rare": 40000, "legendary": 200000, "artifact": 500000,
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _norm(s: str) -> str:
    """Normalized name for dedup against the existing catalog."""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _join_desc(desc: list[str]) -> str:
    """Join the prose, dropping the leading 'Potion, uncommon (requires attunement)'
    header line the dataset prepends — that data lives in structured fields now."""
    lines = list(desc)
    if lines and re.match(
        r"^(Potion|Ring|Wand|Rod|Staff|Scroll|Wondrous item|Weapon|Armor|Ammunition),",
        lines[0],
    ):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _extract_consumable(name: str, item_type: str, text: str) -> tuple[ConsumableMechanics | None, str]:
    """Return (ConsumableMechanics | None, mechanics_marker). Pattern rules applied in
    the plan's priority order. mechanics_marker is "structured" when a combat-carriable
    effect was extracted, else "none"."""
    duration = None
    m = re.search(r"for (\d+\s+(?:hour|hours|minute|minutes|round|rounds))", text)
    if m:
        duration = m.group(1)

    # 1. Healing potions: "regain 2d4 + 2 hit points"
    m = re.search(r"regain\s+(\d+d\d+(?:\s*\+\s*\d+)?)\s+hit points", text)
    if m:
        dice = m.group(1).replace(" ", "")
        return ConsumableMechanics(healing=dice), "structured"

    # 2. Ability-set potions (Giant Strength): "Strength score changes to 21"
    m = re.search(r"(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\s+score\s+(?:changes to|becomes)\s+(\d+)", text)
    if m:
        abil = m.group(1).lower()[:3]
        return ConsumableMechanics(ability_set={abil: int(m.group(2))}, duration=duration), "structured"

    # 3. Resistance potions: "resistance to fire damage"
    m = re.search(r"resistance to (\w+) damage", text)
    if m and item_type == "potion":
        return ConsumableMechanics(grants_resistance=m.group(1).lower(), duration=duration), "structured"

    # 4. Spell scrolls: level from the name — "(Cantrip)" or "(3rd)"
    if item_type == "scroll":
        m = re.search(r"\((Cantrip|\d+)(?:st|nd|rd|th)?\)", name)
        if m:
            lvl = 0 if m.group(1) == "Cantrip" else int(m.group(1))
            # F3: cataloged + level recorded, but casting is unimplemented -> "none"
            return ConsumableMechanics(casts_spell_level=lvl), "none"

    return None, "none"


def _magic_bonus(text: str) -> int | None:
    """+N from the canonical bonus phrasings (weapon attack&damage, armor/ring AC)."""
    m = re.search(r"\+(\d)\s+bonus to attack and damage", text)
    if m:
        return int(m.group(1))
    m = re.search(r"\+(\d)\s+bonus to AC", text)
    if m:
        return int(m.group(1))
    return None


def build_record(src: dict) -> SrdEquipment:
    cat_name = (src.get("equipment_category") or {}).get("name", "")
    category, item_type = _CATEGORY_MAP.get(cat_name, ("misc", "wondrous"))
    rarity = ((src.get("rarity") or {}).get("name") or "").lower() or None
    if rarity == "varies":                   # the generic Spell Scroll: rarity follows its contents
        rarity = None
    full_desc = " ".join(src.get("desc", []))
    text = _join_desc(src.get("desc", []))
    attune = "requires attunement" in (src.get("desc") or [""])[0].lower()

    consumable, mechanics = _extract_consumable(src["name"], item_type, full_desc)
    bonus = _magic_bonus(full_desc) if item_type in ("weapon", "armor", "ammunition", "ring", "wondrous") else None
    if bonus is not None:
        mechanics = "structured"

    return SrdEquipment(
        id=_slug(src["index"]),
        name=src["name"],
        category=category,
        description=text,
        base_value=_RARITY_VALUE.get(rarity or "", None),
        tags=["magic"],
        item_type=item_type,
        rarity=rarity,
        magic_bonus=bonus,
        requires_attunement=attune,
        mechanics=mechanics,
        consumable=consumable,
    )


def enrich_existing(existing: dict, rec: SrdEquipment) -> None:
    """Fold a generated magic item's structured fields onto an existing catalog record
    (the Potion of Healing overlap), preserving the existing id and ordering."""
    existing["item_type"] = rec.item_type
    existing["rarity"] = rec.rarity
    existing["mechanics"] = rec.mechanics
    existing["requires_attunement"] = rec.requires_attunement
    if rec.magic_bonus is not None:
        existing["magic_bonus"] = rec.magic_bonus
    if rec.consumable is not None:
        existing["consumable"] = rec.consumable.model_dump(exclude_none=True)


def main(raw_path: str, out_path: str) -> None:
    raw = json.load(open(raw_path, encoding="utf-8"))
    existing = json.load(open(out_path, encoding="utf-8"))
    by_norm = {_norm(x["name"]): x for x in existing}

    # Drop the 21 parent templates (those carrying a `variants` list) — every concrete
    # child is its own record. EXCEPTION: scrolls. Rather than 10 per-level scroll items
    # (Spell Scroll (Cantrip) .. (9th)), keep the single generic `spell-scroll` PARENT
    # and drop its children: the scroll's level is derived from whichever spell the DM
    # inscribes onto it at grant time, carried as a per-inventory-item rider (A5), so one
    # generic Spell Scroll covers every spell — SRD or authored — with no item explosion.
    concrete = []
    for x in raw:
        if x.get("variants"):
            if x["index"] == "spell-scroll":
                concrete.append(x)            # keep the one generic Spell Scroll
            continue                          # drop every other parent template
        if x["index"].startswith("spell-scroll-"):
            continue                          # drop the per-level scroll children
        concrete.append(x)

    new_records: list[dict] = []
    enriched = 0
    seen_norm: set[str] = set()
    for src in concrete:
        rec = build_record(src)
        nrm = _norm(rec.name)
        if nrm in by_norm:
            enrich_existing(by_norm[nrm], rec)
            enriched += 1
            continue
        if nrm in seen_norm:                 # intra-magic duplicate name — keep first
            continue
        seen_norm.add(nrm)
        new_records.append(rec.model_dump(exclude_none=True))

    # re-validate every existing record too (the enrich step mutated some in place)
    for x in existing:
        SrdEquipment.model_validate(x)

    merged = existing + new_records
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"source items kept: {len(concrete)} (dropped {len(raw) - len(concrete)} "
          f"parent templates + per-level scroll variants)")
    print(f"enriched existing records: {enriched}")
    print(f"new magic-item records: {len(new_records)}")
    print(f"total catalog: {len(merged)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python tools/gen_magic_items.py <raw.json> <equipment.json out>")
    main(sys.argv[1], sys.argv[2])
