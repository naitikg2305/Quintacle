"""The /drop §8 lanes: "stock:"/"invest:" → a real ledger-transaction
proposal, "habit:"/"goal:"/"budget:" → a habit proposal, and the conservative
unprefixed stock gate (drop_router.looks_like_stock_transaction) routing
trade-shaped text to the stock lane instead of parse_journal_dump. The
structure_* model calls are monkeypatched where api.py imports them —
deterministic, no model, same style as test_llm_dispatch's endpoint tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.nodes.journal.llm import FinanceEntry
from quintacle_core.nodes.logs.habit_llm import HabitEstimate
from quintacle_core.nodes.stocks.llm import StockTransactionEstimate


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    return TestClient(api_module.create_app())


def _must_not_run(name):
    def fail(*args, **kwargs):
        raise AssertionError(f"{name} must not be called on this path")

    return fail


STOCK_ESTIMATE = StockTransactionEstimate(
    action="buy", symbol="AAPL", qty=10, price=150.0, fees=0, account="fidelity", entry_date="2026-10-18", notes="dip buy"
)


def test_stock_prefix_proposes_a_ledger_transaction(client, monkeypatch):
    seen = {}

    def fake_structure(description, reference_date=None, provider=None):
        seen["description"] = description
        return STOCK_ESTIMATE

    monkeypatch.setattr(api_module, "structure_stock_transaction", fake_structure)
    monkeypatch.setattr(api_module, "parse_journal_dump", _must_not_run("parse_journal_dump"))

    resp = client.post("/drop", data={"text": "stock: bought 10 shares of AAPL at 150 in fidelity"})

    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert len(entries) == 1
    assert entries[0] == {
        "type": "stock_transaction",
        "action": "buy",
        "symbol": "AAPL",
        "qty": 10,
        "price": 150.0,
        "fees": 0,
        "account": "fidelity",
        "entry_date": "2026-10-18",
        "notes": "dip buy",
    }
    assert seen["description"] == "bought 10 shares of AAPL at 150 in fidelity"


def test_invest_prefix_routes_to_the_same_stock_lane(client, monkeypatch):
    monkeypatch.setattr(api_module, "structure_stock_transaction", lambda *a, **k: STOCK_ESTIMATE)
    monkeypatch.setattr(api_module, "parse_journal_dump", _must_not_run("parse_journal_dump"))

    resp = client.post("/drop", data={"text": "invest: picked up some AAPL"})

    assert resp.status_code == 200
    assert resp.json()["entries"][0]["type"] == "stock_transaction"


HABIT_ESTIMATE = HabitEstimate(
    name="Eating out budget",
    target_amount=200,
    target_period="month",
    metric="spend",
    direction="at_most",
    unit="$",
    match_category="restaurant, takeout",
    match_kind="food",
)


def test_habit_prefix_proposes_a_habit_entry(client, monkeypatch):
    seen = {}

    def fake_structure(description, provider=None):
        seen["description"] = description
        return HABIT_ESTIMATE

    monkeypatch.setattr(api_module, "structure_habit", fake_structure)
    monkeypatch.setattr(api_module, "parse_journal_dump", _must_not_run("parse_journal_dump"))

    resp = client.post("/drop", data={"text": "habit: $200/month on eating out"})

    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert len(entries) == 1
    assert entries[0] == {
        "type": "habit_entry",
        "name": "Eating out budget",
        "target_amount": 200,
        "target_period": "month",
        "metric": "spend",
        "direction": "at_most",
        "unit": "$",
        "match_category": "restaurant, takeout",
        "match_kind": "food",
    }
    assert seen["description"] == "$200/month on eating out"


def test_budget_and_goal_prefixes_route_to_the_same_habit_lane(client, monkeypatch):
    monkeypatch.setattr(api_module, "structure_habit", lambda *a, **k: HABIT_ESTIMATE)
    monkeypatch.setattr(api_module, "parse_journal_dump", _must_not_run("parse_journal_dump"))

    for text in ("budget: $200/month on eating out", "goal: gym 4x a week"):
        resp = client.post("/drop", data={"text": text})
        assert resp.status_code == 200
        assert resp.json()["entries"][0]["type"] == "habit_entry"


def test_unprefixed_stock_text_hits_the_stock_lane_not_journal_dump(client, monkeypatch):
    monkeypatch.setattr(api_module, "structure_stock_transaction", lambda *a, **k: STOCK_ESTIMATE)
    monkeypatch.setattr(api_module, "parse_journal_dump", _must_not_run("parse_journal_dump"))

    resp = client.post("/drop", data={"text": "bought 10 shares of AAPL at 150"})

    assert resp.status_code == 200
    assert resp.json()["entries"][0]["type"] == "stock_transaction"


def test_unprefixed_ordinary_purchase_still_goes_to_journal_dump(client, monkeypatch):
    monkeypatch.setattr(api_module, "structure_stock_transaction", _must_not_run("structure_stock_transaction"))
    monkeypatch.setattr(
        api_module,
        "parse_journal_dump",
        lambda *a, **k: [FinanceEntry(type="finance", amount=8.0, merchant="the store", category="groceries", notes="")],
    )

    resp = client.post("/drop", data={"text": "bought 10 apples at the store"})

    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert entries[0]["type"] == "finance"
    assert entries[0]["merchant"] == "the store"
