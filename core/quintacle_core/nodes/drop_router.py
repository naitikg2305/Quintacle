from __future__ import annotations

import base64
import re
from typing import Literal

import anthropic
from pydantic import BaseModel

from ..llm_config import DEFAULT_MODEL
from ..llm_dispatch import parse_structured
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
    "income": "income",
    "paycheck": "income",
    "statement": "statement_import",
    "bank": "statement_import",
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
    # §8: the old static investment-entry lane retired — "invest:"/"stock:"
    # now propose a REAL ledger transaction (review → POST /stocks/transactions).
    "invest": "stock_transaction",
    "stock": "stock_transaction",
    "habit": "habit_entry",
    "goal": "habit_entry",
    "budget": "habit_entry",
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


# "income: 3200 Acme paycheck on 2026-10-15" — fully deterministic field
# extraction (next-wave-plan §1 decision 3: the income prefix routes AND
# parses without a model; the amount is one number, the source is the rest).
_MONEY_RE = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?")
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_INCOME_SALARY_RE = re.compile(r"\b(salary|paycheck|pay\s*check|payroll|paystub|pay\s*stub)\b", re.IGNORECASE)


def parse_income_text(text: str) -> dict:
    """Deterministic income parse: amount = the first money-looking number,
    entry_date = an explicit YYYY-MM-DD if present (else the UI's date),
    kind = salary when salary/paycheck wording appears else other, source =
    whatever text remains. No AI call — the user reviews/edits before Save,
    same gate as everything else."""
    source = text.strip()
    # Date first — "2026" inside an ISO date must never be mistaken for the amount.
    entry_date = None
    date_match = _ISO_DATE_RE.search(source)
    if date_match:
        entry_date = date_match.group(1)
        source = (source[: date_match.start()] + source[date_match.end():]).strip()
    amount = 0.0
    money = _MONEY_RE.search(source)
    if money:
        amount = float(money.group(1).replace(",", "") + (money.group(2) or ""))
        source = (source[: money.start()] + source[money.end():]).strip()
    kind = "salary" if _INCOME_SALARY_RE.search(text) else "other"
    source = re.sub(r"\s+", " ", source).strip(" -–—,.")
    if source.lower().startswith("from "):
        source = source[5:].strip()
    if source.lower().endswith(" on"):
        source = source[:-3].strip()
    return {
        "type": "income",
        "amount": amount,
        "source": source,
        "kind": kind,
        "notes": "",
        "entry_date": entry_date,
    }


# §8's "cheap natural parse" gate for unprefixed stock text: deterministic,
# local, no API call — same philosophy as the prefix table above. CONSERVATIVE
# on purpose: a missed match just falls through to parse_journal_dump (where
# the text still lands somewhere sensible), but a false positive would hijack
# an ordinary journal line into the stock lane. Requires BOTH a trade verb and
# an unmistakably stock-shaped object: the word share(s)/stock(s), or an
# all-caps ticker-like token right before "at $N" / "@ N". "bought 10 apples
# at the store" has a verb but neither object; "stocked up on rice" has
# neither (\bstock\b doesn't match "stocked", and there's no trade verb).
_STOCK_VERB_RE = re.compile(r"\b(bought|buy|buying|sold|sell|selling|purchased)\b", re.IGNORECASE)
_STOCK_SHARES_RE = re.compile(r"\b(shares?|stocks?)\b", re.IGNORECASE)
# Deliberately case-SENSITIVE: tickers are typed uppercase ("AAPL at $150",
# "VOO @ 420"); a lowercase word before "at ..." is ordinary prose.
_STOCK_TICKER_AT_PRICE_RE = re.compile(r"\b[A-Z]{1,5}\b\s*(?:at\s+\$|@\s*\$?)\s*\d")


def looks_like_stock_transaction(text: str) -> bool:
    """True only when unprefixed text is unambiguously a stock trade — the
    /drop fall-through branch routes it to the stock lane instead of
    parse_journal_dump (whose union must NOT grow a stock type — see the
    schema-size note on _ReceiptExtraction below)."""
    if not _STOCK_VERB_RE.search(text):
        return False
    return bool(_STOCK_SHARES_RE.search(text) or _STOCK_TICKER_AT_PRICE_RE.search(text))


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


def classify_text_file_type(description: str, provider: str | None = None) -> Literal["document_entry", "kb_entry"]:
    """The PDF/DOCX equivalent of classify_image_type() above — a photo gets
    a vision call to spot the "document" kind (an ID/passport/lease/etc.);
    a PDF/DOCX has no image to look at, but describe_drop() already extracted
    its real text, so this classifies THAT instead. Only reached for an
    unprefixed non-image file drop — an explicit "document:" prefix skips
    this and goes straight to document_entry."""
    result = parse_structured(
        (
            "Decide whether this text is the content of a formal personal document — an ID, "
            "passport, visa, lease, insurance policy, certificate, warranty, or similar official "
            "paperwork someone would want to track with an expiry/renewal date — versus a general "
            "note, idea, or piece of knowledge worth remembering. Set is_document accordingly."
        ),
        description,
        _TextFileClassification,
        provider=provider,
        max_tokens=256,
    )
    return "document_entry" if result.parsed.is_document else "kb_entry"


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
