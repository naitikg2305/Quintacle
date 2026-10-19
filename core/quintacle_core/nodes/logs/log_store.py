from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import frontmatter

from ...markdown_paths import resolve_nested, safe_metadata, slugify


def summarize_sets(sets: list[dict]) -> str:
    """A readable one-line fallback (e.g. "8@135lb, 8@135lb, 8@135lb" or
    "30min 3.1mi 320kcal") — kept for anything still reading performance_text,
    but sets_json / markdown frontmatter is the real structured record."""
    parts = []
    for s in sets:
        if s.get("duration_min") is not None or s.get("distance") is not None:
            bits = []
            if s.get("duration_min") is not None:
                bits.append(f"{s['duration_min']}min")
            if s.get("distance") is not None:
                bits.append(f"{s['distance']}{s.get('distance_unit') or 'mi'}")
            if s.get("calories_burned") is not None:
                bits.append(f"{s['calories_burned']}kcal")
            parts.append(" ".join(bits))
        elif s.get("weight") is not None:
            parts.append(f"{s.get('reps')}@{s['weight']}{s.get('weight_unit') or 'lb'}")
        else:
            parts.append(str(s.get("reps")))
    return ", ".join(parts)

# Where each log type/category lives inside the shared KB folder tree —
# nested right alongside the reference notes for that same domain, so
# copying e.g. "Personal Development/Physical/Fitness" out on its own gives
# you both the cues AND the actual dated numbers.
LOG_HOMES = {
    "exercise": "Personal Development/Physical/Fitness",
    "food": "Personal Development/Physical/Nutrition",
    "body_stat": "Personal Development/Physical/Fitness",
    "substance": "Daily Log/Substances",
    "finance": "Organisation/Finance",
    # Income shares the Finance home — all_entries() filters by the `type`
    # frontmatter field, so expense and income files coexist in one logs/ dir
    # the same way exercise and body_stat share Fitness/logs/.
    "income": "Organisation/Finance",
    "activity:productivity": "Daily Log/Productivity",
    "activity:social": "Daily Log/Social",
    "activity:leisure": "Daily Log/Leisure",
    "activity:yourself": "Daily Log/Yourself",
    "activity:emotional": "Daily Log/Emotional",
}


def home_for(entry_type: str, category: str | None = None) -> str:
    key = f"{entry_type}:{category}" if entry_type == "activity" else entry_type
    home = LOG_HOMES.get(key)
    if home is None:
        raise ValueError(f"no KB home configured for log type {key!r}")
    return home


