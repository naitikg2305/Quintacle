"""Bake a photo's place into its note BODY so retrieval can find it.

A photo's GPS used to live only in frontmatter `location` (and maybe the
Media/Photos/<Year>/<Month>/<Country>/<State>/<City> folder path), but the
retrieval index sees title + body only — so "photos from Vienna / Austria /
Europe" missed every photo whose AI description didn't happen to name the
place. Every photo save path now runs bake_photo_place(), which appends ONE
visible line just before the trailing `[asset](...)` lines:

    📍 Vienna, Austria · Europe · 48.2082, 16.3738 · taken 2027-05-14 15:32 <!-- place -->

and stores structured `place: {city, state, country, continent}` in
frontmatter next to `location`.

Deterministic core, model at the edge: coords + capture time come from EXIF
(drop.py's extractors), the continent from a code table; the ONLY model call
is photo_organizer.geocode (city/state/country), cached by coords rounded to
3 decimals (~100 m) in `<data>/geocode-cache.json` so a batch from one place
costs one call. A private note never reaches the cloud geocoder (its
coordinates are sensitive) — it gets coords + date only, unless the cache
already holds that spot (a cache hit sends nothing anywhere).

The trailing `<!-- place -->` marker makes the line recognisable for an
idempotent re-run (replaced, never duplicated); react-markdown drops the raw
HTML comment so Browse shows just the 📍 line, and
retrieval.deterministic_prose_summary skips it like `[asset](` lines."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import frontmatter

from . import photo_organizer
from .drop import extract_photo_date, extract_photo_datetime, extract_photo_location

logger = logging.getLogger(__name__)

PLACE_MARKER = "<!-- place -->"
PLACE_PREFIX = "📍"
GEOCODE_CACHE_FILE = "geocode-cache.json"

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "tif", "tiff"}

_ASSET_LINE_RE = re.compile(r"^\[asset\]\(([^)]+)\)\s*$")


def is_image_name(name: str) -> bool:
    return name.rsplit(".", 1)[-1].lower() in IMAGE_EXTENSIONS if "." in name else False


def _is_file_meta_line(line: str) -> bool:
    s = line.strip()
    return s.startswith("🗂") and s.endswith("<!-- filemeta -->")


def is_place_line(line: str) -> bool:
    s = line.strip()
    return s.startswith(PLACE_PREFIX) and s.endswith(PLACE_MARKER)


# --------------------------------------------------------------- continents

_CONTINENTS: dict[str, list[str]] = {
    "Africa": [
        "Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi", "Cabo Verde", "Cape Verde",
        "Cameroon", "Central African Republic", "CAR", "Chad", "Comoros", "Congo", "Republic of the Congo",
        "Congo-Brazzaville", "Democratic Republic of the Congo", "DR Congo", "DRC", "Congo-Kinshasa",
        "Djibouti", "Egypt", "Equatorial Guinea", "Eritrea", "Eswatini", "Swaziland", "Ethiopia", "Gabon",
        "Gambia", "The Gambia", "Ghana", "Guinea", "Guinea-Bissau", "Ivory Coast", "Côte d'Ivoire",
        "Cote d'Ivoire", "Kenya", "Lesotho", "Liberia", "Libya", "Madagascar", "Malawi", "Mali", "Mauritania",
        "Mauritius", "Morocco", "Mozambique", "Namibia", "Niger", "Nigeria", "Rwanda", "São Tomé and Príncipe",
        "Sao Tome and Principe", "Senegal", "Seychelles", "Sierra Leone", "Somalia", "South Africa",
        "South Sudan", "Sudan", "Tanzania", "Togo", "Tunisia", "Uganda", "Zambia", "Zimbabwe",
        "Western Sahara", "Réunion", "Reunion", "Mayotte", "Saint Helena",
    ],
    "Asia": [
        "Afghanistan", "Armenia", "Azerbaijan", "Bahrain", "Bangladesh", "Bhutan", "Brunei", "Cambodia",
        "China", "People's Republic of China", "PRC", "Georgia", "Hong Kong", "Macau", "Macao", "India",
        "Indonesia", "Iran", "Iraq", "Israel", "Japan", "Jordan", "Kazakhstan", "Kuwait", "Kyrgyzstan",
        "Laos", "Lebanon", "Malaysia", "Maldives", "Mongolia", "Myanmar", "Burma", "Nepal", "North Korea",
        "Oman", "Pakistan", "Palestine", "State of Palestine", "Philippines", "Qatar", "Saudi Arabia",
        "Singapore", "South Korea", "Korea", "Republic of Korea", "Sri Lanka", "Syria", "Taiwan",
        "Tajikistan", "Thailand", "Timor-Leste", "East Timor", "Turkey", "Türkiye", "Turkiye",
        "Turkmenistan", "United Arab Emirates", "UAE", "Uzbekistan", "Vietnam", "Viet Nam", "Yemen",
    ],
    "Europe": [
        "Albania", "Andorra", "Austria", "Belarus", "Belgium", "Bosnia and Herzegovina", "Bosnia",
        "Bulgaria", "Croatia", "Cyprus", "Czechia", "Czech Republic", "Denmark", "Estonia", "Finland",
        "France", "Germany", "Greece", "Hungary", "Iceland", "Ireland", "Republic of Ireland", "Italy",
        "Kosovo", "Latvia", "Liechtenstein", "Lithuania", "Luxembourg", "Malta", "Moldova", "Monaco",
        "Montenegro", "Netherlands", "Holland", "North Macedonia", "Macedonia", "Norway", "Poland",
        "Portugal", "Romania", "Russia", "Russian Federation", "San Marino", "Serbia", "Slovakia",
        "Slovenia", "Spain", "Sweden", "Switzerland", "Ukraine", "United Kingdom", "UK", "Great Britain",
        "Britain", "England", "Scotland", "Wales", "Northern Ireland", "Vatican City", "Vatican",
        "Holy See", "Faroe Islands", "Gibraltar", "Isle of Man", "Jersey", "Guernsey", "Greenland",
    ],
    "North America": [
        "United States", "United States of America", "USA", "US", "U.S.", "U.S.A.", "America", "Canada",
        "Mexico", "Antigua and Barbuda", "Bahamas", "The Bahamas", "Barbados", "Belize", "Costa Rica",
        "Cuba", "Dominica", "Dominican Republic", "El Salvador", "Grenada", "Guatemala", "Haiti",
        "Honduras", "Jamaica", "Nicaragua", "Panama", "Saint Kitts and Nevis", "St Kitts and Nevis",
        "Saint Lucia", "St Lucia", "Saint Vincent and the Grenadines", "St Vincent and the Grenadines",
        "Trinidad and Tobago", "Puerto Rico", "Bermuda", "Cayman Islands", "Aruba", "Curaçao", "Curacao",
        "US Virgin Islands", "British Virgin Islands", "Turks and Caicos Islands", "Guadeloupe",
        "Martinique", "Anguilla", "Sint Maarten", "Saint Martin",
    ],
    "South America": [
        "Argentina", "Bolivia", "Brazil", "Chile", "Colombia", "Ecuador", "Guyana", "Paraguay", "Peru",
        "Suriname", "Uruguay", "Venezuela", "French Guiana", "Falkland Islands",
    ],
    "Oceania": [
        "Australia", "Fiji", "Kiribati", "Marshall Islands", "Micronesia", "Federated States of Micronesia",
        "Nauru", "New Zealand", "Aotearoa", "Palau", "Papua New Guinea", "Samoa", "Solomon Islands", "Tonga",
        "Tuvalu", "Vanuatu", "French Polynesia", "New Caledonia", "Guam", "American Samoa",
        "Northern Mariana Islands", "Cook Islands",
    ],
    "Antarctica": ["Antarctica"],
}


def _norm_country(name: str) -> str:
    s = (name or "").strip().lower().replace("&", "and")
    s = re.sub(r"[.'’]", "", s)
    s = re.sub(r"[^a-z0-9à-ÿ]+", " ", s).strip()
    if s.startswith("the "):
        s = s[4:]
    return s


_COUNTRY_TO_CONTINENT = {_norm_country(c): cont for cont, names in _CONTINENTS.items() for c in names}


def continent_for(country: str | None) -> str | None:
    """Deterministic country → continent (common name variants included).
    None for anything unknown — never guessed."""
    if not country:
        return None
    return _COUNTRY_TO_CONTINENT.get(_norm_country(country))


# --------------------------------------------------------------- geocode cache


def _cache_key(lat: float, lon: float) -> str:
    return f"{lat:.3f},{lon:.3f}"


def _load_cache(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def cached_geocode(lat: float, lon: float, cache_path: Path | None, *, allow_cloud: bool = True) -> dict | None:
    """{city, state, country} for these coords — cache first, then (only
    when allow_cloud) the photo_organizer.geocode model call, whose result is
    cached. None on a miss with cloud disallowed, or on ANY geocode error
    (logged, never raised — a save must not fail over geocoding)."""
    key = _cache_key(lat, lon)
    cache = _load_cache(cache_path)
    if key in cache:
        return cache[key]
    if not allow_cloud:
        return None
    try:
        geo = photo_organizer.geocode(lat, lon)
        result = {"city": geo.city.strip(), "state": geo.state.strip(), "country": geo.country.strip()}
    except Exception as exc:
        logger.warning("photo geocode failed for %s: %s", key, exc)
        return None
    if cache_path is not None:
        try:
            cache[key] = result
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, indent=0, sort_keys=True), encoding="utf-8")
        except Exception as exc:
            logger.warning("geocode cache write failed: %s", exc)
    return result


# --------------------------------------------------------------- the line


@dataclass
class PhotoPlace:
    location: dict | None = None
    place: dict | None = None
    taken: datetime | date | None = None
    line: str | None = None
    extra: dict = field(default_factory=dict)


def compose_place_line(place: dict | None, location: dict | None, taken: datetime | date | None) -> str | None:
    parts: list[str] = []
    if place:
        names: list[str] = []
        for key in ("city", "state", "country"):
            v = (place.get(key) or "").strip()
            if v and v.lower() not in {n.lower() for n in names}:
                names.append(v)
        if names:
            parts.append(", ".join(names))
        if place.get("continent"):
            parts.append(place["continent"])
    if location and location.get("lat") is not None and location.get("lon") is not None:
        parts.append(f"{float(location['lat']):.4f}, {float(location['lon']):.4f}")
    if isinstance(taken, datetime):
        parts.append(f"taken {taken.strftime('%Y-%m-%d %H:%M')}")
    elif isinstance(taken, date):
        parts.append(f"taken {taken.isoformat()}")
    if not parts:
        return None
    return f"{PLACE_PREFIX} {' · '.join(parts)} {PLACE_MARKER}"


def insert_place_line(body: str, line: str | None) -> str:
    """Remove any existing place line(s), then (when `line`) put the new one
    just before the trailing `[asset](...)` block. Idempotent."""
    trailing_nl = body.endswith("\n")
    lines = [l for l in body.rstrip("\n").split("\n") if not is_place_line(l)]
    i = len(lines)
    # 🗂 file-meta lines (nodes/kb/file_meta.py) sit between 📍 and the
    # assets, so they count as part of the trailing block here.
    while i > 0 and (_ASSET_LINE_RE.match(lines[i - 1].strip()) or not lines[i - 1].strip() or _is_file_meta_line(lines[i - 1])):
        i -= 1
    head, tail = lines[:i], [l for l in lines[i:] if l.strip()]
    fm_lines = [l for l in tail if _is_file_meta_line(l)]
    if fm_lines:
        rest = [l for l in tail if not _is_file_meta_line(l)]
        tail = fm_lines + ([""] if rest else []) + rest
    while head and not head[-1].strip():
        head.pop()
    out = list(head)
    if line:
        if out:
            out.append("")
        out.append(line)
    if tail:
        if out:
            out.append("")
        out.extend(tail)
    text = "\n".join(out)
    return text + "\n" if trailing_nl else text


def resolve_photo_place(
    images: list[tuple[str, bytes]],
    *,
    private: bool,
    cache_path: Path | None,
    fallback_location: dict | None = None,
) -> PhotoPlace:
    """Location + capture time from the first image that carries them (EXIF,
    deterministic), place names from the cached geocoder (skipped when
    private), continent from the code table. Never raises."""
    location = None
    taken: datetime | date | None = None
    for name, data in images:
        if not is_image_name(name):
            continue
        try:
            if location is None:
                location = extract_photo_location(data)
            if taken is None:
                taken = extract_photo_datetime(data) or extract_photo_date(data)
        except Exception:
            continue
    if location is None and isinstance(fallback_location, dict) and "lat" in fallback_location and "lon" in fallback_location:
        location = {"lat": fallback_location["lat"], "lon": fallback_location["lon"]}
    place = None
    if location is not None:
        try:
            geo = cached_geocode(float(location["lat"]), float(location["lon"]), cache_path, allow_cloud=not private)
        except Exception as exc:  # belt and braces — never fail the save
            logger.warning("photo place resolve failed: %s", exc)
            geo = None
        if geo:
            place = {**geo, "continent": continent_for(geo.get("country"))}
    return PhotoPlace(location=location, place=place, taken=taken, line=compose_place_line(place, location, taken))


def geocode_cache_path(store) -> Path:
    """The data dir (KB root's parent) — outside kb/ so it never shows up as a note."""
    return Path(store.root).parent / GEOCODE_CACHE_FILE


def _body_image_assets(store, folder: str, content: str) -> list[tuple[str, bytes]]:
    out = []
    for line in content.splitlines():
        m = _ASSET_LINE_RE.match(line.strip())
        if m and is_image_name(m.group(1)):
            data = store.read_asset(folder, m.group(1))
            if data:
                out.append((m.group(1), data))
    return out


def bake_photo_place(
    store,
    folder: str,
    slug: str,
    images: list[tuple[str, bytes]] | None = None,
    *,
    private: bool | None = None,
    dry_run: bool = False,
) -> PhotoPlace | None:
    """Resolve + write the 📍 line and `place`/`location` frontmatter into
    an existing note on disk. `images` defaults to the note's own image
    assets; `private` defaults to the note's flag. Returns the PhotoPlace
    (with `.extra["body"]` = the new body) or None when there is nothing to
    bake (no image data, no location). Never raises; does not restamp
    `edited` (derived metadata, like set_private)."""
    try:
        path = store.entry_path(folder, slug)
        if not path.is_file():
            return None
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        if images is None:
            images = _body_image_assets(store, folder, post.content)
        if private is None:
            from .privacy import is_private_meta

            private = is_private_meta(post.metadata)
        if not images and not post.metadata.get("location"):
            return None
        info = resolve_photo_place(
            images, private=private, cache_path=geocode_cache_path(store), fallback_location=post.metadata.get("location")
        )
        if info.line is None:
            return None
        new_body = insert_place_line(post.content, info.line)
        info.extra["body"] = new_body
        info.extra["changed"] = new_body != post.content or (info.place and post.metadata.get("place") != info.place)
        if dry_run:
            return info
        post.content = new_body
        if info.location is not None:
            post["location"] = info.location
        if info.place is not None:
            post["place"] = info.place
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return info
    except Exception as exc:
        logger.warning("bake_photo_place failed for %s/%s: %s", folder, slug, exc)
        return None


def backfill_photo_places(store, *, dry_run: bool = True, index=None) -> list[dict]:
    """Walk every KB note with image assets (or frontmatter `location`),
    add/refresh its 📍 line + `place`, and (when applying) re-index it via
    `index(folder, slug, title, body)`. Returns one row per note that would
    change / changed."""
    results = []
    for folder in store.list_folders():
        for slug in store.list_entries(folder):
            info = bake_photo_place(store, folder, slug, dry_run=dry_run)
            if info is None or not info.extra.get("changed"):
                continue
            row = {"folder": folder, "slug": slug, "line": info.line, "place": info.place, "location": info.location}
            if not dry_run and index is not None:
                full = store.read_full(folder, slug) or {}
                index(folder, slug, full.get("title") or slug, info.extra["body"])
            results.append(row)
    return results
