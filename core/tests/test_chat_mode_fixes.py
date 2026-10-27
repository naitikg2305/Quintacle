"""§12 corrections (2026-10-27), found by live-testing serious mode with local
qwen3:8b: (1) serious-mode zero-match short-circuit — no model call when
there is nothing to ground on; (2) deterministic post-validation of app
note/asset links in every reply; (3) relative dates in soft facts anchored
to the chat's date at store time. No live model calls: provider runners and
the extractor are monkeypatched. Endpoint tests run on a seeded sandbox."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
import quintacle_core.retrieval as retrieval
from quintacle_core.nodes.kb import chat, soft_record
from quintacle_core.nodes.kb.chat import NOT_FOUND_SUFFIX, SERIOUS_NOTHING_REPLY, validate_reply_links
from quintacle_core.nodes.kb.soft_record import annotate_fact_date
from quintacle_core.nodes.kb.store import KBStore

PROVIDER_RUNNERS = ("_run_anthropic", "_run_openai", "_run_bedrock", "_run_local")


@pytest.fixture(autouse=True)
def _reset_retrieval_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    client = TestClient(api_module.create_app())
    client.post("/logs/meals", json={"name": "Chipotle bowl", "kcal": 800, "protein_g": 45})
    client.post("/logs/routines", json={"name": "Pull Day", "exercises": ["Deadlift", "Pull Ups"]})
    client.post("/people", json={"name": "Laura", "category": "friend", "how_met": "college"})
    client.post("/kb/entries", json={"folder": "Career", "title": "Contract work", "content": "Minfy contract renews in January."})
    client.post("/kb/entries", json={"folder": "Fitness", "title": "Deadlift Cues", "content": "Brace before you pull."})
    return client


def _spy(monkeypatch, reply: str = "stub-reply") -> list[str | None]:
    calls: list[str | None] = []

    def runner(model, messages, kb_text):
        calls.append(kb_text)
        return reply

    for name in PROVIDER_RUNNERS:
        monkeypatch.setattr(chat, name, runner)
    return calls


def _chat(client, text, **extra) -> dict:
    r = client.post("/kb/chat", json={"messages": [{"role": "user", "content": text}], **extra})
    assert r.status_code == 200, r.text
    return r.json()


THROAT = "what's been going on with my throat lately?"


# --- 1. serious-mode zero-match short-circuit -----------------------------------


@pytest.mark.parametrize("model", ["local:qwen3:8b", "claude-opus-5-5", "gpt-5-mini", "bedrock:us.amazon.nova-lite-v1:0"])
def test_zero_match_serious_never_calls_any_provider(client, monkeypatch, model):
    calls = _spy(monkeypatch)
    monkeypatch.setattr(chat, "_me_block", lambda store: None)
    r = _chat(client, THROAT, mode="serious", model=model)
    assert calls == []  # no model call, whatever provider (escalation too)
    assert r == {"reply": SERIOUS_NOTHING_REPLY, "mode": "serious", "mode_switched": False}
    assert r["reply"].startswith("That's not in your notes.")


def test_zero_match_via_switch_phrase_keeps_response_shape(client, monkeypatch):
    calls = _spy(monkeypatch)
    monkeypatch.setattr(chat, "_me_block", lambda store: None)
    r = _chat(client, "just from my notes — " + THROAT, mode="unserious")
    assert calls == [] and r == {"reply": SERIOUS_NOTHING_REPLY, "mode": "serious", "mode_switched": True}


def test_zero_match_unserious_still_calls_the_model(client, monkeypatch):
    calls = _spy(monkeypatch)
    monkeypatch.setattr(chat, "_me_block", lambda store: None)
    assert _chat(client, THROAT, mode="unserious")["reply"] == "stub-reply"
    assert len(calls) == 1


def test_me_only_calls_the_model_with_strict_rule(client, monkeypatch):
    calls = _spy(monkeypatch)
    monkeypatch.setattr(chat, "_me_block", lambda store: "## About the user\n\n- Bench PR 225 lb")
    _chat(client, THROAT, mode="serious")
    [text] = calls
    assert "## About the user" in text and "that's not in your notes" in text


def test_retrieval_hit_calls_the_model(client, monkeypatch):
    calls = _spy(monkeypatch)
    monkeypatch.setattr(chat, "_me_block", lambda store: None)
    _chat(client, "when does my Minfy contract renew?", mode="serious")
    [text] = calls
    assert "Minfy contract renews in January." in text


def test_day_bundle_alone_calls_the_model(client, monkeypatch):
    calls = _spy(monkeypatch)
    monkeypatch.setattr(chat, "_me_block", lambda store: None)
    monkeypatch.setattr(chat, "_day_blocks", lambda messages: "## 2026-10-26 — that day's record\n\nRan 5k")
    _chat(client, THROAT, mode="serious")
    assert len(calls) == 1


def test_folder_scope_is_unaffected(client, monkeypatch):
    calls = _spy(monkeypatch)
    monkeypatch.setattr(chat, "_me_block", lambda store: None)
    _chat(client, THROAT, mode="serious", folder="Fitness")
    assert len(calls) == 1


def test_topic_scope_is_unaffected(client, monkeypatch):
    calls = _spy(monkeypatch)
    monkeypatch.setattr(chat, "_me_block", lambda store: None)
    _chat(client, THROAT, mode="serious", folder="career", slug="contract-work")
    assert len(calls) == 1


def test_legacy_fallback_is_unaffected(client, monkeypatch):
    calls = _spy(monkeypatch)
    monkeypatch.setattr(chat, "_me_block", lambda store: None)

    def down(*a, **k):
        raise RuntimeError("retrieval index not initialized")

    monkeypatch.setattr(chat, "_kb_context", down)
    _chat(client, THROAT, mode="serious")
    [text] = calls
    assert "Minfy contract renews" in text  # dump-everything counts as material


def test_kb_off_is_unaffected(client, monkeypatch):
    calls = _spy(monkeypatch)
    monkeypatch.setattr(chat, "_me_block", lambda store: None)
    _chat(client, THROAT, mode="serious", use_kb=False)
    assert len(calls) == 1


def test_build_context_flag_directly(client, monkeypatch):
    monkeypatch.setattr(chat, "_me_block", lambda store: None)
    from quintacle_core.nodes.kb.api import get_store

    store = get_store()
    msgs = [{"role": "user", "content": THROAT}]
    text, nothing = chat._build_context(store, True, None, None, msgs, "serious")
    assert nothing is True and "(nothing in the knowledge base matched this question)" in text
    assert chat._system_text(store, True, None, None, msgs, "serious") == text
    _, nothing = chat._build_context(store, True, None, None, [{"role": "user", "content": "Minfy renew?"}], "serious")
    assert nothing is False


# --- 2. link post-validation -----------------------------------------------------


@pytest.fixture
def store(tmp_path):
    s = KBStore(tmp_path / "kb")
    s.write("Career", "Contract work", "Minfy contract renews in January.")
    s.write("Health Notes", "Throat Log", "Nothing yet.")
    assets = tmp_path / "kb" / "career" / "assets"
    assets.mkdir(parents=True)
    (assets / "offer-letter.pdf").write_bytes(b"%PDF")
    (tmp_path / "secret.txt").write_text("outside kb")
    return s


def test_valid_note_link_untouched(store):
    reply = "See [Contract work](/kb/browse?path=career&open=contract-work)."
    assert validate_reply_links(reply, store) == reply


def test_missing_note_link_is_unlinked(store):
    reply = "See [Sore Throat Note](/kb/browse?path=health&open=sore-throat) for details."
    assert validate_reply_links(reply, store) == f"See Sore Throat Note{NOT_FOUND_SUFFIX} for details."


def test_folder_and_slug_are_normalized_like_kbstore(store):
    # Title-cased / encoded folder with a space and a title-cased slug still resolve.
    for href in (
        "/kb/browse?path=Health%20Notes&open=throat-log",
        "/kb/browse?path=Health+Notes&open=Throat%20Log",
        "/kb/browse?path=Career&open=Contract%20Work",
    ):
        reply = f"[it]({href})"
        assert validate_reply_links(reply, store) == reply, href


def test_angle_bracket_href_with_spaces(store):
    ok = "[it](</kb/browse?path=Health Notes&open=throat-log>)"
    assert validate_reply_links(ok, store) == ok
    bad = "[it](</kb/browse?path=Health Notes&open=nope>)"
    assert validate_reply_links(bad, store) == f"it{NOT_FOUND_SUFFIX}"


def test_assets_valid_missing_and_escaping(store):
    ok = "[offer](/kb/asset?folder=career&path=assets%2Foffer-letter.pdf)"
    assert validate_reply_links(ok, store) == ok
    ok_slash = "[offer](/kb/asset?folder=Career&path=assets/offer-letter.pdf)"
    assert validate_reply_links(ok_slash, store) == ok_slash
    assert validate_reply_links("[x](/kb/asset?folder=career&path=assets/nope.pdf)", store) == f"x{NOT_FOUND_SUFFIX}"
    # escaping the KB root is "not found", never a raw filesystem check outside it
    assert validate_reply_links("[s](/kb/asset?folder=career&path=../../secret.txt)", store) == f"s{NOT_FOUND_SUFFIX}"
    # a missing asset rendered as an image is unlinked too
    assert validate_reply_links("![pic](/kb/asset?folder=career&path=assets/gone.jpg)", store) == f"pic{NOT_FOUND_SUFFIX}"


def test_external_and_other_links_untouched(store):
    reply = (
        "[docs](https://example.com/kb/browse?path=x&open=y) "
        "![Eiffel Tower](https://upload.wikimedia.org/a.jpg) "
        "[journal](/journal?date=2026-10-20) [browse](/kb/browse) [anchor](#top)"
    )
    assert validate_reply_links(reply, store) == reply


@pytest.mark.parametrize(
    "href",
    [
        "/kb/browse?open=contract-work",  # open without path
        "/kb/browse?path=career&open",  # malformed query field
        "/kb/browse?path=&open=contract-work",
        "/kb/browse?path=nowhere",  # folder that doesn't exist
        "/kb/asset?folder=career",  # no asset path
        "/kb/asset?folder=career&&path=x",
    ],
)
def test_malformed_or_unverifiable_app_hrefs(store, href):
    assert validate_reply_links(f"[t]({href})", store) == f"t{NOT_FOUND_SUFFIX}"


def test_existing_folder_view_link_is_valid(store):
    reply = "[Career](/kb/browse?path=Career)"
    assert validate_reply_links(reply, store) == reply


def test_multiple_links_in_one_reply(store):
    reply = (
        "Your [contract](/kb/browse?path=career&open=contract-work) is fine; "
        "the [doctor note](/kb/browse?path=health&open=doctor-appointment) and "
        "[Sore Throat](/kb/browse?path=health&open=sore-throat) don't exist; "
        "see also [AWS](https://aws.amazon.com)."
    )
    assert validate_reply_links(reply, store) == (
        "Your [contract](/kb/browse?path=career&open=contract-work) is fine; "
        f"the doctor note{NOT_FOUND_SUFFIX} and "
        f"Sore Throat{NOT_FOUND_SUFFIX} don't exist; "
        "see also [AWS](https://aws.amazon.com)."
    )


def test_plain_text_untouched(store):
    for reply in ("", "no links here", "a [bracket] alone", "(parens) and ](odd"):
        assert validate_reply_links(reply, store) == reply


def test_run_kb_chat_validates_every_provider_reply(client, monkeypatch):
    fake = "Check [Sore Throat](/kb/browse?path=health&open=sore-throat) and [Contract](/kb/browse?path=career&open=contract-work)."
    _spy(monkeypatch, reply=fake)
    for model in ("local:qwen3:8b", "claude-opus-5-5"):
        for mode in ("unserious", "serious"):
            r = _chat(client, "when does my Minfy contract renew?", mode=mode, model=model)
            assert r["reply"] == (
                f"Check Sore Throat{NOT_FOUND_SUFFIX} and [Contract](/kb/browse?path=career&open=contract-work)."
            )


# --- 3. soft-fact relative-date anchoring ----------------------------------------

TUE = date(2026, 10, 27)  # a Tuesday


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Throat has been sore since Tuesday.", "Throat has been sore since Tuesday (2026-10-20)."),
        ("Throat soreness started on Tuesday", "Throat soreness started on Tuesday (2026-10-20)"),
        ("Throat soreness began Monday", "Throat soreness began Monday (2026-10-26)"),
        ("Sore since Sunday", "Sore since Sunday (2026-10-25)"),
        ("Started a new job this past Monday", "Started a new job this past Monday (2026-10-26)"),
        ("Knee hurt last Tuesday", "Knee hurt last Tuesday (2026-10-20)"),
        ("Vaped a lot yesterday", "Vaped a lot yesterday (2026-10-26)"),
        ("Skipped the gym today", "Skipped the gym today (2026-10-27)"),
        ("Quit caffeine two weeks ago", "Quit caffeine two weeks ago (2026-10-13)"),
        ("Moved apartments 3 days ago", "Moved apartments 3 days ago (2026-10-24)"),
        # left untouched:
        ("Seeing the doctor next Tuesday", None),
        ("On Tuesday I'll call the doctor", None),
        ("Will call the doctor on Tuesday", None),
        ("Gym this coming Tuesday", None),
        ("Going to start running tomorrow", None),
        ("Ran every day last week", None),  # 7 dates — not exactly one
        ("Sore since Tuesday, worse yesterday", None),  # two different dates
        ("Felt sick yesterday and on Nov 3", None),
        ("Dentist appointment on Nov 3", None),  # explicit month-day alone: never annotated
        ("Gym on Tuesday", None),  # bare weekday without a past cue
        ("Sore since 2026-10-20", None),  # already has an ISO date
        ("Sore since Tuesday (2026-10-20)", None),  # never re-annotated
        ("Switching to a 4-day split", None),
    ],
)
def test_annotation_matrix(text, expected):
    assert annotate_fact_date(text, TUE) == (expected if expected is not None else text)


def test_bare_weekday_is_strictly_before_the_chat_date():
    # on a Wednesday, "since Tuesday" is yesterday; on a Tuesday it's a week back
    assert annotate_fact_date("sore since Tuesday", date(2026, 10, 28)) == "sore since Tuesday (2026-10-27)"
    assert annotate_fact_date("sore since Tuesday", TUE) == "sore since Tuesday (2026-10-20)"


def test_extract_and_store_anchors_to_chat_date_not_today(client, monkeypatch):
    monkeypatch.setattr(
        soft_record, "extract_facts", lambda t: ["Throat sore since Tuesday", "Thinking about a side contract"]
    )
    # A chat held on Tuesday 2026-10-27 whose extraction job runs later still
    # anchors to the chat's own date.
    assert soft_record.extract_and_store("...", "2026-10-27", "t/x.md") == 2
    texts = {r["text"] for r in soft_record.get_soft_record_store().rows()}
    assert texts == {"Throat sore since Tuesday (2026-10-20)", "Thinking about a side contract"}


def test_extract_and_store_bad_date_skips_annotation_only(client, monkeypatch):
    monkeypatch.setattr(soft_record, "extract_facts", lambda t: ["Throat sore since Tuesday"])
    assert soft_record.extract_and_store("...", "not-a-date", "t/x.md") == 1
    assert soft_record.get_soft_record_store().rows()[0]["text"] == "Throat sore since Tuesday"
