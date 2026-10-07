from __future__ import annotations

from datetime import date

from ... import clock
from .models import Profile

# Standard activity multipliers for BMR -> TDEE (Mifflin-St Jeor is the BMR
# formula; these are the widely-used activity-level scalars on top of it).
_ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

# General strength-training/fitness protein recommendation. Real RDA tables
# (MALE_RDA) don't scale with body weight — protein genuinely does, so it's
# handled separately here rather than folded into that static reference.
_PROTEIN_G_PER_KG = 1.6

LB_TO_KG = 0.453592


def age_years(birthdate: date, today: date) -> int:
    had_birthday = (today.month, today.day) >= (birthdate.month, birthdate.day)
    return today.year - birthdate.year - (0 if had_birthday else 1)


def compute_targets(profile: Profile, weight_kg: float, today: date | None = None) -> dict | None:
    """Mifflin-St Jeor BMR -> TDEE, plus a protein target. Deterministic —
    no AI involved, same principle as quotas.py's period math. Returns None
    if the profile isn't complete enough to compute (missing height/sex/dob)."""
    if profile.height_cm is None or profile.sex is None or profile.birthdate is None:
        return None

    today = today or clock.today()
    age = age_years(profile.birthdate, today)
    sex_offset = 5 if profile.sex == "male" else -161
    bmr = 10 * weight_kg + 6.25 * profile.height_cm - 5 * age + sex_offset
    tdee = bmr * _ACTIVITY_MULTIPLIERS[profile.activity_level]

    return {
        "age": age,
        "weight_kg": round(weight_kg, 1),
        "bmr": round(bmr),
        "tdee_kcal": round(tdee),
        "protein_target_g": round(_PROTEIN_G_PER_KG * weight_kg),
    }
