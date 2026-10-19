"""Stock transaction ledger — docs/next-wave-plan.md §2's "Records (what I
own)" layer.

Shape, per the recorded decisions there:
- Buys AND sells (and dividends) per ticker over time, as individual rows.
- Cost basis / realized P&L / positions are COMPUTED from these rows
  (positions.py), never stored — the old static InvestmentStore record
  becomes a derived view over transactions.
- Markdown is the source of truth (one file per transaction under
  `Organisation/Finance/Stocks & Investments/transactions/`, same contract
  as LogFileStore's dated logs); SQLite's `stock_transactions` table is a
  fast, disposable index rebuilt via rebuild_stock_index().

Row semantics (uniform columns date/action/symbol/qty/price/fees/account):
- action="buy":      qty shares at `price` each; `fees` add to the lot's
                     cost basis.
- action="sell":     qty shares at `price` each; `fees` subtract from the
                     realized proceeds.
- action="dividend": `price` is the TOTAL cash received (qty stays 0 — a
                     dividend has no per-share meaning worth hand-entering;
                     share count never changes).
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import frontmatter

from ...markdown_paths import resolve_nested

# Same KB pillar the strategy notes / static holdings already live in, so a
# folder-scoped chat on "Stocks & Investments" sees the real ledger rows'
# folder right alongside the prose.
TRANSACTIONS_HOME = "Organisation/Finance/Stocks & Investments"

# One folder per company — §2's "Reasoning (why I own it)" layer. Thesis
# notes land in RESEARCH_HOME/<SYMBOL>/ and get a thesis_for edge to the
# holding:<SYMBOL> graph node (see api.py).
RESEARCH_HOME = "Organisation/Finance/Stocks Research"

ACTIONS = ("buy", "sell", "dividend")


def holding_node_id(symbol: str) -> str:
    """The graph id anchoring everything about one ticker — fits the
    established "<type>:<rest>" scheme (graph.py module docstring) with a
    new `holding` kind. Keyed by ticker, not a SQLite row id, so it's stable
    across index rebuilds and exists even for researched-but-passed
    companies that have no transactions at all."""
    return f"holding:{normalize_symbol(symbol)}"


def normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper()


class StockTransactionStore:
    """One markdown file per transaction, `YYYY-MM-DD-NNN.md`, frontmatter
    only plus free-prose notes in the body — the same filename and
    source-of-truth contract as LogFileStore's dated logs."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def dir(self) -> Path:
        path = resolve_nested(self.kb_root, TRANSACTIONS_HOME) / "transactions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(
        self,
        entry_date: date,
        action: str,
        symbol: str,
        qty: float = 0,
        price: float = 0,
        fees: float = 0,
        account: str = "",
        notes: str = "",
    ) -> str:
        if action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}, got {action!r}")
        symbol = normalize_symbol(symbol)
        if not symbol:
            raise ValueError("symbol is required")
        tx_dir = self.dir()
        seq = len(list(tx_dir.glob(f"{entry_date.isoformat()}-*.md"))) + 1
        filename = f"{entry_date.isoformat()}-{seq:03d}.md"

        post = frontmatter.Post(notes)
        post["type"] = "stock_transaction"
        post["date"] = entry_date.isoformat()
        post["action"] = action
        post["symbol"] = symbol
        post["qty"] = qty
        post["price"] = price
        post["fees"] = fees
        post["account"] = account
        (tx_dir / filename).write_text(frontmatter.dumps(post), encoding="utf-8")
        return filename

    def all_entries(self) -> list[dict]:
        entries = []
        for path in sorted(self.dir().glob("*.md")):
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
            if post.metadata.get("type") != "stock_transaction":
                continue  # a stray chat-pushed note in the same folder must not poison the ledger
            entries.append({**post.metadata, "notes": post.content, "file": path.name})
        return entries

    def delete(self, filename: str) -> bool:
        # Clamp to a bare filename inside the transactions dir — never a path.
        path = self.dir() / Path(filename).name
        if path.exists():
            path.unlink()
            return True
        return False


