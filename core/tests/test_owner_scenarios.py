"""The owner's hands-on testing (sprint 1, 2026-11-05..07), replayed as
regression checks — so a later fix can't silently break something he already
verified by hand. Source: his testing log ("Master file") and
docs/sprint-1-testing-fixes.md.

Each test is one journey he actually took, end to end through the real app
(TestClient over create_app with a tmp DATA_DIR), with SYNTHETIC stand-ins
for his files: a hand-built PDF, PIL-drawn images, short markdown. None of
his real documents/photos are in the repo. Models are stubbed at the
llm_dispatch seam (the local backend answers with canned schema instances;
the cloud backend raises), OCR is stubbed with fixed text, geocoding is a
lookup table — deterministic and network-free.

Already covered elsewhere, NOT duplicated here (see those files):
- chat meal plan + nutrition summary -> meal_composition proposal, and a
  plain log -> no preset: test_drop_presets.py
  (test_chat_meal_plan_with_nutrition_summary_is_a_meal_2026_11_07,
  test_plain_log_text_gets_no_extra_and_no_extractor_call)
- private notes never in cloud chat context / sort suggesters / MCP:
  test_private_notes.py (only the itinerary-shaped MCP case is replayed below)
- concurrent requests on the shared SQLite connection: test_db_concurrency.py
- label parser line-level cases (%DV, EU panels, OCR noise):
  test_label_parser.py; receipt parser variants: test_local_image_pipeline.py
- Move to Planned edge cases (shared assets, 409, graph re-keying):
  test_travel_states.py
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import quintacle_core.api as api_module
import quintacle_core.llm_dispatch as llm_dispatch
from quintacle_core import clock, retrieval
from quintacle_core.graph import get_graph_store
from quintacle_core.nodes.drop_router import _TextFileClassification
from quintacle_core.nodes.kb import api as kb_api
from quintacle_core.nodes.kb import drop as kb_drop
from quintacle_core.nodes.kb import photo_organizer
from quintacle_core.nodes.kb.llm import KBSuggestion
from quintacle_core.nodes.kb.photo_organizer import GeocodedLocation
from quintacle_core.nutrition_db import store as usda_store
from quintacle_core.perception import image_policy, image_router, ocr
from quintacle_core.perception.ocr import OcrLine, OcrResult
from quintacle_core.trip_photos import KIND as DURING_TRIP

from test_file_meta import pdf_bytes
from test_photo_place import jpeg

VIENNA = (48.2082, 16.3738)
FIX = Path(__file__).parent / "fixtures" / "usda"

# A synthetic stand-in for the Central Europe itinerary PDF's summary — the
# shape of what he saw (dates, cities, rail, nothing booked), no real details.
ITINERARY_SUMMARY = (
    "A 10-day Central Europe trip plan, May 12-21, 2027: Budapest, Vienna, Salzburg and Prague "
    "by rail. Four hotels shortlisted, nothing booked yet; flights and trains still to confirm."
)


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _fresh_singletons(monkeypatch):
    retrieval._index = None
    monkeypatch.delenv("QUINTACLE_IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("QUINTACLE_INGEST_PROVIDER", raising=False)  # owner default: auto (local first)
    image_policy.set_request_provider(None)
    yield
    retrieval._index = None
    image_policy.set_request_provider(None)


@pytest.fixture
def models(monkeypatch):
    """The local text model, stubbed at llm_dispatch's backend seam: answers
    are looked up by schema class name; every call is recorded. The cloud
    backend fails loudly — the owner's default is local-first."""
    answers: dict[str, object] = {}
    calls: list[dict] = []

    def fake_local(system, user_content, output_format, max_tokens):
        calls.append({"system": system, "user": user_content, "schema": output_format.__name__})
        answer = answers.get(output_format.__name__)
        if answer is None:
            raise llm_dispatch.LocalParseError(f"no canned answer for {output_format.__name__}")
        return answer(user_content) if callable(answer) else answer

    def no_cloud(*a, **k):
        raise AssertionError("cloud was called in a local-first scenario")

    monkeypatch.setattr(llm_dispatch, "_parse_local", fake_local)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", no_cloud)
    return answers, calls


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    # The additive experience/person checks and photo perception are their
    # own tests' business; here they'd only add unrelated model calls.
    monkeypatch.setattr(api_module, "maybe_structure_experience", lambda *a, **k: None)
    monkeypatch.setattr(api_module, "maybe_structure_person_mention", lambda *a, **k: None)
    monkeypatch.setattr(api_module, "perceive_photo", lambda data, mime: None)
    monkeypatch.setattr(image_router, "detect_photo_tags", lambda data: None)
    monkeypatch.setattr(
        photo_organizer, "geocode", lambda lat, lon: GeocodedLocation(country="Austria", state="Vienna", city="Vienna")
    )
    c = TestClient(api_module.create_app())
    # Seeded registries (CLAUDE.md: entity-grounded scenarios, never an empty store).
    c.post("/people", json={"name": "Laura", "category": "friend", "how_met": "college"})
    c.post("/logs/meals", json={"name": "Chipotle bowl", "kcal": 800, "protein_g": 45})
    c.post("/travel/experiences", json={"name": "Cafe Central", "city": "Vienna", "kind": "cafe"})
    c.kb_root = tmp_path / "kb"
    c.data_dir = tmp_path
    return c


