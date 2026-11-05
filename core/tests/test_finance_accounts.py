"""Manually-recorded account balances + net worth (nodes/finance/accounts.py):
append-only snapshot history, liabilities subtract, and the
no-double-counting rule against the stock ledger."""
from datetime import date

from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.nodes.finance.accounts import AccountStore, summarize


def make_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    return TestClient(api_module.create_app())


def test_balance_updates_append_history_never_overwrite(tmp_path):
    store = AccountStore(tmp_path / "kb")
    slug = store.upsert("Fidelity 401k", "401k", "Fidelity")
    store.add_balance(slug, 10000, date(2026, 9, 1))
    store.add_balance(slug, 12000, date(2026, 11, 1))
    store.add_balance(slug, 11000, date(2026, 10, 1))  # back-dated entry sorts into place
    acct = store.get(slug)
    assert [b["balance"] for b in acct["balances"]] == [10000, 11000, 12000]
    # Re-upserting descriptive fields keeps the history.
    store.upsert("Fidelity 401k", "401k", "Fidelity Investments")
    assert len(store.get(slug)["balances"]) == 3
    store.delete_balance(slug, 0)
    assert [b["balance"] for b in store.get(slug)["balances"]] == [11000, 12000]


def test_summary_buckets_liabilities_and_history(tmp_path):
    store = AccountStore(tmp_path / "kb")
    chk = store.upsert("Chase Checking", "checking")
    card = store.upsert("Amex", "credit_card")
    store.add_balance(chk, 5000, date(2026, 10, 1))
    store.add_balance(card, 800, date(2026, 10, 15))
    store.add_balance(chk, 6000, date(2026, 11, 1))
    s = summarize(store.all())
    assert s["buckets"]["liquid"] == 6000
    assert s["liabilities"] == 800
    assert s["net_worth"] == 5200
    assert s["history"] == [
        {"date": "2026-10-01", "net_worth": 5000},
        {"date": "2026-10-15", "net_worth": 4200},
        {"date": "2026-11-01", "net_worth": 5200},
    ]


def test_stock_holdings_not_double_counted_with_brokerage_balance(tmp_path):
    store = AccountStore(tmp_path / "kb")
    brk = store.upsert("Robinhood", "brokerage")
    store.add_balance(brk, 3000, date(2026, 11, 1))
    positions = {
        "positions": [
            # Covered: its only account is the recorded brokerage.
            {"symbol": "RIVN", "qty": 100, "cost_basis": 1500, "market_value": 1200, "accounts": ["robinhood"]},
            # No account name -> counts, at market value.
            {"symbol": "AAPL", "qty": 1, "cost_basis": 150, "market_value": 200, "accounts": []},
            # Unpriced, different account -> counts at cost.
            {"symbol": "VTI", "qty": 2, "cost_basis": 500, "market_value": None, "accounts": ["Vanguard"]},
            # Closed position -> ignored.
            {"symbol": "TSLA", "qty": 0, "cost_basis": 0, "market_value": None, "accounts": []},
        ]
    }
    s = summarize(store.all(), positions)
    assert s["stock_symbols_covered"] == ["RIVN"]
    assert s["stock_symbols_counted"] == ["AAPL", "VTI"]
    assert s["stock_holdings_counted"] == 700
    assert s["stock_holdings_at_cost"] is True
    assert s["investments_total"] == 3700
    assert s["net_worth"] == 3700


def test_accounts_endpoints_roundtrip(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    r = client.post(
        "/finance/accounts",
        json={"name": "Ally Savings", "account_type": "savings", "balance": 2500, "as_of": "2026-11-01"},
    )
    assert r.status_code == 200
    slug = r.json()["slug"]
    assert client.post(f"/finance/accounts/{slug}/balance", json={"balance": 2600, "as_of": "2026-11-05"}).status_code == 200
    data = client.get("/finance/accounts").json()
    assert data["net_worth"] == 2600
    assert data["accounts"][0]["latest_date"] == "2026-11-05"
    assert len(data["accounts"][0]["balances"]) == 2
    assert client.post("/finance/accounts", json={"name": "x", "account_type": "nope"}).status_code == 400
    assert client.post("/finance/accounts/missing/balance", json={"balance": 1}).status_code == 404
    assert client.delete(f"/finance/accounts/{slug}/balance/0").json()["snapshots"] == 1
    assert client.delete(f"/finance/accounts/{slug}").status_code == 200
    assert client.get("/finance/accounts").json()["accounts"] == []
