"""DRAFT 2026-11-11 — expectations written by Claude from docs/testing/graph-linking-38-categories.md; NOT confirmed by the owner.

Live drafts for the knowledge-shaped categories (#4 Week goals, #6 Software
engineering knowledge, #16 Projects I have done, #18 Discuss a show,
#19/#20/#21 Show/Book/Game ledgers, #32 Insta & LinkedIn, #36 Business plans,
#37 Contract plans, #38 Knowledge) plus the work-log lane. Each test types a
realistic input into the REAL app (POST /drop with the local model, then the
same Save the review card does: POST /kb/entries with the proposal's
folder/title/content/links), or runs a chat "Record that", and then checks
where it was filed and which graph edges exist.

Run (only after the owner confirms the expectations):
    QUINTACLE_USER_DRAFTS=1 .venv/bin/python -m pytest tests/user/test_draft_knowledge.py -q

Sandboxed by tests.claude.harness.make_client (a temp data dir, cloud
blocked, Ollama required). ~/.quintacle is never written. The sandbox is
seeded first (CLAUDE.md: model-quality tests run on preset-seeded data): the
standard presets (tests.claude.cases.seed) plus the entities these
categories link to — the Quintacle project hub, the Minfy employer hub,
Arjun Mehta and Priya Shah, a Raft knowledge note, and the Shows/Books/Games
folders with their "About" charter hubs.

Shows/books/games ledgers are not a separate feature in the app today — they
are KB notes, so they are drafted here as notes under Fun/Shows, Fun/Books
and Fun/Games.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("QUINTACLE_USER_DRAFTS") != "1", reason="draft: owner hasn't confirmed")

QUINTACLE_HUB = "note:projects/quintacle/quintacle"
MINFY_HUB = "note:career/minfy/minfy"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from tests.claude import cases
    from tests.claude.harness import make_client, missing_requirements

    reason = missing_requirements()
    if reason:
        pytest.skip(reason)
    c = make_client(tmp_path_factory.mktemp("draft-knowledge"))
    cases.seed(c)
    _seed_entities(c)
    return c


def _seed_entities(c):
    assert c.post("/projects", json={"name": "Quintacle", "description": "Local-first personal life OS."}).status_code == 200
    assert c.post("/career/hubs", json={"type": "employer", "name": "Minfy", "summary": "AWS consulting firm."}).status_code == 200
    for name, category in (("Arjun Mehta", "work"), ("Priya Shah", "friend")):
        assert c.post("/people", json={"name": name, "category": category}).status_code == 200
    _save(c, {"folder": "Knowledge/Tech Notes", "title": "Raft consensus", "content": "Leader election with randomized timeouts."})
    for folder, label in (("Fun/Shows", "Shows"), ("Fun/Books", "Books"), ("Fun/Games", "Games")):
        _save(c, {"folder": folder, "title": f"About {label}", "content": f"One note per {label.lower()[:-1]}.", "fields": {"kind": "charter"}})
    _save(c, {"folder": "Fun/Shows", "title": "Severance", "content": "Apple TV. Season 1 done.", "links": []})


# --- helpers ---------------------------------------------------------------------


def _save(c, entry: dict) -> str:
    """The review card's Save for a kb_entry proposal (POST /kb/entries)."""
    body = {
        "folder": entry.get("folder") or "Inbox",
        "title": entry.get("title") or "Untitled",
        "content": entry.get("content") or "",
        "links": entry.get("links") or [],
        "fields": entry.get("fields"),
    }
    r = c.post("/kb/entries", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    return f"note:{j['folder']}/{j['slug']}"


def _drop_and_save(c, text: str) -> tuple[dict, str]:
    from tests.claude.harness import drop, first

    proposal = first(drop(c, text=text), "kb_entry")
    return proposal, _save(c, proposal)


def _folder(note_id: str) -> str:
    return note_id.removeprefix("note:").rsplit("/", 1)[0]


def _linked(a: str, b: str, kind: str | None = None) -> bool:
    from quintacle_core.graph import get_graph_store

    rows = get_graph_store().conn.execute(
        "SELECT kind FROM edges WHERE (source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?)",
        (a, b, b, a),
    ).fetchall()
    return any(kind is None or r["kind"] == kind for r in rows)


def _person(name: str) -> str:
    from quintacle_core.nodes.people.api import get_store

    p = get_store().find(name)
    assert p is not None, name
    return f"note:{p['folder']}/profile"


def _mentions(note_id: str, name: str) -> bool:
    return _linked(note_id, _person(name), "mentions_person")


# --- #4 Week goals ---------------------------------------------------------------


def test_4_week_goals(client):
    """Typing my week's goals as a note files it as a goals note (a folder with
    "goal" in it, never travel or the vault), and the saved note links to Arjun
    Mehta (named) and the Quintacle project (named) — not to Priya (not named)."""
    _, nid = _drop_and_save(
        client,
        "note: Week goals for Nov 9-15: 1) ship the graph tests for Quintacle, "
        "2) call Arjun Mehta about next week's sprint, 3) gym four times.",
    )
    assert "goal" in _folder(nid), nid
    assert _mentions(nid, "Arjun Mehta")
    assert _linked(nid, QUINTACLE_HUB)
    assert not _mentions(nid, "Priya Shah")


# --- #6 Software engineering knowledge ---------------------------------------------


def test_6_software_engineering_knowledge(client):
    """A software-engineering explainer files under Knowledge (not Projects or
    Daily Log), and links to the Quintacle project it names and to my existing
    "Raft consensus" note it refers to."""
    _, nid = _drop_and_save(
        client,
        "note: SQLite WAL mode lets readers keep reading while one writer commits. Quintacle uses WAL on "
        "quintacle.db so the MCP server and the API can share the file. Contrast with Raft consensus, "
        "where the replicated log lives on a majority of nodes.",
    )
    assert _folder(nid).startswith("knowledge"), nid
    assert _linked(nid, QUINTACLE_HUB)
    assert _linked(nid, "note:knowledge/tech-notes/raft-consensus")


# --- #16 Projects I have done --------------------------------------------------------


def test_16_project_writeup_backlinks_to_the_project(client):
    """A write-up about a Quintacle feature files inside the Quintacle project
    folder (projects/quintacle/...), and the Quintacle project page then lists it
    among its notes; a work log naming Quintacle shows up in the project's work logs."""
    _, nid = _drop_and_save(
        client,
        "note: Quintacle project — how the graph engine works: one markdown file per edge under "
        "graph/edges, mirrored into a SQLite edges table; link_new_entry matches titles as whole words.",
    )
    assert _folder(nid).startswith("projects/quintacle"), nid
    detail = client.get("/projects/quintacle").json()
    assert nid.rsplit("/", 1)[-1] in {n["slug"] for n in detail["notes"]}

    log = (
        "# Work Log — 2026-11-10\n\n## Session 1\n\n"
        "**Session:** 09:00–12:30 (local) · **Where:** ~/code/quintacle · **Who:** Naitik + Claude\n\n"
        "**Summary** Wrote graph tests for Quintacle and prepped the Minfy weekly sync.\n"
    )
    r = client.post("/logs/worklog/import", json={"date": "2026-11-10", "content": log})
    assert r.status_code == 200, r.text
    detail = client.get("/projects/quintacle").json()
    assert "work-log-2026-11-10" in {w["slug"] for w in detail["worklogs"]}


# --- #18 Discuss a show ----------------------------------------------------------------


def test_18_discuss_a_show_then_record_that(client):
    """Chatting about Severance and pressing "Record that" on the Severance note
    appends a dated block that states the new fact (season 2 finished, with
    Priya), keeps the old text, and links the ledger note to Priya Shah."""
    messages = [
        {"role": "user", "content": "Just finished Severance season 2 with Priya Shah. The finale was great, 9/10."},
        {"role": "assistant", "content": "Glad you liked it! Season 2 wrapped up the Cold Harbor arc."},
    ]
    r = client.post("/kb/record-that", json={"messages": messages, "folder": "fun/shows", "slug": "severance"})
    assert r.status_code == 200, r.text
    proposal = r.json()
    assert "season 2" in proposal["append"].lower() and "priya" in proposal["append"].lower(), proposal["append"]
    r = client.post("/kb/record-that/save", json={"folder": proposal["folder"], "title": proposal["title"], "append": proposal["append"]})
    assert r.status_code == 200, r.text
    from quintacle_core.nodes.kb.api import get_store

    body = get_store().read("fun/shows", "severance")
    assert "Season 1 done." in body and "season 2" in body.lower()
    assert _mentions("note:fun/shows/severance", "Priya Shah")


# --- #19 / #20 / #21 ledgers --------------------------------------------------------------

LEDGER_INPUTS = [
    ("fun/shows", "note: The Bear — watched seasons 1 to 3 with Priya Shah. Rating 9/10, want season 4.", "Priya Shah"),
    ("fun/books", "note: Project Hail Mary by Andy Weir — read in October, Arjun Mehta recommended it. 5/5.", "Arjun Mehta"),
    ("fun/games", "note: Hades II — co-op nights with Arjun Mehta, about 40 hours in, still on the Surface route.", "Arjun Mehta"),
]


@pytest.mark.parametrize("folder,text,person", LEDGER_INPUTS, ids=["19-show", "20-book", "21-game"])
def test_ledger_entry(client, folder, text, person):
    """A show/book/game entry files into its ledger folder (Fun/Shows, Fun/Books,
    Fun/Games — already existing), links to the person it names, and links to
    that folder's "About" hub note."""
    _, nid = _drop_and_save(client, text)
    assert _folder(nid) == folder, nid
    assert _mentions(nid, person)
    assert _linked(nid, f"note:{folder}/about-{folder.rsplit('/', 1)[-1]}")


# --- #32 Insta & LinkedIn --------------------------------------------------------------------


def test_32_linkedin_post(client):
    """A LinkedIn post draft files as a social/LinkedIn note (folder mentions
    linkedin or social), links to Arjun Mehta (thanked) and the Quintacle project
    (the subject), and does not link to Priya."""
    _, nid = _drop_and_save(
        client,
        "note: LinkedIn post draft — After three months of nights and weekends, Quintacle, my local-first "
        "life OS, now runs fully on my phone. Huge thanks to Arjun Mehta for the architecture reviews.",
    )
    assert any(k in _folder(nid) for k in ("linkedin", "social")), nid
    assert _mentions(nid, "Arjun Mehta")
    assert _linked(nid, QUINTACLE_HUB)
    assert not _mentions(nid, "Priya Shah")


# --- #36 Business plans -------------------------------------------------------------------------


def test_36_business_plan(client):
    """A business idea files under Business Ideas, links to Priya Shah (the
    co-founder named) and the Quintacle project (whose engine it reuses)."""
    _, nid = _drop_and_save(
        client,
        "note: Business idea — weekly macro-matched meal prep delivery for gym-goers. Co-founder candidate "
        "Priya Shah. Reuse the Quintacle nutrition engine to compute each customer's macro targets.",
    )
    assert _folder(nid).startswith("business"), nid
    assert _mentions(nid, "Priya Shah")
    assert _linked(nid, QUINTACLE_HUB)


# --- #37 Contract plans ---------------------------------------------------------------------------


def test_37_contract_plan(client):
    """A side-contract plan with Minfy files under Career (never Fun or the
    vault), links to Minfy and to Arjun Mehta, and — through Minfy — reaches the
    work logs that name Minfy (within two hops)."""
    log = (
        "# Work Log — 2026-11-09\n\n## Session 1\n\n"
        "**Session:** 10:00–11:00 (local) · **Where:** ~/code/minfy-data · **Who:** Naitik\n\n"
        "**Summary** Minfy data platform kickoff.\n"
    )
    r = client.post("/logs/worklog/import", json={"date": "2026-11-09", "content": log})
    assert r.status_code == 200, r.text
    _, nid = _drop_and_save(
        client,
        "note: Contract plan — side contract with Minfy on their data platform, 10 hours a week from "
        "December, reporting to Arjun Mehta. Rate $85/h, invoice monthly.",
    )
    assert _folder(nid).startswith("career"), nid
    assert _linked(nid, MINFY_HUB)
    assert _mentions(nid, "Arjun Mehta")
    from quintacle_core.graph import neighborhood

    assert "note:daily-log/work-logs/work-log-2026-11-09" in neighborhood(nid, 2)["nodes"]


# --- #38 Knowledge ----------------------------------------------------------------------------------


def test_38_knowledge_note(client):
    """A general knowledge note files under Knowledge, links to the person who
    sent the material (Priya Shah) and not to anyone unnamed."""
    _, nid = _drop_and_save(
        client,
        "note: Azulejo history — tin-glazed ceramic tiles, Moorish origins, the national tile museum. "
        "Priya Shah sent me the reading list.",
    )
    assert _folder(nid).startswith("knowledge"), nid
    assert _mentions(nid, "Priya Shah")
    assert not _mentions(nid, "Arjun Mehta")


# --- work-log lane ------------------------------------------------------------------------------------


def test_work_log_links_quintacle_and_minfy(client):
    """Importing a day's work log that names Quintacle and Minfy files it as
    daily-log/work-logs/work-log-<date>, with links [Minfy, Quintacle] and graph
    edges to both hubs; it also links to the work-logs folder's About hub."""
    log = (
        "# Work Log — 2026-11-11\n\n## Session 1\n\n"
        "**Session:** 13:00–17:00 (local) · **Where:** ~/code/quintacle · **Who:** Naitik + Claude\n\n"
        "**Summary** Quintacle graph-linking tests; answered a Minfy client question.\n"
    )
    _save(client, {"folder": "Daily Log/Work Logs", "title": "About Work Logs", "content": "One file per day of work.", "fields": {"kind": "charter"}})
    r = client.post("/logs/worklog/import", json={"date": "2026-11-11", "content": log})
    assert r.status_code == 200, r.text
    out = r.json()
    nid = f"note:{out['folder']}/{out['slug']}"
    assert nid == "note:daily-log/work-logs/work-log-2026-11-11"
    assert out["links"] == ["Minfy", "Quintacle"]
    assert _linked(nid, QUINTACLE_HUB) and _linked(nid, MINFY_HUB)
    assert _linked(nid, "note:daily-log/work-logs/about-work-logs")
