"""Shared drop checks for the owner's food tests (2026-11-17). A "right meal" holds the foods he
named at about the amounts he named; extra items are fine (owner: he deletes them)."""
from __future__ import annotations

import re



def his_answers(chat_md) -> list[str]:
    """The assistant answers in one of his saved chat.md files, in order (local first, then the
    escalated Claude answer, then any follow-ups)."""
    from pathlib import Path

    parts = re.split(r"^### (You|Assistant)\s*$", Path(chat_md).read_text(encoding="utf-8"), flags=re.M)
    return [parts[i + 1].strip() for i in range(1, len(parts) - 1, 2) if parts[i] == "Assistant"]


def missing_foods(meal: dict, wanted: dict[str, float], tolerance: float = 0.25) -> list[str]:
    """Foods from `wanted` ({word: grams}) that the meal lacks, or has at the wrong amount
    (outside +-tolerance). Raw/uncooked amounts: a "cooked" rice counts as wrong."""
    out = []
    comps = meal.get("components") or []
    for word, grams in wanted.items():
        hits = [c for c in comps if re.search(rf"\b{word}", c.get("name") or "", re.IGNORECASE)]
        if not hits:
            out.append(f"{word}: missing")
            continue
        got = sum(float(c.get("quantity_g") or 0) for c in hits)
        if abs(got - grams) > grams * tolerance:
            out.append(f"{word}: {got:g} g, want ~{grams:g} g")
        if word == "rice" and any("cooked" in (c.get("name") or "").lower() and "uncooked" not in (c.get("name") or "").lower() for c in hits):
            out.append("rice: cooked, he has it uncooked")
    return out
