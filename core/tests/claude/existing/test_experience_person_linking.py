"""Proves the concrete retrofit from docs/graph-model.md end to end: an
experience and a person detected from the same drop used to be created side
by side with no connection between them at all (exp_links never included
the person's name; the person-mention kb_entry hardcoded links: []). Now
each commit endpoint calls graph.link_new_entry and a real typed edge
(mentions_person / at_location) gets created."""

from quintacle_core.db import connect
from quintacle_core.graph import get_graph_store, init_graph_store, reverse_lookup
from quintacle_core.nodes.journal.api import init_store as init_journal_store
from quintacle_core.nodes.kb.api import EntryCreate, create_entry, init_store as init_kb_store
from quintacle_core.nodes.people.api import (
    PersonCreate,
    create_person,
    init_store as init_people_store,
)
from quintacle_core.nodes.travel.api import (
    ExperienceCreate,
    create_experience,
    get_store as get_travel_store,
    init_store as init_travel_store,
)


def setup(tmp_path):
    kb_root = tmp_path / "kb"
    init_kb_store(kb_root)
    init_journal_store(tmp_path / "journal")
    init_travel_store(kb_root)
    init_people_store(kb_root)
    init_graph_store(tmp_path, connect(tmp_path / "test.db"))


def test_experience_created_after_person_links_via_mentions_person(tmp_path):
    setup(tmp_path)
    create_person(PersonCreate(name="Laura", category="dating", notes="Met at a party."))
    create_experience(
        ExperienceCreate(name="Carbone", city="New York", kind="restaurant", notes="Great dinner.", links=["Laura"])
    )

    person_id = "note:people/laura/profile"
    edges = reverse_lookup(person_id)
    assert any(e["kind"] == "mentions_person" for e in edges), edges


def test_person_created_after_experience_links_via_at_location(tmp_path):
    setup(tmp_path)
    create_experience(ExperienceCreate(name="Nobu", city="Tokyo", kind="restaurant", notes="Loved it."))
    create_person(PersonCreate(name="Alex", category="friend", notes="We went to Nobu.", links=["Nobu"]))

    exp = get_travel_store().all()[0]
    exp_id = f"experience:{exp['folder']}/{exp['slug']}"
    edges = reverse_lookup(exp_id)
    assert any(e["kind"] == "at_location" for e in edges), edges


def test_neither_side_creates_a_bogus_edge_when_nothing_matches(tmp_path):
    setup(tmp_path)
    create_person(PersonCreate(name="Jordan", category="friend", notes="Nothing experience-related."))
    create_experience(ExperienceCreate(name="Diner on 5th", city="New York", kind="restaurant", notes="Just a diner."))

    person_id = "note:people/jordan/profile"
    assert reverse_lookup(person_id) == []


def test_kb_mention_note_links_to_both_person_and_experience(tmp_path):
    """The exact gap named in the task: the Mentions kb_entry hardcoded
    links: [] and exp_links never included the person's name — both ends
    now get a real edge once propose_drop's `links` hint reaches the
    commit endpoints."""
    setup(tmp_path)
    create_person(PersonCreate(name="Sam", category="friend"))
    create_experience(ExperienceCreate(name="Joe's Pizza", city="New York", kind="restaurant"))

    create_entry(
        EntryCreate(
            folder="people/sam/mentions",
            title="Sam — 2026-10-13",
            content="Grabbed a slice with Sam at Joe's Pizza.",
            links=["Joe's Pizza"],
        )
    )

    note_id = "note:people/sam/mentions/sam-2026-10-13"
    outgoing_kinds = {e["kind"] for e in get_graph_store().edges_from(note_id)}
    assert "mentions_person" in outgoing_kinds
    assert "at_location" in outgoing_kinds
