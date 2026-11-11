"""The owner's own photos inline in chat (my_photos.py, 2026-11-05): photo
notes in the context get {{myphoto:Pn}} handles, tags become /kb/asset
images, unknown handles vanish, a photo request the model ignores still gets
a gallery, and a private photo never reaches a cloud request. Sandbox only —
seeded registries, geocode stubbed, every model runner stubbed."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core import retrieval
from quintacle_core.nodes.kb import chat, photo_organizer
from quintacle_core.nodes.kb.my_photos import PhotoRegistry, render_my_photos
from quintacle_core.nodes.kb.photo_organizer import GeocodedLocation

from test_photo_place import jpeg

VIENNA = (48.2082, 16.3738)
PRAGUE = (50.0755, 14.4378)
RUNNERS = ("_run_anthropic", "_run_openai", "_run_bedrock", "_run_local", "_run_max")
IMG_RE = re.compile(r"!\[[^\]]*\]\((/kb/asset\?[^)\s]+)\)")


@pytest.fixture(autouse=True)
def _reset_retrieval_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    table = {
        round(VIENNA[0], 1): GeocodedLocation(country="Austria", state="Vienna", city="Vienna"),
        round(PRAGUE[0], 1): GeocodedLocation(country="Czechia", state="Prague", city="Prague"),
    }
    monkeypatch.setattr(photo_organizer, "geocode", lambda lat, lon: table[round(lat, 1)])
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    # Seeded registries (CLAUDE.md: entity-grounded, never scratch).
    c.post("/people", json={"name": "Rahul", "category": "friend", "how_met": "college"})
    c.post("/logs/meals", json={"name": "Chipotle bowl", "kcal": 800, "protein_g": 45})
    c.post("/logs/routines", json={"name": "Pull Day", "exercises": ["Deadlift"]})
    c.post("/kb/entries", json={"folder": "Fitness", "title": "Deadlift Cues", "content": "Brace."})
    return c


def commit_photo(client, gps=VIENNA, title="Stephansdom", content="A big cathedral.", private=False):
    form = {"folder": "Media/Photos/2027/May", "title": title, "content": content, "links": ""}
    if private:
        form["private"] = "true"
    res = client.post("/kb/entries/with-asset", data=form, files=[("files", ("p.jpg", jpeg(gps), "image/jpeg"))])
    assert res.status_code == 200, res.text
    out = res.json()
    return f"note:{out['folder']}/{out['slug']}"


def stub(monkeypatch, reply):
    calls: list[str] = []

    def runner(model, messages, kb_text):
        calls.append(kb_text or "")
        return reply(kb_text or "") if callable(reply) else reply

    for name in RUNNERS:
        monkeypatch.setattr(chat, name, runner)
    return calls


def ask(client, text, model=None):
    body = {"messages": [{"role": "user", "content": text}]}
    if model:
        body["model"] = model
    r = client.post("/kb/chat", json=body)
    assert r.status_code == 200, r.text
    return r.json()["reply"]


def handle_for(kb_text, word):
    m = re.search(rf"\[photo:(P\d+)\][^\n]*{word}", kb_text)
    return m and m.group(1)


def test_photo_notes_get_handles_and_the_rule(client, monkeypatch):
    photo = commit_photo(client)
    calls = stub(monkeypatch, "ok")
    ask(client, "photos from Vienna")
    [kb_text] = calls
    assert "## Your photos in this context" in kb_text and "{{myphoto:P1}}" in kb_text
    line = next(l for l in kb_text.split("\n") if l.startswith("[photo:P1]"))
    assert "Stephansdom" in line and "Vienna, Austria" in line and "2027-05-14" in line and photo in line


def test_tag_becomes_asset_image_and_unknown_is_dropped(client, monkeypatch):
    commit_photo(client)
    stub(monkeypatch, lambda kb: f"Here you go:\n\n{{{{myphoto:{handle_for(kb, 'Stephansdom')}}}}}\n{{{{myphoto:P99}}}}\nNice trip.")
    reply = ask(client, "show me Stephansdom")
    imgs = IMG_RE.findall(reply)
    assert len(imgs) == 1
    assert "folder=media%2Fphotos%2F2027%2Fmay" in imgs[0] and "path=assets%2F" in imgs[0] and "open=stephansdom" in imgs[0]
    assert "myphoto" not in reply and "not found in your notes" not in reply
    assert "Nice trip." in reply


def test_fallback_gallery_when_model_ignores_the_instruction(client, monkeypatch):
    commit_photo(client)
    commit_photo(client, gps=PRAGUE, title="Charles Bridge", content="Foggy bridge.")
    stub(monkeypatch, "You were in Vienna in May 2027.")
    reply = ask(client, "photos from Vienna")
    imgs = IMG_RE.findall(reply)
    assert imgs and all("stephansdom" in i for i in imgs)  # ranked to the asked place
    assert reply.startswith("You were in Vienna")
    # no photo request → no gallery
    stub(monkeypatch, "Vienna is lovely.")
    assert not IMG_RE.findall(ask(client, "what did I do in Vienna"))


def test_private_photo_excluded_for_cloud_included_for_local(client, monkeypatch):
    private = commit_photo(client, title="Hotel Secret", content="Vienna hotel room.", private=True)
    calls = stub(monkeypatch, "nothing tagged")
    reply = ask(client, "photos from Vienna hotel", model="claude-sonnet-5-5")
    assert private not in calls[-1] and "Hotel Secret" not in calls[-1]
    assert "hotel-secret" not in reply and not IMG_RE.findall(reply)
    reply = ask(client, "photos from Vienna hotel", model="local:qwen3:8b")
    assert private in calls[-1]
    assert any("hotel-secret" in i for i in IMG_RE.findall(reply))


def test_render_without_registry_strips_tags():
    assert render_my_photos("a {{myphoto:P1}} b", PhotoRegistry(), "photos") == "a  b"
    assert render_my_photos("plain", None) == "plain"
