"""2026-11-11 live-test fix: bank-statement PDFs were cloud-only. Now: the
PDF's text layer (pypdf) or local OCR → rows parsed DETERMINISTICALLY
(statements.parse_statement_lines) → the local model only for leftover
rows → cloud only on provider=cloud. Dates are normalised to ISO in code.

Faked: the PDF is built in-test (real text layer, read by the real pypdf);
every model and cloud seam is stubbed; the cloud is a hard failure unless a
test asks for it."""
from __future__ import annotations

from datetime import date

import pytest

import quintacle_core.llm_dispatch as llm_dispatch
import quintacle_core.max_backend as max_backend
from quintacle_core.nodes.finance import llm as finance_llm
from quintacle_core.nodes.finance.statements import (
    normalize_vision_transactions,
    parse_statement_lines,
    resolve_statement_date,
    statement_period,
)
from quintacle_core.perception import image_policy
from tests.claude.harness import make_pdf

CHECKING = [
    "FIRST CAPITAL BANK - CHECKING ACCOUNT STATEMENT",
    "Account ending 4417    Statement period 10/01/2026 - 10/31/2026",
    "Beginning balance on 10/01/2026: $2,481.30",
    "Date         Description                       Withdrawals   Deposits   Balance",
    "10/02/2026   TRADER JOE'S #548                 67.43                    2,413.87",
    "10/06/2026   COMCAST XFINITY INTERNET          79.99                    2,333.88",
    "10/09/2026   PAYROLL ACME CORP                              1,000.00   3,333.88",
    "10/11/2026   EXXONMOBIL 4471                   52.18                    3,281.70",
    "10/19/2026   CVS PHARMACY 03312                23.65                    3,258.05",
    "10/27/2026   PEPCO ELECTRIC BILL PAY           112.40                   3,145.65",
    "Ending balance on 10/31/2026: $3,145.65",
    "Total withdrawals: $335.65    Total deposits: $1,000.00",
]
CHECKING_ROWS = [
    ("2026-10-02", 67.43, "TRADER JOE"),
    ("2026-10-06", 79.99, "COMCAST XFINITY INTERNET"),
    ("2026-10-11", 52.18, "EXXONMOBIL 4471"),
    ("2026-10-19", 23.65, "CVS PHARMACY 03312"),
    ("2026-10-27", 112.40, "PEPCO ELECTRIC BILL PAY"),
]

CARD = """Billing period 12/06/2026 - 01/05/2027
Trans Date  Post Date  Description            Amount
12/28  12/29  SPOTIFY USA               11.99
12/30  12/31  PAYMENT - THANK YOU       -500.00
01/02  01/03  WHOLE FOODS #10233        94.27
01/03  01/04  AMAZON REFUND             -12.00
Total fees charged this period   0.00"""


def _boom(*a, **k):
    raise AssertionError("cloud was called")


@pytest.fixture
def no_cloud(monkeypatch):
    for mod in (max_backend, finance_llm, llm_dispatch):
        if hasattr(mod, "cloud_client"):
            monkeypatch.setattr(mod, "cloud_client", _boom)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", _boom)
    monkeypatch.setattr(finance_llm, "_extract_statement_cloud", _boom)


@pytest.fixture(autouse=True)
def _default_policy(monkeypatch):
    monkeypatch.delenv("QUINTACLE_IMAGE_PROVIDER", raising=False)
    image_policy.set_request_provider(None)
    yield
    image_policy.set_request_provider(None)


def _rows(txns):
    return [(t["date"], t["amount"], t["merchant"]) for t in txns]


# --- deterministic parse -----------------------------------------------------


def test_checking_pdf_rows_parse_in_code_with_iso_dates():
    from quintacle_core.nodes.kb.drop import _extract_pdf_text

    out = parse_statement_lines(_extract_pdf_text(make_pdf(CHECKING)))
    got = _rows(out["transactions"])
    assert [(d, a) for d, a, _ in got] == [(d, a) for d, a, _ in CHECKING_ROWS]
    for (_, _, merchant), (_, _, want) in zip(got, CHECKING_ROWS):
        assert merchant.upper().startswith(want)
    assert out["skipped_credits"] == 1  # the payroll deposit, decided by the running balance
    assert out["unparsed_lines"] == []
    assert out["period"] == ["2026-10-01", "2026-10-31"]


def test_card_statement_yearless_dates_take_the_period_year_and_credits_skip():
    out = parse_statement_lines(CARD)
    assert _rows(out["transactions"]) == [("2026-12-28", 11.99, "SPOTIFY USA"), ("2027-01-02", 94.27, "WHOLE FOODS #10233")]
    assert out["skipped_credits"] == 1  # the refund: negative on a card where charges are positive
    assert out["skipped_summary"] == 1  # "PAYMENT - THANK YOU" by keyword, like a balance/total line
    assert out["unparsed_lines"] == []


def test_single_signed_column_with_debits_negative():
    text = "Statement period 03/01/2026 - 03/31/2026\nDate Description Amount\n" \
           "03/02 NETFLIX.COM -15.49\n03/05 DIRECT DEPOSIT EMPLOYER 2,000.00\n03/09 SHELL OIL -40.00"
    out = parse_statement_lines(text)
    assert _rows(out["transactions"]) == [("2026-03-02", 15.49, "NETFLIX.COM"), ("2026-03-09", 40.0, "SHELL OIL")]
    assert out["skipped_credits"] == 1


def test_balance_and_total_rows_are_skipped_even_when_dated():
    text = "Date Description Amount Balance\n10/01/2026 Beginning Balance 100.00\n" \
           "10/02/2026 CHIPOTLE 1234 12.80 87.20\n10/31/2026 Ending Balance 87.20"
    out = parse_statement_lines(text)
    assert _rows(out["transactions"]) == [("2026-10-02", 12.8, "CHIPOTLE 1234")]
    assert out["skipped_summary"] == 2


