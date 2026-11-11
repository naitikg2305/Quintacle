"""DRAFT 2026-11-11 — expectations written by Claude from docs/testing/graph-linking-38-categories.md; NOT confirmed by the owner. Do not treat a failure as a product bug until he confirms.

Live end-to-end drafts for categories #1 Travel itinerary, #2 Journal,
#11 DC restaurant experience, #12 Experience, #13 Date, #14 Convo with
Alfonso, #22 Journal & Lore, #35 People.

Each test: a realistic input → POST /drop with the REAL local models
(tests.claude.harness.make_client, provider=local, cloud blocked) → the Save
step exactly as frontend/lib/entries.ts commitDropEntries does it (optional
journal append, one commit per proposed entry, then POST /graph/event over
the committed ids) → assert where it was filed and the spec'd graph links.

Sandbox only: make_client writes to a pytest tmp dir; ~/.quintacle is never
touched. The trip-plan PDF is READ from the owner's testing folder, never
written. Skipped unless QUINTACLE_USER_DRAFTS=1 (and Ollama + the parse
model are up). Run:

    cd core && QUINTACLE_USER_DRAFTS=1 .venv/bin/python -m pytest tests/user/test_draft_travel_people.py -q

The deterministic half of these expectations (same saves, models faked)
lives in tests/claude/existing/test_graph_categories_travel_people.py, with
the known code gaps marked strict-xfail there."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.claude.harness import drop, first, missing_requirements, make_client, types

pytestmark = pytest.mark.skipif(os.environ.get("QUINTACLE_USER_DRAFTS") != "1", reason="draft: owner hasn't confirmed")

TESTING = Path.home() / "Desktop" / "Quintacle Product Testing, files and commands"
CENTRAL_EUROPE_PDF = TESTING / "Travel itinerary" / "Central Europe" / "Austria_drop.pdf"
DAY = "2026-11-10"
VAULT_PREFIX = "note:organisation/document-vault/"


# ------------------------------------------------------------------ setup


@pytest.fixture
def client(tmp_path):
    """A fresh seeded sandbox per test (graph assertions need a clean edge
    table). Seeded like the owner's store will be — CLAUDE.md: entity-grounded."""
    reason = missing_requirements()
    if reason:
        pytest.skip(reason)
    c = make_client(tmp_path)
    for name, category, how_met in [
        ("Arjun Mehta", "friend", "college roommate"),
        ("Alfonso Rivera", "friend", "work at Minfy"),
        ("Priya Shah", "dating", "Hinge"),
    ]:
        assert c.post("/people", json={"name": name, "category": category, "how_met": how_met}).status_code == 200
    assert c.post(
        "/travel/experiences",
        json={"name": "Founding Farmers", "city": "Washington DC", "kind": "restaurant", "rating": "7/10"},
    ).status_code == 200
    assert c.post("/home/residences", json={"name": "Dupont Apartment", "city": "Washington DC", "address": ""}).status_code == 200
    for folder, title, content in [
        ("Fun/Travel/Planned/Japan", "Tokyo plan", "Tokyo, Japan. Spring 2027."),
        ("Fun/Travel/Bucket List", "Patagonia", "Hiking Torres del Paine."),
        ("Software Engineering/Projects", "Quintacle", "Local-first personal life OS."),
    ]:
        assert c.post("/kb/entries", json={"folder": folder, "title": title, "content": content}).status_code == 200
    assert c.post("/logs/meals", json={"name": "Chicken rice bowl", "kcal": 650, "protein_g": 45, "carbs_g": 70, "fat_g": 15}).status_code == 200
    assert c.post("/logs/routines", json={"name": "Push day", "exercises": ["Bench press", "Overhead press", "Dips"]}).status_code == 200
    return c


def person_id(c, name: str) -> str:
    p = [p for p in c.get("/people").json() if p["name"] == name]
    assert p, f"{name} not in people"
    return f"note:{p[0]['folder']}/profile"


def experience_id(c, name: str) -> str:
    e = [e for e in c.get("/travel/experiences").json() if e["name"].lower() == name.lower()]
    assert e, f"no experience named {name!r}"
    return f"experience:{e[0]['folder']}/{e[0]['slug']}"


