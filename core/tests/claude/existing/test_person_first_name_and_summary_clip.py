"""2026-11-11 live-suite findings: a first-name-only mention of a tracked
person never reached the model (the gate matched full names only), and the
prose summary was cut mid-word at 120 chars. Models faked here."""
from __future__ import annotations

from types import SimpleNamespace

from quintacle_core import retrieval
from quintacle_core.nodes.people import llm as people_llm
from quintacle_core.nodes.people.llm import PersonMentionEstimate, _known_name_re, resolve_known_person

KNOWN = ["Arjun Mehta", "Priya Shah", "Sam Lee", "Sam Ortiz"]


def test_gate_matches_unique_first_name():
    rx = _known_name_re(KNOWN)
    assert rx.search("coffee with Arjun at Compass")
    assert rx.search("dinner with arjun mehta")
    # Two tracked Sams: the first name alone is ambiguous, so it isn't a trigger.
    assert not rx.search("lunch with Sam today")


def test_resolve_known_person():
    assert resolve_known_person("Arjun", KNOWN) == "Arjun Mehta"
    assert resolve_known_person("arjun mehta", KNOWN) == "Arjun Mehta"
    assert resolve_known_person("Sam", KNOWN) is None
    assert resolve_known_person("Theo Park", KNOWN) is None
    assert resolve_known_person("Arjun Kapoor", KNOWN) is None


def _fake(monkeypatch, est):
    monkeypatch.setattr(people_llm, "parse_structured", lambda *a, **k: SimpleNamespace(parsed=est))


def test_first_name_mention_resolves_to_tracked_person(monkeypatch):
    _fake(monkeypatch, PersonMentionEstimate(is_person_mention=True, is_new_person=True, person_name="Arjun", notes="startup"))
    est = people_llm.maybe_structure_person_mention("coffee with Arjun, talked about his startup", KNOWN)
    assert est is not None and est.is_new_person is False and est.person_name == "Arjun Mehta"


def test_explicit_new_person_with_same_first_name_stays_new(monkeypatch):
    _fake(monkeypatch, PersonMentionEstimate(is_person_mention=True, is_new_person=True, person_name="Arjun", notes="climber"))
    est = people_llm.maybe_structure_person_mention("met a new guy named Arjun at the gym", KNOWN)
    assert est is not None and est.is_new_person is True and est.person_name == "Arjun"


def test_summary_clip_whole_words():
    long = "Honda Civic oil change and tire rotation at Jiffy Lube, front brake pads at 3mm needing replacement within a month, cost was $89"
    out = retrieval._clip_summary(long)
    assert len(out.split()) <= retrieval.PROSE_SUMMARY_WORDS
    assert len(out) <= retrieval.PROSE_SUMMARY_CHARS
    assert long.startswith(out) and not out.endswith(",")
    assert retrieval._clip_summary("Short line.") == "Short line."
