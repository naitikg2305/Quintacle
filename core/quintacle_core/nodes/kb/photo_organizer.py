from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel

from ...llm_config import DEFAULT_MODEL
from ...max_backend import cloud_client


class GeocodedLocation(BaseModel):
    country: str
    state: str
    city: str


class GeocodeUnavailable(RuntimeError):
    """No local answer for these coords and the provider forbids the cloud."""


def geocode(lat: float, lon: float) -> GeocodedLocation:
    """GPS -> country/state/city, local-first (2026-11-11).

    The provider is the image policy's (perception/image_policy.py): /drop's
    `provider` field (request override) > QUINTACLE_IMAGE_PROVIDER > local.
      local  the offline GeoNames gazetteer (geo_offline.py) or
             GeocodeUnavailable — NEVER a cloud call. Callers degrade to
             coordinates-only (no place names, month folder).
      auto   offline first, Claude when the gazetteer has no answer.
      cloud  Claude (the user chose it — "Redo with cloud"); the offline
             answer still covers a cloud failure.
    The Claude call uses the model's own geographic knowledge — no external
    geocoding API or key. 2026-11-07: refuses NaN / out-of-range / 0,0
    coordinates outright (ValueError) before anything else."""
    from ... import geo_offline
    from ...perception.image_policy import image_provider
    from .drop import valid_coords

    if not valid_coords(lat, lon):
        raise ValueError(f"not real coordinates: {lat}, {lon}")
    mode = image_provider()
    offline = geo_offline.reverse(lat, lon)
    local = GeocodedLocation(country=offline["country"], state=offline["state"], city=offline["city"]) if offline else None
    if mode != "cloud" and local is not None:
        return local
    if mode == "local":
        raise GeocodeUnavailable(
            "no offline place data for these coordinates (python -m quintacle_core.geo_offline installs it) "
            "and the provider is local — coordinates only"
        )
    try:
        return _geocode_cloud(lat, lon)
    except Exception:
        if local is not None:
            return local
        raise


def _geocode_cloud(lat: float, lon: float) -> GeocodedLocation:
    client = cloud_client()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=256,
        system=(
            "Given GPS coordinates, identify the country, state/region, and nearest city — "
            "real place names suitable as folder names (e.g. country='Japan', state='Tokyo', "
            "city='Shibuya')."
        ),
        messages=[{"role": "user", "content": f"{lat}, {lon}"}],
        output_format=GeocodedLocation,
    )
    return response.parsed_output


def compute_photo_folder(
    photo_date: date,
    location: dict | None,
    trip_name: str | None,
    home_countries: list[str] | None = None,
    cache_path: Path | None = None,
) -> str:
    """Deterministic placement for a real camera photo, once its date (and
    optionally location/trip) are known:

    Media/Photos/<Year>/<Month>/<Trip Name>            — a recognized trip
    Media/Photos/<Year>/<Month>/<Country>/<State>/<City> — abroad, no named trip
    Media/Photos/<Year>/<Month>                        — everyday home life

    "Home" is whatever countries are set in Profile.home_countries — not
    hardcoded, so this behaves correctly for whoever's actually running the
    app, not just one person. Empty/unset means every location gets the full
    breakdown (safe default, no assumption about where anyone lives).

    Only the month base is deterministic from the EXIF date alone; the
    trip_name (AI, sees the whole batch at once) and geocode() (AI, GPS ->
    place name) are the only non-deterministic pieces, and only run when
    there's actually a location/trip to resolve.

    2026-11-11: geocoding goes through photo_place.cached_geocode (the
    local-first geocode() above + the shared `<data>/geocode-cache.json`
    when `cache_path` is given), and NEVER fails or blocks the drop: no
    place names (local mode, no offline data, cloud down) = the month
    folder, since home vs abroad can't be told."""
    base = f"Media/Photos/{photo_date.year}/{photo_date.strftime('%B')}"
    if trip_name:
        return f"{base}/{trip_name}"
    from .drop import clean_location

    location = clean_location(location)  # 2026-11-07: NaN/0,0 = no location
    if location:
        from .photo_place import cached_geocode

        geo = cached_geocode(float(location["lat"]), float(location["lon"]), cache_path)
        if geo and geo.get("country"):
            home = {c.strip().lower() for c in (home_countries or [])}
            if geo["country"].strip().lower() not in home:
                parts = [p for p in (geo["country"], geo.get("state"), geo.get("city")) if (p or "").strip()]
                return "/".join([base, *parts])
    return base