def all_edges(c) -> set[tuple[str, str, str]]:
    from quintacle_core.graph import get_graph_store

    return {(e["source_id"], e["target_id"], e["kind"]) for e in get_graph_store().all()}


def out_of(c, node: str, kind: str | None = None) -> set[str]:
    return {t for s, t, k in all_edges(c) if s == node and (kind is None or k == kind)}


def assert_no_vault_edges(c) -> None:
    bad = {e for e in all_edges(c) if e[0].startswith(VAULT_PREFIX) or e[1].startswith(VAULT_PREFIX)}
    assert not bad, f"vault in the graph: {bad}"


def slug_folder(folder: str) -> str:
    from quintacle_core.markdown_paths import slugify

    return "/".join(slugify(s) for s in (folder or "").split("/") if s.strip())


# ------------------------------------------------------------------ the Save step


def _commit(c, day: str, e: dict, file: tuple[str, bytes, str] | None) -> str | None:
    """frontend/lib/entries.ts commitEntry + graphIdFor, for the entry types
    these categories produce. Returns the committed graph id (None when the
    type has no graph id)."""
    t = e["type"]
    d = e.get("entry_date") or day
    if t == "kb_entry":
        if file is not None:
            form = {"folder": e["folder"], "title": e["title"], "content": e["content"], "links": ",".join(e.get("links") or [])}
            if e.get("fields"):
                form["fields"] = json.dumps(e["fields"])
            r = c.post("/kb/entries/with-asset", data=form, files={"files": file})
        else:
            body = {k: e.get(k) for k in ("folder", "title", "content", "links", "fields")}
            body["private"] = bool(e.get("private"))
            r = c.post("/kb/entries", json={k: v for k, v in body.items() if v is not None})
        assert r.status_code == 200, r.text
        return f"note:{r.json()['folder']}/{r.json()['slug']}"
    if t == "experience_entry":
        body = {
            "name": e["suggested_name"], "city": e.get("city") or "", "kind": e.get("kind") or "other",
            "rating": e.get("rating") or "", "would_return": e.get("would_return"),
            "visited_date": e.get("visited_date"), "notes": e.get("notes") or "", "links": e.get("links") or [],
        }
        r = c.post("/travel/experiences", json=body)
        assert r.status_code == 200, r.text
        return f"experience:{r.json()['folder']}/{r.json()['slug']}"
    if t == "person_entry":
        body = {k: e.get(k) for k in ("category", "how_met", "met_date", "notes")}
        r = c.post("/people", json={"name": e["suggested_name"], **body})
        assert r.status_code == 200, r.text
        return f"note:{r.json()['folder']}/profile"
    if t == "activity":
        r = c.post("/logs/activities", json={"date": d, "category": e["category"], "description": e["description"], "hours": e.get("hours") or 0})
        assert r.status_code == 200, r.text
        return f"activity:{r.json()['id']}"
    if t == "food":
        body = {"date": d, "meal_type": e.get("meal_type") or "lunch", "notes": e.get("description") or ""}
        body.update({"meal_id": e["meal_id"]} if e.get("meal_id") else {"freeform_kcal": e.get("estimated_kcal") or 0})
        r = c.post("/logs/food", json=body)
        assert r.status_code == 200, r.text
        return f"food:{r.json()['id']}"
    if t == "exercise":
        r = c.post("/logs/exercise", json={"date": d, "exercise_name": e["exercise_name"], "sets": e.get("sets") or [], "notes": e.get("notes") or ""})
        assert r.status_code == 200, r.text
        return f"exercise:{r.json()['id']}"
    if t == "finance":
        r = c.post("/logs/expenses", json={"date": d, "amount": e["amount"], "merchant": e.get("merchant") or "", "category": e.get("category") or "", "notes": e.get("notes") or "", "kind": e.get("kind") or "regular"})
        assert r.status_code == 200, r.text
        return f"expense:{r.json()['id']}"
    if t == "todo":
        r = c.post("/schedule/todos", json={k: e.get(k) for k in ("title", "due_date", "start_time", "end_time", "priority")})
        assert r.status_code == 200, r.text
        return f"todo:{r.json()['id']}"
    pytest.fail(f"draft Save helper doesn't commit {t!r} yet — proposal was {json.dumps(e)[:300]}")


