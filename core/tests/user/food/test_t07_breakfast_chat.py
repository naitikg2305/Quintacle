"""T7 (TESTING-LOG.md): the owner plans one breakfast in chat, local then escalated to Claude
(2026-11-17), with his lamb (T5, "Costco Lean Lamb") and yogurt (T6) already saved.

What he did, and what this test does:
  1. Chat, local: "okay so planning the balanced day m,eal. breakfast. I have 230 grams of costco
     lamb, 70 grams of atlantic salmon, 2 eggs and 50 grams of uncooked rice."
  2. Escalate it to Claude (the conversation before the local answer).
  3. Paste the LOCAL answer into Drop as text: Sort with AI (local), then Redo with cloud.
His chat: files/food/breakfast-chat-2026-11-17/chat.md; his cards: drop_local_local.md,
drop_local_claude.md there.

How it's judged (owner, 2026-11-17: "these are non deterministic chats ... u can only compare
claude and local. the only hard testing is the final drops ... as long as it suggests an actual
right meal"):
- the two chat answers: compared only (chat_compare.py report in reports/T7-*.md). Never fail.
- the drops, pass/fail:
  - a meal is suggested and it is the RIGHT meal: his lamb (his saved "Costco Lean Lamb", 230 g),
    70 g salmon, 2 eggs (~100 g, never 2 g) and 50 g rice kept UNCOOKED. Extra items are fine
    (he deletes them). Amounts confirmed by the owner, 2026-11-17 ("yes t7 is correct");
  - no food-log card (owner: a meal drop is a plan, "food log card no it shouldnt").
  A drop of an answer that never restates the foods with amounts can't make a meal; that is
  reported as such, not blamed on the drop.

Sandbox: a copy of his real store (a SQLite snapshot, so today's saved lamb is in it) minus this
chat. Needs Ollama AND Claude Max:
    cd core && .venv/bin/python -m pytest tests/user/food/test_t07_breakfast_chat.py -q -s
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest

from tests.claude.harness import REAL_STORE, drop, make_client, missing_max, missing_requirements, sandbox_before, types

PROMPT = ("okay so planning the balanced day m,eal. breakfast. I have 230 grams of costco lamb, "
          "70 grams of atlantic salmon, 2 eggs and 50 grams of uncooked rice. ")
LOCAL_MODEL = "local:qwen3:8b"
CLOUD_MODEL = os.environ.get("QUINTACLE_T07_CLOUD_MODEL", "max:opus")
BREAKFAST_CHAT = Path(__file__).parents[1] / "files" / "food" / "breakfast-chat-2026-11-17" / "chat.md"


def HIS_LOCAL_ANSWER() -> str:
    from tests.user.food.meal_checks import his_answers

    return his_answers(BREAKFAST_CHAT)[0]


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    reason = missing_requirements() or missing_max()
    if reason:
        pytest.skip(reason)
    # His data as it was when he asked (2026-11-17 16:23): lamb and yogurt saved; this chat, its
    # soft facts ("230 grams of Costco lamb") and later chats left out.
    c = sandbox_before(tmp_path_factory.mktemp("t07"), chats_from="2026-11-17-1623", cloud=True)

    def chat(model):
        body = {"messages": [{"role": "user", "content": PROMPT}], "model": model, "web": False}
        if model.startswith("local:"):
            r = c.post("/kb/chat", json=body)
        else:
            from quintacle_core.nodes.kb import chat as kb_chat

            real = kb_chat._run_anthropic
            kb_chat._run_anthropic = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Max failed; metered API blocked"))
            try:
                r = c.post("/kb/chat", json=body)
            finally:
                kb_chat._run_anthropic = real
        assert r.status_code == 200, r.text[:400]
        return r.json()["reply"]

    s = {"local_answer": chat(LOCAL_MODEL), "claude_answer": chat(CLOUD_MODEL)}
    for name, provider in (("local+local", "local"), ("local+claude", "cloud")):
        # HIS saved local answer from that day (fresh answers are compared only, owner 2026-11-17)
        s[name] = drop(c, text=HIS_LOCAL_ANSWER().strip(), provider=provider)  # pasted as text, like his
    import json

    import quintacle_core.api as api_module

    out = Path(api_module.DATA_DIR).parent
    for name in ("local_answer", "claude_answer"):
        (out / f"{name}.md").write_text(s[name], encoding="utf-8")
    for name in ("local+local", "local+claude"):
        (out / f"{name}.json").write_text(json.dumps(s[name], indent=1), encoding="utf-8")
    print(f"\nT7 answers and cards saved in {out}")
    return s


ANSWERS = ["local_answer", "claude_answer"]
CARD_SETS = ["local+local", "local+claude"]
HIS_FOODS = {"lamb": 230, "salmon": 70, "egg": 100, "rice": 50}


def test_local_vs_claude_comparison(session):
    """Report only."""
    from tests.user.chat_compare import compare

    assert compare("T7", PROMPT, session["local_answer"], session["claude_answer"])["report"].exists()


# ------------------------------------------------------------------ drops (pass/fail)


def _meal(session, which) -> dict:
    meal = next((e for e in session[which].get("entries", []) if e.get("type") == "meal_composition"), None)
    assert meal, types(session[which])
    return meal


@pytest.mark.parametrize("which", CARD_SETS)
def test_the_right_meal_is_suggested(session, which):
    from tests.user.food.meal_checks import missing_foods

    meal = _meal(session, which)
    assert not missing_foods(meal, HIS_FOODS), (missing_foods(meal, HIS_FOODS), meal.get("components"))


@pytest.mark.parametrize("which", CARD_SETS)
def test_the_lamb_is_his_saved_lamb(session, which):
    lamb = [c for c in _meal(session, which).get("components") or [] if "lamb" in (c.get("name") or "").lower()]
    assert lamb and lamb[0].get("ingredient_id"), lamb


@pytest.mark.parametrize("which", CARD_SETS)
def test_no_food_log_card(session, which):
    assert "food" not in types(session[which]), types(session[which])
