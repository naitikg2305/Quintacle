"""FINANCE text + statement drops: inputs and the RIGHT answers, written once
and run by BOTH live suites (tests/claude/local = qwen via Ollama, cloud
blocked; tests/claude/subscription_or_api = Claude via Max, API blocked).

Expectations are fixed from product intent up front; a failure is a finding
about the model/code, never a reason to re-fit the expectation.

Two groups:
- MODEL_CHECKS: a model must make the call (classification, field extraction,
  kind, PDF transcription). The Max suite asserts a Max call happened.
- DETERMINISTIC_CHECKS: routing/parsing is code-only by design (CSV by
  extension, the "income:" prefix). Both suites assert NO model was used.
"""
from __future__ import annotations

from quintacle_core import clock
from tests.claude.harness import CloudBlocked, drop, first, make_pdf, types

# --- inputs -----------------------------------------------------------------

NETFLIX = "paid $14.99 for Netflix this month"
INCOME = "got paid $3,200 from Minfy today"
MACBOOK = "bought a $1,450 MacBook Air at Best Buy"

# A checking-account statement as a real text-layer PDF. Five withdrawals,
# no deposits, plus beginning/ending balance lines that are NOT transactions.
# Dates printed US-style (MM/DD/YYYY) like a real bank statement; the product
# stores ISO dates.
STATEMENT_PDF = [
    "FIRST CAPITAL BANK - CHECKING ACCOUNT STATEMENT",
    "Account ending 4417    Statement period 10/01/2026 - 10/31/2026",
    "Beginning balance on 10/01/2026: $2,481.30",
    "Date         Description                       Withdrawals   Deposits   Balance",
    "10/02/2026   TRADER JOE'S #548                 67.43                    2,413.87",
    "10/06/2026   COMCAST XFINITY INTERNET          79.99                    2,333.88",
    "10/11/2026   EXXONMOBIL 4471                   52.18                    2,281.70",
    "10/19/2026   CVS PHARMACY 03312                23.65                    2,258.05",
    "10/27/2026   PEPCO ELECTRIC BILL PAY           112.40                   2,145.65",
    "Ending balance on 10/31/2026: $2,145.65",
    "Total withdrawals: $335.65    Total deposits: $0.00",
]
# (ISO date, amount) -> a merchant token the row must carry.
STATEMENT_PDF_EXPECT = {
    ("2026-10-02", 67.43): "trader joe",
    ("2026-10-06", 79.99): "comcast",
    ("2026-10-11", 52.18): "exxon",
    ("2026-10-19", 23.65): "cvs",
    ("2026-10-27", 112.40): "pepco",
}

# A credit-card CSV export (signed Amount column, charges negative) with one
# payment row. Dropped with NO prefix: the .csv extension alone routes it.
STATEMENT_CSV = "\n".join([
    "Transaction Date,Post Date,Description,Category,Type,Amount",
    "10/03/2026,10/04/2026,SPOTIFY USA,Entertainment,Sale,-11.99",
    "10/08/2026,10/09/2026,WHOLE FOODS MARKET #10233,Groceries,Sale,-94.27",
    "10/12/2026,10/13/2026,UBER *TRIP,Travel,Sale,-18.40",
    "10/15/2026,10/15/2026,AUTOMATIC PAYMENT - THANK YOU,,Payment,500.00",
    "10/21/2026,10/22/2026,REI #64 ARLINGTON,Shopping,Sale,-129.95",
    '10/29/2026,10/30/2026,"AMAZON.COM*2K4RT, AMZN.COM/BILL",Shopping,Sale,-36.18',
]) + "\n"
STATEMENT_CSV_EXPECT = {
    ("2026-10-03", 11.99): "spotify",
    ("2026-10-08", 94.27): "whole foods",
    ("2026-10-12", 18.40): "uber",
    ("2026-10-21", 129.95): "rei",
    ("2026-10-29", 36.18): "amazon",
}


# --- helpers ----------------------------------------------------------------

def _money(a, b) -> bool:
    return a is not None and abs(float(a) - float(b)) < 0.005


def _only_finance(r: dict) -> dict:
    fin = [e for e in r.get("entries", []) if e.get("type") == "finance"]
    assert len(fin) == 1, f"expected exactly one finance entry, got {types(r)}: {fin}"
    return fin[0]


def _date_ok(entry: dict, *, same_month: bool = False) -> None:
    d = entry.get("entry_date")
    today = clock.today().isoformat()
    if same_month:
        assert d is None or d[:7] == today[:7], f"entry_date={d!r}"
    else:
        assert d is None or d == today, f"entry_date={d!r}"


def _match_rows(txns: list[dict], expect: dict) -> None:
    got = {(t.get("date"), round(float(t.get("amount") or 0), 2)): t for t in txns}
    want = {(d, round(a, 2)) for d, a in expect}
    assert set(got) == want, f"rows differ.\n missing: {sorted(want - set(got))}\n extra: {sorted(set(got) - want)}"
    assert len(txns) == len(expect), f"{len(txns)} rows for {len(expect)} transactions (duplicates?): {txns}"
    for (d, a), token in expect.items():
        merchant = (got[(d, round(a, 2))].get("merchant") or "").lower()
        assert token in merchant, f"{d} {a}: merchant={merchant!r}, expected it to name {token!r}"


