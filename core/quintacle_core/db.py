from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    protein_g REAL NOT NULL DEFAULT 0,
    carbs_g REAL NOT NULL DEFAULT 0,
    fat_g REAL NOT NULL DEFAULT 0,
    fiber_g REAL NOT NULL DEFAULT 0,
    kcal REAL NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS meal_micros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id INTEGER NOT NULL REFERENCES meals(id),
    nutrient TEXT NOT NULL,
    amount REAL NOT NULL,
    unit TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    basis_amount_g REAL NOT NULL DEFAULT 100,
    protein_g REAL NOT NULL DEFAULT 0,
    carbs_g REAL NOT NULL DEFAULT 0,
    fat_g REAL NOT NULL DEFAULT 0,
    fiber_g REAL NOT NULL DEFAULT 0,
    kcal REAL NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS ingredient_micros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id),
    nutrient TEXT NOT NULL,
    amount REAL NOT NULL,
    unit TEXT NOT NULL
);

-- Composition of a "composed" meal preset — a meal built from known
-- ingredients at specific quantities, its totals derived by deterministic
-- arithmetic rather than a fresh AI guess every time. A meal with no rows
-- here is just a flat/manually-entered preset, exactly as before.
CREATE TABLE IF NOT EXISTS meal_ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id INTEGER NOT NULL REFERENCES meals(id),
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id),
    quantity_g REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS food_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    meal_type TEXT NOT NULL,
    meal_id INTEGER REFERENCES meals(id),
    freeform_kcal REAL,
    servings REAL NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS substance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    substance TEXT NOT NULL,
    amount REAL NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    hours REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS exercise_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    exercise_name TEXT NOT NULL,
    performance_text TEXT NOT NULL,
    sets_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS body_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS expense_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    merchant TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'regular'
);

-- Stock transaction ledger (docs/next-wave-plan.md §2) — SQLite is the fast
-- index; markdown under kb/.../Stocks & Investments/transactions/ is the
-- source of truth (see nodes/stocks/store.py, rebuild_stock_index).
-- Positions / cost basis / P&L are NEVER stored — always computed from these
-- rows (nodes/stocks/positions.py). source_file is the backing markdown
-- filename, so a delete can remove the real record too.
CREATE TABLE IF NOT EXISTS stock_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    action TEXT NOT NULL,
    symbol TEXT NOT NULL,
    qty REAL NOT NULL DEFAULT 0,
    price REAL NOT NULL DEFAULT 0,
    fees REAL NOT NULL DEFAULT 0,
    account TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    source_file TEXT NOT NULL DEFAULT ''
);

-- EOD price snapshots, append-only — one row per (symbol, trading day),
-- written only by the explicit /stocks/prices/refresh fetch (no daemons).
-- Deliberately SQLite-only, no markdown mirror: this is PUBLIC, re-fetchable
-- market data (a local cache), not a personal record — losing it loses
-- nothing that can't be fetched again. Valuation always reads the latest
-- row per symbol; older rows stay as portfolio-value-over-time history.
CREATE TABLE IF NOT EXISTS stock_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    price_date TEXT NOT NULL,
    price REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'stooq',
    fetched_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_prices_symbol_date ON stock_prices(symbol, price_date);

-- Income side of the ledger (next-wave-plan §1 decision 3, 2026-10-19):
-- separate table, not negative expenses — spend analytics never have to
-- filter income out, and savings rate is a plain two-table subtraction.
CREATE TABLE IF NOT EXISTS income_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'salary',
    notes TEXT NOT NULL DEFAULT ''
);

-- Versioned habits (next-wave-plan §8, 2026-10-20): `habits` is IDENTITY
-- only — id, name (unique), ended_on (NULL = live; set = the last date the
-- habit is still judged). The value columns below (target_amount …) are the
-- pre-versioning legacy shape: they stay physically (dropping columns is a
-- table rebuild for no gain) and still receive the latest values on create,
-- but NOTHING reads them after this wave — habit_versions is the only
-- source of targets.
CREATE TABLE IF NOT EXISTS habits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    target_amount REAL NOT NULL,
    target_period TEXT NOT NULL,
    match_category TEXT,
    unit TEXT NOT NULL DEFAULT '',
    metric TEXT NOT NULL DEFAULT 'activity_hours',
    direction TEXT NOT NULL DEFAULT 'at_least'
);

