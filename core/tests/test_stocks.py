"""Stocks wave (docs/next-wave-plan.md §2): ledger math, snapshot
append/selection, offline-stubbed price fetch, thesis↔holding edges.
Everything runs fully offline — Stooq HTTP is stubbed, never called."""
from datetime import date

from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.db import connect
from quintacle_core.graph import get_graph_store, init_graph_store
from quintacle_core.nodes.stocks import prices as prices_module
from quintacle_core.nodes.stocks.positions import compute_positions
from quintacle_core.nodes.stocks.prices import PriceFetchError, fetch_stooq
from quintacle_core.nodes.stocks.store import (
    StocksRepository,
    StockTransactionStore,
    holding_node_id,
    rebuild_stock_index,
)


def make_repo(tmp_path):
    conn = connect(tmp_path / "test.db")
    return StocksRepository(conn, StockTransactionStore(tmp_path / "kb"))


def make_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    return TestClient(api_module.create_app())


# --- ledger math (pure, computed — never stored) ---


def test_fifo_cost_basis_across_multiple_lots(tmp_path):
    repo = make_repo(tmp_path)
    repo.log_transaction(date(2026, 1, 5), "buy", "AAPL", qty=10, price=100, fees=5)
    repo.log_transaction(date(2026, 2, 5), "buy", "AAPL", qty=10, price=120, fees=5)

    result = compute_positions([dict(r) for r in repo.transactions()])
    (pos,) = result["positions"]

    assert pos["qty"] == 20
    assert pos["cost_basis"] == 10 * 100 + 5 + 10 * 120 + 5  # fees fold into lot basis
    assert pos["avg_cost"] == round(2210 / 20, 4)
    assert pos["realized_pnl"] == 0


def test_partial_sell_realizes_fifo_pnl(tmp_path):
    repo = make_repo(tmp_path)
    repo.log_transaction(date(2026, 1, 5), "buy", "AAPL", qty=10, price=100, fees=5)
    repo.log_transaction(date(2026, 2, 5), "buy", "AAPL", qty=10, price=120, fees=5)
    repo.log_transaction(date(2026, 3, 5), "sell", "AAPL", qty=15, price=130, fees=10)

    result = compute_positions([dict(r) for r in repo.transactions()])
    (pos,) = result["positions"]

    # FIFO: all of lot 1 (cost 1005) + half of lot 2 (cost 602.50) consumed.
    assert pos["realized_pnl"] == round(15 * 130 - (1005 + 602.5) - 10, 2)
    assert pos["qty"] == 5
    assert pos["cost_basis"] == 602.5  # the un-consumed half of lot 2
    assert not pos["oversold"]


def test_dividends_are_income_not_basis(tmp_path):
    repo = make_repo(tmp_path)
    repo.log_transaction(date(2026, 1, 5), "buy", "MSFT", qty=4, price=400)
    repo.log_transaction(date(2026, 3, 10), "dividend", "MSFT", qty=0, price=12.4)

    result = compute_positions([dict(r) for r in repo.transactions()])
    (pos,) = result["positions"]

    assert pos["dividends"] == 12.4
    assert pos["qty"] == 4  # share count untouched
    assert pos["cost_basis"] == 1600  # basis untouched
    assert result["totals"]["dividends"] == 12.4


def test_oversell_is_flagged_not_crashed():
    rows = [
        {"id": 1, "date": "2026-01-05", "action": "buy", "symbol": "NVDA", "qty": 5, "price": 100, "fees": 0},
        {"id": 2, "date": "2026-02-05", "action": "sell", "symbol": "NVDA", "qty": 8, "price": 110, "fees": 0},
    ]
    (pos,) = compute_positions(rows)["positions"]
    assert pos["oversold"] is True
    assert pos["qty"] == 0
    # 8 sold: 5 against the 500 basis, the 3 excess at zero basis.
    assert pos["realized_pnl"] == round(8 * 110 - 500, 2)


def test_unrealized_pnl_uses_latest_snapshot_and_degrades_to_none():
    rows = [{"id": 1, "date": "2026-01-05", "action": "buy", "symbol": "AAPL", "qty": 10, "price": 100, "fees": 0}]
    priced = compute_positions(rows, {"AAPL": {"price": 115.0, "price_date": "2026-10-16", "source": "stooq"}})
    (pos,) = priced["positions"]
    assert pos["market_value"] == 1150
    assert pos["unrealized_pnl"] == 150
    assert pos["last_price_date"] == "2026-10-16"

    unpriced = compute_positions(rows, {})  # no snapshot yet / offline forever
    (pos,) = unpriced["positions"]
    assert pos["market_value"] is None
    assert pos["unrealized_pnl"] is None
    assert unpriced["totals"]["unpriced_symbols"] == 1


