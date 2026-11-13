"""2026-11-13 (owner, T1): a trip plan's folder carries its year; proposed
links must name something that exists."""
from quintacle_core.drop_fixups import existing_links_only, planned_folder_with_year


def test_year_from_plan_dates_goes_in_the_trip_folder():
    assert planned_folder_with_year("Fun/Travel/Planned/Europe", "Central Europe", "May 12-21, 2027 in Europe") == "Fun/Travel/Planned/Europe 2027"


def test_year_from_title_when_body_has_no_dates():
    assert planned_folder_with_year("Fun/Travel/Planned/Japan", "Japan Trip 2028", "temples") == "Fun/Travel/Planned/Japan 2028"


def test_folder_already_carrying_a_year_is_left_alone():
    assert planned_folder_with_year("Fun/Travel/Planned/Central Europe 2027", "x", "May 12-21, 2027") == "Fun/Travel/Planned/Central Europe 2027"


def test_no_year_known_leaves_folder_alone():
    assert planned_folder_with_year("Fun/Travel/Planned/Japan", "Japan", "temples and ramen") == "Fun/Travel/Planned/Japan"


def test_only_planned_trip_subfolders_change():
    assert planned_folder_with_year("Fun/Travel/Bucket List/Japan", "Japan 2028", "") == "Fun/Travel/Bucket List/Japan"
    assert planned_folder_with_year("Fun/Travel/Planned", "Trip 2027", "") == "Fun/Travel/Planned"
    assert planned_folder_with_year("Knowledge/Tech Notes", "Notes 2027", "") == "Knowledge/Tech Notes"


def test_links_to_missing_notes_are_dropped():
    assert existing_links_only(["About Travel", "quintacle"], ["Quintacle", "About Work Logs"]) == ["Quintacle"]
    assert existing_links_only([], ["Quintacle"]) == []
