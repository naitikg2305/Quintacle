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

## Tests

`core/tests/`: `test_budget_lines.py`, `test_finance_insights.py`,
`test_income.py`, `test_statements.py` (+ fixture statements under
`tests/fixtures/`). All seeded with hand-computed expectations; the suite
passes without optional deps. Note: `docs/reference/endpoints.md` predates
these endpoints — restamp it on its next regeneration.