def test_dates_resolve_to_iso_in_code():
    period = (date(2026, 12, 6), date(2027, 1, 5))
    assert resolve_statement_date("10/02/2026") == date(2026, 10, 2)
    assert resolve_statement_date("10/02/26") == date(2026, 10, 2)
    assert resolve_statement_date("12/28", period) == date(2026, 12, 28)
    assert resolve_statement_date("01/02", period) == date(2027, 1, 2)
    assert resolve_statement_date("Oct 2, 2026") == date(2026, 10, 2)
    assert resolve_statement_date("2026-10-02") == date(2026, 10, 2)
    assert resolve_statement_date("13/45/2026") is None
    assert statement_period("Statement period 10/01/2026 - 10/31/2026") == (date(2026, 10, 1), date(2026, 10, 31))


def test_vision_rows_printed_us_style_are_normalised_not_dropped():
    raw = [{"date": "10/02/2026", "amount": 67.43, "merchant": "TRADER JOE'S"},
           {"date": "10/06", "amount": 79.99, "merchant": "COMCAST"}]
    out = normalize_vision_transactions(raw, (date(2026, 10, 1), date(2026, 10, 31)))
    assert [(t["date"], t["amount"]) for t in out["transactions"]] == [("2026-10-02", 67.43), ("2026-10-06", 79.99)]
    assert out["skipped_unparsed"] == 0


# --- dispatch: local first, cloud only when asked ---------------------------


def test_pdf_statement_is_local_and_never_calls_any_model_when_code_parses_it(monkeypatch, no_cloud):
    monkeypatch.setattr(finance_llm, "parse_structured", _boom)
    rows = finance_llm.extract_statement_transactions(make_pdf(CHECKING), "application/pdf")
    assert [(r["date"], r["amount"]) for r in rows] == [(d, a) for d, a, _ in CHECKING_ROWS]


def test_local_model_only_sees_leftover_rows_and_its_dates_become_iso(monkeypatch, no_cloud):
    lines = CHECKING[:4] + ["10/02/2026   TRADER JOE'S #548                 67.43                    2,413.87",
                            "10/03/2026   *** smudged ***",
                            "10/06/2026   COMCAST XFINITY INTERNET          79.99                    2,333.88"]
    seen = {}

    def fake_parse(system, content, schema, provider=None, max_tokens=None):
        seen["content"], seen["provider"] = content, provider
        txns = [finance_llm._StatementTxn(date="10/03/2026", amount=9.5, merchant="SMUDGED CAFE", kind="food"),
                finance_llm._StatementTxn(date="10/02/2026", amount=67.43, merchant="TRADER JOES")]  # dup of a code row
        return type("R", (), {"parsed": schema(transactions=txns)})()

    monkeypatch.setattr(finance_llm, "parse_structured", fake_parse)
    rows = finance_llm.extract_statement_transactions(make_pdf(lines), "application/pdf")
    assert seen["provider"] == "local"
    assert "smudged" in seen["content"] and "COMCAST" not in seen["content"]
    assert "Statement period: 2026-10-01 to 2026-10-31" in seen["content"]
    assert sorted((r["date"], r["amount"]) for r in rows) == [("2026-10-02", 67.43), ("2026-10-03", 9.5), ("2026-10-06", 79.99)]


def test_local_mode_with_unreadable_pdf_asks_for_cloud_instead_of_calling_it(monkeypatch, no_cloud):
    from quintacle_core.nodes.kb import drop as kb_drop

    monkeypatch.setattr(kb_drop, "_extract_pdf_text", lambda data: "")
    monkeypatch.setattr(kb_drop, "_ocr_pdf_images", lambda data: "")
    with pytest.raises(image_policy.LocalImageUnavailable, match="Redo with cloud"):
        finance_llm.extract_statement_transactions(b"%PDF-1.4 scan", "application/pdf")


def test_cloud_only_on_explicit_provider_and_its_dates_are_normalised(monkeypatch):
    monkeypatch.setattr(finance_llm, "parse_structured", _boom)
    calls = []

    def fake_cloud(data, media_type, user_description=""):
        calls.append(media_type)
        return [{"date": "10/02", "amount": 67.43, "merchant": "TRADER JOE'S", "notes": "", "kind": "food"}]

    monkeypatch.setattr(finance_llm, "_extract_statement_cloud", fake_cloud)
    rows = finance_llm.extract_statement_transactions(make_pdf(CHECKING), "application/pdf", provider="cloud")
    assert calls == ["application/pdf"]
    assert rows[0]["date"] == "2026-10-02"  # year from the PDF's printed period


def test_drop_statement_pdf_end_to_end_is_local(tmp_path, monkeypatch, no_cloud):
    from fastapi.testclient import TestClient

    import quintacle_core.api as api_module

    monkeypatch.setenv("QUINTACLE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(finance_llm, "parse_structured", _boom)
    client = TestClient(api_module.create_app())
    res = client.post("/drop", data={"text": "statement: October checking statement", "provider": "local"},
                      files={"file": ("checking_oct_2026.pdf", make_pdf(CHECKING), "application/pdf")})
    assert res.status_code == 200, res.text[:400]
    entries = res.json()["entries"]
    assert [e["type"] for e in entries] == ["statement_import"]
    txns = entries[0]["transactions"]
    assert [(t["date"], t["amount"]) for t in txns] == [(d, a) for d, a, _ in CHECKING_ROWS]
    assert all(t["include"] and not t["duplicate"] for t in txns)
