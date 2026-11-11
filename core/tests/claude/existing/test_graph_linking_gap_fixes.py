"""Focused tests for the 2026-11-11 graph-linking gap fixes
(docs/testing/graph-linking-38-categories.md "Known gaps"), covering the
edges of each rule the category tests don't: first-name ambiguity and the
proper-noun guard, hub vs non-hub notes under Projects/Career, accounts,
known places only when the node exists, visited-day links in both save
orders, folder charter hubs created after their members, and the startup
backfill doing all of it for pre-existing content. Sandboxed tmp DATA_DIR,
no model anywhere."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core import retrieval
from quintacle_core.graph import candidate_mentioned, get_graph_store, proper_name_mentioned
from quintacle_core.graph_capture import mention_candidates, run_graph_capture_backfill

DAY = "2026-11-10"


@pytest.fixture(autouse=True)
def _reset_retrieval():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    return TestClient(api_module.create_app())


def ok(res):
    assert res.status_code == 200, res.text
    return res.json()


def person(c, name: str) -> str:
    return f"note:{ok(c.post('/people', json={'name': name, 'category': 'friend'}))['folder']}/profile"


def note(c, folder, title, content="", links=None) -> str:
    j = ok(c.post("/kb/entries", json={"folder": folder, "title": title, "content": content, "links": links or []}))
    return f"note:{j['folder']}/{j['slug']}"


def journal(c, day: str, text: str) -> None:
    ok(c.post(f"/journal/{day}", content=text, headers={"content-type": "text/plain"}))


def experience(c, **fields) -> str:
    j = ok(c.post("/travel/experiences", json={"kind": "restaurant", "links": [], **fields}))
    return f"experience:{j['folder']}/{j['slug']}"


def edge_set() -> set[tuple[str, str, str]]:
    return {(e["source_id"], e["target_id"], e["kind"]) for e in get_graph_store().all()}


def linked(a: str, b: str) -> bool:
    return any({s, t} == {a, b} for s, t, _k in edge_set())


# --- 1. first names --------------------------------------------------------


def test_matcher_proper_noun_rule():
    assert proper_name_mentioned("Alfonso", "convo with Alfonso today")
    assert proper_name_mentioned("Alfonso", "ALFONSO called")
    assert not proper_name_mentioned("Will", "I will call later")
    assert not proper_name_mentioned("Arjun", "Arjuna's bow")  # whole word only


def test_first_name_alias_only_for_unique_first_names():
    people = [
        {"name": "Arjun Mehta", "folder": "people/arjun-mehta"},
        {"name": "Arjun Rao", "folder": "people/arjun-rao"},
        {"name": "Alfonso Rivera", "folder": "people/alfonso-rivera"},
        {"name": "Al Gore", "folder": "people/al-gore"},  # first name < 3 letters: never an alias
        {"name": "Cher", "folder": "people/cher"},  # single-word name: its title IS the name
    ]
    by_title = {cand["title"]: cand for cand in mention_candidates(people, [])}
    assert by_title["Alfonso Rivera"]["aliases"] == ["Alfonso"]
    assert "aliases" not in by_title["Arjun Mehta"] and "aliases" not in by_title["Arjun Rao"]
    assert "aliases" not in by_title["Al Gore"]
    assert candidate_mentioned(by_title["Alfonso Rivera"], "lunch with Alfonso")
    assert not candidate_mentioned(by_title["Arjun Mehta"], "lunch with Arjun")


def test_shared_first_name_links_nobody(c):
    mehta, rao = person(c, "Arjun Mehta"), person(c, "Arjun Rao")
    journal(c, DAY, "Coffee with Arjun before work.")
    out = {t for s, t, _k in edge_set() if s == f"journal:{DAY}"}
    assert mehta not in out and rao not in out


def test_lowercase_first_name_word_does_not_link(c):
    will = person(c, "Will Turner")
    journal(c, DAY, "I will finish the deck tonight.")
    assert not linked(f"journal:{DAY}", will)
    journal(c, "2026-11-11", "Drinks with Will after work.")
    assert (f"journal:2026-11-11", will, "mentions_person") in edge_set()


# --- 2. hubs + accounts as candidates ---------------------------------------


def test_only_hub_notes_under_projects_are_candidates(c):
    ok(c.post("/projects", json={"name": "Rover", "description": "Autonomous rover."}))
    design = note(c, "Projects/Rover", "Design", "Motor layout.")
    n = note(c, "Knowledge/Tech Notes", "System design", "Design review for the Rover chassis.")
    assert (n, "note:projects/rover/rover", "related") in edge_set()
    assert not linked(n, design)  # a deeper note ("Design") is not a hub


def test_hub_name_as_plain_word_does_not_link(c):
    ok(c.post("/projects", json={"name": "Rover", "description": ""}))
    n = note(c, "Fun/Dogs", "Dog notes", "the rover in the yard keeps digging")
    assert not linked(n, "note:projects/rover/rover")


def test_note_links_named_finance_account(c):
    ok(c.post("/finance/accounts", json={"name": "Ally Savings", "account_type": "savings", "institution": "Ally"}))
    n = note(c, "Organisation/Finance/Goals", "Goals", "Move $500 a month into Ally Savings.")
    assert (n, "note:organisation/finance/accounts/ally-savings", "related") in edge_set()


# --- 3. back-links on create --------------------------------------------------


def test_new_person_backlinks_first_name_only_mentions(c):
    journal(c, DAY, "Climbing with Neha again.")
    neha = person(c, "Neha Kapoor")
    assert (f"journal:{DAY}", neha, "mentions_person") in edge_set()


def test_new_career_hub_backlinks_existing_notes(c):
    n = note(c, "Side Hustles", "Contract plan", "Ten hours a week for Minfy.")
    ok(c.post("/career/hubs", json={"type": "employer", "name": "Minfy", "summary": "AWS consulting."}))
    assert (n, "note:career/minfy/minfy", "related") in edge_set()


# --- 4. known places -------------------------------------------------------------


def test_city_without_a_place_node_is_not_linked(c):
    journal(c, DAY, "Dreaming about Kyoto.")
    assert not any(s == f"journal:{DAY}" and ("kyoto" in t) for s, t, _k in edge_set())


def test_known_city_links_once_and_not_as_a_plain_word(c):
    experience(c, name="Cafe Central", city="Vienna", visited_date="2026-05-14")
    n = note(c, "Personal/Notes", "Pastry list", "Sachertorte from Vienna, twice.")
    targets = [t for s, t, k in edge_set() if s == n and k == "at_location" and t.endswith("/vienna")]
    assert len(targets) == 1
    experience(c, name="Le Negresco", city="Nice")
    m = note(c, "Personal/Notes", "Weather", "It was a nice day.")
    assert not any(s == m and t.endswith("/nice") for s, t, _k in edge_set())


# --- 5. experience -> visited day -------------------------------------------


def test_experience_without_visited_date_gets_no_day(c):
    journal(c, DAY, "Quiet day.")
    exp = experience(c, name="Le Diplomate", city="Washington DC")
    assert not any(s == exp and k == "on_day" for s, t, k in edge_set())


def test_experience_before_its_journal_day_links_when_the_day_is_written(c):
    exp = experience(c, name="Le Diplomate", city="Washington DC", visited_date=DAY)
    assert not any(s == exp and k == "on_day" for s, t, k in edge_set())  # no dangling day
    journal(c, DAY, "Dinner out.")
    assert (exp, f"journal:{DAY}", "on_day") in edge_set()


# --- 6. folder charter hubs ---------------------------------------------------------


def test_charter_created_after_its_members_links_them(c):
    a = note(c, "Fun/Shows", "Lost", "Island.")
    b = note(c, "Fun/Shows", "Severance", "Office.")
    other = note(c, "Fun/Books", "Dune", "Sand.")
    hub = note(c, "Fun/Shows", "About Shows", "One note per show.")
    assert hub == "note:fun/shows/about-shows"
    assert (a, hub, "part_of") in edge_set() and (b, hub, "part_of") in edge_set()
    assert not linked(other, hub)


# --- the startup backfill applies every rule to pre-existing content ---------------


def test_backfill_applies_the_new_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    alfonso = person(c, "Alfonso Rivera")
    ok(c.post("/projects", json={"name": "Quintacle", "description": ""}))
    exp = experience(c, name="Cafe Central", city="Vienna", visited_date=DAY)
    journal(c, DAY, "Convo with Alfonso about Quintacle in Vienna.")
    note(c, "Fun/Shows", "Lost", "Island.")
    note(c, "Fun/Shows", "About Shows", "One note per show.")

    store = get_graph_store()
    for e in store.all():  # wipe every edge: as if all of it predates the rules
        store.remove_edge(e["id"])
    assert store.all() == []

    counts = run_graph_capture_backfill()
    assert counts["structural_edges"] >= 2
    edges = edge_set()
    day = f"journal:{DAY}"
    assert (day, alfonso, "mentions_person") in edges
    assert (day, "note:projects/quintacle/quintacle", "related") in edges
    assert (exp, day, "on_day") in edges
    assert ("note:fun/shows/lost", "note:fun/shows/about-shows", "part_of") in edges
    # the backfill is idempotent
    before = len(store.all())
    run_graph_capture_backfill()
    assert len(store.all()) == before
