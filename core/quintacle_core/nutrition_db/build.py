"""Builds the compact offline USDA nutrition db (2026-11-05).

Input: the official FoodData Central bulk CSV releases (Foundation Foods,
SR Legacy) as .zip files or extracted folders, plus optionally a CSV export
of the USDA Flavonoid Database Release 3.3 (FLAV_DAT, see fetch.py for why
that one is optional). Output: ONE SQLite file

    foods(fdc_id, description, category, source, ndb)
    nutrients(id, name, unit, grp)
    food_nutrient(fdc_id, nutrient_id, amount, approx)   -- per 100 g, Quintacle units
    foods_fts (FTS5 over description + category)
    meta(key, value)

Values are already mapped to Quintacle's nutrient names/units at build time
(nutrients.resolve), so a read is a plain lookup. Stdlib only — runs on the
phone (Termux) the same as the desktop.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import zipfile
from pathlib import Path

from .. import clock
from .nutrients import FLAV_NBR_TO_ID, NUTRIENTS, USED_USDA_IDS, resolve

# FDC food.csv data_type values we keep, → our short source label.
_DATA_TYPES = {"foundation_food": "foundation", "sr_legacy_food": "sr_legacy"}

csv.field_size_limit(10_000_000)


class _Release:
    """One FDC CSV release, zipped or extracted — read by member basename."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._zip = zipfile.ZipFile(self.path) if self.path.is_file() else None

    def _find(self, name: str) -> str | Path | None:
        if self._zip is not None:
            for member in self._zip.namelist():
                if member.rsplit("/", 1)[-1] == name:
                    return member
            return None
        hits = list(self.path.rglob(name))
        return hits[0] if hits else None

    def has(self, name: str) -> bool:
        return self._find(name) is not None

    def rows(self, name: str):
        target = self._find(name)
        if target is None:
            return iter(())
        if self._zip is not None:
            stream = io.TextIOWrapper(self._zip.open(target), encoding="utf-8-sig", newline="")
        else:
            stream = open(target, encoding="utf-8-sig", newline="")
        return csv.DictReader(stream)


