"""/stocks — the transaction ledger, computed positions, EOD price refresh,
and per-company research folders (docs/next-wave-plan.md §2).

Write gating: these endpoints are the Save step of the in-app
propose→review→Save flow — the frontend form is the review; nothing here is
model-driven. The MCP lane writes through the ledger+staged-undo machinery
in mcp_server/server.py instead, never through raw HTTP.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import frontmatter
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...graph import create_edge
from ...markdown_paths import resolve_nested
from ..kb.store import KBStore
from .positions import compute_positions
from .prices import PriceFetchError, fetch_eod
from .store import (
    ACTIONS,
    RESEARCH_HOME,
    StocksRepository,
    StockTransactionStore,
    holding_node_id,
    normalize_symbol,
)

router = APIRouter(prefix="/stocks", tags=["stocks"])

_repo: StocksRepository | None = None
_kb_root: Path | None = None

# The statuses a thesis note cycles through — "passed" notes are kept on
# purpose ("looked, passed, here's why" is half the value at re-evaluation,
# per §2's recorded decision), never deleted when a buy doesn't happen.
RESEARCH_STATUSES = ("owned", "watching", "passed")


def init_store(conn: sqlite3.Connection, kb_root: Path) -> None:
    global _repo, _kb_root
    _repo = StocksRepository(conn, StockTransactionStore(kb_root))
    _kb_root = Path(kb_root)


def get_stocks_repo() -> StocksRepository:
    if _repo is None:
        raise RuntimeError("stocks store not initialized — call init_store() first")
    return _repo


def _kb_store() -> KBStore:
    if _kb_root is None:
        raise RuntimeError("stocks store not initialized — call init_store() first")
    return KBStore(_kb_root)


# --- transactions ---


class TransactionCreate(BaseModel):
    date: date
    action: str
    symbol: str
    qty: float = 0
    price: float = 0
    fees: float = 0
    account: str = ""
    notes: str = ""


@router.post("/transactions")
def log_transaction(body: TransactionCreate) -> dict:
    if body.action not in ACTIONS:
        raise HTTPException(400, f"action must be one of {ACTIONS}")
    if not normalize_symbol(body.symbol):
        raise HTTPException(400, "symbol is required")
    if body.action in ("buy", "sell") and body.qty <= 0:
        raise HTTPException(400, f"a {body.action} needs qty > 0")
    if body.price < 0 or body.fees < 0 or body.qty < 0:
        raise HTTPException(400, "qty/price/fees cannot be negative")
    tx_id = get_stocks_repo().log_transaction(
        body.date, body.action, body.symbol, body.qty, body.price, body.fees, body.account, body.notes
    )
    return {"id": tx_id, "symbol": normalize_symbol(body.symbol)}


@router.get("/transactions")
def list_transactions(symbol: str | None = None) -> list[dict]:
    return [dict(row) for row in get_stocks_repo().transactions(symbol)]


@router.delete("/transactions/{tx_id}")
def delete_transaction(tx_id: int) -> dict:
    """The in-app undo for a mis-entered row — removes the markdown record
    AND its index row, the same delete-the-file mechanism every other
    Quintacle undo uses."""
    if not get_stocks_repo().delete_transaction(tx_id):
        raise HTTPException(404, f"no such transaction: {tx_id}")
    return {"deleted": tx_id}


# --- positions (always computed, never stored) ---


@router.get("/positions")
def positions() -> dict:
    repo = get_stocks_repo()
    latest = repo.latest_prices()
    result = compute_positions([dict(r) for r in repo.transactions()], latest)
    snapshot_dates = [s["price_date"] for s in latest.values()]
    # The valuation's freshness, surfaced instead of hidden: offline just
    # means this date goes stale, never an error (§2's "graceful offline").
    result["prices_as_of"] = max(snapshot_dates) if snapshot_dates else None
    return result


# --- EOD price snapshots (explicit refresh only — no background daemons) ---


class PriceRefreshRequest(BaseModel):
    symbols: list[str] | None = None  # default: every symbol currently held
    source: str | None = None  # default: QUINTACLE_PRICE_SOURCE env, else stooq


@router.post("/prices/refresh")
def refresh_prices(body: PriceRefreshRequest | None = None) -> dict:
    body = body or PriceRefreshRequest()
    repo = get_stocks_repo()
    if body.symbols:
        symbols = [normalize_symbol(s) for s in body.symbols if normalize_symbol(s)]
    else:
        computed = compute_positions([dict(r) for r in repo.transactions()])
        symbols = [p["symbol"] for p in computed["positions"] if p["qty"] > 0]

    results = []
    for symbol in symbols:
        try:
            snap = fetch_eod(symbol, source=body.source)
        except PriceFetchError as e:
            # One bad ticker/outage degrades to a per-symbol error with the
            # last stored snapshot alongside — the page keeps showing stale
            # valuation with its date, never a blank or a 500.
            stale = repo.latest_price(symbol)
            results.append({"symbol": symbol, "error": str(e), "stale": dict(stale) if stale else None})
            continue
        stored = repo.add_price_snapshot(snap["symbol"], snap["price_date"], snap["price"], snap["source"], snap["fetched_at"])
        results.append({**snap, "stored": stored})
    return {
        "results": results,
        "fetched": sum(1 for r in results if "error" not in r),
        "errors": sum(1 for r in results if "error" in r),
    }


@router.get("/prices/{symbol}")
def price_history(symbol: str) -> list[dict]:
    """Every stored snapshot for one symbol, oldest first — the
    portfolio-value-over-time raw material §2 wanted falling out for free."""
    return [dict(row) for row in get_stocks_repo().price_history(symbol)]


# --- research folders (the "reasoning" layer) ---


class ResearchCreate(BaseModel):
    symbol: str
    status: str = "watching"
    title: str | None = None  # default: "<SYMBOL> thesis"
    content: str = ""


@router.post("/research")
def write_research(body: ResearchCreate) -> dict:
    """Creates (or updates, upsert-by-title) a company's thesis note in its
    own folder under Stocks Research/<SYMBOL>/, and materializes the
    thesis↔holding graph edge. The holding:<SYMBOL> node needs no
    transactions to exist — a researched-but-passed company anchors there
    too, so if it's ever bought the trail is already connected."""
    symbol = normalize_symbol(body.symbol)
    if not symbol:
        raise HTTPException(400, "symbol is required")
    if body.status not in RESEARCH_STATUSES:
        raise HTTPException(400, f"status must be one of {RESEARCH_STATUSES}")

    title = body.title or f"{symbol} thesis"
    # Status rendered into the body, not just frontmatter — the folder-scoped
    # chat reads bodies only (same lesson as CreditCardStore._compose_body).
    status_line = {
        "owned": "Status: owned — thesis behind a live position.",
        "watching": "Status: watching — researched, undecided.",
        "passed": "Status: passed — researched and deliberately NOT bought; kept for re-evaluation.",
    }[body.status]
    content = f"{status_line}\n\n{body.content}".strip()
    folder_slug, entry_slug = _kb_store().write(
        f"{RESEARCH_HOME}/{symbol}", title, content, fields={"symbol": symbol, "status": body.status}
    )
    note_id = f"note:{folder_slug}/{entry_slug}"
    edge = create_edge(note_id, holding_node_id(symbol), "thesis_for", "structural")
    return {"folder": folder_slug, "slug": entry_slug, "note_id": note_id, "edge_id": edge["id"], "status": body.status}


@router.get("/research")
def list_research() -> list[dict]:
    """Every thesis note across every company folder — including the passed
    ones, marked as such, because keeping those is recorded owner intent."""
    research_dir = resolve_nested(Path(_kb_root), RESEARCH_HOME)
    if not research_dir.exists():
        return []
    results = []
    for path in sorted(research_dir.rglob("*.md")):
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        fields = post.metadata.get("fields") or {}
        company_dir = path.parent.relative_to(research_dir)
        symbol = fields.get("symbol") or str(company_dir).upper()
        folder_slug = str(path.parent.relative_to(Path(_kb_root))).replace("\\", "/")
        first_line = post.content.strip().splitlines()[0] if post.content.strip() else ""
        title = first_line.lstrip("# ").strip() if first_line.startswith("#") else path.stem.replace("-", " ")
        results.append(
            {
                "symbol": symbol,
                "status": fields.get("status", "watching"),
                "title": title,
                "folder": folder_slug,
                "slug": path.stem,
            }
        )
    return results
