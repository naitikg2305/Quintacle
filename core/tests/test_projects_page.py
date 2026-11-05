"""Projects page (nodes/projects/api.py): deterministic read of
`Projects/<Name>/` folders + owner field edits + project creation. Sandboxed
tmp DATA_DIR per test; ~/.quintacle is never touched."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

TODAY = date(2026, 11, 5)


@pytest.fixture
def c(tmp_path, monkeypatch):
    import quintacle_core.api as api_module
    from quintacle_core import clock

    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    return TestClient(api_module.create_app())


def kb():
    from quintacle_core.nodes.kb.api import get_store

    return get_store()


def note(c, folder, title, content="", fields=None):
    r = c.post("/kb/entries", json={"folder": folder, "title": title, "content": content, "fields": fields})
    assert r.status_code == 200, r.text
    return r.json()


def test_empty_kb_lists_nothing(c):
    assert c.get("/projects").json() == []
    assert c.get("/projects/nope").status_code == 404


def test_folder_project_gathers_notes_files_and_status(c):
    note(c, "Projects/Rover", "Rover", "An autonomous rover.\n\nMore text.",
         fields={"status": "Finished", "repo": "https://github.com/x/rover", "stack": "ROS, Python"})
    note(c, "Projects/Rover", "Wiring", "Pin map for the motor driver.")
    note(c, "Projects/Rover/Design", "Chassis", "Chassis notes.")
    store = kb()
    store.save_asset("projects/rover", "card.stl", b"solid x\nendsolid x\n")
    store.save_asset("projects/rover", "photo.jpg", b"\xff\xd8jpg")
    store.save_asset("projects/rover", "report.pdf", b"%PDF-1.4")
    store.save_asset("projects/rover", "demo.mp4", b"vid")
    store.save_asset("projects/rover/design", "frame.3mf", b"pk")

    [p] = c.get("/projects").json()
    assert p["slug"] == "rover" and p["title"] == "Rover"
    assert p["status"] == "done"  # synonym normalized
    assert p["repo"] == "https://github.com/x/rover"
    assert p["stack"] == ["ROS", "Python"]
    assert p["summary"] == "An autonomous rover."
    assert p["counts"] == {"notes": 2, "model": 2, "image": 1, "pdf": 1, "doc": 0, "video": 1, "other": 0, "worklogs": 0}
    # card.stl wins (the website's convention)
    assert p["card"] == {"kind": "stl", "folder": "projects/rover", "path": "assets/card.stl"}

    d = c.get("/projects/rover").json()
    assert {n["title"] for n in d["notes"]} == {"Wiring", "Chassis"}
    chassis = next(n for n in d["notes"] if n["title"] == "Chassis")
    assert chassis["subfolder"] == "design" and "Chassis notes." in chassis["content"]
    paths = {f["path"] for f in d["files"]}
    assert "design/assets/frame.3mf" in paths and "assets/report.pdf" in paths
    # every path reads back through the existing asset endpoint
    for f in d["files"]:
        r = c.get("/kb/asset", params={"folder": f["folder"], "path": f["path"]})
        assert r.status_code == 200, f
    assert d["body"].startswith("An autonomous rover.")


def test_default_status_cover_field_and_root_note_project(c):
    note(c, "Projects/Quintacle", "Quintacle", "Life OS.")
    kb().save_asset("projects/quintacle", "shot.png", b"png")
    kb().save_asset("projects/quintacle", "other.png", b"png")
    kb().set_fields("projects/quintacle", "quintacle", {"cover": "assets/other.png"})
    note(c, "Projects", "Old Idea", "Just a note.", fields={"status": "idea"})

    rows = {p["slug"]: p for p in c.get("/projects").json()}
    assert rows["quintacle"]["status"] == "doing"
    assert rows["quintacle"]["card"]["path"] == "assets/other.png"
    assert rows["old-idea"]["status"] == "planned"
    assert rows["old-idea"]["folder"] == "projects"
    # doing sorts before planned
    assert [p["slug"] for p in c.get("/projects").json()] == ["quintacle", "old-idea"]


def test_folder_without_hub_lists_and_first_edit_creates_hub(c):
    kb().save_asset("projects/navigatr", "headset.stl", b"solid\nendsolid\n")
    [p] = c.get("/projects").json()
    assert p["hub"] is None and p["title"] == "Navigatr"
    assert p["card"]["kind"] == "stl"

    r = c.put("/projects/navigatr/fields", json={"status": "done", "summary": "Wearable nav aid"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["hub"] == {"folder": "projects/navigatr", "slug": "navigatr"}
    assert d["status"] == "done" and d["summary"] == "Wearable nav aid"


def test_put_fields_merges_and_clears(c):
    note(c, "Projects/Rover", "Rover", "Body.", fields={"repo": "https://github.com/x/rover"})
    before = kb().read_meta("projects/rover", "rover")["edited"]
    r = c.put("/projects/rover/fields", json={"stack": ["C++", " ROS "], "status": "planned", "public_repo": "https://github.com/me/rover"})
    d = r.json()
    assert d["stack"] == ["C++", "ROS"] and d["status"] == "planned" and d["repo"] == "https://github.com/x/rover"
    assert d["public_repo"] == "https://github.com/me/rover"
    # an alias/field edit is not a content edit
    assert kb().read_meta("projects/rover", "rover")["edited"] == before
    d = c.put("/projects/rover/fields", json={"repo": "", "stack": []}).json()
    assert d["repo"] is None and d["stack"] == []
    assert c.put("/projects/rover/fields", json={"status": "bogus"}).status_code == 422
    # the career alias table sees the shared public_repo field
    hubs = {h["slug"]: h for h in c.get("/career/hubs").json()}
    assert hubs["rover"]["public_repo"] == "https://github.com/me/rover"


def test_create_project(c):
    r = c.post("/projects", json={"name": "Self Balance Bot", "status": "done", "stack": "Arduino, C", "description": "Two wheels."})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["slug"] == "self-balance-bot" and d["folder"] == "projects/self-balance-bot"
    assert d["hub"] == {"folder": "projects/self-balance-bot", "slug": "self-balance-bot"}
    assert d["status"] == "done" and d["stack"] == ["Arduino", "C"] and d["body"].startswith("Two wheels.")
    assert c.post("/projects", json={"name": "self balance bot"}).status_code == 409
    assert c.post("/projects", json={"name": "  "}).status_code == 400
    # defaults to doing
    assert c.post("/projects", json={"name": "Next Thing"}).json()["status"] == "doing"


def test_related_work_logs_via_graph_and_links(c):
    note(c, "Projects/Quintacle", "Quintacle", "Life OS.")
    log = "# 2026-11-03\n\n## Session 1\n\n**Session:** 10:00–12:00 (local) · **Where:** quintacle · **Who:** me\n\n**Summary**\nWorked on Quintacle projects page.\n"
    r = c.post("/logs/worklog/import", json={"date": "2026-11-03", "content": log})
    assert r.status_code == 200, r.text
    # a second log linked only by frontmatter links
    note(c, "Daily Log/Work Logs", "Work log - 2026-11-04", "Misc.")
    from quintacle_core.markdown_paths import resolve_nested
    import frontmatter

    path = resolve_nested(kb().root, "daily-log/work-logs") / "work-log-2026-11-04.md"
    post = frontmatter.loads(path.read_text())
    post["links"] = ["Quintacle"]
    path.write_text(frontmatter.dumps(post))

    d = c.get("/projects/quintacle").json()
    dates = [w["date"] for w in d["worklogs"]]
    assert dates[:2] == ["2026-11-04", "2026-11-03"]
    assert d["counts"]["worklogs"] == len(dates) and d["last_worklog"] == "2026-11-04"
    # work logs are not repeated as generic related items
    assert not any(x["id"].startswith("note:daily-log/work-logs/") for x in d["related"])


def test_asset_folder_under_projects_is_not_a_project(c):
    note(c, "Projects", "Solo", "Single note.")
    kb().add_asset_to_entry("projects", "solo", "pic.png", b"png")
    rows = c.get("/projects").json()
    assert [p["slug"] for p in rows] == ["solo"]
    assert rows[0]["counts"]["image"] == 1 and rows[0]["card"]["path"] == "assets/pic.png"
