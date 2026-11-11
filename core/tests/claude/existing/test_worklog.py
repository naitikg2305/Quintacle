"""The work-log lane (next-wave-plan §10): deterministic session parsing of
~/work-logs-shaped markdown, the verbatim KB note import under
Daily Log/Work Logs (overwrite-by-title, graph edges to mentioned
Career/Projects entity notes, retrieval-indexed), and the auto productivity
rows — hours computed in code from session headers, deduped by the
source=worklog-auto tag (never fuzzy matching), manual rows untouchable.

Fixtures mirror the REAL variance found in ~/work-logs/ (which is never read
or written by any test here): numbered multi-session files, a single
unnumbered whole-file session, ~-prefixed times, en-dash/hyphen separators,
past-midnight ranges, missing/unparseable ends ("evening…", "continuation"),
`**Summary**` blocks vs inline `**Summary.**` vs `## Summary` headings.
"""
from datetime import date

import pytest

from quintacle_core.mcp_server import server as s
from quintacle_core.nodes.logs.log_store import rebuild_sqlite_index
from quintacle_core.nodes.logs.worklog import (
    WORKLOG_SOURCE,
    mentioned_entity_titles,
    parse_work_log,
    row_description,
)

D = date(2026, 10, 19)

# Shaped exactly like the real 2026-10-19 file: numbered sessions, ~-prefixed
# en-dash times, worktree parentheticals (with commas inside) in Where,
# **Summary** on its own line with the text in the following paragraph.
MULTI = """# 2026-10-19

## Session 1

**Session:** ~12:45–14:30 (local) · **Where:** ~/code/AWS_Hackathon_Minfy (fresh clone of github.com/example/AWS_Hackathon_Minfy) · **Who:** Naitik + Claude (Fable 5.1)

**Summary**
Deployed the Minfy hackathon agent (Strands SDK + Bedrock, 6 tools over CSV data) to AgentCore Runtime with the cheapest configuration that still runs: CodeZip build, OTel off. Smoke test returned FALSE POSITIVE in ~31 s.

**Done**
- stuff happened

## Session 2

**Session:** ~17:00–18:00 (local) · **Where:** ~/code/quintacle (worktree agent-a324235, branch redone-UI base) · **Who:** Naitik + Claude (Fable 5)

**Summary**
Built the decided stocks wave in a parallel worktree: a markdown-backed transaction ledger with FIFO positions computed in code. Suite green.

**Done**
- more stuff

## Session 3 (main-session close-out)

**Session:** 14:30–18:45 (local) · **Where:** ~/code/quintacle (main thread, branch redone-UI) · **Who:** Naitik + Claude (Fable 5)

**Summary**
Fired five build waves across parallel agents and merged them all.
"""

# Shaped like the real 2026-10-07 file: no `## Session` headings at all, the
# header right under the file title, an unparseable prose start time with a
# `→` to a parseable end, backticked multi-location Where, `## Summary`.
SINGLE_UNNUMBERED = """# 2026-10-07: Portfolio overhaul and moving the site to AWS

**Session:** evening Oct 7 → ~01:50 Oct 8 · **Where:** `~/code/PersonalWebsite`, `~/Career and Resume`, personal AWS account · **Who:** Naitik + Claude (Opus 5.5)

## Summary
Started by using the personal website as a reference for career material, and ended with the site fully migrated to AWS. Along the way: a new 3-page resume.

## Done
- things
"""

MISSING_END = """## Session 1

**Session:** ~13:00 (local) · **Where:** ~/code/quintacle · **Who:** Naitik + Claude (Fable 5)

**Summary**
Started something and never wrote the end time.
"""

# Real shapes from 2026-10-15: "continuation" with an inline `**Summary.**`,
# and "~afternoon" with no clock times at all.
UNPARSEABLE_TIMES = """## Session 12 (main-session integration close-out)

**Session:** continuation · **Where:** ~/code/quintacle (redone-UI) · **Who:** Naitik + Claude (Fable 5)

**Summary.** Integrated the entire perception wave (7 agent branches) plus the phone folder. Full E2E proven on real photos.

## Session 13

**Session:** ~afternoon (local) · **Where:** ~/code/quintacle (worktree agent-a48f, branch worktree-agent-a48f) · **Who:** Naitik + Claude (Fable 5)

**Summary**
Documented the perception wave.
"""

