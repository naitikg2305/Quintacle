"""Downloads the official USDA releases and builds <data_dir>/nutrition/usda.db
(2026-11-05). Stdlib only (urllib, zipfile, csv, sqlite3) — phone-safe.

Sources (verified 2026-11-05):
- FoodData Central download page: https://fdc.nal.usda.gov/download-datasets/
- Foundation Foods CSV: https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_csv_<date>.zip
  The newest release is discovered from the download page. The 2026-10-29
  zip was published WITHOUT food.csv / food_nutrient.csv, so each release is
  checked and the next-newest complete one is used.
- SR Legacy CSV (final, 2018-04): https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip
- USDA Database for the Flavonoid Content of Selected Foods, Release 3.3:
  https://www.ars.usda.gov/ARSUserFiles/80400535/Data/Flav/Flav_R03-3.accdb
  It is published ONLY as an MS Access file (plus PDF), which the stdlib
  can't read. When `mdb-export` (mdbtools) is on PATH — a desktop extra —
  its FLAV_DAT table is exported and merged; otherwise flavonoids are
  skipped and the status says so. A FLAV_DAT CSV exported elsewhere can be
  passed with --flavonoid-csv.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

from .build import build_db, release_is_complete
from .store import db_path

FDC_PAGE = "https://fdc.nal.usda.gov/download-datasets/"
FDC_BASE = "https://fdc.nal.usda.gov/fdc-datasets/"
SR_LEGACY_URL = FDC_BASE + "FoodData_Central_sr_legacy_food_csv_2018-04.zip"
# Used when the page can't be scraped; newest first. 2026-04-30 verified complete.
FOUNDATION_FALLBACK_DATES = ["2026-04-30", "2025-12-18", "2025-04-24"]
FLAV_ACCDB_URL = "https://www.ars.usda.gov/ARSUserFiles/80400535/Data/Flav/Flav_R03-3.accdb"
APPROX_DOWNLOAD_MB = 10  # Foundation ≈4 MB + SR Legacy ≈6 MB (zipped)

_UA = {"User-Agent": "Mozilla/5.0 (Quintacle nutrition db installer)"}


def _get(url: str, dest: Path, timeout: int = 300) -> Path:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)
    return dest


def foundation_candidates() -> list[str]:
    try:
        req = urllib.request.Request(FDC_PAGE, headers=_UA)
        html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        dates = sorted(set(re.findall(r"FoodData_Central_foundation_food_csv_(\d{4}-\d{2}-\d{2})\.zip", html)), reverse=True)
    except Exception:
        dates = []
    dates = dates or FOUNDATION_FALLBACK_DATES
    return [f"{FDC_BASE}FoodData_Central_foundation_food_csv_{d}.zip" for d in dates]


def _flavonoid_csv(work: Path, log) -> tuple[Path | None, str]:
    exporter = shutil.which("mdb-export")
    if exporter is None:
        return None, "skipped: USDA Flavonoid DB R3.3 is only published as MS Access (.accdb); install mdbtools (mdb-export) to import it"
    try:
        accdb = _get(FLAV_ACCDB_URL, work / "Flav_R03-3.accdb")
        log("exporting flavonoid table")
        out = work / "FLAV_DAT.csv"
        with open(out, "wb") as fh:
            subprocess.run([exporter, str(accdb), "FLAV_DAT"], stdout=fh, check=True, timeout=300)
        return out, "imported"
    except Exception as e:
        return None, f"skipped: flavonoid import failed ({e})"


def install(out_path: Path | None = None, log=print, keep_downloads: bool = False, flavonoid_csv: Path | None = None) -> dict:
    out_path = Path(out_path) if out_path else db_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="usda-", dir=out_path.parent))
    try:
        releases, urls = [], []
        for url in foundation_candidates():
            log(f"downloading {url}")
            path = _get(url, work / url.rsplit("/", 1)[-1])
            if release_is_complete(path):
                releases.append(path)
                urls.append(url)
                break
            log("  release is missing food.csv/food_nutrient.csv — trying the previous one")
            path.unlink()
        log(f"downloading {SR_LEGACY_URL}")
        releases.append(_get(SR_LEGACY_URL, work / "sr_legacy.zip"))
        urls.append(SR_LEGACY_URL)
        flav_note = None
        if flavonoid_csv is None:
            flavonoid_csv, flav_note = _flavonoid_csv(work, log)
            if flavonoid_csv is not None:
                urls.append(FLAV_ACCDB_URL)
        log("building db")
        result = build_db(releases, out_path, flavonoid_csv=flavonoid_csv, source_urls=urls)
        if flav_note and flav_note.startswith("skipped"):
            result["flavonoids"] = flav_note
            _patch_summary(out_path, {"flavonoids": flav_note})
        return result
    finally:
        if not keep_downloads:
            shutil.rmtree(work, ignore_errors=True)


def _patch_summary(path: Path, patch: dict) -> None:
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='summary'").fetchone()
        data = {**(json.loads(row[0]) if row else {}), **patch}
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('summary', ?)", (json.dumps(data),))
        conn.commit()
    finally:
        conn.close()


# --- background job for POST /nutrition/db/install ---

_job = {"state": "idle", "step": "", "error": None, "result": None}
_job_lock = threading.Lock()


def job_status() -> dict:
    with _job_lock:
        return dict(_job)


def start_install_job(runner=install) -> bool:
    """False when a job is already running (the endpoint reports that)."""
    with _job_lock:
        if _job["state"] == "running":
            return False
        _job.update(state="running", step="starting", error=None, result=None)

    def log(msg: str) -> None:
        with _job_lock:
            _job["step"] = msg

    def run() -> None:
        try:
            result = runner(log=log)
            with _job_lock:
                _job.update(state="done", step="done", result=result)
        except Exception as e:
            with _job_lock:
                _job.update(state="error", error=str(e))

    threading.Thread(target=run, daemon=True, name="usda-install").start()
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m quintacle_core.nutrition_db", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download the USDA releases and build the db")
    f.add_argument("--out", type=Path, default=None, help="db path (default <QUINTACLE_DATA_DIR>/nutrition/usda.db)")
    f.add_argument("--keep-downloads", action="store_true")
    f.add_argument("--flavonoid-csv", type=Path, default=None, help="FLAV_DAT export of Flav_R03-3.accdb")
    b = sub.add_parser("build", help="build from already-downloaded release zips/folders")
    b.add_argument("releases", nargs="+", type=Path)
    b.add_argument("--out", type=Path, default=None)
    b.add_argument("--flavonoid-csv", type=Path, default=None)
    m = sub.add_parser("match", help="show ranked candidates for a food description")
    m.add_argument("text")
    args = p.parse_args(argv)
    if args.cmd == "fetch":
        print(json.dumps(install(args.out, keep_downloads=args.keep_downloads, flavonoid_csv=args.flavonoid_csv), indent=2))
    elif args.cmd == "build":
        print(json.dumps(build_db(args.releases, args.out or db_path(), flavonoid_csv=args.flavonoid_csv), indent=2))
    else:
        from .store import match_food

        for c in match_food(args.text):
            print(f"{c['score']:.3f}  {c['fdc_id']}  [{c['source']}] {c['description']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
