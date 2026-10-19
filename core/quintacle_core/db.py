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
