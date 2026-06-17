"""Per-turn state/scene context for the DM (fix for harness gap G2).

The model can't set a fair DC "by the NPC's shrewdness" or resolve a sale without
knowing who's present, their disposition, and the party's resources. This builds
a compact, readable snapshot injected into both the assess and resolve prompts.
It reads OPEN flavor (dispositions) + the protected sheet essentials — never
exposes internals the model shouldn't reason about as numbers it owns.
"""

from __future__ import annotations

from ..canon.models import CanonRecord
from ..enums import Ability, Skill
from ..rules.derive import (class_resources, save_modifier, skill_modifier,
                            spell_attack_bonus, spell_save_dc, spell_slots)
from ..state.repository import Repository

LORE_MAX = 3        # most lore entries surfaced in one turn's context
LORE_CHARS = 1200   # per-entry budget — generous (lore is meant to be retold, not clipped)
FEATURE_CAP = 14    # features listed by name before a "+N more" tail (keep the card bounded)


def _mod(n: int) -> str:
    return f"{n:+d}"


def _ord(n: int) -> str:
    return {1: "st", 2: "nd", 3: "rd"}.get(n, "th")


def _character_cards(repo: Repository, ruleset) -> list[str]:
    """A compact mechanical 'card' per sheeted PC (CS6): who they are, what they're
    trained in, their features/spells/resources — names and key numbers, never the
    full rulebook prose. The point is for the DM to call for the RIGHT check/save
    and narrate rules-aware, NOT to own any number: code still rolls and owns state.

    Sheet-less quick-start heroes get nothing here (the PARTY line already covers
    their basics). Reuses `rules/derive` so the numbers match the read-only sheet
    (CS3) exactly. `ruleset` may be None (custom seeds / tests): abilities, skills,
    saves, features and the spell save DC still render; slot pools and class
    resources, which need the ruleset to derive, are simply omitted."""
    def nm(table_attr: str, ident):
        if ident is None:
            return None
        if ruleset is None:
            return ident
        ent = getattr(ruleset, table_attr, {}).get(ident)
        return ent.name if ent is not None else ident

    def spell_nm(spell_id: str) -> str:
        ent = ruleset.spells.get(spell_id) if ruleset is not None else None
        return ent.name if ent is not None else spell_id

    pcs = [c for c in repo.party() if c.sheet is not None]
    if not pcs:
        return []
    out = [
        "CHARACTER SHEET (mechanical reference — use it to call for the RIGHT check or "
        "save and to skip rolls the character handles trivially or via a feature/spell; "
        "you never roll, code applies these modifiers and owns all state):"
    ]
    for pc in pcs:
        sheet = pc.sheet
        race = nm("races", sheet.race)
        subrace = nm("subraces", sheet.subrace)
        race_label = f"{race} ({subrace})" if subrace else race
        klass = nm("classes", sheet.char_class)
        subclass = nm("subclasses", sheet.subclass)
        class_label = f"{klass}/{subclass}" if subclass else klass
        ident = f"  {pc.name} — level {pc.level} {race_label} {class_label}"
        tail = ", ".join(p for p in [nm("backgrounds", sheet.background), sheet.alignment or None] if p)
        out.append(ident + (f", {tail}" if tail else ""))
        out.append("    Abilities: " + ", ".join(
            f"{a.value.upper()} {_mod(pc.ability_mod(a))}" for a in Ability))
        prof_skills = [
            f"{s.value.replace('_', ' ').title()} {_mod(skill_modifier(pc, s))}"
            f"{' (expertise)' if s in sheet.expertise else ''}"
            for s in Skill if s in pc.skill_proficiencies
        ]
        if prof_skills:
            out.append("    Proficient skills: " + ", ".join(prof_skills) + ".")
        if sheet.saving_throw_proficiencies:
            out.append("    Saving throws: " + ", ".join(
                f"{a.value.upper()} {_mod(save_modifier(pc, a))}"
                for a in Ability if a in sheet.saving_throw_proficiencies) + ".")
        train = []
        for label, vals in (("armor", sheet.armor_proficiencies),
                            ("weapons", sheet.weapon_proficiencies),
                            ("tools", sheet.tool_proficiencies),
                            ("languages", sheet.languages)):
            if vals:
                train.append(f"{label}: " + ", ".join(vals))
        if train:
            out.append("    Trained — " + "; ".join(train) + ".")
        feats = [f.name for f in sheet.features]
        if feats:
            shown = feats[:FEATURE_CAP]
            more = len(feats) - len(shown)
            out.append("    Features: " + ", ".join(shown) + (f" (+{more} more)." if more else "."))
        if sheet.spellcasting_ability is not None:
            bits = [f"Spellcasting ({sheet.spellcasting_ability.value.upper()})"]
            dc, atk = spell_save_dc(pc), spell_attack_bonus(pc)
            if dc is not None:
                bits.append(f"save DC {dc}, attack {_mod(atk)}")
            if ruleset is not None:
                slots = spell_slots(pc, ruleset)
                if slots:
                    bits.append("slots " + ", ".join(
                        f"{lvl}{_ord(lvl)}: {n}" for lvl, n in sorted(slots.items())))
            if sheet.cantrips_known:
                bits.append("cantrips " + ", ".join(spell_nm(s) for s in sheet.cantrips_known))
            leveled = sheet.spells_prepared or sheet.spells_known
            if leveled:
                bits.append("spells " + ", ".join(spell_nm(s) for s in leveled))
            out.append("    " + "; ".join(bits) + ".")
        if ruleset is not None:
            res = class_resources(pc, ruleset)
            if res:
                out.append("    Resources: " + ", ".join(
                    f"{name} {'unlimited' if info.get('unlimited') else info.get('max')}"
                    f"/{info.get('recharge', 'long')} rest"
                    for name, info in res.items()) + ".")
        if pc.conditions:
            out.append("    Conditions: " + ", ".join(pc.conditions) + ".")
    return out


