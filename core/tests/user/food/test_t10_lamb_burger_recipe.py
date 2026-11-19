"""T10 (TESTING-LOG.md): the owner plans a recipe in chat, several turns, and drops it (2026-11-18 09:20).

His chat (files/food/lamb-burger-recipe-2026-11-18/chat.md), local first, each turn then escalated to Claude:
  1. "lets write a recipe having ingredients lamb salmon and rest carbs ... I want to make smash burgers. how would i go
     about it if i bough costco buns. that are 300 kcals which is okay."
  2. "I want lamb burgers and we can add salmon in or on the side( 1 egg goes in each sandwiich for the two egg
     thingy) and salmon can also be separate"
  3. "but its 230 grams of lamb, 115 for each"          -> his local answer (A3) and Claude's (C3)
  4. "include all ingredients for this recipe"           -> his local answer (A4) and Claude's (C4)
Then he pasted his LOCAL answer to turn 3 (A3) into Drop as text: Sort with AI (local), then Redo with cloud.
His cards: drop_local_local_1.png (4 notes + a workout routine), drop_local_claude.png (1 note).
Then he dropped Claude's answer to turn 4 (C4), Sort with AI (local). 2026-11-19 run, fully local (owner: "this is
local so replace inside the test"): drop_claude_local.png: 2 notes ("Lamb Smash Burgers Full Ingredient List" in his
Nutrition folder, + a junk "Calories Question" note from the closing questions) and a meal card: his saved lamb 230 g,
egg 100 g, Atlantic salmon 70 g + new "Costco buns" 200 g / 130 kcal (estimate), "Kirkland Plain Nonfat" 170 g (USDA
Greek yogurt, NOT matched to his saved Kirkland yogurt), lemon, dill, salt, "Black nd pepper"... Owner: "the folder
selection is actually pretty great". (The 11-18 run, where the meal step fell back to Claude by itself, is kept as
drop_claude_local_auto_cloud.png.)
Redo with cloud on it (drop_claude_claude.png, owner: "cleaner ofc"): ONE card, a meal "Lamb Smash Burger with Fried
Egg and Salmon Yogurt Sauce" per burger: saved lamb 115 g, egg 50 g, Atlantic salmon 70 g, his saved Kirkland yogurt
30 g (reused), "Costco bun" 90 g / 250 kcal (estimate); 654 kcal. No recipe note.

How it's judged (owner, 2026-11-17: chats are only compared; drops are the hard tests; extras are ignored):
- chat, report only (never fails): fresh local vs fresh Claude answers to turns 3 and 4, given his earlier turns.
  Owner 2026-11-18: "local chat is better claude sort is better".
- drops of A3, local and Claude sort, pass/fail:
  - a recipe note in his Nutrition folder (owner: "meal procedures can go in the nutrition folder ofc ...
    sepeatre folder not like a meal preset");
  - no workout routine card (a recipe is not a workout; the local sort gave "Lamb & Salmon Power Meal" with Barbell
    Squat. Cause: the gate reads "Split into two 115g patties" as a gym split. Fix deferred by the owner, so this
    check FAILS for local until then).
  - Extras are ignored. NOTE (owner): local + local proposes extra notes ("Nutritional Breakdown", "Photo Tags",
    "Tips for Travel & Meal Planning"); Claude sort gave one note. The card counts are printed, never judged.

Sandbox: his data just before 09:20 that day. Needs Ollama AND Claude Max:
    cd core && .venv/bin/python -m pytest tests/user/food/test_t10_lamb_burger_recipe.py -q -s
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tests.claude.harness import drop, missing_max, missing_requirements, sandbox_before, types

CHAT = Path(__file__).parents[1] / "files" / "food" / "lamb-burger-recipe-2026-11-18" / "chat.md"
LOCAL_MODEL = "local:qwen3:8b"
CLOUD_MODEL = os.environ.get("QUINTACLE_T10_CLOUD_MODEL", "max:opus")
NUTRITION = "personal-development/physical/nutrition"
CARD_SETS = ["local+local", "local+claude", "claude4+local", "claude4+claude"]


def his_turns() -> tuple[list[str], list[str]]:
    """(his messages, all assistant answers) in order. Answers: A1, A2, A3, C3, A4, C4."""
    parts = re.split(r"^### (You|Assistant)\s*$", CHAT.read_text(encoding="utf-8"), flags=re.M)
    you = [parts[i + 1].strip() for i in range(1, len(parts) - 1, 2) if parts[i] == "You"]
    ans = [parts[i + 1].strip() for i in range(1, len(parts) - 1, 2) if parts[i] == "Assistant"]
    return you, ans


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    reason = missing_requirements() or missing_max()
    if reason:
        pytest.skip(reason)
    c = sandbox_before(tmp_path_factory.mktemp("t10"), chats_from="2026-11-18-0920", cloud=True)
    you, ans = his_turns()
    a1, a2, a3, _c3, a4, _c4 = ans[:6]

    def chat(model, messages):
        from quintacle_core.nodes.kb import chat as kb_chat

        real = kb_chat._run_anthropic
        kb_chat._run_anthropic = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Max failed; metered API blocked"))
        try:
            r = c.post("/kb/chat", json={"messages": messages, "model": model, "web": False})
        finally:
            kb_chat._run_anthropic = real
        assert r.status_code == 200, r.text[:400]
        return r.json()["reply"]

    turn3 = [{"role": "user", "content": you[0]}, {"role": "assistant", "content": a1},
             {"role": "user", "content": you[1]}, {"role": "assistant", "content": a2},
             {"role": "user", "content": you[2]}]
    turn4 = turn3 + [{"role": "assistant", "content": a3}, {"role": "user", "content": you[3]}]
    s = {"you": you, "turn3": turn3, "turn4": turn4}
    for name, msgs in (("3", turn3), ("4", turn4)):
        s[f"local_{name}"] = chat(LOCAL_MODEL, msgs)
        s[f"claude_{name}"] = chat(CLOUD_MODEL, msgs)
    for name, provider in (("local+local", "local"), ("local+claude", "cloud")):
        s[name] = drop(c, text=a3.strip(), provider=provider)  # his local answer to turn 3, pasted as text
        print(f"\nT10 {name}: {len(s[name].get('entries', []))} cards: {types(s[name])}")
    # 2026-11-18 09:55: he also dropped Claude's answer to turn 4 (C4), Sort with AI (local; the meal step fell back
    # to Claude on its own, auto mode). drop_claude_local.png.
    s["claude4+local"] = drop(c, text=_c4.strip(), provider="local")
    s["claude4+claude"] = drop(c, text=_c4.strip(), provider="cloud")  # his Redo with cloud, 2026-11-19
    for name in ("claude4+local", "claude4+claude"):
        print(f"\nT10 {name}: {len(s[name].get('entries', []))} cards: {types(s[name])}")
    return s


@pytest.mark.parametrize("turn", ["3", "4"])
def test_local_vs_claude_comparison(session, turn):
    """Report only."""
    from tests.user.chat_compare import compare

    msgs = session[f"turn{turn}"]
    out = compare(f"T10-turn{turn}", msgs[-1]["content"], session[f"local_{turn}"], session[f"claude_{turn}"],
                  context=msgs[:-1])
    assert out["report"].exists()


def _folder_slug(e: dict) -> str:
    from quintacle_core.markdown_paths import slugify

    return "/".join(slugify(p) for p in (e.get("folder") or "").split("/") if p.strip())


@pytest.mark.parametrize("which", CARD_SETS)
def test_recipe_note_in_his_nutrition_folder(session, which):
    notes = [e for e in session[which].get("entries", []) if e.get("type") == "kb_entry"]
    assert any(_folder_slug(e).startswith(NUTRITION) for e in notes), [e.get("folder") for e in notes]


@pytest.mark.parametrize("which", CARD_SETS)
def test_no_workout_routine_card(session, which):
    assert "workout_routine" not in types(session[which]), types(session[which])
