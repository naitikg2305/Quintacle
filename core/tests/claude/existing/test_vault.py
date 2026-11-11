from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quintacle_core import clock, graph
from quintacle_core import db
from quintacle_core.nodes.kb.store import KBStore
from quintacle_core.nodes.vault import api as vault_api
from quintacle_core.nodes.vault.store import (
    VaultAlreadyInitialized,
    VaultLocked,
    VaultStore,
    WrongPassphrase,
)

SECRET = "hunter2-very-distinctive-secret-xyzzy"


def make_store(tmp_path) -> VaultStore:
    return VaultStore(tmp_path / "vault")


def make_client(tmp_path) -> TestClient:
    app = FastAPI()
    vault_api.init_store(tmp_path / "vault")
    app.include_router(vault_api.router)
    return TestClient(app)


# --- store round trip ---


def test_init_unlock_put_get_round_trip(tmp_path):
    store = make_store(tmp_path)
    store.init("correct horse")
    store.put("GitHub", "GitHub", "naitik", SECRET, "https://github.com", "personal account")

    entry = store.get("GitHub")
    assert entry["name"] == "GitHub"
    assert entry["username"] == "naitik"
    assert entry["secret"] == SECRET
    assert entry["url"] == "https://github.com"
    assert entry["notes"] == "personal account"
    assert entry["updated_at"]

    # A fresh store over the same directory (new process) unlocks and reads.
    reopened = make_store(tmp_path)
    assert reopened.initialized()
    reopened.unlock("correct horse")
    assert reopened.get("GitHub")["secret"] == SECRET


def test_init_twice_refuses(tmp_path):
    store = make_store(tmp_path)
    store.init("one")
    with pytest.raises(VaultAlreadyInitialized):
        store.init("two")


def test_wrong_passphrase_fails_cleanly_and_entries_stay_unreadable(tmp_path):
    store = make_store(tmp_path)
    store.init("right")
    store.put("GitHub", "GitHub", "naitik", SECRET, "", "")
    store.lock()

    with pytest.raises(WrongPassphrase):
        store.unlock("wrong")
    # The failed attempt never left a usable key behind.
    assert store.locked()
    with pytest.raises(VaultLocked):
        store.get("GitHub")


def test_locked_store_refuses_every_entry_operation(tmp_path):
    store = make_store(tmp_path)
    store.init("pw")
    store.put("GitHub", "GitHub", "u", SECRET, "", "")
    store.lock()

    for op in (
        lambda: store.list(),
        lambda: store.get("GitHub"),
        lambda: store.put("Other", "Other", "u", "s", "", ""),
        lambda: store.delete("GitHub"),
    ):
        with pytest.raises(VaultLocked):
            op()


