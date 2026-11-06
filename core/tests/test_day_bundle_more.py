"""2026-11-05: the day bundle includes work log, income/net, notes saved, chats."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.nodes.kb import api as kb_api


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    return TestClient(api_module.create_app()), tmp_path


def test_day_has_work_log_income_saved_and_chats(client):
    c, root = client
    today = date.today().isoformat()  # notes are stamped with the real edit time
    store = kb_api.get_store()
    store.write("Daily Log/Work Logs", f"work-log-{today}", "Built the dashboard.")
    c.post("/kb/entries", json={"folder": "Knowledge/Lectures", "title": "Thermo lecture 4", "content": "entropy"})
    assert c.post("/logs/income", json={"date": today, "amount": 1000, "source": "Minfy"}).status_code in (200, 201)
    conv = root / "conversations" / "lamb-meal"
    conv.mkdir(parents=True)
    (conv / f"{today}-1830.md").write_text("---\ntopic: lamb-meal\n---\n### You\nhow much selenium in lamb\n\n### Assistant\n54 mcg\n")
    d = c.get(f"/day/{today}").json()
    assert d["work_log"] and "Built the dashboard" in d["work_log"]["content"]
    assert d["money"]["earned"] == 1000 and d["money"]["net"] == 1000
    titles = [n["title"] for n in d["notes_saved"]]
    assert "Thermo lecture 4" in titles and not any(t.lower().startswith("work log") for t in titles)
    assert d["chats"] and d["chats"][0]["first_message"].startswith("how much selenium")


def test_empty_day_has_empty_new_sections(client):
    c, _ = client
    d = c.get("/day/2001-01-01").json()
    assert d["work_log"] is None and d["notes_saved"] == [] and d["chats"] == [] and d["income"] == []
