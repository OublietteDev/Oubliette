"""Stamp REAL SRD coin prices onto the equipment catalog (currency S3).

Source: tools/raw/srd-equipment-raw.json — the 5e-database (2014/en) equipment
list, whose costs carry exact denominations ({quantity: 1, unit: "sp"}). The
CS4 parse rounded everything to whole gold, so a candle (1 cp) and a club
(1 sp) had no price at all — the gap Brett hit.

Writes each matched item's `base_value` as a coin STRING ("1 sp", "15 gp"),
which the loaders parse via coin.authored_to_cp; unmatched items (magic items,
poisons — priced by our own generators) keep their existing values. Idempotent;
rerun any time after refreshing the raw file:

    curl -sL https://raw.githubusercontent.com/5e-bits/5e-database/main/src/2014/en/5e-SRD-Equipment.json \
         -o tools/raw/srd-equipment-raw.json
    python tools/gen_equipment_costs.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "tools" / "raw" / "srd-equipment-raw.json"
CATALOG = ROOT / "oubliette" / "content" / "srd" / "equipment.json"

# 5e-database index -> our catalog id, where snake_casing alone doesn't land.
RENAMES = {
    "crossbow_hand": "hand_crossbow",
    "crossbow_heavy": "heavy_crossbow",
    "crossbow_light": "light_crossbow",
}


def main() -> None:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_id = {it["id"]: it for it in catalog}

    stamped = missing = 0
    for entry in raw:
        cost = entry.get("cost")
        if not cost:
            continue
        rid = entry["index"].replace("-", "_")
        rid = RENAMES.get(rid, rid)
        item = by_id.get(rid)
        if item is None:
            missing += 1
            print(f"  (no catalog item for {entry['index']!r} — skipped)")
            continue
        item["base_value"] = f"{cost['quantity']} {cost['unit']}"
        stamped += 1

    CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    print(f"stamped {stamped} real prices ({missing} source items unmatched)")


if __name__ == "__main__":
    main()
