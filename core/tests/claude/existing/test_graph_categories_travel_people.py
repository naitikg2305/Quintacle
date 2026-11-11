"""Graph linking for the owner's real use categories (2026-11-11), the
travel / journal / people slice of docs/testing/graph-linking-38-categories.md:
#1 Travel itinerary, #2 Journal, #11 DC restaurant experience, #12 Experience,
#13 Date, #14 Convo with Alfonso, #22 Journal & Lore, #35 People.

Each test performs the SAME save the app performs after review: the review
card's Save calls each entry's commit endpoint (frontend/lib/entries.ts
commitEntry), then POST /graph/event with every committed graph id
(linkBatchAsEvent), and — when the "save to journal" toggle is on — POST
/journal/{date} with the raw text first (frontend/app/kb/page.tsx). The
model-facing /drop step is skipped: its output is written here as the
proposal a correct model would make, so these tests measure the LINKING
code only, never a model. No model is called anywhere.

Expectations come from the spec, never from what the code happens to do.
A spec'd link the code does not produce stays asserted and is marked
`xfail(strict=True, reason="GAP: ...")` — when the gap is fixed the test
XPASSes, strict turns that into a failure, and the marker must come off.

Sandbox only: api_module.DATA_DIR → tmp_path. Registries are seeded first
(CLAUDE.md: entity-grounded), the way the owner's real store will be."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core import retrieval
from quintacle_core.graph import get_graph_store, neighborhood, reverse_lookup
from quintacle_core.graph_capture import DOCUMENTS_FOLDER, PLACE_EMERGENCE_THRESHOLD
from quintacle_core.place_graph import proposal_destinations

DAY = "2026-11-10"
VAULT_PREFIX = f"note:{DOCUMENTS_FOLDER}/"


@pytest.fixture(autouse=True)
def _reset_retrieval_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    _seed(c)
    return c


def _seed(c: TestClient) -> dict:
    """The owner's registries after seeding: people, a known restaurant, his
    DC residence. Returns the person profile ids."""
    ids = {}
    for name, category, how_met in [
        ("Arjun Mehta", "friend", "college roommate"),
        ("Alfonso Rivera", "friend", "work at Minfy"),
        ("Priya Shah", "dating", "Hinge"),
    ]:
        res = c.post("/people", json={"name": name, "category": category, "how_met": how_met})
        assert res.status_code == 200, res.text
        ids[name] = f"note:{res.json()['folder']}/profile"
    res = c.post(
        "/travel/experiences",
        json={"name": "Founding Farmers", "city": "Washington DC", "kind": "restaurant", "rating": "7/10"},
    )
    assert res.status_code == 200, res.text
    res = c.post("/home/residences", json={"name": "Dupont Apartment", "city": "Washington DC", "address": ""})
    assert res.status_code == 200, res.text
    return ids


def person_id(c: TestClient, name: str) -> str:
    people = c.get("/people").json()
    match = [p for p in people if p["name"] == name]
    assert match, f"{name} not seeded"
    return f"note:{match[0]['folder']}/profile"


def founding_farmers_id(c: TestClient) -> str:
    exp = [e for e in c.get("/travel/experiences").json() if e["name"] == "Founding Farmers"][0]
    return f"experience:{exp['folder']}/{exp['slug']}"


def edges(kind: str | None = None) -> set[tuple[str, str, str]]:
    return {
        (e["source_id"], e["target_id"], e["kind"])
        for e in get_graph_store().all()
        if kind is None or e["kind"] == kind
    }


def edges_from(node: str, kind: str | None = None) -> set[str]:
    return {t for s, t, k in edges(kind) if s == node}


def edges_touching(node: str) -> set[tuple[str, str, str]]:
    return {e for e in edges() if node in (e[0], e[1])}


def is_dc(node_id: str) -> bool:
    return node_id.endswith("/washington-dc")


def no_vault_edges() -> None:
    touching = {e for e in edges() if e[0].startswith(VAULT_PREFIX) or e[1].startswith(VAULT_PREFIX)}
    assert touching == set(), touching


# --- the Save step, as frontend/lib/entries.ts performs it -----------------


def save_journal(c: TestClient, day: str, text: str) -> None:
    res = c.post(f"/journal/{day}", content=text, headers={"content-type": "text/plain"})
    assert res.status_code == 200, res.text


def commit_note(c: TestClient, folder: str, title: str, content: str, links=None, fields=None) -> str:
    body = {"folder": folder, "title": title, "content": content, "links": links or []}
    if fields:
        body["fields"] = fields
    res = c.post("/kb/entries", json=body)
    assert res.status_code == 200, res.text
    return f"note:{res.json()['folder']}/{res.json()['slug']}"


def commit_experience(c: TestClient, **fields) -> str:
    body = {"kind": "restaurant", "links": [], **fields}
    res = c.post("/travel/experiences", json=body)
    assert res.status_code == 200, res.text
    return f"experience:{res.json()['folder']}/{res.json()['slug']}"


def commit_activity(c: TestClient, day: str, description: str, category: str = "social", hours: float = 2) -> str:
    res = c.post("/logs/activities", json={"date": day, "category": category, "description": description, "hours": hours})
    assert res.status_code == 200, res.text
    return f"activity:{res.json()['id']}"


def commit_food(c: TestClient, day: str, description: str, kcal: float = 700) -> str:
    res = c.post("/logs/food", json={"date": day, "meal_type": "lunch", "freeform_kcal": kcal, "notes": description})
    assert res.status_code == 200, res.text
    return f"food:{res.json()['id']}"


def link_event(c: TestClient, members: list[str], day: str) -> str | None:
    res = c.post("/graph/event", json={"members": members, "date": day})
    assert res.status_code == 200, res.text
    return res.json()["event_id"]


def mention_folder(c: TestClient, name: str) -> str:
    """api.py propose_drop files a known-person mention at
    f"{person['folder']}/Mentions", titled "<Full Name> — <date>"."""
    p = [p for p in c.get("/people").json() if p["name"] == name][0]
    return f"{p['folder']}/Mentions"


def create_vault_document(c: TestClient, name: str, notes: str) -> str:
    res = c.post("/documents", data={"name": name, "doc_type": "travel", "notes": notes})
    assert res.status_code == 200, res.text
    return f"{VAULT_PREFIX}{res.json()['slug']}"


# ============================================================ #1 Travel itinerary

CENTRAL_EUROPE_FOLDER = "Fun/Travel/Planned/Central Europe"
CENTRAL_EUROPE_TITLE = "Central Europe trip, May 2027"
CENTRAL_EUROPE_BODY = (
    "10 days, May 12-21 2027, by rail: Budapest, Vienna, Salzburg and Prague.\n\n"
    "Fly out of Washington Dulles to Vienna, connect to Budapest. Return Prague via Frankfurt.\n"
    "Arjun Mehta joins for the Vienna and Salzburg legs.\n\n"
    "Hotels: Hotel Moments (Budapest, 3 nights), Hotel Kaiserin Elisabeth (Vienna, 2), "
    "IMLAUER Palais Mirabell (Salzburg, 2), MOODs Charles Bridge (Prague, 2)."
)


def _save_trip_plan(c: TestClient) -> str:
    """The drop proposes a kb_entry for Planned/<Trip> carrying
    fields.destinations (place_graph.proposal_destinations); Save posts it."""
    dest = proposal_destinations(CENTRAL_EUROPE_FOLDER, CENTRAL_EUROPE_TITLE, CENTRAL_EUROPE_BODY)
    return commit_note(
        c, CENTRAL_EUROPE_FOLDER, CENTRAL_EUROPE_TITLE, CENTRAL_EUROPE_BODY, fields={"destinations": dest} if dest else None
    )


def test_01_trip_plan_links_each_city_to_country_to_continent(client):
    plan = _save_trip_plan(client)

    cities = {
        "place:europe/hungary/budapest": "place:europe/hungary",
        "place:europe/austria/vienna": "place:europe/austria",
        "place:europe/austria/salzburg": "place:europe/austria",
        "place:europe/czechia/prague": "place:europe/czechia",
    }
    located = edges_from(plan, "located_in")
    assert set(cities) <= located, located
    part_of = edges("part_of")
    for city, country in cities.items():
        assert (city, country, "part_of") in part_of
        assert (country, "place:europe", "part_of") in part_of


def test_01_trip_plan_links_the_people_named_in_it(client):
    plan = _save_trip_plan(client)
    assert (plan, person_id(client, "Arjun Mehta"), "mentions_person") in edges()


def test_01_trip_plan_invents_nothing(client):
    """✗: no link to a person who isn't named, and the departure point
    ("out of Washington Dulles") is not a destination."""
    plan = _save_trip_plan(client)
    out = edges_from(plan)
    assert person_id(client, "Alfonso Rivera") not in out
    assert person_id(client, "Priya Shah") not in out
    assert not any(is_dc(t) or "washington" in t for t in out), out
    assert not any(t.startswith("place:") and "/united-states" in t for t in out), out
    no_vault_edges()


@pytest.mark.xfail(
    strict=True,
    reason="GAP: Document Vault entries are keyword-linked like any item "
    "(documents/api.py create_document -> safe_entry_graph_links; graph_capture._item_description_sources "
    "backfills them too) — spec #1/#10 says the vault is never in the graph",
)
def test_01_flight_ticket_in_document_vault_stays_out_of_the_graph(client):
    """The trip's flight ticket PDF is filed in the Document Vault (same drop
    session). Its notes name the traveler and the city — still ✗ any edge."""
    plan = _save_trip_plan(client)
    doc = create_vault_document(
        client, "Flight ticket IAD-VIE May 2027", "Austrian Airlines, Arjun Mehta and me, IAD to Vienna, Founding Farmers lunch before."
    )
    assert edges_touching(doc) == set()
    assert not any(doc in e for e in edges_touching(plan))
    no_vault_edges()


# ============================================================ #2 Journal

JOURNAL_TEXT = (
    "Lunch with Arjun Mehta at Founding Farmers, he's moving to Austin next month. "
    "Afternoon was heads-down on Quintacle. Gym after: bench 3x8 at 155."
)


def test_02_journal_day_links_people_and_experiences_named(client):
    save_journal(client, DAY, JOURNAL_TEXT)
    day = f"journal:{DAY}"
    assert (day, person_id(client, "Arjun Mehta"), "mentions_person") in edges()
    assert (day, founding_farmers_id(client), "at_location") in edges()
    # ✗ nobody/nothing that isn't named
    out = edges_from(day)
    assert person_id(client, "Alfonso Rivera") not in out
    assert person_id(client, "Priya Shah") not in out
    no_vault_edges()


def test_02_records_parsed_from_one_journal_are_one_event(client):
    """Journal page Save: the raw text to the day, each parsed record through
    its commit endpoint, then one /graph/event over every committed id."""
    save_journal(client, DAY, JOURNAL_TEXT)
    members = [
        commit_activity(client, DAY, "Lunch with Arjun Mehta at Founding Farmers", "social", 1.5),
        commit_food(client, DAY, "Founding Farmers lunch"),
        commit_activity(client, DAY, "Worked on Quintacle", "productivity", 4),
    ]
    event = link_event(client, members, DAY)
    assert event is not None
    part_of = edges("part_of")
    for m in members:
        assert (m, event, "part_of") in part_of
    assert len({t for s, t, k in part_of if s in members}) == 1  # ONE event, not several
    assert (event, f"journal:{DAY}", "on_day") in edges()


def test_02_journal_links_a_place_once_it_has_emerged(client):
    """A city mentioned across PLACE_EMERGENCE_THRESHOLD sources is a place;
    the journal naming it then links to it."""
    assert PLACE_EMERGENCE_THRESHOLD == 3
    save_journal(client, "2026-11-01", "Walked around Washington DC all day.")
    save_journal(client, "2026-11-02", "Another Washington DC museum day.")
    save_journal(client, DAY, "Back home in Washington DC, quiet evening.")
    targets = edges_from(f"journal:{DAY}", "at_location")
    assert any(is_dc(t) for t in targets), targets


def test_02_journal_links_a_known_city_named_once(client):
    # Vienna is known from exactly one experience (its city field): one source,
    # so with this journal it's 2 < PLACE_EMERGENCE_THRESHOLD.
    commit_experience(client, name="Cafe Central", city="Vienna", kind="restaurant", visited_date="2026-05-14")
    assert any(t.endswith("/vienna") for s, t, k in edges("located_in"))  # the place node exists
    save_journal(client, "2026-11-03", "Still thinking about the Sachertorte in Vienna.")
    targets = edges_from("journal:2026-11-03")
    assert any(t.endswith("/vienna") for t in targets), targets


def test_02_journal_first_name_only_mention_links_the_person(client):
    save_journal(client, DAY, "Grabbed coffee with Arjun before work.")
    assert (f"journal:{DAY}", person_id(client, "Arjun Mehta"), "mentions_person") in edges()


# ============================================================ #11 DC restaurant experience

DC_DROP = "Dinner at Le Diplomate in DC with Arjun Mehta. Steak frites were great, 9/10, would go back."


def _save_dc_dinner(c: TestClient) -> dict:
    """The drop proposes: experience_entry (city stated as DC, links carry
    the known person's name — api.py propose_drop's exp_links) + a mention
    kb_entry under People/Arjun Mehta/Mentions. Save: journal toggle on
    (text is long enough), both commits, one event."""
    save_journal(c, DAY, DC_DROP)
    exp = commit_experience(
        c,
        name="Le Diplomate",
        city="Washington DC",
        kind="restaurant",
        rating="9/10",
        would_return=True,
        visited_date=DAY,
        notes="Steak frites were great.",
        links=["Arjun Mehta"],
    )
    mention = commit_note(
        c,
        mention_folder(c, "Arjun Mehta"),
        f"Arjun Mehta — {DAY}",
        "Had dinner with Arjun at Le Diplomate.",
        links=["Le Diplomate"],
    )
    event = link_event(c, [exp, mention], DAY)
    return {"exp": exp, "mention": mention, "event": event}


def test_11_dc_experience_links_to_washington_dc(client):
    saved = _save_dc_dinner(client)
    located = edges_from(saved["exp"], "located_in")
    assert len(located) == 1 and is_dc(next(iter(located))), located


def test_11_dc_experience_links_the_person(client):
    saved = _save_dc_dinner(client)
    arjun = person_id(client, "Arjun Mehta")
    assert (saved["exp"], arjun, "mentions_person") in edges()
    assert (saved["mention"], arjun, "mentions_person") in edges()
    assert (saved["mention"], saved["exp"], "at_location") in edges()


def test_11_dc_experience_reaches_its_day(client):
    saved = _save_dc_dinner(client)
    assert (saved["exp"], saved["event"], "part_of") in edges()
    assert (saved["event"], f"journal:{DAY}", "on_day") in edges()
    assert f"journal:{DAY}" in neighborhood(saved["exp"], 2)["nodes"]


def test_11_dc_experience_invents_no_city_or_person(client):
    saved = _save_dc_dinner(client)
    out = edges_from(saved["exp"])
    assert not any(t.startswith("place:") and not is_dc(t) for t in out), out
    assert person_id(client, "Alfonso Rivera") not in out
    assert person_id(client, "Priya Shah") not in out
    no_vault_edges()


def test_11_experience_saved_alone_still_reaches_its_existing_day(client):
    save_journal(client, DAY, "Quiet day.")  # the day exists
    exp = commit_experience(client, name="Le Diplomate", city="Washington DC", visited_date=DAY, rating="9/10")
    assert f"journal:{DAY}" in neighborhood(exp, 2)["nodes"]


# ============================================================ #12 Experience (generic)


def test_12_experience_without_a_city_links_no_place(client):
    exp = commit_experience(
        client,
        name="Sunset kayak paddle",
        city="",
        kind="activity",
        rating="8/10",
        visited_date=DAY,
        notes="Kayaked with Arjun Mehta at sunset.",
        links=["Arjun Mehta"],
    )
    out = edges_from(exp)
    assert not any(t.startswith("place:") or t.startswith("note:places/") for t in out), out
    assert edges_from(exp, "located_in") == set()
    assert (exp, person_id(client, "Arjun Mehta"), "mentions_person") in edges()
    assert person_id(client, "Alfonso Rivera") not in out
    no_vault_edges()


def test_12_experience_with_a_partner_entry_reaches_its_day(client):
    save_journal(client, DAY, "Sunset kayak paddle with Arjun Mehta.")
    exp = commit_experience(client, name="Sunset kayak paddle", city="", kind="activity", visited_date=DAY, links=["Arjun Mehta"])
    mention = commit_note(client, mention_folder(client, "Arjun Mehta"), f"Arjun Mehta — {DAY}", "Kayaked together.")
    event = link_event(client, [exp, mention], DAY)
    assert (exp, event, "part_of") in edges()
    assert (event, f"journal:{DAY}", "on_day") in edges()


# ============================================================ #13 Date

DATE_DROP = "Date night with Priya Shah at Le Diplomate in DC. Really good conversation, want to see her again."


def _save_date(c: TestClient) -> dict:
    save_journal(c, DAY, DATE_DROP)
    activity = commit_activity(c, DAY, "Date with Priya Shah at Le Diplomate", "social", 3)
    exp = commit_experience(
        c, name="Le Diplomate", city="Washington DC", rating="9/10", visited_date=DAY, notes="Date night.", links=["Priya Shah"]
    )
    mention = commit_note(
        c, mention_folder(c, "Priya Shah"), f"Priya Shah — {DAY}", "Date at Le Diplomate, good conversation.", links=["Le Diplomate"]
    )
    event = link_event(c, [activity, exp, mention], DAY)
    return {"activity": activity, "exp": exp, "mention": mention, "event": event}


def test_13_date_links_the_person(client):
    saved = _save_date(client)
    priya = person_id(client, "Priya Shah")
    assert (saved["mention"], priya, "mentions_person") in edges()
    assert (saved["exp"], priya, "mentions_person") in edges()
    # the activity's prose links from its day (graph_capture's activity rule)
    assert (f"journal:{DAY}", priya, "mentions_person") in edges()


def test_13_date_activity_experience_and_mention_are_one_event(client):
    saved = _save_date(client)
    assert saved["event"] is not None
    for key in ("activity", "exp", "mention"):
        assert (saved[key], saved["event"], "part_of") in edges()
    assert (saved["event"], f"journal:{DAY}", "on_day") in edges()


def test_13_date_links_nobody_else(client):
    saved = _save_date(client)
    others = {person_id(client, "Arjun Mehta"), person_id(client, "Alfonso Rivera")}
    for key in ("exp", "mention"):
        assert not (edges_from(saved[key]) & others)
    assert not (edges_from(f"journal:{DAY}") & others)
    no_vault_edges()


# ============================================================ #14 Convo with Alfonso


def test_14_mention_note_links_alfonsos_profile(client):
    """The drop matched a known person (first name is enough for the drop's
    detector) and filed the mention under his folder with his full name as
    the title — the title carries the link."""
    alfonso = person_id(client, "Alfonso Rivera")
    note = commit_note(
        client,
        mention_folder(client, "Alfonso Rivera"),
        f"Alfonso Rivera — {DAY}",
        "Alfonso said Minfy is restructuring the sales team; he might move to Lisbon.",
    )
    assert note.startswith(f"note:{alfonso.removeprefix('note:').removesuffix('/profile')}/mentions/")
    assert (note, alfonso, "mentions_person") in edges()
    assert alfonso in {s for s, t, k in edges()} | {t for s, t, k in edges()}
    assert any(e["source_id"] == note for e in reverse_lookup(alfonso))
    out = edges_from(note)
    assert person_id(client, "Arjun Mehta") not in out
    no_vault_edges()


def test_14_first_name_only_convo_links_the_only_alfonso(client):
    save_journal(client, DAY, "Long convo with Alfonso about the Minfy reorg.")
    assert (f"journal:{DAY}", person_id(client, "Alfonso Rivera"), "mentions_person") in edges()


def test_14_retitled_mention_note_still_links_by_its_folder(client):
    # 2026-11-11: passes via the unique-first-name alias ("Alfonso" in the
    # title), NOT via the folder — the folder rule itself is still the gap
    # pinned by the test below.
    note = commit_note(
        client, mention_folder(client, "Alfonso Rivera"), "Convo with Alfonso", "Talked about the Minfy reorg."
    )
    assert (note, person_id(client, "Alfonso Rivera"), "mentions_person") in edges()


def test_14_mention_note_naming_nobody_still_links_by_its_folder(client):
    note = commit_note(client, mention_folder(client, "Alfonso Rivera"), "Minfy reorg chat", "Talked about the reorg.")
    assert (note, person_id(client, "Alfonso Rivera"), "mentions_person") in edges()


# ============================================================ #22 Journal & Lore

LORE_FOLDER = "Personal/Lore"  # assumed home for lore notes; no Lore folder exists in the taxonomy yet


def test_22_journal_and_lore_note_link_people_and_places_named(client):
    save_journal(client, DAY, "Told Priya Shah the story of how Arjun Mehta and I got lost near Founding Farmers.")
    lore = commit_note(
        client,
        LORE_FOLDER,
        "The Founding Farmers detour",
        "Freshman year Arjun Mehta and I walked 40 minutes the wrong way looking for Founding Farmers.",
    )
    for src in (f"journal:{DAY}", lore):
        assert (src, person_id(client, "Arjun Mehta"), "mentions_person") in edges()
        assert (src, founding_farmers_id(client), "at_location") in edges()
    assert (f"journal:{DAY}", person_id(client, "Priya Shah"), "mentions_person") in edges()
    assert person_id(client, "Priya Shah") not in edges_from(lore)
    assert person_id(client, "Alfonso Rivera") not in edges_from(lore)
    no_vault_edges()


def test_22_lore_note_links_a_known_city_named(client):
    _save_trip_plan(client)  # Vienna is now a place node
    lore = commit_note(client, LORE_FOLDER, "Grandpa's Vienna story", "Grandpa lived in Vienna for a year in 1971.")
    targets = edges_from(lore)
    assert any(t.endswith("/vienna") for t in targets), targets


# ============================================================ #35 People


def test_35_person_backlinks_content_saved_after_them(client):
    arjun = person_id(client, "Arjun Mehta")
    save_journal(client, DAY, "Arjun Mehta came over for dinner.")
    note = commit_note(client, "Personal/Notes", "Gift ideas", "Arjun Mehta wants a pour-over kettle.")
    exp = commit_experience(client, name="Le Diplomate", city="Washington DC", notes="With Arjun Mehta.", links=["Arjun Mehta"])
    sources = {e["source_id"] for e in reverse_lookup(arjun) if e["kind"] == "mentions_person"}
    assert {f"journal:{DAY}", note, exp} <= sources
    no_vault_edges()


def test_35_new_person_backlinks_existing_content_after_backfill(tmp_path, monkeypatch):
    """Content naming Neha Kapoor exists BEFORE her profile; the mention
    backfill (run at app startup) back-links all of it."""
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    _seed(c)
    save_journal(c, DAY, "Met Neha Kapoor at the climbing gym.")
    note = commit_note(c, "Personal/Notes", "Climbing partners", "Neha Kapoor belays on Thursdays.")
    exp = commit_experience(c, name="Le Diplomate", city="Washington DC", notes="Dinner with Neha Kapoor.")
    res = c.post("/people", json={"name": "Neha Kapoor", "category": "friend", "how_met": "climbing gym"})
    neha = f"note:{res.json()['folder']}/profile"

    retrieval._index = None
    TestClient(api_module.create_app())  # restart → run_graph_capture_backfill
    sources = {e["source_id"] for e in reverse_lookup(neha) if e["kind"] == "mentions_person"}
    assert {f"journal:{DAY}", note, exp} <= sources


def test_35_new_person_backlinks_existing_content_immediately(client):
    save_journal(client, DAY, "Met Neha Kapoor at the climbing gym.")
    note = commit_note(client, "Personal/Notes", "Climbing partners", "Neha Kapoor belays on Thursdays.")
    res = client.post("/people", json={"name": "Neha Kapoor", "category": "friend"})
    neha = f"note:{res.json()['folder']}/profile"
    sources = {e["source_id"] for e in reverse_lookup(neha)}
    assert {f"journal:{DAY}", note} <= sources


def test_35_person_backlinks_never_include_unrelated_people_content(client):
    save_journal(client, DAY, "Arjun Mehta came over for dinner.")
    sources = {e["source_id"] for e in reverse_lookup(person_id(client, "Alfonso Rivera"))}
    assert f"journal:{DAY}" not in sources


@pytest.mark.xfail(
    strict=True,
    reason="GAP: a Document Vault entry naming a person becomes one of their back-links "
    "(documents/api.py create_document -> safe_entry_graph_links) — spec: vault is never in the graph",
)
def test_35_person_backlinks_never_include_the_vault(client):
    create_vault_document(client, "Apartment lease", "Lease co-signed with Arjun Mehta.")
    sources = {e["source_id"] for e in reverse_lookup(person_id(client, "Arjun Mehta"))}
    assert not any(s.startswith(VAULT_PREFIX) for s in sources), sources
    no_vault_edges()
