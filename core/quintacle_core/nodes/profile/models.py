from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

ActivityLevel = Literal["sedentary", "light", "moderate", "active", "very_active"]


class Profile(BaseModel):
    height_cm: float | None = None
    sex: Literal["male", "female"] | None = None
    birthdate: date | None = None
    activity_level: ActivityLevel = "moderate"
    # Countries a dropped photo's GPS shouldn't get a full country/state/city
    # breakdown for — "home," so everyday photos there just file by
    # Year/Month instead of triggering geocoding. Empty by default: no
    # assumptions about where anyone lives until they say so.
    home_countries: list[str] = []
