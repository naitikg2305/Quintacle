"""/business — the Business Ideas board: deterministic reads over
`Business Ideas/<Idea>/` (any file type belongs to the idea) plus the two
direct-edit writes. Sandboxed DATA_DIR per test; no model is called."""
from __future__ import annotations

from datetime import date

import frontmatter
import pytest
from fastapi.testclient import TestClient

from quintacle_core.nodes.business import ideas as ideas_mod
from quintacle_core.nodes.kb.llm import SEED_FOLDERS, _FOLDER_RULE

TODAY = date(2026, 11, 5)


@pytest.fixture
def client(tmp_path, monkeypatch):
    import quintacle_core.api as api_module
    from quintacle_core import clock

    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    c = TestClient(api_module.create_app())
    c.kb_root = tmp_path / "data" / "kb"
    return c


def _create(client, **kw):
    r = client.post("/business/ideas", json={"title": "Solar Kiosk", "summary": "Phone charging at bus stops", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_create_writes_folder_hub(client):
    idea = _create(client, status="exploring", tags="hardware, b2g", market="cities")
    assert idea["slug"] == "solar-kiosk"
    assert idea["folder"] == "business-ideas/solar-kiosk"
    hub = client.kb_root / "business-ideas" / "solar-kiosk" / "solar-kiosk.md"
    post = frontmatter.loads(hub.read_text())
    assert post["fields"] == {
        "status": "exploring",
        "created": "2026-11-05",
        "summary": "Phone charging at bus stops",
        "market": "cities",
        "tags": ["hardware", "b2g"],
    }
    assert idea["has_hub"] and idea["status"] == "exploring" and idea["tags"] == ["hardware", "b2g"]
    # The hub is a normal KB note (Browse/search see it).
    assert client.get("/kb/entry", params={"folder": idea["folder"], "slug": "solar-kiosk"}).status_code == 200


def test_create_rejects_duplicate_and_bad_status(client):
    _create(client)
    assert client.post("/business/ideas", json={"title": "solar kiosk"}).status_code == 409
    assert client.post("/business/ideas", json={"title": "Other", "status": "maybe"}).status_code == 400
    assert client.post("/business/ideas", json={"title": "!!!"}).status_code == 400


def test_all_file_types_belong_to_the_idea(client):
    _create(client)
    d = client.kb_root / "business-ideas" / "solar-kiosk"
    (d / "assets").mkdir()
    for name in ("mock.png", "pitch.pdf", "plan.docx", "costs.xlsx", "data.csv", "case.stl", "demo.mp4", "blob.bin"):
        (d / "assets" / name).write_bytes(b"x")
    (d / "competitor.url").write_text("[InternetShortcut]\nURL=https://example.com/rival\n")
    (d / "market-notes.md").write_text("# Market notes\n\nSee https://example.org/report.\n")
    (d / "research").mkdir()
    (d / "research" / "interview.md").write_text("# Interview\n\nTalked to a driver.\n[asset](assets/x.png)\n")
    (d / "_view.json").write_text("{}")  # plumbing, not a member file

    listed = client.get("/business/ideas").json()
    assert listed["statuses"] == list(ideas_mod.STATUSES)
    [card] = listed["ideas"]
    assert card["file_counts"] == {
        "markdown": 2,
        "image": 1,
        "video": 1,
        "pdf": 1,
        "doc": 1,
        "spreadsheet": 2,
        "model": 1,
        "link": 1,
        "other": 1,
    }
    assert card["file_total"] == 11  # hub itself excluded
    assert card["last_edited"]

    detail = client.get("/business/ideas/solar-kiosk").json()
    md = {m["slug"]: m for m in detail["files"]["markdown"]}
    assert md["market-notes"]["folder"] == "business-ideas/solar-kiosk"
    assert md["interview"]["folder"] == "business-ideas/solar-kiosk/research"
    assert md["interview"]["title"] == "Interview"
    assert detail["files"]["link"][0]["url"] == "https://example.com/rival"
    assert detail["files"]["pdf"][0]["path"] == "assets/pitch.pdf"
    assert "https://example.org/report" in detail["links"]
    # Paths resolve through the normal clamped KB asset route.
    r = client.get("/kb/asset", params={"folder": detail["folder"], "path": "assets/pitch.pdf"})
    assert r.status_code == 200


def test_hubless_folder_is_listed_then_adopted(client):
    d = client.kb_root / "business-ideas" / "dog-cafe"
    d.mkdir(parents=True)
    (d / "menu.pdf").write_bytes(b"x")
    [card] = client.get("/business/ideas").json()["ideas"]
    assert card["has_hub"] is False and card["title"] == "Dog Cafe" and card["status"] == "idea"
    assert client.put("/business/ideas/dog-cafe/fields", json={"status": "parked"}).status_code == 404
    idea = client.post("/business/ideas", json={"title": "Dog Cafe"}).json()
    assert idea["has_hub"] and idea["file_total"] == 1


def test_update_fields_merges_without_restamp(client):
    _create(client)
    hub = client.kb_root / "business-ideas" / "solar-kiosk" / "solar-kiosk.md"
    edited = frontmatter.loads(hub.read_text())["edited"]
    body_before = frontmatter.loads(hub.read_text()).content

    r = client.put("/business/ideas/solar-kiosk/fields", json={"status": "Building", "tags": ["iot"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "building" and r.json()["tags"] == ["iot"]
    r = client.put("/business/ideas/solar-kiosk/fields", json={"summary": ""})
    assert r.json()["summary"] == ""
    post = frontmatter.loads(hub.read_text())
    assert "summary" not in post["fields"] and post["fields"]["status"] == "building"
    assert post["edited"] == edited and post.content == body_before
    assert client.put("/business/ideas/solar-kiosk/fields", json={"status": "nope"}).status_code == 400
    assert client.get("/business/ideas/missing").status_code == 404


def test_unknown_status_reads_as_idea(client):
    _create(client)
    hub = client.kb_root / "business-ideas" / "solar-kiosk" / "solar-kiosk.md"
    post = frontmatter.loads(hub.read_text())
    post["fields"]["status"] = "who knows"
    hub.write_text(frontmatter.dumps(post))
    assert client.get("/business/ideas/solar-kiosk").json()["status"] == "idea"


def test_sorter_offers_business_ideas():
    assert "Business Ideas" in SEED_FOLDERS
    assert "Business Ideas/<Idea>" in _FOLDER_RULE
