"""T2 (TESTING-LOG.md): the owner's NYC 2028 session, redone step by step.

What the owner did on 2026-11-13, and what this test does, in order:
  1. Chat, local:  "plan a trip to new york city in 2028 5 days?"
  2. Send the local answer to Drop (send-to-Drop -> chat-draft.md), Sort with AI (local),
     Save as A, title + "(local+local)".
  3. Same file, Redo with cloud, Save as B, title + "(local+claude)", typed link -> A.
  4. Escalate the chat to Claude. The app re-sends the conversation BEFORE the local
     answer (frontend/app/kb/page.tsx `escalate`: chatLog.slice(0, i)), so Claude gets
     the question, not the local answer. It sees the local plan only through A and B,
     which are in the knowledge base by now.
  5. Send Claude's answer to Drop, Sort with AI (local), Save as D, + "(claude+local)".
  6. Same file, Redo with cloud, Save as E, + "(claude+claude)".

Expectations (owner, 2026-11-13):
- Chat answer (local and Claude):
  - about New York, in 2028;
  - exactly 5 days (Day 1-5), going home only on the last day;
  - no "all five boroughs" (not asked);
  - no "Quintacle" (made-up "links in Quintacle note").
- Claude also:
  - finds the saved NYC notes in the knowledge base;
  - never offers to delete (chat is read-only).
- Every drop card:
  - KB entry under Fun/Travel/Planned with 2028 in the folder;
  - destinations New York only: no Washington DC (the origin), no Italy ("Little Italy");
  - no Quintacle chip.
- After every Save:
  - the folder chain;
  - New York -> United States -> North America;
  - no Italy, no Washington, no Quintacle link;
  - B -> A connects;
  - four distinct notes, nothing overwritten.

Chat answers differ every run, so chat checks are must / must-not checks, never
exact text. The owner's own answers from that day stay as reference:
files/travel/nyc-2028/local_itinerary.md and claude_itinerary.md.

Sandbox: a copy of the owner's real store with today's NYC 2028 folder and chat
left out, so the knowledge base is as it was before step 1. Needs Ollama AND
Claude Max (local and cloud in one run, like the owner's session):
    cd core && .venv/bin/python -m pytest tests/user/travel/test_t02_nyc_2028_chat.py -q
Cloud chat model: QUINTACLE_T02_CLOUD_MODEL (default max:opus).
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest

from tests.claude.harness import REAL_STORE, drop, first, folder_of, make_client, missing_max, missing_requirements, sandbox_before, types

PROMPT = "plan a trip to new york city in 2028 5 days? "
LOCAL_MODEL = "local:qwen3:8b"
CLOUD_MODEL = os.environ.get("QUINTACLE_T02_CLOUD_MODEL", "max:opus")
QUINTACLE_HUB = "note:projects/quintacle/quintacle"
HIS_LOCAL = Path(__file__).parents[1] / "files" / "travel" / "nyc-2028" / "local_itinerary.md"
HIS_CLAUDE = Path(__file__).parents[1] / "files" / "travel" / "nyc-2028" / "claude_itinerary.md"
# Left out of the sandbox copy: what the owner's session itself created.
LEFT_OUT = ("new-york-2028", "plan-a-trip-to-new-york-city-in-2028-5-days")


# ------------------------------------------------------------------ the session


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    reason = missing_requirements() or missing_max()
    if reason:
        pytest.skip(reason)
    # His data as it was when he started the chat (2026-11-13 07:05): T1's Europe 2027 itinerary
    # existed; the NYC 2028 notes, the T3 ticket, Europe 2026 and all later chats did not.
    return sandbox_before(tmp_path_factory.mktemp("t02"), chats_from="2026-11-13-0705",
                          leave_out=("fun/travel/planned/new-york-2028", "fun/travel/planned/europe-2026",
                                     "fun/travel/planned/europe-2027/2027-europe-travel-itinerary-sample",
                                     "fun/travel/planned/europe-2027/assets/sample-dc-europe-flight-2027.pdf"),
                          leave_out_ingredients=("Costco Lean Lamb", "Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)"), cloud=True)


def _chat(client, messages, model):
    body = {"messages": messages, "model": model, "web": False}
    if model.startswith("local:"):
        r = client.post("/kb/chat", json=body)
    else:
        # A Max failure must fail the test, never fall back to the metered API.
        from quintacle_core.nodes.kb import chat as kb_chat

        real = kb_chat._run_anthropic
        kb_chat._run_anthropic = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Max failed; metered API blocked"))
        try:
            r = client.post("/kb/chat", json=body)
        finally:
            kb_chat._run_anthropic = real
    assert r.status_code == 200, r.text[:400]
    return r.json()["reply"]


def _send_to_drop(client, answer: str, provider: str) -> dict:
    """ChatLog.tsx messageToFile: the whole answer as chat-draft.md."""
    result = drop(client, data=answer.strip().encode(), filename="chat-draft.md", provider=provider)
    return first(result, "kb_entry") | {"_types": types(result)}


def _save(client, card: dict, answer: str, suffix: str, links: list[str]) -> str:
    """The review card's Save (pushKBEntryWithAsset), with the owner's edits."""
    form = {"folder": card["folder"], "title": f"{card['title']}{suffix}", "content": card["content"],
            "links": ",".join(links), "on_conflict": "new"}  # the card's default: keep both
    if card.get("fields"):
        form["fields"] = json.dumps(card["fields"])
    r = client.post("/kb/entries/with-asset", data=form,
                    files=[("files", ("chat-draft.md", answer.strip().encode(), "text/markdown"))])
    assert r.status_code == 200, r.text[:400]
    j = r.json()
    return f"note:{j['folder']}/{j['slug']}"


@pytest.fixture(scope="module")
def session(client):
    s: dict = {}
    # 1. local chat (fresh answer: compared only). The DROPS use HIS saved answers from that day,
    # so a random chat answer can't decide the pass/fail drop checks (owner, 2026-11-17).
    s["fresh_local_answer"] = _chat(client, [{"role": "user", "content": PROMPT}], LOCAL_MODEL)
    s["local_answer"] = HIS_LOCAL.read_text(encoding="utf-8")
    # 2. drop it locally, Save as A (owner kept the card's links)
    s["A_card"] = _send_to_drop(client, s["local_answer"], "local")
    s["A"] = _save(client, s["A_card"], s["local_answer"], "(local+local)", s["A_card"].get("links") or [])
    a_title = s["A_card"]["title"] + "(local+local)"
    # 3. Redo with cloud, Save as B with a typed link to A
    s["B_card"] = _send_to_drop(client, s["local_answer"], "cloud")
    s["B"] = _save(client, s["B_card"], s["local_answer"], "(local+claude)", [a_title])
    # 4. escalate: the conversation before the local answer, to Claude
    s["fresh_claude_answer"] = _chat(client, [{"role": "user", "content": PROMPT}], CLOUD_MODEL)
    s["claude_answer"] = HIS_CLAUDE.read_text(encoding="utf-8")
    # 5-6. drop Claude's answer locally (D) and with cloud (E); no links typed
    s["D_card"] = _send_to_drop(client, s["claude_answer"], "local")
    s["D"] = _save(client, s["D_card"], s["claude_answer"], "(claude+local)", [])
    s["E_card"] = _send_to_drop(client, s["claude_answer"], "cloud")
    s["E"] = _save(client, s["E_card"], s["claude_answer"], "(claude+claude)", [])
    # Both answers kept next to the sandbox, to compare with the owner's.
    import quintacle_core.api as api_module

    for name in ("fresh_local_answer", "fresh_claude_answer"):
        (Path(api_module.DATA_DIR).parent / f"{name}.md").write_text(s[name], encoding="utf-8")
    print(f"\nT2 answers saved in {Path(api_module.DATA_DIR).parent}")
    return s


ANSWERS = ["fresh_local_answer", "fresh_claude_answer"]  # this run's chat answers (report only)
CARDS = ["A_card", "B_card", "D_card", "E_card"]
NOTES = ["A", "B", "D", "E"]


# ------------------------------------------------------------------ chat answers


def _days(text: str) -> dict[int, str]:
    """Day number -> that day's text, from "Day 1" ... headings."""
    marks = [(int(m.group(1)), m.start()) for m in re.finditer(r"\bDay\s+(\d+)\b", text)]
    out: dict[int, str] = {}
    for i, (n, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        out.setdefault(n, "")
        out[n] += text[start:end]
    return out


_GOING_HOME = re.compile(
    r"\b(depart\w*\s+(nyc|new york)|(return|back|head(?:ing)?\s+home|train)\s+(?:\w+\s+){0,2}to\s+(dc|d\.c\.|washington)"
    r"|check\s+into\s+(?:a\s+)?hotel\s+in\s+(dc|d\.c\.|washington))", re.IGNORECASE)


def _chat_answer_is_new_york_in_2028(session, which):
    text = session[which]
    assert re.search(r"new york|nyc", text, re.IGNORECASE), text[:500]
    assert "2028" in text, text[:500]


def _chat_answer_has_exactly_five_days(session, which):
    days = _days(session[which])
    assert set(days) == {1, 2, 3, 4, 5}, sorted(days)


def _chat_answer_goes_home_only_on_the_last_day(session, which):
    days = _days(session[which])
    early = {n: t for n, t in days.items() if n < 5 and _GOING_HOME.search(t)}
    assert not early, {n: _GOING_HOME.search(t).group(0) for n, t in early.items()}


def _chat_answer_does_not_add_all_five_boroughs(session, which):
    assert not re.search(r"(all|every|each)\s+(of\s+the\s+)?(5|five)\s+boroughs", session[which], re.IGNORECASE)


def _chat_answer_does_not_invent_a_quintacle_note(session, which):
    assert "quintacle" not in session[which].lower()


def _chat_claude_finds_the_saved_nyc_notes(session):
    text = session["claude_answer"]
    assert "new-york-2028" in text or "(local+local)" in text or "(local+claude)" in text, text[:800]


def _chat_claude_never_offers_to_delete(session):
    assert not re.search(r"\b(delete|remove)\b", session["claude_answer"], re.IGNORECASE)




# 2026-11-17 (owner): "these are non deterministic chats ... u can only compare claude and local.
# the only hard testing is the final drops." His chat expectations from 2026-11-13 are kept,
# but as a REPORT printed with the comparison: they never fail the run.
_CHAT_CHECKS = [(_chat_answer_is_new_york_in_2028, True), (_chat_answer_has_exactly_five_days, True), (_chat_answer_goes_home_only_on_the_last_day, True), (_chat_answer_does_not_add_all_five_boroughs, True), (_chat_answer_does_not_invent_a_quintacle_note, True), (_chat_claude_finds_the_saved_nyc_notes, False), (_chat_claude_never_offers_to_delete, False)]


def test_chat_expectations_report(session):
    """Report only: which of the owner's chat expectations each answer met."""
    lines = []
    for check, per_answer in _CHAT_CHECKS:
        for which in (ANSWERS if per_answer else ["claude_answer"]):
            try:
                check(session, which) if per_answer else check(session)
                ok = "met"
            except AssertionError:
                ok = "NOT met"
            lines.append(f"  {which:14} {check.__name__[6:]:45} {ok}")
    print("\nT2 chat expectations (report only):\n" + "\n".join(lines))


def test_local_vs_claude_comparison(session):
    """Report only (owner, 2026-11-17): similarity + Claude-judged local fact accuracy,
    written to tests/user/reports/. Never fails on the scores."""
    from tests.user.chat_compare import compare

    out = compare("T2", PROMPT, session["local_answer"], session["claude_answer"])
    assert out["report"].exists()


# ------------------------------------------------------------------ drop cards


def _dest(card) -> str:
    return ((card.get("fields") or {}).get("destinations") or "").lower()


@pytest.mark.parametrize("which", CARDS)
def test_card_is_a_planned_trip_with_the_year(session, which):
    card = session[which]
    assert "document_entry" not in card["_types"], card["_types"]
    folder = folder_of(card)
    assert folder.startswith("fun/travel/planned/") and "2028" in folder, card.get("folder")


@pytest.mark.parametrize("which", CARDS)
def test_card_destination_is_only_new_york(session, which):
    dest = _dest(session[which])
    assert "new york" in dest, dest
    assert "washington" not in dest, dest
    assert "italy" not in dest, dest


@pytest.mark.parametrize("which", CARDS)
def test_card_suggests_no_quintacle(session, which):
    assert "quintacle" not in [str(x).lower() for x in (session[which].get("links") or [])], session[which].get("links")


# ------------------------------------------------------------------ after Save


def _edges():
    from quintacle_core.graph import get_graph_store

    return [(e["source_id"], e["target_id"]) for e in get_graph_store().all()]


def _reachable(start: str) -> set[str]:
    out, todo, edges = set(), [start], _edges()
    while todo:
        n = todo.pop()
        for s, t in edges:
            if s == n and t not in out:
                out.add(t)
                todo.append(t)
    return out


def test_four_distinct_notes_nothing_overwritten(session):
    assert len({session[n] for n in NOTES}) == 4, [session[n] for n in NOTES]


@pytest.mark.parametrize("which", NOTES)
def test_saved_note_in_folder_tree(session, which):
    note = session[which]
    folder = note.removeprefix("note:").rsplit("/", 1)[0]
    up = _reachable(note)
    for f in (f"folder:{folder}", "folder:fun/travel/planned", "folder:fun/travel", "folder:fun"):
        assert f in up, (f, sorted(up))


@pytest.mark.parametrize("which", NOTES)
def test_saved_note_chains_new_york_to_north_america(session, which):
    up = _reachable(session[which])
    assert any(n.startswith("place:") and n.endswith("/new-york") for n in up), sorted(up)
    assert any(n.startswith("place:") and n.endswith("/united-states") for n in up), sorted(up)
    assert "place:north-america" in up, sorted(up)


@pytest.mark.parametrize("which", NOTES)
def test_saved_note_has_no_italy_washington_or_quintacle(session, which):
    note = session[which]
    up = _reachable(note)
    assert not any(n.endswith("/italy") or n.endswith("/washington") for n in up), sorted(up)
    assert QUINTACLE_HUB not in {t for s, t in _edges() if s == note}


def test_typed_link_b_to_a_connects(session):
    assert (session["B"], session["A"]) in _edges()