-- Effective-dated versions of a habit's targets (next-wave-plan §8).
-- effective_from is the PERIOD-START date this version takes force: a new
-- habit starts at the current period's start (it counts this week), an edit
-- at the NEXT period start (the current period finishes under the old
-- target). Past windows are always judged against the version in force at
-- their start. Rows are append-only — ties on effective_from resolve to the
-- highest id (the latest edit wins), earlier rows stay as history.
CREATE TABLE IF NOT EXISTS habit_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    habit_id INTEGER NOT NULL REFERENCES habits(id),
    effective_from TEXT NOT NULL,
    target_amount REAL NOT NULL,
    target_period TEXT NOT NULL,
    match_category TEXT,
    unit TEXT NOT NULL DEFAULT '',
    metric TEXT NOT NULL DEFAULT 'activity_hours',
    direction TEXT NOT NULL DEFAULT 'at_least',
    match_kind TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_habit_versions_habit_from ON habit_versions(habit_id, effective_from);

-- Mirrors graph/edges/*.md (see quintacle_core/graph.py) — a derived,
-- fast-query cache, never the source of truth. id is the edge file's
-- filename stem; source_id/target_id reuse /graph's existing id scheme
-- ("note:folder/slug", "journal:date", "experience:folder/slug").
CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    source_of_edge TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_edges_source_id ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target_id ON edges(target_id);
"""

# habits.metric/direction were added after the table already existed in some
# installs — ALTER TABLE is idempotent-by-hand since SQLite has no
# "ADD COLUMN IF NOT EXISTS"; ignore the duplicate-column error on re-run.
_MIGRATIONS = [
    "ALTER TABLE habits ADD COLUMN metric TEXT NOT NULL DEFAULT 'activity_hours'",
    "ALTER TABLE habits ADD COLUMN direction TEXT NOT NULL DEFAULT 'at_least'",
    "ALTER TABLE meals ADD COLUMN fiber_g REAL NOT NULL DEFAULT 0",
    "ALTER TABLE exercise_sets ADD COLUMN sets_json TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE exercise_sets ADD COLUMN notes TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE body_stats ADD COLUMN unit TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE expense_log ADD COLUMN kind TEXT NOT NULL DEFAULT 'regular'",
    # Budget lines (next-wave-plan §1 decision 2): the spend metric's matcher.
    # match_kind = one of the 7 expense kinds; match_category doubles as the
    # whole-word text-match terms for spend habits (see quotas.py).
    "ALTER TABLE habits ADD COLUMN match_kind TEXT",
    # Versioned habits (next-wave-plan §8): NULL = live; a date = the last day
    # the habit is still judged (end-dating never deletes the row).
    "ALTER TABLE habits ADD COLUMN ended_on TEXT",
    # Backfill: one initial version per pre-versioning habit, in force since
    # forever ('0001-01-01'). Pre-versioning weeks are therefore judged
    # against the targets current AT MIGRATION TIME — the only honest reading,
    # since no edit history exists to reconstruct what they "really" were.
    # Idempotent via the NOT IN guard (this list re-runs on every connect).
    """INSERT INTO habit_versions
         (habit_id, effective_from, target_amount, target_period, match_category,
          unit, metric, direction, match_kind, created_at)
       SELECT id, '0001-01-01', target_amount, target_period, match_category,
              unit, metric, direction, match_kind, '0001-01-01'
       FROM habits WHERE id NOT IN (SELECT habit_id FROM habit_versions)""",
]


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for migration in _MIGRATIONS:
        try:
            conn.execute(migration)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e):
                raise
    conn.commit()
    return conn
