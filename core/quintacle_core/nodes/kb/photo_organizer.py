from __future__ import annotations

from datetime import date

import anthropic
from pydantic import BaseModel

from ...llm_config import DEFAULT_MODEL


class GeocodedLocation(BaseModel):
    country: str
    state: str
    city: str


def geocode(lat: float, lon: float) -> GeocodedLocation:
    """Reverse-geocode via Claude's own geographic knowledge — no external
    geocoding API or key. Good enough for sorting personal photos into
    country/state/city folders; not a precision mapping product."""
    client = anthropic.Anthropic()
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
    photo_date: date, location: dict | None, trip_name: str | None, home_countries: list[str] | None = None
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
    there's actually a location/trip to resolve."""
    base = f"Media/Photos/{photo_date.year}/{photo_date.strftime('%B')}"
    if trip_name:
        return f"{base}/{trip_name}"
    if location:
        geo = geocode(location["lat"], location["lon"])
        home = {c.strip().lower() for c in (home_countries or [])}
        if geo.country.strip().lower() not in home:
            return f"{base}/{geo.country}/{geo.state}/{geo.city}"
    return base
