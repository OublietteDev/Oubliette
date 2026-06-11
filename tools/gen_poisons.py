"""Generate the SRD poison catalog and FOLD it into content/srd/equipment.json, from
the machine-readable 5e-database 2014 dataset — a DETERMINISTIC parse, never a
transcription. Poisons aren't a structured endpoint (no 5e-SRD-Poisons.json); they
live in the prose "Poisons" rule-section, so this parses that section's type/price
table plus the per-poison effect prose (DC / damage dice / imposed conditions).

Source: https://github.com/5e-bits/5e-database  (CC-BY-4.0 / OGL SRD 5.1 content)
        src/2014/en/5e-SRD-Rule-Sections.json  -> section "Poisons"

Re-run:
    curl -sL https://raw.githubusercontent.com/5e-bits/5e-database/main/src/2014/en/5e-SRD-Rule-Sections.json -o srd-rule-sections-raw.json
    python tools/gen_poisons.py srd-rule-sections-raw.json oubliette/content/srd/equipment.json

WHAT IT DOES
- Parses the 14 SRD poisons (Assassin's Blood .. Wyvern Poison) into PoisonMechanics:
  Constitution save DC, poison type (contact/ingested/inhaled/injury), failed-save
  damage dice, and the conditions imposed (poisoned / paralyzed / unconscious / ...).
- Enriches the existing mundane `poison_basic_vial` (PHB basic poison) in place with
  the same structured shape, so every poison in the catalog carries combat mechanics.
- Appends the 14 as `item_type: "poison"`, tagged `poison`, validated against the
  SrdEquipment schema before writing.
"""

from __future__ import annotations

import json
import re
import sys

from oubliette.content.srd_schemas import PoisonMechanics, SrdEquipment

# Secondary conditions a poison imposes — read ONLY from effect phrasing ("the poisoned
# creature is [also] X"), never a bare substring, so the harvesting flavor ("a dead or
# incapacitated crawler") can't masquerade as an effect.
_SECONDARY_CONDITIONS = ["paralyzed", "unconscious", "blinded", "incapacitated"]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower().replace("'", "")).strip("_")


def _parse_price(cell: str) -> int | None:
    m = re.search(r"([\d,]+)\s*gp", cell)
    return int(m.group(1).replace(",", "")) if m else None


def _poison_section(rule_sections: list[dict]) -> str:
    for x in rule_sections:
        if x.get("name") == "Poisons":
            return x["desc"]
    raise SystemExit("no 'Poisons' rule-section found in source")


def _parse_table(desc: str) -> dict[str, tuple[str, int | None]]:
    """The '| Item | Type | Price per Dose |' table -> {name: (type, price_gp)}."""
    out: dict[str, tuple[str, int | None]] = {}
    for line in desc.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3:
            continue
        name, ptype, price = cells
        if ptype.lower() not in ("contact", "ingested", "inhaled", "injury"):
            continue                                   # header / separator rows
        out[name.lower()] = (ptype.lower(), _parse_price(price))
    return out


def _parse_effect(block: str) -> PoisonMechanics:
    """One '***Name (Type).*** ...' prose block -> the structured failure effect."""
    dc = int(re.search(r"DC (\d+) Constitution", block).group(1))
    dmg_m = re.search(r"\((\d+d\d+)\)", block)          # "10 (3d6) poison damage"
    damage = dmg_m.group(1) if dmg_m else None
    low = block.lower()
    conditions: list[str] = []
    if re.search(r"(?:become|becomes|be|is|are) poisoned|poisoned for", low):
        conditions.append("poisoned")                  # the base condition, listed first
    for cond in _SECONDARY_CONDITIONS:                 # only "...creature is [also] X"
        if re.search(rf"\bis (?:also )?{cond}\b", low):
            conditions.append(cond)
    dur_m = re.search(r"poisoned for (\d+(?:d\d+)?\s+(?:hours?|minutes?))", low)
    duration = dur_m.group(1) if dur_m else None
    ptype = re.search(r"\((Contact|Ingested|Inhaled|Injury)\)", block).group(1).lower()
    return PoisonMechanics(poison_type=ptype, save_dc=dc, damage=damage,
                           conditions=conditions, duration=duration)


def _parse_effects(desc: str) -> dict[str, tuple[str, PoisonMechanics]]:
    """Split the 'Sample Poisons' prose on '***' -> {name: (clean_desc, mechanics)}."""
    out: dict[str, tuple[str, PoisonMechanics]] = {}
    # each sample begins '***Name (Type).*** rest...'. The name can't contain '*' or a
    # newline, so this can't latch onto the '***Contact.***' type-definition headers (no
    # parenthesized type) and swallow the table in between.
    for m in re.finditer(r"\*\*\*([^(*\n]+?)\s*\((Contact|Ingested|Inhaled|Injury)\)\.\*\*\*\s*(.+?)(?=\*\*\*|$)",
                         desc, flags=re.DOTALL):
        name = m.group(1).strip()
        block = m.group(0)
        prose = re.sub(r"\s+", " ", m.group(3)).strip()
        out[name.lower()] = (prose, _parse_effect(block))
    return out


def build_records(rule_sections: list[dict]) -> list[SrdEquipment]:
    desc = _poison_section(rule_sections)
    table = _parse_table(desc)
    effects = _parse_effects(desc)
    records: list[SrdEquipment] = []
    for name_lc, (ptype, price) in table.items():
        if name_lc not in effects:
            raise SystemExit(f"poison {name_lc!r} in table but no effect prose found")
        prose, mech = effects[name_lc]
        # the table 'Type' and the prose 'Type' must agree (deterministic cross-check)
        assert mech.poison_type == ptype, f"{name_lc}: type mismatch {mech.poison_type} vs {ptype}"
        display = " ".join(w.capitalize() for w in name_lc.split())
        records.append(SrdEquipment(
            id=_slug(name_lc), name=display, category="consumable",
            description=prose, base_value=price, tags=["poison"],
            item_type="poison", rarity=None, mechanics="structured", poison=mech,
        ))
    return records


def enrich_basic_poison(existing: dict) -> None:
    """The PHB basic poison vial (already in the mundane 238) -> structured mechanics.
    Stays in the base catalog (no 'poison' tag) so the CS4 base-238 tripwire holds; it
    just gains the `poison` field for the bridge. Injury, DC 10 Con, 1d4, no condition."""
    existing["item_type"] = "poison"
    existing["mechanics"] = "structured"
    existing["poison"] = PoisonMechanics(
        poison_type="injury", save_dc=10, damage="1d4",
    ).model_dump(exclude_none=True)


def main(raw_path: str, out_path: str) -> None:
    rule_sections = json.load(open(raw_path, encoding="utf-8"))
    existing = json.load(open(out_path, encoding="utf-8"))
    by_id = {x["id"]: x for x in existing}

    records = build_records(rule_sections)
    if "poison_basic_vial" in by_id:
        enrich_basic_poison(by_id["poison_basic_vial"])

    # never add a poison whose id already exists (idempotent re-runs)
    existing_ids = set(by_id)
    new = [r.model_dump(exclude_none=True) for r in records if r.id not in existing_ids]

    for x in existing:                       # re-validate (enrich mutated one in place)
        SrdEquipment.model_validate(x)

    merged = existing + new
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"parsed SRD poisons: {len(records)}")
    print(f"new poison records: {len(new)} (enriched poison_basic_vial in place)")
    print(f"total catalog: {len(merged)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python tools/gen_poisons.py <rule-sections.json> <equipment.json out>")
    main(sys.argv[1], sys.argv[2])