def save_all(c, result: dict, *, day: str = DAY, journal_text: str | None = None, file=None) -> dict:
    """Drop page Save: journal append (if toggled), commit every proposal,
    one /graph/event over the committed ids. Returns {"ids": [...per entry],
    "event": event_id|None}."""
    if journal_text:
        r = c.post(f"/journal/{day}", content=journal_text, headers={"content-type": "text/plain"})
        assert r.status_code == 200, r.text
    ids = [_commit(c, day, e, file if e["type"] == "kb_entry" else None) for e in result.get("entries", [])]
    real = [i for i in ids if i]
    event = None
    if len(real) >= 2:
        r = c.post("/graph/event", json={"members": real, "date": day})
        assert r.status_code == 200, r.text
        event = r.json()["event_id"]
    return {"ids": ids, "event": event}


def ids_of(result: dict, saved: dict, entry_type: str) -> list[str]:
    return [i for e, i in zip(result["entries"], saved["ids"]) if e["type"] == entry_type and i]


# ============================================================ #1 Travel itinerary


def test_01_central_europe_pdf_files_as_a_planned_trip_with_the_place_chain(client):
    """#1. Dropping the owner's Central Europe planning PDF (Budapest /
    Vienna / Salzburg / Prague, May 2027) should:
    - be ONE kb_entry note under Fun/Travel/Planned/<something> — not a
      Document Vault entry, not an experience (nothing was visited yet);
    - after Save, the note is `located_in` Budapest, Vienna, Salzburg and
      Prague, each chained `part_of` its country (Hungary / Austria /
      Czechia) and then Europe;
    - nobody is named in the PDF, so NO mentions_person edges;
    - Washington Dulles is the departure point, not a destination: no
      located_in to Washington;
    - nothing touches the Document Vault."""
    if not CENTRAL_EUROPE_PDF.exists():
        pytest.skip(f"testing file missing: {CENTRAL_EUROPE_PDF}")
    data = CENTRAL_EUROPE_PDF.read_bytes()  # read-only
    r = drop(client, data=data, filename=CENTRAL_EUROPE_PDF.name, provider="local")
    assert "document_entry" not in types(r), types(r)
    assert "experience_entry" not in types(r), types(r)
    note = first(r, "kb_entry")
    assert slug_folder(note["folder"]).startswith("fun/travel/planned/"), note["folder"]

    saved = save_all(client, r, file=(CENTRAL_EUROPE_PDF.name, data, "application/pdf"))
    plan = ids_of(r, saved, "kb_entry")[0]
    located = out_of(client, plan, "located_in")
    for city in ("budapest", "vienna", "salzburg", "prague"):
        assert any(t.endswith("/" + city) for t in located), f"{city} missing from {located}"
    part_of = {(s, t) for s, t, k in all_edges(client) if k == "part_of"}
    assert ("place:europe/austria/vienna", "place:europe/austria") in part_of
    assert ("place:europe/hungary/budapest", "place:europe/hungary") in part_of
    assert ("place:europe/czechia/prague", "place:europe/czechia") in part_of
    assert ("place:europe/austria", "place:europe") in part_of
    assert not out_of(client, plan, "mentions_person")
    assert not any("washington" in t for t in located), located
    assert_no_vault_edges(client)


