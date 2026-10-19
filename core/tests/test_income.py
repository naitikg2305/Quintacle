"""Income lane (next-wave-plan §1 decision 3): deterministic "income:" drop
parsing, the income_log store round-trip (markdown + SQLite + rebuild), and
the savings arithmetic it feeds."""
from datetime import date

from quintacle_core.db import connect
from quintacle_core.nodes.drop_router import parse_income_text, parse_prefix
from quintacle_core.nodes.finance.insights import monthly_breakdown
from quintacle_core.nodes.logs.log_store import LogFileStore, rebuild_sqlite_index
from quintacle_core.nodes.logs.repository import LogsRepository


def test_income_prefix_routes_deterministically():
    assert parse_prefix("income: 3200 Acme paycheck") == ("income", "3200 Acme paycheck")
    assert parse_prefix("paycheck: $3,200.50 from Acme") == ("income", "$3,200.50 from Acme")


def test_parse_income_text_amount_source_kind():
    entry = parse_income_text("$3,200.50 paycheck from Acme")
    assert entry["type"] == "income"
    assert entry["amount"] == 3200.50
    assert entry["kind"] == "salary"
    assert "Acme" in entry["source"]
    assert entry["entry_date"] is None


def test_parse_income_text_with_explicit_date_and_other_kind():
    entry = parse_income_text("sold a lens 250 on 2026-10-12")
    assert entry["amount"] == 250.0
    assert entry["kind"] == "other"
    assert entry["entry_date"] == "2026-10-12"
    assert "2026" not in entry["source"]  # the date never leaks into the amount or source


def test_income_log_roundtrip_markdown_and_rebuild(tmp_path):
    store = LogFileStore(tmp_path / "kb")
    repo = LogsRepository(connect(tmp_path / "test.db"), store)

    repo.log_income(date(2026, 10, 1), 4000.0, "Acme", "salary", "October paycheck")

    entries = store.all_entries("income")
    assert len(entries) == 1
    assert entries[0]["amount"] == 4000.0
    assert entries[0]["source"] == "Acme"
    assert entries[0]["kind"] == "salary"

    # Wipe SQLite and rebuild from markdown — markdown is the source of truth.
    repo.conn.execute("DELETE FROM income_log")
    repo.conn.commit()
    counts = rebuild_sqlite_index(store, repo.conn)
    assert counts["income_log"] == 1
    assert repo.total_income_between(date(2026, 10, 1), date(2026, 10, 31)) == 4000.0
    # income and expense share a markdown home but never cross-contaminate
    assert store.all_entries("finance") == []


def test_savings_rate_is_income_minus_spend_in_code(tmp_path):
    repo = LogsRepository(connect(tmp_path / "test.db"))
    repo.log_income(date(2026, 10, 1), 5000.0, "Acme", "salary")
    repo.log_expense(date(2026, 10, 5), 1250.0, "Rent Co", "", "", "regular")

    months = monthly_breakdown(repo.conn, months=1, today=date(2026, 10, 15))

    assert months[0]["savings"] == 3750.0
    assert months[0]["savings_rate_pct"] == 75.0
