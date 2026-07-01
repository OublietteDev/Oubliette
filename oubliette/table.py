"""The table contract: a per-campaign agreement between the player and the DM.

It carries the *tone of the telling* plus the player's content boundaries — LINES
(ruled out entirely) and VEILS (kept off the page, faded to black). This is
configuration, NOT state the DM owns: code stores it (event-sourced like the
environment, see `record/events.CONTRACT_SET`) and feeds it into the DM's system
prompt every turn. The DM honors it; it never sets it — the firewall holds.
"""

from __future__ import annotations

from pydantic import BaseModel

# Canonical tone presets: label -> a sentence of narration guidance appended to the
# DM's system prompt. "Balanced" is the neutral default (no extra instruction);
# "Custom" is special — it uses the contract's own free `tone_text`.
TONE_PRESETS: dict[str, str] = {
    "Balanced": "",
    "Cinematic": "Tell it cinematically: vivid sensory detail, momentum, and a sense of spectacle.",
    "Gritty": "Keep it gritty and grounded: lean prose, real stakes, consequences that land hard.",
    "Whimsical": "Keep it light and whimsical: warmth, wit, and room for the absurd.",
    "Ominous": "Keep it ominous: tension and a quiet dread threaded under every scene.",
    "Storybook": "Tell it like classic high fantasy: a mythic, storybook cadence — archetypes and wonder.",
    "Custom": "",
}


class TableContract(BaseModel):
    """A campaign's session-zero agreement. All fields are optional; an all-default
    contract renders to nothing, so the DM simply runs with its own voice."""

    tone_label: str = "Balanced"
    tone_text: str = ""           # resolved guidance sentence (preset text, or the custom one)
    lines: list[str] = []         # hard no's — never depicted, on screen or off
    veils: list[str] = []         # portrayed only obliquely — fade to black
    freeform: str = ""            # anything else the player asked for

    def resolved_tone(self) -> str:
        """The tone sentence to inject: the custom text for 'Custom', else the preset."""
        if self.tone_label == "Custom":
            return self.tone_text.strip()
        return TONE_PRESETS.get(self.tone_label, "").strip()


DEFAULT_TABLE = TableContract()


def normalize_contract(table: TableContract) -> TableContract:
    """Tidy a contract for storage: snap `tone_text` to the chosen preset (so what's
    stored is always the *effective* tone), drop blank list entries, trim text. A
    'Custom' tone keeps its own author-written `tone_text`; an unknown label falls
    back to 'Balanced'."""
    label = table.tone_label if table.tone_label in TONE_PRESETS else "Balanced"
    tone_text = table.tone_text.strip() if label == "Custom" else TONE_PRESETS[label]
    return TableContract(
        tone_label=label,
        tone_text=tone_text,
        lines=[s.strip() for s in table.lines if s.strip()],
        veils=[s.strip() for s in table.veils if s.strip()],
        freeform=table.freeform.strip(),
    )


def render_table_prompt(table: TableContract) -> str:
    """The system-prompt addendum for a campaign's table contract. Returns '' when
    there is nothing to say, so a default table adds no prompt weight."""
    tone = table.resolved_tone()
    if not tone and not (table.lines or table.veils or table.freeform.strip()):
        return ""
    out = ["\n--- THE TABLE (this campaign's agreement with the player — honor it every scene) ---"]
    if tone:
        out.append(f"TONE: {tone}")
    if table.lines:
        out.append(
            "LINES — content the player has ruled OUT entirely. Never depict it, on screen or "
            "off; steer the fiction so it simply does not arise: " + "; ".join(table.lines) + ".")
    if table.veils:
        out.append(
            "VEILS — content to keep off the page: if the story approaches it, cut away or fade "
            "to black rather than portraying it: " + "; ".join(table.veils) + ".")
    if table.freeform.strip():
        out.append(f"ALSO: {table.freeform.strip()}")
    if table.lines or table.veils:
        out.append(
            "If the player repeatedly forces past these agreed limits — not an honest in-fiction "
            "turn, but bulldozing the boundary — that is bad faith, and force_end_session is available.")
    return "\n".join(out)
