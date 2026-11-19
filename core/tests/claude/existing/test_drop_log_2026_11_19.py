"""2026-11-19 (owner: "lets have a save log this way we can test better"):
every /drop proposal and every Save on the drop page is appended to
<DATA_DIR>/drop-log/YYYY-MM-DD.jsonl (drop_log.py). No model is called here:
the private drop path is zero-model, the local_unavailable path is forced by
a faked classifier."""
import json

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core import clock, drop_log
from quintacle_core.nodes.kb.chat import OllamaError


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    c.data_dir = tmp_path
    return c


def _lines(data_dir):
    path = data_dir / "drop-log" / f"{clock.today().isoformat()}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_append_adds_ts_kind_and_cleans_big_fields(client):
    drop_log.append("drop", {"text": "a" * 25_000,
                             "entries": [{"type": "kb_entry", "img": "data:image/png;base64,AAAA", "raw": b"xyz"}]})
    (rec,) = _lines(client.data_dir)
    assert rec["kind"] == "drop" and rec["ts"].startswith(clock.today().isoformat())
    assert rec["text"].startswith("a" * 20_000) and "truncated 5000 chars" in rec["text"]
    assert rec["entries"][0]["img"] == "<data-url omitted>"
    assert rec["entries"][0]["raw"] == "<3 bytes omitted>"


def test_append_never_raises(monkeypatch, tmp_path):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    monkeypatch.setattr(drop_log, "_data_dir", blocker)  # drop-log/ cannot be created under a file
    drop_log.append("drop", {"text": "hi"})  # must not raise


def test_private_drop_logs_placeholders_and_returns_drop_id(client):
    r = client.post("/drop", data={"text": "my secret diary", "private_skip_ai": "true"},
                    files={"file": ("n.txt", b"hello world", "text/plain")})
    assert r.status_code == 200
    drop_id = r.json()["drop_id"]
    assert len(drop_id) == 32
    (rec,) = _lines(client.data_dir)
    assert rec["kind"] == "drop" and rec["drop_id"] == drop_id
    assert rec["text"] is None
    assert rec["entries"] == [{"type": "kb_entry", "private": True}]
    assert rec["files"] == [{"name": "n.txt", "size": 11}]
    assert "secret" not in json.dumps(rec)


def test_local_unavailable_drop_is_logged_with_drop_id(client, monkeypatch):
    def boom(*a, **k):
        raise OllamaError("daemon down")

    monkeypatch.setattr(api_module, "classify_text_file_type", boom)
    monkeypatch.setattr(api_module, "describe_drop", lambda *a, **k: "some text")
    r = client.post("/drop", data={"text": "hello", "provider": "local"},
                    files={"file": ("a.docx", b"not really a docx", "application/octet-stream")})
    body = r.json()
    assert r.status_code == 200 and body["entries"] == [] and body["local_unavailable"]
    (rec,) = _lines(client.data_dir)
    assert rec["drop_id"] == body["drop_id"]
    assert rec["local_unavailable"] == body["local_unavailable"]
    assert rec["text"] == "hello" and rec["provider_requested"] == "local"


def test_save_endpoint_logs_saved_and_deleted_with_privacy(client):
    r = client.post("/drop-log/save", json={
        "drop_id": "abc",
        "saved": [{"type": "kb_entry", "private": True, "content": "secret"}, {"type": "finance", "amount": 4.5}],
        "deleted": [{"type": "todo", "title": "x"}],
        "provider_used": "local",
    })
    assert r.json() == {"ok": True}
    (rec,) = _lines(client.data_dir)
    assert rec["kind"] == "save" and rec["drop_id"] == "abc" and rec["provider_used"] == "local"
    assert rec["saved"] == [{"type": "kb_entry", "private": True}, {"type": "finance", "amount": 4.5}]
    assert rec["deleted"] == [{"type": "todo", "title": "x"}]


def test_save_endpoint_bad_body_is_ok_false_not_500(client):
    r = client.post("/drop-log/save", json={"saved": "not a list"})
    assert r.status_code == 200 and r.json() == {"ok": False}


def test_recent_returns_newest_last(client):
    for i in range(5):
        drop_log.append("save", {"drop_id": str(i)})
    r = client.get("/drop-log/recent", params={"limit": 3})
    assert [x["drop_id"] for x in r.json()["records"]] == ["2", "3", "4"]
