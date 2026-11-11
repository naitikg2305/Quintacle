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
from ..max_backend import cloud_client

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


# 2026-11-11: unprefixed income ("got paid $3,200 from Minfy today"). The
# journal union has no income type (and must not grow one — schema-size
# limit, see _ReceiptExtraction), so a model could only answer "expense".
# Same pattern as the stock gate below: a deterministic, CONSERVATIVE regex
# gate, then the income: prefix's own deterministic parse. Every phrase is
# unambiguously money IN; bare "salary"/"paycheck" mentions ("spent $200 of
# my salary") are NOT enough — they need a receiving verb next to them.
_INCOME_PHRASE_RE = re.compile(
    r"\b(?:got|been|just got|finally got) paid\b"
    r"|\b(?:got|received|deposited|cashed)\s+(?:my|the|a|this\s+\w+'?s?)?\s*(?:pay\s*check|salary|paycheque|wages|bonus)\b"
    r"|\b(?:pay\s*check|salary|paycheque|wages|bonus)\s+(?:came in|came through|hit|landed|arrived|cleared|(?:was |got )?deposited)\b"
    r"|\bpayday\b|\bdirect deposit\b"
    r"|\b(?:received|got|earned|made)\s+\$\s?\d[\d,]*(?:\.\d{1,2})?(?:k\b)?\s+(?:\w+\s+)?from\b"
    r"|\binvoice\s+(?:\w+\s+)?(?:was|got|has been)\s+paid\b",
    re.IGNORECASE,
)
_INCOME_AMOUNT_RE = re.compile(r"\$\s?\d|\b\d[\d,]*(?:\.\d{1,2})?\s*(?:dollars|usd|bucks)\b|\b\d{1,3}(?:,\d{3})+\b|\b\d{3,}\b", re.IGNORECASE)
_INCOME_SOURCE_RE = re.compile(
    r"\bfrom\s+(.+?)(?=\s+(?:today|yesterday|tonight|this\s+\w+|last\s+\w+|on|for|via|into|to|and|but)\b|[,.;!\n]|$)",
    re.IGNORECASE,
)
_INCOME_YESTERDAY_RE = re.compile(r"\byesterday\b", re.IGNORECASE)


def looks_like_income(text: str) -> bool:
    """True only when unprefixed text unambiguously reports money received
    (a receiving phrase AND an amount). /drop's plain-text fall-through then
    proposes the same entry the income: prefix would."""
    return bool(text and _INCOME_PHRASE_RE.search(text) and _INCOME_AMOUNT_RE.search(text))


def parse_income_natural(text: str, reference_date=None) -> dict:
    """parse_income_text (the income: prefix's parse: amount, kind, ISO
    date) plus a cleaner source for prose: "from <payer>" when present, and
    "yesterday" resolved against the drop's reference date. "today" stays
    None (= the day picked in the UI), exactly like the prefix lane."""
    entry = parse_income_text(text)
    match = _INCOME_SOURCE_RE.search(text)
    if match and match.group(1).strip(" -–—,.$"):
        entry["source"] = match.group(1).strip(" -–—,.")
    else:
        entry["source"] = re.sub(r"\b(?:just |finally )?(?:got|been) paid\b|\b(?:today|yesterday)\b", "", entry["source"], flags=re.IGNORECASE)
        entry["source"] = re.sub(r"\s+", " ", entry["source"]).strip(" -–—,.")
    if entry["entry_date"] is None and reference_date is not None and _INCOME_YESTERDAY_RE.search(text):
        from datetime import timedelta

        entry["entry_date"] = (reference_date - timedelta(days=1)).isoformat()
    return entry


# 2026-11-11: the ingredient: prefix's NAME is the food, not the label text.
# "Fage 0% greek yogurt, per 170g: 90 kcal, 18g protein" -> "Fage 0% greek
# yogurt". Deterministic: cut at the earliest label marker — "per ..."
# wording, "macros"/"nutrition facts"/"serving size", a colon, or the first
# nutrient-number ("90 kcal", "18g protein", "protein 18g", "170g"). A "0%"
# or "2%" stays (percent is part of the product name).
_INGREDIENT_NAME_CUT_RE = re.compile(
    r"[,;(]?\s*\b(?:per|macros?|nutrition(?:al)?|serving size|contains)\b"
    r"|:"
    r"|[,;(]?\s*\b\d+(?:\.\d+)?\s*(?:g|grams?|kg|oz|ml|kcal|cal|calories)\b"
    r"|[,;(]?\s*\b(?:calories|kcal|protein|carbs?|fat|fib(?:er|re))\s*[:=-]?\s*\d",
    re.IGNORECASE,
)


