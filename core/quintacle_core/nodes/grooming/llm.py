from __future__ import annotations

import anthropic
from pydantic import BaseModel

from ...llm_config import DEFAULT_MODEL
from ..journal.normalize import canonicalize_item_name
from ..vision import image_content_blocks
from ...llm_dispatch import parse_structured
from ...max_backend import cloud_client
from ...perception.image_policy import run_image_task

_ITEM_CATEGORIES = "skincare, haircare, shaving, oral, fragrance, tool, or another short lowercase category"


class GroomingItemEstimate(BaseModel):
    suggested_name: str
    category: str
    description: str


_GROOMING_CATEGORIES = ("skincare", "haircare", "shaving", "oral", "fragrance", "tool")
# Printed-label words -> category, for the no-VLM OCR fallback (first hit wins).
_GROOMING_KEYWORDS = {
    "shampoo": "haircare", "conditioner": "haircare", "hair": "haircare", "pomade": "haircare",
    "toothpaste": "oral", "mouthwash": "oral", "floss": "oral", "fluoride": "oral",
    "aftershave": "shaving", "shave": "shaving", "shaving": "shaving", "razor": "shaving",
    "parfum": "fragrance", "cologne": "fragrance", "eau de": "fragrance", "fragrance": "fragrance",
    "cleanser": "skincare", "moisturiz": "skincare", "serum": "skincare", "spf": "skincare", "sunscreen": "skincare",
    "lotion": "skincare", "cream": "skincare", "retinol": "skincare", "toner": "skincare",
}


def describe_grooming_item(photos: list[tuple[bytes, str]], user_description: str = "", provider: str | None = None) -> GroomingItemEstimate:
    """Vision-based product capture — one or two photos (e.g. the front of
    the bottle plus its ingredients label) turned into a reusable grooming
    item preset. AI used once per product; every routine built from it after
    that is presence-only, no re-describing.

    2026-11-06: local-first — OCR reads the bottle's printed name (a hint to
    the local VLM, and the whole answer when no VLM is running)."""
    from ...perception.local_describe import describe_item_local

    def local():
        fields, pipeline = describe_item_local(
            photos, noun="grooming product", categories=_GROOMING_CATEGORIES,
            user_description=user_description, category_keywords=_GROOMING_KEYWORDS, use_ocr=True,
        )
        return GroomingItemEstimate(**fields), pipeline

    return run_image_task(local, lambda: _describe_grooming_item_cloud(photos, user_description), what="product photo", provider=provider)


def _describe_grooming_item_cloud(photos: list[tuple[bytes, str]], user_description: str = "") -> GroomingItemEstimate:
    client = cloud_client()
    content: list[dict] = image_content_blocks(photos)
    if user_description.strip():
        content.append({"type": "text", "text": user_description.strip()})
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=512,
        system=(
            "Describe this grooming product for a personal grooming library — if two photos are "
            "given, treat them as views of the SAME product (e.g. front and a label), not two "
            f"different products: a short suggested_name (brand + product), category ({_ITEM_CATEGORIES}), "
            "and a one-sentence description (what it's for, notable details)."
        ),
        messages=[{"role": "user", "content": content}],
        output_format=GroomingItemEstimate,
    )
    return response.parsed_output


def describe_grooming_item_from_text(description: str, provider: str | None = None) -> GroomingItemEstimate:
    """Text-only counterpart to describe_grooming_item() — for "product:
    CeraVe foaming cleanser" typed with no photo.

    2026-11-11: local-first like every other text parse (llm_dispatch) —
    cloud only on provider=cloud ("Redo with cloud") or the auto fallback."""
    system = (
        "Turn this description into a grooming item entry: a short suggested_name, category "
        f"({_ITEM_CATEGORIES}), and a one-sentence description."
    )
    return parse_structured(system, description, GroomingItemEstimate, provider=provider, max_tokens=512).parsed


_COMPOSER_SYSTEM_PROMPT = """You help assemble a grooming routine from a product library. Given \
a description of what's wanted and the known products, list the steps IN ORDER — match names to \
the library where it's clearly the same thing (paraphrasing is fine, e.g. "my face wash" -> the \
library's "CeraVe Foaming Cleanser"). For anything not in the library, still include it with your \
best guess at category and a short description — it'll be offered as a new product to add. Also \
propose routine_name, a short name for the routine (e.g. "AM Routine", "PM Routine")."""


class GroomingRoutineComponent(BaseModel):
    name: str
    category: str
    description: str = ""


class GroomingRoutineSuggestion(BaseModel):
    routine_name: str
    steps: list[GroomingRoutineComponent]


def suggest_grooming_routine(description: str, known_items: list[dict], provider: str | None = None) -> GroomingRoutineSuggestion:
    """2026-11-11: local-first via llm_dispatch (was cloud-only); the
    deterministic resolve step below matches names to the library."""
    if known_items:
        library = "Known grooming products:\n" + "\n".join(
            f"name={i['name']!r} category={i['category']!r}" for i in known_items
        )
    else:
        library = "Known grooming products: (none saved yet)"
    return parse_structured(_COMPOSER_SYSTEM_PROMPT + "\n\n" + library, description, GroomingRoutineSuggestion, provider=provider, max_tokens=2048).parsed


def resolve_grooming_routine(suggestion: GroomingRoutineSuggestion, known_items: list[dict]) -> dict:
    """Deterministic pass, not AI — same fuzzy-match-against-the-real-library
    pattern as meal/outfit composition. A match means this product already
    exists (reused as-is, order preserved); only genuinely new products need
    creating."""
    known_names = [i["name"] for i in known_items]
    by_name = {i["name"]: i for i in known_items}
    resolved = []
    for step in suggestion.steps:
        matched_name = canonicalize_item_name(step.name, known_names)
        existing = by_name.get(matched_name)
        if existing is not None:
            resolved.append({"name": existing["name"], "category": existing["category"], "is_new": False})
        else:
            resolved.append({"name": step.name, "category": step.category, "description": step.description, "is_new": True})
    return {"routine_name": suggestion.routine_name, "steps": resolved}