def test_auto_lock_expires_without_sleeping(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    t0 = clock.now()
    monkeypatch.setattr(clock, "now", lambda: t0)
    store.init("pw")
    store.put("GitHub", "GitHub", "u", SECRET, "", "")

    # A successful operation refreshes the window...
    monkeypatch.setattr(clock, "now", lambda: t0 + timedelta(seconds=250))
    assert store.list()

    # ...so 250s after THAT the vault is still open, but past 300s it isn't.
    monkeypatch.setattr(clock, "now", lambda: t0 + timedelta(seconds=500))
    assert not store.locked()
    monkeypatch.setattr(clock, "now", lambda: t0 + timedelta(seconds=551))
    assert store.locked()
    with pytest.raises(VaultLocked):
        store.get("GitHub")


def test_delete_removes_the_entry(tmp_path):
    store = make_store(tmp_path)
    store.init("pw")
    store.put("GitHub", "GitHub", "u", SECRET, "", "")
    assert store.delete("GitHub") is True
    assert store.get("GitHub") is None
    assert store.delete("GitHub") is False


# --- plaintext never on disk ---


def test_nothing_under_vault_dir_contains_the_plaintext_secret(tmp_path):
    store = make_store(tmp_path)
    store.init("pw")
    store.put("GitHub", "GitHub", "naitik", SECRET, "https://github.com", "note text")

    files = [p for p in (tmp_path / "vault").rglob("*") if p.is_file()]
    assert files  # meta.json + the entry at minimum
    for path in files:
        data = path.read_bytes()
        assert SECRET.encode() not in data
        # Entry fields besides the secret are sensitive too — all encrypted.
        if path.suffix == ".enc":
            assert b"naitik" not in data
            assert b"github" not in data.lower()


def test_list_never_includes_the_secret_field(tmp_path):
    store = make_store(tmp_path)
    store.init("pw")
    store.put("GitHub", "GitHub", "naitik", SECRET, "https://github.com", "")

    rows = store.list()
    assert rows == [
        {
            "slug": "github",
            "name": "GitHub",
            "username": "naitik",
            "url": "https://github.com",
            "updated_at": rows[0]["updated_at"],
        }
    ]
    assert all("secret" not in row for row in rows)


# --- invisibility: KB / search / graph never see vault content ---


def test_kb_store_never_sees_the_sibling_vault_dir(tmp_path):
    # Same data_dir layout as the real app: kb/ and vault/ are siblings.
    kb = KBStore(tmp_path / "kb")
    kb.write("Fitness", "Deadlift Cues", "Brace before you pull.")
    vault = make_store(tmp_path)
    vault.init("pw")
    vault.put("GitHub", "GitHub", "naitik", SECRET, "https://github.com", "")

    assert kb.list_folders() == ["fitness"]
    assert kb.search(SECRET) == []
    assert kb.search("github") == []
    assert all("vault" not in e["folder"] for e in kb.graph_entries())
    assert all("vault" not in e["folder"] for e in kb.notes_index())


def test_graph_rebuild_picks_up_no_vault_nodes_or_edges(tmp_path):
    conn = db.connect(tmp_path / "quintacle.db")
    graph.init_graph_store(tmp_path, conn)
    vault = make_store(tmp_path)
    vault.init("pw")
    vault.put("GitHub", "GitHub", "naitik", SECRET, "https://github.com", "")

    assert graph.rebuild_from_folder(tmp_path, conn) == 0
    assert graph.get_graph_store().all() == []


# --- API surface ---


def test_api_full_flow(tmp_path):
    client = make_client(tmp_path)

    assert client.get("/vault/status").json() == {
        "initialized": False,
        "locked": True,
        "auto_lock_seconds_remaining": None,
    }

    # Every entry endpoint refuses while locked/uninitialized.
    assert client.get("/vault/entries").status_code == 401
    assert client.get("/vault/entries/github").status_code == 401
    assert client.put("/vault/entries/github", json={"name": "GitHub", "secret": SECRET}).status_code == 401
    assert client.delete("/vault/entries/github").status_code == 401

    res = client.post("/vault/init", json={"passphrase": "pw"})
    assert res.status_code == 200
    status = res.json()
    assert status["initialized"] and not status["locked"]
    assert 0 < status["auto_lock_seconds_remaining"] <= 300
    assert client.post("/vault/init", json={"passphrase": "pw"}).status_code == 409

    put = client.put(
        "/vault/entries/github",
        json={"name": "GitHub", "username": "naitik", "secret": SECRET, "url": "https://github.com", "notes": "n"},
    )
    assert put.status_code == 200
    assert "secret" not in put.json()

    rows = client.get("/vault/entries").json()
    assert [r["slug"] for r in rows] == ["github"]
    assert all("secret" not in r for r in rows)

    entry = client.get("/vault/entries/github").json()
    assert entry["secret"] == SECRET

    assert client.get("/vault/entries/nope").status_code == 404

    # Lock clears access immediately.
    assert client.post("/vault/lock").json()["locked"] is True
    assert client.get("/vault/entries").status_code == 401
    assert client.get("/vault/entries/github").status_code == 401

    assert client.post("/vault/unlock", json={"passphrase": "wrong"}).status_code == 403
    assert client.get("/vault/entries").status_code == 401
    assert client.post("/vault/unlock", json={"passphrase": "pw"}).status_code == 200
    assert client.get("/vault/entries/github").json()["secret"] == SECRET

    assert client.delete("/vault/entries/github").status_code == 200
    assert client.get("/vault/entries").json() == []


def test_api_unlock_before_init_conflicts(tmp_path):
    client = make_client(tmp_path)
    assert client.post("/vault/unlock", json={"passphrase": "pw"}).status_code == 409


def test_api_auto_lock_expiry(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    t0 = clock.now()
    monkeypatch.setattr(clock, "now", lambda: t0)
    client.post("/vault/init", json={"passphrase": "pw"})
    client.put("/vault/entries/github", json={"name": "GitHub", "secret": SECRET})

    monkeypatch.setattr(clock, "now", lambda: t0 + timedelta(seconds=301))
    assert client.get("/vault/status").json()["locked"] is True
    assert client.get("/vault/entries").status_code == 401
