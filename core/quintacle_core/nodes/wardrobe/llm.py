from __future__ import annotations

import anthropic
from pydantic import BaseModel

from ...llm_config import DEFAULT_MODEL
from ..journal.normalize import canonicalize_name
from ..vision import image_content_blocks
from ...max_backend import cloud_client
from ...perception.image_policy import run_image_task

_ITEM_CATEGORIES = "jacket, pants, shirt, shoes, sunglasses, accessory, or another short lowercase category"


class WardrobeItemEstimate(BaseModel):
    suggested_name: str
    category: str
    description: str


_WARDROBE_CATEGORIES = ("jacket", "pants", "shirt", "shoes", "sunglasses", "accessory")
# COCO tags YOLO can see on their own -> wardrobe category (no-VLM fallback).
_WARDROBE_TAGS = {"tie": "accessory", "handbag": "accessory", "backpack": "accessory", "suitcase": "accessory", "umbrella": "accessory"}


def describe_wardrobe_item(photos: list[tuple[bytes, str]], user_description: str = "", provider: str | None = None) -> WardrobeItemEstimate:
    """Vision-based item capture — one or two photos (e.g. the item plus a
    closer shot of a label/detail) of a jacket, sunglasses, whatever, turned
    into a reusable item preset. AI used once per item; every outfit built
    from it after that is presence-only, no re-describing needed.

    2026-11-06: local-first (perception/image_policy.py) — the local VLM
    fills the fields, YOLO tags as the no-VLM fallback; cloud only on
    provider=cloud or the auto fallback."""
    from ...perception.local_describe import describe_item_local

    def local():
        fields, pipeline = describe_item_local(
            photos, noun="clothing item or accessory", categories=_WARDROBE_CATEGORIES,
            user_description=user_description, tag_categories=_WARDROBE_TAGS,
        )
        return WardrobeItemEstimate(**fields), pipeline

    return run_image_task(local, lambda: _describe_wardrobe_item_cloud(photos, user_description), what="clothing photo", provider=provider)


def _describe_wardrobe_item_cloud(photos: list[tuple[bytes, str]], user_description: str = "") -> WardrobeItemEstimate:
    client = cloud_client()
    content: list[dict] = image_content_blocks(photos)
    if user_description.strip():
        content.append({"type": "text", "text": user_description.strip()})
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=512,
        system=(
            "Describe this clothing/accessory item for a personal wardrobe library — if two "
            "photos are given, treat them as views of the SAME item (e.g. front and back, or a "
            "close-up of a label), not two different items: a short "
            f"suggested_name (e.g. brand + item, or a plain description), category ({_ITEM_CATEGORIES}), "
            "and a one-sentence description (color, material, notable details)."
        ),
        messages=[{"role": "user", "content": content}],
        output_format=WardrobeItemEstimate,
    )
    return response.parsed_output


def describe_wardrobe_item_from_text(description: str) -> WardrobeItemEstimate:
    """Text-only counterpart to describe_wardrobe_item() — for "item: black
    leather bomber jacket" typed with no photo."""
    client = cloud_client()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=512,
        system=(
            "Turn this description into a wardrobe item entry: a short suggested_name, category "
            f"({_ITEM_CATEGORIES}), and a one-sentence description."
        ),
        messages=[{"role": "user", "content": description}],
        output_format=WardrobeItemEstimate,
    )
    return response.parsed_output


class OutfitPhotoEstimate(BaseModel):
    suggested_name: str
    description: str


