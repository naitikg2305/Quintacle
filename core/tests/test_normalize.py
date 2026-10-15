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


def test_expand_routine_mentions_adds_preset_exercises():
    from quintacle_core.nodes.journal.normalize import expand_routine_mentions

    entries = [{"type": "activity", "category": "yourself", "description": "gym at 7 did pull day"}]
    routines = [{"name": "Pull Day", "exercises": ["Pullups", "Barbell Rows", "Lat Pulldown"]}]
    expand_routine_mentions(entries, "gym at 7 did pull day, felt good", routines)

    names = [e["exercise_name"] for e in entries if e.get("type") == "exercise"]
    assert names == ["Pullups", "Barbell Rows", "Lat Pulldown"]
    assert all(e["sets"] == [] for e in entries if e.get("type") == "exercise")


def test_expand_routine_mentions_skips_already_expanded_and_unmentioned():
    from quintacle_core.nodes.journal.normalize import expand_routine_mentions

    entries = [{"type": "exercise", "exercise_name": "Pullups", "sets": [{"reps": 8}]}]
    routines = [
        {"name": "Pull Day", "exercises": ["Pullups", "Barbell Rows"]},
        {"name": "Leg Day", "exercises": ["Squats"]},
    ]
    expand_routine_mentions(entries, "did pull day", routines)

    names = [e["exercise_name"] for e in entries if e.get("type") == "exercise"]
    assert names == ["Pullups", "Barbell Rows"]  # no duplicate Pullups, no Leg Day


def test_parse_journal_dump_expands_routine_even_when_model_does_not(monkeypatch):
    from quintacle_core.nodes.journal import llm as journal_llm

    class FakeParsed:
        def __init__(self):
            self.entries = [
                journal_llm.ActivityEntry(type="activity", category="yourself", description="did pull day", hours=1.0)
            ]

    class FakeResult:
        parsed = FakeParsed()
        provider_used = "local"

    monkeypatch.setattr(journal_llm, "parse_structured", lambda *a, **k: FakeResult())
    entries = journal_llm.parse_journal_dump(
        "did pull day", known_routines=[{"name": "Pull Day", "exercises": ["Pullups", "Barbell Rows"]}]
    )
    names = [e.exercise_name for e in entries if getattr(e, "type", "") == "exercise"]
    assert names == ["Pullups", "Barbell Rows"]
    assert all("from routine" in e.notes for e in entries if getattr(e, "type", "") == "exercise")