PAST_MIDNIGHT = """## Session 1

**Session:** 23:15–00:10 (local, ran past midnight) · **Where:** `~/code/quintacle testing` (new), /tmp/qt-gen · **Who:** Naitik + Claude (Fable 5.1)

**Summary**
Ran the generated corpus experiment past midnight.
"""

NO_SUMMARY = """## Session 1

**Session:** 13:40-14:35 (local) · **Where:** ~/Career and Resume · **Who:** Naitik + Claude (Fable 5.1)

Wrote a one-page resume tailored to the posting. Then reorganised the folder.
"""


# --- the parser: pure, deterministic, zero model calls -----------------------


def test_multi_session_blocks_times_and_hours():
    sessions = parse_work_log(MULTI, D)

    assert [x.label for x in sessions] == ["Session 1", "Session 2", "Session 3 (main-session close-out)"]
    assert [x.start for x in sessions] == ["12:45", "17:00", "14:30"]
    assert [x.end for x in sessions] == ["14:30", "18:00", "18:45"]
    # Exact arithmetic, in code: 105min, 60min, 255min.
    assert [x.hours for x in sessions] == [1.75, 1.0, 4.25]
    assert all(x.date == D for x in sessions)


def test_summary_first_sentence_is_the_one_liner():
    sessions = parse_work_log(MULTI, D)

    assert sessions[0].description == (
        "Deployed the Minfy hackathon agent (Strands SDK + Bedrock, 6 tools over CSV data) to "
        "AgentCore Runtime with the cheapest configuration that still runs: CodeZip build, OTel off."
    )
    assert sessions[1].description == (
        "Built the decided stocks wave in a parallel worktree: a markdown-backed transaction "
        "ledger with FIFO positions computed in code."
    )
    assert sessions[2].description == "Fired five build waves across parallel agents and merged them all."


def test_where_repos_and_project_extraction():
    sessions = parse_work_log(MULTI, D)

    assert sessions[0].repos == ["~/code/AWS_Hackathon_Minfy"]
    assert sessions[0].project == "AWS_Hackathon_Minfy"  # cased name kept verbatim
    assert sessions[1].repos == ["~/code/quintacle"]  # worktree parenthetical (with commas) dropped
    assert sessions[1].project == "Quintacle"  # all-lowercase name capitalized
    assert row_description(sessions[2]).startswith("Quintacle: Fired five build waves")


def test_unnumbered_file_is_one_whole_file_session():
    sessions = parse_work_log(SINGLE_UNNUMBERED, date(2026, 10, 7))

    assert len(sessions) == 1
    x = sessions[0]
    assert x.label == ""
    # "evening Oct 7" has no parseable start — hours are never guessed.
    assert x.hours is None and x.start is None and x.end is None
    # `## Summary` heading form, first sentence only.
    assert x.description.startswith("Started by using the personal website")
    assert x.description.endswith("migrated to AWS.")
    assert x.repos == ["~/code/PersonalWebsite", "~/Career and Resume", "personal AWS account"]
    assert x.project == "PersonalWebsite"


def test_missing_end_time_means_no_hours():
    sessions = parse_work_log(MISSING_END, D)
    assert len(sessions) == 1
    assert sessions[0].hours is None


def test_continuation_and_afternoon_headers_have_no_hours():
    sessions = parse_work_log(UNPARSEABLE_TIMES, D)

    assert [x.hours for x in sessions] == [None, None]
    # Inline `**Summary.** text…` form — markdown markers stripped.
    assert sessions[0].description == "Integrated the entire perception wave (7 agent branches) plus the phone folder."
    assert sessions[1].description == "Documented the perception wave."


def test_past_midnight_range_adds_a_day():
    sessions = parse_work_log(PAST_MIDNIGHT, date(2026, 10, 14))
    assert sessions[0].hours == round(55 / 60, 2)  # 23:15 → 00:10 = 55 minutes


def test_plain_hyphen_times_and_fallback_first_line_description():
    sessions = parse_work_log(NO_SUMMARY, date(2026, 10, 14))

    x = sessions[0]
    assert x.hours == round(55 / 60, 2)  # 13:40-14:35, plain hyphen
    # No Summary section → first non-empty line after the header, first sentence.
    assert x.description == "Wrote a one-page resume tailored to the posting."
    assert x.project is None  # no /code/ repo in Where → no prefix


