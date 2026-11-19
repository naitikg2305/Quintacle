"""T11 (TESTING-LOG.md): the owner plans his pull day in chat and drops it (2026-11-19 17:09).

His chat (files/workout/pull-day-2026-11-19/chat.md), local then escalated to Claude:
  "okay lets plan a workout routine. starting with pull workout. I do a pull workout usually 3 sets each. deadlifts,
   weighted pullups weighted chinups. barbell rows. bicep curls. facepulls and supportive back exercizes like cable
   pull aparts and facepulls"
Then he pasted the LOCAL answer into Drop as text: Sort with AI (local), then Redo with cloud.
His cards: drop_local_local.md (7 exercise LOG cards with the answer's rep ranges as reps, + routine "Pull Day" with
his 7 exercises), drop_local_claude.png (KB note "Pull Workout Routine (3 Sets Each)" in a new top folder
"Fitness/Routines", + routine "Pull Day" with his 7 exercises). Owner: "local + claude is definitely nicer"; on local:
"it includes all so im not super worried persay. tho its logging it in before its even a route".

How it's judged (owner, 2026-11-17: chats only compared; the drops are the hard tests; extras ignored):
- chat, report only: fresh local vs Claude answers to his question.
- drops of his local answer, local and Claude sort, pass/fail:
  - a workout routine with every exercise he named: deadlift, weighted pull-ups, weighted chin-ups, barbell rows,
    bicep curls, face pulls, cable pull-aparts (names may differ in wording/case/plural).
Then he dropped CLAUDE's answer: Sort with AI (local) -> drop_claude_local.md (exercise LOG cards from the table's
ranges, e.g. Deadlift 3/5/3, + a junk ACTIVITY "productivity: Review and organize workout plan for pull day 0.5";
the KB note + "Pull Day" shown above them look like the previous drop's cards still on the page, since a new sort
ADDS to the pending cards), and Redo with cloud -> drop_claude_claude.png (only routine "Pull Day", his 7).
Reported, not judged (owner hasn't confirmed them as rules yet): exercise LOG cards from a plan (he: "logging it in
before its even a route"), and where the KB note goes (Claude made a new "Fitness/Routines"; his folder is
Personal Development/Physical/Fitness/Routines).

Sandbox: his data just before 17:09 that day. Needs Ollama AND Claude Max:
    cd core && .venv/bin/python -m pytest tests/user/workout/test_t11_pull_day_chat.py -q -s
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tests.claude.harness import drop, missing_max, missing_requirements, sandbox_before, types

CHAT = Path(__file__).parents[1] / "files" / "workout" / "pull-day-2026-11-19" / "chat.md"
PROMPT = ("okay lets plan a workout routine. starting with pull workout. I do a pull workout usually 3 sets each. "
          "deadlifts, weighted pullups weighted chinups. barbell rows. bicep curls. facepulls and supportive back "
          "exercizes like cable pull aparts and facepulls")
LOCAL_MODEL = "local:qwen3:8b"
CLOUD_MODEL = os.environ.get("QUINTACLE_T11_CLOUD_MODEL", "max:opus")
CARD_SETS = ["local+local", "local+claude", "claude+local", "claude+claude"]
# his exercises -> words that must all appear in one routine exercise (lowercase, hyphens/spaces ignored)
HIS_EXERCISES = {
    "deadlift": ("deadlift",),
    "weighted pull-ups": ("weighted", "pullup"),
    "weighted chin-ups": ("weighted", "chinup"),
    "barbell rows": ("barbell", "row"),
    "bicep curls": ("curl",),
    "face pulls": ("facepull",),
    "cable pull-aparts": ("pullapart",),
}


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    reason = missing_requirements() or missing_max()
    if reason:
        pytest.skip(reason)
    from tests.user.food.meal_checks import his_answers

    c = sandbox_before(tmp_path_factory.mktemp("t11"), chats_from="2026-11-19-1709", cloud=True)

    def chat(model):
        from quintacle_core.nodes.kb import chat as kb_chat

        real = kb_chat._run_anthropic
        kb_chat._run_anthropic = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Max failed; metered API blocked"))
        try:
            r = c.post("/kb/chat", json={"messages": [{"role": "user", "content": PROMPT}], "model": model, "web": False})
        finally:
            kb_chat._run_anthropic = real
        assert r.status_code == 200, r.text[:400]
        return r.json()["reply"]

    s = {"local_answer": chat(LOCAL_MODEL), "claude_answer": chat(CLOUD_MODEL)}
    local, claude = his_answers(CHAT)[:2]
    for name, text, provider in (("local+local", local, "local"), ("local+claude", local, "cloud"),
                                 ("claude+local", claude, "local"), ("claude+claude", claude, "cloud")):
        s[name] = drop(c, text=text.strip(), provider=provider)  # his answer, pasted as text
        e = s[name].get("entries", [])
        print(f"\nT11 {name}: {types(s[name])}; folders: {[x.get('folder') for x in e if x.get('type') == 'kb_entry']}")
    return s


def test_local_vs_claude_comparison(session):
    """Report only."""
    from tests.user.chat_compare import compare

    assert compare("T11", PROMPT, session["local_answer"], session["claude_answer"])["report"].exists()


def _key(name: str) -> str:
    return re.sub(r"[^a-z]", "", (name or "").lower())


@pytest.mark.parametrize("which", CARD_SETS)
def test_routine_has_every_exercise_he_named(session, which):
    routines = [e for e in session[which].get("entries", []) if e.get("type") == "workout_routine"]
    assert routines, types(session[which])
    got = [_key(x) for x in routines[0].get("exercises") or []]
    missing = [ex for ex, words in HIS_EXERCISES.items() if not any(all(w in g for w in words) for g in got)]
    assert not missing, (missing, routines[0].get("exercises"))