def _reachable(location: str | None, places: dict) -> list:
    """Places the party can travel to from `location`: its explicit exits, its
    sublocations (children), and its siblings (same parent). Returns PlaceNodes."""
    if location is None or location not in places:
        return []
    here = places[location]
    ids: set[str] = set(here.exits)
    ids |= {pid for pid, n in places.items() if n.parent == location}      # children
    if here.parent is not None:
        ids |= {pid for pid, n in places.items() if n.parent == here.parent}  # siblings
    ids.discard(location)
    return [places[i] for i in ids if i in places]


def region_root(location: str | None, places: dict) -> str | None:
    """The party's top-level enclosing area — walk up the parent chain to the outermost
    ancestor. This is "the area you're in" (a town and its districts resolve to one
    region), used to scope ambient quest awareness and the quest-card art."""
    cur, seen = location, set()
    while cur in places and cur not in seen:
        seen.add(cur)
        parent = places[cur].parent
        if not parent:
            break
        cur = parent
    return cur


def _reward_text(repo: Repository, reward) -> str:
    """A short advisory reward line for the DM (the engine never auto-grants it)."""
    if reward is None:
        return ""
    bits: list[str] = []
    if reward.gold:
        bits.append(f"{reward.gold}g")
    if reward.item:
        try:
            name = repo.get_item(reward.item).name
        except Exception:
            name = reward.item
        bits.append(f"{reward.qty}x {name}")
    if reward.note:
        bits.append(reward.note)
    return ", ".join(bits)


