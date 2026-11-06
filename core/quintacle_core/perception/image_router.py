"""Local photo-kind routing — OCR first, then YOLO tags, then (only if still
ambiguous) the local VLM. Replaces the one cloud classification call
`drop_router.classify_image_type` used to make for every unprefixed photo
(2026-11-06, the owner's "YOLO plus OCR" decision).

Order and why:
  1. OCR text + keyword rules (deterministic, case-insensitive, tolerant of
     OCR typos via a sliding fuzzy match): a nutrition panel, a receipt and
     an ID/lease are all decided by the words printed on them — the cheapest
     and most exact signal there is.
  2. YOLOX-nano tags (perception/yolo.py, the same 80 COCO classes the
     people lens uses): food items -> prepared_meal, a bag/tie with nobody in
     frame -> outfit_item.
  3. The local VLM (qwen2.5vl:3b via local_vlm/) answers a fixed one-label
     question — only for a person-in-frame or tagless photo, where neither
     text nor tags decide.
No signal at all (no OCR engine, no tagger, no VLM) raises
LocalImageUnavailable; the policy layer turns that into "Redo with cloud?".
"""

from __future__ import annotations

import io
import logging
import re
from difflib import SequenceMatcher
from typing import Literal

logger = logging.getLogger(__name__)

ImageKind = Literal["nutrition_label", "prepared_meal", "receipt", "outfit_item", "full_outfit", "document", "generic"]

# ------------------------------------------------------------ fuzzy match

_LEET = str.maketrans({"0": "o", "1": "l", "5": "s", "|": "l", "$": "s"})


def _tokens(text: str) -> list[str]:
    """Lowercased word tokens; a token mixing letters and digits gets the
    usual OCR confusions undone (T0TAL -> total, Ca1ories -> calories)."""
    out = []
    for raw in re.findall(r"[A-Za-z0-9%|$]+", text or ""):
        tok = raw.lower()
        if re.search(r"[a-z]", tok) and re.search(r"[0-9|$]", tok):
            tok = tok.translate(_LEET)
        out.append(tok)
    return out


