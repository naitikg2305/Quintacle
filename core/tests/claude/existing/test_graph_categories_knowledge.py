"""Graph linking for the owner's knowledge-shaped categories (2026-11-11).

Spec: docs/testing/graph-linking-38-categories.md (DRAFT expectations). This
file covers #4 Week goals, #6 Software engineering knowledge, #16 Projects I
have done, #18 Discuss a show, #19/#20/#21 Show/Book/Game ledgers, #32 Insta &
LinkedIn, #36 Business plans, #37 Contract plans, #38 Knowledge, plus the two
known gaps: (a) work logs imported via the work-log lane (REST
/logs/worklog/import and MCP import_work_log) must link the Quintacle/Minfy
hubs they name; (b) folder "about" hub notes must link to the notes in their
folder.

Models FAKED: every save here is the structured Save the app performs AFTER
review (POST /kb/entries with the reviewed folder/title/content/links, the
/projects, /career/hubs, /business/ideas create forms, /kb/record-that/save,
/transcripts/archive, the MCP tools). The two model seams touched
(suggest_record_fold, soft_record.extract_facts) are monkeypatched.

Expectations come from the spec, never from current behaviour. Where the code
doesn't do what the spec says, the assertion stays and the test is marked
xfail(strict=True) with the gap and its code location.

Shows/books/games ledgers are NOT a feature (no ledger store/router exists in
quintacle_core — `grep -ri ledger` only finds the stock and MCP write
ledgers), so they are tested as plain KB notes under Fun/Shows, Fun/Books,
Fun/Games, each folder with an `About <Folder>` charter hub (kind: charter),
the same shape as the real store's daily-log/work-logs/about-work-logs.md.

Sandboxed: a tmp DATA_DIR per test; ~/.quintacle is never touched.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

TODAY = date(2026, 11, 11)

QUINTACLE_HUB = "note:projects/quintacle/quintacle"
MINFY_HUB = "note:career/minfy/minfy"

GAP_PROJECT_MENTION = (
    "GAP: a note's body naming a project/company hub makes no edge — the write-rule candidates are people "
    "+ experiences only (graph_capture.mention_candidates, used by entry_graph_links via "
    "kb/api._sync_note_graph_links and mcp_server/graph_link.link_new_entry); only the work-log importer "
    "matches Career/Projects hub titles (logs/worklog.mentioned_entity_titles)"
)
GAP_FOLDER_HUB = (
    "GAP: folder 'about' charter hubs (about-<folder>.md) never link to the notes in their folder — no code "
    "creates a note<->folder-hub edge on save (kb/api._sync_note_graph_links, graph_capture.entry_graph_links)"
)
GAP_HUB_BACKFILL = (
    "GAP: creating a project hub (POST /projects -> projects/api._index_new_note -> _sync_note_graph_links) "
    "only links the hub's OWN text outward; notes already naming the project get no back-link (no reverse "
    "scan like the startup mention backfill, which itself only targets people/experiences)"
)
GAP_RECORD_THAT_WIPES_LINKS = (
    "GAP: /kb/record-that/save (nodes/kb/api.py record_that_save) keeps the note's `links:` frontmatter "
    "(store.write links=None) but calls _sync_note_graph_links(..., None) -> sync_frontmatter_links with [] "
    "-> every existing frontmatter_links edge of the ledger note is deleted as 'stale'"
)
GAP_SOFT_FACTS = (
    "GAP (by design, next-wave-plan §12): soft facts extracted from an archived chat live in "
    "conversations/soft_record.db, outside kb/ and the graph — nothing ties a fact to the show's ledger note "
    "unless the owner runs Record that"
)


# --- sandbox app + seed --------------------------------------------------------


@pytest.fixture
def c(tmp_path, monkeypatch):
    import quintacle_core.api as api_module
    from quintacle_core import clock

    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    client = TestClient(api_module.create_app())
    seed(client)
    return client


def seed(c):
    """Entity grounding: the Quintacle project hub, the Minfy employer hub,
    two people, and a prior knowledge note to link to."""
    r = c.post("/projects", json={"name": "Quintacle", "description": "Local-first personal life OS."})
    assert r.status_code == 200, r.text
    r = c.post("/career/hubs", json={"type": "employer", "name": "Minfy", "summary": "AWS consulting firm."})
    assert r.status_code == 200, r.text
    for name, category in (("Arjun Mehta", "work"), ("Priya Shah", "friend")):
        r = c.post("/people", json={"name": name, "category": category})
        assert r.status_code == 200, r.text
    note(c, "Knowledge/Tech Notes", "Raft consensus", "Leader election with randomized timeouts.")
    kb = kb_store()
    assert kb.read("projects/quintacle", "quintacle") is not None
    assert kb.read("career/minfy", "minfy") is not None


def kb_store():
    from quintacle_core.nodes.kb.api import get_store

    return get_store()


def person_id(name: str) -> str:
    from quintacle_core.nodes.people.api import get_store

    p = get_store().find(name)
    assert p is not None, name
    return f"note:{p['folder']}/profile"


def note(c, folder, title, content="", links=None, fields=None) -> str:
    r = c.post("/kb/entries", json={"folder": folder, "title": title, "content": content, "links": links, "fields": fields})
    assert r.status_code == 200, r.text
    j = r.json()
    return f"note:{j['folder']}/{j['slug']}"


def edges_between(a: str, b: str) -> list[dict]:
    from quintacle_core.graph import get_graph_store

    rows = get_graph_store().conn.execute(
        "SELECT * FROM edges WHERE (source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?)",
        (a, b, b, a),
    ).fetchall()
    return [dict(r) for r in rows]


def linked(a: str, b: str, kind: str | None = None) -> bool:
    return any(kind is None or e["kind"] == kind for e in edges_between(a, b))


def mentions(src: str, name: str) -> bool:
    return linked(src, person_id(name), "mentions_person")


WORK_LOG = """# Work Log — 2026-11-10

