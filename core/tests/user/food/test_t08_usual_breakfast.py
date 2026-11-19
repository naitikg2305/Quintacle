"""T8 (TESTING-LOG.md): the owner's usual breakfast, after the 2026-11-18 fixes (a eggs, b raw rice,
c his lamb re-matched, g past-chat numbers, h nutrition summary).

What he did (2026-11-18 08:15):
  1. Chat, local: "okay this is what I normally have for breakfast. 230 grams of the lamb(costco),
     70 grams atlantic salmon, 2 eggs and 50 grams of uncooked rice." Then escalated to Claude.
  2. Pasted each answer into Drop as text and sorted it with local and with Claude: four cards,
     each saved as a meal (his names end "(local+local)", "(local+claude)", "(claude +claude)").
His chat: files/food/breakfast-2026-11-18/chat.md (answer 1 = local, answer 2 = Claude).

How it's judged (owner, 2026-11-17, same checks as T7, which he confirmed for this meal):
- the two chat answers: compared only (report in reports/T8-*.md). Never fail.
- the four drops, pass/fail: a meal is suggested and it is the RIGHT meal: his saved "Costco Lean
  Lamb" 230 g, 70 g salmon, 2 eggs ~100 g, 50 g rice kept uncooked; no food-log card.
  Extra cards/items are ignored (owner 2026-11-18: "extras can be ignored").

Sandbox: his data just before 08:15 that day (lamb + yogurt saved; this chat and the salmon, egg,
rice and 4 meals he saved from it left out, harness.OWNER_SAVES). Needs Ollama AND Claude Max:
    cd core && .venv/bin/python -m pytest tests/user/food/test_t08_usual_breakfast.py -q -s
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.claude.harness import drop, missing_max, missing_requirements, sandbox_before, types

PROMPT = ("okay this is what I normally have for breakfast. 230 grams of the lamb(costco), 70 grams "
          "atlantic salmon, 2 eggs and 50 grams of uncooked rice. ")
LOCAL_MODEL = "local:qwen3:8b"
CLOUD_MODEL = os.environ.get("QUINTACLE_T08_CLOUD_MODEL", "max:opus")
CHAT = Path(__file__).parents[1] / "files" / "food" / "breakfast-2026-11-18" / "chat.md"
HIS_FOODS = {"lamb": 230, "salmon": 70, "egg": 100, "rice": 50}
CARD_SETS = ["local+local", "local+claude", "claude+local", "claude+claude"]


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    reason = missing_requirements() or missing_max()
    if reason:
        pytest.skip(reason)
    from tests.user.food.meal_checks import his_answers

    c = sandbox_before(tmp_path_factory.mktemp("t08"), chats_from="2026-11-18-0815", cloud=True)

    def chat(model):
        body = {"messages": [{"role": "user", "content": PROMPT}], "model": model, "web": False}
        from quintacle_core.nodes.kb import chat as kb_chat

        real = kb_chat._run_anthropic
        kb_chat._run_anthropic = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Max failed; metered API blocked"))
        try:
            r = c.post("/kb/chat", json=body)
        finally:
            kb_chat._run_anthropic = real
        assert r.status_code == 200, r.text[:400]
        return r.json()["reply"]

    local_ans, claude_ans = his_answers(CHAT)[:2]
    s = {"local_answer": chat(LOCAL_MODEL), "claude_answer": chat(CLOUD_MODEL)}
    for name, text in (("local", local_ans), ("claude", claude_ans)):
        for sorter, provider in (("local", "local"), ("claude", "cloud")):
            s[f"{name}+{sorter}"] = drop(c, text=text.strip(), provider=provider)  # pasted as text, like his
    return s


def test_local_vs_claude_comparison(session):
    """Report only."""
    from tests.user.chat_compare import compare

    assert compare("T8", PROMPT, session["local_answer"], session["claude_answer"])["report"].exists()


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
