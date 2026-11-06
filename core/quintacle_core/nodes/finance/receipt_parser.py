"""Deterministic receipt parser over OCR text (2026-11-06).

The local-first image pipeline's receipt stage: perception/ocr.py reads the
receipt, THIS module pulls merchant / date / total / line items in code. Only
when no total can be found does the caller hand the OCR TEXT (not the image)
to the local text model (drop_router's local receipt path), and a total
read here always wins over the model's.

Rules:
  merchant  the first top-of-receipt line that looks like a name — not an
            address, phone, URL, date, store number or "welcome"/"receipt";
  date      first parseable date in many formats (11/05/2026, 11-05-26,
            2026-11-05, 05.11.2026, Nov 5 2026, 5 November 2026 ...); US
            month-first unless the first number can't be a month;
  total     lines saying TOTAL / AMOUNT DUE / BALANCE (DUE) / GRAND TOTAL,
            excluding SUBTOTAL / TAX / SAVINGS / CHANGE / CASH / TENDERED;
            the strongest keyword wins, and among equals the LARGEST
            plausible amount (a total can't be below the subtotal);
  items     best effort: "name ... 4.99" lines above the subtotal/total.
OCR noise: keywords match fuzzily (T0TAL, TOTAI), amounts accept "12,34"
and "12 . 34", a value pushed to the next line is picked up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher

# A price: 12.34 / 1,234.56 / OCR's "12 . 34" / EU "12,34" — never the
# middle of a dotted date ("05.11.2026").
_MONEY_RE = re.compile(r"(?<![\d.])\$?\s*(\d{1,3}(?:,\d{3})+|\d+)\s*[.,]\s*(\d{2})(?!\d)(?![./]\d)")
_LEET = str.maketrans({"0": "o", "1": "l", "5": "s", "$": "s", "|": "l"})

_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
         ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
         ("dec", "december")]
    )
    for m in names
}
_MONTH_RX = "|".join(sorted(_MONTHS, key=len, reverse=True))

# keyword -> strength (higher = more authoritative for the charged total)
_TOTAL_KEYWORDS = {
    "grand total": 4, "amount due": 4, "balance due": 4, "total due": 4, "total amount": 4, "amount paid": 3,
    "total": 3, "balance": 2, "amount": 1, "charged": 2, "sale": 1,
}
_NOT_TOTAL = ("subtotal", "sub total", "sub-total", "tax", "savings", "saved", "discount", "change", "cash",
              "tendered", "tender", "items", "item count", "tip", "points", "you saved", "rewards")
_SUBTOTAL_KEYS = ("subtotal", "sub total", "sub-total")
_TAX_KEYS = ("tax", "hst", "gst", "vat", "pst")
_NON_ITEM = ("total", "subtotal", "tax", "change", "cash", "visa", "mastercard", "amex", "debit", "credit", "card",
             "balance", "tender", "auth", "approval", "amount", "tip", "discount", "savings", "payment", "account")
_SKIP_MERCHANT = re.compile(
    r"(?i)\b(welcome|receipt|invoice|thank|store\s*#|store\s*no|tel\b|phone|www\.|\.com|http|cashier|register|"
    r"order\s*#|transaction|table|server|guest|check\s*#)"
)
_ADDRESS = re.compile(r"(?i)^\s*\d+\s+\w+.*\b(st|street|ave|avenue|rd|road|blvd|dr|drive|ln|lane|way|hwy|suite|ste)\b")
_PHONE = re.compile(r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")

_CATEGORY_RULES: tuple[tuple[re.Pattern, str, str], ...] = (
    (re.compile(r"(?i)\b(liquor|wine|spirits|brewery|brewing|taproom|pub|tavern|bar\b)"), "alcohol", "alcohol"),
    (re.compile(r"(?i)\b(grocery|groceries|market|foods?\b|supermarket|whole foods|trader joe|safeway|kroger|aldi|"
                r"wegmans|giant|publix|costco|h-?e-?b|lidl|sprouts)"), "groceries", "food"),
    (re.compile(r"(?i)\b(restaurant|cafe|café|coffee|starbucks|grill|kitchen|pizza|pizzeria|burger|taco|sushi|diner|"
                r"bistro|bakery|deli|chipotle|mcdonald|subway|eatery|noodle|ramen|bbq)"), "dining", "food"),
    (re.compile(r"(?i)\b(shell|exxon|chevron|bp\b|sunoco|mobil|gas|fuel|citgo|valero|wawa|sheetz)"), "transport", "regular"),
    (re.compile(r"(?i)\b(pharmacy|cvs|walgreens|rite aid)"), "health", "regular"),
    (re.compile(r"(?i)\b(target|walmart|amazon|best buy|apparel|clothing|outfitters|nike|adidas|uniqlo|h&m|zara|"
                r"ikea|home depot|lowe'?s)"), "shopping", "shopping"),
    (re.compile(r"(?i)\b(museum|cinema|theat(?:er|re)|tickets?|admission|park|zoo|aquarium)"), "entertainment", "experience"),
)


@dataclass
class ReceiptParse:
    merchant: str = ""
    entry_date: str | None = None  # YYYY-MM-DD
    total: float | None = None
    subtotal: float | None = None
    tax: float | None = None
    items: list[dict] = field(default_factory=list)  # [{"name", "price"}]
    category: str = ""
    kind: str = "regular"
    confidence: dict = field(default_factory=dict)


# ------------------------------------------------------------ helpers


def _norm_label(text: str) -> str:
    """Lowercased label words with OCR digit/letter confusions undone in
    mixed tokens (T0TAL -> total) and money amounts removed."""
    t = _MONEY_RE.sub(" ", text)
    toks = []
    for raw in re.findall(r"[A-Za-z0-9$|\-]+", t):
        tok = raw.lower()
        if re.search(r"[a-z]", tok) and re.search(r"[0-9$|]", tok):
            tok = tok.translate(_LEET)
        toks.append(tok)
    return " ".join(toks)


def _has_kw(label: str, kw: str) -> bool:
    if re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", label):
        return True
    if len(kw) < 5:
        return False
    n = len(kw.split())
    words = label.split()
    for i in range(0, max(0, len(words) - n + 1)):
        window = " ".join(words[i : i + n])
        if abs(len(window) - len(kw)) <= 2 and SequenceMatcher(None, window, kw).ratio() >= 0.8:
            return True
    return False


def _amounts(text: str) -> list[float]:
    return [float(m.group(1).replace(",", "") + "." + m.group(2)) for m in _MONEY_RE.finditer(text)]


def parse_date(text: str) -> str | None:
    """First plausible calendar date in the text, ISO formatted."""
    candidates: list[tuple[int, date]] = []

    def add(pos: int, y: int, m: int, d: int) -> None:
        if y < 100:
            y += 2000
        try:
            dt = date(y, m, d)
        except ValueError:
            return
        if 2000 <= dt.year <= 2100:
            candidates.append((pos, dt))

    for m in re.finditer(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", text):
        add(m.start(), int(m.group(1)), int(m.group(2)), int(m.group(3)))
    for m in re.finditer(r"(?<![\d.])(\d{1,2})([-/.])(\d{1,2})\2(\d{4}|\d{2})(?![\d])", text):
        a, b, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
        if m.group(2) == "." or a > 12:  # dotted dates are day-first (EU); 25/12 can only be D/M
            add(m.start(), y, b, a)
        else:
            add(m.start(), y, a, b)
    for m in re.finditer(rf"(?i)\b({_MONTH_RX})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", text):
        add(m.start(), int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    for m in re.finditer(rf"(?i)\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RX})\.?,?\s+(\d{{4}})\b", text):
        add(m.start(), int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    if not candidates:
        return None
    return min(candidates, key=lambda c: c[0])[1].isoformat()


def _merchant(lines: list[str]) -> str:
    for line in lines[:6]:
        clean = line.strip(" *-=#")
        letters = len(re.findall(r"[A-Za-z]", clean))
        if letters < 3 or letters < len(clean.replace(" ", "")) * 0.5:
            continue
        if _SKIP_MERCHANT.search(clean) or _ADDRESS.search(clean) or _PHONE.search(clean) or parse_date(clean):
            continue
        clean = re.sub(r"\s{2,}", " ", clean)
        return clean.title() if clean.isupper() else clean
    return ""


def guess_category(merchant: str, text: str = "") -> tuple[str, str]:
    """(category, kind) from the merchant name first, then the receipt body."""
    for source in (merchant, text):
        for rx, category, kind in _CATEGORY_RULES:
            if source and rx.search(source):
                return category, kind
    return "", "regular"


# ------------------------------------------------------------ parser


def parse_receipt(text: str) -> ReceiptParse:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    out = ReceiptParse()
    out.merchant = _merchant(lines)
    out.entry_date = parse_date(text or "")

    totals: list[tuple[int, float, int]] = []  # (strength, amount, line idx)
    first_total_idx = len(lines)
    for i, line in enumerate(lines):
        label = _norm_label(line)
        amounts = _amounts(line)
        if not amounts and i + 1 < len(lines) and not re.search(r"[a-z]{3,}", _norm_label(lines[i + 1])):
            amounts = _amounts(lines[i + 1])  # value pushed to the next row
        if not amounts:
            continue
        if any(_has_kw(label, k) for k in _SUBTOTAL_KEYS):
            out.subtotal = amounts[-1]
            first_total_idx = min(first_total_idx, i)
            continue
        if any(_has_kw(label, k) for k in _TAX_KEYS) and not _has_kw(label, "total"):
            out.tax = amounts[-1]
            continue
        if any(_has_kw(label, k) for k in _NOT_TOTAL):
            continue
        strength = max((s for k, s in _TOTAL_KEYWORDS.items() if _has_kw(label, k)), default=0)
        if strength:
            totals.append((strength, amounts[-1], i))
            first_total_idx = min(first_total_idx, i)

    plausible = [t for t in totals if 0 < t[1] < 100_000 and (out.subtotal is None or t[1] >= out.subtotal - 0.005)]
    if plausible:
        best_strength = max(t[0] for t in plausible)
        out.total = max(t[1] for t in plausible if t[0] == best_strength)
        out.confidence["total"] = 0.9 if best_strength >= 3 else 0.7
    elif out.subtotal is not None:
        # No TOTAL line read — subtotal + tax computed in code (never a model's arithmetic).
        out.total = round(out.subtotal + (out.tax or 0), 2)
        out.confidence["total"] = 0.6

    for line in lines[1:first_total_idx]:
        amounts = _amounts(line)
        if not amounts:
            continue
        label = _norm_label(line)
        if any(_has_kw(label, k) for k in _NON_ITEM) or parse_date(line):
            continue
        name = _MONEY_RE.sub(" ", line)
        name = re.sub(r"(?i)\b\d{4,}\b|\b[0-9]+\s*@|\bqty\b|\s[A-Z]$|\s[TFNX]\s*$", " ", name)
        name = re.sub(r"\s{2,}", " ", name).strip(" -*#.:")
        if len(re.findall(r"[A-Za-z]", name)) >= 2:
            out.items.append({"name": name[:60], "price": amounts[-1]})
        if len(out.items) >= 50:
            break

    out.category, out.kind = guess_category(out.merchant, text or "")
    out.confidence.setdefault("total", 0.0)
    out.confidence["merchant"] = 0.8 if out.merchant else 0.0
    out.confidence["entry_date"] = 0.9 if out.entry_date else 0.0
    return out


__all__ = ["ReceiptParse", "guess_category", "parse_date", "parse_receipt"]