def ingredient_name_from_text(text: str) -> str:
    """The food name in typed ingredient/label text, or "" when the text
    starts straight with label wording (caller falls back)."""
    first_line = (text or "").strip().split("\n", 1)[0]
    match = _INGREDIENT_NAME_CUT_RE.search(first_line)
    name = first_line[: match.start()] if match else first_line
    return re.sub(r"\s+", " ", name).strip(" -–—,.;:(")[:60].strip()


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


# --- additive preset suggestion gate ------------------------------------
# Unprefixed text that DEFINES a reusable thing (a recipe, a routine, an
# ingredient/label) deserves a preset proposal alongside the normal result.
# Pure regexes, zero model calls, conservative: ambiguity -> None. The preset
# types must NEVER join parse_journal_dump's union (schema-size limit — see
# the _ReceiptExtraction note below); /drop appends them additively instead.

_UNIT = r"(?:g|grams?|kg|oz|ounces?|lbs?|cups?|tbsp|tsp|tablespoons?|teaspoons?|ml)"
_QTY = rf"\d+(?:\.\d+)?\s*{_UNIT}\b"
_NON_FOOD = {
    "protein", "carbs", "carb", "carbohydrate", "carbohydrates", "fat", "fats", "fiber", "fibre", "sugar", "sugars",
    "sodium", "kcal", "calories", "cholesterol", "x", "for", "on", "at", "and", "each", "per", "with", "to", "in",
    "today", "reps", "rep", "sets", "set", "the", "a", "of",
}
_FOOD_AFTER_QTY_RE = re.compile(rf"(?<![\w.]){_QTY}\.?\s*(?:of\s+)?([a-z][a-z'-]{{2,}})", re.IGNORECASE)
_FOOD_BEFORE_QTY_RE = re.compile(rf"([a-z][a-z'-]{{2,}})\s*[:=-]?\s*{_QTY}", re.IGNORECASE)
_NUTRIENT_NUM_RE = re.compile(
    r"\b(calories|kcal|protein|carb(?:ohydrate)?s?|total fat|fat|fib(?:er|re)|sugars?|sodium)\b\s*[:=-]?\s*\d",
    re.IGNORECASE,
)
_LABEL_WORDING_RE = re.compile(
    r"\b(?:nutrition(?:al)? (?:facts|label|info)|serving size|macros? per|per\s+(?:100\s*g|100\s*grams|serving))\b",
    re.IGNORECASE,
)
_RECIPE_WORDING_RE = re.compile(r"\b(?:recipe|my usual|my go-?to|i (?:usually |always )?make|ingredients)\b", re.IGNORECASE)
_SETREP_RE = re.compile(r"\b\d+\s*[x×]\s*\d+\b|\b\d+\s*sets?\s*(?:of|x|×)\s*\d+\b", re.IGNORECASE)
_ROUTINE_STRONG_RE = re.compile(r"\b(?:routine|split|workout plan|ppl)\b|\bday\s*\d+\s*:", re.IGNORECASE)
_DAY_NAME_RE = re.compile(r"\b(?:push|pull|leg|upper|lower|chest|back|arm|shoulder)s?\s+day\b", re.IGNORECASE)
_DEFINED_LIST_RE = re.compile(r"[:=]\s*(.+)$", re.DOTALL)


def _food_quantity_count(text: str) -> int:
    best = 0
    for rx in (_FOOD_AFTER_QTY_RE, _FOOD_BEFORE_QTY_RE):
        best = max(best, sum(1 for m in rx.finditer(text) if m.group(1).lower() not in _NON_FOOD))
    return best


def _setrep_segments(text: str) -> int:
    """Segments (lines / commas / semicolons) naming an exercise AND carrying a sets x reps shape."""
    return sum(
        1
        for seg in re.split(r"[\n;,]+", text)
        if _SETREP_RE.search(seg) and re.search(r"[A-Za-z]{3,}", _SETREP_RE.sub("", seg))
    )


def _defined_list_items(text: str) -> int:
    m = _DEFINED_LIST_RE.search(text)
    return len([i for i in re.split(r"[\n,+]+", m.group(1)) if i.strip()]) if m else 0