def describe_outfit_photo(photos: list[tuple[bytes, str]], user_description: str = "", provider: str | None = None) -> OutfitPhotoEstimate:
    """A full-outfit photo (a mirror selfie, an OOTD shot) — distinct from
    describe_wardrobe_item(), which is for a single item. Deliberately does
    NOT try to decompose the look into matched library items; the photo
    itself is the record, saved as an outfit AS IS. Local-first since
    2026-11-06 (local VLM; the owner's own words name it when no VLM runs)."""

    def local():
        from ...perception.image_policy import LocalImageUnavailable
        from ...perception.local_describe import ask_vlm, first_sentence, parse_kv

        hint = f"\nThe owner says: {user_description.strip()[:300]}" if user_description.strip() else ""
        answer = ask_vlm(
            photos,
            "This is a photo of a complete outfit being worn. Reply in exactly this format:\n"
            "NAME: <a short name for the outfit, e.g. Navy Casual Friday Fit>\n"
            "DESCRIPTION: <one sentence on the look, vibe and occasion>" + hint,
        )
        if answer:
            kv = parse_kv(answer, ("name", "description"))
            name = (kv.get("name") or first_sentence(answer, 60)).strip(" .\"'")
            return OutfitPhotoEstimate(suggested_name=name[:80], description=kv.get("description") or first_sentence(answer)), "yolo+local-vlm"
        if user_description.strip():
            return OutfitPhotoEstimate(suggested_name=user_description.strip()[:60], description=user_description.strip()), "yolo"
        raise LocalImageUnavailable("no local vision model to describe this outfit (start Ollama with qwen2.5vl:3b)", what="outfit photo")

    return run_image_task(local, lambda: _describe_outfit_photo_cloud(photos, user_description), what="outfit photo", provider=provider)


def _describe_outfit_photo_cloud(photos: list[tuple[bytes, str]], user_description: str = "") -> OutfitPhotoEstimate:
    client = cloud_client()
    content: list[dict] = image_content_blocks(photos)
    if user_description.strip():
        content.append({"type": "text", "text": user_description.strip()})
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=512,
        system=(
            "This is a photo of a complete outfit being worn (e.g. a mirror selfie). Propose a short "
            "suggested_name for it (e.g. \"Navy Casual Friday Fit\") and a one-sentence description "
            "of the look/vibe/occasion."
        ),
        messages=[{"role": "user", "content": content}],
        output_format=OutfitPhotoEstimate,
    )
    return response.parsed_output


_COMPOSER_SYSTEM_PROMPT = """You help assemble an outfit from a wardrobe item library. Given a \
description of what's wanted and the known items, list which items make it up — match names to \
the library where it's clearly the same thing (paraphrasing is fine, e.g. "my black jacket" -> \
the library's "Black Bomber Jacket"). For anything not in the library, still include it with your \
best guess at category and a short description — it'll be offered as a new item to add. Also \
propose outfit_name, a short name for the outfit."""


class OutfitComponent(BaseModel):
    name: str
    category: str
    description: str = ""


class OutfitSuggestion(BaseModel):
    outfit_name: str
    items: list[OutfitComponent]


def suggest_outfit(description: str, known_items: list[dict]) -> OutfitSuggestion:
    client = cloud_client()
    if known_items:
        library = "Known wardrobe items:\n" + "\n".join(
            f"name={i['name']!r} category={i['category']!r}" for i in known_items
        )
    else:
        library = "Known wardrobe items: (none saved yet)"
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=2048,
        system=_COMPOSER_SYSTEM_PROMPT + "\n\n" + library,
        messages=[{"role": "user", "content": description}],
        output_format=OutfitSuggestion,
    )
    return response.parsed_output


def resolve_outfit(suggestion: OutfitSuggestion, known_items: list[dict]) -> dict:
    """Deterministic pass, not AI — same fuzzy-match-against-the-real-library
    pattern as meal composition's resolve_composition(). A match means this
    item already exists (reused as-is); only genuinely new items need creating."""
    known_names = [i["name"] for i in known_items]
    by_name = {i["name"]: i for i in known_items}
    resolved = []
    for item in suggestion.items:
        matched_name = canonicalize_name(item.name, known_names)
        existing = by_name.get(matched_name)
        if existing is not None:
            resolved.append({"name": existing["name"], "category": existing["category"], "is_new": False})
        else:
            resolved.append({"name": item.name, "category": item.category, "description": item.description, "is_new": True})
    return {"outfit_name": suggestion.outfit_name, "items": resolved}
