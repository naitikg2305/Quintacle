"""Statement drop lane (next-wave-plan §2b): deterministic CSV/OFX parsing,
column-mapping guesses + overrides, vision-row normalization, dedup flags,
and the gated import endpoint. Fixture statements are authored by hand with
hand-computed expectations."""
from datetime import date
from pathlib import Path

from quintacle_core.db import connect
from quintacle_core.nodes.finance.statements import (
    annotate_duplicates,
    guess_csv_mapping,
    normalize_vision_transactions,
    parse_csv_statement,
    parse_ofx,
    parse_statement_date,
)
from quintacle_core.nodes.logs.repository import LogsRepository

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- CSV ---------------------------------------------------------------------


def test_card_csv_mapping_is_guessed_from_headers():
    headers = ["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount", "Memo"]
    mapping = guess_csv_mapping(headers)
    assert mapping["date"] == "Transaction Date"
    assert mapping["merchant"] == "Description"
    assert mapping["amount"] == "Amount"
    assert mapping["notes"] == "Memo"
    assert mapping["debit"] is None and mapping["credit"] is None


def test_card_csv_parses_debits_skips_credits_and_flags_sign_convention():
    result = parse_csv_statement(_fixture("statement_card.csv"))

    assert result["mapping"]["negate"] is True  # debits were negative in the file
    assert result["skipped_credits"] == 1  # the card payment row
    assert result["skipped_unparsed"] == 1  # the garbled-date row
    txns = result["transactions"]
    assert [(t["date"], t["amount"]) for t in txns] == [
        ("2026-09-02", 15.49),
        ("2026-09-05", 12.80),
        ("2026-09-14", 43.25),
        ("2026-09-21", 12.80),
    ]
    by_merchant = {t["merchant"]: t for t in txns}
    assert by_merchant["NETFLIX.COM"]["kind"] == "subscription"
    assert by_merchant["CHIPOTLE 1234"]["kind"] == "food"
    assert by_merchant["TOTAL WINE AND MORE"]["kind"] == "alcohol"
    assert txns[1]["notes"] == "lunch"


def test_bank_csv_uses_debit_credit_columns():
    result = parse_csv_statement(_fixture("statement_bank.csv"))

    assert result["mapping"]["debit"] == "Debit"
    assert result["mapping"]["credit"] == "Credit"
    assert result["skipped_credits"] == 1  # the payroll deposit
    assert [(t["date"], t["amount"], t["merchant"]) for t in result["transactions"]] == [
        ("2026-09-03", 84.17, "HEB GROCERY #612"),
        ("2026-09-10", 38.50, "SHELL OIL 57444"),
        ("2026-09-17", 61.02, "HEB GROCERY #612"),
    ]
    assert result["transactions"][0]["kind"] == "food"  # "grocery" keyword


def test_csv_mapping_override_wins_over_guess():
    text = "When,Who,How Much\n2026-09-03,Chipotle,-12.80\n"
    mapping = {"date": "When", "merchant": "Who", "amount": "How Much", "debit": None, "credit": None, "notes": None}
    result = parse_csv_statement(text, mapping)
    assert len(result["transactions"]) == 1
    assert result["transactions"][0]["merchant"] == "Chipotle"
    assert result["transactions"][0]["amount"] == 12.80  # single negative row -> negate guessed


def test_csv_negate_override_sticks():
    # Positive-amounts file, but the user says these are already debits=positive;
    # forcing negate=True flips everything negative -> all skipped as credits.
    text = "Date,Description,Amount\n2026-09-03,Chipotle,12.80\n"
    result = parse_csv_statement(text, {"negate": True})
    assert result["transactions"] == []
    assert result["skipped_credits"] == 1
    result = parse_csv_statement(text, {"negate": False})
    assert len(result["transactions"]) == 1


def test_statement_date_formats():
    assert parse_statement_date("2026-09-03") == date(2026, 9, 3)
    assert parse_statement_date("09/03/2026") == date(2026, 9, 3)
    assert parse_statement_date("09/03/26") == date(2026, 9, 3)
    assert parse_statement_date("Sep 3, 2026") == date(2026, 9, 3)
    assert parse_statement_date("garbage") is None


# --- OFX ---------------------------------------------------------------------


def test_ofx_parses_debits_and_skips_credits():
    result = parse_ofx(_fixture("statement.ofx"))

    assert result["skipped_credits"] == 1
    assert [(t["date"], t["amount"], t["merchant"]) for t in result["transactions"]] == [
        ("2026-09-04", 55.00, "STUBHUB TICKETS"),
        ("2026-09-12", 9.99, "SPOTIFY USA"),
    ]
    assert result["transactions"][0]["notes"] == "concert"
    assert result["transactions"][0]["kind"] == "experience"
    assert result["transactions"][1]["kind"] == "subscription"