def fuzzy_has(text_or_tokens, phrase: str, threshold: float = 0.8) -> bool:
    """True when `phrase` (one or more words) appears in the text, allowing
    small OCR errors: each sliding window of the same word count is compared
    with difflib's ratio. Exact substring short-circuits."""
    tokens = text_or_tokens if isinstance(text_or_tokens, list) else _tokens(text_or_tokens)
    target = " ".join(_tokens(phrase))
    if not target:
        return False
    joined = " ".join(tokens)
    if re.search(rf"(?<![a-z0-9]){re.escape(target)}(?![a-z0-9])", joined):
        return True
    n = len(target.split())
    if len(target) < 5:  # short words fuzzy-match too much ("tax" ~ "tex"); exact only
        return False
    for i in range(0, max(0, len(tokens) - n + 1)):
        window = " ".join(tokens[i : i + n])
        if abs(len(window) - len(target)) > max(2, len(target) // 4):
            continue
        if SequenceMatcher(None, window, target).ratio() >= threshold:
            return True
    return False


# ------------------------------------------------------------ text rules

_LABEL_PHRASES = (
    "nutrition facts", "serving size", "calories", "total fat", "% daily value", "daily value",
    "total carbohydrate", "servings per container", "saturated fat", "dietary fiber",
    # EU / UK panels
    "nutrition information", "nutritional information", "of which saturates", "of which sugars", "per 100g",
)
_RECEIPT_PHRASES = (
    "subtotal", "sub total", "total", "tax", "change", "amount due", "balance due", "cash", "visa",
    "mastercard", "amex", "debit", "credit", "receipt", "thank you", "tip", "gratuity", "invoice",
)
_DOC_PHRASES = (
    "lease", "landlord", "tenant", "lessee", "lessor", "premises", "passport", "driver license",
    "drivers license", "driver licence", "date of birth", "dob", "expires", "expiration", "issued",
    "issue date", "insurance", "policy number", "member id", "group number", "certificate",
    "license number", "nationality", "visa", "social security", "warranty", "agreement", "signature",
    "endorsements",
)
_PRICE_LINE_RE = re.compile(r"\d+[.,]\d{2}\s*[A-Za-z*]{0,2}\s*$")
_CARD_MASK_RE = re.compile(r"(?:[*xX#]{3,}\s*\d{3,4})")
# "total" inside a nutrient name is not a receipt total.
_NUTRIENT_TOTAL_RE = re.compile(r"total\s*(?:fat|carb\w*|sugars?)", re.IGNORECASE)


def text_signals(text: str) -> dict:
    """Counts the deterministic router decides on — exposed for tests and for
    the proposal's debugging metadata."""
    text = text or ""
    tokens = _tokens(text)
    label_hits = [p for p in _LABEL_PHRASES if fuzzy_has(tokens, p)]
    receipt_tokens = _tokens(_NUTRIENT_TOTAL_RE.sub(" ", text))
    receipt_hits = [p for p in _RECEIPT_PHRASES if fuzzy_has(receipt_tokens, p, threshold=0.85)]
    doc_hits = [p for p in _DOC_PHRASES if fuzzy_has(tokens, p, threshold=0.85)]
    lines = [ln for ln in text.splitlines() if ln.strip()]
    price_lines = sum(1 for ln in lines if _PRICE_LINE_RE.search(ln))
    return {
        "label_hits": label_hits,
        "receipt_hits": receipt_hits,
        "doc_hits": doc_hits,
        "price_lines": price_lines,
        "card_mask": bool(_CARD_MASK_RE.search(text)),
        "words": len(tokens),
        "lines": len(lines),
    }


def classify_text(text: str) -> ImageKind | None:
    """Keyword decision over OCR text, or None when the text doesn't decide.
    Nutrition first (a label says "total fat"; that must never read as a
    receipt "total"), then receipt, then document."""
    s = text_signals(text)
    if len(s["label_hits"]) >= 2:
        return "nutrition_label"
    totals = {"total", "subtotal", "sub total", "amount due", "balance due"}
    has_total = bool(totals & set(s["receipt_hits"]))
    if (has_total and s["price_lines"] >= 2) or (len(s["receipt_hits"]) >= 3 and s["price_lines"] >= 1) or (
        s["card_mask"] and s["price_lines"] >= 1
    ):
        return "receipt"
    dense = s["words"] >= 40 or s["lines"] >= 8
    if len(s["doc_hits"]) >= 2 or (s["doc_hits"] and dense):
        return "document"
    return None


# ------------------------------------------------------------ tag rules

FOOD_TAGS = {"banana", "apple", "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake"}
TABLEWARE_TAGS = {"bowl", "fork", "knife", "spoon", "dining table"}
CLOTHING_TAGS = {"tie", "handbag", "backpack", "suitcase", "umbrella"}


def classify_tags(tags: list[str]) -> ImageKind | None:
    """YOLO tags -> kind, or None when they don't decide (a person in frame,
    or nothing recognizable) — that's the VLM's job."""
    tagset = set(tags or [])
    if "person" in tagset:
        return None
    if tagset & FOOD_TAGS or len(tagset & TABLEWARE_TAGS) >= 2:
        return "prepared_meal"
    if tagset & CLOTHING_TAGS:
        return "outfit_item"
    return None


def detect_photo_tags(data: bytes) -> list[str] | None:
    """YOLO object tags only (no faces, nothing persisted) — None when the
    perception deps aren't installed. Shares perceive_photo's backend switch
    (onnx desktop / tflite phone). QUINTACLE_IMAGE_TAGS=off skips it (the
    test suite sets that — YOLO weights download on first real use)."""
    import os

    from . import backend_tflite, perception_available

    if os.environ.get("QUINTACLE_IMAGE_TAGS", "").strip().lower() == "off" or not perception_available():
        return None
    try:
        from PIL import Image, ImageOps

        from .yolo import detect_tags

        backend_tflite.sync_sessions()
        img = Image.open(io.BytesIO(data))
        img.load()
        return detect_tags(ImageOps.exif_transpose(img))
    except Exception:
        logger.warning("local object tagging failed", exc_info=True)
        return None


# ------------------------------------------------------------ VLM tie-break

_VLM_LABELS: dict[str, ImageKind] = {
    "nutrition_label": "nutrition_label",
    "nutrition": "nutrition_label",
    "receipt": "receipt",
    "food": "prepared_meal",
    "meal": "prepared_meal",
    "outfit_worn": "full_outfit",
    "outfit": "full_outfit",
    "selfie": "full_outfit",
    "clothing_item": "outfit_item",
    "clothing": "outfit_item",
    "document": "document",
    "other": "generic",
}
_VLM_QUESTION = (
    "Classify this photo. Reply with exactly one label and nothing else: "
    "food (a plate/dish/food), receipt, nutrition_label, clothing_item (one garment or accessory on its own), "
    "outfit_worn (a person wearing a full outfit, e.g. a mirror selfie), document (ID, passport, lease, "
    "insurance card), other."
)


def parse_vlm_label(answer: str) -> ImageKind | None:
    low = (answer or "").lower()
    for word, kind in sorted(_VLM_LABELS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(word)}\b", low):
            return kind
    return None


def vlm_classify(data: bytes, mime: str) -> ImageKind | None:
    from ..local_vlm import describe_images_local

    answer = describe_images_local([(data, mime)], _VLM_QUESTION)
    return parse_vlm_label(answer) if answer else None


# ------------------------------------------------------------ entry point


def classify_local(data: bytes, mime: str) -> ImageKind:
    """OCR rules -> YOLO rules -> VLM label. Raises LocalImageUnavailable
    only when NO local signal source exists at all."""
    from .image_policy import LocalImageUnavailable
    from .ocr import ocr_image

    ocr = ocr_image(data)
    if ocr is not None:
        kind = classify_text(ocr.text)
        if kind is not None:
            return kind
    tags = detect_photo_tags(data)
    if tags:
        kind = classify_tags(tags)
        if kind is not None:
            return kind
    kind = vlm_classify(data, mime)
    if kind is not None:
        return kind
    if ocr is None and tags is None:
        raise LocalImageUnavailable(
            "no local OCR engine, object tagger or vision model is available — install "
            "core/requirements-ocr.txt (or the tesseract package), core/perception-requirements.txt, "
            "or run Ollama with qwen2.5vl:3b",
            what="photo",
        )
    return "generic"


__all__ = [
    "ImageKind",
    "classify_local",
    "classify_tags",
    "classify_text",
    "detect_photo_tags",
    "fuzzy_has",
    "parse_vlm_label",
    "text_signals",
    "vlm_classify",
]