def test_01_typed_trip_plan_links_the_people_named(client):
    """#1. A typed plan that names a travel companion: filed under
    Fun/Travel/Planned/, located_in Lisbon and Porto (→ Portugal → Europe),
    and `mentions_person` → Arjun Mehta. Not → Alfonso / Priya."""
    text = (
        "note: Lisbon + Porto trip plan, June 2027. 7 days with Arjun Mehta. Fly IAD to Lisbon Jun 3, "
        "4 nights Memmo Alfama, train to Porto, 3 nights PortoBay Flores, fly home from Porto Jun 10. Nothing booked."
    )
    r = drop(client, text=text, provider="local")
    note = first(r, "kb_entry")
    assert slug_folder(note["folder"]).startswith("fun/travel/planned/"), note["folder"]
    saved = save_all(client, r)
    plan = ids_of(r, saved, "kb_entry")[0]
    located = out_of(client, plan, "located_in")
    assert any(t.endswith("/lisbon") for t in located), located
    assert any(t.endswith("/porto") for t in located), located
    out = out_of(client, plan)
    assert person_id(client, "Arjun Mehta") in out, out
    assert person_id(client, "Alfonso Rivera") not in out
    assert person_id(client, "Priya Shah") not in out
    assert_no_vault_edges(client)


# ============================================================ #2 Journal

JOURNAL_DUMP = (
    "Lunch with Arjun Mehta at Founding Farmers, had the chicken rice bowl. He's moving to Austin next month. "
    "Spent the afternoon on Quintacle, about 4 hours. Push day at the gym in the evening, bench 3x8 at 155."
)


def test_02_journal_dump_links_people_places_and_is_one_event(client):
    """#2. The nightly dump, saved with "save to journal" on:
    - the journal day for 2026-11-10 → mentions_person Arjun Mehta and
      → at_location the Founding Farmers experience;
    - parsed records (food: the known Chicken rice bowl meal, the work
      activity, the bench sets) are all `part_of` ONE event, and that event
      is `on_day` the journal day;
    - not → Alfonso or Priya (not named)."""
    r = drop(client, text=JOURNAL_DUMP, provider="local")
    saved = save_all(client, r, journal_text=JOURNAL_DUMP)
    day = f"journal:{DAY}"
    assert person_id(client, "Arjun Mehta") in out_of(client, day, "mentions_person")
    assert experience_id(client, "Founding Farmers") in out_of(client, day, "at_location")
    assert saved["event"] is not None, types(r)
    members = [i for i in saved["ids"] if i]
    assert len(members) >= 2, types(r)
    for m in members:
        assert (m, saved["event"], "part_of") in all_edges(client), m
    assert (saved["event"], day, "on_day") in all_edges(client)
    others = {person_id(client, "Alfonso Rivera"), person_id(client, "Priya Shah")}
    assert not (out_of(client, day) & others)
    assert_no_vault_edges(client)


def test_02_first_name_only_journal_still_links_the_person(client):
    """#2 (known gap today). "coffee with Arjun" — Arjun Mehta is the only
    Arjun, so the journal day should → mentions_person Arjun Mehta even
    without his surname."""
    text = "Grabbed coffee with Arjun before work, he's stressed about the Austin move."
    r = drop(client, text=text, provider="local")
    save_all(client, r, journal_text=text)
    assert person_id(client, "Arjun Mehta") in out_of(client, f"journal:{DAY}", "mentions_person")


# ============================================================ #11 DC restaurant experience

DC_DINNER = "Dinner at Le Diplomate in DC with Arjun Mehta. Steak frites were great, 9/10, would go back."


def test_11_dc_restaurant_experience_links_dc_person_and_day(client):
    """#11. The drop proposes an experience (Le Diplomate, restaurant, city
    Washington DC — stated as "DC"). After Save (journal toggle on):
    - the experience is `located_in` a Washington DC place node and no
      other city (✗ invented city);
    - → mentions_person Arjun Mehta (from the experience and/or a Mentions
      note under his folder);
    - reaches the day: experience part_of event, event on_day 2026-11-10;
    - not → Alfonso / Priya."""
    r = drop(client, text=DC_DINNER, provider="local")
    exp_e = first(r, "experience_entry")
    assert "le diplomate" in exp_e["suggested_name"].lower(), exp_e
    assert "dc" in (exp_e.get("city") or "").lower() or "washington" in (exp_e.get("city") or "").lower(), exp_e
    saved = save_all(client, r, journal_text=DC_DINNER)
    exp = ids_of(r, saved, "experience_entry")[0]
    located = out_of(client, exp, "located_in")
    assert len(located) == 1 and ("washington" in next(iter(located)) or next(iter(located)).endswith("/dc")), located
    arjun = person_id(client, "Arjun Mehta")
    sources = {s for s, t, k in all_edges(client) if t == arjun and k == "mentions_person"}
    assert exp in sources or any(s.startswith("note:people/arjun-mehta/mentions/") for s in sources), sources
    assert saved["event"] is not None
    assert (exp, saved["event"], "part_of") in all_edges(client)
    assert (saved["event"], f"journal:{DAY}", "on_day") in all_edges(client)
    others = {person_id(client, "Alfonso Rivera"), person_id(client, "Priya Shah")}
    assert not (out_of(client, exp) & others)
    assert_no_vault_edges(client)