class StocksRepository:
    """SQLite index + price-snapshot queries over one db connection — the
    same conn/markdown split as LogsRepository (markdown truth when a store
    is attached; plain SQLite in index-only tests)."""

    def __init__(self, conn: sqlite3.Connection, store: StockTransactionStore | None = None):
        self.conn = conn
        self.store = store

    # --- transactions ---

    def log_transaction(
        self,
        entry_date: date,
        action: str,
        symbol: str,
        qty: float = 0,
        price: float = 0,
        fees: float = 0,
        account: str = "",
        notes: str = "",
    ) -> int:
        symbol = normalize_symbol(symbol)
        source_file = ""
        if self.store:
            source_file = self.store.write(entry_date, action, symbol, qty, price, fees, account, notes)
        elif action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}, got {action!r}")
        cur = self.conn.execute(
            """INSERT INTO stock_transactions (date, action, symbol, qty, price, fees, account, notes, source_file)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry_date.isoformat(), action, symbol, qty, price, fees, account, notes, source_file),
        )
        self.conn.commit()
        return cur.lastrowid

    def delete_transaction(self, tx_id: int) -> bool:
        row = self.conn.execute("SELECT * FROM stock_transactions WHERE id = ?", (tx_id,)).fetchone()
        if row is None:
            return False
        if self.store and row["source_file"]:
            self.store.delete(row["source_file"])
        self.conn.execute("DELETE FROM stock_transactions WHERE id = ?", (tx_id,))
        self.conn.commit()
        return True

    def transactions(self, symbol: str | None = None) -> list[sqlite3.Row]:
        if symbol:
            return self.conn.execute(
                "SELECT * FROM stock_transactions WHERE symbol = ? ORDER BY date, id",
                (normalize_symbol(symbol),),
            ).fetchall()
        return self.conn.execute("SELECT * FROM stock_transactions ORDER BY date, id").fetchall()

    def all_symbols(self) -> list[str]:
        return [r["symbol"] for r in self.conn.execute("SELECT DISTINCT symbol FROM stock_transactions ORDER BY symbol")]

    # --- price snapshots (append-only; see db.py's stock_prices comment) ---

    def add_price_snapshot(self, symbol: str, price_date: str, price: float, source: str, fetched_at: str) -> bool:
        """Appends one EOD snapshot row; returns False when that (symbol,
        trading day) is already recorded — an EOD close for a past date is a
        fixed fact, so re-refreshing the same day is a no-op, not an update."""
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO stock_prices (symbol, price_date, price, source, fetched_at)
               VALUES (?, ?, ?, ?, ?)""",
            (normalize_symbol(symbol), price_date, price, source, fetched_at),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def latest_price(self, symbol: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM stock_prices WHERE symbol = ? ORDER BY price_date DESC, id DESC LIMIT 1",
            (normalize_symbol(symbol),),
        ).fetchone()

    def latest_prices(self) -> dict[str, dict]:
        """Newest snapshot per symbol, one query — {symbol: row-as-dict}."""
        rows = self.conn.execute(
            """SELECT p.* FROM stock_prices p
               JOIN (SELECT symbol, MAX(price_date) AS md FROM stock_prices GROUP BY symbol) latest
                 ON p.symbol = latest.symbol AND p.price_date = latest.md
               ORDER BY p.symbol"""
        ).fetchall()
        return {r["symbol"]: dict(r) for r in rows}

    def price_history(self, symbol: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM stock_prices WHERE symbol = ? ORDER BY price_date",
            (normalize_symbol(symbol),),
        ).fetchall()


def rebuild_stock_index(store: StockTransactionStore, conn: sqlite3.Connection) -> int:
    """Wipes and repopulates `stock_transactions` from the markdown files —
    the disposable-cache half of the contract, same as
    log_store.rebuild_sqlite_index. Row ids renumber on rebuild, which is
    safe here: nothing (graph edges included) ever references a transaction
    row id — the stable graph anchor is holding:<SYMBOL>. `stock_prices` is
    deliberately untouched: it has no markdown source (public re-fetchable
    data, see db.py)."""
    conn.execute("DELETE FROM stock_transactions")
    n = 0
    for e in store.all_entries():
        conn.execute(
            """INSERT INTO stock_transactions (date, action, symbol, qty, price, fees, account, notes, source_file)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                e["date"],
                e.get("action", ""),
                normalize_symbol(e.get("symbol", "")),
                e.get("qty", 0),
                e.get("price", 0),
                e.get("fees", 0),
                e.get("account", ""),
                e.get("notes", ""),
                e["file"],
            ),
        )
        n += 1
    conn.commit()
    return n
