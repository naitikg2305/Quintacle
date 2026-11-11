"""Faked regressions for two 2026-11-11 live findings — no model calls.

1. lifestyle_cases.check_home_text: local qwen3:8b invented a price, a room
   and an exact purchase day for "Dyson V15 vacuum, bought 2025, warranty 2
   years" and dropped the warranty. structure_home_item now runs a
   deterministic guard after the parse.
2. photos_cases.check_passport_photo: the cloud path returned a passport
   document_entry with expiry_date=None. The vision prompt now asks for
   printed dates verbatim, and structure_document reads labelled
   issue/expiry dates (and a passport MRZ) in code."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.nodes.documents import llm as doc_llm
from quintacle_core.nodes.documents.llm import DocumentEstimate, labeled_document_dates
from quintacle_core.nodes.home import llm as home_llm
from quintacle_core.nodes.home.llm import HomeItemEstimate, guard_home_item
from quintacle_core.nodes.vision import vision_prompt

DYSON = "Dyson V15 vacuum, bought 2025, warranty 2 years"
INVENTED = dict(
    suggested_name="Dyson V15 Vacuum",
    category="electronics",
    location="living room, vacuum bag",
    purchase_price=599.99,
    purchase_date="2025-01-15",
    notes="High-performance vacuum with excellent suction.",
)


def _fake_parse(estimate, seen=None):
    def fake(system, text, schema, provider=None, max_tokens=512):
        if seen is not None:
            seen.append(system)
        return SimpleNamespace(parsed=estimate.model_copy())
    return fake


# --- Bug 1: home item guard -------------------------------------------------

def test_structure_home_item_drops_invented_fields_and_keeps_warranty(monkeypatch):
    prompts = []
    monkeypatch.setattr(home_llm, "parse_structured", _fake_parse(HomeItemEstimate(**INVENTED), prompts))
    e = home_llm.structure_home_item(DYSON, ["Iris 307"])
    assert e.purchase_price is None
    assert e.location == ""
    assert e.purchase_date is None or e.purchase_date.startswith("2025")
    assert e.purchase_date == "2025-01-01"  # year only -> no invented month/day
    assert "warranty 2 years" in e.notes.lower()
    assert "never invent" in prompts[0].lower()


@pytest.mark.parametrize("text,price,kept", [
    ("couch, paid $450 in 2023", 450.0, 450.0),
    ("lamp 30 dollars", 30.0, 30.0),
    ("lamp, cost 25", 25.0, 25.0),
    ("old lamp from 2019", 25.0, None),
])
def test_price_needs_a_money_amount(text, price, kept):
    assert guard_home_item(HomeItemEstimate(suggested_name="x", category="decor", purchase_price=price), text).purchase_price == kept


@pytest.mark.parametrize("text,loc,kept", [
    ("drill, in the garage closet", "garage closet", "garage closet"),
    ("drill in hall closet box 3", "closet, box 3", "closet, box 3"),
    ("drill", "garage", ""),
])
def test_location_words_must_appear(text, loc, kept):
    assert guard_home_item(HomeItemEstimate(suggested_name="x", category="tools", location=loc), text).location == kept


@pytest.mark.parametrize("text,model_date,kept", [
    ("tv bought 2025", "2025-01-15", "2025-01-01"),
    ("tv bought 2025", "2024-06-01", None),
    ("tv bought March 2025", "2025-03-15", "2025-03-01"),
    ("tv bought March 15, 2025", "2025-03-15", "2025-03-15"),
    ("tv bought 15 mar 2025", "2025-03-15", "2025-03-15"),
    ("tv bought 2025-03-15", "2025-03-15", "2025-03-15"),
    ("tv bought 3/15/2025", "2025-03-15", "2025-03-15"),
    ("tv, no date", "2025-03-15", None),
])
def test_purchase_date_cut_to_what_text_supports(text, model_date, kept):
    assert guard_home_item(HomeItemEstimate(suggested_name="x", category="electronics", purchase_date=model_date), text).purchase_date == kept


def test_warranty_not_duplicated_when_model_kept_it():
    e = guard_home_item(HomeItemEstimate(suggested_name="x", category="appliance", notes="Warranty 2 years."), DYSON)
    assert e.notes.lower().count("warranty") == 1


def test_home_drop_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(home_llm, "parse_structured", _fake_parse(HomeItemEstimate(**INVENTED)))
    c = TestClient(api_module.create_app())
    r = c.post("/drop", data={"text": f"home: {DYSON}", "provider": "local"})
    assert r.status_code == 200, r.text
    e = next(x for x in r.json()["entries"] if x["type"] == "home_item")
    assert e["purchase_price"] is None and not e["location"]
    assert e["purchase_date"] in (None, "2025-01-01")
    assert "warrant" in e["notes"].lower() and "2" in e["notes"]


# --- Bug 2: document dates ----------------------------------------------------

PASSPORT_DESC = (
    "A United States passport data page for Jane Doe.\n"
    "Passport No. 912345678\nDate of birth: 14 MAR 1990\n"
    "**Date of issue:** 02 JAN 2020\n**Date of expiration:** 01 JAN 2030\n"
)


@pytest.mark.parametrize("text,issued,expiry", [
    (PASSPORT_DESC, "2020-01-02", "2030-01-01"),
    ("| Date of issue | 02 Jan 2020 |\n| Date of expiry | 01 Jan 2030 |", "2020-01-02", "2030-01-01"),
    ("Issued on March 3, 2021. Expires: 2026-03-02", "2021-03-03", "2026-03-02"),
    ("Card valid until 12/31/2027", None, "2027-12-31"),
    ("EXP 31/12/2027", None, "2027-12-31"),
    ("Issue date (DD MMM YYYY): 05 FEB 2019", "2019-02-05", None),
    ("Date of birth: 14 MAR 1990, issued by the State Department", None, None),
    # MRZ only (cloud summary dropped the labels): expiry from line 2.
    ("P<USADOE<<JANE<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<\n9123456784USA9003141F3001015<<<<<<<<<<<<<<00", None, "2030-01-01"),
])
def test_labeled_document_dates(text, issued, expiry):
    assert labeled_document_dates(text) == (issued, expiry)


def test_structure_document_fills_missing_expiry(monkeypatch):
    model = DocumentEstimate(suggested_name="US Passport", doc_type="passport", issued_date="2020-01-02", expiry_date=None)
    monkeypatch.setattr(doc_llm, "parse_structured", _fake_parse(model))
    e = doc_llm.structure_document(PASSPORT_DESC, provider="cloud")
    assert (e.issued_date, e.expiry_date) == ("2020-01-02", "2030-01-01")


def test_structure_document_keeps_model_dates_when_text_has_no_labels(monkeypatch):
    model = DocumentEstimate(suggested_name="Lease", doc_type="lease", issued_date="2024-06-01", expiry_date="2025-05-31")
    monkeypatch.setattr(doc_llm, "parse_structured", _fake_parse(model))
    e = doc_llm.structure_document("Lease for apartment 307, June 2024 through May 2025")
    assert (e.issued_date, e.expiry_date) == ("2024-06-01", "2025-05-31")


def test_vision_prompt_asks_for_printed_dates_verbatim():
    for n in (1, 2):
        p = vision_prompt(n).lower()
        assert "verbatim" in p and "date" in p and "expiration" in p
    assert "verbatim" not in vision_prompt(1, "what's on the desk?").lower()


def test_passport_photo_cloud_drop_end_to_end(tmp_path, monkeypatch):
    """The cloud path: classify -> describe -> structure. The model drops
    the expiry; code reads it back from the description."""
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api_module, "classify_image_type", lambda data, mime: "document")
    monkeypatch.setattr(api_module, "describe_drop", lambda *a, **k: PASSPORT_DESC)
    model = DocumentEstimate(suggested_name="US Passport", doc_type="passport")
    monkeypatch.setattr(doc_llm, "parse_structured", _fake_parse(model))
    c = TestClient(api_module.create_app())
    r = c.post("/drop", data={"provider": "cloud"}, files={"file": ("passport.png", b"\x89PNG fake", "image/png")})
    assert r.status_code == 200, r.text
    e = next(x for x in r.json()["entries"] if x["type"] == "document_entry")
    assert (e["issued_date"], e["expiry_date"]) == ("2020-01-02", "2030-01-01")
