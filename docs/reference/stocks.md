# Stocks — transaction ledger, computed positions, EOD snapshots, research folders

Derived from code at commit `72036cd` on 2026-10-19. Spec and recorded
decisions: `docs/next-wave-plan.md` §2 ("records vs reasoning — two
different animals, deliberately").

Four pieces: a markdown-backed **transaction ledger**
([core/quintacle_core/nodes/stocks/store.py](../../core/quintacle_core/nodes/stocks/store.py)),
pure-arithmetic **position/P&L computation**
([positions.py](../../core/quintacle_core/nodes/stocks/positions.py)),
free **EOD price snapshots**
([prices.py](../../core/quintacle_core/nodes/stocks/prices.py)), and
per-company **research folders** wired to holdings through the graph
([api.py](../../core/quintacle_core/nodes/stocks/api.py)).

## The ledger (records)

One markdown file per transaction —
`kb/organisation/finance/stocks-and-investments/transactions/YYYY-MM-DD-NNN.md`,
frontmatter `type: stock_transaction` plus
`date/action/symbol/qty/price/fees/account`, notes in the body — the same
source-of-truth contract as LogFileStore's dated logs. SQLite's
`stock_transactions` table (schema in
[db.py](../../core/quintacle_core/db.py)) is a disposable index:
`rebuild_stock_index(store, conn)` wipes and repopulates it from the files,
and runs inside `sync.rebuild_derived_indexes()` after every pull. Row ids
renumber on rebuild, which is safe because nothing references them — the
stable graph anchor is `holding:<TICKER>`.

Row semantics (uniform columns, per store.py's module docstring):

| action     | qty                | price              | fees                       |
|------------|--------------------|--------------------|----------------------------|
| `buy`      | shares bought      | per share          | added to the lot's basis   |
| `sell`     | shares sold        | per share          | subtracted from proceeds   |
| `dividend` | 0 (shares unchanged) | TOTAL cash received | —                        |

Deleting a transaction (`DELETE /stocks/transactions/{id}`) removes the
markdown file too — the index row carries `source_file` so the real record
and the cache never diverge.

## Positions — computed, never stored

`compute_positions(rows, latest_price_by_symbol)` is a pure function run on
every read of `GET /stocks/positions` (and the MCP `stock_positions` tool).
FIFO lot accounting: each buy opens a lot (fees folded in); each sell
consumes oldest lots first; realized P&L = proceeds − consumed lot cost −
sell fees. Dividends accumulate as per-symbol income, never touching share
count or basis. Selling more than the lots hold consumes what exists, the
excess realizes at zero basis, and the position is flagged `oversold`
(visible data-entry error, not a crash). Output per symbol: `qty`,
`cost_basis`, `avg_cost`, `realized_pnl`, `dividends`, and — only when a
snapshot exists — `last_price`/`last_price_date`/`market_value`/
`unrealized_pnl` (otherwise `null`, surfaced as "—"). The old static
`InvestmentStore` record is superseded by this derived view (the §2
decision); the store itself still exists pending a merge-time retirement.

## EOD price snapshots

`stock_prices` is append-only, one row per `(symbol, price_date)` (UNIQUE
index; re-fetching the same trading day is a no-op — an EOD close is a fixed
fact). It is deliberately SQLite-only with no markdown mirror and is NOT
rebuilt/synced: public, re-fetchable market data, i.e. a local cache, not a
personal record. Old rows stay — portfolio-value-over-time raw material.

Fetching happens ONLY via `POST /stocks/prices/refresh` (no background
daemon), defaulting to every currently-held symbol. Sources:

- **stooq** (default): `https://stooq.com/q/l/?s=<sym>&f=sd2t2ohlcv&h&e=csv`,
  plain stdlib urllib — zero new dependencies, so `core/requirements.txt`
  stays phone/Termux-safe. US tickers get the `.us` suffix automatically.
- **yfinance** (optional lane): `core/stocks-requirements.txt`, lazy import,
  selected per request (`source` in the body) or via
  `QUINTACLE_PRICE_SOURCE=yfinance`. Not installed ⇒ a readable
  PriceFetchError, never an ImportError at startup.

Degradation: each symbol fetches independently; a failure lands in the
response as `{symbol, error, stale: <last stored snapshot or null>}` and the
positions endpoint keeps valuing against the newest stored row, whose date
(`prices_as_of`, per-position `last_price_date`) the frontend always shows —
stale is visible, never silent. `fetched_at` stamps use `clock.now()`
(Eastern), like every other timestamp. Tests stub the HTTP callable
(`fetch_stooq(http_get=...)` / monkeypatching `prices._http_get`) so the
suite runs fully offline.

## Research folders (reasoning) and the graph

`POST /stocks/research {symbol, status, content}` writes (upsert-by-title)
a thesis note into `Organisation/Finance/Stocks Research/<TICKER>/` via
KBStore — ordinary KB notes, so folder-scoped chat/drop/graph all see them —
with `fields: {symbol, status}` and the status ALSO rendered into the body
(folder-scoped chat reads bodies only; same lesson as credit cards).
Status ∈ `owned | watching | passed`; **passed theses are kept and marked**,
per the recorded decision — "looked, passed, here's why" is half the value
at re-evaluation.

Each write materializes `note:<folder>/<slug> --thesis_for--> holding:<TICKER>`
(`source_of_edge: structural`). `holding:` is a new id kind in the existing
`<type>:<rest>` scheme (graph.py): ticker-keyed, stable across rebuilds, and
valid with zero transactions. `/graph` emits a holding node for every symbol
in the ledger plus every `holding:` id an edge references.

## Endpoints

| Method/path                        | What |
|------------------------------------|------|
| `POST /stocks/transactions`        | Save one ledger row (the in-app form's Save) |
| `GET /stocks/transactions[?symbol]`| Rows, date-ordered |
| `DELETE /stocks/transactions/{id}` | Remove row + its markdown file |
| `GET /stocks/positions`            | Computed positions + totals + `prices_as_of` |
| `POST /stocks/prices/refresh`      | Explicit EOD fetch (`{symbols?, source?}`) |
| `GET /stocks/prices/{symbol}`      | Full snapshot history, oldest first |
| `POST /stocks/research`            | Thesis note + `thesis_for` edge |
| `GET /stocks/research`             | Every thesis note with status/folder |

MCP (ledger + staged-undo like every write tool; `stock_transactions` added
to undo's allowed tables): `log_stock_transaction` (write),
`stock_positions` (free, deterministic read — no fetch).

## Frontend

`frontend/app/stocks/page.tsx` (nav: Life → Stocks): positions table of
finished server-computed numbers, `prices as of <date> (EOD)` + explicit
refresh button (per-symbol failures shown as a stale-snapshot notice),
transaction form/list with delete, research section with status badges and
links into each company's KB folder. API client types/functions in
`frontend/lib/api.ts` (`StockTransaction`, `StockPositions`, …).

## Tests

`core/tests/test_stocks.py` — 15 tests, fully offline: FIFO basis across
lots, partial-sell realized P&L, dividends, oversell flagging, snapshot
append/latest-selection, stubbed Stooq parse + unknown-ticker error,
markdown rebuild/delete, refresh degradation through the live app,
thesis↔holding edge creation (+ `/graph` emission), passed-thesis retention,
and MCP commit/undo round-trip.
