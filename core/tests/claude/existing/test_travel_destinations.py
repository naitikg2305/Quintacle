"""2026-11-11: derived trip destinations + the typed bucket-list gate.

- A Fun/Travel/Planned (or Bucket List) note with NO `fields.destinations`
  still joins the place graph: places come from its folder segments and the
  cities/countries named in its title + body (gazetteer.find_places), code
  only. A hand-typed Destinations still wins.
- The backfill links such plans too.
- A typed "Someday I want to see <place>" becomes a Fun/Travel/Bucket List
  proposal (states.bucket_wish_proposal) even though parse_journal_dump's
  prompt never sees the folder list.

Faked: every model call on the drop path is monkeypatched; no network."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core import retrieval
from quintacle_core.gazetteer import find_places
from quintacle_core.graph import get_graph_store
from quintacle_core.nodes.journal.llm import KBEntryProposal, TodoEntry
from quintacle_core.nodes.travel.states import bucket_wish_proposal
from quintacle_core.place_graph import derive_destinations, destinations_text, proposal_destinations

EU, AT, VIE = "place:europe", "place:europe/austria", "place:europe/austria/vienna"

VIENNA_BODY = (
    "VIENNA, AUSTRIA | MAY 2027 | TRIP PLAN\n\n"
    "4 days in Vienna. Fly IAD to Vienna (VIE) Fri May 14, back Tue May 18.\n\n"
    "Day 1: Stephansdom, coffee and Sachertorte at Cafe Central."
)


@pytest.fixture(autouse=True)
def _reset_retrieval_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    # Seeded registries (CLAUDE.md: entity-grounded, never scratch).
    c.post("/people", json={"name": "Laura", "category": "friend", "how_met": "college"})
    c.post("/kb/entries", json={"folder": "Fun/Travel/Planned/Japan", "title": "Tokyo plan", "content": "Tokyo, Japan."})
    c.post("/kb/entries", json={"folder": "Fun/Travel/Bucket List", "title": "Patagonia", "content": "Hiking."})
    return c


def edges(kind=None):
    return {(e["source_id"], e["target_id"], e["kind"]) for e in get_graph_store().all() if kind is None or e["kind"] == kind}


def _save(client, folder, title, content, fields=None):
    body = {"folder": folder, "title": title, "content": content}
    if fields is not None:
        body["fields"] = fields
    res = client.post("/kb/entries", json=body)
    assert res.status_code == 200, res.text
    return f"note:{res.json()['folder']}/{res.json()['slug']}"


# --------------------------------------------------------------- gazetteer


def test_find_places_is_conservative():
    got = find_places("Fly from Boston to Paris, then Lyon. nice weather; Chad and Jordan come; turkey sandwich")
    assert [(p.city, p.country) for p in got] == [("Paris", "France"), ("Lyon", "France")]
    upper = find_places("VIENNA, AUSTRIA | MAY 2027")
    assert [(p.city, p.country, p.continent) for p in upper] == [("Vienna", "Austria", "Europe"), (None, "Austria", "Europe")]
    assert find_places("vienna sausages") == []  # lower-case is not a name


def test_derive_destinations_folder_and_text():
    d = derive_destinations("fun/travel/planned/europe/austria", "# Plan\n\nDay trip to Salzburg.\n[asset](assets/vienna.md)")
    assert destinations_text(d) == "Salzburg, Austria"  # Europe/Austria covered by the city; asset line ignored
    assert destinations_text(derive_destinations("fun/travel/planned/japan", "# Plan\n\nNothing named.")) == "Japan"
    assert destinations_text(derive_destinations("fun/travel/planned/2027", "# Plan\n\nRome, then Paris.")) == "Rome, Italy; Paris, France"
    assert derive_destinations("fun/travel/planned/summer", "# Ideas\n\nsomewhere warm") == []
    assert proposal_destinations("Fun/Travel/Planned/Austria", "Vienna trip", VIENNA_BODY) == "Vienna, Austria"
    assert proposal_destinations("Work/Notes", "Vienna trip", VIENNA_BODY) == ""


# --------------------------------------------------------------- save-time linking


def test_plan_saved_without_destinations_links_vienna_chain(client):
    note = _save(client, "Fun/Travel/Planned/Austria", "Vienna trip May 2027", VIENNA_BODY)
    e = edges()
    assert (note, VIE, "located_in") in e
    assert (VIE, AT, "part_of") in e and (AT, EU, "part_of") in e
    # Cafe Central / Stephansdom / IAD aren't places in the gazetteer — only Vienna is linked.
    assert {t for s, t, k in e if s == note and k == "located_in"} == {VIE}
    g = client.get("/graph").json()
    got = {(x["source"], x["target"], x["kind"]) for x in g["edges"]}
    assert (note, VIE, "located_in") in got


def test_plan_folder_only_links_country(client):
    note = _save(client, "Fun/Travel/Planned/Austria", "Spring ideas", "Some museums, some cake.")
    assert {t for s, t, k in edges("located_in") if s == note} == {AT}


def test_typed_destinations_still_win(client):
    note = _save(client, "Fun/Travel/Planned/Austria", "Vienna trip", VIENNA_BODY, fields={"destinations": "Graz, Austria"})
    assert {t for s, t, k in edges("located_in") if s == note} == {"place:europe/austria/graz"}


def test_non_travel_note_never_derived(client):
    note = _save(client, "Work/Notes", "Vienna conference", VIENNA_BODY)
    assert not any(s == note for s, _, _ in edges("located_in"))


def test_bucket_note_links_and_counts(client):
    note = _save(client, "Fun/Travel/Bucket List", "Northern lights", "In Tromsø, Norway.")
    located = {t for s, t, k in edges("located_in") if s == note}
    assert len(located) == 1 and next(iter(located)).startswith("place:europe/norway/")


def test_backfill_links_plans_without_destinations(client, tmp_path):
    import frontmatter

    d = tmp_path / "kb" / "fun" / "travel" / "planned" / "austria"
    d.mkdir(parents=True, exist_ok=True)
    (d / "old-vienna.md").write_text(frontmatter.dumps(frontmatter.Post("# Old Vienna plan\n\n" + VIENNA_BODY)), encoding="utf-8")
    note = "note:fun/travel/planned/austria/old-vienna"
    assert (note, VIE, "located_in") not in edges()
    dry = client.post("/kb/graph/backfill-places").json()
    assert dry["counts"]["plans"] >= 1 and (note, VIE, "located_in") not in edges()
    client.post("/kb/graph/backfill-places", params={"dry_run": "false"})
    assert (note, VIE, "located_in") in edges()
    assert client.post("/kb/graph/backfill-places", params={"dry_run": "false"}).json()["edges"] == 0


# --------------------------------------------------------------- drop proposal + bucket gate


def test_bucket_wish_proposal_gate():
    p = bucket_wish_proposal("Someday I want to see the northern lights in Tromsø, Norway")
    assert p["folder"] == "Fun/Travel/Bucket List" and p["title"] == "Northern lights in Tromsø, Norway"
    assert p["fields"]["destinations"] == "Tromsø, Norway"
    assert bucket_wish_proposal("Someday I want to learn piano") is None  # no place named
    assert bucket_wish_proposal("I want to visit Paris") is None  # no someday phrase: could be a plan


def _no_models(monkeypatch, parsed):
    monkeypatch.setattr(api_module, "parse_journal_dump", lambda *a, **k: parsed)
    monkeypatch.setattr(api_module, "maybe_structure_experience", lambda *a, **k: None)
    monkeypatch.setattr(api_module, "maybe_structure_person_mention", lambda *a, **k: None)


def test_typed_someday_wish_lands_in_bucket_list(client, monkeypatch):
    misfiled = KBEntryProposal(type="kb_entry", folder="Ideas", title="Northern lights", content="northern lights")
    todo = TodoEntry(type="todo", title="See the northern lights")
    _no_models(monkeypatch, [misfiled, todo])
    r = client.post("/drop", data={"text": "Someday I want to see the northern lights in Tromsø, Norway"}).json()
    kb = [e for e in r["entries"] if e["type"] == "kb_entry"]
    assert len(kb) == 1 and kb[0]["folder"] == "Fun/Travel/Bucket List"
    assert kb[0]["fields"]["destinations"] == "Tromsø, Norway"
    assert any(e["type"] == "todo" for e in r["entries"])  # other proposals kept
    assert not any(e["type"] == "experience_entry" for e in r["entries"])


def test_plain_typed_note_untouched(client, monkeypatch):
    plain = KBEntryProposal(type="kb_entry", folder="Ideas", title="App idea", content="An app for X")
    _no_models(monkeypatch, [plain])
    r = client.post("/drop", data={"text": "An app for X"}).json()
    assert r["entries"][0]["folder"] == "Ideas" and "fields" not in r["entries"][0]


def test_planned_drop_proposal_carries_destinations(client, monkeypatch):
    planned = KBEntryProposal(type="kb_entry", folder="Fun/Travel/Planned/Austria", title="Vienna trip", content=VIENNA_BODY)
    _no_models(monkeypatch, [planned])
    r = client.post("/drop", data={"text": VIENNA_BODY}).json()
    kb = [e for e in r["entries"] if e["type"] == "kb_entry"]
    assert kb[0]["fields"] == {"destinations": "Vienna, Austria"}
