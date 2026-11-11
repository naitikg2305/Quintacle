"""Offline reverse geocoding — GPS coords -> {city, state, country} with no
network and no model (2026-11-11, local-first).

Before this, photo_organizer.geocode() was the only geocoder and it was a
CLOUD Claude call, so every GPS photo dropped in local mode either reached
the cloud or lost its place names. Now the local answer comes from the
GeoNames gazetteer: the nearest populated place to the coordinates.

Stdlib only (csv-ish parsing, urllib, zipfile) — no numpy/scipy, so it is
phone/Termux-safe and nothing joins core/requirements.txt. The DATA is not in
the repo: download it once with

    core/.venv/bin/python -m quintacle_core.geo_offline            # cities1000 (~11 MB zip)
    core/.venv/bin/python -m quintacle_core.geo_offline --size 5000   # phone: ~6 MB zip

which writes `<data_dir>/geonames/` (QUINTACLE_GEONAMES_DIR overrides):
  cities.tsv     compact name/lat/lon/country/admin1/population rows built from citiesN.zip
  admin1.tsv     "US.NY" -> "New York" (state/region names)
  countries.tsv  "US" -> "United States" + continent code
Without that folder, reverse() returns None and callers fall back to
coordinates only (or the cloud, when the user chose it).

Data: GeoNames (https://www.geonames.org/), CC BY 4.0. Sources:
https://download.geonames.org/export/dump/{citiesN.zip, admin1CodesASCII.txt, countryInfo.txt}

Lookup: a 1°x1° grid of places, searched ring by ring around the photo;
haversine distance; nothing farther than MAX_KM counts (a photo mid-ocean
gets no city rather than one 400 km away). Pure nearest-centroid names
neighbourhoods and suburbs (the Empire State Building's nearest centroid is
Weehawken, NJ; the Eiffel Tower's is "Paris 16 Passy"), so a place whose
rough radius (CITY_RADIUS_K * sqrt(population) km — ~8 km for Paris, ~16 km
for New York) contains the photo wins, the most populous such place first;
the nearest centroid is only the fallback. Loaded lazily, once per process
(~150k rows for cities1000)."""
from __future__ import annotations

import argparse
import io
import logging
import math
import os
import shutil
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

GEONAMES_DIR_ENV = "QUINTACLE_GEONAMES_DIR"
CITIES_FILE = "cities.tsv"
ADMIN1_FILE = "admin1.tsv"
COUNTRIES_FILE = "countries.tsv"
MAX_KM = 100.0
CITY_RADIUS_K = 0.0055  # km per sqrt(person): city area roughly ∝ population
DUMP_BASE = "https://download.geonames.org/export/dump/"
SIZES = ("1000", "5000", "15000")
# Sections of a city ("Paris 07 Palais-Bourbon"), historical/abandoned
# places — never what a photo's place line should say.
_SKIP_FEATURES = {"PPLX", "PPLH", "PPLQ", "PPLW", "PPLCH"}
_CONTINENT_NAMES = {
    "AF": "Africa", "AS": "Asia", "EU": "Europe", "NA": "North America",
    "SA": "South America", "OC": "Oceania", "AN": "Antarctica",
}


def geonames_dir() -> Path:
    """Resolved per call so a sandboxed QUINTACLE_DATA_DIR (tests) is honoured."""
    override = os.environ.get(GEONAMES_DIR_ENV)
    if override:
        return Path(override)
    return Path(os.environ.get("QUINTACLE_DATA_DIR", Path.home() / ".quintacle")) / "geonames"


def available() -> bool:
    return (geonames_dir() / CITIES_FILE).is_file()


# ------------------------------------------------------------------ index


