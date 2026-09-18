from __future__ import annotations

import base64
import re
from typing import Literal

import anthropic
from pydantic import BaseModel

from ..llm_config import DEFAULT_MODEL
from .journal.llm import FinanceEntry
from .vision import image_content_blocks

IMAGE_MIME_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}


def extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


# Deterministic-first, everywhere: a recognized "keyword: ..." prefix decides
# the entry TYPE without any AI call. Only when there's no prefix (or it
# doesn't resolve) does classification fall through to AI. This is the same
# principle as journal/normalize.py's canonicalize_name — local/free/instant
# beats an API call whenever the answer is already unambiguous from the text.
PREFIX_TYPES = {
    "todo": "todo",
    "task": "todo",
    "food": "food",
    "meal": "food",
    "ate": "food",
    "exercise": "exercise",
    "workout": "exercise",
    "lift": "exercise",
    "routine": "workout_routine",
    "substance": "substance",
    "drink": "substance",
    "activity": "activity",
    "weight": "body_stat",
    "finance": "finance",
    "expense": "finance",
    "spend": "finance",
    "note": "kb_entry",
    "kb": "kb_entry",
    "ingredient": "ingredient_preset",
    "preset": "ingredient_preset",
    "label": "ingredient_preset",
    "recipe": "meal_composition",
    "dish": "meal_composition",
    "item": "wardrobe_item",
    "wardrobe": "wardrobe_item",
    "outfit": "outfit_composition",
    "product": "grooming_item",
    "grooming": "grooming_routine_composition",
    "document": "document_entry",
    "doc": "document_entry",
    "home": "home_item",
    "residence": "residence_entry",
    "apartment": "residence_entry",
    "experience": "experience_entry",
    "visit": "experience_entry",
    "person": "person_entry",
    "friend": "person_entry",
    "creditcard": "credit_card_entry",
    "card": "credit_card_entry",
    "invest": "investment_entry",
    "stock": "investment_entry",
}

_PREFIX_RE = re.compile(r"^\s*([a-zA-Z]+)\s*:\s*(.*)$", re.DOTALL)


def parse_prefix(text: str) -> tuple[str, str] | None:
    """"food: had a burrito" -> ("food", "had a burrito"). None if there's no
    recognized prefix — the caller should fall through to AI classification."""
    match = _PREFIX_RE.match(text)
    if not match:
        return None
    keyword, rest = match.group(1).lower(), match.group(2).strip()
    entry_type = PREFIX_TYPES.get(keyword)
    if entry_type is None or not rest:
        return None
    return entry_type, rest


_ROUTINE_RE = re.compile(r"^\s*(.+?)\s*=\s*(.+)$", re.DOTALL)


def parse_routine_definition(text: str) -> tuple[str, list[str]] | None:
    """"Pull Day = Pull-ups, Rows, Lat Pulldown" -> ("Pull Day", ["Pull-ups",
    "Rows", "Lat Pulldown"]). No AI needed — this format is simple enough to
    just type correctly. None if the text isn't in this shape."""
    match = _ROUTINE_RE.match(text)
    if not match:
        return None
    name, rest = match.group(1).strip(), match.group(2).strip()
    exercises = [e.strip() for e in rest.split(",") if e.strip()]
    if not name or not exercises:
        return None
    return name, exercises


# Only reached for a photo drop with no recognized text prefix — the one
# classification step that can't be done deterministically, since it depends
# on what's actually in the image. Kept to a single cheap vision call with a
# fixed, small label set (not open-ended "what folder should this go in?"),
# which the rest of the routing after it stays deterministic against.
ImageKind = Literal["nutrition_label", "prepared_meal", "receipt", "outfit_item", "full_outfit", "document", "generic"]

_IMAGE_KIND_TO_ENTRY_TYPE: dict[ImageKind, str] = {
    "nutrition_label": "ingredient_preset",
    "prepared_meal": "ingredient_preset",
    "receipt": "finance",
    "outfit_item": "wardrobe_item",
    "full_outfit": "outfit_photo",
    "document": "document_entry",
    "generic": "kb_entry",
}


class _ImageClassification(BaseModel):
    kind: ImageKind