## Session 1

**Session:** 09:00–12:30 (local) · **Where:** ~/code/quintacle · **Who:** Naitik + Claude (Opus)

**Summary** Wrote graph-linking tests for Quintacle and prepped notes for the Minfy weekly sync.

**Done**
- Drafted test_graph_categories_knowledge.py.
"""


def import_log(c, day: date = date(2026, 11, 10), text: str = WORK_LOG) -> dict:
    r = c.post("/logs/worklog/import", json={"date": day.isoformat(), "content": text})
    assert r.status_code == 200, r.text
    return r.json()


# --- #4 Week goals --------------------------------------------------------------

WEEK_GOALS = (
    "1. Ship the graph tests for Quintacle.\n"
    "2. Call Arjun Mehta about next week's sprint.\n"
    "3. Gym 4x."
)


def test_4_week_goals_link_people_named(c):
    nid = note(c, "Personal Development/Goals", "Week goals 2026-11-09", WEEK_GOALS)
    assert mentions(nid, "Arjun Mehta")
    # ✗ a person the goals never name
    assert not mentions(nid, "Priya Shah")


@pytest.mark.xfail(strict=True, reason=GAP_PROJECT_MENTION)
def test_4_week_goals_link_projects_named(c):
    nid = note(c, "Personal Development/Goals", "Week goals 2026-11-09", WEEK_GOALS)
    assert linked(nid, QUINTACLE_HUB)


def test_4_week_goals_do_not_link_unnamed_hubs(c):
    nid = note(c, "Personal Development/Goals", "Week goals 2026-11-09", WEEK_GOALS)
    assert not linked(nid, MINFY_HUB)  # ✗ Minfy is never named


# --- #6 Software engineering knowledge -----------------------------------------

SWE_NOTE = (
    "SQLite WAL mode lets readers run while one writer commits. Quintacle uses it for quintacle.db so the "
    "MCP server and the API can share the file. See Raft consensus for the replicated-log contrast."
)


def test_6_swe_knowledge_links_frontmatter_related(c):
    nid = note(c, "Knowledge/Tech Notes", "SQLite WAL mode", SWE_NOTE, links=["Raft consensus"])
    assert linked(nid, "note:knowledge/tech-notes/raft-consensus", "related")


@pytest.mark.xfail(strict=True, reason=GAP_PROJECT_MENTION)
def test_6_swe_knowledge_links_project_it_names(c):
    nid = note(c, "Knowledge/Tech Notes", "SQLite WAL mode", SWE_NOTE, links=["Raft consensus"])
    assert linked(nid, QUINTACLE_HUB)


# --- #16 Projects I have done ----------------------------------------------------


def test_16_project_hub_backlinks_work_logs_that_name_it(c):
    out = import_log(c)
    assert "Quintacle" in out["links"]
    wl = f"note:{out['folder']}/{out['slug']}"
    assert linked(wl, QUINTACLE_HUB, "related")
    detail = c.get("/projects/quintacle").json()
    assert [w["slug"] for w in detail["worklogs"]] == ["work-log-2026-11-10"]


@pytest.mark.xfail(strict=True, reason=GAP_PROJECT_MENTION)
def test_16_project_hub_backlinks_knowledge_notes_that_name_it(c):
    nid = note(c, "Knowledge/Tech Notes", "SQLite WAL mode", SWE_NOTE)
    from quintacle_core.graph import reverse_lookup, get_graph_store

    back = {e["source_id"] for e in reverse_lookup(QUINTACLE_HUB)} | {
        e["target_id"] for e in get_graph_store().edges_from(QUINTACLE_HUB)
    }
    assert nid in back


@pytest.mark.xfail(strict=True, reason=GAP_HUB_BACKFILL)
def test_16_new_project_hub_backlinks_older_notes_naming_it(c):
    # A knowledge note links to the project via `links:` even before the hub
    # exists (the title is stated, just unresolvable yet) — then the hub is created.
    older = note(c, "Knowledge/Tech Notes", "Rover motor tuning", "PID gains for the Rover drive.", links=["Rover"])
    r = c.post("/projects", json={"name": "Rover", "description": "Autonomous rover."})
    assert r.status_code == 200, r.text
    assert linked(older, "note:projects/rover/rover")


# --- #18 Discuss a show (chat -> extracted facts) --------------------------------


def _seed_show_ledgers(c) -> str:
    note(c, "Fun/Shows", "Lost", "Island mystery. Finished 2025.")
    return note(c, "Fun/Shows", "Severance", "Apple TV. Season 1 done.", links=["Lost"])


SHOW_CHAT = [
    {"role": "user", "content": "Just finished Severance season 2 with Priya Shah. The finale was great."},
    {"role": "assistant", "content": "Glad you liked it! Season 2 resolved the Cold Harbor arc."},
]
SHOW_POINTS = "- Finished Severance season 2 with Priya Shah; loved the finale."


def _record_that_onto_ledger(c, monkeypatch):
    import quintacle_core.nodes.kb.api as kb_api
    from quintacle_core.nodes.kb.llm import RecordFoldPoints

    monkeypatch.setattr(kb_api, "suggest_record_fold", lambda convo, title=None, provider=None: RecordFoldPoints(points=SHOW_POINTS))
    r = c.post("/kb/record-that", json={"messages": SHOW_CHAT, "folder": "fun/shows", "slug": "severance"})
    assert r.status_code == 200, r.text
    proposal = r.json()
    assert proposal["folder"] == "fun/shows" and proposal["title"] == "Severance"
    r = c.post("/kb/record-that/save", json={"folder": proposal["folder"], "title": proposal["title"], "append": proposal["append"]})
    assert r.status_code == 200, r.text
    assert r.json()["appended"] is True


def test_18_archived_show_chat_links_to_the_show_ledger(c):
    ledger = _seed_show_ledgers(c)
    r = c.post("/transcripts/archive", json={"messages": SHOW_CHAT, "subject": "Severance season 2"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["archived"] and j["edge_id"]
    assert linked(f"transcript:{j['topic']}/{j['stamp']}", ledger, "transcript_of")


def test_18_record_that_lands_facts_in_the_ledger_and_links_people(c, monkeypatch):
    ledger = _seed_show_ledgers(c)
    _record_that_onto_ledger(c, monkeypatch)
    body = kb_store().read("fun/shows", "severance")
    assert "Season 1 done." in body and "Finished Severance season 2 with Priya Shah" in body
    assert mentions(ledger, "Priya Shah")


def test_18_record_that_keeps_the_ledger_existing_links(c, monkeypatch):
    ledger = _seed_show_ledgers(c)
    assert linked(ledger, "note:fun/shows/lost", "related")  # before
    _record_that_onto_ledger(c, monkeypatch)
    assert kb_store().read_links("fun/shows", "severance") == ["Lost"]  # frontmatter kept...
    assert linked(ledger, "note:fun/shows/lost", "related")  # ...and so must the edge


@pytest.mark.xfail(strict=True, reason=GAP_SOFT_FACTS)
def test_18_extracted_soft_facts_reach_the_show_ledger(c, monkeypatch):
    ledger = _seed_show_ledgers(c)
    import quintacle_core.nodes.kb.soft_record as soft_record

    monkeypatch.setattr(soft_record, "extract_facts", lambda text: ["Finished Severance season 2 with Priya Shah"])
    r = c.post("/transcripts/archive", json={"messages": SHOW_CHAT, "subject": "Severance season 2", "final": True})
    assert r.status_code == 200 and r.json()["soft_facts_pending"]
    facts = c.get("/soft-record").json()
    assert any("Severance" in (f.get("text") or "") for f in facts)  # the fact was extracted (background task ran)
    from quintacle_core.graph import get_graph_store

    store = get_graph_store()
    fact_edges = [
        e for e in store.reverse_edges(ledger) + store.edges_from(ledger) if not e["source_id"].startswith("transcript:")
        and e["kind"] != "related" and e["kind"] != "mentions_person"
    ]
    in_ledger = "season 2" in (kb_store().read("fun/shows", "severance") or "")
    assert fact_edges or in_ledger


# --- #19 / #20 / #21 Show, Book, Game ledgers -------------------------------------

LEDGERS = [
    ("Fun/Shows", "Shows", "The Bear", "Watched seasons 1-3 with Priya Shah. Rating 9/10."),
    ("Fun/Books", "Books", "Project Hail Mary", "Read in October; Arjun Mehta recommended it. 5/5."),
    ("Fun/Games", "Games", "Hades II", "Co-op nights with Arjun Mehta. 40 hours so far."),
]
LEDGER_IDS = ["19-show", "20-book", "21-game"]


def _hub(c, folder, label) -> str:
    return note(c, folder, f"About {label}", f"One note per {label.lower()[:-1]}: status, rating, who with.", fields={"kind": "charter"})


@pytest.mark.parametrize("folder,label,title,body", LEDGERS, ids=LEDGER_IDS)
def test_ledger_entry_links_people_named(c, folder, label, title, body):
    _hub(c, folder, label)
    nid = note(c, folder, title, body)
    named = "Priya Shah" if "Priya" in body else "Arjun Mehta"
    other = "Arjun Mehta" if named == "Priya Shah" else "Priya Shah"
    assert mentions(nid, named)
    assert not mentions(nid, other)  # ✗ someone the entry never names


@pytest.mark.xfail(strict=True, reason=GAP_FOLDER_HUB)
@pytest.mark.parametrize("folder,label,title,body", LEDGERS, ids=LEDGER_IDS)
def test_ledger_entry_links_its_folder_hub(c, folder, label, title, body):
    hub = _hub(c, folder, label)
    nid = note(c, folder, title, body)
    assert linked(nid, hub)


# --- #32 Insta & LinkedIn -------------------------------------------------------

LINKEDIN = (
    "Draft: After 3 months of nights and weekends, Quintacle — my local-first life OS — runs fully on my "
    "phone. Huge thanks to Arjun Mehta for the architecture reviews."
)


def test_32_social_post_links_people_named(c):
    nid = note(c, "Me/Social/LinkedIn", "LinkedIn post - Quintacle on phone", LINKEDIN)
    assert mentions(nid, "Arjun Mehta")
    assert not mentions(nid, "Priya Shah")


@pytest.mark.xfail(strict=True, reason=GAP_PROJECT_MENTION)
def test_32_social_post_links_projects_named(c):
    nid = note(c, "Me/Social/LinkedIn", "LinkedIn post - Quintacle on phone", LINKEDIN)
    assert linked(nid, QUINTACLE_HUB)


# --- #36 Business plans ---------------------------------------------------------

IDEA = {
    "title": "Meal prep delivery",
    "summary": "Weekly macro-matched meal prep for gym-goers.",
    "body": "Co-founder candidate: Priya Shah. Reuse the Quintacle nutrition engine for macro targets.",
}


def test_36_business_plan_links_people_named(c):
    r = c.post("/business/ideas", json=IDEA)
    assert r.status_code == 200, r.text
    nid = "note:business-ideas/meal-prep-delivery/meal-prep-delivery"
    assert kb_store().read("business-ideas/meal-prep-delivery", "meal-prep-delivery") is not None
    assert mentions(nid, "Priya Shah")
    assert not mentions(nid, "Arjun Mehta")


@pytest.mark.xfail(strict=True, reason=GAP_PROJECT_MENTION)
def test_36_business_plan_links_projects_named(c):
    assert c.post("/business/ideas", json=IDEA).status_code == 200
    assert linked("note:business-ideas/meal-prep-delivery/meal-prep-delivery", QUINTACLE_HUB)


# --- #37 Contract plans (side hustles, e.g. Minfy) --------------------------------

CONTRACT_SUMMARY = "Side contract with Minfy on their data platform, 10 h/week, reporting to Arjun Mehta."


def _contract_hub(c) -> str:
    r = c.post("/career/hubs", json={"type": "contract", "name": "Data platform contract", "summary": CONTRACT_SUMMARY})
    assert r.status_code == 200, r.text
    return "note:career/contracts/data-platform-contract/data-platform-contract"


def test_37_contract_plan_links_people_named(c):
    nid = _contract_hub(c)
    assert kb_store().read("career/contracts/data-platform-contract", "data-platform-contract") is not None
    assert mentions(nid, "Arjun Mehta")


@pytest.mark.xfail(strict=True, reason=GAP_PROJECT_MENTION)
def test_37_contract_plan_links_company_named(c):
    nid = _contract_hub(c)
    assert linked(nid, MINFY_HUB)


@pytest.mark.xfail(strict=True, reason=GAP_PROJECT_MENTION)
def test_37_contract_plan_note_links_company_named(c):
    nid = note(c, "Side Hustles", "Minfy contract plan", CONTRACT_SUMMARY)
    assert mentions(nid, "Arjun Mehta")
    assert linked(nid, MINFY_HUB)


@pytest.mark.xfail(strict=True, reason=GAP_PROJECT_MENTION + " — so the work logs (linked to the Minfy hub) are unreachable")
def test_37_contract_plan_reaches_work_logs_that_name_the_company(c):
    out = import_log(c)
    wl = f"note:{out['folder']}/{out['slug']}"
    assert linked(wl, MINFY_HUB, "related")
    nid = _contract_hub(c)
    from quintacle_core.graph import neighborhood

    assert wl in neighborhood(nid, 2)["nodes"]


# --- #38 Knowledge --------------------------------------------------------------


def test_38_knowledge_links_frontmatter_people_and_places(c):
    # Lisbon is a known place string (an experience's city) mentioned twice already...
    r = c.post("/travel/experiences", json={"name": "Pastel Bakery", "city": "Lisbon", "kind": "bakery"})
    assert r.status_code == 200, r.text
    note(c, "Fun/Travel", "Lisbon tram notes", "Tram 28 through Alfama.")
    # ...and this knowledge note is the third mention: the place emerges and links.
    nid = note(
        c,
        "Knowledge/Research",
        "Azulejo history",
        "Tin-glazed tiles; the museum in Lisbon. Priya Shah sent me the reading list.",
        links=["Raft consensus"],
    )
    assert linked(nid, "note:knowledge/tech-notes/raft-consensus", "related")
    assert mentions(nid, "Priya Shah")
    assert linked(nid, "note:places/lisbon", "at_location")
    assert not mentions(nid, "Arjun Mehta")


# --- known gap (a): work logs via the work-log lane --------------------------------


def test_worklog_rest_import_links_quintacle_and_minfy(c):
    out = import_log(c)
    assert out["links"] == ["Minfy", "Quintacle"]
    wl = f"note:{out['folder']}/{out['slug']}"
    assert wl == "note:daily-log/work-logs/work-log-2026-11-10"
    assert kb_store().read_links("daily-log/work-logs", "work-log-2026-11-10") == ["Minfy", "Quintacle"]
    assert linked(wl, QUINTACLE_HUB, "related")
    assert linked(wl, MINFY_HUB, "related")


def test_worklog_naming_only_the_repo_path_still_links_the_project(c):
    text = (
        "# Work Log — 2026-11-09\n\n## Session 1\n\n"
        "**Session:** 14:00–15:00 (local) · **Where:** ~/code/quintacle · **Who:** Naitik + Claude\n\n"
        "**Summary** Fixed the drop router.\n"
    )
    out = import_log(c, date(2026, 11, 9), text)
    wl = f"note:{out['folder']}/{out['slug']}"
    assert linked(wl, QUINTACLE_HUB, "related")
    assert not linked(wl, MINFY_HUB)  # ✗ Minfy is never named


def test_worklog_without_entity_names_has_no_hub_links(c):
    """The real-store `links: []` logs (Oct 21/25/28/29/31) contain neither
    word — an empty list is the correct outcome there, not a regression."""
    text = (
        "# Work Log — 2026-10-21\n\n## Session 1\n\n"
        "**Session:** ~13:00–13:25 (local) · **Where:** ~ (system config), ~/computer setup/linux · **Who:** Naitik\n\n"
        "**Summary** Tuned the Linux keyboard layout.\n"
    )
    out = import_log(c, date(2026, 10, 21), text)
    assert out["links"] == []
    wl = f"note:{out['folder']}/{out['slug']}"
    assert not linked(wl, QUINTACLE_HUB) and not linked(wl, MINFY_HUB)


def test_worklog_reimport_keeps_hub_links(c):
    import_log(c)
    out = import_log(c)
    wl = f"note:{out['folder']}/{out['slug']}"
    assert linked(wl, QUINTACLE_HUB, "related") and linked(wl, MINFY_HUB, "related")


@pytest.mark.xfail(strict=True, reason=GAP_FOLDER_HUB)
def test_worklog_links_the_work_logs_folder_hub(c):
    hub = _hub(c, "Daily Log/Work Logs", "Work Logs")
    out = import_log(c)
    assert linked(f"note:{out['folder']}/{out['slug']}", hub)


# --- the MCP lane (Claude pushing knowledge / work logs) -----------------------------


@pytest.fixture
def mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("QUINTACLE_DATA_DIR", str(tmp_path / "mcp"))  # before any first import of the server
    from quintacle_core.mcp_server import server as s
    from quintacle_core.nodes.people.store import PersonStore

    s.init(tmp_path / "mcp")
    s.kb_create_entry(folder="Projects/Quintacle", title="Quintacle", content="Local-first personal life OS.")
    s.kb_create_entry(folder="Career/Minfy", title="Minfy", content="AWS consulting firm.")
    s.kb_create_entry(folder="Knowledge/Tech Notes", title="Raft consensus", content="Leader election.")
    PersonStore(tmp_path / "mcp" / "kb").write("Arjun Mehta", category="work")
    return s


def test_worklog_mcp_import_links_quintacle_and_minfy(mcp):
    out = mcp.import_work_log(for_date="2026-11-10", content=WORK_LOG)
    assert out["links"] == ["Minfy", "Quintacle"]
    wl = f"note:{out['folder']}/{out['slug']}"
    assert linked(wl, QUINTACLE_HUB, "related")
    assert linked(wl, MINFY_HUB, "related")


def test_6_mcp_knowledge_links_frontmatter_and_people(mcp):
    out = mcp.kb_create_entry(
        folder="Knowledge/Tech Notes",
        title="SQLite WAL mode",
        content=SWE_NOTE + " Arjun Mehta suggested it.",
        links=["Raft consensus"],
    )
    nid = f"note:{out['folder']}/{out['slug']}"
    assert linked(nid, "note:knowledge/tech-notes/raft-consensus", "related")
    assert linked(nid, "note:people/arjun-mehta/profile", "mentions_person")


@pytest.mark.xfail(strict=True, reason=GAP_PROJECT_MENTION)
def test_6_mcp_knowledge_links_project_it_names(mcp):
    out = mcp.kb_create_entry(folder="Knowledge/Tech Notes", title="SQLite WAL mode", content=SWE_NOTE)
    assert linked(f"note:{out['folder']}/{out['slug']}", QUINTACLE_HUB)


@pytest.mark.xfail(strict=True, reason=GAP_PROJECT_MENTION)
def test_37_mcp_contract_plan_links_company_named(mcp):
    out = mcp.kb_create_entry(folder="Side Hustles", title="Minfy contract plan", content=CONTRACT_SUMMARY)
    assert linked(f"note:{out['folder']}/{out['slug']}", MINFY_HUB)