class _Index:
    def __init__(self, folder: Path):
        self.grid: dict[tuple[int, int], list[tuple[float, float, str, str, str, int]]] = {}
        with open(folder / CITIES_FILE, encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 5:
                    continue
                try:
                    lat, lon = float(parts[1]), float(parts[2])
                    pop = int(parts[5]) if len(parts) > 5 and parts[5] else 0
                except ValueError:
                    continue
                self.grid.setdefault((math.floor(lat), math.floor(lon)), []).append((lat, lon, parts[0], parts[3], parts[4], pop))
        self.admin1 = _read_pairs(folder / ADMIN1_FILE)
        self.countries: dict[str, tuple[str, str]] = {}
        path = folder / COUNTRIES_FILE
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    self.countries[parts[0]] = (parts[1], parts[2] if len(parts) > 2 else "")

    def nearest(self, lat: float, lon: float) -> tuple[float, tuple] | None:
        """(distance_km, row) of the place the photo is IN (largest place
        whose radius covers it), else of the nearest centroid."""
        best: tuple[float, tuple] | None = None
        inside: tuple[float, tuple] | None = None
        cy, cx = math.floor(lat), math.floor(lon)
        # 1° of latitude ≈ 111 km, so 2 rings always cover MAX_KM north/south;
        # longitude cells shrink toward the poles — widen the ring there.
        lon_rings = min(180, 2 + int(2 / max(math.cos(math.radians(lat)), 0.02)))
        for dy in range(-2, 3):
            for dx in range(-lon_rings, lon_rings + 1):
                x = (cx + dx + 180) % 360 - 180
                for row in self.grid.get((cy + dy, x), ()):
                    d = _haversine_km(lat, lon, row[0], row[1])
                    if best is None or d < best[0]:
                        best = (d, row)
                    if d <= max(1.0, CITY_RADIUS_K * math.sqrt(row[5])) and (inside is None or row[5] > inside[1][5]):
                        inside = (d, row)
        return inside or best


def _read_pairs(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out[parts[0]] = parts[1]
    return out


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


_lock = threading.Lock()
_cache: dict[tuple[str, float], _Index] = {}


def _index() -> _Index | None:
    folder = geonames_dir()
    path = folder / CITIES_FILE
    try:
        key = (str(folder), path.stat().st_mtime)
    except OSError:
        return None
    with _lock:
        if key not in _cache:
            _cache.clear()
            _cache[key] = _Index(folder)
        return _cache[key]


def reverse(lat: float, lon: float) -> dict | None:
    """{city, state, country, continent} of the nearest populated place
    within MAX_KM, or None (no data installed / nothing near / bad coords).
    Never raises, never touches the network."""
    try:
        lat, lon = float(lat), float(lon)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or math.isnan(lat) or math.isnan(lon):
            return None
        index = _index()
        if index is None:
            return None
        hit = index.nearest(lat, lon)
        if hit is None or hit[0] > MAX_KM:
            return None
        _, (_, _, name, cc, admin1, _) = hit
        country, continent_code = index.countries.get(cc, (cc, ""))
        return {
            "city": name,
            "state": index.admin1.get(f"{cc}.{admin1}", ""),
            "country": country,
            "continent": _CONTINENT_NAMES.get(continent_code),
        }
    except Exception as exc:  # a corrupt data file must never fail a drop
        logger.warning("offline geocode failed for %s,%s: %s", lat, lon, exc)
        return None


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# --------------------------------------------------------------- download


def build_cities_tsv(cities_txt: io.TextIOBase, out_path: Path) -> int:
    """GeoNames citiesN.txt (19 tab columns) -> compact name/lat/lon/cc/admin1/population."""
    n = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for line in cities_txt:
            c = line.rstrip("\n").split("\t")
            if len(c) < 11 or c[7] in _SKIP_FEATURES:
                continue
            out.write(f"{c[1]}\t{c[4]}\t{c[5]}\t{c[8]}\t{c[10]}\t{c[14] if len(c) > 14 else ''}\n")
            n += 1
    return n


def build_admin1_tsv(admin1_txt: str, out_path: Path) -> None:
    rows = [l.split("\t") for l in admin1_txt.splitlines() if l and not l.startswith("#")]
    out_path.write_text("".join(f"{r[0]}\t{r[1]}\n" for r in rows if len(r) >= 2), encoding="utf-8")


def build_countries_tsv(country_info_txt: str, out_path: Path) -> None:
    rows = [l.split("\t") for l in country_info_txt.splitlines() if l and not l.startswith("#")]
    out_path.write_text("".join(f"{r[0]}\t{r[4]}\t{r[8]}\n" for r in rows if len(r) >= 9), encoding="utf-8")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Quintacle offline geocoder installer"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def install(size: str = "1000", dest: Path | None = None) -> Path:
    if size not in SIZES:
        raise ValueError(f"size must be one of {', '.join(SIZES)}")
    dest = dest or geonames_dir()
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(_get(f"{DUMP_BASE}cities{size}.zip"))) as zf:
        with zf.open(f"cities{size}.txt") as raw:
            n = build_cities_tsv(io.TextIOWrapper(raw, encoding="utf-8"), tmp / CITIES_FILE)
    build_admin1_tsv(_get(DUMP_BASE + "admin1CodesASCII.txt").decode("utf-8"), tmp / ADMIN1_FILE)
    build_countries_tsv(_get(DUMP_BASE + "countryInfo.txt").decode("utf-8"), tmp / COUNTRIES_FILE)
    (tmp / "SOURCE.txt").write_text(
        f"GeoNames cities{size} + admin1CodesASCII + countryInfo ({n} places), CC BY 4.0, https://www.geonames.org/\n",
        encoding="utf-8",
    )
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    clear_cache()
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Download the GeoNames gazetteer for offline photo geocoding.")
    ap.add_argument("--size", choices=SIZES, default="1000", help="cities with population >= N (1000 = most detail)")
    ap.add_argument("--dest", type=Path, default=None, help=f"default: $QUINTACLE_DATA_DIR/geonames (or ${GEONAMES_DIR_ENV})")
    args = ap.parse_args(argv)
    dest = install(args.size, args.dest)
    print(f"offline geocoder data installed in {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
