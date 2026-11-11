from datetime import date

from quintacle_core.nodes.kb.photo_organizer import compute_photo_folder


def test_trip_name_wins_over_everything():
    folder = compute_photo_folder(date(2026, 4, 10), {"lat": 35.0, "lon": 139.0}, "Japan Trip 2026")
    assert folder == "Media/Photos/2026/April/Japan Trip 2026"


def test_no_location_no_trip_falls_back_to_month_only():
    folder = compute_photo_folder(date(2026, 4, 10), None, None)
    assert folder == "Media/Photos/2026/April"


def test_month_is_full_name_not_number():
    folder = compute_photo_folder(date(2026, 1, 1), None, None)
    assert folder == "Media/Photos/2026/January"