# ============================================================ #12 Experience (generic)


def test_12_experience_without_a_city_gets_no_place(client):
    """#12. "Went on a sunset kayak paddle with Arjun Mehta, 8/10" names no
    city: the experience is proposed with an EMPTY city and, after Save,
    has no located_in edge at all (✗ invented city). → mentions_person
    Arjun Mehta."""
    text = "Went on a sunset kayak paddle with Arjun Mehta yesterday, 8/10, calm water."
    r = drop(client, text=text, provider="local")
    exp_e = first(r, "experience_entry")
    assert not (exp_e.get("city") or "").strip(), f"invented city {exp_e.get('city')!r}"
    saved = save_all(client, r, journal_text=text)
    exp = ids_of(r, saved, "experience_entry")[0]
    assert not out_of(client, exp, "located_in")
    arjun = person_id(client, "Arjun Mehta")
    sources = {s for s, t, k in all_edges(client) if t == arjun and k == "mentions_person"}
    assert exp in sources or any(s.startswith("note:people/arjun-mehta/mentions/") for s in sources), sources


# ============================================================ #13 Date


def test_13_date_is_activity_experience_and_mention_in_one_event(client):
    """#13. "Date night with Priya Shah at Le Diplomate in DC..." should
    produce an activity (social), an experience (Le Diplomate, Washington
    DC) and a Mentions note under People/Priya Shah. After Save:
    - the Mentions note → mentions_person Priya Shah;
    - activity, experience and mention are all `part_of` ONE event;
    - nobody else is linked."""
    text = "Date night with Priya Shah at Le Diplomate in DC, 3 hours, really good conversation. Want to see her again."
    r = drop(client, text=text, provider="local")
    for t in ("activity", "experience_entry", "kb_entry"):
        assert t in types(r), types(r)
    mention = [e for e in r["entries"] if e["type"] == "kb_entry" and "/mentions" in slug_folder(e["folder"])]
    assert mention and slug_folder(mention[0]["folder"]).startswith("people/priya-shah/mentions"), r["entries"]
    saved = save_all(client, r, journal_text=text)
    priya = person_id(client, "Priya Shah")
    mention_ids = [i for i in ids_of(r, saved, "kb_entry") if "/mentions/" in i]
    assert (mention_ids[0], priya, "mentions_person") in all_edges(client)
    assert saved["event"] is not None
    for t in ("activity", "experience_entry"):
        assert (ids_of(r, saved, t)[0], saved["event"], "part_of") in all_edges(client), t
    assert (mention_ids[0], saved["event"], "part_of") in all_edges(client)
    others = {person_id(client, "Arjun Mehta"), person_id(client, "Alfonso Rivera")}
    for i in saved["ids"]:
        if i:
            assert not (out_of(client, i) & others), i


# ============================================================ #14 Convo with Alfonso


