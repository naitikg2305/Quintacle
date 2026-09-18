from __future__ import annotations

import json
import sqlite3
from datetime import date

from ..journal.normalize import canonicalize_name
from .log_store import IngredientPresetStore, LogFileStore, MealPresetStore, RoutineStore, summarize_sets as _summarize_sets


class LogsRepository:
    def __init__(self, conn: sqlite3.Connection, log_store: LogFileStore | None = None):
        self.conn = conn
        # Markdown (log_store) is the source of truth when present; SQLite is
        # always kept in sync as the fast/queryable side. None here (as in
        # most tests) just means "no markdown backing for this repo instance".
        self.log_store = log_store
        self.preset_store = MealPresetStore(log_store.kb_root) if log_store else None
        self.ingredient_store = IngredientPresetStore(log_store.kb_root) if log_store else None
        self.routine_store = RoutineStore(log_store.kb_root) if log_store else None

    # --- workout routines (named exercise-name templates, no SQLite mirror) ---

    def add_routine(self, name: str, exercises: list[str]) -> str:
        known_routines = [r["name"] for r in self.routine_store.all()] if self.routine_store else []
        name = canonicalize_name(name, known_routines)
        known_exercises = (
            sorted({e["exercise_name"] for e in self.log_store.all_entries("exercise")}) if self.log_store else []
        )
        exercises = [canonicalize_name(e, known_exercises) for e in exercises]
        if self.routine_store:
            self.routine_store.write(name, exercises)
        return name

    def list_routines(self) -> list[dict]:
        return self.routine_store.all() if self.routine_store else []

    def get_meal(self, meal_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()

    # --- meals (premade library) ---

    def add_meal(
        self,
        name: str,
        protein_g: float,
        carbs_g: float,
        fat_g: float,
        kcal: float,
        fiber_g: float = 0,
        notes: str = "",
        micros: list[dict] | None = None,
        components: list[dict] | None = None,
    ) -> int:
        micros = micros or []
        # Deterministic, local — corrects "Lamb" / "lamb" / "Ground Lamb" drift
        # against presets that already exist, the same safety net already used
        # for exercise/substance names, so a slightly-different AI-guessed name
        # updates the existing preset instead of silently forking a duplicate.
        known_names = [r["name"] for r in self.conn.execute("SELECT name FROM meals")]
        name = canonicalize_name(name, known_names)
        if self.preset_store:
            fields = {"protein_g": protein_g, "carbs_g": carbs_g, "fat_g": fat_g, "fiber_g": fiber_g, "kcal": kcal, "notes": notes}
            if components is not None:
                fields["components"] = components
            self.preset_store.write(name, fields, micros)
        # Upsert by name (unique) — redefining an existing preset updates it
        # in place rather than colliding on the UNIQUE constraint, and keeps
        # its id stable for anything that already references it.
        existing = self.conn.execute("SELECT id FROM meals WHERE name = ?", (name,)).fetchone()
        if existing:
            meal_id = existing["id"]
            self.conn.execute(
                "UPDATE meals SET protein_g=?, carbs_g=?, fat_g=?, fiber_g=?, kcal=?, notes=? WHERE id=?",
                (protein_g, carbs_g, fat_g, fiber_g, kcal, notes, meal_id),
            )
            self.conn.execute("DELETE FROM meal_micros WHERE meal_id=?", (meal_id,))
        else:
            cur = self.conn.execute(
                """INSERT INTO meals (name, protein_g, carbs_g, fat_g, fiber_g, kcal, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (name, protein_g, carbs_g, fat_g, fiber_g, kcal, notes),
            )
            meal_id = cur.lastrowid
        for m in micros:
            self.conn.execute(
                "INSERT INTO meal_micros (meal_id, nutrient, amount, unit) VALUES (?, ?, ?, ?)",
                (meal_id, m["nutrient"], m["amount"], m["unit"]),
            )
        self.conn.commit()
        return meal_id

    def list_meals(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM meals ORDER BY name").fetchall()

    # --- ingredients (the atomic, reusable nutrition library meals are built from) ---

    def add_ingredient(
        self,
        name: str,
        protein_g: float,
        carbs_g: float,
        fat_g: float,
        kcal: float,
        fiber_g: float = 0,
        basis_amount_g: float = 100,
        notes: str = "",
        micros: list[dict] | None = None,
    ) -> int:
        micros = micros or []
        known_names = [r["name"] for r in self.conn.execute("SELECT name FROM ingredients")]
        name = canonicalize_name(name, known_names)
        if self.ingredient_store:
            self.ingredient_store.write(
                name,
                {
                    "basis_amount_g": basis_amount_g, "protein_g": protein_g, "carbs_g": carbs_g,
                    "fat_g": fat_g, "fiber_g": fiber_g, "kcal": kcal, "notes": notes,
                },
                micros,
            )
        existing = self.conn.execute("SELECT id FROM ingredients WHERE name = ?", (name,)).fetchone()
        values = (basis_amount_g, protein_g, carbs_g, fat_g, fiber_g, kcal, notes)
        if existing:
            ingredient_id = existing["id"]
            self.conn.execute(
                "UPDATE ingredients SET basis_amount_g=?, protein_g=?, carbs_g=?, fat_g=?, fiber_g=?, kcal=?, notes=? WHERE id=?",
                values + (ingredient_id,),
            )
            self.conn.execute("DELETE FROM ingredient_micros WHERE ingredient_id=?", (ingredient_id,))
        else:
            cur = self.conn.execute(
                "INSERT INTO ingredients (name, basis_amount_g, protein_g, carbs_g, fat_g, fiber_g, kcal, notes) VALUES (?,?,?,?,?,?,?,?)",
                (name,) + values,
            )
            ingredient_id = cur.lastrowid
        for m in micros:
            self.conn.execute(
                "INSERT INTO ingredient_micros (ingredient_id, nutrient, amount, unit) VALUES (?, ?, ?, ?)",
                (ingredient_id, m["nutrient"], m["amount"], m["unit"]),
            )
        self.conn.commit()
        return ingredient_id

    def list_ingredients(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM ingredients ORDER BY name").fetchall()

    def get_ingredient(self, ingredient_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()

    def micros_for_ingredient(self, ingredient_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT nutrient, amount, unit FROM ingredient_micros WHERE ingredient_id = ? ORDER BY nutrient", (ingredient_id,)
        ).fetchall()

    def compute_meal_totals(self, components: list[dict]) -> dict:
        """Pure deterministic arithmetic — no AI involved. Each component is
        {ingredient_id, quantity_g}; totals are the sum of each ingredient's
        stored macros scaled by quantity_g / that ingredient's basis_amount_g.
        This is what makes a composed meal preset self-correcting: fix an
        ingredient's macros once, every meal built from it recomputes right."""
        totals = {"protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fiber_g": 0.0, "kcal": 0.0}
        micros: dict[tuple[str, str], float] = {}
        for comp in components:
            ingredient = self.get_ingredient(comp["ingredient_id"])
            if ingredient is None:
                continue
            ratio = comp["quantity_g"] / ingredient["basis_amount_g"] if ingredient["basis_amount_g"] else 0
            for field in totals:
                totals[field] += ingredient[field] * ratio
            for m in self.micros_for_ingredient(comp["ingredient_id"]):
                key = (m["nutrient"], m["unit"])
                micros[key] = micros.get(key, 0.0) + m["amount"] * ratio
        return {**totals, "micros": [{"nutrient": n, "unit": u, "amount": a} for (n, u), a in micros.items()]}

    def add_meal_from_ingredients(self, name: str, components: list[dict], notes: str = "") -> int:
        """components: [{ingredient_id, quantity_g}, ...] — every id must
        already exist (create any brand-new ingredients first via
        add_ingredient(), then call this). Computes totals deterministically
        and stores the composition (by ingredient name, not id — markdown is
        the portable source of truth) alongside the usual meals/meal_micros."""
        totals = self.compute_meal_totals(components)
        meal_id = self.add_meal(
            name,
            totals["protein_g"], totals["carbs_g"], totals["fat_g"], totals["kcal"],
            totals["fiber_g"], notes, totals["micros"],
            components=[
                {
                    "ingredient_name": self.get_ingredient(c["ingredient_id"])["name"],
                    "quantity_g": c["quantity_g"],
                }
                for c in components
            ],
        )
        self.conn.execute("DELETE FROM meal_ingredients WHERE meal_id=?", (meal_id,))
        for c in components:
            self.conn.execute(
                "INSERT INTO meal_ingredients (meal_id, ingredient_id, quantity_g) VALUES (?, ?, ?)",
                (meal_id, c["ingredient_id"], c["quantity_g"]),
            )
        self.conn.commit()
        return meal_id

    def meal_components(self, meal_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT mi.ingredient_id, i.name AS ingredient_name, mi.quantity_g
               FROM meal_ingredients mi JOIN ingredients i ON i.id = mi.ingredient_id
               WHERE mi.meal_id = ?""",
            (meal_id,),
        ).fetchall()

    # --- meal micronutrients ---

    def add_meal_micro(self, meal_id: int, nutrient: str, amount: float, unit: str) -> None:
        # SQLite-only, low-level — used by rebuild/internal paths. New meal
        # creation goes through add_meal(..., micros=[...]) so markdown and
        # SQLite are written together, not in two separate steps.
        self.conn.execute(
            "INSERT INTO meal_micros (meal_id, nutrient, amount, unit) VALUES (?, ?, ?, ?)",
            (meal_id, nutrient, amount, unit),
        )
        self.conn.commit()

    def micros_for_meal(self, meal_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT nutrient, amount, unit FROM meal_micros WHERE meal_id = ? ORDER BY nutrient", (meal_id,)
        ).fetchall()

    def micros_between(self, start: date, end: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT mm.nutrient, mm.unit, SUM(mm.amount * f.servings) AS total_amount
               FROM food_log f
               JOIN meal_micros mm ON mm.meal_id = f.meal_id
               WHERE f.date >= ? AND f.date <= ?
               GROUP BY mm.nutrient, mm.unit""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    # --- food log ---

    def log_food(
        self,
        entry_date: date,
        meal_type: str,
        meal_id: int | None = None,
        freeform_kcal: float | None = None,
        servings: float = 1,
        notes: str = "",
    ) -> int:
        if self.log_store:
            meal = self.get_meal(meal_id) if meal_id else None
            # Snapshot the resolved macros at logging time — the markdown record
            # of "what I actually ate" shouldn't silently shift if the preset's
            # numbers get edited later.
            self.log_store.write(
                "food",
                entry_date,
                {
                    "meal_type": meal_type,
                    "meal_id": meal_id,
                    "meal_name": meal["name"] if meal else None,
                    "servings": servings,
                    "kcal": (meal["kcal"] if meal else (freeform_kcal or 0)) * servings,
                    "protein_g": (meal["protein_g"] if meal else 0) * servings,
                    "carbs_g": (meal["carbs_g"] if meal else 0) * servings,
                    "fat_g": (meal["fat_g"] if meal else 0) * servings,
                    "fiber_g": (meal["fiber_g"] if meal else 0) * servings,
                },
                notes=notes,
            )
        cur = self.conn.execute(
            """INSERT INTO food_log (date, meal_type, meal_id, freeform_kcal, servings, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (entry_date.isoformat(), meal_type, meal_id, freeform_kcal, servings, notes),
        )
        self.conn.commit()
        return cur.lastrowid

    def food_log_for_date(self, entry_date: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT f.id, f.date, f.meal_type, f.servings, f.notes,
                      m.name AS meal_name,
                      COALESCE(m.kcal, f.freeform_kcal, 0) * f.servings AS kcal,
                      COALESCE(m.protein_g, 0) * f.servings AS protein_g,
                      COALESCE(m.carbs_g, 0) * f.servings AS carbs_g,
                      COALESCE(m.fat_g, 0) * f.servings AS fat_g,
                      COALESCE(m.fiber_g, 0) * f.servings AS fiber_g
               FROM food_log f
               LEFT JOIN meals m ON f.meal_id = m.id
               WHERE f.date = ?
               ORDER BY f.id""",
            (entry_date.isoformat(),),
        ).fetchall()

    def kcal_between(self, start: date, end: date) -> float:
        row = self.conn.execute(
            """SELECT COALESCE(SUM(COALESCE(m.kcal, f.freeform_kcal, 0) * f.servings), 0) AS total_kcal
               FROM food_log f
               LEFT JOIN meals m ON f.meal_id = m.id
               WHERE f.date >= ? AND f.date <= ?""",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        return row["total_kcal"]

    def daily_totals(self, entry_date: date) -> sqlite3.Row:
        return self.conn.execute(
            """SELECT
                 COALESCE(SUM(COALESCE(m.kcal, f.freeform_kcal, 0) * f.servings), 0) AS total_kcal,
                 COALESCE(SUM(COALESCE(m.protein_g, 0) * f.servings), 0) AS total_protein_g,
                 COALESCE(SUM(COALESCE(m.carbs_g, 0) * f.servings), 0) AS total_carbs_g,
                 COALESCE(SUM(COALESCE(m.fat_g, 0) * f.servings), 0) AS total_fat_g,
                 COALESCE(SUM(COALESCE(m.fiber_g, 0) * f.servings), 0) AS total_fiber_g
               FROM food_log f
               LEFT JOIN meals m ON f.meal_id = m.id
               WHERE f.date = ?""",
            (entry_date.isoformat(),),
        ).fetchone()

    # --- substances ---

    def log_substance(self, entry_date: date, substance: str, amount: float, notes: str = "") -> int:
        if self.log_store:
            self.log_store.write("substance", entry_date, {"substance": substance, "amount": amount}, notes=notes)
        cur = self.conn.execute(
            "INSERT INTO substance_log (date, substance, amount, notes) VALUES (?, ?, ?, ?)",
            (entry_date.isoformat(), substance, amount, notes),
        )
        self.conn.commit()
        return cur.lastrowid

    # --- activity / productivity ---

    def log_activity(self, entry_date: date, category: str, description: str, hours: float = 0) -> int:
        if self.log_store:
            self.log_store.write(
                "activity", entry_date, {"category": category, "description": description, "hours": hours}, category=category
            )
        cur = self.conn.execute(
            "INSERT INTO activity_log (date, category, description, hours) VALUES (?, ?, ?, ?)",
            (entry_date.isoformat(), category, description, hours),
        )
        self.conn.commit()
        return cur.lastrowid

    def activities_for_date(self, entry_date: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM activity_log WHERE date = ? ORDER BY id", (entry_date.isoformat(),)
        ).fetchall()

    def activities_between(self, start: date, end: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM activity_log WHERE date >= ? AND date <= ? ORDER BY date, id",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    def food_log_between(self, start: date, end: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM food_log WHERE date >= ? AND date <= ? ORDER BY date, id",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    def exercise_between(self, start: date, end: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM exercise_sets WHERE date >= ? AND date <= ? ORDER BY date, id",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    def substances_between(self, start: date, end: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM substance_log WHERE date >= ? AND date <= ? ORDER BY date, id",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    def hours_for_category_between(self, category: str, start: date, end: date) -> float:
        row = self.conn.execute(
            """SELECT COALESCE(SUM(hours), 0) AS total_hours FROM activity_log
               WHERE category = ? AND date >= ? AND date <= ?""",
            (category, start.isoformat(), end.isoformat()),
        ).fetchone()
        return row["total_hours"]

    def get_habit(self, habit_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone()

    # --- exercise ---

    def log_exercise(self, entry_date: date, exercise_name: str, sets: list[dict], notes: str = "") -> int:
        performance_text = _summarize_sets(sets)
        if self.log_store:
            self.log_store.write(
                "exercise", entry_date, {"exercise_name": exercise_name, "sets": sets, "notes": notes}
            )
        cur = self.conn.execute(
            """INSERT INTO exercise_sets (date, exercise_name, performance_text, sets_json, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (entry_date.isoformat(), exercise_name, performance_text, json.dumps(sets), notes),
        )
        self.conn.commit()
        return cur.lastrowid

    def total_calories_burned(self, entry_date: date) -> float:
        total = 0.0
        for row in self.exercise_for_date(entry_date):
            for s in json.loads(row["sets_json"] or "[]"):
                total += s.get("calories_burned") or 0
        return total

    def exercise_for_date(self, entry_date: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM exercise_sets WHERE date = ? ORDER BY id", (entry_date.isoformat(),)
        ).fetchall()

    # --- body stats ---

    def log_body_stat(self, entry_date: date, metric: str, value: float, unit: str = "") -> int:
        if self.log_store:
            self.log_store.write("body_stat", entry_date, {"metric": metric, "value": value, "unit": unit})
        cur = self.conn.execute(
            "INSERT INTO body_stats (date, metric, value, unit) VALUES (?, ?, ?, ?)",
            (entry_date.isoformat(), metric, value, unit),
        )
        self.conn.commit()
        return cur.lastrowid

    def latest_body_stat(self, metric: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM body_stats WHERE metric = ? ORDER BY date DESC, id DESC LIMIT 1", (metric,)
        ).fetchone()

    def body_stats_for_date(self, entry_date: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM body_stats WHERE date = ? ORDER BY id", (entry_date.isoformat(),)
        ).fetchall()

    def substances_for_date(self, entry_date: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM substance_log WHERE date = ? ORDER BY id", (entry_date.isoformat(),)
        ).fetchall()

    # --- finance ---

    def log_expense(
        self, entry_date: date, amount: float, merchant: str = "", category: str = "", notes: str = "", kind: str = "regular"
    ) -> int:
        if self.log_store:
            self.log_store.write(
                "finance",
                entry_date,
                {"amount": amount, "merchant": merchant, "category": category, "kind": kind},
                notes=notes,
            )
        cur = self.conn.execute(
            "INSERT INTO expense_log (date, amount, merchant, category, notes, kind) VALUES (?, ?, ?, ?, ?, ?)",
            (entry_date.isoformat(), amount, merchant, category, notes, kind),
        )
        self.conn.commit()
        return cur.lastrowid

    def expenses_for_date(self, entry_date: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM expense_log WHERE date = ? ORDER BY id", (entry_date.isoformat(),)
        ).fetchall()

    def expenses_between(self, start: date, end: date) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM expense_log WHERE date >= ? AND date <= ? ORDER BY date, id",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    def total_spend_between(self, start: date, end: date) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM expense_log WHERE date >= ? AND date <= ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        return row["total"]

    # --- habits / quotas ---

    def add_habit(
        self,
        name: str,
        target_amount: float,
        target_period: str,
        match_category: str | None,
        unit: str = "",
        metric: str = "activity_hours",
        direction: str = "at_least",
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO habits (name, target_amount, target_period, match_category, unit, metric, direction)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, target_amount, target_period, match_category, unit, metric, direction),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_habits(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM habits ORDER BY name").fetchall()