def looks_like_preset(text: str) -> Literal["meal_composition", "workout_routine", "ingredient_preset"] | None:
    """Which reusable preset (if any) unprefixed text is confidently defining.
    Order matters: a nutrition label also carries many 'Ng' quantities, so
    ingredient_preset is checked before meal_composition. A single logged set
    ("bench 3x8 today") or meal ("ate a burrito") is a LOG, never a preset."""
    if not text or not text.strip():
        return None
    qty = _food_quantity_count(text)
    nutrients = len({m.group(1).lower()[:4] for m in _NUTRIENT_NUM_RE.finditer(text)})
    label = bool(_LABEL_WORDING_RE.search(text))
    # 2026-11-07 fix: a planned meal pasted from chat lists several foods WITH
    # amounts and usually a nutrition summary ("protein 45 g, 650 kcal…" —
    # the USDA chat lane makes that common). 3+ food quantities without real
    # label wording ("Nutrition Facts", "Serving size") is a MEAL, not a label.
    if qty >= 3 and not label:
        return "meal_composition"
    if nutrients >= 3 or (label and nutrients >= 1) or (label and qty < 3 and re.search(r"\d", text)):
        return "ingredient_preset"
    setrep = _setrep_segments(text)
    if (
        setrep >= 2
        or (_ROUTINE_STRONG_RE.search(text) and (setrep >= 1 or _defined_list_items(text) >= 3))
        or (_DAY_NAME_RE.search(text) and _defined_list_items(text) >= 3)
    ):
        return "workout_routine"
    if qty >= 3 or (qty >= 2 and _RECIPE_WORDING_RE.search(text)):
        return "meal_composition"
    return None


_ROUTINE_RE = re.compile(r"^\s*(.+?)\s*=\s*(.+)$", re.DOTALL)
_SET_SCHEME_RE = re.compile(
    r"\s*[-–—:(]?\s*(?:\d+\s*[x×]\s*\d+(?:\s*-\s*\d+)?|\d+\s*sets?\s*(?:of|x)\s*\d+(?:\s*-\s*\d+)?(?:\s*reps?)?)\s*\)?\s*$",
    re.IGNORECASE,
)


def strip_set_scheme(exercise: str) -> str:
    """'Bench Press 4x8' -> 'Bench Press'. A routine preset holds exercise
    NAMES — routine expansion and the exercise registry match on them, so a
    trailing set/rep scheme must never become part of the name."""
    stripped = _SET_SCHEME_RE.sub("", exercise).strip()
    return stripped or exercise.strip()


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
# [2026-11-06: no longer a cloud call by default — classify_image_type runs
# OCR keyword rules -> YOLO tags -> a local VLM label first; see
# perception/image_router.py and image_policy.py.]
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


def classify_image_type(data: bytes, mime_type: str, provider: str | None = None) -> ImageKind:
    """Distinguishes what KIND of photo this is, so the caller can route it
    without asking the user to say so manually every time.

    2026-11-06: local-first (perception/image_policy.py, default local) —
    OCR keyword rules, then YOLO tags, then a one-label local VLM question
    (perception/image_router.py). The cloud vision call below runs only for
    provider=cloud (Redo with cloud) or as the auto fallback."""
    from ..perception.image_policy import run_image_task
    from ..perception.image_router import classify_local

    return run_image_task(
        lambda: (classify_local(data, mime_type), None),
        lambda: _classify_image_type_cloud(data, mime_type),
        what="photo",
        provider=provider,
    )


def _classify_image_type_cloud(data: bytes, mime_type: str) -> ImageKind:
    client = cloud_client()
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


# 2026-11-11: since PDFs are read locally (raw text, not a cloud summary),
# qwen3:8b called a 4-page trip plan "formal paperwork" (flights + bookings
# read official). Plans/itineraries/tickets/bookings are never vault
# documents — caught here in code before any model call.
_TRIP_PLAN_RE = re.compile(
    r"\b(itinerar(y|ies)|trip plan|travel plan|day\s*1\b|day one\b|boarding pass|e-?ticket|"
    r"flight (number|details|itinerary)|booking (reference|confirmation|status)|"
    r"confirmation (number|code)|check-?in\b|depart(s|ure)?\b.*\barriv(e|al|es))",
    re.IGNORECASE,
)
# Real vault paperwork names itself — kept out of the trip shortcut.
_DOCUMENT_WORD_RE = re.compile(
    r"\b(passport|visa|driver'?s licen[cs]e|lease agreement|rental agreement|insurance policy|"
    r"policy number|certificate of|warranty|birth certificate|green card|permanent resident)\b",
    re.IGNORECASE,
)
_CLASSIFY_HEAD_CHARS = 3000

_TEXT_FILE_SYSTEM = (
    "Decide whether this text is a FORMAL PERSONAL DOCUMENT to keep in a document vault. "
    "A document is official paperwork tied to the person, usually with an ID number and an "
    "issue/expiry/renewal date: passport, visa, ID card, driver's license, residence permit, "
    "lease or rental agreement, insurance policy, certificate, warranty, contract. "
    "NOT documents (is_document=false): travel plans and itineraries, flight/train tickets and "
    "bookings, hotel reservations, receipts, bank statements, articles, lecture notes, recipes, "
    "research, plans, ideas, or any general note. When unsure, answer false."
)


