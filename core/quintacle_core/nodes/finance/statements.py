"""Statement drops (next-wave-plan §2b, decided 2026-10-19): CSV and OFX/QFX
bank/card statements parsed DETERMINISTICALLY — stdlib csv + a hand-rolled
reader for the tiny SGML/XML subset real OFX files use. No model, no
third-party aggregator, no credentials, no new dependency in
core/requirements.txt. PDF statements went through the cloud vision lane
until 2026-11-11; now they are read locally and parsed by
parse_statement_lines below, with a local model only for rows code can't
parse (see llm.extract_statement_transactions). Every path lands in the same
propose -> review -> Save gate.

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


def normalize_vision_transactions(raw: list[dict], period: tuple[date, date] | None = None) -> dict:
    """Puts vision-extracted (PDF/photo) statement rows into the exact shape
    the deterministic parsers emit, DROPPING anything the model returned with
    an unparseable date or non-positive amount — transcription is the model's
    only job; shape/validity is enforced here in code."""
    transactions = []
    skipped_unparsed = 0
    for t in raw:
        # Models are told to give ISO, but bank statements print MM/DD/YYYY
        # (or MM/DD) — normalised HERE in code, never trusted as-is.
        entry_date = resolve_statement_date(str(t.get("date") or ""), period)
        if entry_date is None:
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


# --- PDF / OCR statement text ------------------------------------------------
# 2026-11-11: a PDF statement is read LOCALLY (pypdf text layer, or OCR of a
# scan — nodes/kb/drop.py) and its rows are parsed here in code: a line that
# starts with a date (MM/DD/YYYY, MM/DD/YY, MM/DD, "Oct 2") followed by a
# description and money columns. The year of a bare MM/DD comes from the
# statement period. Withdrawal vs deposit is decided by the running balance
# when the statement prints one (prev - amount = balance -> money out), else
# by which header column the amount sits under, else by the file's majority
# sign (the CSV rule). Balance/total/"payment - thank you" lines are skipped.
# Rows that look like transactions but can't be resolved come back in
# `unparsed_lines` for the local-model fallback (finance/llm.py).

_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_TOKEN = (
    r"(?:\d{1,2}/\d{1,2}(?:/\d{2}(?:\d{2})?)?|\d{1,2}-\d{1,2}-\d{2,4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:,?\s+\d{4})?)"
)
_ROW_RE = re.compile(rf"^\s*({_DATE_TOKEN})\s+(?:({_DATE_TOKEN})\s+)?(.*)$", re.I)
_MONEY_RE = re.compile(
    r"(?<![\w.,/])(\()?(-)?\s?\$?\s?(\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})(\))?(-|\s?CR\b)?(?![\w.%])", re.I
)
_PERIOD_RE = re.compile(rf"({_DATE_TOKEN})\s*(?:-|–|—|to|through|thru)\s*({_DATE_TOKEN})", re.I)
_SUMMARY_RE = re.compile(
    r"\b(?:beginning|ending|opening|closing|previous|new|daily|available|statement|starting)\s+balance\b|^\s*balance\b|"
    r"\b(?:sub)?totals?\b|\bpayments?\s*[-–]?\s*thank\s*you\b|\bpayments?\s+received\b|\bbalance\s+(?:forward|brought)\b",
    re.I,
)
_OPENING_RE = re.compile(r"\b(?:beginning|opening|previous|starting)\s+balance\b|\bbalance\s+(?:forward|brought)\b", re.I)
_HEADER_COLS = {
    "out": re.compile(r"withdrawals?|debits?|charges?", re.I),
    "in": re.compile(r"deposits?|credits?|additions", re.I),
    "balance": re.compile(r"\bbalance\b", re.I),
    "amount": re.compile(r"\bamount\b", re.I),
}


def _date_parts(raw: str) -> tuple[int, int, int | None] | None:
    """(month, day, year|None) from one date token; a 2-digit year -> 20yy."""
    raw = raw.strip().rstrip(",.")
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2}|\d{4}))?", raw)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        m = re.fullmatch(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?", raw, re.I)
        if not m or m.group(1).lower() not in _MONTHS:
            return None
        month, day, year = _MONTHS[m.group(1).lower()], int(m.group(2)), m.group(3)
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return month, day, (int(year) + (2000 if len(year) == 2 else 0)) if year else None


def statement_period(text: str) -> tuple[date, date] | None:
    """The printed statement period: the first "date - date" span whose end
    carries a year."""
    for m in _PERIOD_RE.finditer(text or ""):
        a, b = _date_parts(m.group(1)), _date_parts(m.group(2))
        if not a or not b or b[2] is None:
            continue
        try:
            end = date(b[2], b[0], b[1])
            start = date(a[2] if a[2] is not None else (b[2] - 1 if a[0] > b[0] else b[2]), a[0], a[1])
        except ValueError:
            continue
        if start <= end:
            return start, end
    return None


def resolve_statement_date(raw: str, period: tuple[date, date] | None = None, fallback_year: int | None = None) -> date | None:
    """Any printed row date -> a real date. ISO and the CSV formats first;
    then MM/DD[/YY[YY]] or "Oct 2". A missing year comes from the period (a
    December row in a Dec-Jan statement gets the start year), else the
    latest year printed in the statement, else this year (Eastern)."""
    raw = (raw or "").strip()
    found = parse_statement_date(raw)
    if found is not None:
        return found
    parts = _date_parts(raw)
    if parts is None:
        return None
    month, day, year = parts
    if year is None:
        if period is not None:
            start, end = period
            year = start.year if (start.year == end.year or month >= start.month) else end.year
        elif fallback_year is not None:
            year = fallback_year
        else:
            from ...clock import today

            year = today().year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _header_columns(line: str) -> dict[str, tuple[int, int]] | None:
    """Column spans of a table header line ("Date  Description  Withdrawals
    Deposits  Balance"), or None if the line isn't one."""
    if not re.search(r"\bdate\b", line, re.I):
        return None
    cols = {}
    for key, pat in _HEADER_COLS.items():
        m = pat.search(line)
        if m:
            cols[key] = (m.start(), m.end())
    return cols or None


def _nearest_column(pos: int, cols: dict[str, tuple[int, int]]) -> str | None:
    best, dist = None, None
    for key, (a, b) in cols.items():
        d = 0 if a <= pos <= b else min(abs(pos - a), abs(pos - b))
        if dist is None or d < dist:
            best, dist = key, d
    return best


def _money_tokens(text: str, offset: int = 0) -> list[tuple[float, int]]:
    """[(signed value, column)] — "(12.00)", "-12.00", "12.00-", "12.00 CR"
    are negative."""
    out = []
    for m in _MONEY_RE.finditer(text):
        value = float(m.group(3).replace(",", ""))
        if (m.group(1) and m.group(4)) or m.group(2) or (m.group(5) or "").strip():
            value = -value
        out.append((value, offset + m.start(3)))
    return out


def parse_statement_lines(text: str) -> dict:
    """Deterministic rows from a statement's TEXT (pypdf / OCR). Same result
    shape as the CSV/OFX parsers plus `period`, `skipped_summary` and
    `unparsed_lines` (row-like lines code couldn't resolve)."""
    period = statement_period(text)
    years = [int(y) for y in re.findall(r"\b\d{1,2}/\d{1,2}/(\d{4})\b", text or "")]
    fallback_year = max(years) if years else None
    cols: dict[str, tuple[int, int]] | None = None
    balance: float | None = None
    rows: list[dict] = []
    unparsed: list[str] = []
    skipped_summary = 0
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        if _OPENING_RE.search(line):
            money = _money_tokens(line)
            if money:
                balance = money[-1][0]
        m = _ROW_RE.match(line)
        if not m:
            header = _header_columns(line)
            if header and not _money_tokens(line):
                cols = header
            continue
        rest = m.group(3)
        money = _money_tokens(rest, m.start(3))
        first_money = _MONEY_RE.search(rest)
        merchant = re.sub(r"\s{2,}", " ", rest[: first_money.start()] if first_money else rest).strip(" -|")
        if _SUMMARY_RE.search(merchant):
            skipped_summary += 1
            continue
        entry_date = resolve_statement_date(m.group(1), period, fallback_year)
        if entry_date is None or not money or not re.search(r"[a-z]", merchant, re.I):
            unparsed.append(line.strip())
            continue
        side_cols = {k: v for k, v in (cols or {}).items() if k in ("out", "in")}
        if len(money) >= 2 and (cols is None or "balance" in cols):
            # amount column(s) then the running balance
            amount, pos = money[0]
            new_balance = money[-1][0]
            direction = None
            if balance is not None:
                if abs(balance - abs(amount) - new_balance) < 0.005:
                    direction = "out"
                elif abs(balance + abs(amount) - new_balance) < 0.005:
                    direction = "in"
            if direction is None and side_cols:
                direction = _nearest_column(pos, side_cols)
            balance = new_balance
            if direction is None:
                unparsed.append(line.strip())
                continue
            rows.append({"date": entry_date, "merchant": merchant, "amount": abs(amount), "direction": direction})
        elif len(money) == 1:
            amount, pos = money[0]
            direction = None
            if side_cols and "amount" not in (cols or {}):
                direction = _nearest_column(pos, side_cols)
            rows.append({"date": entry_date, "merchant": merchant,
                         "amount": amount if direction is None else abs(amount), "direction": direction})
        else:  # several amounts and no balance column: can't tell which is the charge
            unparsed.append(line.strip())

    # A single signed-amount column: the CSV rule — spending dominates a
    # statement, so if most rows are negative, negative means money out.
    signed = [r for r in rows if r["direction"] is None]
    negate = bool(signed) and sum(1 for r in signed if r["amount"] < 0) > len(signed) / 2
    transactions, skipped_credits = [], 0
    for r in rows:
        if r["direction"] is None:
            amount = -r["amount"] if negate else r["amount"]
            r["direction"], r["amount"] = ("out" if amount > 0 else "in"), abs(amount)
        if r["direction"] != "out" or r["amount"] <= 0:
            skipped_credits += 1
            continue
        transactions.append(_transaction(r["date"], r["amount"], r["merchant"], ""))
    return {
        "format": "pdf-text",
        "headers": [],
        "mapping": {},
        "transactions": transactions,
        "skipped_credits": skipped_credits,
        "skipped_summary": skipped_summary,
        "skipped_unparsed": len(unparsed),
        "unparsed_lines": unparsed,
        "period": [period[0].isoformat(), period[1].isoformat()] if period else None,
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
