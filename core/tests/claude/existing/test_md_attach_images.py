"""2026-11-05: images inside an attached markdown file get attached."""
import io

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.nodes.kb import api as kb_api

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    return TestClient(api_module.create_app())


def test_remote_and_own_images_in_md_attachment_are_attached(client, monkeypatch):
    # an existing own photo the chat linked to
    r = client.post("/kb/entries/with-asset", data={"folder": "Media", "title": "Lake", "content": "lake"},
                    files=[("files", ("lake.png", io.BytesIO(PNG), "image/png"))])
    assert r.status_code == 200

    class Resp:
        headers = {"Content-Type": "image/jpeg"}

        def read(self):
            return b"\xff\xd8\xff" + b"1" * 32

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(kb_api.urllib.request, "urlopen", lambda req, timeout=None: Resp())
    md = (
        "# Austria\n\n![Eiffel Tower](https://upload.wikimedia.org/x/Eiffel.jpg)\n\n"
        "![my lake](http://localhost:8000/kb/asset?folder=media&path=assets/lake.png&open=lake)\n"
        "![bad](notaurl)\n"
    )
    r = client.post("/kb/entries/with-asset", data={"folder": "Fun/Travel", "title": "Austria chat", "content": "Trip notes"},
                    files=[("files", ("chat-draft.md", io.BytesIO(md.encode()), "text/markdown"))])
    assert r.status_code == 200
    store = kb_api.get_store()
    full = store.read_full("fun/travel", "austria-chat")
    body = full["content"]
    assert "![](assets/eiffel-tower.jpg)" in body and "![](assets/my-lake.png)" in body
    assert store.read_asset("fun/travel", "assets/eiffel-tower.jpg").startswith(b"\xff\xd8")
    assert store.read_asset("fun/travel", "assets/my-lake.png") == PNG
    saved_md = store.read_asset("fun/travel", "assets/chat-draft.md").decode()
    assert "](eiffel-tower.jpg)" in saved_md and "](my-lake.png)" in saved_md and "](notaurl)" in saved_md


def test_failed_download_leaves_link(client, monkeypatch):
    def boom(*a, **k):
        raise TimeoutError
    monkeypatch.setattr(kb_api.urllib.request, "urlopen", boom)
    md = "![x](https://example.com/x.jpg)"
    r = client.post("/kb/entries/with-asset", data={"folder": "Notes", "title": "T", "content": "c"},
                    files=[("files", ("a.md", io.BytesIO(md.encode()), "text/markdown"))])
    assert r.status_code == 200
    assert kb_api.get_store().read_asset("notes", "assets/a.md").decode() == md
