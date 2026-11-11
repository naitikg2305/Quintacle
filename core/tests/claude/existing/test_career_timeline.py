"""The Career page read model + hub create/edit (nodes/career/timeline.py).

Sandboxed: tmp DATA_DIR per test, clock pinned, no models anywhere (the
timeline is deterministic). ~/.quintacle is never touched.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from quintacle_core.nodes.career.timeline import date_range, parse_when

TODAY = date(2026, 11, 5)

RECORD = """**Compiled:** 2026-09-30

## 7. Jan 2026 – present · Minfy Technologies, AI Engineer

### 7.1 Generalized AI evaluation test bench (Feb – Aug 2026) `[R]`
**What I did**
- FastAPI service + CLI sharing Pydantic models. `[R]`

**Resume phrasing bank**
- Built an evaluation harness for LLM endpoints. `[R 2026]`

**Tech.** Python, FastAPI.
"""


@pytest.fixture
def app(tmp_path, monkeypatch):
    import quintacle_core.api as api_module
    from quintacle_core import clock

    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.delenv("QUINTACLE_CAREER_RECORD_FOLDER", raising=False)
    monkeypatch.delenv("QUINTACLE_CAREER_RECORD_TITLE", raising=False)
    return TestClient(api_module.create_app())


def kb():
    from quintacle_core.nodes.kb.api import get_store

    return get_store()


def hub(c, **body):
    r = c.post("/career/hubs", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def log(c, day: str, text: str):
    r = c.post("/logs/worklog/import", json={"date": day, "content": f"# {day}\n\n## Session 1\n\n**Summary**\n{text}\n"})
    assert r.status_code == 200, r.text


def seed(c):
    hub(c, type="employer", name="Minfy", location="Tysons, VA", summary="AWS consulting.")
    hub(c, type="role", org="career/minfy", name="Engineering", role="AI Engineer", start="2026-01", end="present",
        bullets=["Load-tested a ranker", "Built an eval bench"])
    hub(c, type="role", org="career/minfy", name="Sales", role="Solutions Architect", start="Sep 2026")
    hub(c, type="contract", name="Acme", start="2025-03", end="2025-06", location="Remote")
    hub(c, type="education", name="UMD", start="2021-08", end="2025-05")


def walk(items):
    for n in items:
        yield n
        yield from walk(n["children"])


def by_title(data, title):
    return next(n for n in walk(data["items"]) if n["title"] == title)


# --- pure date handling ---------------------------------------------------------


def test_parse_when_formats():
    assert parse_when("2026-01") == (date(2026, 1, 1), "month")
    assert parse_when("Jan 2026") == (date(2026, 1, 1), "month")
    assert parse_when("September 2026") == (date(2026, 9, 1), "month")
    assert parse_when("2026-01-15") == (date(2026, 1, 15), "day")
    assert parse_when("2024") == (date(2024, 1, 1), "year")
    assert parse_when("present") == (None, "present")
    assert parse_when("whenever") == (None, "")


def test_date_range_display_and_present():
    assert date_range("2026-01", "present") == {"start": "2026-01-01", "end": None, "present": True, "display": "Jan 2026 – Present"}
    assert date_range("2026-01", None)["present"] is True  # a start with no end is ongoing
    r = date_range("2025-03", "2025-06")
    assert r["present"] is False and r["display"] == "Mar 2025 – Jun 2025"
    assert date_range(None, None)["display"] == ""


# --- create / tree / sort ---------------------------------------------------------


def test_create_hubs_lands_at_folder_hub_paths(app):
    seed(app)
    assert kb().read_meta("career/minfy", "minfy") is not None
    assert kb().read_meta("career/minfy/engineering", "engineering")["fields"]["role"] == "AI Engineer"
    assert kb().read_meta("career/contracts/acme", "acme")["fields"]["type"] == "contract"
    # duplicate refused, role without an org refused, unreadable date refused
    assert app.post("/career/hubs", json={"type": "employer", "name": "Minfy"}).status_code == 409
    assert app.post("/career/hubs", json={"type": "role", "name": "X"}).status_code == 400
    assert app.post("/career/hubs", json={"type": "role", "org": "career/nope", "name": "X"}).status_code == 404
    assert app.post("/career/hubs", json={"type": "employer", "name": "Z", "start": "someday"}).status_code == 400


def test_timeline_nests_roles_sorts_current_first_and_derives_org_range(app):
    seed(app)
    data = app.get("/career/timeline").json()
    titles = [n["title"] for n in data["items"]]
    assert titles == ["Minfy", "Acme", "UMD"]  # present first, then most recent end (Jun > May 2025)
    minfy = data["items"][0]
    assert minfy["type"] == "employer"
    assert [c["title"] for c in minfy["children"]] == ["Sales", "Engineering"]  # both present; later start first
    assert all(c["type"] == "role" for c in minfy["children"])
    assert minfy["range"]["present"] and minfy["range"]["display"] == "Jan 2026 – Present"
    assert minfy["range"].get("derived") is True
    eng = by_title(data, "Engineering")
    assert eng["bullets"] == ["Load-tested a ranker", "Built an eval bench"]
    assert by_title(data, "Acme")["type"] == "contract"
    assert data["counts"]["employer"] == 1 and data["counts"]["contract"] == 1 and data["counts"]["education"] == 1


def test_root_level_career_notes_are_not_timeline_hubs(app):
    assert app.post("/kb/entries", json={"folder": "Career", "title": "Loose note", "content": "x"}).status_code == 200
    seed(app)
    assert "Loose note" not in [n["title"] for n in walk(app.get("/career/timeline").json()["items"])]


# --- edit ---------------------------------------------------------------------------


def test_put_fields_merges_clears_and_validates(app):
    seed(app)
    r = app.put("/career/hubs/career/minfy/engineering/fields", json={"end": "2026-10", "location": "Tysons"})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["range"]["display"] == "Jan 2026 – Oct 2026" and v["location"] == "Tysons"
    assert v["bullets"] == ["Load-tested a ranker", "Built an eval bench"]  # untouched
    v = app.put("/career/hubs/career/minfy/engineering/fields", json={"bullets": [], "location": ""}).json()
    assert v["bullets"] == [] and v["location"] == ""
    assert "bullets" not in kb().read_meta("career/minfy/engineering", "engineering")["fields"]
    assert app.put("/career/hubs/career/minfy/engineering/fields", json={"type": "boss"}).status_code == 400
    assert app.put("/career/hubs/career/nope/fields", json={"end": "present"}).status_code == 404
    # the body is untouched by a fields edit
    assert "AWS consulting." in kb().read("career/minfy", "minfy")


# --- work logs / files / record -----------------------------------------------------


def test_worklog_days_count_and_role_needs_org_colink(app):
    seed(app)
    log(app, "2026-10-01", "Minfy: sales call with a prospect.")
    log(app, "2026-10-02", "Minfy engineering: fixed the Spark pipeline.")
    log(app, "2026-10-03", "Sales tax research for the house.")  # no Minfy: Sales must NOT count it
    log(app, "2026-11-04", "Minfy standup.")
    data = app.get("/career/timeline").json()
    sales = by_title(data, "Sales")
    assert sales["activity"]["days"] == 1 and sales["activity"]["last"] == ["2026-10-01"]
    minfy = by_title(data, "Minfy")
    assert minfy["activity"]["days"] == 3
    assert minfy["activity"]["last"] == ["2026-11-04", "2026-10-02", "2026-10-01"]
    spark = minfy["activity"]["spark"]
    assert len(spark) == 12 and spark[-1] == {"month": "2026-11", "days": 1} and spark[-2] == {"month": "2026-10", "days": 2}


def test_private_worklogs_never_count(app):
    seed(app)
    log(app, "2026-10-01", "Minfy: sales call.")
    kb().set_private("daily-log/work-logs", "work-log-2026-10-01", True)
    assert by_title(app.get("/career/timeline").json(), "Minfy")["activity"]["days"] == 0


def test_files_in_hub_folder_are_listed_but_child_roles_are_not(app):
    seed(app)
    assert app.post("/kb/entries", json={"folder": "Career/Minfy", "title": "Offer letter", "content": "Dear..."}).status_code == 200
    kb().save_asset("career/minfy", "offer.pdf", b"%PDF-1.4")
    minfy = by_title(app.get("/career/timeline").json(), "Minfy")
    names = {(f["kind"], f["name"]) for f in minfy["files"]}
    assert ("note", "Offer letter") in names and ("file", "offer.pdf") in names
    assert not any(f["kind"] == "folder" and f["name"] in {"engineering", "sales"} for f in minfy["files"])
    assert minfy["file_count"] == 2


def test_record_entry_bullets_when_mapped(app):
    assert app.post("/career/record/import", json={"content": RECORD}).status_code == 200
    seed(app)
    app.put("/career/hubs/career/minfy/engineering/fields", json={"record_entry": "7.1"})
    data = app.get("/career/timeline").json()
    assert data["record_present"] is True
    rec = by_title(data, "Engineering")["record"]
    assert rec["id"] == "7.1" and rec["how"] == "field"
    texts = [b["text"] for b in rec["bullets"]]
    assert "FastAPI service + CLI sharing Pydantic models." in texts
    assert "Built an evaluation harness for LLM endpoints." in texts  # tags stripped
    assert by_title(data, "Acme")["record"] is None


def test_updater_endpoints_still_work(app):
    seed(app)
    assert app.get("/career/hubs").status_code == 200
    assert app.get("/career/settings").status_code == 200
    # depth-3 role hubs stay out of the updater alias table
    assert "Engineering" not in [h["title"] for h in app.get("/career/hubs").json()]