def _statement(r: dict) -> dict:
    return first(r, "statement_import")


# --- model checks -----------------------------------------------------------

def check_netflix_subscription(c, provider):
    """A monthly Netflix charge is the textbook recurring subscription: one expense of exactly $14.99, kind subscription."""
    r = drop(c, text=NETFLIX, provider=provider)
    assert "income" not in types(r), types(r)
    e = _only_finance(r)
    assert _money(e.get("amount"), 14.99), e
    assert e.get("kind") == "subscription", e
    assert "netflix" in (e.get("merchant") or "").lower(), e
    _date_ok(e, same_month=True)


def check_income_natural(c, provider):
    """Getting paid by an employer is money IN: it must propose an income entry of $3,200 from Minfy, never a $3,200 expense."""
    # Known gap at time of writing: the unprefixed lane (parse_journal_dump)
    # has no income type in its union, so a model can only answer finance
    # (an expense) or a note. Only "income:"/"paycheck:" reach the income
    # lane. A failure here is that finding, not a wrong expectation.
    r = drop(c, text=INCOME, provider=provider)
    assert not any(e.get("type") == "finance" and _money(e.get("amount"), 3200) for e in r.get("entries", [])), \
        f"income recorded as an EXPENSE: {r.get('entries')}"
    e = first(r, "income")
    assert _money(e.get("amount"), 3200), e
    assert "minfy" in (e.get("source") or "").lower(), e
    _date_ok(e)


def check_macbook_big_purchase(c, provider):
    """A $1,450 laptop is a large one-off electronics purchase (the prompt's own big_purchase example), not a stock trade or shopping."""
    r = drop(c, text=MACBOOK, provider=provider)
    assert "stock_transaction" not in types(r), types(r)
    e = _only_finance(r)
    assert _money(e.get("amount"), 1450), e
    assert e.get("kind") == "big_purchase", e
    assert "best buy" in (e.get("merchant") or "").lower(), e
    _date_ok(e)


def check_statement_pdf(c, provider):
    """A 'statement:' PDF must yield every one of its 5 charges with exact printed amounts and ISO dates, and no balance/total lines as rows."""
    # KNOWN GAP (local): finance/llm.extract_statement_transactions sends
    # PDFs to the CLOUD document lane only ("the local stack has no PDF
    # reader yet"). The correct local-first behaviour is to read the PDF's
    # text layer locally (pypdf) and transcribe rows with the local text
    # model, so the local suite asserts that and will fail with "cloud call
    # blocked" until that lane exists.
    try:
        r = drop(c, text="statement: October checking statement", data=make_pdf(STATEMENT_PDF),
                 filename="checking_oct_2026.pdf", provider=provider)
    except CloudBlocked as e:
        raise AssertionError(f"KNOWN GAP — PDF statement needs cloud, no local read: {e}") from e
    s = _statement(r)
    assert "finance" not in types(r), f"statement rows leaked out as separate expenses: {types(r)}"
    _match_rows(s.get("transactions") or [], STATEMENT_PDF_EXPECT)
    assert all(t.get("include", True) for t in s["transactions"]), "nothing is in the ledger yet — no row is a duplicate"


# --- deterministic checks ---------------------------------------------------

def check_statement_csv_no_prefix(c, provider):
    """A .csv IS a statement: routed by extension with zero model calls, all 5 charges at exact amounts, the card payment skipped as a credit."""
    r = drop(c, data=STATEMENT_CSV.encode(), filename="card_oct_2026.csv", provider=provider)
    assert r.get("provider_used") is None, f"a CSV must not touch a model; provider_used={r.get('provider_used')!r}"
    s = _statement(r)
    assert s.get("format") == "csv", s.get("format")
    _match_rows(s.get("transactions") or [], STATEMENT_CSV_EXPECT)
    assert s.get("skipped_credits") == 1, f"the $500 payment is money in, not spend: {s.get('skipped_credits')}"
    assert s.get("skipped_unparsed") == 0, s.get("skipped_unparsed")
    spotify = next(t for t in s["transactions"] if "spotify" in t["merchant"].lower())
    assert spotify.get("kind") == "subscription", spotify


def check_income_prefixed(c, provider):
    """'income:' routes deterministically to the income lane: $3,200 from Minfy, no model call at all."""
    r = drop(c, text=f"income: {INCOME}", provider=provider)
    assert r.get("provider_used") is None, f"the income prefix is code-only; provider_used={r.get('provider_used')!r}"
    assert "finance" not in types(r), types(r)
    e = first(r, "income")
    assert _money(e.get("amount"), 3200), e
    assert "minfy" in (e.get("source") or "").lower(), e


MODEL_CHECKS = [check_netflix_subscription, check_income_natural, check_macbook_big_purchase, check_statement_pdf]
DETERMINISTIC_CHECKS = [check_statement_csv_no_prefix, check_income_prefixed]
ALL = MODEL_CHECKS + DETERMINISTIC_CHECKS
