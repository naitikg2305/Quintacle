"""T4 (TESTING-LOG.md): the owner's full-day meal plan chat, redone step by step (2026-11-17).

What he did, and what this test does, in order:
  1. Chat, local: "alright so i want to design a meal thats covers all the nutrients for me in
     the day. this includes 180-200 g of protein, keeping it under 2500 kcals and all micros and
     macros."
  2. Paste the local answer into Drop as text: Sort with AI (local), then Redo with cloud. Not saved.
  3. Escalate the chat to Claude (only the question goes, like the app's escalate).
  4. (Not done by him; the test does it) Claude's answer into Drop: local, then Redo with cloud.
  5. Follow-up, picker still on local: "okay give me a list of ingredients for an entire day"
     (the app sends the whole chat: question, local answer, Claude answer, follow-up).
  6. Escalate the follow-up to Claude.
His run: files/food/meal-plan-2026-11-17/ (chat.md, drop_local_local.md + screenshot,
drop_local_claude.md); his comparisons: reports/T4-owner-session-*.md, T4-followup-owner-session-*.md.

How it's judged (owner, 2026-11-17: chats are non-deterministic, "u can only compare claude and
local. the only hard testing is the final drops"; extra notes are fine "as long as it suggests an
actual right meal"):
- both chat questions: local vs Claude comparison reports only (reports/T4-*.md). Never fail.
- the drops, pass/fail:
  - a meal is suggested (when the answer restates foods with amounts; a drop can only suggest
    ONE meal, so for a full-day plan that's one dish of it);
  - the note goes in his Nutrition folder (Personal Development/Physical/Nutrition), never a new
    top folder (owner OK'd the fix, 2026-11-17).

Sandbox: a copy of his real store (SQLite snapshot) with this chat left out. Needs Ollama AND
Claude Max:
    cd core && .venv/bin/python -m pytest tests/user/food/test_t04_full_day_meal_plan_chat.py -q -s
Cloud chat model: QUINTACLE_T04_CLOUD_MODEL (default max:opus).
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest

from tests.claude.harness import REAL_STORE, drop, folder_of, make_client, missing_max, missing_requirements, sandbox_before, types

FOLLOW_UP = "okay give me a list of ingredients for an entire day"
PROMPT = ("alright so i want to design a meal thats covers all the nutrients for me in the day. "
          "this includes 180-200 g of protein, keeping it under 2500 kcals and all micros and macros. ")
LOCAL_MODEL = "local:qwen3:8b"
CLOUD_MODEL = os.environ.get("QUINTACLE_T04_CLOUD_MODEL", "max:opus")
NUTRITION_FOLDER = "personal-development/physical/nutrition"
MEAL_PLAN_CHAT = Path(__file__).parents[1] / "files" / "food" / "meal-plan-2026-11-17" / "chat.md"
# Left out of the sandbox copy: the owner's own session of this chat.
LEFT_OUT = ("alright-so-i-want-to-design-a-meal-thats-covers-all-the-nutr",)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    reason = missing_requirements() or missing_max()
    if reason:
        pytest.skip(reason)
    # His data as it was when he asked (2026-11-17 15:49): no lamb or yogurt saved yet, and
    # none of this chat or later ones (transcripts, soft facts).
    return sandbox_before(tmp_path_factory.mktemp("t04"), chats_from="2026-11-17-1549",
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
    """The answer pasted into Drop as TEXT (his cards include a food log + a meal, which only
    the plain-text lane makes; a chat-draft.md file drop never proposes a meal)."""
    return drop(client, text=answer.strip(), provider=provider)


@pytest.fixture(scope="module")
def session(client):
    s: dict = {}
    # Fresh chat answers are compared only; the DROPS use HIS saved answers from that day
    # (owner, 2026-11-17), so a random chat answer can't decide a pass/fail drop check.
    from tests.user.food.meal_checks import his_answers

    his = his_answers(MEAL_PLAN_CHAT)
    s["local_answer"] = _chat(client, [{"role": "user", "content": PROMPT}], LOCAL_MODEL)
    s["local+local"] = _send_to_drop(client, his[0], "local")
    s["local+claude"] = _send_to_drop(client, his[0], "cloud")
    s["claude_answer"] = _chat(client, [{"role": "user", "content": PROMPT}], CLOUD_MODEL)
    s["claude+local"] = _send_to_drop(client, his[1], "local")
    s["claude+claude"] = _send_to_drop(client, his[1], "cloud")
    # Follow-up: the whole chat so far, both answers kept (frontend/app/kb/page.tsx sendChat).
    s["context"] = [{"role": "user", "content": PROMPT},
                    {"role": "assistant", "content": s["local_answer"]},
                    {"role": "assistant", "content": s["claude_answer"]}]
    follow = s["context"] + [{"role": "user", "content": FOLLOW_UP}]
    s["local_followup"] = _chat(client, follow, LOCAL_MODEL)
    # Escalate: the same messages, before the local follow-up answer (page.tsx escalate).
    s["claude_followup"] = _chat(client, follow, CLOUD_MODEL)
    import quintacle_core.api as api_module

    for name in ("local_answer", "claude_answer", "local_followup", "claude_followup"):
        (Path(api_module.DATA_DIR).parent / f"{name}.md").write_text(s[name], encoding="utf-8")
    print(f"\nT4 answers saved in {Path(api_module.DATA_DIR).parent}")
    return s


ANSWERS = ["local_answer", "claude_answer"]
CARD_SETS = ["local+local", "local+claude", "claude+local", "claude+claude"]  # all confirmed by the owner 2026-11-17



def test_local_vs_claude_comparison(session):
    """Report only."""
    from tests.user.chat_compare import compare

    assert compare("T4", PROMPT, session["local_answer"], session["claude_answer"])["report"].exists()


def test_follow_up_local_vs_claude_comparison(session):
    """Report only. The judge sees the earlier turns, so each model may build on its own plan."""
    from tests.user.chat_compare import compare

    ctx = [{"role": "user", "content": PROMPT},
           {"role": "assistant", "label": "local answer", "content": session["local_answer"]},
           {"role": "assistant", "label": "Claude answer (escalated)", "content": session["claude_answer"]}]
    out = compare("T4-followup", FOLLOW_UP, session["local_followup"], session["claude_followup"], context=ctx)
    assert out["report"].exists()


# ------------------------------------------------------------------ drops (pass/fail)


@pytest.mark.parametrize("which", CARD_SETS)
def test_a_meal_is_suggested(session, which):
    assert "meal_composition" in types(session[which]), types(session[which])


@pytest.mark.parametrize("which", CARD_SETS)
def test_notes_go_in_his_nutrition_folder(session, which):
    from quintacle_core.markdown_paths import slugify

    notes = [e for e in session[which].get("entries", []) if e.get("type") == "kb_entry"]
    folders = ["/".join(slugify(x) for x in (e.get("folder") or "").split("/")) for e in notes]
    assert all(f.startswith(NUTRITION_FOLDER) for f in folders), folders