def test_14_convo_with_alfonso_files_under_his_mentions_and_links(client):
    """#14. "Long convo with Alfonso about the Minfy reorg..." — first name
    only; he is the only Alfonso. Expected: a kb_entry under
    People/Alfonso Rivera/Mentions (not a new person_entry), and after Save
    that note → mentions_person Alfonso Rivera's profile (so his person
    page shows it)."""
    text = "Long convo with Alfonso about the Minfy reorg, he thinks the sales team gets split and he might move to Lisbon."
    r = drop(client, text=text, provider="local")
    assert "person_entry" not in types(r), f"proposed a duplicate person: {r['entries']}"
    mention = [e for e in r["entries"] if e["type"] == "kb_entry" and slug_folder(e["folder"]).startswith("people/alfonso-rivera/mentions")]
    assert mention, r["entries"]
    saved = save_all(client, r, journal_text=text)
    alfonso = person_id(client, "Alfonso Rivera")
    note = [i for i in ids_of(r, saved, "kb_entry") if i.startswith("note:people/alfonso-rivera/mentions/")][0]
    assert (note, alfonso, "mentions_person") in all_edges(client)
    assert person_id(client, "Arjun Mehta") not in out_of(client, note)


# ============================================================ #22 Journal & Lore


def test_22_journal_and_lore_link_people_and_places_named(client):
    """#22. A journal entry that also tells a piece of personal lore (a story
    worth keeping as its own note). After Save:
    - the journal day → mentions_person Arjun Mehta and Priya Shah,
      → at_location Founding Farmers;
    - the lore note (wherever the model files it — a KB note, not a Mentions
      note) → mentions_person Arjun Mehta and → at_location Founding Farmers;
    - nothing → Alfonso."""
    text = (
        "Told Priya Shah the story tonight of how Arjun Mehta and I got lost freshman year walking 40 minutes "
        "the wrong way looking for Founding Farmers, and ended up eating gas station hot dogs. Classic us. "
        "Want to keep that one as a lore note."
    )
    r = drop(client, text=text, provider="local")
    saved = save_all(client, r, journal_text=text)
    day = f"journal:{DAY}"
    ff = experience_id(client, "Founding Farmers")
    assert person_id(client, "Arjun Mehta") in out_of(client, day, "mentions_person")
    assert person_id(client, "Priya Shah") in out_of(client, day, "mentions_person")
    assert ff in out_of(client, day, "at_location")
    lore = [i for i in ids_of(r, saved, "kb_entry") if "/mentions/" not in i]
    assert lore, f"no lore note proposed: {types(r)}"
    assert person_id(client, "Arjun Mehta") in out_of(client, lore[0], "mentions_person")
    assert ff in out_of(client, lore[0], "at_location")
    for i in [day, *lore]:
        assert person_id(client, "Alfonso Rivera") not in out_of(client, i)


# ============================================================ #35 People


def test_35_new_person_backlinks_what_already_names_them(client):
    """#35. Content naming Neha Kapoor exists first (a journal day and a
    note), then a drop introduces her as a new person. Expected: the drop
    proposes a person_entry (not a Mentions note — she isn't known yet);
    after Save, her profile's back-links (reverse_lookup) include the
    earlier journal day and note — at least after the next app restart's
    mention backfill (the owner decides if "immediately" is required).
    Never a Document Vault entry among them."""
    assert client.post("/journal/2026-11-01", content="Met Neha Kapoor at the climbing gym.", headers={"content-type": "text/plain"}).status_code == 200
    n = client.post("/kb/entries", json={"folder": "Personal/Notes", "title": "Climbing partners", "content": "Neha Kapoor belays on Thursdays."})
    assert n.status_code == 200
    note = f"note:{n.json()['folder']}/{n.json()['slug']}"
    r = drop(client, text="Neha Kapoor is my new climbing partner, met her at Movement Crystal City last week. She's a nurse.", provider="local")
    pe = first(r, "person_entry")
    assert "neha kapoor" in pe["suggested_name"].lower(), pe
    save_all(client, r)

    from fastapi.testclient import TestClient

    import quintacle_core.api as api_module
    from quintacle_core import retrieval
    from quintacle_core.graph import reverse_lookup

    retrieval._index = None
    TestClient(api_module.create_app())  # restart → startup mention backfill, same sandbox DATA_DIR
    neha = person_id(client, "Neha Kapoor")
    sources = {e["source_id"] for e in reverse_lookup(neha) if e["kind"] == "mentions_person"}
    assert {"journal:2026-11-01", note} <= sources, sources
    assert not any(s.startswith(VAULT_PREFIX) for s in sources)