def _commit(client, folder, title, content, files, **extra):
    form = {"folder": folder, "title": title, "content": content, "links": "", **extra}
    r = client.post("/kb/entries/with-asset", data=form, files=[("files", f) for f in files])
    assert r.status_code == 200, r.text
    return r.json()


def _note(client, out) -> str:
    return (client.kb_root / out["folder"] / f"{out['slug']}.md").read_text()


def _edges(kind=None):
    return {(e["source_id"], e["target_id"], e["kind"]) for e in get_graph_store().all() if kind in (None, e["kind"])}


# --------------------------------------------------------------- Travel: itinerary PDF


def test_itinerary_pdf_drop_is_read_and_sorted_into_planned_region(client, models, monkeypatch):
    """Master file 'Drop after chat': the Central Europe PDF through Sort with
    AI. Round-1 fix: the sorter may create a trip subfolder and sends
    itineraries to Fun/Travel/Planned/<Region>; the review card shows the
    PDF's own metadata (🗂)."""
    answers, calls = models
    monkeypatch.setattr(kb_drop, "_describe_pdf", lambda data: ITINERARY_SUMMARY)  # the (cloud) PDF reader
    answers["_TextFileClassification"] = _TextFileClassification(is_document=False)
    answers["KBSuggestion"] = KBSuggestion(
        folder="Fun/Travel/Planned/Central Europe", title="Central Europe 2027", content=ITINERARY_SUMMARY
    )
    pdf = pdf_bytes(title=b"(Central Europe trip plan)", pages=4)
    r = client.post("/drop", data={"text": ""}, files={"file": ("itinerary.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider_used"] == "local"
    [entry] = body["entries"]
    assert entry["type"] == "kb_entry" and entry["folder"] == "Fun/Travel/Planned/Central Europe"
    [fm] = entry["file_meta"]
    assert fm["title"] == "Central Europe trip plan" and fm["pages"] == 4 and fm["line"].startswith("🗂 PDF")
    # The sorter saw the PDF's content, and its prompt carries the travel rule.
    sort_call = next(c for c in calls if c["schema"] == "KBSuggestion")
    assert "Budapest, Vienna" in sort_call["user"]
    assert "Fun/Travel/Planned/<Region or Trip>" in sort_call["system"] and "NEW SUBFOLDER" in sort_call["system"]

    # Review -> Save (the PDF rides along), then Travel -> Planned lists it.
    out = _commit(client, entry["folder"], entry["title"], entry["content"], [("itinerary.pdf", pdf, "application/pdf")])
    planned = client.get("/travel/planned").json()
    assert [(p["slug"], p["group"]) for p in planned] == [(out["slug"], "central-europe")]
    text = _note(client, out)
    assert "🗂" in text and "Central Europe trip plan" in text
    got = client.get("/kb/asset", params={"folder": out["folder"], "path": "assets/itinerary.pdf"})
    assert got.status_code == 200 and got.content == pdf
    # Round-1 fix: Planned notes are not experiences.
    assert [e["name"] for e in client.get("/travel/experiences").json()] == ["Cafe Central"]


def test_old_itinerary_in_travel_moves_to_planned_with_its_pdf(client):
    """Round-1 fix: itineraries saved before the Planned tab existed sit
    loose in Fun/Travel; 'Move to Planned' files them, PDFs included."""
    pdf = pdf_bytes(title=b"(Austria plan)")
    out = _commit(client, "Fun/Travel", "Austria Itinerary", "Vienna then Salzburg.", [("austria.pdf", pdf, "application/pdf")])
    assert out["folder"] == "fun/travel"
    assert [u["slug"] for u in client.get("/travel/unsorted").json()] == [out["slug"]]
    assert [e["name"] for e in client.get("/travel/experiences").json()] == ["Cafe Central"]  # not a "city"

    r = client.post("/travel/planned/move", json={"folder": "fun/travel", "slug": out["slug"], "group": "Austria"})
    assert r.status_code == 200, r.text
    moved = r.json()
    assert moved["folder"] == "fun/travel/planned/austria"
    assert client.get("/travel/unsorted").json() == []
    assert [p["slug"] for p in client.get("/travel/planned").json()] == [out["slug"]]
    assert client.get("/kb/asset", params={"folder": moved["folder"], "path": "assets/austria.pdf"}).content == pdf
    assert not (client.kb_root / "fun/travel/assets/austria.pdf").exists()


def test_mcp_push_of_itinerary_pdf_is_ledgered_baked_and_undoable(tmp_path):
    """Master file 'MCP write': the itinerary pushed from Claude via MCP.
    Every push is a ledger entry with staged undo (CLAUDE.md), the PDF gets
    its 🗂 line, the plan links to its destination places."""
    from quintacle_core.mcp_server import server as s

    s.init(tmp_path / "data")
    created = s.kb_create_entry(
        folder="Fun/Travel/Planned/Austria", title="Austria trip", content="Vienna and Salzburg, May 2027.",
        fields={"destinations": "Vienna, Austria", "start": "2027-05-14", "end": "2027-05-18"},
    )
    note_path = s.kb_store.entry_path(created["folder"], created["slug"])
    before = note_path.read_bytes()
    src = tmp_path / "downloads"
    src.mkdir()
    (src / "austria_mcp.pdf").write_bytes(pdf_bytes(title=b"(Austria MCP plan)"))
    attached = s.kb_attach_file(folder=created["folder"], slug=created["slug"], local_path=str(src / "austria_mcp.pdf"))

    text = note_path.read_text()
    assert "🗂" in text and "Austria MCP plan" in text and "austria_mcp.pdf" in text
    nid = f"note:{created['folder']}/{created['slug']}"
    assert (nid, "place:europe/austria/vienna", "located_in") in _edges()
    writes = s.list_recent_writes()
    assert len(writes) == 2 and writes[0]["id"] == attached["ledger_id"]
    ledger_md = (tmp_path / "data" / "mcp-log.md").read_text()
    assert attached["ledger_id"] in ledger_md and created["ledger_id"] in ledger_md

    s.undo_write(attached["ledger_id"])
    assert note_path.read_bytes() == before
    assert not (note_path.parent / "assets" / "austria_mcp.pdf").exists()
    s.undo_write(created["ledger_id"])
    assert not note_path.exists()


# --------------------------------------------------------------- Travel: NYC chat answer saved as .md


def test_chat_answer_md_drop_is_read_then_saved_with_images_browse_can_load(client, models, monkeypatch):
    """Round-2 fixes, NYC plan: a chat answer saved as .md was sorted as 'no
    description given'; its pictures weren't attached; Browse showed them
    broken. Now: the md is read at drop, web pictures are downloaded, own
    photos copied, and every note-relative path loads via /kb/asset."""
    answers, calls = models
    png = io.BytesIO()
    Image.new("RGB", (6, 6), "blue").save(png, format="PNG")
    own = _commit(client, "Media/Photos", "Skyline", "my skyline", [("skyline.png", png.getvalue(), "image/png")])

    md = (
        "# NYC 5-Day Itinerary 2027\n\nDay 1: Central Park.\n\n"
        "![Central Park](https://upload.wikimedia.org/x/Central_Park.jpg)\n\n"
        f"![my skyline](http://localhost:8000/kb/asset?folder={own['folder']}&path=assets/skyline.png)\n"
    )
    answers["_TextFileClassification"] = _TextFileClassification(is_document=False)
    answers["KBSuggestion"] = lambda user: KBSuggestion(folder="Fun/Travel/Planned/New York", title="NYC 5-Day Itinerary 2027", content=user)
    r = client.post("/drop", data={"text": ""}, files={"file": ("chat-draft.md", md.encode(), "text/markdown")})
    assert r.status_code == 200, r.text
    [entry] = r.json()["entries"]
    sort_call = next(c for c in calls if c["schema"] == "KBSuggestion")
    assert "no description given" not in sort_call["user"] and "Day 1: Central Park" in sort_call["user"]
    assert entry["folder"] == "Fun/Travel/Planned/New York"

    class Resp:
        headers = {"Content-Type": "image/jpeg"}

        def read(self):
            return b"\xff\xd8\xff" + b"1" * 32

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(kb_api.urllib.request, "urlopen", lambda req, timeout=None: Resp())
    out = _commit(client, entry["folder"], entry["title"], "Five days, all five boroughs.", [("chat-draft.md", md.encode(), "text/markdown")])
    body = _note(client, out)
    paths = re.findall(r"!\[[^\]]*\]\((assets/[^)]+)\)", body)
    assert len(paths) == 2, body
    for p in paths:  # Browse loads note-relative paths from the note's folder
        got = client.get("/kb/asset", params={"folder": out["folder"], "path": p})
        assert got.status_code == 200 and len(got.content) > 0, p
    assert client.get("/travel/planned").json()[0]["group"] == "new-york"


def test_plain_text_file_drop_is_read_not_no_description(client, models):
    answers, calls = models
    answers["_TextFileClassification"] = _TextFileClassification(is_document=False)
    answers["KBSuggestion"] = KBSuggestion(folder="Notes", title="Packing list", content="x")
    r = client.post("/drop", data={"text": ""}, files={"file": ("packing.txt", b"passport\ncharger\nrail pass", "text/plain")})
    assert r.status_code == 200, r.text
    user = next(c for c in calls if c["schema"] == "KBSuggestion")["user"]
    assert "rail pass" in user and "no description" not in user


# --------------------------------------------------------------- Food / Finances photos (local-first)


def _fake_ocr(text: str):
    def fake(data: bytes):
        lines = [OcrLine(t, (0.0, i * 20.0, 100.0, 18.0), 0.99) for i, t in enumerate(text.splitlines())]
        return OcrResult(lines=lines, text=text, engine="fake")

    return fake


def _drawn(text: str) -> bytes:
    img = Image.new("RGB", (240, 20 * (text.count("\n") + 2)), "white")
    ImageDraw.Draw(img).multiline_text((4, 4), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


GREEK_YOGURT_LABEL = """Nutrition Facts
1 serving per container
Serving size 1 container (170g)
Calories 100
Total Fat 0g 0%
Sodium 65mg 3%
Total Carbohydrate 6g 2%
Total Sugars 4g
Protein 17g
Calcium 190mg 15%
INGREDIENTS: CULTURED PASTEURIZED NONFAT MILK"""


@pytest.fixture
def usda_db(tmp_path, monkeypatch):
    from quintacle_core.nutrition_db.build import build_db

    out = tmp_path / "usda" / "usda.db"
    build_db([FIX / "foundation", FIX / "sr_legacy"], out, flavonoid_csv=FIX / "flavonoid" / "FLAV_DAT.csv")
    monkeypatch.setenv("QUINTACLE_USDA_DB", str(out))
    usda_store._conns.clear()
    yield out
    usda_store._conns.clear()


def test_label_photo_exact_macros_profile_backtrack_and_usda_backfill(client, models, usda_db, monkeypatch):
    """2026-11-06/07: a Nutrition Facts photo is read locally (OCR + parser,
    no model), the printed values are kept exactly (source=label), the food
    is found from the label's own numbers + ingredient words, and nutrients
    the label doesn't print come from USDA on the review card."""
    _, calls = models
    monkeypatch.setattr(ocr, "ocr_image", _fake_ocr(GREEK_YOGURT_LABEL))
    r = client.post("/drop", data={"text": ""}, files={"file": ("label.jpg", _drawn(GREEK_YOGURT_LABEL), "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pipeline"] == "ocr+parser" and calls == []  # deterministic: zero model calls
    [e] = body["entries"]
    assert e["type"] == "ingredient_preset" and e["source"] == "label"
    assert (e["basis_amount_g"], e["kcal"], e["protein_g"], e["carbs_g"], e["fat_g"]) == (170, 100, 17, 6, 0)
    assert e["fdc_id"] == 330137 and e["usda_description"] == "Yogurt, Greek, plain, nonfat"
    assert e["usda_match_by"] == "nutrition profile"
    micros = {m["nutrient"]: m for m in e["micros"]}
    assert micros["Calcium"]["amount"] == 190 and micros["Calcium"]["source"] in ("label", None, "")
    assert micros["Selenium"]["source"] == "usda"  # not printed -> USDA, scaled to 170 g
    assert micros["Selenium"]["amount"] == pytest.approx(9.7 * 1.7, abs=0.05)


RECEIPT = """CORNER MARKET
12 Example Ave
09/20/2026 15:49
BANANAS 1.29
OAT MILK 4.99
SUBTOTAL 6.28
TAX 0.31
TOTAL 6.59
VISA ****0000 6.59"""


def test_receipt_photo_read_locally_with_merchant_date_total(client, models, monkeypatch):
    """Finances input (a receipt photo): read locally, every field from the
    deterministic parser. Extends test_drop_receipt_photo_read_locally,
    which only pins the amount."""
    _, calls = models
    monkeypatch.setattr(ocr, "ocr_image", _fake_ocr(RECEIPT))
    r = client.post("/drop", data={"text": ""}, files={"file": ("receipt.jpg", _drawn(RECEIPT), "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    [e] = body["entries"]
    assert body["pipeline"] == "ocr+parser" and calls == []
    assert e["type"] == "finance" and e["amount"] == 6.59
    assert e["merchant"].lower() == "corner market" and e["entry_date"] == "2026-09-20"


# --------------------------------------------------------------- Photos: place line, place graph, trip link


def test_trip_photo_gets_place_line_place_graph_and_trip_link(client):
    """Round-1/2: photo location searchable (📍 line), place hierarchy
    (Europe -> Austria -> Vienna), and photos taken during a planned trip
    attach to its plan."""
    r = client.post("/kb/entries", json={
        "folder": "Fun/Travel/Planned/Central Europe", "title": "Central Europe 2027", "content": ITINERARY_SUMMARY,
        "fields": {"start": "2027-05-12", "end": "2027-05-21", "destinations": "Budapest, Vienna, Salzburg, Prague"},
    })
    assert r.status_code == 200, r.text
    plan_id = f"note:{r.json()['folder']}/{r.json()['slug']}"
    out = _commit(client, "Media/Photos/2027/May", "Stephansdom", "A cathedral.",
                  [("vienna.jpg", jpeg(VIENNA, "2027:05:14 15:32:00"), "image/jpeg")])
    photo_id = f"note:{out['folder']}/{out['slug']}"
    assert "📍 Vienna, Austria · Europe" in _note(client, out)
    edges = _edges()
    # The seeded Cafe Central experience made a real Places/Vienna note, which
    # is preferred over a virtual city node (test_real_places_note_is_preferred).
    assert (photo_id, "note:places/vienna", "located_in") in edges
    assert ("note:places/vienna", "place:europe/austria", "part_of") in edges
    assert ("place:europe/austria", "place:europe", "part_of") in edges
    assert (photo_id, plan_id, DURING_TRIP) in edges
    for q in ("Vienna", "Austria", "Europe"):
        assert photo_id in [h["id"] for h in retrieval.retrieve(q, k=10)], q
    # A photo from outside the trip window does not attach.
    late = _commit(client, "Media/Photos/2027/June", "Later", "x", [("late.jpg", jpeg(VIENNA, "2027:06:30 10:00:00"), "image/jpeg")])
    assert (f"note:{late['folder']}/{late['slug']}", plan_id, DURING_TRIP) not in _edges()


# --------------------------------------------------------------- Chats autosave + day bundle


def test_chat_autosaves_into_one_transcript_and_shows_on_the_day(client):
    """Round-2 fix: chats saved only on 'New chat'. Now every reply saves
    into ONE transcript per session; the day view lists the chat, the work
    log, notes saved and income."""
    today = clock.today().isoformat()
    turns = [{"role": "user", "content": "plan a new york trip 2027"}, {"role": "assistant", "content": "Day 1: Manhattan"}]
    a = client.post("/transcripts/archive", json={"messages": turns, "session_id": "nyc-1", "final": False}).json()
    turns += [{"role": "user", "content": "add the bronx"}, {"role": "assistant", "content": "Day 5: Bronx Zoo"}]
    b = client.post("/transcripts/archive", json={"messages": turns, "session_id": "nyc-1", "final": False}).json()
    assert a["archived"] and b["archived"] and a["path"] == b["path"]
    files = list((client.data_dir / "conversations").rglob("*.md"))
    assert len(files) == 1 and "Bronx Zoo" in files[0].read_text()
    assert client.post("/transcripts/archive", json={"messages": turns, "incognito": True}).json()["archived"] is False

    kb_api.get_store().write("Daily Log/Work Logs", f"work-log-{today}", "Tested travel drops.")
    client.post("/kb/entries", json={"folder": "Fun/Travel/Planned/New York", "title": "NYC plan", "content": "5 days"})
    client.post("/logs/income", json={"date": today, "amount": 250, "source": "Freelance"})
    day = client.get(f"/day/{today}").json()
    assert day["chats"] and day["chats"][0]["first_message"].startswith("plan a new york trip")
    assert "Tested travel drops" in day["work_log"]["content"]
    assert "NYC plan" in [n["title"] for n in day["notes_saved"]]
    assert day["money"]["earned"] == 250


# --------------------------------------------------------------- Private + MCP


def test_private_itinerary_is_invisible_to_mcp(client):
    """A private note (passport/visa notes live in itineraries) never
    reaches MCP — same store the app writes, read through the MCP tools."""
    from quintacle_core.mcp_server import server as s

    out = _commit(client, "Fun/Travel/Planned/Austria", "Visa notes", "Schengen visa appointment zqxprivate",
                  [("visa.pdf", pdf_bytes(title=b"(Visa)"), "application/pdf")], private="true")
    s.init(client.data_dir)
    assert s.kb_search_entries("zqxprivate") == []
    assert all(h["id"] != f"note:{out['folder']}/{out['slug']}" for h in s.search_index("zqxprivate"))
    with pytest.raises(ValueError):
        s.kb_get_entry(out["folder"], out["slug"])


# --------------------------------------------------------------- Goals


def test_goal_saved_as_weekly_is_normalized_and_nonsense_rejected(client):
    """Round-2 fix: a goal saved with period 'weekly' broke permanently."""
    r = client.post("/logs/habits", json={"name": "Gym", "target_amount": 3, "target_period": "weekly", "metric": "activity_hours"})
    assert r.status_code == 200, r.text
    habits = client.get("/logs/habits").json()
    gym = next(h for h in habits if h["name"] == "Gym")
    assert gym["target_period"] == "week"
    assert client.post("/logs/habits", json={"name": "Bad", "target_amount": 1, "target_period": "yearly"}).status_code == 422