# --- snapshots: append-only + latest selection ---


def test_snapshot_append_and_latest_selection(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.add_price_snapshot("AAPL", "2026-10-15", 240.0, "stooq", "2026-10-15T18:00:00-04:00")
    assert repo.add_price_snapshot("AAPL", "2026-10-16", 245.5, "stooq", "2026-10-16T18:00:00-04:00")
    # Same trading day again: append-only no-op, the recorded EOD close stands.
    assert not repo.add_price_snapshot("AAPL", "2026-10-16", 999.0, "stooq", "2026-10-16T19:00:00-04:00")

    latest = repo.latest_price("AAPL")
    assert latest["price"] == 245.5
    assert latest["price_date"] == "2026-10-16"
    assert [r["price"] for r in repo.price_history("AAPL")] == [240.0, 245.5]  # history retained
    assert repo.latest_prices()["AAPL"]["price"] == 245.5


# --- price fetch, fully offline ---

STOOQ_CSV = "Symbol,Date,Time,Open,High,Low,Close,Volume\nAAPL.US,2026-10-17,22:00:00,247.25,249,245.5,248.5,45000000\n"
STOOQ_ND_CSV = "Symbol,Date,Time,Open,High,Low,Close,Volume\nNOPE.US,N/D,N/D,N/D,N/D,N/D,N/D,N/D\n"


def test_stooq_fetch_parses_csv_offline():
    seen = {}

    def fake_get(url):
        seen["url"] = url
        return STOOQ_CSV

    snap = fetch_stooq("aapl", http_get=fake_get)
    assert "s=aapl.us" in seen["url"]  # US suffix added, lowercased
    assert snap == {"symbol": "AAPL", "price": 248.5, "price_date": "2026-10-17", "source": "stooq"}


def test_stooq_unknown_ticker_raises_fetch_error():
    try:
        fetch_stooq("NOPE", http_get=lambda url: STOOQ_ND_CSV)
        raise AssertionError("expected PriceFetchError")
    except PriceFetchError as e:
        assert "NOPE" in str(e)


# --- markdown is the source of truth ---


def test_markdown_roundtrip_rebuild_and_delete(tmp_path):
    repo = make_repo(tmp_path)
    tx_id = repo.log_transaction(date(2026, 1, 5), "buy", "AAPL", qty=10, price=100, fees=1, account="Fidelity", notes="first lot")
    repo.log_transaction(date(2026, 1, 5), "buy", "VOO", qty=2, price=500)

    files = list(repo.store.dir().glob("*.md"))
    assert len(files) == 2

    # A stray chat-pushed note in the same folder must not poison the ledger.
    (repo.store.dir() / "stray.md").write_text("just a note", encoding="utf-8")

    repo.conn.execute("DELETE FROM stock_transactions")
    assert rebuild_stock_index(repo.store, repo.conn) == 2
    rows = repo.transactions()
    assert [(r["symbol"], r["qty"], r["account"]) for r in rows] == [("AAPL", 10, "Fidelity"), ("VOO", 2, "")]
    assert rows[0]["notes"] == "first lot"

    # Delete removes the real record (the file), not just the index row.
    tx_id = rows[0]["id"]
    assert repo.delete_transaction(tx_id)
    assert len(list(repo.store.dir().glob("2026-01-05-*.md"))) == 1
    assert len(repo.transactions()) == 1


# --- endpoints: refresh degradation, positions, research edges ---


def test_refresh_endpoint_stores_snapshots_and_degrades_per_symbol(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    client.post("/stocks/transactions", json={"date": "2026-01-05", "action": "buy", "symbol": "AAPL", "qty": 10, "price": 100})
    client.post("/stocks/transactions", json={"date": "2026-01-06", "action": "buy", "symbol": "NOPE", "qty": 1, "price": 10})

    def fake_get(url, timeout=10):
        return STOOQ_CSV if "aapl.us" in url else STOOQ_ND_CSV

    monkeypatch.setattr(prices_module, "_http_get", fake_get)

    res = client.post("/stocks/prices/refresh", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["fetched"] == 1 and body["errors"] == 1
    by_symbol = {r["symbol"]: r for r in body["results"]}
    assert by_symbol["AAPL"]["stored"] is True
    assert "error" in by_symbol["NOPE"] and by_symbol["NOPE"]["stale"] is None

    positions = client.get("/stocks/positions").json()
    assert positions["prices_as_of"] == "2026-10-17"
    by_symbol = {p["symbol"]: p for p in positions["positions"]}
    assert by_symbol["AAPL"]["market_value"] == 2485.0
    assert by_symbol["AAPL"]["unrealized_pnl"] == 1485.0
    assert by_symbol["NOPE"]["market_value"] is None  # stale/absent price shown as absent, not fabricated

    assert client.get("/stocks/prices/AAPL").json()[0]["price"] == 248.5


def test_transaction_endpoint_validates(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    assert client.post("/stocks/transactions", json={"date": "2026-01-05", "action": "hold", "symbol": "A", "qty": 1}).status_code == 400
    assert client.post("/stocks/transactions", json={"date": "2026-01-05", "action": "buy", "symbol": "", "qty": 1}).status_code == 400
    assert client.post("/stocks/transactions", json={"date": "2026-01-05", "action": "buy", "symbol": "A", "qty": 0}).status_code == 400
    # dividend with qty 0 is the documented shape
    ok = client.post("/stocks/transactions", json={"date": "2026-01-05", "action": "dividend", "symbol": "a", "price": 5})
    assert ok.status_code == 200 and ok.json()["symbol"] == "A"


def test_research_note_creates_thesis_holding_edge(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    res = client.post("/stocks/research", json={"symbol": "amd", "status": "owned", "content": "Datacenter share gains."})
    assert res.status_code == 200
    body = res.json()
    assert body["folder"] == "organisation/finance/stocks-research/amd"

    edges = get_graph_store().edges_from(body["note_id"])
    assert holding_node_id("amd") == "holding:AMD"  # new id kind, "<type>:<rest>" convention
    assert [(e["kind"], e["target_id"], e["source_of_edge"]) for e in edges] == [
        ("thesis_for", "holding:AMD", "structural")
    ]

    # /graph emits the holding node even before any transaction exists.
    graph = client.get("/graph").json()
    holding_nodes = [n for n in graph["nodes"] if n["type"] == "holding"]
    assert [n["id"] for n in holding_nodes] == ["holding:AMD"]
    assert any(e["kind"] == "thesis_for" and e["target"] == "holding:AMD" for e in graph["edges"])


def test_passed_research_is_kept_and_marked(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    client.post("/stocks/research", json={"symbol": "RIVN", "status": "passed", "content": "Cash burn too high; revisit if gross margin turns."})
    client.post("/stocks/research", json={"symbol": "AMD", "status": "owned", "content": "Owned thesis."})

    notes = client.get("/stocks/research").json()
    by_symbol = {n["symbol"]: n for n in notes}
    assert by_symbol["RIVN"]["status"] == "passed"  # looked, passed, kept — recorded owner intent
    assert by_symbol["AMD"]["status"] == "owned"

    # The status is in the note BODY (folder-scoped chat reads bodies only).
    note_path = tmp_path / "kb" / "organisation" / "finance" / "stocks-research" / "rivn" / "rivn-thesis.md"
    assert "passed" in note_path.read_text(encoding="utf-8")


def test_sell_without_position_errors_vs_dividend(tmp_path):
    repo = make_repo(tmp_path)
    try:
        repo.log_transaction(date(2026, 1, 5), "short", "AAPL", qty=1, price=1)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# --- MCP: write through ledger + staged undo ---


def test_mcp_stock_transaction_commit_and_undo(tmp_path):
    from quintacle_core.mcp_server import server as mcp_server

    mcp_server.init(tmp_path)
    init_graph_store(tmp_path, mcp_server.db_conn)

    result = mcp_server.log_stock_transaction(for_date="2026-01-05", action="buy", symbol="aapl", qty=3, price=150, fees=1)
    assert result["symbol"] == "AAPL"
    tx_dir = mcp_server.stocks_repo.store.dir()
    assert len(list(tx_dir.glob("2026-01-05-*.md"))) == 1
    assert len(mcp_server.stocks_repo.transactions()) == 1
    assert "ledger_id" in result

    positions = mcp_server.stock_positions()
    assert positions["positions"][0]["cost_basis"] == 451  # 3*150 + 1 fee
    assert positions["prices_as_of"] is None  # no snapshot yet, surfaced not faked

    mcp_server.undo_write(result["ledger_id"])
    assert len(list(tx_dir.glob("2026-01-05-*.md"))) == 0  # staged file restored away
    assert len(mcp_server.stocks_repo.transactions()) == 0  # sqlite row reversed
