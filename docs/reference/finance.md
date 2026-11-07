# Finance: insights, budget lines, income, statement imports

Derived from code on 2026-10-19 (finance wave, next-wave-plan §1/§2b).
Code is truth; restamp if regenerated.

The finance wave adds four things on top of the existing expense ledger
(`expense_log`, 7 kinds, Drop/Journal/MCP capture): deterministic spend
analytics, named budget lines in the quota engine, an income side, and a
statement-drop import lane. The governing principle everywhere: **models
never re-derive numbers** — all arithmetic is SQL/code; the only model call
in this whole area is the optional PDF/photo statement *transcription*.

## Data

- `expense_log` (unchanged): `date, amount, merchant, category, notes, kind`.
- `income_log` (new, `db.py`): `date, amount, source, kind(salary|other),
  notes`. Separate table, deliberately NOT negative expenses — spend
  analytics never filter income out, and savings is a two-table subtraction.
  Markdown record: `Organisation/Finance/logs/*.md` with `type: income`
  frontmatter (shares the folder with `type: finance` expense logs; readers
  filter by type). `rebuild_sqlite_index` covers it.
- `habits.match_kind` (new column, idempotent ALTER migration): one of the 7
  expense kinds, used only by the spend metric.
- Graph: `income:<id>` rows label like expenses do (`graph_capture._LOG_ROW_LABELS`);
  day counts include income entries.

## Insights (`core/quintacle_core/nodes/finance/insights.py`)

Pure functions over the SQLite connection; served by `finance/api.py`'s
`finance_router` (prefix `/finance`):

- `GET /finance/insights/monthly?months=12` → per calendar month (Eastern,
  oldest first): `total`, `by_kind`, `income`, `savings`,
  `savings_rate_pct` (null when income is 0), `delta_total` /
  `delta_by_kind` vs the previous month (null for the first).
- `GET /finance/insights/merchants?start&end&limit` → merchant rollup
  (case/whitespace-insensitive grouping): count, total, average, last_date,
  biggest total first.
- `GET /finance/insights/movers?limit` → per-merchant month-to-date delta,
  this month vs last, largest absolute swing first.
- `GET /finance/insights/subscriptions` → recurrence detection over ALL
  expenses (not just kind=subscription): group by merchant, cluster similar
  amounts (±max($1, 5%)), a cluster with ≥2 charges whose median gap fits a
  cadence band (weekly 5–9d, monthly 26–36d, yearly 350–380d) is recurring.
  Each line: avg amount, cadence, charge count, `next_expected`
  (last + median gap), `active` (not overdue by more than half an
  interval), `monthly_equivalent`; plus total `monthly_burn` of active
  lines. Constants are deliberate, in code, not model-tunable.

Frontend: Finance page → **Insights** tab (`frontend/app/finance/page.tsx`,
`InsightsView`) — stat tiles, by-kind bars with MoM deltas, monthly table,
top merchants, movers, detected recurring charges, income quick-add + list.
Rendering only; display-scaling is the only client-side math.

## Budget lines (quota engine)

`repository.spend_for_habit_between()` is the matcher
(next-wave-plan §1 decision 2): an expense counts toward a spend habit when

- `match_kind` is set and equals the expense's kind, **OR**
- any comma-separated term in `match_category` appears as a whole word
  (case-insensitive, `graph.title_mentioned` — THE matcher) in the
  expense's merchant/category/notes.

Neither set → total spend, so pre-existing "total spend ≤ $X" quotas are
untouched. OR (not AND) so one line can be "kind=alcohol or the word
creatine". `quotas._progress_for_window` now also returns `period_days`
(real month lengths via `calendar.monthrange`), `elapsed_days`, and
`prorated_target` — the even-pace share of the cap by the window's last
day. Dashboard (`frontend/app/habits/page.tsx`) adds the "Budget line ($)"
goal type (kind select + match-words input) and shows the pace line on
spend caps.

## Income

- `POST /logs/income` / `GET /logs/income?start&end` (`logs/api.py`).
- Drop prefixes `income:` / `paycheck:` route AND parse deterministically —
  `drop_router.parse_income_text`: ISO date extracted first (so "2026" never
  reads as an amount), then the first money-shaped number, salary-vs-other
  by keyword regex, remainder = source. No model call; reviewed before Save.
- Savings rate = `(income − spend) / income` per month, computed in
  `insights.monthly_breakdown` only.