# --- vision normalization ----------------------------------------------------


def test_vision_rows_are_validated_in_code():
    raw = [
        {"date": "2026-09-03", "amount": 12.8, "merchant": "Chipotle", "notes": "", "kind": "food"},
        {"date": "not a date", "amount": 5.0, "merchant": "X", "notes": "", "kind": "regular"},
        {"date": "2026-09-04", "amount": -3.0, "merchant": "Refund", "notes": "", "kind": "regular"},
        {"date": "2026-09-05", "amount": 9.99, "merchant": "Spotify", "notes": "", "kind": "not_a_kind"},
    ]
    result = normalize_vision_transactions(raw)
    assert result["skipped_unparsed"] == 2
    assert [(t["date"], t["amount"]) for t in result["transactions"]] == [("2026-09-03", 12.8), ("2026-09-05", 9.99)]
    # invalid model kind falls back to the deterministic keyword guess
    assert result["transactions"][1]["kind"] == "subscription"


# --- dedup -------------------------------------------------------------------


def test_duplicates_flagged_against_ledger_and_within_batch(tmp_path):
    repo = LogsRepository(connect(tmp_path / "test.db"))
    repo.log_expense(date(2026, 9, 5), 12.80, "Chipotle 1234", "", "", "food")

    txns = [
        {"date": "2026-09-05", "amount": 12.80, "merchant": "CHIPOTLE 1234", "notes": "", "kind": "food"},  # in ledger
        {"date": "2026-09-14", "amount": 43.25, "merchant": "Total Wine", "notes": "", "kind": "alcohol"},  # new
        {"date": "2026-09-14", "amount": 43.25, "merchant": "total wine", "notes": "", "kind": "alcohol"},  # batch dup
    ]
    annotate_duplicates(txns, repo)

    assert [t["duplicate"] for t in txns] == [True, False, True]
    assert [t["include"] for t in txns] == [False, True, False]


# --- the gated import endpoint ----------------------------------------------


def test_statement_parse_and_import_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("QUINTACLE_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient

    import quintacle_core.api as api_module

    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())

    # Propose: deterministic parse, nothing written.
    res = client.post(
        "/finance/statement/parse",
        json={"filename": "card.csv", "text": _fixture("statement_card.csv")},
    )
    assert res.status_code == 200
    proposal = res.json()
    assert len(proposal["transactions"]) == 4
    assert all(t["duplicate"] is False for t in proposal["transactions"])
    assert client.get("/logs/expenses?start=2026-09-01&end=2026-09-30").json() == []

    # Commit the reviewed rows — the gated write.
    res = client.post(
        "/finance/statement/import",
        json={"transactions": proposal["transactions"], "statement_name": "card.csv"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["written"] == 4
    assert body["skipped_duplicates"] == 0
    assert body["event_id"]  # statement rows share one event

    expenses = client.get("/logs/expenses?start=2026-09-01&end=2026-09-30").json()
    assert len(expenses) == 4
    assert all("[statement: card.csv]" in e["notes"] for e in expenses)

    # Re-import the same statement: every row flags as duplicate at parse time
    # and is skipped at write time — never double-written.
    res = client.post(
        "/finance/statement/parse",
        json={"filename": "card.csv", "text": _fixture("statement_card.csv")},
    )
    assert all(t["duplicate"] is True for t in res.json()["transactions"])
    res = client.post(
        "/finance/statement/import",
        json={"transactions": proposal["transactions"], "statement_name": "card.csv"},
    )
    assert res.json() == {"written": 0, "skipped_duplicates": 4, "ids": [], "event_id": None}
    assert len(client.get("/logs/expenses?start=2026-09-01&end=2026-09-30").json()) == 4


def test_drop_routes_csv_statement_deterministically(tmp_path, monkeypatch):
    monkeypatch.setenv("QUINTACLE_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient

    import quintacle_core.api as api_module

    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())

    res = client.post(
        "/drop",
        data={"text": ""},
        files={"file": ("card.csv", _fixture("statement_card.csv").encode(), "text/csv")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["provider_used"] is None  # fully deterministic — no model touched this
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert entry["type"] == "statement_import"
    assert entry["format"] == "csv"
    assert entry["filename"] == "card.csv"
    assert len(entry["transactions"]) == 4
    # Still nothing written — the review gate owns the commit.
    assert client.get("/logs/expenses?start=2026-09-01&end=2026-09-30").json() == []