def build_context(repo: Repository, scene: str = "", recent: list[str] | None = None,
                  canon: list[CanonRecord] | None = None, location: str | None = None,
                  places: dict | None = None, quests: list | None = None,
                  time_of_day: str | None = None, weather: str | None = None,
                  ruleset=None, authored_quests: dict | None = None,
                  offerable: set | None = None, offered_here: set | None = None) -> str:
    # Show the item id (tool calls need it, gap G2b) + an advisory value anchor for
    # the soft economy (the DM asked for a pricing reference; it's not enforced).
    def _item_label(item_id: str, qty: int) -> str:
        item = repo.get_item(item_id)
        worth = f", ~{item.base_value}g" if item.base_value else ""
        return f"{qty}x {item.name} [id: {item_id}{worth}]"

    def _party_line(p) -> str:
        inv = ", ".join(_item_label(s.item_id, s.qty) for s in p.inventory) or "nothing"
        return f"{p.name} (id: {p.id}) — {p.hp}/{p.max_hp} HP, {p.gold}g, {p.xp} XP; carrying {inv}."

    lines: list[str] = []
    if scene:
        lines.append(f"SCENE: {scene}")
    if time_of_day or weather:
        lines.append(f"ENVIRONMENT: it is {time_of_day or 'day'}, weather {weather or 'clear'} "
                     f"(report these back on your TurnResolution; keep them unless the story turns).")
    party = repo.party()
    if len(party) == 1:
        lines.append(f"PARTY: {_party_line(party[0])}")
    else:
        lines.append("PARTY (the player controls ALL of these heroes — address them by name/id, "
                     "call for whoever's check fits, and award XP/loot to each):")
        for p in party:
            lines.append(f"  - {_party_line(p)}")
    # CS6: the mechanical 'card(s)' — who the PC(s) are in rules terms, so the DM
    # calls for the right checks/saves and narrates rules-aware (reference only).
    lines.extend(_character_cards(repo, ruleset))
    # Only NPCs whose home is the party's current location are "present" in the
    # scene — this keeps the prompt scoped as the cast grows. An NPC with no home
    # is "nowhere in particular" and isn't placed in any scene. Everyone remains
    # retrievable via canon search regardless of where they are. When no location
    # is known (e.g. a custom seed with no pack), fall back to showing all NPCs.
    npcs = repo.npcs()
    if location is not None:
        npcs = [n for n in npcs if n.home_location == location]
    if npcs:
        lines.append("PRESENT (NPCs you may reference by id):")
        for n in npcs:
            note = n.disposition or n.description or "no notes"
            # Surface a merchant's priced stock so the DM can negotiate (it was
            # "blind to the trade window contents" otherwise).
            stock = ""
            if n.price_list:
                in_stock = {s.item_id for s in n.inventory if s.qty > 0}
                items = [f"{repo.get_item(i).name} {p}g"
                         for i, p in list(n.price_list.items())[:8] if i in in_stock]
                if items:
                    stock = "; sells " + ", ".join(items)
            lines.append(f"  - {n.name} (id: {n.id}) — {note}; carries {n.gold}g{stock}.")
    # Where the party can travel from here (exits, sublocations, neighbours). The DM
    # moves them with the travel tool, naming the destination by id.
    dests = _reachable(location, places or {})
    if dests:
        lines.append("WHERE YOU CAN GO (travel here with the travel tool, by id):")
        for d in sorted(dests, key=lambda p: p.name):
            lines.append(f"  - {d.name} (id: {d.id})")
    # Long-term memory: world canon relevant to this turn, retrieved by keyword
    # (gap G4). Stay consistent with these; provisional canon is soft.
    if canon:
        lore_hits = [r for r in canon if r.entity_type == "lore"]
        other = [r for r in canon if r.entity_type != "lore"]
        # Authored history/legend gets a generous budget (a few entries, near-full
        # text) so the DM can actually retell it, not a clipped snippet.
        if lore_hits:
            lines.append("WORLD LORE (established history/legend — treat as true; weave in as it fits):")
            for r in lore_hits[:LORE_MAX]:
                text = (r.text[:LORE_CHARS] + "…") if len(r.text) > LORE_CHARS else r.text
                lines.append(f"  - {r.name}: {text}")
        if other:
            lines.append("RELEVANT CANON (established world facts — stay consistent):")
            for r in other:
                text = (r.text[:160] + "…") if len(r.text) > 160 else r.text
                lines.append(f"  - [{r.status}] {r.entity_type} '{r.name}' (id: {r.id}){': ' + text if text else ''}")
    # Authored quest offers, two tiers. AT-SOURCE (full hook + secret briefing + reward +
    # outcomes; acceptable now) vs IN-REGION (a sparse signpost — count + place + rumor — so
    # the DM can point the party toward work without spoiling it).
    if authored_quests:
        here_ids = sorted(offered_here or set())
        npc_name = {n.id: n.name for n in repo.npcs()}
        npc_home = {n.id: n.home_location for n in repo.npcs()}
        if here_ids:
            lines.append("QUESTS OFFERED HERE (the party can take these up now — accept_quest by "
                         "id when they engage; tell the player the HOOK, never the BRIEFING):")
            for qid in here_ids:
                q = authored_quests[qid]
                src = (f"from {npc_name.get(q.giver_npc, q.giver_npc)}" if q.giver_npc is not None
                       else f"found here — {q.discovery}")
                lines.append(f"  - [{qid}] \"{q.title}\" ({src})")
                if q.hook:
                    lines.append(f"      HOOK (tell the player): {q.hook}")
                if q.briefing:
                    lines.append(f"      BRIEFING (secret — yours alone): {q.briefing}")
                reward = _reward_text(repo, q.reward)
                if reward:
                    lines.append(f"      REWARD (advisory — grant via give/transact, renegotiable): {reward}")
                if q.branches:
                    lines.append("      OUTCOMES (on resolution, update_quest status=completed with "
                                 "outcome=<one label>): " + ", ".join(b.outcome for b in q.branches))
        # In-region: eligible elsewhere in the same top-level area, not present here.
        my_region = region_root(location, places or {})
        groups: dict[str, list] = {}
        for qid in (set(offerable or set()) - set(offered_here or set())):
            q = authored_quests.get(qid)
            if q is None:
                continue
            src_loc = q.giver_place if q.giver_place is not None else npc_home.get(q.giver_npc)
            if src_loc is None or region_root(src_loc, places or {}) != my_region:
                continue
            node = (places or {}).get(src_loc)
            groups.setdefault(node.name if node is not None else src_loc, []).append(q)
        if groups:
            total = sum(len(v) for v in groups.values())
            lines.append(f"WORK AVAILABLE IN THE REGION ({total} elsewhere in this area — use ONLY to "
                         "point the party toward where work is if they look for it; do NOT reveal "
                         "details or accept until they travel there):")
            for place in sorted(groups):
                qs = groups[place]
                lines.append(f"  - {place}: {len(qs)} available")
                for q in qs:
                    if q.rumor:
                        lines.append(f"      rumor: {q.rumor}")
    # Ongoing goals the code is tracking — so the DM stays consistent about what the
    # party is pursuing and advances them (update_quest) as the fiction develops.
    if quests:
        lines.append("ACTIVE QUESTS (the party's open goals — advance with update_quest as they develop):")
        for q in quests:
            text = (q.text[:200] + "…") if len(q.text) > 200 else q.text
            latest = f" — latest: {q.notes[-1]}" if q.notes else ""
            lines.append(f"  - [{q.id}] {q.title}{': ' + text if text else ''}{latest}")
    # Short-term continuity: what just happened, so the DM honors established
    # fiction and successful checks instead of re-litigating each turn (gap G5).
    if recent:
        lines.append("RECENT TURNS (oldest first — this already happened, treat as true):")
        for beat in recent:
            lines.append(f"  - {beat}")
    return "\n".join(lines)