## 2026-11-06 — receipt and statement PHOTOS read locally

Receipt photos (`drop_router.extract_finance_from_receipt`) now go local
OCR → `nodes/finance/receipt_parser.parse_receipt`, all in code: merchant
(first name-like top line — skips addresses, phones, URLs, dates, "welcome"),
date (11/05/2026, 11-05-26, 2026-11-05, 05.11.2026 day-first, 25/12/2025,
Nov 5 2026, 5 November 2026 …), total (GRAND TOTAL / AMOUNT DUE / BALANCE
DUE outrank TOTAL, which outranks BALANCE/AMOUNT; SUBTOTAL, TAX, CASH,
CHANGE, TIP, SAVINGS never count; among equals the largest plausible, never
below the subtotal; no total line → subtotal + tax computed in code),
best-effort line items (into `notes` when the owner typed nothing), and a
keyword category/kind guess from the merchant. Fuzzy keyword matching
survives OCR (`T0TAL`). Only when no total is found does the OCR TEXT go to
the local text model, and code's merchant/date still win. `pipeline:
"ocr+parser"` / `"ocr+local-llm"`.

**2026-11-07 correction — two-column / tilted receipts.** The owner's real
Toast POS receipt (Pink Tiger) parsed total **$19.00**; the printed total is
**$510.13**. Cause: the phone photo sat ~9° off level, so the price column ran
~85 px lower than its labels, and RapidOCR's axis-aligned boxes of tilted
text were twice their real height — row grouping chained the receipt into a
few giant rows, and "Subtotal … $19.00" (the burger's price) became the
subtotal → total. Fixed in code, no model:

- `perception/ocr.py` keeps each fragment's quad angle + true width/height,
  undoes the page's dominant angle (`deskew`, `page_angle`), and groups rows
  by deskewed center distance; `OcrResult.fragments` carries the deskewed
  per-fragment boxes.
- `parse_receipt(text, fragments=None)`: with fragments,
  `rows_from_fragments` pairs every money-only fragment with the ONE label
  row whose vertical center is nearest (`_extract_receipt_local` passes them;
  two photos are stacked). Text only: N label lines followed by N amount
  lines (a column dump) are zipped back (`_zip_columns`).
- Percentages ("Operations Fee (5.00%)") are never amounts; tip / gratuity /
  service charge is read (`ReceiptParse.tip`), fees after the subtotal into
  `fees`; suggested-tip tables ("20%: (Tip $83.48 Total $593.61)") ignored.
- Total sanity in code: a labelled total must be ≥ subtotal; the candidate
  equal to subtotal + tax + tip (+ fees) wins (confidence 0.95); a labelled
  total below that sum keeps confidence 0.6; no usable total → the sum is
  computed. An item price is never taken as the total.

Golden check after the fix: amount 19.0 → 510.13 (merchant/date unchanged).
Tests: `core/tests/test_real_world_ocr_fixes.py` (synthetic tilted
two-column fragments, never the real image).

Statement **photos** (`statement:` prefix + an image) → local OCR + the
local text model transcribing rows into the same schema (`ocr+local-llm`),
then the unchanged code validation/dedup. **PDF** statements keep the cloud
document lane (not an image; documented exception). Policy and Redo with
cloud: [perception-and-autojournal.md](perception-and-autojournal.md).

## Statement imports (§2b — drops, not aggregator APIs)

Flow (the review gate, end to end):

1. **Drop** a file on the Drop page. `csv/ofx/qfx` extensions route to
   `statement_import` with no model call; `statement:`/`bank:` prefix routes
   a PDF/photo through `finance/llm.extract_statement_transactions` (the
   same cloud vision pattern as receipt extraction — the model transcribes
   rows only; `statements.normalize_vision_transactions` drops anything with
   a bad date or non-positive amount in code).
2. **Parse** — `nodes/finance/statements.py`, stdlib only (no new deps in
   `core/requirements.txt`): CSV via `csv` + header-name mapping guess
   (`guess_csv_mapping`) + data-derived sign convention (`negate`); OFX/QFX
   via a hand-rolled regex reader of the minimal SGML/XML `<STMTTRN>`
   subset (`DTPOSTED/TRNAMT/NAME/MEMO`). Credits/payments are skipped and
   counted; spend kinds get a conservative whole-word keyword guess
   (`guess_kind`), user-editable. `annotate_duplicates` flags rows already
   in the ledger or repeated in the batch (same date + amount-to-the-cent +
   merchant, `repository.expense_exists`).
3. **Review** — `frontend/components/StatementImportCard.tsx` inside the
   normal Drop review list: per-row checkbox/date/merchant/amount/kind/notes,
   duplicate rows flagged and unchecked by default, CSV column-mapping
   selects + "Re-parse with this mapping" (client keeps the raw text; calls
   `POST /finance/statement/parse`, which never writes).
4. **Save** — only kept rows go to `POST /finance/statement/import`; each
   becomes a normal `repo.log_expense` write (markdown + SQLite, notes
   suffixed `[statement: <file>]`). Dedup is re-checked at write time —
   skipped unless the row carries the review UI's explicit
   `allow_duplicate` override (set when the user re-checks a flagged row).
   Written rows are event-grouped (`graph_capture.link_event`, one event per
   statement; additive, never blocks the writes). Response: written /
   skipped_duplicates / ids / event_id.

Property check (CLAUDE.md "writes are gated or undoable"): this lane is
gated — nothing is written before the user's per-row review and Save.

## 2026-11-05 — ONE Finances page; manual account balances + net worth

Owner: "finances + stocks whatever becomes Finances — with my budgets, my
spend, my subscriptions", plus "where I can update what I have in my 401k,
what stocks I own, how much liquid I have".

**Frontend.** `/finance` is now a tabbed page (`?tab=` search param, so it
works in the static export): Overview · Accounts · Investments · Spend &
budgets · Subscriptions · Income. Shell: `frontend/app/finance/page.tsx`;
tabs in `frontend/app/finance/_components/` (private folder, not routes).
Everything the old page had moved, nothing dropped: the per-kind expense
ledger + add-expense form and the spend insights (this month by kind,
monthly spend/income/savings, top merchants, movers) → Spend & budgets
(plus budget lines = active `metric="spend"` habits with
`/logs/habits/{id}/progress` bars); detected recurring charges + logged
`kind=subscription` groups → Subscriptions; income form/list + monthly
income → Income; the KB / credit-card / static-holdings / statement-import
links → a footer strip on every tab. The Stocks page became the
Investments tab (see stocks.md). `/stocks` and `/investments` are tiny
client-side redirect pages to `/finance?tab=investments`.

**Backend — accounts** (`core/quintacle_core/nodes/finance/accounts.py`,
endpoints on `finance_router` in `api.py`). One markdown file per account
under `Organisation/Finance/Accounts/` (markdown is truth, no SQLite
mirror). Types → buckets: checking/savings/cash → liquid;
brokerage/crypto → investments; 401k/ira/roth_ira/hsa → retirement;
other_asset → other; credit_card/loan → liabilities (entered as the
positive amount owed, subtracted). Balances are an append-only list of
dated snapshots in frontmatter; "update balance" appends, history is never
overwritten, and an explicit per-snapshot DELETE is the undo (CLAUDE.md
"gated or undoable": the in-app form is the review/Save). Kept separate
from `CreditCardStore`, which records card *benefits/points* — a
`credit_card` account records the *balance owed*. The old static
`InvestmentStore` (`/investments`, `/finance/investments` page) is
untouched and still linked.

**Net worth rule (no double counting)** — computed in `summarize()`:
net worth = latest balance of every account (liabilities negative) + the
stock-ledger value of every OPEN position that is *not covered* by a
recorded account. A position is covered when every account name on its
transactions matches (case-insensitive) a recorded brokerage/crypto/
retirement account that has a balance — that balance already includes it.
Positions with no account name always count. Uncovered positions count at
market value when a price snapshot exists, else at cost basis
(`stock_holdings_at_cost` flags it). `investments_total` = brokerage +
crypto balances + uncovered holdings (retirement is its own bucket). The
net-worth *history* series uses recorded account snapshots only (at each
snapshot date, each account's latest balance as of then) — the stock
ledger has no per-date valuation worth trusting there.

## Tests

`core/tests/`: `test_budget_lines.py`, `test_finance_insights.py`,
`test_income.py`, `test_statements.py`, `test_finance_accounts.py` (2026-11-05: append-only history, buckets/liabilities/history, the no-double-count rule, endpoint round-trip) (+ fixture statements under
`tests/fixtures/`). All seeded with hand-computed expectations; the suite
passes without optional deps. Note: `docs/reference/endpoints.md` predates
these endpoints — restamp it on its next regeneration.
