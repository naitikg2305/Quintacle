from __future__ import annotations

from pydantic import BaseModel

from ...llm_dispatch import parse_structured

_CATEGORIES = "furniture, decor, electronics, kitchen, appliance, storage, or another short lowercase category"


class HomeItemEstimate(BaseModel):
    suggested_name: str
    category: str
    location: str = ""  # room/container it's kept in, e.g. "closet, box 3" — empty if not stated
    purchase_price: float | None = None
    purchase_date: str | None = None  # YYYY-MM-DD if stated
    residence_name: str | None = None  # only if the text specifies WHICH home — else defaults to current
    notes: str = ""


def structure_home_item(description: str, known_residences: list[str], provider: str | None = None) -> HomeItemEstimate:
    """Same pattern as documents/llm.py's structure_document() — takes an
    already-extracted description (vision/PDF/DOCX/typed, via kb/drop.py's
    describe_drop) and structures it into a home inventory entry."""
    residence_hint = (
        f"Known residences: {', '.join(known_residences)}. Only set residence_name if the text "
        "clearly refers to one of these (or explicitly names a different, new one) — leave it "
        "null otherwise, it'll default to your current home."
        if known_residences
        else "No residences saved yet — leave residence_name null unless one is explicitly named."
    )
    result = parse_structured(
        (
            "Turn this into a home inventory item: a short suggested_name, category "
            f"({_CATEGORIES}), location (which room/container it's kept in, e.g. 'closet, box 3' "
            "— empty if not stated), purchase_price and purchase_date (YYYY-MM-DD) if stated, "
            f"and brief notes (what it is, why you got it). {residence_hint}"
        ),
        description,
        HomeItemEstimate,
        provider=provider,
        max_tokens=512,
    )
    return result.parsed


class ResidenceEstimate(BaseModel):
    suggested_name: str
    city: str
    address: str = ""
    moved_in: str | None = None
    moved_out: str | None = None
    notes: str = ""


def structure_residence(description: str, provider: str | None = None) -> ResidenceEstimate:
    result = parse_structured(
        (
            "Turn this into a residence/apartment record: a short suggested_name (e.g. 'Iris "
            "307' or 'Standard'), city, address if stated, moved_in and moved_out dates as "
            "YYYY-MM-DD if stated (moved_out null if still living there), and brief notes."
        ),
        description,
        ResidenceEstimate,
        provider=provider,
        max_tokens=512,
    )
    return result.parsed