def release_is_complete(path: Path) -> bool:
    """A usable release carries food.csv + food_nutrient.csv + nutrient.csv.
    (The 2026-10-29 Foundation zip on the FDC page shipped without the first
    two — fetch.py falls back to the previous release when that happens.)"""
    rel = _Release(path)
    return all(rel.has(n) for n in ("food.csv", "food_nutrient.csv", "nutrient.csv"))


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_db(
    releases: list[Path],
    out_path: Path,
    flavonoid_csv: Path | None = None,
    source_urls: list[str] | None = None,
) -> dict:
    """Builds (atomically — temp file then rename) and returns a summary."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".building")
    if tmp.exists():
        tmp.unlink()

    foods: dict[int, dict] = {}
    raw: dict[int, dict[int, float]] = {}
    ndb_to_fdc: dict[str, int] = {}
    for path in releases:
        rel = _Release(Path(path))
        categories = {r["id"]: r["description"] for r in rel.rows("food_category.csv")}
        kept: set[int] = set()
        for r in rel.rows("food.csv"):
            source = _DATA_TYPES.get(r.get("data_type", ""))
            if source is None:
                continue
            fdc_id = int(r["fdc_id"])
            kept.add(fdc_id)
            foods[fdc_id] = {
                "description": r["description"].strip(),
                "category": categories.get(r.get("food_category_id", ""), ""),
                "source": source,
                "ndb": "",
            }
        for list_name in ("foundation_food.csv", "sr_legacy_food.csv"):
            for r in rel.rows(list_name):
                fdc_id = int(r["fdc_id"])
                if fdc_id in kept and r.get("NDB_number"):
                    foods[fdc_id]["ndb"] = r["NDB_number"].strip()
                    ndb_to_fdc[r["NDB_number"].strip().lstrip("0")] = fdc_id
        for r in rel.rows("food_nutrient.csv"):
            fdc_id = int(r["fdc_id"])
            if fdc_id not in kept:
                continue
            nid = int(r["nutrient_id"])
            if nid not in USED_USDA_IDS:
                continue
            amount = _num(r.get("amount"))
            if amount is None:
                continue
            raw.setdefault(fdc_id, {})[nid] = amount

    flav_rows = 0
    flav_status = "not provided"
    if flavonoid_csv is not None and Path(flavonoid_csv).exists():
        flav_rows = _merge_flavonoids(Path(flavonoid_csv), raw, ndb_to_fdc)
        flav_status = f"imported {flav_rows} values from {Path(flavonoid_csv).name}"

    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(
            """
            CREATE TABLE foods (fdc_id INTEGER PRIMARY KEY, description TEXT NOT NULL,
                                category TEXT NOT NULL DEFAULT '', source TEXT NOT NULL, ndb TEXT NOT NULL DEFAULT '');
            CREATE TABLE nutrients (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, unit TEXT NOT NULL, grp TEXT NOT NULL);
            CREATE TABLE food_nutrient (fdc_id INTEGER NOT NULL, nutrient_id INTEGER NOT NULL,
                                        amount REAL NOT NULL, approx INTEGER NOT NULL DEFAULT 0,
                                        PRIMARY KEY (fdc_id, nutrient_id)) WITHOUT ROWID;
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE VIRTUAL TABLE foods_fts USING fts5(description, category, content='foods', content_rowid='fdc_id');
            """
        )
        nutrient_ids = {}
        for i, n in enumerate(NUTRIENTS, start=1):
            conn.execute("INSERT INTO nutrients (id, name, unit, grp) VALUES (?,?,?,?)", (i, n.name, n.unit, n.group))
            nutrient_ids[n.name] = i
        rows = 0
        for fdc_id, f in foods.items():
            conn.execute(
                "INSERT INTO foods (fdc_id, description, category, source, ndb) VALUES (?,?,?,?,?)",
                (fdc_id, f["description"], f["category"], f["source"], f["ndb"]),
            )
            for name, (amount, approx) in resolve(raw.get(fdc_id, {})).items():
                conn.execute(
                    "INSERT INTO food_nutrient (fdc_id, nutrient_id, amount, approx) VALUES (?,?,?,?)",
                    (fdc_id, nutrient_ids[name], round(amount, 6), int(approx)),
                )
                rows += 1
        conn.execute("INSERT INTO foods_fts (foods_fts) VALUES ('rebuild')")
        summary = {
            "built_at": clock.now().isoformat(timespec="seconds"),
            "foods": len(foods),
            "food_nutrient_rows": rows,
            "sources": sorted({f["source"] for f in foods.values()}),
            "releases": [Path(p).name for p in releases],
            "source_urls": source_urls or [],
            "flavonoids": flav_status,
        }
        conn.execute("INSERT INTO meta (key, value) VALUES ('summary', ?)", (json.dumps(summary),))
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    os.replace(tmp, out_path)
    summary["size_bytes"] = out_path.stat().st_size
    return summary


def _merge_flavonoids(path: Path, raw: dict[int, dict[int, float]], ndb_to_fdc: dict[str, int]) -> int:
    """FLAV_DAT export (columns NDB_No, Nutr_No, Flav_Val — `mdb-export`
    output of Flav_R03-3.accdb) → adds compound/class values (mg/100 g) to
    the matching SR/Foundation food by NDB number. Foods not in the FDC
    releases are skipped (they'd have no other nutrients)."""
    n = 0
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            row = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            ndb = row.get("ndb_no", "").lstrip("0")
            nbr = _num(row.get("nutr_no"))
            value = _num(row.get("flav_val") or row.get("nutr_val"))
            if not ndb or nbr is None or value is None:
                continue
            fdc_id = ndb_to_fdc.get(ndb)
            nid = FLAV_NBR_TO_ID.get(int(nbr))
            if fdc_id is None or nid is None:
                continue
            raw.setdefault(fdc_id, {})[nid] = value
            n += 1
    return n
