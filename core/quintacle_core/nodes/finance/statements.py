"""Statement drops (next-wave-plan §2b, decided 2026-10-19): CSV and OFX/QFX
bank/card statements parsed DETERMINISTICALLY — stdlib csv + a hand-rolled
reader for the tiny SGML/XML subset real OFX files use. No model, no
third-party aggregator, no credentials, no new dependency in
core/requirements.txt. PDF statements go through the existing cloud vision
lane instead (see llm.extract_statement_transactions); every path lands in
the same propose -> review -> Save gate.

A parsed transaction is a plain dict:
    {date: "YYYY-MM-DD", amount: positive dollars spent, merchant, notes,
     kind: one of the 7 expense kinds (deterministic keyword guess,
     user-editable at review), duplicate: bool, include: bool}
Credits/payments/refunds are skipped (counted in skipped_credits) — the
spend ledger is what statements feed; income is its own lane ("income:"
drop prefix).
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime

from ...graph import title_mentioned

STATEMENT_EXTENSIONS = {"csv", "ofx", "qfx"}

# --- dates -------------------------------------------------------------------

_DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%m-%d-%Y", "%b %d, %Y", "%B %d, %Y"]


def parse_statement_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


# --- kind guessing -----------------------------------------------------------

# Deterministic whole-word keyword lists (THE matcher, graph.title_mentioned)
# — a first guess the review UI lets you correct, never a model call. Kept
# deliberately conservative: anything unmatched stays "regular".
_KIND_KEYWORDS: list[tuple[str, list[str]]] = [
    ("subscription", ["netflix", "spotify", "hulu", "subscription", "membership", "patreon", "icloud", "prime video", "disney"]),
    ("alcohol", ["bar", "brewery", "liquor", "wine", "winery", "pub", "taproom", "distillery"]),
    ("food", [
        "restaurant", "grill", "cafe", "coffee", "pizza", "chipotle", "doordash", "grubhub", "ubereats",
        "bakery", "kitchen", "taco", "sushi", "deli", "burger", "starbucks", "grocery", "market",
    ]),
    ("experience", ["cinema", "theater", "theatre", "museum", "golf", "bowling", "tickets", "ticketmaster"]),
    ("shopping", ["amazon", "target", "nordstrom", "uniqlo", "zara", "best buy", "ikea"]),
]


def guess_kind(merchant: str, notes: str = "") -> str:
    text = f"{merchant} {notes}"
    for kind, keywords in _KIND_KEYWORDS:
        if any(title_mentioned(kw, text) for kw in keywords):
            return kind
    return "regular"


# --- CSV ---------------------------------------------------------------------

_HEADER_HINTS: dict[str, list[str]] = {
    # field -> header substrings tried in order; first header containing one wins
    "date": ["transaction date", "posted date", "post date", "posting date", "trans date", "date"],
    "merchant": ["description", "merchant", "payee", "name", "details"],
    "amount": ["transaction amount", "amount", "amt"],
    "debit": ["debit", "withdrawal"],
    "credit": ["credit", "deposit"],
    "notes": ["memo", "note", "category"],
}


def guess_csv_mapping(headers: list[str]) -> dict:
    """Column-mapping guess from header names — surfaced in the review UI for
    the user to correct, then re-parsed. Returns header NAMES (not indexes)
    so the mapping survives column reordering between statements."""
    lowered = [h.strip().lower() for h in headers]

    def pick(field: str, exclude: set[str]) -> str | None:
        for hint in _HEADER_HINTS[field]:
            for header, low in zip(headers, lowered):
                if hint in low and header not in exclude:
                    return header
        return None

    mapping: dict = {}
    used: set[str] = set()
    for field in ("date", "merchant", "debit", "credit", "notes"):
        chosen = pick(field, used)
        mapping[field] = chosen
        if chosen:
            used.add(chosen)
    # "amount" hints overlap "transaction amount"/debit-credit header text —
    # resolve it after debit/credit so a Debit/Credit pair isn't shadowed.
    mapping["amount"] = pick("amount", used)
    # negate is decided at parse time from the data (sign convention), but a
    # user override in the review UI sticks.
    mapping["negate"] = None
    return mapping


def _parse_money(raw: str) -> float | None:
    raw = (raw or "").strip().replace("$", "").replace(",", "")
    if not raw:
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1]
    try:
        value = float(raw)
    except ValueError:
        return None
    return -value if negative else value


def parse_csv_statement(text: str, mapping: dict | None = None) -> dict:
    """Deterministic CSV parse. With a single signed amount column the sign
    convention is guessed from the data (most banks export debits negative);
    mapping["negate"] overrides the guess when the user corrects it in
    review. With separate debit/credit columns there is nothing to guess."""
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return {"format": "csv", "headers": [], "mapping": {}, "transactions": [], "skipped_credits": 0, "skipped_unparsed": 0}
    headers = [h.strip() for h in rows[0]]
    guessed = guess_csv_mapping(headers)
    if mapping:
        guessed.update({k: v for k, v in mapping.items() if k in guessed})
    mapping = guessed
    index = {h: i for i, h in enumerate(headers)}

    def cell(row: list[str], field: str) -> str:
        header = mapping.get(field)
        if header is None or header not in index or index[header] >= len(row):
            return ""
        return row[index[header]].strip()

    # First pass: raw signed amounts, so the sign convention can be decided
    # from the whole file rather than row by row.
    parsed: list[tuple[date, float, str, str]] = []
    skipped_unparsed = 0
    for row in rows[1:]:
        entry_date = parse_statement_date(cell(row, "date"))
        if entry_date is None:
            skipped_unparsed += 1
            continue
        if mapping.get("debit") or mapping.get("credit"):
            debit = _parse_money(cell(row, "debit"))
            credit = _parse_money(cell(row, "credit"))
            # Debit column holds spend as a positive number; a credit-column
            # row is a payment/refund, carried through negative to be skipped.
            amount = abs(debit) if debit else (-abs(credit) if credit else None)
        else:
            amount = _parse_money(cell(row, "amount"))
        if amount is None:
            skipped_unparsed += 1
            continue
        parsed.append((entry_date, amount, cell(row, "merchant"), cell(row, "notes")))

    negate = mapping.get("negate")
    if negate is None and not (mapping.get("debit") or mapping.get("credit")):
        # Debits-negative is the common export convention: if spending (which
        # dominates any statement) is mostly negative, flip signs.
        negate = sum(1 for _, a, _, _ in parsed if a < 0) > len(parsed) / 2
    mapping["negate"] = bool(negate)

    transactions = []
    skipped_credits = 0
    for entry_date, amount, merchant, notes in parsed:
        if mapping["negate"]:
            amount = -amount
        if amount <= 0:
            skipped_credits += 1
            continue
        transactions.append(_transaction(entry_date, amount, merchant, notes))

    return {
        "format": "csv",
        "headers": headers,
        "mapping": mapping,
        "transactions": transactions,
        "skipped_credits": skipped_credits,
        "skipped_unparsed": skipped_unparsed,
    }


# --- OFX / QFX ---------------------------------------------------------------

_STMTTRN_RE = re.compile(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|$)", re.S | re.I)
# OFX 1.x is SGML — leaf elements have no closing tag, the value runs to the
# next tag or end of line. OFX 2.x is XML with closing tags; stopping at "<"
# handles both without a real parser.
_FIELD_RE_TEMPLATE = r"<{tag}>\s*([^<\r\n]*)"


def _ofx_field(block: str, tag: str) -> str:
    match = re.search(_FIELD_RE_TEMPLATE.format(tag=tag), block, re.I)
    return match.group(1).strip() if match else ""


def parse_ofx(text: str) -> dict:
    """Deterministic OFX/QFX parse of <STMTTRN> blocks — the minimal subset
    (DTPOSTED/TRNAMT/NAME/MEMO/TRNTYPE) every bank export actually fills.
    Negative TRNAMT = money out (the OFX convention); positive amounts are
    payments/refunds/interest and get skipped as credits."""
    transactions = []
    skipped_credits = 0
    skipped_unparsed = 0
    for block in _STMTTRN_RE.findall(text):
        raw_date = _ofx_field(block, "DTPOSTED")[:8]
        amount_raw = _parse_money(_ofx_field(block, "TRNAMT"))
        try:
            entry_date = datetime.strptime(raw_date, "%Y%m%d").date()
        except ValueError:
            skipped_unparsed += 1
            continue
        if amount_raw is None:
            skipped_unparsed += 1
            continue
        if amount_raw >= 0:
            skipped_credits += 1
            continue
        merchant = _ofx_field(block, "NAME") or _ofx_field(block, "PAYEE")
        memo = _ofx_field(block, "MEMO")
        transactions.append(_transaction(entry_date, -amount_raw, merchant, memo))
    return {
        "format": "ofx",
        "headers": [],
        "mapping": {},
        "transactions": transactions,
        "skipped_credits": skipped_credits,
        "skipped_unparsed": skipped_unparsed,
    }


def _transaction(entry_date: date, amount: float, merchant: str, notes: str) -> dict:
    return {
        "date": entry_date.isoformat(),
        "amount": round(amount, 2),
        "merchant": merchant,
        "notes": notes,
        "kind": guess_kind(merchant, notes),
    }


def normalize_vision_transactions(raw: list[dict]) -> dict:
    """Puts vision-extracted (PDF/photo) statement rows into the exact shape
    the deterministic parsers emit, DROPPING anything the model returned with
    an unparseable date or non-positive amount — transcription is the model's
    only job; shape/validity is enforced here in code."""
    transactions = []
    skipped_unparsed = 0
    for t in raw:
        try:
            entry_date = date.fromisoformat(str(t.get("date") or ""))
        except ValueError:
            skipped_unparsed += 1
            continue
        amount = t.get("amount")
        if not isinstance(amount, (int, float)) or amount <= 0:
            skipped_unparsed += 1
            continue
        txn = _transaction(entry_date, float(amount), str(t.get("merchant") or ""), str(t.get("notes") or ""))
        kind = t.get("kind")
        if kind in {"subscription", "food", "alcohol", "experience", "shopping", "big_purchase", "regular"}:
            txn["kind"] = kind
        transactions.append(txn)
    return {
        "format": "vision",
        "headers": [],
        "mapping": {},
        "transactions": transactions,
        "skipped_credits": 0,
        "skipped_unparsed": skipped_unparsed,
    }


# --- dedup -------------------------------------------------------------------

def annotate_duplicates(transactions: list[dict], repo) -> list[dict]:
    """Flags each transaction already present in the ledger (same date +
    amount + merchant, see repository.expense_exists) or repeated within this
    same batch. Flagged rows default to include=False in the review UI —
    don't double-write — but stay visible and overridable."""
    seen: set[tuple[str, float, str]] = set()
    for t in transactions:
        key = (t["date"], round(t["amount"], 2), t["merchant"].strip().lower())
        duplicate = key in seen or repo.expense_exists(date.fromisoformat(t["date"]), t["amount"], t["merchant"])
        t["duplicate"] = duplicate
        t["include"] = not duplicate
        seen.add(key)
    return transactions