class LogFileStore:
    """Markdown-frontmatter is the real record for every dense daily log
    (activity/food/exercise/substance/body-stat) — SQLite is a fast,
    disposable index rebuilt from these files, never the other way around.
    One file per log entry, mirroring how schedule/todos already works."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _logs_dir(self, entry_type: str, category: str | None) -> Path:
        path = resolve_nested(self.kb_root, home_for(entry_type, category)) / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(
        self,
        entry_type: str,
        entry_date: date,
        fields: dict,
        category: str | None = None,
        notes: str = "",
    ) -> str:
        logs_dir = self._logs_dir(entry_type, category)
        seq = len(list(logs_dir.glob(f"{entry_date.isoformat()}-*.md"))) + 1
        filename = f"{entry_date.isoformat()}-{seq:03d}.md"

        post = frontmatter.Post(notes)
        post["type"] = entry_type
        post["date"] = entry_date.isoformat()
        for key, value in fields.items():
            post[key] = value
        (logs_dir / filename).write_text(frontmatter.dumps(post), encoding="utf-8")
        return filename

    def all_entries(self, entry_type: str, category: str | None = None) -> list[dict]:
        # Multiple entry types can share a home folder (exercise and body_stat
        # both live under .../Fitness/logs/) — filter by the type field itself,
        # not just directory, or they'd cross-contaminate each other's results.
        logs_dir = self._logs_dir(entry_type, category)
        entries = []
        for path in sorted(logs_dir.glob("*.md")):
            post = frontmatter.loads(path.read_text(encoding="utf-8"))
            if post.metadata.get("type") != entry_type:
                continue
            entries.append({**post.metadata, "notes": post.content})
        return entries

    def all_categories_for(self, entry_type: str) -> list[str | None]:
        if entry_type != "activity":
            return [None]
        return [key.split(":", 1)[1] for key in LOG_HOMES if key.startswith("activity:")]


class MealPresetStore:
    """One markdown file per meal preset, nested under Nutrition/presets/ —
    the reusable macro library, alongside but distinct from logs/ (actual
    dated eating instances) in that same folder. This is the single source
    of truth for presets; SQLite's meals/meal_micros tables are a rebuildable
    index, same contract as the daily logs."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _dir(self) -> Path:
        path = resolve_nested(self.kb_root, LOG_HOMES["food"]) / "presets"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, name: str, fields: dict, micros: list[dict]) -> str:
        slug = slugify(name)
        post = frontmatter.Post("")
        post["name"] = name
        for key, value in fields.items():
            post[key] = value
        post["micros"] = micros
        (self._dir() / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
        return slug

    def all(self) -> list[dict]:
        results = []
        for p in sorted(self._dir().glob("*.md")):
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
            results.append(safe_metadata(post, p.stem, {"micros": []}))
        return results

    def delete(self, name: str) -> None:
        path = self._dir() / f"{slugify(name)}.md"
        if path.exists():
            path.unlink()


class IngredientPresetStore:
    """One markdown file per ingredient preset, nested under Nutrition/ingredients/
    — the reusable per-basis-amount macro library that meal presets are built
    from. Same contract as MealPresetStore: this is the source of truth,
    SQLite's ingredients/ingredient_micros tables are a rebuildable index."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _dir(self) -> Path:
        path = resolve_nested(self.kb_root, LOG_HOMES["food"]) / "ingredients"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, name: str, fields: dict, micros: list[dict]) -> str:
        slug = slugify(name)
        post = frontmatter.Post("")
        post["name"] = name
        for key, value in fields.items():
            post[key] = value
        post["micros"] = micros
        (self._dir() / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
        return slug

    def all(self) -> list[dict]:
        results = []
        for p in sorted(self._dir().glob("*.md")):
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
            results.append(safe_metadata(post, p.stem, {"micros": []}))
        return results

    def delete(self, name: str) -> None:
        path = self._dir() / f"{slugify(name)}.md"
        if path.exists():
            path.unlink()


class RoutineStore:
    """One markdown file per workout routine — just a name + an ordered list
    of exercise names, nested under Fitness/routines/. Deliberately
    markdown-only, no SQLite mirror: nothing else holds a foreign key into a
    routine (it's a template you log AGAINST via exercise_sets, not a logged
    fact itself), so there's no rebuild-stability concern to solve for."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _dir(self) -> Path:
        path = resolve_nested(self.kb_root, LOG_HOMES["exercise"]) / "routines"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, name: str, exercises: list[str]) -> str:
        slug = slugify(name)
        post = frontmatter.Post("")
        post["name"] = name
        post["exercises"] = exercises
        (self._dir() / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
        return slug

    def all(self) -> list[dict]:
        results = []
        for p in sorted(self._dir().glob("*.md")):
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
            results.append(safe_metadata(post, p.stem, {"exercises": []}))
        return results

    def delete(self, name: str) -> None:
        path = self._dir() / f"{slugify(name)}.md"
        if path.exists():
            path.unlink()


def rebuild_sqlite_index(
    store: LogFileStore,
    conn,
    preset_store: MealPresetStore | None = None,
    ingredient_store: IngredientPresetStore | None = None,
) -> dict[str, int]:
    """Wipes and repopulates the SQLite log tables by scanning the markdown
    files — the disposable-cache half of the markdown-is-source-of-truth
    contract. Safe to run any time; SQLite is never the thing that's trusted."""
    counts: dict[str, int] = {}

    if ingredient_store is not None:
        # Same upsert-by-name contract as meals — meal_ingredients references
        # ingredients by integer id, so ids must survive a rebuild.
        existing_ing_ids = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM ingredients")}
        seen_ing = set()
        n = 0
        for ing in ingredient_store.all():
            name = ing["name"]
            seen_ing.add(name)
            values = (
                ing.get("basis_amount_g", 100), ing.get("protein_g", 0), ing.get("carbs_g", 0),
                ing.get("fat_g", 0), ing.get("fiber_g", 0), ing.get("kcal", 0), ing.get("notes", ""),
            )
            if name in existing_ing_ids:
                ingredient_id = existing_ing_ids[name]
                conn.execute(
                    "UPDATE ingredients SET basis_amount_g=?, protein_g=?, carbs_g=?, fat_g=?, fiber_g=?, kcal=?, notes=? WHERE id=?",
                    values + (ingredient_id,),
                )
                conn.execute("DELETE FROM ingredient_micros WHERE ingredient_id=?", (ingredient_id,))
            else:
                cur = conn.execute(
                    "INSERT INTO ingredients (name, basis_amount_g, protein_g, carbs_g, fat_g, fiber_g, kcal, notes) VALUES (?,?,?,?,?,?,?,?)",
                    (name,) + values,
                )
                ingredient_id = cur.lastrowid
            for m in ing.get("micros") or []:
                conn.execute(
                    "INSERT INTO ingredient_micros (ingredient_id, nutrient, amount, unit) VALUES (?, ?, ?, ?)",
                    (ingredient_id, m["nutrient"], m["amount"], m["unit"]),
                )
            n += 1
        for name, ingredient_id in existing_ing_ids.items():
            if name not in seen_ing:
                conn.execute("DELETE FROM ingredient_micros WHERE ingredient_id=?", (ingredient_id,))
                conn.execute("DELETE FROM meal_ingredients WHERE ingredient_id=?", (ingredient_id,))
                conn.execute("DELETE FROM ingredients WHERE id=?", (ingredient_id,))
        counts["ingredients"] = n

    if preset_store is not None:
        # Upsert by name (unique), not DELETE+INSERT — food_log.meal_id (both
        # SQLite and markdown food-log snapshots) references meals by integer
        # id. Regenerating ids on every rebuild would silently detach every
        # existing food_log entry from its preset.
        existing_ids = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM meals")}
        seen = set()
        n = 0
        for preset in preset_store.all():
            name = preset["name"]
            seen.add(name)
            values = (
                preset.get("protein_g", 0), preset.get("carbs_g", 0), preset.get("fat_g", 0),
                preset.get("fiber_g", 0), preset.get("kcal", 0), preset.get("notes", ""),
            )
            if name in existing_ids:
                meal_id = existing_ids[name]
                conn.execute(
                    "UPDATE meals SET protein_g=?, carbs_g=?, fat_g=?, fiber_g=?, kcal=?, notes=? WHERE id=?",
                    values + (meal_id,),
                )
                conn.execute("DELETE FROM meal_micros WHERE meal_id=?", (meal_id,))
            else:
                cur = conn.execute(
                    "INSERT INTO meals (name, protein_g, carbs_g, fat_g, fiber_g, kcal, notes) VALUES (?,?,?,?,?,?,?)",
                    (name,) + values,
                )
                meal_id = cur.lastrowid
            for m in preset.get("micros") or []:
                conn.execute(
                    "INSERT INTO meal_micros (meal_id, nutrient, amount, unit) VALUES (?, ?, ?, ?)",
                    (meal_id, m["nutrient"], m["amount"], m["unit"]),
                )
            n += 1
        for name, meal_id in existing_ids.items():
            if name not in seen:
                conn.execute("DELETE FROM meal_micros WHERE meal_id=?", (meal_id,))
                conn.execute("DELETE FROM meal_ingredients WHERE meal_id=?", (meal_id,))
                conn.execute("DELETE FROM meals WHERE id=?", (meal_id,))
        counts["meals"] = n

        if ingredient_store is not None:
            # A meal preset's `components` (written by name, not id — markdown
            # is portable, SQLite ids aren't) get resolved against the
            # ingredients table just rebuilt above.
            ingredient_ids_by_name = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM ingredients")}
            meal_ids_by_name = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM meals")}
            n = 0
            for preset in preset_store.all():
                meal_id = meal_ids_by_name.get(preset["name"])
                if meal_id is None:
                    continue
                conn.execute("DELETE FROM meal_ingredients WHERE meal_id=?", (meal_id,))
                for comp in preset.get("components") or []:
                    ingredient_id = ingredient_ids_by_name.get(comp.get("ingredient_name"))
                    if ingredient_id is None:
                        continue  # ingredient renamed/deleted since this meal was composed
                    conn.execute(
                        "INSERT INTO meal_ingredients (meal_id, ingredient_id, quantity_g) VALUES (?, ?, ?)",
                        (meal_id, ingredient_id, comp.get("quantity_g", 0)),
                    )
                    n += 1
            counts["meal_ingredients"] = n

    conn.execute("DELETE FROM activity_log")
    n = 0
    for category in store.all_categories_for("activity"):
        for e in store.all_entries("activity", category):
            conn.execute(
                "INSERT INTO activity_log (date, category, description, hours) VALUES (?, ?, ?, ?)",
                (e["date"], e.get("category", category), e.get("description", ""), e.get("hours", 0)),
            )
            n += 1
    counts["activity_log"] = n

    conn.execute("DELETE FROM exercise_sets")
    n = 0
    for e in store.all_entries("exercise"):
        # Old entries (pre-structured-sets) only have performance_text; new
        # ones have a real sets list — handle both without losing history.
        sets = e.get("sets") or []
        performance_text = e.get("performance_text") or summarize_sets(sets)
        conn.execute(
            """INSERT INTO exercise_sets (date, exercise_name, performance_text, sets_json, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (e["date"], e.get("exercise_name", ""), performance_text, json.dumps(sets), e.get("notes", "")),
        )
        n += 1
    counts["exercise_sets"] = n

    conn.execute("DELETE FROM substance_log")
    n = 0
    for e in store.all_entries("substance"):
        conn.execute(
            "INSERT INTO substance_log (date, substance, amount, notes) VALUES (?, ?, ?, ?)",
            (e["date"], e.get("substance", ""), e.get("amount", 0), e.get("notes", "")),
        )
        n += 1
    counts["substance_log"] = n

    conn.execute("DELETE FROM body_stats")
    n = 0
    for e in store.all_entries("body_stat"):
        conn.execute(
            "INSERT INTO body_stats (date, metric, value, unit) VALUES (?, ?, ?, ?)",
            (e["date"], e.get("metric", ""), e.get("value", 0), e.get("unit", "")),
        )
        n += 1
    counts["body_stats"] = n

    conn.execute("DELETE FROM expense_log")
    n = 0
    for e in store.all_entries("finance"):
        conn.execute(
            "INSERT INTO expense_log (date, amount, merchant, category, notes, kind) VALUES (?, ?, ?, ?, ?, ?)",
            (
                e["date"],
                e.get("amount", 0),
                e.get("merchant", ""),
                e.get("category", ""),
                e.get("notes", ""),
                e.get("kind", "regular"),
            ),
        )
        n += 1
    counts["expense_log"] = n

    conn.execute("DELETE FROM income_log")
    n = 0
    for e in store.all_entries("income"):
        conn.execute(
            "INSERT INTO income_log (date, amount, source, kind, notes) VALUES (?, ?, ?, ?, ?)",
            (e["date"], e.get("amount", 0), e.get("source", ""), e.get("kind", "salary"), e.get("notes", "")),
        )
        n += 1
    counts["income_log"] = n

    conn.execute("DELETE FROM food_log")
    n = 0
    for e in store.all_entries("food"):
        meal_id = e.get("meal_id")
        conn.execute(
            "INSERT INTO food_log (date, meal_type, meal_id, freeform_kcal, servings, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (
                e["date"],
                e.get("meal_type", ""),
                meal_id,
                None if meal_id else e.get("kcal", 0),
                e.get("servings", 1),
                e.get("notes", ""),
            ),
        )
        n += 1
    counts["food_log"] = n

    conn.commit()
    return counts