def test_empty_block_yields_blank_description_and_no_hours():
    sessions = parse_work_log("## Session 1\n\n", D)
    assert len(sessions) == 1
    assert sessions[0].hours is None
    assert sessions[0].description == ""


# --- the import: note + rows + edges + index, via the MCP lane ---------------


@pytest.fixture(autouse=True)
def isolated_stores(tmp_path):
    """Every test gets its own on-disk data dir — server.init() repoints the
    module-level stores the @mcp.tool() functions call into. ~/.quintacle and
    ~/work-logs are never touched."""
    s.init(tmp_path)
    yield


def _seed_entity_notes():
    s.kb_create_entry(folder="Projects", title="Quintacle", content="Project hub: the external brain.")
    s.kb_create_entry(folder="Career", title="Minfy", content="Employer hub.")


def _auto_rows(iso: str):
    return s.db_conn.execute(
        "SELECT * FROM activity_log WHERE date = ? AND source = ? ORDER BY id", (iso, WORKLOG_SOURCE)
    ).fetchall()


def test_import_creates_verbatim_note_and_exact_rows():
    _seed_entity_notes()

    result = s.import_work_log(for_date="2026-10-19", content=MULTI)

    assert result["folder"] == "daily-log/work-logs"
    assert result["slug"] == "work-log-2026-10-19"
    assert result["sessions_parsed"] == 3
    assert result["rows_written"] == 3
    assert result["rows_skipped"] == 0
    assert "ledger_id" in result

    entry = s.kb_get_entry(folder="daily-log/work-logs", slug="work-log-2026-10-19")
    assert entry["title"] == "Work log - 2026-10-19"
    assert MULTI.strip() in entry["content"]  # full text verbatim in the body
    assert entry["fields"] == {"date": "2026-10-19", "kind": "work-log"}

    rows = _auto_rows("2026-10-19")
    assert [r["hours"] for r in rows] == [1.75, 1.0, 4.25]  # exact, computed in code
    assert {r["category"] for r in rows} == {"productivity"}
    assert rows[0]["description"].startswith("AWS_Hackathon_Minfy: Deployed the Minfy hackathon agent")
    assert rows[1]["description"].startswith("Quintacle: Built the decided stocks wave")
    assert rows[2]["description"].startswith("Quintacle: Fired five build waves")


def test_sessions_without_hours_are_skipped_never_guessed():
    result = s.import_work_log(for_date="2026-10-15", content=UNPARSEABLE_TIMES)
    assert result["sessions_parsed"] == 2
    assert result["rows_written"] == 0
    assert result["rows_skipped"] == 2
    assert _auto_rows("2026-10-15") == []


def test_mentions_edges_form_to_seeded_entity_notes():
    _seed_entity_notes()
    assert mentioned_entity_titles(s.kb_store, MULTI) == ["Minfy", "Quintacle"]

    s.import_work_log(for_date="2026-10-19", content=MULTI)

    note_id = "note:daily-log/work-logs/work-log-2026-10-19"
    targets = {
        r["target_id"]
        for r in s.db_conn.execute("SELECT target_id FROM edges WHERE source_id = ?", (note_id,))
    }
    assert "note:projects/quintacle" in targets
    assert "note:career/minfy" in targets


def test_reimport_replaces_rows_and_note_without_duplicating():
    s.import_work_log(for_date="2026-10-19", content=MULTI)
    first_ids = [r["id"] for r in _auto_rows("2026-10-19")]

    # Same day re-imported with one session dropped — the log file grew/changed.
    shorter = MULTI.split("## Session 3")[0]
    result = s.import_work_log(for_date="2026-10-19", content=shorter)

    assert result["rows_replaced"] == len(first_ids) == 3
    rows = _auto_rows("2026-10-19")
    assert len(rows) == 2  # replaced, not stacked
    assert [r["hours"] for r in rows] == [1.75, 1.0]
    # One note file, overwritten by title — never a second entry.
    assert s.kb_store.list_entries("daily-log/work-logs") == ["work-log-2026-10-19"]
    # The markdown side was replaced too (markdown is the source of truth).
    total = s.db_conn.execute(
        "SELECT COUNT(*) AS n FROM activity_log WHERE date='2026-10-19'"
    ).fetchone()["n"]
    assert total == 2


