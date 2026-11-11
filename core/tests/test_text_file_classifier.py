"""2026-11-11 regression: since PDFs are read locally (raw text), the
document-vs-note classifier called a trip plan / flight ticket "formal
paperwork". Trip plans and tickets short-circuit to a KB note in code;
real paperwork still reaches the model."""
from types import SimpleNamespace

import pytest

from quintacle_core.nodes import drop_router


@pytest.fixture
def model_calls(monkeypatch):
    calls = []

    def fake_parse(system, user_content, output_format, provider=None, max_tokens=0):
        calls.append(user_content)
        return SimpleNamespace(parsed=output_format(is_document=True))

    monkeypatch.setattr(drop_router, "parse_structured", fake_parse)
    return calls


AUSTRIA = (
    "CENTRAL EUROPE | MAY 2027 | PLANNING EDITION\nA complete 10-day Central Europe plan | "
    "May 12-21, 2027\nFlights I would target\nOutbound | Tue, May 11 Austrian Airlines: Washington "
    "Dulles (IAD) to Vienna (VIE) to Budapest (BUD). Arrive Wed, May 12.\nBooking status: not booked\n"
    "Day 1 Budapest: Parliament, Danube walk"
)
TICKET = "E-TICKET RECEIPT\nPassenger: N GUPTA\nConfirmation code: X7Q2LM\nFlight number LH 419 departs IAD 17:40 arrives FRA 07:35"


@pytest.mark.parametrize("text", [AUSTRIA, TICKET])
def test_trip_plans_and_tickets_are_notes_without_a_model_call(model_calls, text):
    assert drop_router.classify_text_file_type(text, provider="local") == "kb_entry"
    assert model_calls == []


def test_real_paperwork_still_asks_the_model(model_calls):
    passport = "PASSPORT\nRepublic of India\nPassport No. Z1234567\nDate of issue 01/02/2020 Date of expiry 01/02/2030\nCheck-in not applicable"
    assert drop_router.classify_text_file_type(passport) == "document_entry"
    assert len(model_calls) == 1


def test_model_sees_only_the_head_of_long_text(model_calls):
    drop_router.classify_text_file_type("lease agreement " + "x" * 20000)
    assert len(model_calls[0]) == drop_router._CLASSIFY_HEAD_CHARS
