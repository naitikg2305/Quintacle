from __future__ import annotations

import base64
import logging
from typing import Literal

from pydantic import BaseModel

from ...llm_config import DEFAULT_MODEL
from ...llm_dispatch import parse_structured
from ...max_backend import cloud_client

logger = logging.getLogger(__name__)


class CreditCardEstimate(BaseModel):
    suggested_name: str
    issuer: str = ""
    annual_fee: float | None = None
    rewards_summary: str = ""
    points_balance: float | None = None
    signup_bonus: str = ""
    notes: str = ""


_SYSTEM_PROMPT = (
    "Structure this into a credit card entry: suggested_name (the card's name, e.g. \"Chase "
    "Sapphire Preferred\"), issuer (the bank), annual_fee (a number in dollars if stated, else "
    "null), rewards_summary (a short description of reward categories/multipliers, e.g. \"3x "
    "dining, 2x travel, 1x everything else\"), points_balance (a number if a current balance is "
    "stated, else null), signup_bonus (a short description if mentioned), and notes (anything "
    "else worth remembering — redemption tips, why you got it, perks)."
)


def structure_credit_card(description: str, provider: str | None = None) -> CreditCardEstimate:
    """For the explicit "creditcard:"/"card:" prefix — intent already
    stated, so no relevance gate, always extracts fields."""
    return parse_structured(_SYSTEM_PROMPT, description, CreditCardEstimate, provider=provider, max_tokens=1024).parsed


class InvestmentEstimate(BaseModel):
    suggested_name: str
    symbol: str = ""
    shares: float | None = None
    cost_basis: float | None = None
    account: str = ""
    purchase_date: str | None = None
    notes: str = ""


_INVESTMENT_SYSTEM_PROMPT = (
    "Structure this into an investment holding entry: suggested_name (the company/fund name, "
    "e.g. \"Apple\" or \"VOO\"), symbol (the ticker if stated/known, e.g. \"AAPL\"), shares (a "
    "number if stated, else null), cost_basis (the average price PER SHARE paid, in dollars, if "
    "stated — if only a total dollar amount and share count are given, compute the per-share "
    "average yourself), account (the brokerage/account it's held in, if stated), purchase_date "
    "(YYYY-MM-DD if stated), and notes (why you bought it, a strategy note, anything else worth "
    "remembering — this is a manually-tracked record, not a live price feed, so don't invent a "
    "current price)."
)


def structure_investment(description: str, provider: str | None = None) -> InvestmentEstimate:
    """For the explicit "invest:"/"stock:" prefix — intent already stated,
    so no relevance gate, always extracts fields."""
    return parse_structured(_INVESTMENT_SYSTEM_PROMPT, description, InvestmentEstimate, provider=provider, max_tokens=1024).parsed


class _StatementTxn(BaseModel):
    date: str  # as printed; code normalises it to ISO (statements.resolve_statement_date)
    amount: float  # positive dollars spent
    merchant: str = ""
    notes: str = ""
    kind: Literal["subscription", "food", "alcohol", "experience", "shopping", "big_purchase", "regular"] = "regular"


class _StatementExtraction(BaseModel):
    transactions: list[_StatementTxn]


_STATEMENT_SYSTEM = (
    "This is a bank or credit card statement. Extract EVERY purchase/charge transaction as a row: "
    "date (copy the row's date as printed, e.g. 10/02/2026 or 10/02 — include the year from the statement "
    "period when the row omits it; code converts it to ISO), amount (the positive dollar amount charged), merchant "
    "(the payee/description as printed, lightly cleaned), notes (any extra detail on the line, else "
    "empty), and kind — exactly one of: subscription (a recurring bill/membership charge), food (a "
    "meal or non-alcoholic food/drink purchase), alcohol (a drink/bar tab/bottle purchase), "
    "experience (paying to do something — an activity, ticket, entrance fee), shopping (clothing, "
    "gear, everyday retail), big_purchase (a large one-off purchase), or regular (anything else). "
    "SKIP payments, credits, refunds, deposits, interest, fees-reversals, and balance/total lines — only "
    "money spent. Do not compute or invent anything: only transcribe what the statement shows."
)