def test_manual_rows_on_the_same_date_survive_reimport():
    manual_id = s.logs_repo.log_activity(date(2026, 10, 19), "productivity", "Reviewed PRs by hand", 2.0)
    s.import_work_log(for_date="2026-10-19", content=MULTI)
    s.import_work_log(for_date="2026-10-19", content=MULTI)

    manual = s.db_conn.execute("SELECT * FROM activity_log WHERE id = ?", (manual_id,)).fetchone()
    assert manual is not None
    assert manual["description"] == "Reviewed PRs by hand"
    assert manual["source"] == ""  # never tagged, never a dedupe candidate
    assert len(_auto_rows("2026-10-19")) == 3


def test_source_tag_survives_sqlite_rebuild_so_dedupe_still_works():
    s.import_work_log(for_date="2026-10-19", content=MULTI)

    # Wipe + rebuild activity_log from the markdown files (sync's rebuild hook).
    rebuild_sqlite_index(s.log_file_store, s.db_conn)
    rebuilt = _auto_rows("2026-10-19")
    assert len(rebuilt) == 3  # the tag came back from frontmatter

    s.import_work_log(for_date="2026-10-19", content=MULTI)
    assert len(_auto_rows("2026-10-19")) == 3  # deduped against rebuilt rows


def test_note_and_rows_are_retrieval_indexed():
    s.import_work_log(for_date="2026-10-19", content=MULTI)

    from quintacle_core import retrieval

    note_hits = retrieval.retrieve("stocks wave worktree", types=["note"])
    assert any(h["id"] == "note:daily-log/work-logs/work-log-2026-10-19" for h in note_hits)

    row_ids = {f"activity:{r['id']}" for r in _auto_rows("2026-10-19")}
    activity_hits = retrieval.retrieve("build waves", types=["activity"])
    assert row_ids & {h["id"] for h in activity_hits}


def test_import_is_one_undoable_ledger_entry():
    manual_id = s.logs_repo.log_activity(date(2026, 10, 19), "productivity", "Manual entry", 1.5)
    first = s.import_work_log(for_date="2026-10-19", content=MULTI)
    second = s.import_work_log(for_date="2026-10-19", content=MULTI.split("## Session 3")[0])
    assert len(_auto_rows("2026-10-19")) == 2

    # Undoing the re-import restores the FIRST import's note, rows and files.
    s.undo_write(second["ledger_id"])
    rows = _auto_rows("2026-10-19")
    assert [r["hours"] for r in rows] == [1.75, 1.0, 4.25]
    entry = s.kb_get_entry(folder="daily-log/work-logs", slug="work-log-2026-10-19")
    assert "## Session 3" in entry["content"]

    # Undoing the first import clears the lane entirely; the manual row stays.
    s.undo_write(first["ledger_id"])
    assert _auto_rows("2026-10-19") == []
    with pytest.raises(ValueError):
        s.kb_get_entry(folder="daily-log/work-logs", slug="work-log-2026-10-19")
    assert s.db_conn.execute("SELECT * FROM activity_log WHERE id = ?", (manual_id,)).fetchone() is not None


# --- the REST door: POST /logs/worklog/import --------------------------------


def test_endpoint_imports_through_the_same_lane(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import quintacle_core.api as api_module

    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path / "app-data")
    client = TestClient(api_module.create_app())

    r = client.post("/logs/worklog/import", json={"date": "2026-10-19", "content": MULTI})
    assert r.status_code == 200
    body = r.json()
    assert body["folder"] == "daily-log/work-logs"
    assert body["slug"] == "work-log-2026-10-19"
    assert body["sessions_parsed"] == 3
    assert body["rows_written"] == 3

    note = client.get(
        "/kb/entry", params={"folder": "daily-log/work-logs", "slug": "work-log-2026-10-19"}
    ).json()
    assert MULTI.strip() in note["content"]
    rows = client.get("/logs/activities/2026-10-19").json()
    assert [x["hours"] for x in rows] == [1.75, 1.0, 4.25]

    # Re-import through the endpoint dedupes the same deterministic way.
    r2 = client.post("/logs/worklog/import", json={"date": "2026-10-19", "content": MULTI})
    assert r2.status_code == 200
    assert len(client.get("/logs/activities/2026-10-19").json()) == 3