def classify_image_type(data: bytes, mime_type: str) -> ImageKind:
    """Cheap vision call distinguishing what KIND of photo this is, so the
    caller can route it without asking the user to say so manually every time."""
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=256,
        system=(
            "Classify this photo into exactly one category:\n"
            "- nutrition_label: a printed nutrition facts panel\n"
            "- prepared_meal: food/a plate/dish ready to eat\n"
            "- receipt: a purchase receipt or an invoice/bill\n"
            "- outfit_item: ONE clothing item/accessory/gear on its own (a product shot, laid flat, on a hanger)\n"
            "- full_outfit: a PERSON wearing a complete outfit (a mirror selfie, an OOTD photo) — the whole look, not a single item\n"
            "- document: an ID, passport, lease, insurance card, or other official/personal paperwork\n"
            "- generic: anything else (whiteboards, objects, scenes)"
        ),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime_type, "data": base64.standard_b64encode(data).decode()},
                    }
                ],
            }
        ],
        output_format=_ImageClassification,
    )
    return response.parsed_output.kind


def entry_type_for_image_kind(kind: ImageKind) -> str:
    return _IMAGE_KIND_TO_ENTRY_TYPE[kind]


class _TextFileClassification(BaseModel):
    is_document: bool


def classify_text_file_type(description: str) -> Literal["document_entry", "kb_entry"]:
    """The PDF/DOCX equivalent of classify_image_type() above — a photo gets
    a vision call to spot the "document" kind (an ID/passport/lease/etc.);
    a PDF/DOCX has no image to look at, but describe_drop() already extracted
    its real text, so this classifies THAT instead. Only reached for an
    unprefixed non-image file drop — an explicit "document:" prefix skips
    this and goes straight to document_entry."""
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=256,
        system=(
            "Decide whether this text is the content of a formal personal document — an ID, "
            "passport, visa, lease, insurance policy, certificate, warranty, or similar official "
            "paperwork someone would want to track with an expiry/renewal date — versus a general "
            "note, idea, or piece of knowledge worth remembering. Set is_document accordingly."
        ),
        messages=[{"role": "user", "content": description}],
        output_format=_TextFileClassification,
    )
    return "document_entry" if response.parsed_output.is_document else "kb_entry"


class _ReceiptExtraction(BaseModel):
    """Standalone, not FinanceEntry — FinanceEntry's entry_date is
    SkipJsonSchema (invisible to structured output) to keep the big
    parse_journal_dump() union under Anthropic's schema-size limit, but this
    is its own single-model call with plenty of room, so entry_date is a
    normal, real field here — a receipt's own printed date is worth reading."""

    amount: float
    merchant: str = ""
    category: str = ""
    notes: str = ""
    entry_date: str | None = None  # YYYY-MM-DD if the receipt shows a printed date
    kind: Literal["subscription", "food", "alcohol", "experience", "shopping", "big_purchase", "regular"] = "regular"


def extract_finance_from_receipt(photos: list[tuple[bytes, str]], user_description: str = "") -> FinanceEntry:
    """Vision extraction for one or two receipt/invoice photos (e.g. a long
    receipt shot in two overlapping halves) — the one finance path that
    can't be handled by the deterministic "expense: $12 at chipotle" text
    prefix, since there's no text to parse."""
    client = anthropic.Anthropic()
    content: list[dict] = image_content_blocks(photos)
    if user_description.strip():
        content.append({"type": "text", "text": user_description.strip()})
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=512,
        system=(
            "Read this receipt/invoice photo and extract the total amount charged (a single "
            "positive number, dollars), the merchant name, a short lowercase spending category "
            "guess (groceries, dining, transport, subscription, etc.), entry_date as "
            "YYYY-MM-DD if the receipt shows a printed date (leave it null if none is visible), "
            "and kind — exactly one of: subscription (a recurring bill/membership charge), food "
            "(a meal or non-alcoholic food/drink purchase), alcohol (a drink/bar tab/bottle "
            "purchase), experience (paying to do something — an activity, ticket, entrance fee), "
            "shopping (clothing, gear, everyday retail), big_purchase (a large one-off purchase — "
            "furniture, electronics, a major appliance), or regular (anything else)."
        ),
        messages=[{"role": "user", "content": content}],
        output_format=_ReceiptExtraction,
    )
    extracted = response.parsed_output
    entry = FinanceEntry(
        type="finance", amount=extracted.amount, merchant=extracted.merchant, category=extracted.category, notes=extracted.notes
    )
    entry.entry_date = extracted.entry_date
    entry.kind = extracted.kind
    return entry