def _statement_rows_local(text: str, user_description: str = "", source: str = "statement text") -> tuple[list[dict], str]:
    """Local-first rows from a statement's TEXT (pypdf layer or OCR):
    deterministic parse first (statements.parse_statement_lines); the LOCAL
    model only sees the row-like lines code couldn't resolve (or the whole
    text when code found no rows at all). Model rows are deduped against the
    code rows and their dates normalised to ISO in code. Returns (rows,
    pipeline)."""
    from .statements import parse_statement_lines, resolve_statement_date, statement_period

    parsed = parse_statement_lines(text)
    rows = list(parsed["transactions"])
    leftover = parsed["unparsed_lines"]
    if rows and not leftover:
        return rows, "ocr+parser"
    from ...perception.image_policy import LocalImageUnavailable

    period = statement_period(text)
    content = (
        f"Unparsed rows of a {source} (the other rows were already read):\n" + "\n".join(leftover)
        if rows else f"{source[0].upper()}{source[1:]}:\n{text}"
    )
    if period:
        content = f"Statement period: {period[0].isoformat()} to {period[1].isoformat()}\n\n{content}"
    if user_description.strip():
        content += f"\n\nThe owner adds: {user_description.strip()}"
    try:
        extracted = parse_structured(_STATEMENT_SYSTEM, content, _StatementExtraction, provider="local", max_tokens=8192).parsed
    except Exception as exc:
        if rows:  # the code-parsed rows stand; the leftovers are visible in review as missing
            logger.warning("local statement fallback failed (%s) — keeping %d code-parsed rows", exc, len(rows))
            return rows, "ocr+parser"
        if isinstance(exc, LocalImageUnavailable):
            raise
        raise LocalImageUnavailable(f"no statement rows parsed and the local model failed ({exc})", what="statement") from exc
    seen = {(r["date"], round(r["amount"], 2)) for r in rows}
    for t in extracted.transactions:
        row = t.model_dump()
        when = resolve_statement_date(row["date"], period)
        if when is None:
            continue
        row["date"] = when.isoformat()
        key = (row["date"], round(float(row["amount"] or 0), 2))
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    if not rows:
        raise LocalImageUnavailable("no transactions found in the statement text", what="statement")
    return rows, "ocr+local-llm"


def extract_statement_transactions(data: bytes, media_type: str, user_description: str = "", provider: str | None = None) -> list[dict]:
    """Local-first for photos AND PDFs (2026-11-11; photos since 11-06).
    PDF: the text layer via pypdf, else local OCR of the page images
    (nodes/kb/drop.py's helpers); photo: local OCR. Then rows are parsed IN
    CODE (statements.parse_statement_lines) and only the leftovers go to the
    local model. Cloud only on provider=cloud / "Redo with cloud" (or auto
    after a local failure) — the image policy gate decides. Dates come
    back ISO, normalised in code."""
    from ...perception.image_policy import LocalImageUnavailable, run_image_task

    is_pdf = media_type == "application/pdf"

    def local():
        if is_pdf:
            from ..kb.drop import _PDF_MIN_TEXT_CHARS, _extract_pdf_text, _meaningful, _ocr_pdf_images

            text = _extract_pdf_text(data)
            if _meaningful(text) < _PDF_MIN_TEXT_CHARS:
                text = _ocr_pdf_images(data)
            if _meaningful(text) < _PDF_MIN_TEXT_CHARS:
                raise LocalImageUnavailable("no text layer and local OCR read nothing", what="statement PDF")
            return _statement_rows_local(text, user_description, "bank statement PDF")
        from ...perception.ocr import ocr_image

        reading = ocr_image(data)
        if reading is None or not reading.text.strip():
            raise LocalImageUnavailable("no readable text found by local OCR (or no OCR engine installed)", what="statement photo")
        return _statement_rows_local(reading.text, user_description, "statement photo's OCR text (may contain OCR errors)")

    def cloud():
        rows = _extract_statement_cloud(data, media_type, user_description)
        period = None
        if is_pdf:  # the period from the local text layer, when there is one, fixes yearless dates
            from ..kb.drop import _extract_pdf_text
            from .statements import statement_period

            period = statement_period(_extract_pdf_text(data))
        return _iso_dates(rows, period)

    return run_image_task(local, cloud, what="statement PDF" if is_pdf else "statement photo", provider=provider)


def _iso_dates(rows: list[dict], period=None) -> list[dict]:
    """Model rows' printed dates (MM/DD/YYYY, MM/DD, ...) → ISO, in code. An
    unreadable date is left as-is for normalize_vision_transactions to drop."""
    from .statements import resolve_statement_date

    out = []
    for row in rows:
        when = resolve_statement_date(str(row.get("date") or ""), period)
        out.append({**row, "date": when.isoformat()} if when else row)
    return out


def _extract_statement_cloud(data: bytes, media_type: str, user_description: str = "") -> list[dict]:
    """PDF/photo statements through the SAME cloud vision lane receipts use
    (drop_router.extract_finance_from_receipt's pattern). Since 2026-11-11
    this is only the explicit escalation (provider=cloud / "Redo with
    cloud", or auto after a local failure) — never the default. The
    model only TRANSCRIBES rows; every number it returns is reviewed in the
    statement gate and all downstream arithmetic happens in code. anthropic
    imports lazily so the deterministic CSV/OFX lane never touches it."""
    import anthropic

    if media_type == "application/pdf":
        source_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(data).decode()},
        }
    else:
        source_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(data).decode()},
        }
    content: list[dict] = [source_block]
    if user_description.strip():
        content.append({"type": "text", "text": user_description.strip()})
    client = cloud_client()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=8192,
        system=_STATEMENT_SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_format=_StatementExtraction,
    )
    return [t.model_dump() for t in response.parsed_output.transactions]
