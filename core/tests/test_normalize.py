from quintacle_core.nodes.journal.normalize import canonicalize_name


def test_case_and_hyphen_variants_resolve_to_the_established_name():
    known = ["Pull Ups"]
    assert canonicalize_name("pull ups", known) == "Pull Ups"
    assert canonicalize_name("pull-ups", known) == "Pull Ups"
    assert canonicalize_name("PULL UPS", known) == "Pull Ups"


def test_unrelated_name_passes_through_unchanged():
    known = ["Pull Ups", "Deadlift"]
    assert canonicalize_name("Bench Press", known) == "Bench Press"


def test_empty_known_list_passes_through_unchanged():
    assert canonicalize_name("Deadlift", []) == "Deadlift"


def test_picks_the_closest_of_multiple_known_names():
    known = ["Deadlift", "Deadlift (sumo)"]
    assert canonicalize_name("deadlift", known) == "Deadlift"