def classify_text_file_type(description: str, provider: str | None = None) -> Literal["document_entry", "kb_entry"]:
    """The PDF/DOCX equivalent of classify_image_type() above — a photo gets
    a vision call to spot the "document" kind (an ID/passport/lease/etc.);
    a PDF/DOCX has no image to look at, but describe_drop() already extracted
    its real text, so this classifies THAT instead. Only reached for an
    unprefixed non-image file drop — an explicit "document:" prefix skips
    this and goes straight to document_entry. [2026-11-11: deterministic
    trip-plan/ticket shortcut first; the model sees only the head of the
    text with explicit negatives, since local PDF reading now hands it raw
    text instead of a cloud summary.]"""
    head = description[:_CLASSIFY_HEAD_CHARS]
    if _TRIP_PLAN_RE.search(head) and not _DOCUMENT_WORD_RE.search(head):
        return "kb_entry"
    result = parse_structured(
        _TEXT_FILE_SYSTEM,
        head,
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


_RECEIPT_TEXT_SYSTEM = (
    "You are given OCR text read from a photographed receipt/invoice (it may contain OCR errors). "
    "Extract the total amount charged (a single positive number, dollars — the final total, not the "
    "subtotal or cash tendered), the merchant name, a short lowercase spending category guess "
    "(groceries, dining, transport, subscription, etc.), entry_date as YYYY-MM-DD if a date is printed "
    "(null if none), and kind — one of subscription, food, alcohol, experience, shopping, big_purchase, "
    "regular. Only transcribe; never compute."
)


def _receipt_entry(amount: float, merchant: str, category: str, notes: str, entry_date: str | None, kind: str) -> FinanceEntry:
    entry = FinanceEntry(type="finance", amount=amount, merchant=merchant, category=category, notes=notes)
    entry.entry_date = entry_date
    entry.kind = kind
    return entry


def _extract_receipt_local(photos: list[tuple[bytes, str]], user_description: str) -> tuple[FinanceEntry, str]:
    """OCR every photo (a long receipt shot in two halves reads as one text),
    parse in code; the local TEXT model sees the OCR text only when code
    found no total — and code's merchant/date still win."""
    from ..perception.image_policy import LocalImageUnavailable
    from ..perception.ocr import ocr_image
    from .finance.receipt_parser import parse_receipt

    readings = [r for r in (ocr_image(data) for data, _mime in photos) if r is not None and r.text.strip()]
    if not readings:
        raise LocalImageUnavailable("no readable text found by local OCR (or no OCR engine installed)", what="receipt")
    text = "\n".join(r.text for r in readings)
    # 2026-11-07: hand the parser the deskewed per-fragment boxes so it pairs
    # each price with the label on its own visual row (two-column receipts).
    # Two photos (a long receipt in halves) stack: the second's boxes are
    # shifted below the first's.
    fragments: list = []
    if all(r.fragments for r in readings):
        offset = 0.0
        for r in readings:
            fragments += [(f.text, (f.box[0], f.box[1] + offset, f.box[2], f.box[3]), f.conf) for f in r.fragments]
            offset = max(f[1][1] + f[1][3] for f in fragments) + 100.0
    parsed = parse_receipt(text, fragments or None)
    items = ", ".join(f"{i['name']} ({i['price']:.2f})" for i in parsed.items[:8])
    notes = user_description.strip() or (f"Items: {items}" if items else "")
    if parsed.total is not None:
        return _receipt_entry(parsed.total, parsed.merchant, parsed.category, notes[:300], parsed.entry_date, parsed.kind), "ocr+parser"
    content = text + (f"\n\nThe owner adds: {user_description.strip()}" if user_description.strip() else "")
    model = parse_structured(_RECEIPT_TEXT_SYSTEM, content, _ReceiptExtraction, provider="local", max_tokens=512).parsed
    return (
        _receipt_entry(
            model.amount,
            parsed.merchant or model.merchant,
            parsed.category or model.category,
            notes[:300] or model.notes,
            parsed.entry_date or model.entry_date,
            parsed.kind if parsed.kind != "regular" else model.kind,
        ),
        "ocr+local-llm",
    )


def extract_finance_from_receipt(photos: list[tuple[bytes, str]], user_description: str = "", provider: str | None = None) -> FinanceEntry:
    """Extraction for one or two receipt/invoice photos (e.g. a long
    receipt shot in two overlapping halves) — the one finance path that
    can't be handled by the deterministic "expense: $12 at chipotle" text
    prefix, since there's no typed text to parse.

    2026-11-06: local-first — OCR + nodes/finance/receipt_parser.py, the
    local text model over the OCR text only when no total is found; the
    cloud vision call runs only for provider=cloud or the auto fallback."""
    from ..perception.image_policy import run_image_task

    return run_image_task(
        lambda: _extract_receipt_local(photos, user_description),
        lambda: _extract_receipt_cloud(photos, user_description),
        what="receipt",
        provider=provider,
    )


def _extract_receipt_cloud(photos: list[tuple[bytes, str]], user_description: str = "") -> FinanceEntry:
    client = cloud_client()
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
