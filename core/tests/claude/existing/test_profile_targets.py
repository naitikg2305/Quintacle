from datetime import date

from quintacle_core.nodes.profile.models import Profile
from quintacle_core.nodes.profile.targets import compute_targets


def test_incomplete_profile_returns_none():
    assert compute_targets(Profile(), weight_kg=80) is None
    assert compute_targets(Profile(height_cm=180), weight_kg=80) is None


def test_male_mifflin_st_jeor_bmr_and_tdee():
    profile = Profile(height_cm=180, sex="male", birthdate=date(1996, 9, 8), activity_level="moderate")

    targets = compute_targets(profile, weight_kg=80, today=date(2026, 9, 8))

    # BMR = 10*80 + 6.25*180 - 5*30 + 5 = 800 + 1125 - 150 + 5 = 1780
    assert targets["age"] == 30
    assert targets["bmr"] == 1780
    assert targets["tdee_kcal"] == round(1780 * 1.55)
    assert targets["protein_target_g"] == round(80 * 1.6)


def test_female_offset_is_different_from_male():
    male = compute_targets(Profile(height_cm=170, sex="male", birthdate=date(1990, 1, 1)), weight_kg=70, today=date(2026, 1, 1))
    female = compute_targets(Profile(height_cm=170, sex="female", birthdate=date(1990, 1, 1)), weight_kg=70, today=date(2026, 1, 1))

    assert male["bmr"] != female["bmr"]
    assert male["bmr"] - female["bmr"] == 166  # sex offset difference: +5 vs -161


def test_age_not_yet_had_birthday_this_year_rounds_down():
    # Born Sept 8; "today" is Sept 7 -> birthday hasn't happened yet this year.
    profile = Profile(height_cm=180, sex="male", birthdate=date(1996, 9, 8))

    targets = compute_targets(profile, weight_kg=80, today=date(2026, 9, 7))

    assert targets["age"] == 29
