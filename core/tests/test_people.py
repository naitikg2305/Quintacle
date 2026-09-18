from quintacle_core.nodes.people.llm import _NEW_PERSON_SIGNAL_RE, _known_name_re
from quintacle_core.nodes.people.store import PersonStore


def test_person_write_then_all(tmp_path):
    store = PersonStore(tmp_path)
    folder, slug = store.write("Laura", category="dating", how_met="mutual friend", notes="Loves hiking.")

    people = store.all()
    assert len(people) == 1
    assert people[0]["name"] == "Laura"
    assert people[0]["category"] == "dating"
    assert people[0]["notes"] == "Loves hiking."
    assert people[0]["folder"] == folder
    assert slug == "laura"
    assert folder == "people/laura"


def test_profile_lives_inside_the_persons_own_folder(tmp_path):
    """The whole point of nesting: a mention filed into <folder>/Mentions
    and the profile file must both resolve as descendants of the same
    folder, so the existing folder-scoped chat sees both with zero new code."""
    store = PersonStore(tmp_path)
    folder, _ = store.write("Alex", category="friend")

    profile_path = tmp_path / "people" / "alex" / "profile.md"
    assert profile_path.exists()
    assert folder == "people/alex"


def test_find_matches_case_insensitively(tmp_path):
    store = PersonStore(tmp_path)
    store.write("Laura", category="dating")

    assert store.find("laura") is not None
    assert store.find("Nobody") is None


def test_new_person_signal_regex():
    assert _NEW_PERSON_SIGNAL_RE.search("met a new friend today named Alex")
    assert _NEW_PERSON_SIGNAL_RE.search("went on a first date with Sarah")
    assert not _NEW_PERSON_SIGNAL_RE.search("logged today's weight, 181.2 lbs")


def test_known_name_regex_matches_word_boundaries():
    pattern = _known_name_re(["Laura", "Alex"])
    assert pattern is not None
    assert pattern.search("grabbed coffee with Laura")
    assert not pattern.search("lauraverse is not a word")
